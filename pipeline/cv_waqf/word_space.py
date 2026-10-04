"""Map a script DB's word positions to the printed-word index of the waqf table.

``quran_script.db`` (the Shemrly/Mesaha word space) lists every token of an
ayah, including ornaments such as the hizb mark and the ayah-end numerals, so
its ``word_key`` positions run ahead of the waqf table's ``word_index`` (the
1-based index among printed *words*). Counting only tokens that contain an
Arabic letter reproduces ``word_index`` for 11,699 of the 12,445 waqf rows
(94%); the rest are known mis-indexed or duplicate DB rows.
"""
from __future__ import annotations

import sqlite3
from functools import lru_cache


def _is_word(text: str) -> bool:
    return any('ء' <= ch <= 'ي' or ch in 'ٱٰ' for ch in (text or ''))


@lru_cache(maxsize=4)
def _printed_index(script_db: str) -> dict[tuple[int, int, int], int]:
    conn = sqlite3.connect(script_db)
    try:
        rows = conn.execute(
            'SELECT surah, ayah, word_key, text FROM words'
        ).fetchall()
    finally:
        conn.close()
    by_ayah: dict[tuple[int, int], list[tuple[int, str]]] = {}
    for surah, ayah, word_key, text in rows:
        try:
            position = int(str(word_key).rsplit(':', 1)[-1])
        except ValueError:
            continue
        by_ayah.setdefault((int(surah), int(ayah)), []).append((position, text))
    out: dict[tuple[int, int, int], int] = {}
    for (surah, ayah), words in by_ayah.items():
        counter = 0
        for position, text in sorted(words):
            if _is_word(text):
                counter += 1
                out[(surah, ayah, position)] = counter
    return out


def printed_position(
    script_db: str, surah: int, ayah: int, script_position: int,
) -> int | None:
    """Printed-word index for a script position; ``None`` for an ornament."""
    return _printed_index(str(script_db)).get(
        (int(surah), int(ayah), int(script_position)),
    )
