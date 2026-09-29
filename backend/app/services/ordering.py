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


def field_number(material, replicate_count: int, replicate_no: int) -> str:
    number = display_number(material.experiment_number)
    return number if replicate_count == 1 else f"{number}-{replicate_no}"
