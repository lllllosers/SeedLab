"""Preview and atomically import a complete material inventory."""

from datetime import date, datetime, time, timezone
from hashlib import sha256
from io import BytesIO

from fastapi import HTTPException
from openpyxl import load_workbook
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ImportJob, SeedLot, Taxon
from app.services.common import commit_or_conflict, flush_or_conflict, next_code, record


COLUMNS = ("系统物种编号", "中文名", "学名", "科", "属", "生活型", "原始材料编号",
           "来源", "采集/获得日期", "数量（粒）", "物种备注", "种子批次备注")
TAXON_FIELDS = {"中文名": "common_name", "科": "family", "属": "genus",
                "生活型": "life_form", "物种备注": "notes"}
LOT_FIELDS = {"来源": "source", "采集/获得日期": "collected_at",
              "数量（粒）": "quantity", "种子批次备注": "notes"}


def _text(value) -> str | None:
    result = str(value).strip() if value is not None else ""
    return result or None


def _date(value, line: int):
    if value is None or str(value).strip() == "":
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    if isinstance(value, date):
        return datetime.combine(value, time.min)
    try:
        return datetime.fromisoformat(str(value).strip()).replace(tzinfo=None)
    except ValueError as exc:
        raise ValueError(f"第 {line} 行：采集/获得日期请填写有效日期") from exc


def _quantity(value, line: int):
    if value is None or str(value).strip() == "":
        return None
    try:
        number = int(value)
        if isinstance(value, bool) or number < 0 or number > 2**63 - 1 or (
                isinstance(value, float) and value != number):
            raise ValueError
        return number
    except (ValueError, TypeError) as exc:
        raise ValueError(f"第 {line} 行：数量（粒）请填写非负整数或留空") from exc


def parse_file(content: bytes) -> list[dict]:
    if len(content) > 8_000_000:
        raise HTTPException(413, "文件不能超过 8 MB")
    try:
        workbook = load_workbook(BytesIO(content), read_only=True, data_only=True)
        try:
            rows = workbook.active.iter_rows(values_only=True)
            header = [_text(value) or "" for value in next(rows)]
            if header != list(COLUMNS):
                raise ValueError("表头与下载的种子材料模板不一致，请使用最新模板")
            parsed = []
            for line, values in enumerate(rows, start=2):
                if all(value is None or str(value).strip() == "" for value in values):
                    continue
                if len(parsed) >= 500:
                    raise ValueError("一次最多预检 500 行材料")
                raw = dict(zip(COLUMNS, values))
                row = {column: _text(raw.get(column)) for column in COLUMNS}
                row_errors = []
                for column, parser in (("采集/获得日期", _date), ("数量（粒）", _quantity)):
                    try:
                        row[column] = parser(raw.get(column), line)
                    except ValueError as exc:
                        row[column] = None
                        row_errors.append(str(exc))
                row["_errors"] = row_errors
                row["line"] = line
                parsed.append(row)
            if not parsed:
                raise ValueError("文件没有材料数据行，请在模板中填写至少一份材料")
            return parsed
        finally:
            workbook.close()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(422, f"无法读取种子材料文件：{exc}") from exc


def _same_name(value: str | None) -> str:
    return (value or "").strip().casefold()


def _lot_changes(row: dict, lot: SeedLot) -> tuple[list[str], list[str]]:
    fills, conflicts = [], []
    for label, field in LOT_FIELDS.items():
        value = row[label]
        current = getattr(lot, field)
        if value is None:
            continue
        if current is None or current == "":
            fills.append(label)
        elif current != value:
            conflicts.append(label)
    return fills, conflicts


