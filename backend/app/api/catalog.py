from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from app.api.schemas import TaxonIn, TaxonOut, TaxonPatch, SeedLotIn, SeedLotOut, SeedLotPatch
from app.core.auth import current_user
from app.db.session import get_db
from app.models import ExperimentMaterial, SeedLot, Taxon, User
from app.services.common import commit_or_conflict, flush_or_conflict, next_code, record, require_entity
from app.services.ordering import taxon_key, material_key


router = APIRouter(tags=["catalog"])


def taxon_snapshot(item: Taxon) -> dict:
    return TaxonOut.model_validate(item).model_dump(mode="json")


def lot_snapshot(item: SeedLot) -> dict:
    return SeedLotOut.model_validate(item).model_dump(mode="json")


@router.get("/taxa", response_model=list[TaxonOut])
def list_taxa(q: str = "", include_inactive: bool = False, db: Session = Depends(get_db), _user: User = Depends(current_user)):
    statement = select(Taxon)
    if q.strip():
        term = f"%{q.strip()}%"
        statement = statement.where(or_(Taxon.code.ilike(term), Taxon.scientific_name.ilike(term), Taxon.common_name.ilike(term)))
    if not include_inactive:
        statement = statement.where(Taxon.is_active.is_(True))
    return sorted(db.scalars(statement.limit(500)).all(), key=taxon_key)


@router.post("/taxa", response_model=TaxonOut, status_code=201)
def create_taxon(data: TaxonIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    item = Taxon(code=next_code(db, Taxon, "SP-"), **data.model_dump())
    db.add(item)
    flush_or_conflict(db)
    record(db, user.id, "create", "Taxon", item.id, None, taxon_snapshot(item))
    commit_or_conflict(db)
    return item


@router.get("/taxa/{item_id}", response_model=TaxonOut)
def get_taxon(item_id: str, db: Session = Depends(get_db), _user: User = Depends(current_user)):
    return require_entity(db, Taxon, item_id)


@router.patch("/taxa/{item_id}", response_model=TaxonOut)
def update_taxon(item_id: str, data: TaxonPatch, db: Session = Depends(get_db), user: User = Depends(current_user)):
    item = require_entity(db, Taxon, item_id)
    before = taxon_snapshot(item)
    for key, value in data.model_dump(exclude_unset=True).items():
        if key in {"scientific_name", "is_active"} and value is None:
            raise HTTPException(422, "学名和使用状态不能为空")
        setattr(item, key, value)
    flush_or_conflict(db)
    record(db, user.id, "update", "Taxon", item.id, before, taxon_snapshot(item))
    commit_or_conflict(db)
    return item


@router.delete("/taxa/{item_id}", status_code=204)
def delete_taxon(item_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    item = require_entity(db, Taxon, item_id)
    if db.scalar(select(SeedLot.id).where(SeedLot.taxon_id == item_id).limit(1)):
        raise HTTPException(409, "该物种已有种子批次或实验记录，不能直接删除。可以将其停用，以保留历史数据。")
    before = taxon_snapshot(item)
    db.delete(item)
    record(db, user.id, "delete", "Taxon", item_id, before, None)
    commit_or_conflict(db)


@router.get("/seed-lots", response_model=list[SeedLotOut])
def list_lots(taxon_id: str | None = None, q: str = "", db: Session = Depends(get_db), _user: User = Depends(current_user)):
    statement = select(SeedLot).join(SeedLot.taxon).options(selectinload(SeedLot.taxon))
    if taxon_id:
        statement = statement.where(SeedLot.taxon_id == taxon_id)
    if q.strip():
        term = f"%{q.strip()}%"
        statement = statement.where(or_(SeedLot.code.ilike(term), SeedLot.source.ilike(term),
                                        Taxon.common_name.ilike(term), Taxon.scientific_name.ilike(term),
                                        Taxon.code.ilike(term), SeedLot.source_code.ilike(term)))
    return sorted(db.scalars(statement.limit(500)).all(), key=lambda lot: material_key(lot.taxon, lot))


@router.post("/seed-lots", response_model=SeedLotOut, status_code=201)
def create_lot(data: SeedLotIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    require_entity(db, Taxon, data.taxon_id)
    item = SeedLot(code=next_code(db, SeedLot, f"LOT-{datetime.now().year}-", 3), **data.model_dump())
    db.add(item)
    flush_or_conflict(db)
    record(db, user.id, "create", "SeedLot", item.id, None, lot_snapshot(item))
    commit_or_conflict(db)
    return item


@router.get("/seed-lots/{item_id}", response_model=SeedLotOut)
def get_lot(item_id: str, db: Session = Depends(get_db), _user: User = Depends(current_user)):
    return require_entity(db, SeedLot, item_id)


@router.patch("/seed-lots/{item_id}", response_model=SeedLotOut)
def update_lot(item_id: str, data: SeedLotPatch, db: Session = Depends(get_db), user: User = Depends(current_user)):
    item = require_entity(db, SeedLot, item_id)
    before = lot_snapshot(item)
    for key, value in data.model_dump(exclude_unset=True).items():
        if key == "is_active" and value is None:
            raise HTTPException(422, "种子批次的使用状态不能为空")
        setattr(item, key, value)
    flush_or_conflict(db)
    record(db, user.id, "update", "SeedLot", item.id, before, lot_snapshot(item))
    commit_or_conflict(db)
    return item


@router.delete("/seed-lots/{item_id}", status_code=204)
def delete_lot(item_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    item = require_entity(db, SeedLot, item_id)
    if db.scalar(select(ExperimentMaterial.id).where(ExperimentMaterial.seed_lot_id == item_id).limit(1)):
        raise HTTPException(409, "该种子批次已经用于实验，不能直接删除。可以将其停用，以保留实验记录。")
    before = lot_snapshot(item)
    db.delete(item)
    record(db, user.id, "delete", "SeedLot", item_id, before, None)
    commit_or_conflict(db)
