from datetime import datetime, timezone
import subprocess
import sys
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import make_engine
from app.models import Experiment, ExperimentMaterial, GerminationDish, GerminationObservation, MeasurementTimepoint, SeedlingMeasurement, SeedlingSample, SeedLot, Taxon
from app.version import VERSION


def test_migration_and_sqlite_settings(client: TestClient, tmp_path):
    assert client.get("/api/health").json()["version"] == VERSION
    engine = make_engine(f"sqlite:///{(tmp_path / 'test.db').as_posix()}")
    with engine.connect() as connection:
        tables = {row[0] for row in connection.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))}
        assert {"users", "taxa", "seed_lots", "experiments", "germination_observations", "seedling_measurements", "audit_logs", "import_jobs"} <= tables
        assert connection.exec_driver_sql("PRAGMA journal_mode").scalar().lower() == "wal"
        assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar() == "d2e7a46b910c"
        timepoint_columns = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(measurement_timepoints)")}
        sample_columns = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(seedling_samples)")}
        assert "day_after_germination" in timepoint_columns
        assert "day_after_sowing" not in timepoint_columns
        assert "germinated_at" in sample_columns
    engine.dispose()


def test_authentication_csrf_and_cookie(client: TestClient):
    assert client.get("/api/taxa").status_code == 401
    assert client.post("/api/auth/login", json={"username": "admin", "password": "wrong"}).status_code == 401
    response = client.post("/api/auth/login", json={"username": "admin", "password": "test-password-123"})
    assert response.status_code == 200
    assert "httponly" in response.headers["set-cookie"].lower()
    assert client.get("/api/auth/me").json()["user"]["is_admin"] is True
    assert client.post("/api/taxa", json={"scientific_name": "Test plant"}).status_code == 403
    csrf = response.json()["csrf_token"]
    assert client.post("/api/auth/logout", headers={"X-CSRF-Token": csrf}).status_code == 204
    assert client.get("/api/auth/me").status_code == 401


def test_taxon_crud_and_audit(auth_client):
    client, headers = auth_client
    created = client.post("/api/taxa", json={"scientific_name": "Arabidopsis thaliana", "common_name": "拟南芥"}, headers=headers)
    assert created.status_code == 201
    item = created.json()
    assert item["code"] == "SP-0001"
    assert client.get(f"/api/taxa/{item['id']}").json()["common_name"] == "拟南芥"
    assert len(client.get("/api/taxa", params={"q": "拟南"}).json()) == 1
    updated = client.patch(f"/api/taxa/{item['id']}", json={"is_active": False}, headers=headers)
    assert updated.status_code == 200
    assert client.get("/api/taxa").json() == []
    assert len(client.get("/api/taxa", params={"include_inactive": True}).json()) == 1
    assert client.patch(f"/api/taxa/{item['id']}", json={"is_active": True}, headers=headers).status_code == 200
    assert client.delete(f"/api/taxa/{item['id']}", headers=headers).status_code == 204
    assert client.get(f"/api/taxa/{item['id']}").status_code == 404
    assert [entry["action"] for entry in client.get("/api/audit-logs", params={"page_size": 100}).json()["items"]] == ["delete", "update", "update", "create"]


def test_taxon_unique_and_seed_lot_relationship(auth_client):
    client, headers = auth_client
    taxon = client.post("/api/taxa", json={"scientific_name": "Poa annua"}, headers=headers).json()
    assert client.post("/api/taxa", json={"scientific_name": "Poa annua"}, headers=headers).status_code == 409
    lot = client.post("/api/seed-lots", json={"taxon_id": taxon["id"], "quantity": 0}, headers=headers)
    assert lot.status_code == 201
    assert lot.json()["quantity"] == 0
    assert len(client.get("/api/seed-lots", params={"taxon_id": taxon["id"]}).json()) == 1
    assert client.delete(f"/api/taxa/{taxon['id']}", headers=headers).status_code == 409


def test_experiment_crud_and_dashboard(auth_client):
    client, headers = auth_client
    created = client.post("/api/experiments", json={"experiment_type": "GER", "name": "萌发温度试验"}, headers=headers)
    assert created.status_code == 201
    item = created.json()
    assert item["code"].startswith("GER-")
    assert item["status"] == "draft"
    updated = client.patch(f"/api/experiments/{item['id']}", json={"description": "设计草稿"}, headers=headers)
    assert updated.status_code == 200 and updated.json()["description"] == "设计草稿"
    assert client.get("/api/dashboard").json()["active_experiments"] == 0
    assert len(client.get("/api/experiments", params={"q": "萌发"}).json()) == 1
    assert client.delete(f"/api/experiments/{item['id']}", headers=headers).status_code == 204
    assert client.get("/api/dashboard").json()["experiments"] == 0


def test_users_admin_only(auth_client):
    client, headers = auth_client
    created = client.post("/api/users", json={"username": "member", "display_name": "成员", "password": "member-password-123"}, headers=headers)
    assert created.status_code == 201 and created.json()["is_admin"] is False
    member = TestClient(client.app)
    login = member.post("/api/auth/login", json={"username": "member", "password": "member-password-123"})
    assert login.status_code == 200
    assert member.get("/api/users").status_code == 403
    member.close()


