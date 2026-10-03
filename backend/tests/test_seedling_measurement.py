"""Stage 3 public workflow, database semantics, and migration round trip."""

from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from openpyxl import load_workbook
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.core.config import get_settings
from app.db.session import make_engine
from app.services.local_time import local_date, today


def setup_experiment(client, headers, days=(0, 1, 3), replicates=1):
    taxon = client.post("/api/taxa", json={"scientific_name": "Setaria viridis", "common_name": "狗尾草"}, headers=headers).json()
    lot = client.post("/api/seed-lots", json={"taxon_id": taxon["id"], "quantity": 100, "source_code": "SRC-1"}, headers=headers).json()
    response = client.post("/api/experiments/configured", json={"experiment_type": "GER", "name": "幼苗测定试验",
        "protocol": {"seeds_per_dish": 10, "replicate_count": replicates, "observation_period_days": 30,
                     "sampling_rule": "first_germinated", "sample_count": 2, "sample_scope": "per_dish",
                     "germination_criterion": "胚根露出"}, "materials": [{"seed_lot_id": lot["id"]}],
        "dag_days": list(days)}, headers=headers)
    assert response.status_code == 201, response.text
    base = f"/api/experiments/{response.json()['experiment']['id']}"
    assert client.patch(base, json={"status": "ready"}, headers=headers).status_code == 200
    dish = client.post(f"{base}/confirm-numbers", headers=headers).json()["dishes"][0]
    sown = datetime.now(timezone.utc) - timedelta(days=10)
    assert client.post(f"{base}/sowing/batch", json={"dish_ids": [dish["id"]],
        "sown_at": sown.isoformat()}, headers=headers).status_code == 200
    return base, dish, taxon, lot


def observe(client, headers, base, dish, when):
    response = client.post(f"{base}/observations/batch", json={"observed_at": when.isoformat(),
        "entries": [{"dish_id": dish["id"], "new_germinated_count": 1}]}, headers=headers)
    assert response.status_code == 200, response.text
    return client.get(f"{base}/samples").json()[-1]


def payload(task, when, root=0, shoot=0, root_na=False, shoot_na=False):
    return {"sample_id": task["sample_id"], "timepoint_id": task["timepoint_id"],
            "root_length_mm": root, "shoot_length_mm": shoot,
            "root_unavailable": root_na, "shoot_unavailable": shoot_na,
            "measured_at": when.isoformat(), "notes": "现场测量"}


def test_calendar_dag_status_search_and_missing_time(auth_client, tmp_path):
    client, headers = auth_client
    base, dish, taxon, lot = setup_experiment(client, headers, days=(0, 1, 3, 21))
    now = datetime.now(timezone.utc)
    sample = observe(client, headers, base, dish, now - timedelta(days=2))
    tasks = client.get(f"{base}/measurement-tasks").json()
    dashboard = client.get("/api/dashboard").json()["measurement"]
    assert dashboard["overdue_count"] >= 1
    assert dashboard["experiments"][0]["id"] == base.split("/")[-1]
    assert tasks["dag_days"] == [0, 1, 3, 21]
    by_dag = {item["day_after_germination"]: item for item in tasks["tasks"]}
    assert by_dag[0]["status"] == "overdue"
    assert by_dag[21]["status"] == "upcoming"
    assert by_dag[0]["germinated_at"] == sample["germinated_at"]
    assert by_dag[0]["field_number"] == "001"
    for term in ("001", "狗尾草", "Setaria", taxon["code"], lot["code"], "SRC-1", str(sample["sample_number"])):
        assert client.get(f"{base}/measurement-tasks", params={"q": term}).json()["tasks"]
    assert len(client.get(f"{base}/measurement-tasks", params={"status": "pending"}).json()["tasks"]) >= 1
    engine = make_engine(f"sqlite:///{(tmp_path / 'test.db').as_posix()}")
    with engine.begin() as conn:
        conn.execute(text("UPDATE seedling_samples SET germinated_at=NULL WHERE id=:id"), {"id": sample["id"]})
    engine.dispose()
    result = client.get(f"{base}/measurement-tasks").json()
    assert result["summary"]["unschedulable_count"] == 4
    assert all(item["status"] == "unschedulable" for item in result["tasks"])


