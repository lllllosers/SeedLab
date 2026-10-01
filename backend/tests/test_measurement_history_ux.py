"""Structural history order and separation of recorded values from progress slots."""
from datetime import datetime, timedelta, timezone
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models import (Experiment, ExperimentMaterial, ExperimentProtocol, GerminationDish,
    MeasurementTimepoint, SeedlingSample, SeedlingMeasurement, SeedLot, Taxon)
from test_stage31_closeout import fixture_engine


def seed_history(tmp_path):
    engine = fixture_engine(tmp_path)
    now = datetime.now(timezone.utc)
    with Session(engine) as db:
        experiment = Experiment(code='EXP-HISTORY', name='测定进度验收', status='active', numbering_locked_at=now)
        db.add(experiment); db.flush()
        db.add(ExperimentProtocol(experiment_id=experiment.id, seeds_per_dish=20, replicate_count=2,
            observation_period_days=30, sampling_rule='first_germinated', sample_count=3,
            sample_scope='per_dish', germination_criterion='胚根可见'))
        points = {}
        for day in (0, 1, 3):
            point = MeasurementTimepoint(experiment_id=experiment.id, day_after_germination=day)
            db.add(point); db.flush(); points[day] = point.id
        material_ids, counter = [], 0
        for number in (1, 2):
            taxon = Taxon(code=f'SP-H{number}', scientific_name=f'Aster history {number}', common_name=f'狗娃花{number}')
            db.add(taxon); db.flush()
            lot = SeedLot(code=f'LOT-H{number}', taxon_id=taxon.id)
            db.add(lot); db.flush()
            material = ExperimentMaterial(experiment_id=experiment.id, seed_lot_id=lot.id,
                experiment_number=number, display_order=number-1)
            db.add(material); db.flush(); material_ids.append(material.id)
            for replicate in (1, 2):
                dish = GerminationDish(material_id=material.id, code=f'H{number}-{replicate}', replicate_no=replicate,
                    label=f'R{replicate}', seed_count=20, sown_at=now-timedelta(days=20))
                db.add(dish); db.flush()
                for sample_number in (1, 2, 3):
                    germinated_at = now-timedelta(days=5 if sample_number == 1 else 1) if sample_number != 3 else None
                    sample = SeedlingSample(dish_id=dish.id, sample_number=sample_number, germinated_at=germinated_at)
                    db.add(sample); db.flush()
                    days = (0, 3) if (replicate, sample_number) == (1, 1) else (0,) if (replicate, sample_number) == (1, 2) else (1,) if (replicate, sample_number) == (2, 1) else ()
                    for day in days:
                        counter += 1
                        db.add(SeedlingMeasurement(sample_id=sample.id, timepoint_id=points[day],
                            root_length_mm=0 if day == 0 else 2.5, shoot_length_mm=None if day == 0 else 3,
                            shoot_unavailable=day == 0, measured_at=now-timedelta(minutes=counter), notes='原始记录'))
        db.commit()
        experiment_id = experiment.id
    engine.dispose()
    return '/api/experiments/' + experiment_id, material_ids


def test_material_progress_all_states_but_global_records_only_facts_in_structural_order(auth_client, tmp_path):
    client, headers = auth_client
    base, ids = seed_history(tmp_path)
    tasks = client.get(base + '/measurement-tasks', params={'material_id': ids[0]}).json()['tasks']
    assert len(tasks) == 18 and sum(bool(task['measurement_id']) for task in tasks) == 4
    assert {task['status'] for task in tasks} == {'completed', 'due_today', 'overdue', 'upcoming', 'unschedulable'}
    record = next(task for task in tasks if task['measurement_id'] and task['day_after_germination'] == 0)
    assert record['root_length_mm'] == 0 and record['shoot_length_mm'] is None and record['shoot_unavailable']
    assert all(task['root_length_mm'] is None and task['shoot_length_mm'] is None for task in tasks if not task['measurement_id'])
    response = client.get(base + '/measurement-records').json()
    records = response['items']
    assert response['total'] == 8 and all(task['measurement_id'] for task in records)
    key = lambda task: (int(task['experiment_number']), task['replicate_no'], task['sample_number'], task['day_after_germination'])
    assert list(map(key, records)) == sorted(map(key, records))
    # Timestamps deliberately run backwards within the structural order.
    assert records[0]['measured_at'] > records[1]['measured_at']
    filtered = client.get(base + '/measurement-records', params={'q': '001'}).json()
    assert list(map(key, filtered['items'])) == [(1, 1, 1, 0), (1, 1, 1, 3), (1, 1, 2, 0), (1, 2, 1, 1)]
    paged = []
    for page in range(1, 5):
        paged.extend(client.get(base + '/measurement-records', params={'page': page, 'page_size': 2}).json()['items'])
    assert [task['measurement_id'] for task in paged] == [task['measurement_id'] for task in records]
    saved = client.patch(base + '/measurements/' + record['measurement_id'], json={'notes': '已核对'}, headers=headers)
    assert saved.status_code == 200 and saved.json()['notes'] == '已核对'
    assert client.get(base + '/measurement-records').json()['total'] == 8
