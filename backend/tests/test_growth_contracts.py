"""Contract authority and HTTP compatibility across the moved boundaries."""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api import schemas
from app.api.errors import application_error_handler
from app.contracts import experiments, germination, measurement
from app.contracts.errors import ApplicationError, ConflictError, NotFoundError, ValidationError
from app.main import create_app
from app.models import Experiment
from app.services import application_support, common
from test_experiment_config import design, make_lot
from test_seedling_measurement import observe, payload, setup_experiment


@pytest.mark.parametrize("module,names", [
    (experiments, "ExperimentIn ExperimentPatch ExperimentOut ProtocolInput TerminateExperiment "
                  "MaterialInput MaterialPatch ConfiguredExperimentInput DagInput MaterialOrderInput"),
    (germination, "SowDishesInput CorrectSowingInput CancelDishInput ObservationEntry "
                  "BatchObservationInput ObservationInput ObservationPatch"),
    (measurement, "MeasurementInput MeasurementPatch PositionLabelPatch"),
])
def test_api_compatibility_aliases_share_single_contract(module, names):
    for name in names.split():
        assert getattr(schemas, name) is getattr(module, name)


@pytest.mark.parametrize("error_type,status", [(NotFoundError, 404), (ConflictError, 409),
                                               (ValidationError, 422)])
def test_error_mapping_matches_original_http_response(error_type, status):
    detail = "找不到所选内容，请刷新页面后重试"
    responses = []
    for error in (HTTPException(status, detail), error_type(detail)):
        app = FastAPI()
        app.add_exception_handler(ApplicationError, application_error_handler)

        @app.get("/failure")
        def fail():
            raise error

        with TestClient(app) as client:
            responses.append(client.get("/failure"))
    original, moved = responses
    assert moved.status_code == original.status_code == status
    assert moved.content == original.content
    assert moved.json() == {"detail": detail}
    assert moved.headers == original.headers


def test_unclassified_error_is_not_mapped_to_a_client_failure():
    app = FastAPI()
    app.add_exception_handler(ApplicationError, application_error_handler)

    @app.get("/failure")
    def fail():
        raise ApplicationError("unclassified")

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/failure")
    assert response.status_code == 500
    assert response.text == "Internal Server Error"


@pytest.mark.parametrize("helper", ["commit_or_conflict", "flush_or_conflict"])
@pytest.mark.parametrize("module,error_type", [(application_support, ConflictError), (common, HTTPException)])
def test_persistence_conflict_keeps_rollback_and_non_growth_compatibility(helper, module, error_type):
    engine = create_engine("sqlite://")
    Experiment.__table__.create(engine)
    try:
        with Session(engine) as db:
            db.add(Experiment(code="GER-202610-001", experiment_type="GER", name="保留实验"))
            db.commit()
            db.add(Experiment(code="GER-202610-001", experiment_type="GER", name="重复编号"))
            with pytest.raises(error_type) as failure:
                getattr(module, helper)(db)
            assert failure.value.detail == "编号或名称已存在，或数据正在被引用"
            assert isinstance(failure.value.__cause__, IntegrityError)
            if module is common:
                assert failure.value.status_code == 409
            # The session is usable again and the failed write was rolled back.
            assert db.scalars(select(Experiment.name)).all() == ["保留实验"]
    finally:
        engine.dispose()


def test_openapi_selected_contracts_keep_requests_responses_and_required_fields():
    schema = create_app().openapi()
    operations = [
        ("/api/experiments", "post", "ExperimentIn", "201", "ExperimentOut"),
        ("/api/experiments/{item_id}", "patch", "ExperimentPatch", "200", "ExperimentOut"),
        ("/api/experiments/configured", "post", "ConfiguredExperimentInput", "201", None),
        ("/api/experiments/{item_id}/protocol", "put", "ProtocolInput", "200", None),
        ("/api/experiments/{experiment_id}/sowing/batch", "post", "SowDishesInput", "200", None),
        ("/api/experiments/{experiment_id}/observations/batch", "post", "BatchObservationInput", "200", None),
        ("/api/experiments/{experiment_id}/measurements", "post", "MeasurementInput", "201", None),
        ("/api/experiments/{experiment_id}/measurements/{measurement_id}", "patch", "MeasurementPatch", "200", None),
    ]
    for path, method, request, status, response in operations:
        operation = schema["paths"][path][method]
        body = operation["requestBody"]
        assert body["required"] is True
        assert body["content"]["application/json"]["schema"] == {"$ref": f"#/components/schemas/{request}"}
        result = operation["responses"][status]["content"]["application/json"]["schema"]
        assert result == ({"$ref": f"#/components/schemas/{response}"} if response else {})
        assert operation["responses"]["422"]["content"]["application/json"]["schema"] == {
            "$ref": "#/components/schemas/HTTPValidationError"}
    components = schema["components"]["schemas"]
    assert components["ConfiguredExperimentInput"]["required"] == [
        "experiment_type", "name", "protocol", "materials", "dag_days"]
    assert components["MeasurementInput"]["required"] == ["sample_id", "timepoint_id", "measured_at"]
    assert components["MeasurementPatch"]["additionalProperties"] is False
    assert components["ExperimentPatch"]["additionalProperties"] is False
    assert components["BatchObservationInput"]["properties"]["entries"]["minItems"] == 1


