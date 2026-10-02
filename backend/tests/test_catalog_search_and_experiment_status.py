def test_material_and_seed_lot_search_use_all_taxon_names(auth_client):
    client, headers = auth_client
    taxon = client.post("/api/taxa", headers=headers,
                        json={"scientific_name": "Setaria viridis", "common_name": "狗尾草"}).json()
    lot = client.post("/api/seed-lots", headers=headers,
                      json={"taxon_id": taxon["id"], "source": "野外采集"}).json()
    for term in ("狗尾草", "Setaria", taxon["code"]):
        available = client.get("/api/experiments/available-seed-lots", params={"q": term}).json()
        assert len(available) == 1
        assert available[0]["id"] == lot["id"]
        assert available[0]["taxon_common_name"] == "狗尾草"
        assert available[0]["taxon_scientific_name"] == "Setaria viridis"
        assert available[0]["taxon_code"] == taxon["code"]
        assert "taxon_name" not in available[0]
        listed = client.get("/api/seed-lots", params={"q": term}).json()
        assert [item["id"] for item in listed] == [lot["id"]]
    for term in (lot["code"], "野外采集"):
        assert [item["id"] for item in client.get("/api/seed-lots", params={"q": term}).json()] == [lot["id"]]


def test_experiment_status_actions_keep_start_as_only_active_path(auth_client):
    client, headers = auth_client
    taxon = client.post("/api/taxa", headers=headers, json={"scientific_name": "Setaria viridis"}).json()
    lot = client.post("/api/seed-lots", headers=headers, json={"taxon_id": taxon["id"]}).json()
    experiment = client.post("/api/experiments/configured", headers=headers, json={
        "experiment_type": "GER", "name": "状态流程测试", "protocol": {"seeds_per_dish": 5, "replicate_count": 1,
        "observation_period_days": 7, "sampling_rule": "first_germinated", "sample_count": 1,
        "sample_scope": "per_dish", "germination_criterion": "胚根可见"},
        "materials": [{"seed_lot_id": lot["id"]}], "dag_days": [0, 3],
    }).json()["experiment"]
    path = f"/api/experiments/{experiment['id']}"
    assert client.patch(path, headers=headers, json={"status": "ready"}).json()["status"] == "ready"
    assert client.patch(path, headers=headers, json={"status": "draft"}).json()["status"] == "draft"
    assert client.patch(path, headers=headers, json={"status": "ready"}).json()["status"] == "ready"
    assert client.patch(path, headers=headers, json={"status": "active"}).status_code == 409
    numbered = client.post(f"{path}/confirm-numbers", headers=headers)
    assert numbered.status_code == 200
    started = client.post(f"{path}/sowing/batch", headers=headers,
                          json={"sown_at": "2026-10-01T08:00:00+08:00",
                                "dish_ids": [dish["id"] for dish in numbered.json()["dishes"]]})
    assert started.status_code == 200, started.text
    assert client.get(path).json()["status"] == "active"


def test_ready_action_explains_incomplete_configuration(auth_client):
    client, headers = auth_client
    experiment = client.post("/api/experiments", headers=headers, json={"experiment_type": "GER", "name": "尚未配置的实验"}).json()
    response = client.patch(f"/api/experiments/{experiment['id']}", headers=headers,
                            json={"status": "ready"})
    assert response.status_code == 422
    message = response.json()["detail"]
    assert "默认实验方案" in message
    assert "实验材料" in message
    assert "发芽后测定时间" in message
    assert client.get(f"/api/experiments/{experiment['id']}").json()["status"] == "draft"
