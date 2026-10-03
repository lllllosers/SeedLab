from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.core.config import get_settings
from app.db.session import make_engine
from app.services import germination_execution as execution
from app.services import sowing_workflow as sowing


SOWN = "2026-09-01T08:00:00+08:00"
MORNING = "2026-09-02T08:30:00+08:00"


def configured(client, headers, *, scope="per_dish", target=3, replicates=2, seeds=5, second=False):
    material_inputs = []
    lots = []
    for name in (["Setaria viridis", "Poa annua"] if second else ["Setaria viridis"]):
        taxon = client.post("/api/taxa", json={"scientific_name": name}, headers=headers).json()
        lot = client.post("/api/seed-lots", json={"taxon_id": taxon["id"], "quantity": 100}, headers=headers).json()
        lots.append(lot)
        material_inputs.append({"seed_lot_id": lot["id"]})
    data = {
        "experiment_type": "GER", "name": "Stage 2 发芽执行试验",
        "protocol": {"seeds_per_dish": seeds, "replicate_count": replicates,
                     "observation_period_days": 5, "sampling_rule": "first_germinated",
                     "sample_count": target, "sample_scope": scope,
                     "germination_criterion": "胚根达到本实验判定标准"},
        "materials": material_inputs, "dag_days": [0, 3, 7],
    }
    response = client.post("/api/experiments/configured", json=data, headers=headers)
    assert response.status_code == 201, response.text
    experiment_id = response.json()["experiment"]["id"]
    base = f"/api/experiments/{experiment_id}"
    assert client.patch(base, json={"status": "ready"}, headers=headers).status_code == 200
    return base, lots, response.json()


def start(client, headers, base, at=SOWN):
    planned = client.post(f"{base}/confirm-numbers", headers=headers)
    if planned.status_code != 200:
        return planned
    return client.post(f"{base}/sowing/batch", headers=headers, json={
        "sown_at": at, "dish_ids": [dish["id"] for dish in planned.json()["dishes"]]})


def batch(client, headers, base, time, entries):
    return client.post(f"{base}/observations/batch", json={"observed_at": time, "entries": entries}, headers=headers)


def test_start_is_atomic_uses_effective_values_and_never_decrements_lot(auth_client):
    client, headers = auth_client
    base, lots, original = configured(client, headers, second=True)
    second_id = original["materials"][1]["id"]
    assert client.patch(f"{base}/materials/{second_id}", json={"seeds_per_dish_override": 3,
                        "replicate_count_override": 3}, headers=headers).status_code == 200
    assert client.patch(base, json={"status": "active"}, headers=headers).status_code == 409
    response = start(client, headers, base)
    assert response.status_code == 200, response.text
    summary = response.json()
    assert summary["experiment"]["status"] == "active"
    assert summary["experiment"]["started_at"] == "2026-09-01T00:00:00Z"
    assert summary["dish_count"] == 5
    assert summary["materials"][0]["taxon_scientific_name"] == "Poa annua"
    assert summary["materials"][0]["taxon_common_name"] is None
    assert summary["dishes"][0]["taxon_code"] == original["materials"][0]["taxon_code"]
    assert [dish["seed_count"] for dish in summary["dishes"]] == [5, 5, 3, 3, 3]
    assert [dish["replicate_no"] for dish in summary["dishes"]] == [1, 2, 1, 2, 3]
    assert [dish["code"] for dish in summary["dishes"]] == [
        f"{original['experiment']['code']}-M001-R01", f"{original['experiment']['code']}-M001-R02",
        f"{original['experiment']['code']}-M002-R01", f"{original['experiment']['code']}-M002-R02",
        f"{original['experiment']['code']}-M002-R03",
    ]
    assert all(dish["sown_at"] == "2026-09-01T00:00:00Z" for dish in summary["dishes"])
    assert start(client, headers, base).status_code == 409
    assert client.get(f"{base}/execution").json()["dish_count"] == 5
    assert all(client.get(f"/api/seed-lots/{lot['id']}").json()["quantity"] == 100 for lot in lots)
    audit = client.get("/api/audit-logs", params={"page_size": 100}).json()["items"]
    assert sum(row["entity_type"] == "GerminationDish" and row["action"] == "create" for row in audit) == 5