@pytest.mark.parametrize("suffix,body", [
    ("materials", {"seed_lot_id": "missing"}),
    ("observations/batch", {"observed_at": "2026-10-01T00:00:00Z",
                            "entries": [{"dish_id": "missing", "new_germinated_count": 0}]}),
    ("measurements", {"sample_id": "missing", "timepoint_id": "missing",
                      "measured_at": "2026-10-01T00:00:00Z"}),
])
def test_each_growth_domain_preserves_missing_entity_response(auth_client, suffix, body):
    client, headers = auth_client
    response = client.post(f"/api/experiments/missing/{suffix}", json=body, headers=headers)
    assert response.status_code == 404
    assert response.json() == {"detail": "找不到所选内容，请刷新页面后重试"}
    assert response.headers["content-type"] == "application/json"


def test_configuration_contract_conflict_state_body_and_csrf(auth_client):
    client, headers = auth_client
    _, lot = make_lot(client, headers)
    body = design(lot["id"])
    response = client.post("/api/experiments/configured", json=body, headers=headers)
    assert response.status_code == 201
    assert response.json()["experiment"]["experiment_type"] == "GER"
    base = f"/api/experiments/{response.json()['experiment']['id']}"
    conflict = client.post(f"{base}/materials", json={"seed_lot_id": lot["id"]}, headers=headers)
    assert conflict.status_code == 409
    assert conflict.json() == {"detail": "该种子批次已加入本实验"}
    assert client.patch(base, json={"status": "ready"}, headers=headers).status_code == 200
    assert client.post(f"{base}/confirm-numbers", headers=headers).status_code == 200
    locked = client.put(f"{base}/protocol", json=body["protocol"], headers=headers)
    assert locked.status_code == 409
    assert locked.json() == {"detail": "置床编号已确认；尚未置床时可先选择“重新调整实验”"}
    invalid = client.patch(base, json={"unexpected": 1}, headers=headers)
    assert invalid.status_code == 422
    assert invalid.json()["detail"][0]["type"] == "extra_forbidden"
    assert invalid.json()["detail"][0]["loc"] == ["body", "unexpected"]
    csrf = client.put(f"{base}/protocol", json=body["protocol"])
    assert csrf.status_code == 403
    assert csrf.json() == {"detail": "页面验证已失效，请刷新页面后重试"}


def test_ger_preserves_observation_conflict_and_invalid_state(auth_client):
    client, headers = auth_client
    base, dish, _, _ = setup_experiment(client, headers, days=(0,))
    when = datetime.now(timezone.utc) - timedelta(days=2)
    observe(client, headers, base, dish, when)
    body = {"observed_at": when.isoformat(),
            "entries": [{"dish_id": dish["id"], "new_germinated_count": 0}]}
    conflict = client.post(f"{base}/observations/batch", json=body, headers=headers)
    assert conflict.status_code == 409
    assert conflict.json() == {"detail": "培养皿 001 在这个时间已有巡检记录，请修改原记录或选择其他时间"}
    draft = client.post("/api/experiments", json={"experiment_type": "GER", "name": "未开始试验"}, headers=headers).json()
    state = client.post(f"/api/experiments/{draft['id']}/observations/batch", json=body, headers=headers)
    assert state.status_code == 409
    assert state.json() == {"detail": "只有进行中的实验可以新增发芽巡检"}


def test_measurement_preserves_zero_unavailable_and_completed_correction(auth_client):
    client, headers = auth_client
    base, dish, _, _ = setup_experiment(client, headers, days=(0,))
    when = datetime.now(timezone.utc) - timedelta(days=2)
    observe(client, headers, base, dish, when)
    task = client.get(f"{base}/measurement-tasks").json()["tasks"][0]
    invalid = client.post(f"{base}/measurements", json=payload(task, when, root="0.001"), headers=headers)
    assert invalid.status_code == 422
    assert invalid.json() == {"detail": "根长请填写不超过两位小数的非负数值"}
    created = client.post(f"{base}/measurements", json=payload(task, when, shoot=None, shoot_na=True), headers=headers)
    assert created.status_code == 201
    result = created.json()
    assert result["root_length_mm"] == 0
    assert result["root_unavailable"] is False
    assert result["shoot_length_mm"] is None
    assert result["shoot_unavailable"] is True
    assert client.post(f"{base}/complete", headers=headers).status_code == 200
    record = f"{base}/measurements/{result['id']}"
    corrected = client.patch(record, json={"shoot_length_mm": "1.25", "shoot_unavailable": False}, headers=headers)
    assert corrected.status_code == 200
    assert corrected.json()["root_length_mm"] == 0
    assert corrected.json()["shoot_length_mm"] == 1.25
    cleared = client.delete(record, headers=headers)
    assert cleared.status_code == 409
    assert cleared.json() == {"detail": "只有进行中的实验可以清除本阶段测定；已完成实验仍可修改原记录"}
    invalid_body = client.patch(record, json={"unexpected": 1}, headers=headers)
    assert invalid_body.status_code == 422
    assert invalid_body.json()["detail"][0]["type"] == "extra_forbidden"
