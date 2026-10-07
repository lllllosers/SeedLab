"""The optional plan must not substitute for observation facts or stop execution."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.api.schemas import MaterialInput, ProtocolInput
from app.services.germination_config import workload

from test_experiment_config import design, make_lot
from test_germination_execution import batch, start


@pytest.mark.parametrize("omitted", [False, True])
def test_optional_period_allows_complete_configuration_start_and_inspection(auth_client, omitted):
    client, headers = auth_client
    _, lot = make_lot(client, headers)
    data = design(lot["id"])
    data["protocol"]["observation_period_days"] = None
    if omitted:
        del data["protocol"]["observation_period_days"]
    estimate = client.post("/api/experiments/estimate", json=data, headers=headers)
    assert estimate.status_code == 200, estimate.text
    assert estimate.json()["estimated_latest_finish_date"] is None
    created = client.post("/api/experiments/configured", json=data, headers=headers)
    assert created.status_code == 201, created.text
    config = created.json()
    base = f"/api/experiments/{config['experiment']['id']}"
    assert config["protocol"]["observation_period_days"] is None
    assert config["workload"]["estimated_measurement_count"] == 45
    assert client.get(base + "/configuration").json()["workload"]["estimated_latest_finish_date"] is None
    assert client.put(base + "/protocol", json=data["protocol"], headers=headers).status_code == 200
    assert client.patch(base, json={"status": "ready"}, headers=headers).status_code == 200
    now = datetime.now(timezone.utc)
    response = start(client, headers, base, at=(now - timedelta(days=45)).isoformat())
    assert response.status_code == 200, response.text
    execution = response.json()
    assert execution["experiment"]["status"] == "active"
    assert execution["observation_period_end_at"] is None
    assert execution["observation_period_overdue"] is False
    assert execution["latest_sown_estimated_finish_at"] is None
    assert execution["today_pending_count"] == 3
    assert all(dish["observation_period_end_at"] is None for dish in execution["dishes"])
    assert all(dish[key] is None for dish in execution["dishes"] for key in (
        "cumulative_germinated", "germination_rate", "remaining_ungerminated"))
    saved = batch(client, headers, base, now.isoformat(), [
        {"dish_id": execution["dishes"][0]["id"], "new_germinated_count": 0}])
    assert saved.status_code == 200, saved.text
    result = saved.json()["execution"]
    assert result["today_pending_count"] == 2
    dish = result["dishes"][0]
    assert (dish["cumulative_germinated"], dish["germination_rate"], dish["remaining_ungerminated"]) == (0, 0, 20)
    assert client.get(base + "/configuration").json()["protocol"]["observation_period_days"] is None


@pytest.mark.parametrize("start_date,days,dag_days,expected", [
    ("2026-10-01", 30, [0, 3, 7], "2026-11-07"),
    ("2026-10-01", 14, [0], "2026-10-15"),
    (None, 30, [7], None),
    ("2026-10-01", None, [7], None),
])
def test_estimate_requires_all_three_plan_inputs(auth_client, start_date, days, dag_days, expected):
    client, headers = auth_client
    _, lot = make_lot(client, headers)
    data = design(lot["id"], planned_start_date=start_date, dag_days=dag_days)
    data["protocol"]["observation_period_days"] = days
    response = client.post("/api/experiments/configured", json=data, headers=headers)
    assert response.status_code == 201, response.text
    config = response.json()
    assert config["protocol"]["observation_period_days"] == days
    assert config["workload"]["estimated_latest_finish_date"] == expected


def test_workload_without_dag_does_not_invent_finish_date():
    # Configured creation still requires a DAG; incomplete draft estimates do not.
    protocol = ProtocolInput(**design("test-lot")["protocol"])
    result = workload(SimpleNamespace(planned_start_date=datetime(2026, 10, 1).date()),
                      protocol, [MaterialInput(seed_lot_id="test-lot")], [])
    assert result["estimated_latest_finish_date"] is None
    assert result["estimated_measurement_count"] == 0


@pytest.mark.parametrize("field", ["seeds_per_dish", "replicate_count", "sampling_rule",
                                   "sample_count", "sample_scope", "germination_criterion"])
def test_optional_period_does_not_relax_core_protocol(auth_client, field):
    client, headers = auth_client
    _, lot = make_lot(client, headers)
    data = design(lot["id"])
    data["protocol"]["observation_period_days"] = None
    data["protocol"][field] = None
    assert client.post("/api/experiments/configured", json=data, headers=headers).status_code == 422


def test_overdue_dishes_remain_pending_and_accept_zero_and_positive_with_dag_tasks(auth_client):
    client, headers = auth_client
    _, lot = make_lot(client, headers)
    data = design(lot["id"])
    data["protocol"].update(observation_period_days=30, seeds_per_dish=5,
                            replicate_count=2, sample_count=3)
    created = client.post("/api/experiments/configured", json=data, headers=headers)
    assert created.status_code == 201, created.text
    base = f"/api/experiments/{created.json()['experiment']['id']}"
    assert client.patch(base, json={"status": "ready"}, headers=headers).status_code == 200
    now = datetime.now(timezone.utc)
    sown_at = now - timedelta(days=45)
    initial = start(client, headers, base, at=sown_at.isoformat())
    assert initial.status_code == 200, initial.text
    execution = initial.json()
    assert execution["observation_period_end_at"] == (sown_at + timedelta(days=30)).isoformat().replace("+00:00", "Z")
    assert execution["observation_period_overdue"] is True
    assert execution["today_pending_count"] == 2
    assert execution["cumulative_germinated"] is None and execution["germination_rate"] is None
    assert all(dish[key] is None for dish in execution["dishes"] for key in (
        "cumulative_germinated", "germination_rate", "remaining_ungerminated"))
    zero_id, positive_id = [dish["id"] for dish in execution["dishes"]]
    saved = batch(client, headers, base, now.isoformat(), [{"dish_id": zero_id, "new_germinated_count": 0}])
    assert saved.status_code == 200, saved.text
    after_zero = saved.json()["execution"]
    assert after_zero["today_pending_count"] == 1 and after_zero["today_observed_count"] == 1
    assert after_zero["observation_period_overdue"] is True
    zero, unrecorded = after_zero["dishes"]
    assert (zero["cumulative_germinated"], zero["germination_rate"], zero["remaining_ungerminated"]) == (0, 0, 5)
    assert all(unrecorded[key] is None for key in ("cumulative_germinated", "germination_rate", "remaining_ungerminated"))
    positive = client.post(base + "/observations", json={"dish_id": positive_id,
        "observed_at": now.isoformat(), "new_germinated_count": 4}, headers=headers)
    assert positive.status_code == 201, positive.text
    refreshed = client.get(base + "/execution").json()
    assert refreshed["today_pending_count"] == 0
    assert refreshed["experiment"]["status"] == "active"
    assert refreshed["dishes"][0]["germination_rate"] == 0
    assert refreshed["dishes"][1]["sample_count"] == 3
    assert refreshed["dishes"][1]["cumulative_germinated"] == 4
    samples = client.get(base + "/samples").json()
    assert len(samples) == 3 and all(s["germinated_at"] == now.isoformat().replace("+00:00", "Z") for s in samples)
    tasks = client.get(base + "/measurement-tasks").json()["tasks"]
    assert len(tasks) == 9 and {t["day_after_germination"] for t in tasks} == {0, 3, 7}
    task = next(t for t in tasks if t["day_after_germination"] == 0)
    measurement = client.post(base + "/measurements", json={"sample_id": task["sample_id"],
        "timepoint_id": task["timepoint_id"], "root_length_mm": 0, "shoot_length_mm": 1,
        "measured_at": now.isoformat()}, headers=headers)
    assert measurement.status_code == 201, measurement.text
    check = client.get(base + "/completion-check").json()
    assert check["observing_dish_count"] == 2 and check["can_complete"] is False
    assert check["measurement_pending_count"] == 8


@pytest.mark.parametrize("period_days,sown_days_ago,overdue", [
    (None, 2, False),
    (30, 2, False),
    (30, 45, True),
])
@pytest.mark.parametrize("explicit_zero", [False, True])
def test_manual_completion_is_independent_of_plan_and_preserves_observation_facts(
        auth_client, period_days, sown_days_ago, overdue, explicit_zero):
    client, headers = auth_client
    _, lot = make_lot(client, headers)
    data = design(lot["id"])
    data["protocol"].update(observation_period_days=period_days, replicate_count=1)
    created = client.post("/api/experiments/configured", json=data, headers=headers)
    assert created.status_code == 201, created.text
    base = f"/api/experiments/{created.json()['experiment']['id']}"
    assert not client.get(base + "/completion-check").json()["can_complete"]
    assert client.post(base + "/complete", headers=headers).status_code == 409
    assert client.patch(base, json={"status": "ready"}, headers=headers).status_code == 200
    assert not client.get(base + "/completion-check").json()["can_complete"]
    assert client.post(base + "/complete", headers=headers).status_code == 409
    now = datetime.now(timezone.utc)
    sown = start(client, headers, base, at=(now - timedelta(days=sown_days_ago)).isoformat())
    assert sown.status_code == 200, sown.text
    dish = sown.json()["dishes"][0]
    if explicit_zero:
        saved = batch(client, headers, base, now.isoformat(), [
            {"dish_id": dish["id"], "new_germinated_count": 0}])
        assert saved.status_code == 200, saved.text
    before = client.get(base + "/execution").json()
    assert before["experiment"]["status"] == "active"
    assert before["observation_period_overdue"] is overdue
    assert before["dishes"][0]["cancelled_at"] is None
    check = client.get(base + "/completion-check").json()
    assert check["observing_dish_count"] == 1
    assert check["pending_dish_count"] == check["measurement_pending_count"] == 0
    assert check["can_complete"] is True
    completed = client.post(base + "/complete", headers=headers)
    assert completed.status_code == 200, completed.text
    assert completed.json()["status"] == "completed"
    assert completed.json()["termination_reason"] is None
    assert completed.json()["ended_at"] is not None
    after = client.get(base + "/execution").json()
    assert after["experiment"]["status"] == "completed"
    assert after["dishes"][0]["cancelled_at"] is None
    assert after["dishes"][0]["sown_at"] == dish["sown_at"]
    assert after["sample_count"] == 0
    expected = 0 if explicit_zero else None
    for result in (before, after):
        assert result["cumulative_germinated"] == result["germination_rate"] == expected
        assert result["materials"][0]["cumulative_germinated"] == expected
        assert result["materials"][0]["germination_rate"] == expected
        assert result["dishes"][0]["cumulative_germinated"] == expected
        assert result["dishes"][0]["germination_rate"] == expected
        assert result["dishes"][0]["remaining_ungerminated"] == (20 if explicit_zero else None)
        assert len(result["recent_observations"]) == int(explicit_zero)
    assert after["recent_observations"] == before["recent_observations"]
    if explicit_zero:
        assert after["recent_observations"][0]["new_germinated_count"] == 0
    assert not client.get(base + "/completion-check").json()["can_complete"]
    assert client.post(base + "/complete", headers=headers).status_code == 409
    assert client.post(base + "/terminate", json={"reason": "不应转为终止"}, headers=headers).status_code == 409
