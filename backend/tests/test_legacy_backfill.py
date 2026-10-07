"""Source integration is opt-in; the original workbook is never checked into Git."""
import hashlib
import os
from pathlib import Path
import sqlite3
import sys

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy.orm import Session

from app.db.session import make_engine
from app.models import User

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts' / 'maintenance'))
import backfill_legacy_200_species as legacy
from app.services.germination_execution import execution_summary
from app.services.measurement_query import dashboard, records, slot_summary, task_summary, worklist
from app.services.seedling_measurement import task_data
from app.services.migrations import check_database_schema
from app.analysis import read_dataset
from app.services.measurement_slots import MeasurementDatasetReader


def assert_historical_dataset(db, experiment_id):
    dataset = read_dataset(MeasurementDatasetReader(db), [experiment_id])
    assert len({slot.material_id for slot in dataset.seedling_slots}) == 200
    assert len(dataset.seedling_slots) == 2000 and len(dataset.rows) == 6000
    assert sum(slot.sample_id is not None for slot in dataset.seedling_slots) == 1665
    assert sum(row.measurement_exists for row in dataset.rows) == 4955
    assert sum(not row.measurement_exists and row.slot.sample_id is not None for row in dataset.rows) == 40
    assert sum(row.slot.sample_id is None for row in dataset.rows) == 1005
    assert sum(row.root_length_mm == 0 for row in dataset.rows) == 6
    assert sum(row.shoot_length_mm == 0 for row in dataset.rows) == 283
    assert all(row.scheduled_date is None for row in dataset.rows if row.slot.sample_id is None)
    assert not db.new and not db.dirty and not db.deleted


@pytest.fixture(scope='module')
def source_path():
    value = os.environ.get('SEEDLAB_LEGACY_SOURCE')
    if not value:
        pytest.skip('Set SEEDLAB_LEGACY_SOURCE for read-only original-workbook integration')
    return Path(value)


@pytest.fixture(scope='module')
def source_data(source_path):
    return legacy.read_source(source_path)


@pytest.fixture
def temporary_target(tmp_path):
    path = tmp_path / 'seedlab.db'
    url = f'sqlite:///{path.as_posix()}'
    config = Config(str(legacy.BACKEND / 'alembic.ini'))
    config.set_main_option('script_location', str(legacy.BACKEND / 'alembic'))
    config.attributes['database_url'] = url
    command.upgrade(config, 'head')
    engine = make_engine(url)
    with Session(engine) as db:
        user = User(username='legacy-test-owner', display_name='临时测试负责人', password_hash='test-only')
        db.add(user)
        db.commit()
        owner_id = user.id
    engine.dispose()
    return path, owner_id


def test_formal_and_nontemporary_targets_are_rejected(tmp_path):
    outside = Path(__file__).resolve().parents[2] / '.test-temp-legacy' / 'test.db'
    with pytest.raises(ValueError, match='系统临时目录'):
        legacy.temporary_database(outside)
    with pytest.raises(ValueError, match='SeedLabData'):
        legacy.temporary_database(tmp_path / 'SeedLabData' / 'seedlab.db')
    root = tmp_path / 'runtime'
    root.mkdir()
    (root / 'installation.json').write_text('{}', encoding='utf8')
    with pytest.raises(ValueError, match='运行中的数据目录'):
        legacy.temporary_database(root / 'seedlab.db')
    missing = tmp_path / 'never-created.db'
    with pytest.raises(ValueError, match='请先'):
        legacy.temporary_database(missing)
    assert not missing.exists()


def test_wrong_source_hash_is_rejected_without_database_access(tmp_path, capsys):
    source = tmp_path / 'synthetic-invalid.xlsx'
    source.write_bytes(b'not the original workbook')
    missing = tmp_path / 'never-created.db'
    assert legacy.main(['--source', str(source), '--database', str(missing), '--owner', 'test']) == 1
    assert 'SHA256' in capsys.readouterr().err
    assert not missing.exists()


