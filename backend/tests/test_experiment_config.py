from datetime import date
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.session import make_engine
from app.models import ExperimentMaterial, ExperimentProtocol


def make_lot(client, headers, name="Setaria viridis"):
    taxon = client.post("/api/taxa", json={"scientific_name": name}, headers=headers).json()
    lot = client.post("/api/seed-lots", json={"taxon_id": taxon["id"], "quantity": 100}, headers=headers).json()
    return taxon, lot


def design(lot_id, **changes):
    data = {
        "name": "可配置萌发试验", "planned_start_date": "2026-10-01",
        "protocol": {"seeds_per_dish": 20, "replicate_count": 3, "observation_period_days": 14,
                     "sampling_rule": "first_germinated", "sample_count": 5, "sample_scope": "per_dish",
                     "germination_criterion": "胚根可见"},
        "materials": [{"seed_lot_id": lot_id}], "dag_days": [7, 0, 3],
    }
    data.update(changes)
    return data


def test_configured_creation_defaults_and_workload(auth_client, tmp_path):
    client, headers = auth_client
    taxon, lot = make_lot(client, headers)
    assert client.get("/api/experiments/available-seed-lots", params={"q": "Setaria"}).json()[0]["id"] == lot["id"]
    response = client.post("/api/experiments/configured", json=design(lot["id"]), headers=headers)
    assert response.status_code == 201, response.text
    config = response.json()
    assert config["experiment"]["owner_id"]
    assert config["dag_days"] == [0, 3, 7]
    assert config["materials"][0]["taxon_id"] == taxon["id"]
    assert config["materials"][0]["taxon_common_name"] is None
    assert config["materials"][0]["taxon_scientific_name"] == "Setaria viridis"
    assert config["materials"][0]["taxon_code"] == taxon["code"]
    assert config["materials"][0]["effective_seeds_per_dish"] == 20
    assert config["workload"] == {
        "material_count": 1, "estimated_dish_count": 3, "estimated_seed_count": 60,
        "estimated_sample_count": 15, "estimated_measurement_count": 45,
        "estimated_latest_finish_date": "2026-10-22",
    }
    experiment_id = config["experiment"]["id"]
    assert client.get(f"/api/experiments/{experiment_id}/configuration").json()["workload"] == config["workload"]
    assert client.get(f"/api/experiments/{experiment_id}/workload").json() == config["workload"]
    engine = make_engine(f"sqlite:///{(tmp_path / 'test.db').as_posix()}")
    with engine.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM germination_dishes")).scalar() == 0
        assert conn.execute(text("SELECT COUNT(*) FROM seedling_samples")).scalar() == 0
    engine.dispose()


def test_protocol_created_for_existing_draft(auth_client):
    client, headers = auth_client
    experiment = client.post("/api/experiments", json={"name": "旧草稿实验"}, headers=headers).json()
    path = f"/api/experiments/{experiment['id']}"
    _, lot = make_lot(client, headers)
    assert client.put(f"{path}/protocol", json=design(lot['id'])["protocol"], headers=headers).status_code == 200
    added = client.post(f"{path}/materials", json={"seed_lot_id": lot["id"]}, headers=headers)
    assert added.status_code == 201
    assert client.put(f"{path}/dag", json={"days": [2, 5]}, headers=headers).json() == [2, 5]
    assert client.get(f"{path}/workload").json()["estimated_dish_count"] == 3


def test_protocol_update_override_and_sample_scopes(auth_client):
    client, headers = auth_client
    _, lot = make_lot(client, headers)
    created = client.post("/api/experiments/configured", json=design(lot["id"]), headers=headers).json()
    path = f"/api/experiments/{created['experiment']['id']}"
    material_id = created["materials"][0]["id"]
    updated = client.patch(f"{path}/materials/{material_id}", json={"seeds_per_dish_override": 10,
              "replicate_count_override": 2, "sample_count_override": 8}, headers=headers)
    assert updated.status_code == 200, updated.text
    assert updated.json()["effective_replicate_count"] == 2
    assert client.get(f"{path}/workload").json()["estimated_sample_count"] == 16
    protocol = {**design(lot["id"])["protocol"], "sample_scope": "per_material", "sample_count": 9}
    response = client.put(f"{path}/protocol", json=protocol, headers=headers)
    assert response.status_code == 200, response.text
    assert client.get(f"{path}/workload").json()["estimated_sample_count"] == 8
    assert client.get(f"{path}/workload").json()["estimated_seed_count"] == 20


def test_material_add_duplicate_order_remove_and_inactive(auth_client):
    client, headers = auth_client
    _, first = make_lot(client, headers)
    _, second = make_lot(client, headers, "Poa annua")
    created = client.post("/api/experiments/configured", json=design(first["id"]), headers=headers).json()
    path = f"/api/experiments/{created['experiment']['id']}"
    assert client.post(f"{path}/materials", json={"seed_lot_id": first["id"]}, headers=headers).status_code == 409
    second_material = client.post(f"{path}/materials", json={"seed_lot_id": second["id"]}, headers=headers)
    assert second_material.status_code == 201
    ids = [second_material.json()["id"], created["materials"][0]["id"]]
    assert client.put(f"{path}/materials/order", json={"material_ids": ids}, headers=headers).status_code == 409
    assert client.get(f"{path}/configuration").json()["materials"][0]["seed_lot_id"] == second["id"]
    assert client.delete(f"{path}/materials/{ids[0]}", headers=headers).status_code == 204
    assert client.get(f"{path}/workload").json()["material_count"] == 1
    client.patch(f"/api/seed-lots/{second['id']}", json={"is_active": False}, headers=headers)
    assert client.post(f"{path}/materials", json={"seed_lot_id": second["id"]}, headers=headers).status_code == 422
    assert all(item["id"] != second["id"] for item in client.get("/api/experiments/available-seed-lots").json())


