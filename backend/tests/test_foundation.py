from io import BytesIO
from datetime import datetime, timezone
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import make_engine
from app.models import Experiment, ExperimentMaterial, GerminationDish, GerminationObservation, MeasurementTimepoint, SeedlingMeasurement, SeedlingSample, SeedLot, Taxon


def test_migration_and_sqlite_settings(client: TestClient, tmp_path):
    assert client.get("/api/health").json()["version"] == "0.1.0-dev"
    engine = make_engine(f"sqlite:///{(tmp_path / 'test.db').as_posix()}")
    with engine.connect() as connection:
        tables = {row[0] for row in connection.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))}
        assert {"users", "taxa", "seed_lots", "experiments", "germination_observations", "seedling_measurements", "audit_logs", "import_jobs"} <= tables
        assert connection.exec_driver_sql("PRAGMA journal_mode").scalar().lower() == "wal"
        assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar() == "3179cf93a5f4"
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
    assert [entry["action"] for entry in client.get("/api/audit-logs").json()] == ["delete", "update", "update", "create"]


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
    created = client.post("/api/experiments", json={"name": "萌发温度试验"}, headers=headers)
    assert created.status_code == 201
    item = created.json()
    assert item["code"].startswith("EXP-")
    assert item["status"] == "draft"
    updated = client.patch(f"/api/experiments/{item['id']}", json={"status": "active"}, headers=headers)
    assert updated.status_code == 200 and updated.json()["started_at"]
    assert client.get("/api/dashboard").json()["active_experiments"] == 1
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


def test_excel_import_and_csv_export(auth_client):
    client, headers = auth_client
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["scientific_name", "common_name", "family"])
    sheet.append(["Festuca rubra", "羊茅", "Poaceae"])
    stream = BytesIO()
    workbook.save(stream)
    response = client.post("/api/import/taxa", files={"file": ("taxa.xlsx", stream.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}, headers=headers)
    assert response.status_code == 201 and response.json()["imported"] == 1
    exported = client.get("/api/export/taxa.csv")
    assert exported.status_code == 200 and "Festuca rubra" in exported.text
    assert client.get("/api/audit-logs").json()[0]["action"] == "import"


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
        timepoint = MeasurementTimepoint(experiment_id=experiment.id, day_after_sowing=0)
        db.add_all([material, timepoint])
        db.flush()
        dish = GerminationDish(material_id=material.id, label="A1", seed_count=10)
        db.add(dish)
        db.flush()
        sample = SeedlingSample(dish_id=dish.id, sample_number=1)
        observation = GerminationObservation(dish_id=dish.id, observed_at=datetime(2026, 9, 28, 9, tzinfo=timezone.utc), new_germinated_count=0)
        db.add_all([sample, observation])
        db.flush()
        measurement = SeedlingMeasurement(sample_id=sample.id, timepoint_id=timepoint.id, root_length_mm=0, shoot_length_mm=None)
        db.add(measurement)
        db.commit()
        assert observation.new_germinated_count == 0
        assert measurement.root_length_mm == 0
        assert measurement.shoot_length_mm is None
        assert lot.quantity == 0
        experiment_id = experiment.id
    with Session(engine) as db:
        db.add(MeasurementTimepoint(experiment_id=experiment_id, day_after_sowing=-1))
        with pytest.raises(IntegrityError):
            db.flush()
    engine.dispose()


def test_create_admin_cli(client: TestClient):
    script = "import getpass, sys; getpass.getpass=lambda _prompt: 'cli-password-123'; sys.argv=['seedlab', 'create-admin', 'cliadmin']; from app.cli import main; main()"
    result = subprocess.run([sys.executable, "-c", script], cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    login = client.post("/api/auth/login", json={"username": "cliadmin", "password": "cli-password-123"})
    assert login.status_code == 200 and login.json()["user"]["is_admin"] is True
