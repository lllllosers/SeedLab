"""Protect the existing entry-point semantics while Core owns every transition."""
from datetime import datetime, timezone

import pytest

from app.services import experiment_lifecycle as lifecycle
from test_experiment_config import design, make_lot
from test_lifecycle_contract import audit_rows
from test_seedling_measurement import setup_experiment


def ready_plan(client, headers, replicates=2):
    _, lot = make_lot(client, headers)
    body = design(lot["id"], dag_days=[0])
    body["protocol"]["replicate_count"] = replicates
    created = client.post("/api/experiments/configured", json=body, headers=headers)
    assert created.status_code == 201
    experiment = created.json()["experiment"]
    base = f"/api/experiments/{experiment['id']}"
    assert client.patch(base, json={"status": "ready"}, headers=headers).status_code == 200
    planned = client.post(f"{base}/confirm-numbers", headers=headers)
    assert planned.status_code == 200
    return base, experiment, planned.json()["dishes"]


@pytest.mark.parametrize("second,expected", [
    ("2026-09-04T00:00:00Z", "2026-09-03T00:00:00Z"),
    ("2026-09-01T00:00:00Z", "2026-09-01T00:00:00Z"),
])
def test_first_sowing_activates_once_and_preserves_earliest_actual_fact(auth_client, monkeypatch, second, expected):
    client, headers = auth_client
    base, experiment, dishes = ready_plan(client, headers)
    transitions = []
    original = lifecycle.activate_from_fact

    def trace(db, item, actual, user_id):
        before = item.status
        original(db, item, actual, user_id)
        transitions.append((before, item.status))

    monkeypatch.setattr(lifecycle, "activate_from_fact", trace)
    first = client.post(f"{base}/sowing/batch", json={"dish_ids": [dishes[0]["id"]],
                        "sown_at": "2026-09-03T00:00:00Z"}, headers=headers)
    assert first.status_code == 200
    assert first.json()["experiment"]["started_at"] == "2026-09-03T00:00:00Z"
    later = client.post(f"{base}/sowing/batch", json={"dish_ids": [dishes[1]["id"]],
                        "sown_at": second}, headers=headers)
    assert later.status_code == 200
    assert later.json()["experiment"]["started_at"] == expected
    assert transitions == [("ready", "active"), ("active", "active")]
    assert later.json()["experiment"]["code"] == experiment["code"]
    audits = audit_rows(client, "Experiment", experiment["id"])
    count = len(audits)
    assert sum(row["before"] is None and row["after"].get("status") == "active" for row in audits) == 2
    repeated = client.post(f"{base}/sowing/batch", json={"dish_ids": [dishes[0]["id"]],
                           "sown_at": second}, headers=headers)
    assert repeated.status_code == 409
    assert repeated.json() == {"detail": "所选培养皿中已有置床记录；请使用时间纠错入口"}
    assert len(transitions) == 2
    assert len(audit_rows(client, "Experiment", experiment["id"])) == count
    # ExperimentOut keeps SQLite's naive datetime serialization; execution uses iso_utc.
    assert client.get(base).json()["started_at"] == expected.removesuffix("Z")


def test_reopen_uses_core_transition_and_keeps_numbering_audit(auth_client, monkeypatch):
    client, headers = auth_client
    base, experiment, _ = ready_plan(client, headers)
    transitions = []
    original = lifecycle.reopen_after_cleanup

    def trace(item):
        before = item.status
        original(item)
        transitions.append((before, item.status))

    monkeypatch.setattr(lifecycle, "reopen_after_cleanup", trace)
    blocked = client.patch(base, json={"status": "draft"}, headers=headers)
    assert blocked.status_code == 409
    assert blocked.json() == {"detail": "置床编号已确认；若尚未置床，请使用“重新调整实验”"}
    reopened = client.post(f"{base}/reopen-design", headers=headers)
    assert reopened.status_code == 200
    assert transitions == [("ready", "draft")]
    assert reopened.json()["dishes"] == []
    assert reopened.json()["experiment"]["numbering_locked_at"] is None
    assert client.get(base).json()["code"] == experiment["code"]
    assert all(item["experiment_number"] is None for item in client.get(f"{base}/configuration").json()["materials"])
    audit = audit_rows(client, "Experiment", experiment["id"])[0]
    assert audit["before"] == {"numbering_confirmed": True}
    assert audit["after"] == {"numbering_confirmed": False, "status": "draft"}


