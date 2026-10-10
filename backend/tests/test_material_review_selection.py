"""Synthetic research inventory only; no user workbook is a Git fixture."""
import json

from test_material_import_and_execution import material_file, row, preview, confirm, config


def test_unique_populations_pending_and_explicit_material_choices(auth_client):
    client, headers = auth_client
    content = material_file([row('Species a', None, '甲', source='山地'),
                             row('Species a', None, '甲别名', source='山地'),
                             row('Species a', None, '甲', source='河岸'),
                             row('Species b', None, '乙', source='山地')])
    report = preview(client, headers, content, 'new')
    summary = report['experiment_selection_summary']
    assert summary['new_species_unique_count'] == 2
    assert summary['new_batch_unique_count'] == 3
    assert summary['pending_material_count'] == 1
    assert summary['species_groups'] == [[2, 3, 4], [5]]
    assert report['rows'][0]['selection_batch_group'] == report['rows'][1]['selection_batch_group']
    response = client.post('/api/import/materials/preview', headers=headers,
        data={'mode':'new', 'decisions':json.dumps({'3':'new'})}, files={'file':('synthetic.xlsx',content)})
    assert response.status_code == 200
    assert response.json()['experiment_selection_summary']['new_batch_unique_count'] == 4
    assert response.json()['experiment_selection_summary']['pending_material_count'] == 0


def test_unresolved_taxon_not_counted_and_reuse_removes_pending(auth_client):
    client, headers = auth_client
    seed = material_file([row('Old species', 'old', '同名', source='旧地')])
    confirm(client, headers, seed)
    content = material_file([row('Different species', None, '同名', source='新地')])
    report = preview(client, headers, content, 'new')
    summary = report['experiment_selection_summary']
    assert summary['pending_taxon_count'] == 1
    assert summary['new_species_unique_count'] == summary['new_batch_unique_count'] == 0
    taxon = report['rows'][0]['taxon_candidates'][0]['id']
    resolved = preview(client, headers, content, 'new', {'2':f'reuse:{taxon}'})
    assert resolved['experiment_selection_summary']['pending_taxon_count'] == 0
    assert resolved['rows'][0]['taxon_id'] == taxon


def test_common_name_explicit_update_is_atomic_and_preserves_identity(auth_client):
    client, headers = auth_client
    seeded = confirm(client, headers, material_file([row('Glycyrrhiza uralensis','original','甘草')])).json()
    lot_id = seeded['all_seed_lot_ids'][0]
    experiment = config(client, headers, [lot_id])['experiment']
    before_taxa = client.get('/api/taxa',headers=headers).json()
    content = material_file([row('Glycyrrhiza uralensis','original','乌拉尔甘草')])
    report = preview(client,headers,content)
    taxon_id = report['rows'][0]['taxon_id']
    assert report['rows'][0]['name_difference'] and report['rows'][0]['can_update_common_name']
    assert client.get('/api/taxa',headers=headers).json() == before_taxa
    response = client.post('/api/import/materials/confirm',headers=headers,
        data={'name_decisions':json.dumps({'2':'update'})},files={'file':('rename.xlsx',content)})
    assert response.status_code == 200, response.text
    assert response.json()['new_taxa'] == 0 and response.json()['new_lots'] == 0
    assert response.json()['all_seed_lot_ids'] == [lot_id]
    taxon = client.get(f'/api/taxa/{taxon_id}',headers=headers).json()
    assert taxon['common_name'] == '乌拉尔甘草' and taxon['scientific_name'] == 'Glycyrrhiza uralensis'
    after = client.get(f"/api/experiments/{experiment['id']}",headers=headers).json()
    assert after['id'] == experiment['id']
    assert client.get(f"/api/experiments/{experiment['id']}/configuration",headers=headers).json()['materials'][0]['seed_lot_id'] == lot_id
    audit = client.get('/api/audit-logs',headers=headers)
    assert audit.status_code == 200
    assert 'common_name' in audit.text and '乌拉尔甘草' in audit.text


def test_default_name_retained_and_conflicting_explicit_names_rejected(auth_client):
    client, headers = auth_client
    confirm(client,headers,material_file([row('Species a','A','旧名')]))
    report = preview(client,headers,material_file([row('Species a','A','新名')]))
    taxon_id = report['rows'][0]['taxon_id']
    result = confirm(client,headers,material_file([row('Species a','A','新名')]))
    assert result.status_code == 200
    assert client.get(f'/api/taxa/{taxon_id}',headers=headers).json()['common_name'] == '旧名'
    content = material_file([row('Species a','A','新名一'),row('Species a','B','新名二')])
    response = client.post('/api/import/materials/confirm',headers=headers,
        data={'name_decisions':json.dumps({'2':'update','3':'update'})},files={'file':('names.xlsx',content)})
    assert response.status_code == 422
    assert client.get(f'/api/taxa/{taxon_id}',headers=headers).json()['common_name'] == '旧名'
