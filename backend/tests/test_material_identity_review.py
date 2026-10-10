"""Synthetic regression cases from production feedback; no production files are used."""
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.db.session import make_engine
from app.models import Taxon, SeedLot, Experiment, ExperimentMaterial
from app.services.material_import import scientific_comparison_key, chinese_comparison_key
from test_material_import_and_execution import material_file, row, preview, confirm


@pytest.mark.parametrize("value", ["Potentilla_supina", " Potentilla\u00a0supina ", "POTENTILLA   SUPINA", "Ｐｏｔｅｎｔｉｌｌａ\u2003supina", "Potentilla\t\nsupina"])
def test_scientific_comparison_only(value):
    assert scientific_comparison_key(value) == "potentilla supina"


def test_chinese_comparison_preserves_number_and_description():
    assert chinese_comparison_key(" 球果群心菜（０６８）\u00a0 ") == "球果群心菜(068)"
    assert chinese_comparison_key("球果群心菜（068）") != chinese_comparison_key("球果群心菜")
    assert chinese_comparison_key("甘草") != chinese_comparison_key("乌拉尔甘草")


CASES = [("朝天委陵菜", "Potentilla supina", "Potentilla\u00a0supina"),
         ("短柄草", "Brachypodium sylvaticum", "Brachypodium\u2003sylvaticum"),
         ("柳叶马鞭草", "Verbena bonariensis", "Verbena_ bonariensis"),
         ("紫花针茅", "Stipa purpurea", "Stipa purpurea"),
         ("鹤虱", "Lappula myosotis", "Lappula myosotis"),
         ("甘草", "Glycyrrhiza uralensis", "Glycyrrhiza uralensis"),
         ("球果群心菜（068）", "Cardaria chalepensis", "Lepidium chalepense")]


@pytest.fixture
def historical_catalog(auth_client, tmp_path):
    client, headers = auth_client
    taxa, lots = [], []
    for i, (name, scientific, _) in enumerate(CASES):
        taxon = client.post("/api/taxa", headers=headers, json={"common_name": name, "scientific_name": scientific}).json()
        taxa.append(taxon)
        lots.append(client.post("/api/seed-lots", headers=headers, json={"taxon_id": taxon["id"], "source": "历史来源", "source_code": f"OLD{i}"}).json())
    client.post("/api/seed-lots", headers=headers, json={"taxon_id": taxa[4]["id"], "source": "另一来源"})
    engine = make_engine("sqlite:///" + (tmp_path / "test.db").as_posix())
    with Session(engine) as db, db.begin():
        for i, state in enumerate(["active", "cancelled", "draft", "completed", "completed", "completed", "completed"]):
            experiment = Experiment(code=f"GER-202610-{i+1:03d}", name="合成历史身份核对", status=state)
            db.add(experiment)
            db.flush()
            db.add(ExperimentMaterial(experiment_id=experiment.id, seed_lot_id=lots[i]["id"]))
    engine.dispose()
    yield client, headers, taxa, lots


def feedback_file():
    return material_file([row(scientific, None, "乌拉尔甘草" if i == 5 else name,
                              source="历史来源" if i in (4, 6) else "新来源")
                          for i, (name, _, scientific) in enumerate(CASES)])


@pytest.mark.parametrize("mode", ["complete", "new"])
def test_seven_feedback_cases_identity_and_history(historical_catalog, mode):
    client, headers, taxa, lots = historical_catalog
    report = preview(client, headers, feedback_file(), mode=mode)
    rows = report["rows"]
    assert [r["taxon_status"] for r in rows] == ["existing"] * 6 + ["confirm"]
    assert [r["material_status"] for r in rows] == ["new"] * 4 + ["confirm", "new", "pending"]
    assert [r["taxon_ger_status"] for r in rows] == ["active", "recorded", "recorded", "completed", "completed", "completed", "pending"]
    assert rows[3]["material_ger_status"] == "none"
    assert rows[4]["candidate_lots"][0]["id"] == lots[4]["id"]
    assert rows[5]["warnings"] and rows[5]["taxon_id"] == taxa[5]["id"]
    assert rows[6]["taxon_candidates"][0]["scientific_name"] == "Cardaria chalepensis"
    assert rows[6]["scientific_name"] == "Lepidium chalepense"
    assert report["stats"]["taxon_existing"] == 6 and report["stats"]["taxon_confirm"] == 1
    assert report["stats"]["taxon_with_ger"] == 6
    assert confirm(client, headers, feedback_file(), {"6": "new"}).status_code == 422