@pytest.mark.parametrize("protocol_change,override,expected", [
    ({"seeds_per_dish": 0}, {}, 422),
    ({"replicate_count": 0}, {}, 422),
    ({"observation_period_days": 0}, {}, 422),
    ({"sample_count": 0}, {}, 422),
    ({"sample_count": 21}, {}, 422),
    ({"sample_scope": "per_material", "sample_count": 61}, {}, 422),
    ({}, {"seeds_per_dish_override": 4, "sample_count_override": 5}, 422),
    ({"sampling_rule": "random"}, {}, 422),
])
def test_invalid_protocol_and_effective_capacity(auth_client, protocol_change, override, expected):
    client, headers = auth_client
    _, lot = make_lot(client, headers)
    data = design(lot["id"])
    data["protocol"].update(protocol_change)
    data["materials"][0].update(override)
    response = client.post("/api/experiments/configured", json=data, headers=headers)
    assert response.status_code == expected


def test_dynamic_dag_and_active_protection(auth_client):
    client, headers = auth_client
    _, lot = make_lot(client, headers)
    created = client.post("/api/experiments/configured", json=design(lot["id"]), headers=headers).json()
    path = f"/api/experiments/{created['experiment']['id']}"
    assert client.put(f"{path}/dag", json={"days": [-1, 3]}, headers=headers).status_code == 422
    assert client.put(f"{path}/dag", json={"days": [3, 3]}, headers=headers).status_code == 422
    assert client.put(f"{path}/dag", json={"days": [14, 1, 5]}, headers=headers).json() == [1, 5, 14]
    assert client.post(f"{path}/dag", params={"day_after_germination": 10}, headers=headers).json() == [1, 5, 10, 14]
    assert client.delete(f"{path}/dag/5", headers=headers).status_code == 204
    assert client.patch(path, json={"status": "active"}, headers=headers).status_code == 409
    assert client.patch(path, json={"status": "ready"}, headers=headers).status_code == 200
    assert client.put(f"{path}/dag", json={"days": []}, headers=headers).status_code == 422
    assert client.delete(f"{path}/materials/{created['materials'][0]['id']}", headers=headers).status_code == 422
    assert client.put(f"{path}/dag", json={"days": [0, 2, 8]}, headers=headers).json() == [0, 2, 8]
    assert client.patch(path, json={"status": "active"}, headers=headers).status_code == 409
    numbered = client.post(f"{path}/confirm-numbers", headers=headers)
    assert numbered.status_code == 200
    assert client.post(f"{path}/sowing/batch", headers=headers, json={
        "sown_at": "2026-10-01T08:00:00+08:00",
        "dish_ids": [dish["id"] for dish in numbered.json()["dishes"]]}).status_code == 200
    assert client.put(f"{path}/dag", json={"days": [3]}, headers=headers).status_code == 409
    assert client.delete(f"{path}/materials/{created['materials'][0]['id']}", headers=headers).status_code == 409
    assert client.patch(f"{path}/materials/{created['materials'][0]['id']}", json={"replicate_count_override": 2}, headers=headers).status_code == 409
    assert client.put(f"{path}/materials/order", json={"material_ids": [created['materials'][0]['id']]}, headers=headers).status_code == 409
    assert client.put(f"{path}/protocol", json=design(lot["id"])["protocol"], headers=headers).status_code == 409
    assert client.patch(path, json={"description": "进行中的备注"}, headers=headers).status_code == 200


def test_stage1_migration_round_trip_preserves_data(client, tmp_path):
    url = f"sqlite:///{(tmp_path / 'test.db').as_posix()}"
    login = client.post("/api/auth/login", json={"username": "admin", "password": "test-password-123"}).json()
    headers = {"X-CSRF-Token": login["csrf_token"]}
    _, lot = make_lot(client, headers)
    experiment = client.post("/api/experiments", json={"name": "迁移保留实验"}, headers=headers).json()
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    config.set_main_option("script_location", str(Path(__file__).resolve().parents[1] / "alembic"))
    engine = make_engine(url)
    with Session(engine) as db:
        db.add_all([ExperimentProtocol(experiment_id=experiment["id"], seeds_per_dish=12),
                    ExperimentMaterial(experiment_id=experiment["id"], seed_lot_id=lot["id"], display_order=0)])
        db.commit()
    with engine.connect() as conn:
        assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar() == "c6d91f28a405"
        assert "seeds_per_dish" in {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(experiment_protocols)")}
    engine.dispose()
    command.downgrade(config, "9456099da4fd")
    engine = make_engine(url)
    with engine.connect() as conn:
        assert "seed_count_per_dish" in {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(experiment_protocols)")}
        assert "display_order" not in {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(experiment_materials)")}
        assert conn.execute(text("SELECT seed_count_per_dish FROM experiment_protocols WHERE experiment_id=:id"), {"id": experiment["id"]}).scalar() == 12
        assert conn.exec_driver_sql("PRAGMA foreign_key_check").all() == []
    engine.dispose()
    command.upgrade(config, "head")
    engine = make_engine(url)
    with engine.connect() as conn:
        assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar() == "c6d91f28a405"
        assert conn.execute(text("SELECT seeds_per_dish FROM experiment_protocols WHERE experiment_id=:id"), {"id": experiment["id"]}).scalar() == 12
        assert conn.execute(text("SELECT display_order FROM experiment_materials WHERE experiment_id=:id"), {"id": experiment["id"]}).scalar() == 0
        assert conn.exec_driver_sql("PRAGMA foreign_key_check").all() == []
    engine.dispose()