def test_owner_validation_is_read_only(temporary_target):
    path, _ = temporary_target
    before = path.read_bytes()
    with pytest.raises(ValueError, match='负责人'):
        legacy.inspect_target(path, 'missing-owner')
    assert path.read_bytes() == before
    assert not Path(str(path) + '-wal').exists()
    assert not Path(str(path) + '-shm').exists()


def test_original_source_baseline_and_empty_samples(source_data):
    assert {key: source_data.metrics[key] for key in legacy.EXPECTED} == legacy.EXPECTED
    assert source_data.metrics['all_dag_empty_samples'] == [[27, n] for n in range(1, 11)]
    names = {m.number: m.scientific_name for m in source_data.materials}
    assert names[33] == names[153] == 'Lepidium apetalum'
    assert names[55] == names[56] == 'Lappula myosotis'
    assert {k: names[k] for k in legacy.SCIENTIFIC_NAMES} == legacy.SCIENTIFIC_NAMES
    obtained = {m.number: sum(s.material_number == m.number for s in source_data.samples) for m in source_data.materials}
    assert obtained[51] == 10
    assert sum(n == 0 for n in obtained.values()) == 21
    assert sum(0 < n < 10 for n in obtained.values()) == 20
    assert sum(10-n for n in obtained.values()) == 335


def test_default_dry_run_apply_and_repeat_rejection(source_path, source_data, temporary_target, capsys):
    path, _ = temporary_target
    before = path.read_bytes()
    with source_path.open('rb') as stream:
        source_hash_before = hashlib.file_digest(stream, 'sha256').hexdigest()
    args = ['--source', str(source_path), '--database', str(path), '--owner', 'legacy-test-owner']
    assert legacy.main(args) == 0
    assert 'dry-run' in capsys.readouterr().out
    assert path.read_bytes() == before
    assert not Path(str(path) + '-wal').exists() and not Path(str(path) + '-shm').exists()
    apply_args = ['--source', str(source_path), '--data-root', str(path.parent), '--owner', 'legacy-test-owner', '--apply']
    assert legacy.main(apply_args) == 0
    result = capsys.readouterr().out
    assert 'GER-202608-001' in result and '"wide_rows": 2000' in result and '"long_rows": 6000' in result
    engine = make_engine(f'sqlite:///{path.as_posix()}')
    check_database_schema(f'sqlite:///{path.as_posix()}', legacy.BACKEND / 'alembic')
    with engine.connect() as connection:
        assert connection.exec_driver_sql('SELECT version_num FROM alembic_version').scalar() == 'd2e7a46b910c'
        assert connection.exec_driver_sql('PRAGMA integrity_check').all() == [('ok',)]
        assert connection.exec_driver_sql('PRAGMA foreign_key_check').all() == []
    with Session(engine) as db:
        experiment = db.query(legacy.Experiment).one()
        assert experiment.experiment_type == 'GER'
        assert db.query(legacy.ExperimentProtocol).one().observation_period_days is None
        assert legacy.reconcile_database(db, source_data, experiment)['value_differences'] == 0
        assert_historical_dataset(db, experiment.id)
        report = legacy.reconcile_workbook(legacy.build(db, [experiment.id]), source_data)
        from test_measurement_dataset import workbook_digest
        # Full six-sheet content digest captured before AF-4's dataset adapter.
        assert workbook_digest(legacy.build(db, [experiment.id])) == '7b5ff6d69409b209bd86b060cd19b7ffa4c2da1459c424624d11ef578b121c60'
        assert report['value_differences'] == 0
        assert report['all_dag_empty_actual_rows'] == 10 and report['all_dag_empty_rows'] == 345
        assert (report['planned_sample_slots'], report['planned_measurement_slots'], report['obtained_sample_slots'],
            report['measured_slots'], report['absent_sample_slots'], report['unmeasured_actual_slots'],
            report['absent_sample_measurement_slots']) == (2000, 6000, 1665, 4955, 335, 40, 1005)
    engine.dispose()
    assert legacy.main(args + ['--apply']) == 1
    assert '已有业务数据' in capsys.readouterr().err
    with source_path.open('rb') as stream:
        assert hashlib.file_digest(stream, 'sha256').hexdigest() == source_hash_before == legacy.SOURCE_SHA256


