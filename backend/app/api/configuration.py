from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.api.schemas import ConfiguredExperimentInput, DagInput, MaterialInput, MaterialOrderInput, MaterialPatch, ProtocolInput
from app.core.auth import current_user
from app.db.session import get_db
from app.models import Experiment, SeedLot, Taxon, User
from app.services import experiment_config as design
from app.services.common import require_entity


router = APIRouter(prefix="/experiments", tags=["experiment configuration"])


@router.get("/available-seed-lots")
def available_seed_lots(q: str = "", taxon_id: str | None = None, db: Session = Depends(get_db), _user: User = Depends(current_user)):
    query = select(SeedLot, Taxon).join(Taxon, SeedLot.taxon_id == Taxon.id).where(
        SeedLot.is_active.is_(True), Taxon.is_active.is_(True))
    if taxon_id:
        query = query.where(Taxon.id == taxon_id)
    if q.strip():
        term = f"%{q.strip()}%"
        query = query.where(or_(Taxon.scientific_name.ilike(term), Taxon.common_name.ilike(term),
                                Taxon.code.ilike(term), SeedLot.code.ilike(term), SeedLot.source.ilike(term)))
    return [{"id": lot.id, "code": lot.code, "taxon_id": taxon.id, "taxon_name": taxon.scientific_name,
             "source": lot.source, "quantity": lot.quantity} for lot, taxon in db.execute(query.order_by(Taxon.scientific_name, SeedLot.code).limit(500))]


@router.post("/estimate")
def estimate(data: ConfiguredExperimentInput, db: Session = Depends(get_db), _user: User = Depends(current_user)):
    return design.preview(data, db)


@router.post("/configured", status_code=201)
def create_configured(data: ConfiguredExperimentInput, db: Session = Depends(get_db), user: User = Depends(current_user)):
    return design.create_configured(db, data, user.id)


@router.get("/{item_id}/configuration")
def get_configuration(item_id: str, db: Session = Depends(get_db), _user: User = Depends(current_user)):
    return design.configuration(db, item_id)


@router.get("/{item_id}/workload")
def get_workload(item_id: str, db: Session = Depends(get_db), _user: User = Depends(current_user)):
    data = design.configuration(db, item_id)
    if data["workload"] is None:
        raise HTTPException(422, "请先配置默认实验方案与材料")
    return data["workload"]


@router.put("/{item_id}/protocol")
def put_protocol(item_id: str, data: ProtocolInput, db: Session = Depends(get_db), user: User = Depends(current_user)):
    return design.put_protocol(db, item_id, data, user.id)


@router.post("/{item_id}/materials", status_code=201)
def add_material(item_id: str, data: MaterialInput, db: Session = Depends(get_db), user: User = Depends(current_user)):
    return design.add_material(db, item_id, data, user.id)


@router.patch("/{item_id}/materials/{material_id}")
def update_material(item_id: str, material_id: str, data: MaterialPatch,
                    db: Session = Depends(get_db), user: User = Depends(current_user)):
    return design.update_material(db, item_id, material_id, data, user.id)


@router.delete("/{item_id}/materials/{material_id}", status_code=204)
def remove_material(item_id: str, material_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    design.remove_material(db, item_id, material_id, user.id)


@router.put("/{item_id}/materials/order")
def reorder_materials(item_id: str, data: MaterialOrderInput, db: Session = Depends(get_db), user: User = Depends(current_user)):
    return design.reorder_materials(db, item_id, data.material_ids, user.id)


@router.put("/{item_id}/dag")
def replace_days(item_id: str, data: DagInput, db: Session = Depends(get_db), user: User = Depends(current_user)):
    return design.replace_days(db, item_id, data.days, user.id)


@router.post("/{item_id}/dag", status_code=201)
def add_day(item_id: str, day_after_germination: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    current = [item.day_after_germination for item in design.days_for(db, require_entity(db, Experiment, item_id).id)]
    return design.replace_days(db, item_id, current + [day_after_germination], user.id)


@router.delete("/{item_id}/dag/{day_after_germination}", status_code=204)
def remove_day(item_id: str, day_after_germination: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    current = [item.day_after_germination for item in design.days_for(db, require_entity(db, Experiment, item_id).id)]
    if day_after_germination not in current:
        raise HTTPException(404, "DAG 时间点不存在")
    design.replace_days(db, item_id, [day for day in current if day != day_after_germination], user.id)