def test_zero_is_fact_and_null_is_missing(client: TestClient, tmp_path):
    engine = make_engine(f"sqlite:///{(tmp_path / 'test.db').as_posix()}")
    with Session(engine) as db:
        taxon = Taxon(code="SP-0001", scientific_name="Setaria viridis")
        db.add(taxon)
        db.flush()
        lot = SeedLot(code="LOT-2026-001", taxon_id=taxon.id, quantity=0)
        experiment = Experiment(code="EXP-2026-001", name="测量约束")
        db.add_all([lot, experiment])
        db.flush()
        material = ExperimentMaterial(experiment_id=experiment.id, seed_lot_id=lot.id)
        timepoint = MeasurementTimepoint(experiment_id=experiment.id, day_after_germination=0)
        db.add_all([material, timepoint])
        db.flush()
        dish = GerminationDish(material_id=material.id, code="EXP-2026-001-M001-R01", replicate_no=1, label="A1", seed_count=10)
        db.add(dish)
        db.flush()
        germinated_at = datetime(2026, 9, 28, 8, tzinfo=timezone.utc)
        sample = SeedlingSample(dish_id=dish.id, sample_number=1, germinated_at=germinated_at)
        observation = GerminationObservation(dish_id=dish.id, observed_at=datetime(2026, 9, 28, 9, tzinfo=timezone.utc), new_germinated_count=0)
        db.add_all([sample, observation])
        db.flush()
        measurement = SeedlingMeasurement(sample_id=sample.id, timepoint_id=timepoint.id, root_length_mm=0,
                                          shoot_length_mm=None, shoot_unavailable=True,
                                          measured_at=datetime(2026, 9, 29, tzinfo=timezone.utc))
        db.add(measurement)
        db.commit()
        assert observation.new_germinated_count == 0
        assert measurement.root_length_mm == 0
        assert measurement.shoot_length_mm is None
        assert lot.quantity == 0
        experiment_id = experiment.id
        sample_id = sample.id
    with Session(engine) as db:
        stored = db.get(SeedlingSample, sample_id)
        assert stored is not None and stored.germinated_at is not None
        assert stored.germinated_at.replace(tzinfo=timezone.utc) == germinated_at
        db.add(MeasurementTimepoint(experiment_id=experiment_id, day_after_germination=-1))
        with pytest.raises(IntegrityError):
            db.flush()
    with Session(engine) as db:
        db.add(MeasurementTimepoint(experiment_id=experiment_id, day_after_germination=0))
        with pytest.raises(IntegrityError):
            db.flush()
    engine.dispose()


def test_dag_migration_round_trip_preserves_referenced_rows(client: TestClient, tmp_path):
    url = f"sqlite:///{(tmp_path / 'test.db').as_posix()}"
    engine = make_engine(url)
    with Session(engine, expire_on_commit=False) as db:
        taxon = Taxon(code="SP-0001", scientific_name="Setaria italica")
        experiment = Experiment(code="EXP-2026-001", name="DAG 迁移")
        db.add_all([taxon, experiment])
        db.flush()
        lot = SeedLot(code="LOT-2026-001", taxon_id=taxon.id)
        timepoint = MeasurementTimepoint(experiment_id=experiment.id, day_after_germination=2)
        db.add_all([lot, timepoint])
        db.flush()
        material = ExperimentMaterial(experiment_id=experiment.id, seed_lot_id=lot.id)
        db.add(material)
        db.flush()
        dish = GerminationDish(material_id=material.id, code="EXP-2026-001-M001-R01", replicate_no=1, label="A1", seed_count=10)
        db.add(dish)
        db.flush()
        sample = SeedlingSample(dish_id=dish.id, sample_number=1, germinated_at=datetime(2026, 9, 28, tzinfo=timezone.utc))
        db.add(sample)
        db.flush()
        db.add(SeedlingMeasurement(sample_id=sample.id, timepoint_id=timepoint.id, root_length_mm=0,
                                   shoot_length_mm=1, measured_at=datetime(2026, 9, 29, tzinfo=timezone.utc)))
        db.commit()
        timepoint_id = timepoint.id
    engine.dispose()

    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    config.set_main_option("script_location", str(Path(__file__).resolve().parents[1] / "alembic"))
    command.downgrade(config, "3179cf93a5f4")
    engine = make_engine(url)
    with engine.connect() as connection:
        columns = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(measurement_timepoints)")}
        assert "day_after_sowing" in columns and "day_after_germination" not in columns
        assert "germinated_at" not in {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(seedling_samples)")}
        old_schema = connection.execute(text("SELECT sql FROM sqlite_master WHERE name='measurement_timepoints'")).scalar()
        assert "ck_timepoint_day" in old_schema and "uq_timepoint_day" in old_schema
        assert connection.execute(text("SELECT day_after_sowing FROM measurement_timepoints WHERE id=:id"), {"id": timepoint_id}).scalar() == 2
        assert connection.exec_driver_sql("PRAGMA foreign_key_check").all() == []
    engine.dispose()

    command.upgrade(config, "head")
    engine = make_engine(url)
    with engine.connect() as connection:
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar() == "d2e7a46b910c"
        assert connection.execute(text("SELECT day_after_germination FROM measurement_timepoints WHERE id=:id"), {"id": timepoint_id}).scalar() == 2
        index_names = {row[1] for row in connection.exec_driver_sql("PRAGMA index_list(measurement_timepoints)")}
        assert "uq_timepoint_experiment_dag" in index_names
        assert connection.execute(text("SELECT COUNT(*) FROM seedling_measurements")).scalar() == 1
        assert connection.execute(text("SELECT germinated_at FROM seedling_samples")).scalar() is None
        assert connection.exec_driver_sql("PRAGMA foreign_key_check").all() == []
    engine.dispose()


def test_create_admin_cli(client: TestClient):
    script = "import getpass, sys; getpass.getpass=lambda _prompt: 'cli-pass'; sys.argv=['seedlab', 'create-admin', 'cliadmin']; from app.cli import main; main()"
    result = subprocess.run([sys.executable, "-c", script], cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    login = client.post("/api/auth/login", json={"username": "cliadmin", "password": "cli-pass"})
    assert login.status_code == 200 and login.json()["user"]["is_admin"] is True
