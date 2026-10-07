"""The ordering authority and its Python/SQLite field identities must agree."""
from types import SimpleNamespace

import pytest
from sqlalchemy import Integer, literal, select

from app.db.session import make_engine
from app.services.ordering import (dish_display_number, field_number_expression,
    material_key, pinyin_key, sample_display_number, sample_number_expression, taxon_key)


def test_full_pinyin_and_material_tie_breakers_use_the_existing_authority():
    names = ['狗尾草', '白头翁', '白三叶', '白花蛇舌草']
    taxa = [SimpleNamespace(common_name=name, scientific_name=f'Species {n}', code=f'SP-{n:04d}')
            for n, name in enumerate(names, 1)]
    assert pinyin_key('  白头翁  ') == ('bai', 'tou', 'weng')
    assert [taxon.common_name for taxon in sorted(taxa, key=taxon_key)] == [
        '白花蛇舌草', '白三叶', '白头翁', '狗尾草']
    fallback = SimpleNamespace(common_name=None, scientific_name='Alpha species', code='SP-0000')
    assert sorted([*taxa, fallback], key=taxon_key)[0] is fallback
    # Same Chinese name: scientific name, original number, then permanent lot code.
    pairs = [(SimpleNamespace(common_name='白三叶', scientific_name=scientific),
              SimpleNamespace(source_code=source, code=code))
             for scientific, source, code in [
                 ('Z species', None, 'LOT-2026-001'),
                 ('A species', 'B', 'LOT-2026-004'),
                 ('A species', 'a', 'LOT-2026-003'),
                 ('a species', 'A', 'LOT-2026-002'),
                 ('A species', None, 'LOT-2026-005')]]
    assert [lot.code for _, lot in sorted(pairs, key=lambda pair: material_key(*pair))] == [
        'LOT-2026-005', 'LOT-2026-002', 'LOT-2026-003', 'LOT-2026-004', 'LOT-2026-001']


@pytest.mark.parametrize('material, replicate, count, sample, expected_dish, expected_sample', [
    (None, 1, 1, 1, None, None),
    (1, 1, 1, 1, '001', '001-01'),
    (9, 2, 3, 10, '009-2', '009-2-10'),
    (999, 10, 10, 99, '999-10', '999-10-99'),
    (1000, 100, 100, 100, '1000-100', '1000-100-100'),
])
def test_python_and_sql_numbering_parity(material, replicate, count, sample,
                                        expected_dish, expected_sample):
    engine = make_engine('sqlite:///:memory:')
    try:
        field = field_number_expression(literal(material, Integer), literal(replicate), literal(count))
        with engine.connect() as connection:
            sql_dish, sql_sample = connection.execute(select(
                field, sample_number_expression(field, literal(sample)))).one()
        assert sql_dish == dish_display_number(material, replicate, count) == expected_dish
        assert sql_sample == sample_display_number(material, replicate, count, sample) == expected_sample
    finally:
        engine.dispose()