def test_start_rolls_back_dishes_status_and_audit_on_failure(auth_client, monkeypatch):
    client, headers = auth_client
    base, _, _ = configured(client, headers)
    original = sowing.flush_or_conflict
    calls = 0

    def fail_after_generation(db):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("injected failure")
        return original(db)

    monkeypatch.setattr(sowing, "flush_or_conflict", fail_after_generation)
    with pytest.raises(RuntimeError, match="injected failure"):
        start(client, headers, base)
    assert client.get(base).json()["status"] == "ready"
    assert client.get(f"{base}/execution").json()["dish_count"] == 0
    assert not any(row["entity_type"] == "GerminationDish" for row in client.get("/api/audit-logs", params={"page_size": 100}).json()["items"])


def test_dish_code_and_replicate_constraints_are_enforced(auth_client, tmp_path):
    client, headers = auth_client
    base, _, _ = configured(client, headers)
    dish = start(client, headers, base).json()["dishes"][0]
    engine = make_engine(f"sqlite:///{(tmp_path / 'test.db').as_posix()}")
    cases = [
        ("OTHER-CODE", 1, "OTHER-LABEL"),
        (dish["code"], 3, "R3"),
        ("ZERO-REPLICATE", 0, "R0"),
    ]
    for code, replicate, label in cases:
        with pytest.raises(IntegrityError):
            with engine.begin() as conn:
                conn.execute(text("INSERT INTO germination_dishes (id, created_at, material_id, code, replicate_no, label, seed_count) VALUES (:id,:created,:material,:code,:replicate,:label,1)"),
                             {"id": str(uuid4()), "created": "2026-09-02 00:00:00",
                              "material": dish["material_id"], "code": code,
                              "replicate": replicate, "label": label})
    engine.dispose()


def test_batch_blank_is_missing_zero_is_checked_and_late_observation_is_allowed(auth_client):
    client, headers = auth_client
    base, _, _ = configured(client, headers)
    dish_id = "missing"
    assert client.post(f"{base}/observations", json={"dish_id": dish_id, "observed_at": MORNING,
                        "new_germinated_count": 0}, headers=headers).status_code == 409
    dishes = start(client, headers, base).json()["dishes"]
    before = client.get(f"{base}/execution").json()
    assert before["cumulative_germinated"] is None and before["germination_rate"] is None
    assert all(m["cumulative_germinated"] is None and m["germination_rate"] is None for m in before["materials"])
    assert all(d[key] is None for d in dishes for key in (
        "cumulative_germinated", "remaining_ungerminated", "germination_rate"))
    r1, r2 = dishes[0]["id"], dishes[1]["id"]
    response = batch(client, headers, base, MORNING, [
        {"dish_id": r1, "new_germinated_count": None},
        {"dish_id": r2, "new_germinated_count": 0},
    ])
    assert response.status_code == 200, response.text
    assert len(response.json()["created"]) == 1
    summary = response.json()["execution"]
    assert summary["dishes"][0]["observation_count"] == 0
    assert all(summary["dishes"][0][key] is None for key in (
        "cumulative_germinated", "remaining_ungerminated", "germination_rate"))
    assert summary["dishes"][1]["observation_count"] == 1
    assert summary["dishes"][1]["cumulative_germinated"] == 0
    assert summary["dishes"][1]["germination_rate"] == 0
    assert summary["dishes"][1]["remaining_ungerminated"] == 5
    assert summary["cumulative_germinated"] == 0 and summary["germination_rate"] == 0
    assert summary["dishes"][1]["last_observed_at"] is not None
    assert batch(client, headers, base, MORNING, [{"dish_id": r2, "new_germinated_count": 0}],).status_code == 409
    assert batch(client, headers, base, "2026-08-31T20:00:00+08:00",
                 [{"dish_id": r1, "new_germinated_count": 1}]).status_code == 422
    assert batch(client, headers, base, "2026-09-10T08:30:00+08:00",
                 [{"dish_id": r1, "new_germinated_count": 1}]).status_code == 200
    assert client.get(f"{base}/execution").json()["observation_period_overdue"] is True
    assert client.get(base).json()["status"] == "active"