@pytest.mark.parametrize("choice", ["reuse", "new"])
def test_explicit_taxon_and_lot_decisions_are_independent(historical_catalog, choice):
    client, headers, taxa, lots = historical_catalog
    content = material_file([row("Lepidium chalepense", "OLD6", "球果群心菜（068）", source="历史来源")])
    taxon_decisions = {"2": f"reuse:{taxa[6]['id']}" if choice == "reuse" else "new"}
    reviewed = preview(client, headers, content, taxon_decisions=taxon_decisions)["rows"][0]
    assert reviewed["taxon_status"] == ("existing" if choice == "reuse" else "new")
    assert reviewed["taxon_ger_status"] == ("completed" if choice == "reuse" else "none")
    result = confirm(client, headers, content, taxon_decisions=taxon_decisions)
    assert result.status_code == 200, result.text
    assert result.json()["new_taxa"] == (0 if choice == "reuse" else 1)
    assert result.json()["new_lots"] == (0 if choice == "reuse" else 1)
    saved = client.get(f"/api/taxa/{taxa[6]['id']}").json()
    assert saved["scientific_name"] == "Cardaria chalepensis"


def test_normalized_existing_taxon_new_lot_preserves_display(historical_catalog):
    client, headers, taxa, lots = historical_catalog
    content = material_file([row("  GLYCYRRHIZA_uralensis  ", "NEW", "乌拉尔甘草", source="新来源")])
    result = confirm(client, headers, content)
    assert result.status_code == 200, result.text
    assert result.json()["new_taxa"] == 0 and result.json()["new_lots"] == 1
    lot = client.get(f"/api/seed-lots/{result.json()['created_seed_lot_ids'][0]}").json()
    assert lot["taxon_id"] == taxa[5]["id"]
    saved = client.get(f"/api/taxa/{taxa[5]['id']}").json()
    assert saved["common_name"] == "甘草" and saved["scientific_name"] == "Glycyrrhiza uralensis"


def test_missing_scientific_requires_reuse_and_invalid_code_blocks(historical_catalog):
    client, headers, taxa, lots = historical_catalog
    content = material_file([row(None, "OLD6", "球果群心菜（068）")])
    assert preview(client, headers, content)["rows"][0]["taxon_status"] == "confirm"
    assert confirm(client, headers, content, taxon_decisions={"2": "new"}).status_code == 422
    assert confirm(client, headers, content, taxon_decisions={"2": f"reuse:{taxa[0]['id']}"}).status_code == 422
    assert confirm(client, headers, content, taxon_decisions={"2": f"reuse:{taxa[6]['id']}"}).status_code == 200
    wrong = material_file([row("Lepidium chalepense", "NEW", taxon_code=taxa[6]["code"])])
    assert preview(client, headers, wrong)["rows"][0]["errors"]
    assert confirm(client, headers, wrong).status_code == 422


def test_normalization_collision_returns_all_candidates_and_rechecks(auth_client):
    client, headers = auth_client
    taxa = [client.post("/api/taxa", headers=headers, json={"scientific_name": name}).json()
            for name in ["Potentilla supina", "Potentilla_supina"]]
    content = material_file([row("Potentilla\u00a0supina", "A")])
    reviewed = preview(client, headers, content)["rows"][0]
    assert reviewed["taxon_status"] == "confirm"
    assert {t["id"] for t in reviewed["taxon_candidates"]} == {t["id"] for t in taxa}
    assert confirm(client, headers, content).status_code == 422
    assert confirm(client, headers, content, taxon_decisions={"2": "new"}).status_code == 422
    assert confirm(client, headers, content, taxon_decisions={"2": f"reuse:{taxa[1]['id']}"}).json()["new_taxa"] == 0


def test_confirmation_rechecks_changed_candidates_and_is_atomic(auth_client):
    client, headers = auth_client
    taxon = client.post("/api/taxa", headers=headers, json={"scientific_name": "Old species", "common_name": "同名"}).json()
    content = material_file([row("Valid new", "N"), row("Other species", "B", "同名")])
    assert preview(client, headers, content)["rows"][1]["taxon_status"] == "confirm"
    client.patch(f"/api/taxa/{taxon['id']}", headers=headers, json={"common_name": "改名"})
    response = confirm(client, headers, content, taxon_decisions={"3": f"reuse:{taxon['id']}"})
    assert response.status_code == 422
    assert client.get("/api/seed-lots").json() == []