def test_validation_failure_rolls_back_all_business_rows(source_data, temporary_target, monkeypatch):
    path, owner_id = temporary_target
    def fail(*args):
        raise ValueError('injected export validation failure')
    monkeypatch.setattr(legacy, 'reconcile_workbook', fail)
    with pytest.raises(ValueError, match='injected'):
        legacy.apply(source_data, legacy.temporary_database(path), owner_id)
    with sqlite3.connect(path) as db:
        assert all(db.execute(f'SELECT count(*) FROM {table}').fetchone()[0] == 0 for table in legacy.BUSINESS_TABLES)
        assert db.execute('SELECT count(*) FROM audit_logs').fetchone()[0] == 0
        assert db.execute('SELECT count(*) FROM users').fetchone()[0] == 1


@pytest.mark.parametrize('status', ['completed', 'cancelled'])
def test_ended_historical_experiment_preserves_facts_and_export_without_current_tasks(
        source_path, source_data, temporary_target, status):
    path, owner_id = temporary_target
    source_before = hashlib.sha256(source_path.read_bytes()).hexdigest()
    legacy.apply(source_data, legacy.temporary_database(path), owner_id)
    engine = make_engine(f'sqlite:///{path.as_posix()}')
    try:
        with Session(engine) as db:
            experiment = db.query(legacy.Experiment).one()
            experiment.status = status
            experiment.ended_at = None
            db.commit()
            report = legacy.reconcile_database(db, source_data, experiment, expected_status=status)
            assert report['value_differences'] == 0
            assert report['missing_subtraction'] == report['missing_enumeration'] == 40
            assert report['root_zeros'] == 6 and report['shoot_zeros'] == 283
            assert experiment.ended_at is None
            assert_historical_dataset(db, experiment.id)
            assert slot_summary(db, experiment.id)['overdue_count'] == 40
            assert all(value == 0 for value in task_summary(db, experiment.id).values())
            execution = execution_summary(db, experiment.id)
            assert execution['today_pending_count'] == 0
            assert execution['cumulative_germinated'] is execution['germination_rate'] is None
            assert execution['sample_count'] == 1665 and execution['sown_count'] == 200
            assert execution['recent_observations'] == []
            for task_status in ('pending', 'overdue', 'due_today', 'all'):
                queue = worklist(db, experiment.id, status=task_status)
                assert queue['materials'] == [] and queue['total_materials'] == 0
            assert task_data(db, experiment.id)['tasks'] == []
            assert dashboard(db) == {'due_today_count': 0, 'overdue_count': 0, 'experiments': []}
            history = records(db, experiment.id)
            assert history['total'] == 4955 and len(history['items']) == 50
            assert records(db, experiment.id, dag=3)['total'] == 1655
            assert records(db, experiment.id, dag=7)['total'] == 1655
            assert records(db, experiment.id, dag=14)['total'] == 1645
            exported = legacy.reconcile_workbook(legacy.build(db, [experiment.id]), source_data)
            assert exported['value_differences'] == 0
            assert (exported['wide_rows'], exported['long_rows'], exported['measured_slots'],
                    exported['unmeasured_actual_slots'], exported['absent_sample_measurement_slots']) == (
                        2000, 6000, 4955, 40, 1005)
            assert exported['all_dag_empty_actual_rows'] == 10
            assert exported['root_zeros'] == 6 and exported['shoot_zeros'] == 283
    finally:
        engine.dispose()
    assert hashlib.sha256(source_path.read_bytes()).hexdigest() == source_before == legacy.SOURCE_SHA256