def preview(db: Session, content: bytes) -> dict:
    file_hash = sha256(content).hexdigest()
    already = db.scalar(select(ImportJob.id).where(ImportJob.file_hash == file_hash,
                ImportJob.status == "completed")) is not None
    rows = parse_file(content)
    taxa = list(db.scalars(select(Taxon)))
    lots = list(db.scalars(select(SeedLot)))
    by_code = {item.code: item for item in taxa}
    by_name = {_same_name(item.scientific_name): item for item in taxa}
    results = []
    seen_identity = {}
    for row in rows:
        line = row["line"]
        errors, fills, conflicts = list(row["_errors"]), [], []
        code, sci = row["系统物种编号"], row["学名"]
        taxon = by_code.get(code) if code else by_name.get(_same_name(sci))
        if code and taxon is None:
            errors.append(f"第 {line} 行填写的物种编号 {code} 不存在，请核对")
        if not code and not sci:
            errors.append(f"第 {line} 行：新物种必须填写学名")
        if taxon and sci and _same_name(sci) != _same_name(taxon.scientific_name):
            errors.append(f"第 {line} 行：物种编号与学名不对应，请核对")
        taxon_key = taxon.id if taxon else f"new:{_same_name(sci)}"
        if taxon:
            for label, field in TAXON_FIELDS.items():
                value = row[label]
                current = getattr(taxon, field)
                if value is None:
                    continue
                if current is None or current == "":
                    fills.append(label)
                elif current != value:
                    conflicts.append(label)
        matching_lots = [lot for lot in lots if taxon and lot.taxon_id == taxon.id]
        source_code = row["原始材料编号"]
        exact = [lot for lot in matching_lots if source_code and lot.source_code == source_code]
        candidate = exact[0] if len(exact) == 1 else None
        possible = exact
        candidate_row = None
        status = "new"
        if len(exact) > 1:
            errors.append(f"第 {line} 行：同一物种与原始材料编号对应多个已有批次，请先整理已有数据")
        if candidate:
            lot_fills, lot_conflicts = _lot_changes(row, candidate)
            fills.extend(lot_fills)
            conflicts.extend(lot_conflicts)
            status = "updatable" if fills or conflicts else "registered"
        elif not source_code and matching_lots:
            possible = [lot for lot in matching_lots
                        if (not row["来源"] or lot.source == row["来源"])
                        and (not row["采集/获得日期"] or lot.collected_at == row["采集/获得日期"])]
            candidate = possible[0] if len(possible) == 1 else None
            if possible:
                status = "confirm"
        identity = (taxon_key, source_code) if source_code else (
            taxon_key, row["来源"], row["采集/获得日期"])
        if identity in seen_identity:
            candidate_row = seen_identity[identity]
            status = "confirm"
        else:
            seen_identity[identity] = line
        if errors:
            status = "error"
        results.append({"line": line, "status": status, "taxon_id": taxon.id if taxon else None,
                        "new_taxon": taxon is None, "candidate_lot_id": candidate.id if candidate else None,
                        "candidate_lots": [{"id": lot.id, "code": lot.code, "source_code": lot.source_code,
                                            "source": lot.source, "collected_at": lot.collected_at.isoformat()
                                            if lot.collected_at else None} for lot in possible],
                        "candidate_row": candidate_row, "name": row["中文名"] or sci,
                        "scientific_name": sci or (taxon.scientific_name if taxon else None),
                        "source_code": source_code, "fills": fills, "conflicts": conflicts,
                        "errors": errors})
    return {"file_hash": file_hash, "already_imported": already,
            "rows": results,
            "stats": {"total": len(results), "registered": sum(r["status"] == "registered" for r in results),
                      "new": sum(r["status"] == "new" for r in results),
                      "new_taxa": len({ _same_name(r["scientific_name"]) for r in results if r["new_taxon"] and r["status"] != "error"}),
                      "reused_taxa": sum(not r["new_taxon"] for r in results),
                      "updatable": sum(r["status"] == "updatable" for r in results),
                      "confirm": sum(r["status"] == "confirm" for r in results),
                      "errors": sum(r["status"] == "error" for r in results)}}


def _valid_decision(row: dict, choice: str | None) -> bool:
    if not isinstance(choice, str):
        return False
    if choice == "new":
        return True
    if choice == "reuse":
        return row["candidate_row"] is not None or row["candidate_lot_id"] is not None
    if choice and choice.startswith("reuse-row:"):
        return row["candidate_row"] is not None and choice == f"reuse-row:{row['candidate_row']}"
    if choice and choice.startswith("reuse:"):
        return choice.removeprefix("reuse:") in {lot["id"] for lot in row["candidate_lots"]}
    return False