def test_observation_and_samples_roll_back_together(auth_client, monkeypatch):
    client, headers = auth_client
    base, _, _ = configured(client, headers)
    dish_id = start(client, headers, base).json()["dishes"][0]["id"]
    original = execution.reconcile_samples

    def fail_after_sampling(*args):
        original(*args)
        raise RuntimeError("injected sample failure")

    monkeypatch.setattr(execution, "reconcile_samples", fail_after_sampling)
    with pytest.raises(RuntimeError, match="injected sample failure"):
        batch(client, headers, base, MORNING, [{"dish_id": dish_id, "new_germinated_count": 2}])
    summary = client.get(f"{base}/execution").json()
    assert summary["recent_observations"] == []
    assert summary["sample_count"] == 0
    assert not any(row["entity_type"] in {"GerminationObservation", "SeedlingSample"}
                   for row in client.get("/api/audit-logs", params={"page_size": 100}).json()["items"])


def test_multiple_checks_per_day_capacity_and_atomic_batch(auth_client):
    client, headers = auth_client
    base, _, _ = configured(client, headers, target=2)
    r1, r2 = [dish["id"] for dish in start(client, headers, base).json()["dishes"]]
    assert batch(client, headers, base, "2026-09-02T08:30:00+08:00",
                 [{"dish_id": r1, "new_germinated_count": 2}]).status_code == 200
    assert batch(client, headers, base, "2026-09-02T14:00:00+08:00",
                 [{"dish_id": r1, "new_germinated_count": 0}]).status_code == 200
    assert batch(client, headers, base, "2026-09-02T20:00:00+08:00",
                 [{"dish_id": r1, "new_germinated_count": 3}]).status_code == 200
    summary = client.get(f"{base}/execution").json()
    assert summary["dishes"][0]["cumulative_germinated"] == 5
    assert summary["dishes"][0]["germination_rate"] == 100
    assert summary["dishes"][0]["sample_count"] == 2
    failed = batch(client, headers, base, "2026-09-03T08:30:00+08:00", [
        {"dish_id": r2, "new_germinated_count": 1},
        {"dish_id": r1, "new_germinated_count": 1},
    ])
    assert failed.status_code == 422
    assert client.get(f"{base}/execution").json()["dishes"][1]["observation_count"] == 0


def test_per_dish_first_n_and_source_time(auth_client):
    client, headers = auth_client
    base, _, _ = configured(client, headers, target=3)
    r1, r2 = [dish["id"] for dish in start(client, headers, base).json()["dishes"]]
    first = batch(client, headers, base, MORNING, [
        {"dish_id": r1, "new_germinated_count": 2},
        {"dish_id": r2, "new_germinated_count": 4},
    ])
    assert first.status_code == 200, first.text
    assert [dish["sample_count"] for dish in first.json()["execution"]["dishes"]] == [2, 3]
    second = batch(client, headers, base, "2026-09-03T08:30:00+08:00",
                   [{"dish_id": r1, "new_germinated_count": 2}])
    assert second.status_code == 200, second.text
    assert [dish["sample_count"] for dish in second.json()["execution"]["dishes"]] == [3, 3]
    assert batch(client, headers, base, "2026-09-04T08:30:00+08:00",
                 [{"dish_id": r1, "new_germinated_count": 1}]).status_code == 200
    assert client.get(f"{base}/execution").json()["sample_count"] == 6
    samples = client.get(f"{base}/samples").json()
    assert [sample["sample_number"] for sample in samples if sample["dish_id"] == r1] == [1, 2, 3]
    assert all(sample["source_observation_id"] for sample in samples)
    times = {item["id"]: item["observed_at"] for item in client.get(f"{base}/execution").json()["recent_observations"]}
    assert all(sample["germinated_at"] == times[sample["source_observation_id"]] for sample in samples)
    source_dishes = {item["id"]: item["dish_id"] for item in client.get(f"{base}/execution").json()["recent_observations"]}
    assert all(sample["dish_id"] == source_dishes[sample["source_observation_id"]] for sample in samples)