def test_local_day_boundary_and_germination_basis(auth_client):
    client, headers = auth_client
    base, dish, _, _ = setup_experiment(client, headers, days=(0, 1))
    local_midnight_utc = datetime.combine(today(), datetime.min.time(), timezone.utc) - timedelta(hours=8)
    when = local_midnight_utc + timedelta(minutes=20)
    observe(client, headers, base, dish, when)
    tasks = client.get(f"{base}/measurement-tasks").json()["tasks"]
    assert tasks[0]["scheduled_date"] == local_date(when).isoformat()
    assert {item["scheduled_date"] for item in tasks} == {today().isoformat(), (today() + timedelta(days=1)).isoformat()}
    assert any(item["status"] == "due_today" for item in tasks)
    assert any(item["status"] == "upcoming" for item in tasks)
    assert tasks[0]["scheduled_date"] != local_date(datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
    day0 = next(item for item in tasks if item["day_after_germination"] == 0)
    day1 = next(item for item in tasks if item["day_after_germination"] == 1)
    assert client.post(f"{base}/measurements", json=payload(day0, datetime.now(timezone.utc)), headers=headers).status_code == 201
    assert client.post(f"{base}/measurements", json=payload(day1, datetime.now(timezone.utc)), headers=headers).status_code == 422


def test_field_number_keeps_replicate_suffix_before_other_dishes_have_samples(auth_client):
    client, headers = auth_client
    base, dish, _, _ = setup_experiment(client, headers, days=(0,), replicates=2)
    observe(client, headers, base, dish, datetime.now(timezone.utc) - timedelta(days=1))
    task = client.get(f"{base}/measurement-tasks").json()["tasks"][0]
    assert task["field_number"] == "001-1"
    assert client.get(f"{base}/measurement-worklist", params={"q": "001-1"}).json()["total_materials"] == 1


def test_create_correct_clear_position_and_export(auth_client):
    client, headers = auth_client
    base, dish, _, _ = setup_experiment(client, headers, days=(0, 3))
    when = datetime.now(timezone.utc) - timedelta(days=5)
    sample = observe(client, headers, base, dish, when)
    tasks = client.get(f"{base}/measurement-tasks").json()["tasks"]
    dag0 = next(item for item in tasks if item["day_after_germination"] == 0)
    dag3 = next(item for item in tasks if item["day_after_germination"] == 3)
    now = datetime.now(timezone.utc)
    assert client.post(f"{base}/measurements", json=payload(dag0, when - timedelta(days=1)), headers=headers).status_code == 422
    for root, shoot, rna, sna in ((-1, 1, False, False), (None, 1, False, False), (1, None, False, False), (1, 1, True, False)):
        assert client.post(f"{base}/measurements", json=payload(dag0, now, root, shoot, rna, sna), headers=headers).status_code == 422
    assert client.post(f"{base}/measurements", json={**payload(dag0, now), "measured_at": now.replace(tzinfo=None).isoformat()}, headers=headers).status_code == 422
    created = client.post(f"{base}/measurements", json=payload(dag0, now, root=0, shoot=None, shoot_na=True), headers=headers)
    assert created.status_code == 201, created.text
    item = created.json()
    assert item["root_length_mm"] == 0 and item["shoot_unavailable"]
    assert client.post(f"{base}/measurements", json=payload(dag0, now), headers=headers).status_code == 409
    assert client.get(f"{base}/measurement-tasks").json()["summary"]["completed_today_count"] == 1
    completed = next(row for row in client.get(f"{base}/measurement-tasks").json()["tasks"] if row["measurement_id"] == item["id"])
    assert completed["delay_days"] >= 5 and completed["status"] == "completed"
    assert client.get(f"{base}/measurement-history/{dag0['material_id']}").json()["dag_days"] == [0, 3]
    updated = client.patch(f"{base}/measurements/{item['id']}", json={"root_length_mm": 5, "shoot_length_mm": 2,
        "shoot_unavailable": False}, headers=headers)
    assert updated.status_code == 200, updated.text
    assert updated.json()["root_length_mm"] == 5
    assert client.patch(f"{base}/measurements/{item['id']}", json={}, headers=headers).status_code == 200
    assert client.patch(f"{base}/samples/{sample['id']}/position", json={"position_label": "托盘2-15"}, headers=headers).status_code == 200
    assert client.patch(f"{base}/samples/{sample['id']}/position", json={"germinated_at": now.isoformat()}, headers=headers).status_code == 422
    assert client.get(f"{base}/samples").json()[0]["germinated_at"] == sample["germinated_at"]
    assert client.get(f"{base}/measurement-tasks", params={"q": "托盘2-15"}).json()["tasks"]
    audit = client.get("/api/audit-logs", params={"page_size": 100}).json()["items"]
    assert sum(row["entity_type"] == "SeedlingMeasurement" and row["action"] == "update" for row in audit) == 1
    assert any(row["entity_type"] == "SeedlingSample" and row["before"] == {"position_label": None} for row in audit)
    # Workbook includes a completed zero/NA stage and an unmeasured dynamic DAG column.
    stream = client.post("/api/export/experiments/workbook.xlsx", json={"experiment_ids": [base.split('/')[-1]]}, headers=headers)
    assert stream.status_code == 200, stream.text[:200]
    book = load_workbook(BytesIO(stream.content), data_only=True)
    assert "根长（mm）" in [cell.value for cell in book["04_幼苗测定长表"][1]]
    assert "RL3" in [cell.value for cell in book["05_幼苗测定宽表"][1]]
    book.close()
    assert client.delete(f"{base}/measurements/{item['id']}", headers=headers).status_code == 204
    assert next(row for row in client.get(f"{base}/measurement-tasks").json()["tasks"] if row["day_after_germination"] == 0)["measurement_id"] is None
    assert any(row["entity_type"] == "SeedlingMeasurement" and row["action"] == "delete" for row in client.get("/api/audit-logs", params={"page_size": 100}).json()["items"])


def test_completed_allows_correction_not_creation_or_deletion(auth_client, tmp_path):
    client, headers = auth_client
    base, dish, _, _ = setup_experiment(client, headers, days=(0, 1))
    observe(client, headers, base, dish, datetime.now(timezone.utc) - timedelta(days=3))
    tasks = client.get(f"{base}/measurement-tasks").json()["tasks"]
    item = client.post(f"{base}/measurements", json=payload(tasks[0], datetime.now(timezone.utc)), headers=headers).json()
    assert client.post(f"{base}/measurements", json=payload(tasks[1], datetime.now(timezone.utc)), headers=headers).status_code == 201
    # Existing completed data keeps its correction policy, independently of planned days.
    engine = make_engine(f"sqlite:///{(tmp_path / 'test.db').as_posix()}")
    with engine.begin() as conn:
        conn.execute(text("UPDATE experiments SET status='completed' WHERE id=:id"),
                     {"id": base.split('/')[-1]})
    engine.dispose()
    assert client.get(base).json()["status"] == "completed"
    assert client.post(f"{base}/measurements", json=payload(tasks[1], datetime.now(timezone.utc)), headers=headers).status_code == 409
    assert client.patch(f"{base}/measurements/{item['id']}", json={"notes": "复核完成"}, headers=headers).status_code == 200
    assert client.delete(f"{base}/measurements/{item['id']}", headers=headers).status_code == 409


def test_export_keeps_zero_na_and_unmeasured_blank(auth_client):
    client, headers = auth_client
    base, dish, _, _ = setup_experiment(client, headers, days=(0, 21))
    observe(client, headers, base, dish, datetime.now(timezone.utc) - timedelta(days=2))
    dag0 = next(row for row in client.get(f"{base}/measurement-tasks").json()["tasks"] if row["day_after_germination"] == 0)
    created = client.post(f"{base}/measurements", json=payload(dag0, datetime.now(timezone.utc),
        root=0, shoot=None, shoot_na=True), headers=headers)
    assert created.status_code == 201, created.text
    workbook = load_workbook(BytesIO(client.post("/api/export/experiments/workbook.xlsx",
        json={"experiment_ids": [base.split('/')[-1]]}, headers=headers).content), data_only=True)
    long_rows = list(workbook["04_幼苗测定长表"].values)
    wide_rows = list(workbook["05_幼苗测定宽表"].values)
    assert len(long_rows) == 5
    long = dict(zip(long_rows[0], long_rows[1]))
    assert long["根长（mm）"] == 0
    assert long["苗长（mm）"] is None and long["苗长状态"] == "无法测量"
    assert long["延迟天数"] >= 2
    wide = dict(zip(wide_rows[0], wide_rows[1]))
    assert wide["RL0"] == 0 and wide["SL0"] == "NA"
    assert wide["RL21"] is None and wide["SL21"] is None
    workbook.close()


def test_database_constraints_and_migration_roundtrip(tmp_path, monkeypatch):
    url = f"sqlite:///{(tmp_path / 'migration.db').as_posix()}"
    monkeypatch.setenv("SEEDLAB_DATABASE_URL", url)
    get_settings.cache_clear()
    backend = Path(__file__).resolve().parents[1]
    config = Config(str(backend / "alembic.ini"))
    config.set_main_option("script_location", str(backend / "alembic"))
    command.upgrade(config, "0b6111724c00")
    engine = make_engine(url)
    stamp = "2026-09-01 00:00:00"
    ids = {name: str(uuid4()) for name in ("experiment", "taxon", "lot", "material", "dish", "sample", "point", "measurement")}
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO experiments(id,created_at,code,name,status) VALUES (:id,:t,'EXP-1','迁移验证','active')"), {"id": ids["experiment"], "t": stamp})
        conn.execute(text("INSERT INTO taxa(id,created_at,code,scientific_name,is_active) VALUES (:id,:t,'SP-1','Poa annua',1)"), {"id": ids["taxon"], "t": stamp})
        conn.execute(text("INSERT INTO seed_lots(id,created_at,code,taxon_id,is_active) VALUES (:id,:t,'LOT-1',:taxon,1)"), {"id": ids["lot"], "t": stamp, "taxon": ids["taxon"]})
        conn.execute(text("INSERT INTO experiment_materials(id,created_at,experiment_id,seed_lot_id,display_order) VALUES (:id,:t,:exp,:lot,1)"), {"id": ids["material"], "t": stamp, "exp": ids["experiment"], "lot": ids["lot"]})
        conn.execute(text("INSERT INTO germination_dishes(id,created_at,material_id,code,replicate_no,label,seed_count) VALUES (:id,:t,:material,'D1',1,'R1',5)"), {"id": ids["dish"], "t": stamp, "material": ids["material"]})
        conn.execute(text("INSERT INTO seedling_samples(id,created_at,dish_id,sample_number) VALUES (:id,:t,:dish,1)"), {"id": ids["sample"], "t": stamp, "dish": ids["dish"]})
        conn.execute(text("INSERT INTO measurement_timepoints(id,created_at,experiment_id,day_after_germination) VALUES (:id,:t,:exp,0)"), {"id": ids["point"], "t": stamp, "exp": ids["experiment"]})
        conn.execute(text("INSERT INTO seedling_measurements(id,created_at,sample_id,timepoint_id,root_length_mm,shoot_length_mm) VALUES (:id,:t,:sample,:point,0,NULL)"), {"id": ids["measurement"], "t": stamp, "sample": ids["sample"], "point": ids["point"]})
    engine.dispose()
    with pytest.raises(RuntimeError, match="人工核对"):
        command.upgrade(config, "head")
    engine = make_engine(url)
    with engine.begin() as conn:
        conn.execute(text("UPDATE seedling_measurements SET shoot_length_mm=2, measured_at=:t WHERE id=:id"), {"t": stamp, "id": ids["measurement"]})
    engine.dispose()
    command.upgrade(config, "head")
    engine = make_engine(url)
    with engine.connect() as conn:
        assert conn.exec_driver_sql("PRAGMA foreign_key_check").all() == []
        assert conn.exec_driver_sql("SELECT root_unavailable FROM seedling_measurements").scalar() == 0
    engine.dispose()
    command.check(config)
    command.downgrade(config, "0b6111724c00")
    command.upgrade(config, "head")
    engine = make_engine(url)
    with engine.connect() as conn:
        assert conn.exec_driver_sql("SELECT version_num FROM alembic_version").scalar() == "d2e7a46b910c"
        assert conn.exec_driver_sql("PRAGMA foreign_key_check").all() == []
    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.execute(text("UPDATE seedling_measurements SET root_length_mm=NULL, root_unavailable=0"))
    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.execute(text("UPDATE seedling_measurements SET root_length_mm=1, root_unavailable=1"))
    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.execute(text("UPDATE seedling_measurements SET shoot_length_mm=NULL, shoot_unavailable=0"))
    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.execute(text("UPDATE seedling_measurements SET measured_at=NULL"))
    with engine.begin() as conn:
        conn.execute(text("UPDATE seedling_measurements SET root_length_mm=NULL, root_unavailable=1"))
    engine.dispose()
    with pytest.raises(RuntimeError, match="不能保存这些事实"):
        command.downgrade(config, "0b6111724c00")
    get_settings.cache_clear()
