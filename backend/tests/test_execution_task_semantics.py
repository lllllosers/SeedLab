"""Current execution tasks end with the experiment; historical facts do not."""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import Session

from app.models import Experiment
from app.services.measurement_query import slot_summary
from app.services.seedling_measurement import history
from test_measurement_history_ux import seed_history
from test_measurement_workflow_and_lifecycle import fixture_engine
from test_seedling_measurement import setup_experiment


@pytest.mark.parametrize('status', ['active', 'completed', 'cancelled'])
@pytest.mark.parametrize('explicit_zero', [False, True])
def test_inspection_tasks_do_not_change_unrecorded_or_zero_facts(auth_client, tmp_path, status, explicit_zero):
    client, headers = auth_client
    base, dish, _, _ = setup_experiment(client, headers, days=(0,))
    if explicit_zero:
        response = client.post(base + '/observations/batch', json={
            'observed_at': (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),
            'entries': [{'dish_id': dish['id'], 'new_germinated_count': 0}]}, headers=headers)
        assert response.status_code == 200
    before = client.get(base + '/execution').json()
    assert before['today_pending_count'] == 1
    engine = fixture_engine(tmp_path)
    try:
        with Session(engine) as db:
            experiment = db.get(Experiment, base.rsplit('/', 1)[1])
            experiment.status = status
            # Historical completion time is unknown; do not invent one.
            experiment.ended_at = None
            db.commit()
        result = client.get(base + '/execution').json()
        assert result['today_pending_count'] == (1 if status == 'active' else 0)
        for key in ('dishes', 'materials', 'recent_observations', 'sown_count',
                    'sample_count', 'observation_period_end_at'):
            assert result[key] == before[key]
        assert result['cumulative_germinated'] == (0 if explicit_zero else None)
        assert result['germination_rate'] == (0 if explicit_zero else None)
        assert result['dishes'][0]['remaining_ungerminated'] == (10 if explicit_zero else None)
    finally:
        engine.dispose()


@pytest.mark.parametrize('status', ['completed', 'cancelled', 'ready', 'draft'])
def test_inactive_work_queues_are_empty_but_records_and_missing_slots_remain(auth_client, tmp_path, status):
    client, _ = auth_client
    base, material_ids = seed_history(tmp_path)
    before_records = client.get(base + '/measurement-records', params={'page_size': 100}).json()
    assert before_records['total'] == 8
    engine = fixture_engine(tmp_path)
    try:
        with Session(engine) as db:
            experiment = db.get(Experiment, base.rsplit('/', 1)[1])
            before_slots = slot_summary(db, experiment.id)
            assert all(before_slots[key] > 0 for key in
                       ('due_today_count', 'overdue_count', 'upcoming_count', 'unschedulable_count'))
            before_history = history(db, experiment.id, material_ids[0])
            experiment.status = status
            experiment.ended_at = None
            db.commit()
            assert slot_summary(db, experiment.id) == before_slots
            assert history(db, experiment.id, material_ids[0]) == before_history
        for filter_status in ('pending', 'overdue', 'due_today', 'all'):
            response = client.get(base + '/measurement-worklist', params={'status': filter_status})
            assert response.status_code == 200
            queue = response.json()
            assert queue['materials'] == [] and queue['total_materials'] == queue['total_pages'] == 0
            assert all(value == 0 for value in queue['summary'].values())
            assert queue['dag_days'] == [0, 1, 3]
        for filter_status in (None, 'pending', 'overdue', 'upcoming', 'unschedulable', 'completed'):
            params = {} if filter_status is None else {'status': filter_status}
            tasks = client.get(base + '/measurement-tasks', params=params).json()
            assert tasks['tasks'] == [] and all(value == 0 for value in tasks['summary'].values())
        assert client.get(base + '/measurement-records', params={'page_size': 100}).json() == before_records
        assert client.get('/api/dashboard').json()['measurement']['experiments'] == []
        assert client.get(base + '/completion-check').json()['measurement_pending_count'] == 28
        assert client.get(base + '/measurement-worklist', params={'status': 'invalid'}).status_code == 422
    finally:
        engine.dispose()
