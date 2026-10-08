"""Detached canonical data and workbook content regression, without statistics."""
from collections import Counter
from dataclasses import FrozenInstanceError, fields, is_dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
import hashlib
import json

from openpyxl import load_workbook
import pytest
from sqlalchemy import event, inspect, select

from app.analysis import DatasetReader, read_dataset
from app.contracts.measurement_dataset import MeasurementDataset
from app.db.base import Base
from app.models import ExperimentMaterial, SeedlingMeasurement, SeedlingSample, SeedLot
from app.services.measurement_slots import MeasurementDatasetReader, build_measurement_dataset, build_measurement_slots
from app.services.workbook_export import build
from app.version import VERSION
from test_planned_measurement_slots import design, obtained


def workbook_digest(output):
    book = load_workbook(output, data_only=True)
    try:
        content = []
        for sheet in book:
            rows = []
            for row in sheet.values:
                if sheet.title == '06_导出说明' and row[0] == '导出时间':
                    continue
                row = list(row)
                if sheet.title == '06_导出说明' and row[0] == '软件版本':
                    # Assert the live release identity, then normalize only this
                    # metadata cell to the accepted AF-3/AF-4 baseline version.
                    assert row[1] == VERSION
                    row[1] = '0.5.1'
                rows.append(row)
            content.append((sheet.title, rows))
        return hashlib.sha256(json.dumps(content, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()
    finally:
        book.close()


@pytest.mark.parametrize('status', ['active', 'completed', 'cancelled'])
@pytest.mark.parametrize('actual', [False, True], ids=['zero-germination', 'partial-values'])
def test_workbook_content_matches_af3_baseline(design, status, actual):
    db, experiment, _, _, dish, points = design
    experiment.status = status
    if actual:
        for number, root, shoot, root_na, shoot_na in (
            (1, 0, None, False, True), (2, None, 12.5, True, False),
            (3, None, None, True, True), (4, 1.25, 0, False, False)):
            sample = obtained(db, dish, number)
            db.add(SeedlingMeasurement(sample_id=sample.id, timepoint_id=points[0].id,
                root_length_mm=root, shoot_length_mm=shoot, root_unavailable=root_na,
                shoot_unavailable=shoot_na, measured_at=sample.germinated_at + timedelta(days=3)))
        obtained(db, dish, 5)
    db.commit()
    digest = workbook_digest(build(db, [experiment.id]))
    # Captured from accepted AF-3 before changing the export consumer; all six
    # research sheets/cells are included; time is omitted and release metadata
    # is asserted separately before normalization. Original digests stay fixed.
    expected = ('04266618548f0484007b4bb17b2f30053bbb866445cdff1eeeef2e6f729e5f80'
                if actual else '956917bd03918896dc7c138a2c03f37f82c175e9897912332a8a523b1b3d5a15')
    assert digest == expected


def fact_snapshot(db):
    return {table.name: tuple(db.execute(select(table).order_by(*table.primary_key.columns)).all())
            for table in Base.metadata.sorted_tables}


def assert_detached(value):
    if is_dataclass(value):
        assert inspect(value, raiseerr=False) is None
        for field in fields(value):
            assert_detached(getattr(value, field.name))
    elif isinstance(value, tuple):
        for item in value:
            assert_detached(item)
    else:
        assert value is None or isinstance(value, (str, int, bool, Decimal, date, datetime))


def test_dataset_and_analysis_read_detached_facts_on_readonly_connection(design):
    db, experiment, _, material, dish, points = design
    first = obtained(db, dish, 1)
    second = obtained(db, dish, 2)
    third = obtained(db, dish, 3)
    obtained(db, dish, 4)
    for sample, root, shoot, root_na, shoot_na in (
        (first, 0, None, False, True), (second, None, 12.5, True, False),
        (third, None, None, True, True)):
        db.add(SeedlingMeasurement(sample_id=sample.id, timepoint_id=points[0].id,
            root_length_mm=root, shoot_length_mm=shoot, root_unavailable=root_na,
            shoot_unavailable=shoot_na, measured_at=sample.germinated_at + timedelta(days=3)))
    db.commit()
    before = fact_snapshot(db)
    db.connection().exec_driver_sql('PRAGMA query_only=ON')
    dataset = read_dataset(MeasurementDatasetReader(db), [experiment.id])
    assert isinstance(dataset, MeasurementDataset)
    assert_detached(dataset)
    assert len(dataset.seedling_slots) == 10 and len(dataset.rows) == 30
    assert Counter(row.data_status for row in dataset.rows) == {
        '已测定': 3, '无测定记录': 9, '无实际幼苗': 18}
    day3 = [row for row in dataset.rows if row.stage.day_after_germination == 3]
    assert [(r.root_length_mm, r.shoot_length_mm, r.root_unavailable, r.shoot_unavailable) for r in day3[:5]] == [
        (Decimal(0), None, False, True), (None, Decimal('12.5'), True, False),
        (None, None, True, True), (None, None, None, None), (None, None, None, None)]
    assert day3[0].measurement_exists and day3[2].measurement_exists
    assert not day3[3].measurement_exists and day3[3].slot.sample_id is not None
    assert day3[4].slot.sample_id is None and day3[4].scheduled_date is None
    assert day3[0].slot.material_id == material.id and day3[0].slot.experiment_id == experiment.id
    assert day3[0].slot.sample_id == first.id and day3[0].slot.seedling_number == '001-01'
    assert day3[0].scheduled_date == date(2026, 8, 11)
    assert [r.stage.day_after_germination for r in dataset.rows[:3]] == [3, 7, 14]
    assert all(slot.key == (material.id, 1, n) for n, slot in enumerate(dataset.seedling_slots, 1))
    assert set(name for name in vars(DatasetReader) if not name.startswith('_')) == {'read'}
    assert set(name for name in vars(MeasurementDatasetReader) if not name.startswith('_')) == {'read'}
    with pytest.raises(FrozenInstanceError):
        day3[0].root_length_mm = Decimal(100)
    with pytest.raises(FrozenInstanceError):
        day3[0].slot.sample_id = None
    assert fact_snapshot(db) == before
    assert not db.new and not db.dirty and not db.deleted
    db.expunge_all()
    db.close()
    # Entire dataset remains usable without a database or ORM lazy loading.
    assert dataset.rows[0].root_length_mm == 0 and dataset.seedling_slots[0].sample_id == first.id


def test_dataset_never_autoflushes_callers_pending_fact_changes(design):
    db, experiment, _, _, dish, _ = design
    obtained(db, dish, 1)
    db.commit()
    sample = db.scalar(select(SeedlingSample))
    sample.position_label = '尚未保存的标签'
    pending = SeedlingSample(dish_id=dish.id, sample_number=2, germinated_at=datetime(2026, 8, 9))
    db.add(pending)
    statements = []
    def capture(_, __, statement, *args):
        statements.append(statement)
    connection = db.connection()
    event.listen(connection, 'before_cursor_execute', capture)
    try:
        dataset = build_measurement_dataset(db, [experiment.id])
        assert pending in db.new and sample in db.dirty
        assert sum(slot.sample_id is not None for slot in dataset.seedling_slots) == 1
        assert all(s.lstrip().upper().startswith('SELECT') for s in statements)
    finally:
        event.remove(connection, 'before_cursor_execute', capture)
        db.rollback()


@pytest.mark.parametrize('scope', ['per_dish', 'per_material'])
def test_detached_contract_preserves_existing_slot_matching_and_population(design, scope):
    db, experiment, protocol, material, dish, _ = design
    protocol.sample_scope = scope
    protocol.replicate_count = 2
    protocol.sample_count = 3
    obtained(db, dish, 2)
    first_lot = db.get(SeedLot, material.seed_lot_id)
    second_lot = SeedLot(code='LOT-2026-002', taxon_id=first_lot.taxon_id)
    db.add(second_lot)
    db.flush()
    db.add(ExperimentMaterial(experiment_id=experiment.id, seed_lot_id=second_lot.id,
                             experiment_number=2, display_order=10))
    db.commit()
    source = build_measurement_slots(db, [experiment.id])
    data = build_measurement_dataset(db, [experiment.id])
    assert len({slot.material_id for slot in data.seedling_slots}) == 2
    assert [slot.material_number for slot in data.seedling_slots] == ([1] * 6 + [2] * 6
        if scope == 'per_dish' else [1] * 3 + [2] * 3)
    assert [slot.key for slot in data.seedling_slots] == [slot.key for slot in source.seedling_slots]
    assert [slot.seedling_number for slot in data.seedling_slots] == [slot.seedling_number for slot in source.seedling_slots]
    assert [slot.sample_id for slot in data.seedling_slots] == [slot.sample.id if slot.sample else None
                                                            for slot in source.seedling_slots]
    assert [r.data_status for r in data.rows] == [r.data_status for r in source.measurement_slots]
    assert len(data.seedling_slots) == (12 if scope == 'per_dish' else 6)
    assert all(slot.sample_id is None for slot in data.seedling_slots if slot.material_id != material.id)
    assert_detached(data)