def confirm(db: Session, content: bytes, filename: str, decisions: dict[str, str], user_id: str) -> dict:
    report = preview(db, content)
    if report["already_imported"]:
        raise HTTPException(409, "这份文件已经成功导入过；请使用更新后的完整清单")
    if report["stats"]["errors"]:
        raise HTTPException(422, "文件仍有错误，请先按预检提示修正后重新上传")
    if any(row["status"] == "confirm" and not _valid_decision(row, decisions.get(str(row["line"])))
           for row in report["rows"]):
        raise HTTPException(422, "请先为所有需要确认的材料选择复用或新增")
    rows = parse_file(content)
    by_code = {item.code: item for item in db.scalars(select(Taxon))}
    by_name = {_same_name(item.scientific_name): item for item in by_code.values()}
    created_by_line = {}
    selected = []
    new_taxa = new_lots = 0
    taxon_next = int(next_code(db, Taxon, "SP-").removeprefix("SP-"))
    lot_prefix = f"LOT-{datetime.now().year}-"
    lot_next = int(next_code(db, SeedLot, lot_prefix, 3).rsplit("-", 1)[1])
    try:
        for row, result in zip(rows, report["rows"]):
            line = row["line"]
            taxon = by_code.get(row["系统物种编号"]) if row["系统物种编号"] else by_name.get(_same_name(row["学名"]))
            if taxon is None:
                taxon = Taxon(code=f"SP-{taxon_next:04d}", scientific_name=row["学名"],
                              **{field: row[label] for label, field in TAXON_FIELDS.items()})
                taxon_next += 1
                db.add(taxon)
                flush_or_conflict(db)
                by_code[taxon.code] = taxon
                by_name[_same_name(taxon.scientific_name)] = taxon
                new_taxa += 1
                record(db, user_id, "import", "Taxon", taxon.id, None, {"code": taxon.code, "line": line})
            else:
                before, after = {}, {}
                for label, field in TAXON_FIELDS.items():
                    value = row[label]
                    if value is not None and not getattr(taxon, field):
                        before[field] = None
                        setattr(taxon, field, value)
                        after[field] = value
                if after:
                    record(db, user_id, "update", "Taxon", taxon.id, before, after)
            decision = decisions.get(str(line))
            lot = db.get(SeedLot, result["candidate_lot_id"]) if result["candidate_lot_id"] else None
            if result["status"] == "confirm":
                if decision and decision.startswith("reuse:"):
                    lot = db.get(SeedLot, decision.removeprefix("reuse:"))
                elif decision and decision.startswith("reuse-row:"):
                    lot = created_by_line.get(int(decision.removeprefix("reuse-row:")))
                elif result["candidate_row"] is not None:
                    lot = created_by_line.get(result["candidate_row"])
            if result["status"] == "new" or (result["status"] == "confirm" and decision == "new"):
                lot = SeedLot(code=f"{lot_prefix}{lot_next:03d}", taxon_id=taxon.id,
                              source_code=row["原始材料编号"],
                              **{field: row[label] for label, field in LOT_FIELDS.items()})
                lot_next += 1
                db.add(lot)
                flush_or_conflict(db)
                new_lots += 1
                selected.append(lot.id)
                record(db, user_id, "import", "SeedLot", lot.id, None, {"code": lot.code, "line": line})
            elif lot is not None:
                before, after = {}, {}
                for label, field in LOT_FIELDS.items():
                    value = row[label]
                    if value is not None and getattr(lot, field) is None:
                        before[field] = None
                        setattr(lot, field, value)
                        after[field] = value.isoformat() if isinstance(value, datetime) else value
                if after:
                    record(db, user_id, "update", "SeedLot", lot.id, before, after)
                if result["status"] == "confirm":
                    selected.append(lot.id)
            else:
                raise HTTPException(422, f"第 {line} 行找不到可复用材料，请改选新增")
            created_by_line[line] = lot
        job = ImportJob(user_id=user_id, filename=filename[:255], status="completed",
                        total_rows=len(rows), successful_rows=len(rows), file_hash=report["file_hash"])
        db.add(job)
        flush_or_conflict(db)
        commit_or_conflict(db)
    except Exception:
        db.rollback()
        raise
    return {"job_id": job.id, "total": len(rows), "new_taxa": new_taxa,
            "new_lots": new_lots, "selected_lot_ids": list(dict.fromkeys(selected))}