@pytest.mark.parametrize("entry", ["complete", "patch"])
def test_completion_keeps_entry_specific_timestamp_and_audit_shapes(auth_client, monkeypatch, entry):
    client, headers = auth_client
    base, _, _, _ = setup_experiment(client, headers, days=(0,))
    before = client.get(base).json()
    fixed = datetime(2026, 10, 7, 4, 5, 6, tzinfo=timezone.utc)

    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed if tz else fixed.replace(tzinfo=None)

    monkeypatch.setattr(lifecycle, "datetime", FixedDatetime)
    monkeypatch.setattr(lifecycle, "now_utc", lambda: fixed)
    assert client.get(f"{base}/completion-check").json()["can_complete"] is True
    response = client.post(f"{base}/complete", headers=headers) if entry == "complete" else \
        client.patch(base, json={"status": "completed"}, headers=headers)
    assert response.status_code == 200
    after = response.json()
    assert after["ended_at"] == ("2026-10-07T04:05:06" if entry == "complete" else "2026-10-07T04:05:06Z")
    assert after["started_at"] == before["started_at"]
    assert after["status"] == "completed" and after["termination_reason"] is None
    audit = audit_rows(client, "Experiment", before["id"])[0]
    if entry == "patch":
        assert audit["before"] == before
        assert audit["after"] == after
    else:
        assert audit["before"] == {key: before[key] for key in ("code", "name", "status")}
        assert audit["after"] == {**{key: after[key] for key in ("code", "name", "status")},
                                  "ended_at": "2026-10-07T04:05:06Z"}


def test_generic_termination_keeps_reason_timestamps_and_single_audit(auth_client):
    client, headers = auth_client
    base, _, _, _ = setup_experiment(client, headers, days=(0,))
    before = client.get(base).json()
    count = len(audit_rows(client, "Experiment", before["id"]))
    blank = client.post(f"{base}/terminate", json={"reason": "   "}, headers=headers)
    assert blank.status_code == 422
    assert blank.json() == {"detail": "请填写终止原因，方便以后核对实验履历"}
    assert len(audit_rows(client, "Experiment", before["id"])) == count
    ended = client.post(f"{base}/terminate", json={"reason": "  材料污染  "}, headers=headers)
    assert ended.status_code == 200
    assert ended.json()["status"] == "cancelled"
    assert ended.json()["termination_reason"] == "材料污染"
    assert ended.json()["started_at"] == before["started_at"]
    assert ended.json()["ended_at"]
    assert len(audit_rows(client, "Experiment", before["id"])) == count + 1
    repeated = client.post(f"{base}/terminate", json={"reason": "改变原因"}, headers=headers)
    assert repeated.status_code == 409
    assert repeated.json() == {"detail": "只有进行中的实验可以终止"}
    assert client.get(base).json()["termination_reason"] == "材料污染"
    assert len(audit_rows(client, "Experiment", before["id"])) == count + 1


def test_unused_delete_rolls_back_ger_cleanup_and_core_deletion_together(auth_client, monkeypatch):
    client, headers = auth_client
    base, experiment, _ = ready_plan(client, headers)
    config_before = client.get(f"{base}/configuration").json()
    execution_before = client.get(f"{base}/execution").json()
    audits_before = audit_rows(client, "Experiment", experiment["id"])
    workflow = client.app.state.experiment_types.require("GER").workflow
    cleanup = workflow.cleanup_unused

    def fail_after_cleanup(db, item):
        cleanup(db, item)
        raise RuntimeError("injected cleanup failure")

    monkeypatch.setattr(workflow, "cleanup_unused", fail_after_cleanup)
    with pytest.raises(RuntimeError, match="injected cleanup failure"):
        client.delete(base, headers=headers)
    assert client.get(f"{base}/configuration").json() == config_before
    assert client.get(f"{base}/execution").json() == execution_before
    assert audit_rows(client, "Experiment", experiment["id"]) == audits_before
    monkeypatch.setattr(workflow, "cleanup_unused", cleanup)
    assert client.delete(base, headers=headers).status_code == 204
    assert client.get(base).status_code == 404