def test_per_material_same_time_replicate_tie_break(auth_client):
    client, headers = auth_client
    base, _, _ = configured(client, headers, scope="per_material", target=3)
    r1, r2 = [dish["id"] for dish in start(client, headers, base).json()["dishes"]]
    response = batch(client, headers, base, MORNING, [
        {"dish_id": r2, "new_germinated_count": 2},
        {"dish_id": r1, "new_germinated_count": 2},
    ])
    assert response.status_code == 200, response.text
    assert [dish["sample_count"] for dish in response.json()["execution"]["dishes"]] == [2, 1]
    assert batch(client, headers, base, "2026-09-03T08:30:00+08:00",
                 [{"dish_id": r2, "new_germinated_count": 2}]).status_code == 200
    summary = client.get(f"{base}/execution").json()
    assert summary["cumulative_germinated"] == 6
    assert summary["sample_count"] == 3
    assert summary["materials"][0]["sample_target"] == 3
    assert len(client.get(f"{base}/samples").json()) == 3


def test_retroactive_observation_cannot_displace_selected_samples(auth_client):
    client, headers = auth_client
    base, _, _ = configured(client, headers, scope="per_material", target=2)
    r1, r2 = [dish["id"] for dish in start(client, headers, base).json()["dishes"]]
    assert batch(client, headers, base, "2026-09-03T08:30:00+08:00",
                 [{"dish_id": r2, "new_germinated_count": 2}]).status_code == 200
    rejected = batch(client, headers, base, MORNING,
                     [{"dish_id": r1, "new_germinated_count": 1}])
    assert rejected.status_code == 409
    assert "前 N 株" in rejected.json()["detail"]
    assert client.get(f"{base}/execution").json()["cumulative_germinated"] == 2


def test_correction_deletion_and_audit_preserve_selected_samples(auth_client):
    client, headers = auth_client
    base, _, _ = configured(client, headers, target=2)
    r1 = start(client, headers, base).json()["dishes"][0]["id"]
    first = batch(client, headers, base, MORNING, [{"dish_id": r1, "new_germinated_count": 2}]).json()["created"][0]
    path = f"{base}/observations/{first['id']}"
    assert client.patch(path, json={"new_germinated_count": 1}, headers=headers).status_code == 409
    assert client.patch(path, json={"new_germinated_count": 6}, headers=headers).status_code == 422
    assert client.patch(path, json={"notes": "复核胚根"}, headers=headers).json()["notes"] == "复核胚根"
    assert client.delete(path, headers=headers).status_code == 409
    later = batch(client, headers, base, "2026-09-03T08:30:00+08:00",
                  [{"dish_id": r1, "new_germinated_count": 0}]).json()["created"][0]
    assert client.patch(f"{base}/observations/{later['id']}", json={"new_germinated_count": None}, headers=headers).status_code == 422
    assert client.delete(f"{base}/observations/{later['id']}", headers=headers).status_code == 204
    assert client.get(f"{base}/execution").json()["dishes"][0]["cumulative_germinated"] == 2
    audit = client.get("/api/audit-logs", params={"page_size": 100}).json()["items"]
    obs_actions = [row["action"] for row in audit if row["entity_type"] == "GerminationObservation"]
    assert {"create", "update", "delete"} <= set(obs_actions)
    assert any(row["entity_type"] == "SeedlingSample" and row["action"] == "create" for row in audit)


def test_correction_can_fill_remaining_first_n_slots(auth_client):
    client, headers = auth_client
    base, _, _ = configured(client, headers, target=3)
    dish_id = start(client, headers, base).json()["dishes"][0]["id"]
    earlier = batch(client, headers, base, MORNING,
                    [{"dish_id": dish_id, "new_germinated_count": 1}]).json()["created"][0]
    batch(client, headers, base, "2026-09-02T14:00:00+08:00",
          [{"dish_id": dish_id, "new_germinated_count": 1}])
    assert client.get(f"{base}/execution").json()["sample_count"] == 2
    assert client.patch(f"{base}/observations/{earlier['id']}",
                        json={"new_germinated_count": 2}, headers=headers).status_code == 200
    samples = client.get(f"{base}/samples").json()
    assert len(samples) == 3
    assert sum(sample["source_observation_id"] == earlier["id"] for sample in samples) == 2


