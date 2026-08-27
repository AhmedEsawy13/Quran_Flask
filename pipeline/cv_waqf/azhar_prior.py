"""Azhar occupancy prior for Bahrain CV waqf detections.

After a mark is attached to a word, keep it only if الأزهر has **some**
waqf on that same word. Ignore the Azhar glyph. Match on
``(سورة, آية, token_index / word_position)`` only. Any non-empty الأزهر
cell counts. This is an FP cut, not a mark classifier.

الأزهر has more printed stops than البحرين, so a real Bahrain stop should
almost always sit on an Azhar-occupied word. Counting glyphs would create
false mismatches (Azhar ج vs Bahrain ص).

Evidence (already measured, do not re-train), ``data/mushaf_waqf.db``
table ``waqf``:

- الأزهر non-null: 4870, البحرين: 4275, overlap 4263. Only **12** Bahrain
  DB seats have empty Azhar.
- ``word_key`` in detect is ``surah:ayah:word_position``. In this DB,
  ``token_index`` and ``word_index`` match that 1-based word_position
  (example: label word_key ``2:5:5`` is token_index 5).

On 44 labeled Bahrain pages, gated hybrid min_conf 0.55:

- FPs 31 → 6 (killed 25) if we drop marks whose word has empty Azhar.
- Correct 217 → 213. The 4 dropped "TPs" are NOT Bahrain-DB seats:
  ``4:23:11`` / ``4:23:17`` / ``4:23:36`` are Qatar-only ص; ``5:111:8``
  is empty in every edition. So vs mushaf_waqf.db this prior does not
  drop real البحرين cells on that set.

Global recall cost vs DB — 12 البحرين seats with empty الأزهر (documented
here; do not special-case them unless a test needs the list):

``2:2:4`` ع, ``2:131:5`` ص, ``2:133:14`` ص, ``4:162:14`` ج,
``4:162:16`` ج, ``5:41:20`` ع, ``6:76:6`` ص, ``6:134:4`` ص,
``6:141:26`` ص, ``16:10:6`` ص, ``28:35:11`` ج, ``60:5:9`` ص.

``mushaf_waqf.db`` may be gitignored. Missing or unreadable DB fails
**open** (keep the mark) so detections are not wiped in CI.
"""
from __future__ import annotations

import sqlite3
from functools import lru_cache
from pathlib import Path
from typing import Any

from pipeline.cv_waqf.config import WAQF_DB

AZHAR_REJECT_REASON = 'azhar_empty'


def reset_azhar_occupancy_cache() -> None:
    """Drop the cached occupancy set (tests / swapped DB path)."""
    load_azhar_occupied_seats.cache_clear()


@lru_cache(maxsize=4)
def load_azhar_occupied_seats(db_path: str = '') -> frozenset[tuple[int, int, int]] | None:
    """Cached ``(surah, ayah, token_index)`` where الأزهر is non-empty.

    Returns ``None`` when the file is missing, unreadable, or has no
    occupied Azhar seats — callers must fail open.
    """
    path = Path(db_path) if db_path else Path(WAQF_DB)
    if not path.is_file():
        return None
    try:
        conn = sqlite3.connect(f'file:{path.as_posix()}?mode=ro', uri=True)
        try:
            rows = conn.execute(
                'SELECT "السورة", "الآية", token_index FROM waqf '
                'WHERE "الأزهر" IS NOT NULL AND TRIM("الأزهر") != ""'
            ).fetchall()
        finally:
            conn.close()
    except sqlite3.Error:
        return None
    seats: set[tuple[int, int, int]] = set()
    for surah, ayah, token_index in rows:
        try:
            seats.add((int(surah), int(ayah), int(token_index)))
        except (TypeError, ValueError):
            continue
    return frozenset(seats) if seats else None


def word_has_azhar_waqf(
    surah: int,
    ayah: int,
    word_position: int,
    *,
    db_path: str | Path | None = None,
) -> bool:
    """True if الأزهر occupies this 1-based word, or if the DB is unavailable."""
    occupied = load_azhar_occupied_seats('' if db_path is None else str(db_path))
    if not occupied:
        return True
    try:
        key = (int(surah), int(ayah), int(word_position))
    except (TypeError, ValueError):
        return True
    return key in occupied


def word_position_of(mark: Any) -> int | None:
    """1-based word_position from ``word_key`` (``surah:ayah:position``)."""
    if isinstance(mark, dict):
        key = mark.get('word_key')
        explicit = mark.get('word_position')
    else:
        key = getattr(mark, 'word_key', None)
        explicit = getattr(mark, 'word_position', None)
    raw = str(key or '').strip()
    if raw:
        try:
            return int(raw.rsplit(':', 1)[-1])
        except ValueError:
            pass
    if explicit is not None:
        try:
            return int(explicit)
        except (TypeError, ValueError):
            return None
    return None


def partition_marks_by_azhar_occupancy(
    marks: list[Any],
    *,
    db_path: str | Path | None = None,
) -> tuple[list[Any], list[Any]]:
    """Split attached marks / dicts into kept vs Azhar-empty rejected.

    Empty or missing DB: return every mark as kept.
    """
    occupied = load_azhar_occupied_seats('' if db_path is None else str(db_path))
    if not occupied:
        return list(marks), []
    kept: list[Any] = []
    rejected: list[Any] = []
    for mark in marks:
        if isinstance(mark, dict):
            surah, ayah = mark.get('surah'), mark.get('ayah')
        else:
            surah = getattr(mark, 'surah', None)
            ayah = getattr(mark, 'ayah', None)
        position = word_position_of(mark)
        if (
            surah is None or ayah is None or position is None
            or (int(surah), int(ayah), int(position)) in occupied
        ):
            kept.append(mark)
        else:
            rejected.append(mark)
    return kept, rejected
