"""Stable identities, legacy upgrade, and user numbers across public workflows."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from io import BytesIO
from threading import Barrier

import pytest
from alembic import command
from alembic.config import Config
from openpyxl import load_workbook
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import make_engine
from app.models import Experiment
from app.services.experiment_identity import experiment_batch_month, next_experiment_code
from app.services.ordering import dish_display_number, sample_display_number
from app.services.database_upgrade import prepare_database_for_startup, read_revision
from test_experiment_config import design, make_lot
from test_seedling_measurement import setup_experiment, observe


def test_creation_scopes_and_identity_survive_edits(auth_client, tmp_path):
    client, headers = auth_client
    engine = make_engine(f"sqlite:///{(tmp_path / 'test.db').as_posix()}")
    with Session(engine) as db:
        db.add(Experiment(code="EXP-2026-099", name="历史实验"))
        db.commit()
    assert client.get('/api/experiments/types').json() == [{'value': 'GER', 'label': '种子萌发试验'}]
    _, lot = make_lot(client, headers)
    first = client.post('/api/experiments', headers=headers, json={
        'experiment_type': 'GER', 'name': '用户自由命名', 'planned_start_date': '2026-09-15'}).json()
    second = client.post('/api/experiments/configured', headers=headers,
        json=design(lot['id'], planned_start_date='2026-09-30')).json()['experiment']
    third = client.post('/api/experiments', headers=headers, json={
        'experiment_type': 'GER', 'name': '跨月实验', 'planned_start_date': '2026-10-01'}).json()
    assert [item['code'] for item in (first, second, third)] == [
        'GER-202609-001', 'GER-202609-002', 'GER-202610-001']
    assert second['experiment_type_label'] == '种子萌发试验'
    changed = client.patch('/api/experiments/' + first['id'], headers=headers,
        json={'name': '修改描述', 'planned_start_date': '2027-01-01'}).json()
    assert changed['code'] == first['code'] and changed['experiment_type'] == 'GER'
    for patch in ({'experiment_type': 'GER'}, {'experiment_type': 'ALT'}, {'code': 'OTHER'}):
        assert client.patch('/api/experiments/' + first['id'], headers=headers, json=patch).status_code == 422
    engine.dispose()


@pytest.mark.parametrize('route', ['/api/experiments', '/api/experiments/configured', '/api/experiments/estimate'])
def test_creation_requires_explicit_supported_type(auth_client, route):
    client, headers = auth_client
    _, lot = make_lot(client, headers)
    payload = design(lot['id'])
    payload.pop('experiment_type')
    assert client.post(route, headers=headers, json=payload).status_code == 422
    payload['experiment_type'] = 'ALT'
    assert client.post(route, headers=headers, json=payload).status_code == 422


def test_month_without_date_uses_laboratory_timezone(auth_client, monkeypatch):
    from app.services import local_time
    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 9, 30, 17, 0, tzinfo=timezone.utc).astimezone(tz)
    monkeypatch.setattr(local_time, 'datetime', FrozenDatetime)
    assert get_settings().seedlab_timezone == 'Asia/Shanghai'
    assert experiment_batch_month(None) == '202610'
    assert experiment_batch_month(date(2020, 2, 3)) == '202002'
    client, headers = auth_client
    response = client.post('/api/experiments', headers=headers,
        json={'experiment_type': 'GER', 'name': '无计划日期'})
    assert response.status_code == 201 and response.json()['code'] == 'GER-202610-001'


def test_allocator_has_independent_type_and_month_parameters():
    # Future type support needs a real workflow/schema extension, not a new allocator.
    class NumberingStore:
        def scalars(self, statement):
            params = statement.compile().params
            kind = params['experiment_type_1']
            prefix = params['code_1'].removesuffix('%')
            return [value for type_, value in [('GER', 'GER-202609-005'), ('ALT', 'ALT-202609-002')]
                    if type_ == kind and value.startswith(prefix)]
    store = NumberingStore()
    assert next_experiment_code(store, 'GER', '202609') == 'GER-202609-006'
    assert next_experiment_code(store, 'ALT', '202609') == 'ALT-202609-003'
    assert next_experiment_code(store, 'GER', '202610') == 'GER-202610-001'


@pytest.mark.parametrize('configured', [False, True])
def test_concurrent_candidate_collision_rolls_back_entire_request(auth_client, tmp_path, monkeypatch, configured):
    from app.api import experiments
    from app.services import experiment_config
    client, headers = auth_client
    _, lot = make_lot(client, headers)
    target = experiment_config if configured else experiments
    allocate = target.next_experiment_code
    barrier = Barrier(2)
    def synchronized(*args):
        candidate = allocate(*args)
        barrier.wait(timeout=10)
        return candidate
    monkeypatch.setattr(target, 'next_experiment_code', synchronized)
    payload = design(lot['id'], planned_start_date='2026-09-15') if configured else {
        'experiment_type': 'GER', 'name': '并发创建', 'planned_start_date': '2026-09-15'}
    route = '/api/experiments/configured' if configured else '/api/experiments'
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: client.post(route, headers=headers, json=payload), range(2)))
    assert sorted(result.status_code for result in results) == [201, 409]
    engine = make_engine(f"sqlite:///{(tmp_path / 'test.db').as_posix()}")
    with engine.connect() as conn:
        assert conn.exec_driver_sql('SELECT code FROM experiments').all() == [('GER-202609-001',)]
        assert conn.exec_driver_sql("SELECT count(*) FROM audit_logs WHERE entity_type='Experiment'").scalar() == 1
        assert conn.exec_driver_sql('SELECT count(*) FROM experiment_materials').scalar() == int(configured)
    engine.dispose()


@pytest.mark.parametrize('replicates, dish_number, sample_number', [(1, '001', '001-01'), (2, '001-1', '001-1-01')])
def test_user_numbers_in_tasks_search_export_errors_and_audit(auth_client, replicates, dish_number, sample_number):
    client, headers = auth_client
    base, dish, taxon, lot = setup_experiment(client, headers, replicates=replicates)
    now = datetime.now(timezone.utc)
    sample = observe(client, headers, base, dish, now)
    assert sample['field_number'] == dish_number
    assert sample['sample_display_number'] == sample_number
    tasks = client.get(base + '/measurement-tasks').json()['tasks']
    first = next(task for task in tasks if task['sample_id'] == sample['id'])
    assert first['sample_display_number'] == sample_number
    assert client.post(base + '/measurements', headers=headers, json={
        'sample_id': first['sample_id'], 'timepoint_id': first['timepoint_id'],
        'root_length_mm': 0, 'shoot_length_mm': 2, 'measured_at': now.isoformat()}).status_code == 201
    found = client.get(base + '/measurement-records', params={'q': sample_number}).json()['items']
    assert len(found) == 1 and found[0]['sample_display_number'] == sample_number
    assert client.get(base + '/measurement-records', params={'q': dish['code']}).json()['items'] == []
    history = client.get(base + '/measurement-history/' + first['material_id']).json()
    assert history['samples'][0]['sample_display_number'] == sample_number
    exported = client.post('/api/export/experiments/workbook.xlsx', headers=headers,
        json={'experiment_ids': [base.rsplit('/', 1)[-1]]})
    assert exported.status_code == 200
    book = load_workbook(BytesIO(exported.content))
    for sheet_name in ('04_幼苗测定长表', '05_幼苗测定宽表'):
        rows = list(book[sheet_name].values)
        assert rows[1][3:5] == (dish_number, sample_number)
    assert '系统培养皿编号' not in [cell.value for cell in book['03_发芽原始记录'][1]]
    assert dish['code'] not in str([list(sheet.values) for sheet in book])
    book.close()
    audit = client.get('/api/audit-logs', params={'page_size': 100}).json()['items']
    assert any(sample_number in item['subject_label'] for item in audit if item['entity_type'] == 'SeedlingMeasurement')
    assert all(dish['code'] not in item['subject_label'] for item in audit)
    assert client.get('/api/audit-logs', params={'q': dish['code']}).json()['items'] == []
    failed = client.post(base + '/observations/batch', headers=headers, json={
        'observed_at': now.isoformat(), 'entries': [{'dish_id': dish['id'], 'new_germinated_count': 999}]})
    assert failed.status_code == 422 and dish_number in failed.json()['detail']
    assert dish['code'] not in failed.text
    assert client.patch('/api/taxa/' + taxon['id'], headers=headers, json={'common_name': '改名'}).json()['code'] == taxon['code'] == 'SP-0001'
    assert client.patch('/api/seed-lots/' + lot['id'], headers=headers, json={'source': '修改来源'}).json()['code'] == lot['code']
    assert client.get(base + '/configuration').json()['materials'][0]['experiment_number'] == 1


def test_formatters_include_single_multi_and_large_sequence():
    assert dish_display_number(1, 1, 1) == '001'
    assert dish_display_number(999, 10, 10) == '999-10'
    assert sample_display_number(1, 1, 1, 10) == '001-10'
    assert sample_display_number(1, 2, 3, 1) == '001-2-01'
    assert sample_display_number(None, 1, 1, 1) is None


@pytest.mark.parametrize('legacy', [False, True])
def test_v041_upgrade_and_roundtrip_preserve_existing_identities(tmp_path, monkeypatch, legacy):
    url = f"sqlite:///{(tmp_path / 'upgrade.db').as_posix()}"
    monkeypatch.setenv('SEEDLAB_DATABASE_URL', url)
    get_settings.cache_clear()
    config = Config('alembic.ini')
    command.upgrade(config, 'c6d91f28a405')
    engine = make_engine(url)
    if legacy:
        with engine.begin() as conn:
            conn.exec_driver_sql("INSERT INTO experiments(id,created_at,code,name,status) VALUES ('exp','2026-09-01','EXP-2026-001','旧实验','active')")
            conn.exec_driver_sql("INSERT INTO taxa(id,created_at,code,scientific_name,is_active) VALUES ('taxon','2026-09-01','SP-0001','Setaria viridis',1)")
            conn.exec_driver_sql("INSERT INTO seed_lots(id,created_at,code,taxon_id,is_active) VALUES ('lot','2026-09-01','LOT-2026-001','taxon',1)")
            conn.exec_driver_sql("INSERT INTO experiment_materials(id,created_at,experiment_id,seed_lot_id,display_order,experiment_number) VALUES ('material','2026-09-01','exp','lot',0,1)")
            conn.exec_driver_sql("INSERT INTO germination_dishes(id,created_at,material_id,code,replicate_no,label,seed_count) VALUES ('dish','2026-09-01','material','EXP-2026-001-M001-R01',1,'R1',20)")
            conn.exec_driver_sql("INSERT INTO germination_observations(id,created_at,dish_id,observed_at,new_germinated_count,notes) VALUES ('observation','2026-09-01','dish','2026-09-01',1,'原巡检事实')")
            conn.exec_driver_sql("INSERT INTO seedling_samples(id,created_at,dish_id,sample_number,germinated_at) VALUES ('sample','2026-09-01','dish',1,'2026-09-01')")
            conn.exec_driver_sql("UPDATE seedling_samples SET source_observation_id='observation'")
            conn.exec_driver_sql("INSERT INTO measurement_timepoints(id,created_at,experiment_id,day_after_germination) VALUES ('point','2026-09-01','exp',3)")
            conn.exec_driver_sql("INSERT INTO seedling_measurements(id,created_at,sample_id,timepoint_id,root_length_mm,shoot_length_mm,root_unavailable,shoot_unavailable,measured_at) VALUES ('measurement','2026-09-04','sample','point',0,2,0,0,'2026-09-04')")
            conn.exec_driver_sql("INSERT INTO audit_logs(id,created_at,action,entity_type,entity_id) VALUES ('audit','2026-09-01','create','Experiment','exp')")
    result = prepare_database_for_startup(url, 'alembic', backup_root=tmp_path / 'backups')
    assert result.migrated and read_revision(result.snapshot, immutable=True) == 'c6d91f28a405'
    command.current(config)
    command.check(config)
    with engine.connect() as conn:
        assert conn.exec_driver_sql('PRAGMA foreign_key_check').all() == []
        assert conn.exec_driver_sql('SELECT version_num FROM alembic_version').scalar() == 'd2e7a46b910c'
        if legacy:
            assert conn.exec_driver_sql('SELECT code,experiment_type FROM experiments').all() == [('EXP-2026-001', 'GER')]
            assert conn.exec_driver_sql('SELECT root_length_mm,shoot_length_mm FROM seedling_measurements').all() == [(0, 2)]
            assert conn.exec_driver_sql('SELECT code FROM germination_dishes').scalar() == 'EXP-2026-001-M001-R01'
            assert conn.exec_driver_sql('SELECT new_germinated_count,notes FROM germination_observations').all() == [(1, '原巡检事实')]
            assert conn.exec_driver_sql('SELECT source_observation_id FROM seedling_samples').scalar() == 'observation'
            assert conn.exec_driver_sql('SELECT action,entity_type,entity_id FROM audit_logs').all() == [('create','Experiment','exp')]
    for invalid in ('ALT', None):
        with pytest.raises(IntegrityError), engine.begin() as conn:
            conn.exec_driver_sql("INSERT INTO experiments(id,created_at,code,name,status,experiment_type) VALUES ('bad','2026-09-01','BAD','拒绝类型','draft',?)", (invalid,))
    command.downgrade(config, 'c6d91f28a405')
    command.upgrade(config, 'head')
    command.check(config)
    with Session(engine) as db:
        assert next_experiment_code(db, 'GER', '202609') == 'GER-202609-001'
    with engine.connect() as conn:
        assert conn.exec_driver_sql('PRAGMA foreign_key_check').all() == []
        if legacy:
            assert conn.exec_driver_sql('SELECT code,experiment_type FROM experiments').all() == [('EXP-2026-001', 'GER')]
            assert conn.exec_driver_sql('SELECT count(*) FROM seedling_measurements').scalar() == 1
    engine.dispose()
    get_settings.cache_clear()