def test_completed_experiment_stops_new_observations(auth_client, tmp_path):
    client, headers = auth_client
    base, _, _ = configured(client, headers)
    dish = start(client, headers, base).json()["dishes"][0]
    # Seed an already completed legacy experiment; elapsed plan days no longer complete it.
    engine = make_engine(f"sqlite:///{(tmp_path / 'test.db').as_posix()}")
    with engine.begin() as conn:
        conn.execute(text("UPDATE experiments SET status='completed' WHERE id=:id"),
                     {"id": base.split('/')[-1]})
    engine.dispose()
    assert client.get(base).json()["status"] == "completed"
    assert batch(client, headers, base, MORNING,
                 [{"dish_id": dish["id"], "new_germinated_count": 0}]).status_code == 409


def test_stage2_migration_preserves_existing_dish_and_sample(tmp_path, monkeypatch):
    url = f"sqlite:///{(tmp_path / 'legacy.db').as_posix()}"
    monkeypatch.setenv("SEEDLAB_DATABASE_URL", url)
    get_settings.cache_clear()
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    config.set_main_option("script_location", str(Path(__file__).resolve().parents[1] / "alembic"))
    command.upgrade(config, "d50447b51d78")
    engine = make_engine(url)
    ids = {name: str(uuid4()) for name in ("taxon", "lot", "experiment", "material", "dish", "observation", "sample")}
    with engine.begin() as conn:
        stamp = "2026-09-01 00:00:00"
        conn.execute(text("INSERT INTO taxa (id, created_at, code, scientific_name, is_active) VALUES (:id,:t,'SP-1','Setaria italica',1)"), {"id": ids["taxon"], "t": stamp})
        conn.execute(text("INSERT INTO seed_lots (id, created_at, code, taxon_id, is_active) VALUES (:id,:t,'LOT-1',:taxon,1)"), {"id": ids["lot"], "t": stamp, "taxon": ids["taxon"]})
        conn.execute(text("INSERT INTO experiments (id, created_at, code, name, status) VALUES (:id,:t,'EXP-2026-001','历史试验','active')"), {"id": ids["experiment"], "t": stamp})
        conn.execute(text("INSERT INTO experiment_materials (id, created_at, experiment_id, seed_lot_id, display_order) VALUES (:id,:t,:experiment,:lot,0)"), {"id": ids["material"], "t": stamp, "experiment": ids["experiment"], "lot": ids["lot"]})
        conn.execute(text("INSERT INTO germination_dishes (id, created_at, material_id, label, seed_count, sown_at) VALUES (:id,:t,:material,'A1',10,:t)"), {"id": ids["dish"], "t": stamp, "material": ids["material"]})
        conn.execute(text("INSERT INTO germination_observations (id, created_at, dish_id, observed_at, new_germinated_count) VALUES (:id,:t,:dish,:t,1)"), {"id": ids["observation"], "t": stamp, "dish": ids["dish"]})
        conn.execute(text("INSERT INTO seedling_samples (id, created_at, dish_id, sample_number, germinated_at) VALUES (:id,:t,:dish,1,:t)"), {"id": ids["sample"], "t": stamp, "dish": ids["dish"]})
    engine.dispose()
    command.upgrade(config, "head")
    engine = make_engine(url)
    with engine.connect() as conn:
        assert conn.execute(text("SELECT code FROM germination_dishes WHERE id=:id"), {"id": ids["dish"]}).scalar() == "EXP-2026-001-M001-R01"
        assert conn.execute(text("SELECT replicate_no FROM germination_dishes WHERE id=:id"), {"id": ids["dish"]}).scalar() == 1
        assert conn.execute(text("SELECT source_observation_id FROM seedling_samples WHERE id=:id"), {"id": ids["sample"]}).scalar() is None
        assert conn.exec_driver_sql("PRAGMA foreign_key_check").all() == []
    engine.dispose()
    command.downgrade(config, "d50447b51d78")
    command.upgrade(config, "head")
    engine = make_engine(url)
    with engine.connect() as conn:
        assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar() == "d2e7a46b910c"
        assert conn.execute(text("SELECT COUNT(*) FROM germination_observations")).scalar() == 1
        assert conn.execute(text("SELECT COUNT(*) FROM seedling_samples")).scalar() == 1
        assert conn.exec_driver_sql("PRAGMA foreign_key_check").all() == []
    engine.dispose()
    get_settings.cache_clear()
