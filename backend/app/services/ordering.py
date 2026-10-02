"""Stable ordering for user-facing material lists and sequential numbers."""

from pypinyin import lazy_pinyin


def pinyin_key(value: str | None) -> tuple[str, ...]:
    return tuple(part.casefold() for part in lazy_pinyin((value or "").strip()))


def taxon_key(taxon) -> tuple:
    return (pinyin_key(taxon.common_name or taxon.scientific_name),
            taxon.scientific_name.casefold(), taxon.code)


def material_key(taxon, lot) -> tuple:
    return (pinyin_key(taxon.common_name or taxon.scientific_name),
            taxon.scientific_name.casefold(), (lot.source_code or "").casefold(), lot.code)


def display_number(value: int) -> str:
    return f"{value:03d}"


def dish_display_number(material_number: int | None, replicate_no: int, replicate_count: int) -> str | None:
    if material_number is None:
        return None
    number = display_number(material_number)
    return number if replicate_count == 1 else f"{number}-{replicate_no}"


def field_number(material, replicate_count: int, replicate_no: int) -> str | None:
    return dish_display_number(material.experiment_number, replicate_no, replicate_count)


def sample_display_number(material_number: int | None, replicate_no: int, replicate_count: int,
                          sample_number: int) -> str | None:
    dish = dish_display_number(material_number, replicate_no, replicate_count)
    return f"{dish}-{sample_number:02d}" if dish else None


def field_number_expression(material_number, replicate_no, replicate_count):
    from sqlalchemy import String, case, cast, func
    number = func.printf("%03d", material_number)
    return case((material_number.is_(None), None), (replicate_count == 1, number),
                else_=number + "-" + cast(replicate_no, String))


def sample_number_expression(field, sample_number):
    from sqlalchemy import func
    return field + "-" + func.printf("%02d", sample_number)
