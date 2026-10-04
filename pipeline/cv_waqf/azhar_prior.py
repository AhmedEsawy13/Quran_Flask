"""Seat-occupancy prior for CV waqf detections (Azhar, optionally more).

Which editions supply the occupancy is per print (``EditionSpec
.seat_prior_editions``); Azhar alone was the original choice and stays the
default. Measured on the DB, adding المدينة الجديد + المدينة القديم grows the
allowed set by 52 seats (4870 → 4922) yet recovers 11 of Bahrain's 12
Azhar-empty seats and 29 of Qatar's 93. The prior never includes the print's
own column, or it could not find anything new. Everything below that says
"Azhar" describes the original single-edition behaviour and applies to any
edition set.

After a mark is attached to a word, keep it only if الأزهر has **some**
waqf on that same word. Ignore the Azhar glyph. Match on
``(سورة, آية, word_index)`` only — the same 1-based printed-word
position as detect ``word_key`` (``surah:ayah:word_position``). Any
non-empty الأزهر cell counts. This is an FP cut, not a mark classifier.

الأزهر has more printed stops than البحرين, so a real Bahrain stop should
almost always sit on an Azhar-occupied word. Counting glyphs would create
false mismatches (Azhar ج vs Bahrain ص).

Evidence (already measured, do not re-train), ``data/mushaf_waqf.db``
table ``waqf``:

- الأزهر non-null: 4870, البحرين: 4275, overlap 4263. Only **12** Bahrain
  DB seats have empty Azhar.
- ``word_key`` in detect is ``surah:ayah:word_position``, and that
  position is ``word_index`` (the printed word). ``token_index`` equals
  ``word_index`` on most rows, but **353** rows differ. Occupancy must
  use ``word_index`` or real البحرين seats are dropped (e.g. 33:51:8
  تشاء: DB word_index 8, token_index 9).

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


AZHAR_ONLY: tuple[str, ...] = ('الأزهر',)


def _edition_columns(conn: sqlite3.Connection, editions: tuple[str, ...]) -> list[str]:
    """Quoted column names for ``editions``, checked against the real table."""
    known = {str(row[1]) for row in conn.execute('PRAGMA table_info(waqf)')}
    missing = [edition for edition in editions if edition not in known]
    if missing:
        raise ValueError(f'unknown edition column(s) in waqf table: {missing}')
    return ['"' + edition.replace('"', '""') + '"' for edition in editions]


@lru_cache(maxsize=8)
def load_occupied_seats(
    db_path: str = '',
    editions: tuple[str, ...] = AZHAR_ONLY,
) -> frozenset[tuple[int, int, int]] | None:
    """Cached ``(surah, ayah, word_index)`` where any of ``editions`` has a mark.

    ``word_index`` is the 1-based printed-word position in detect
    ``word_key``. Skip null or unparseable ``word_index``. Returns
    ``None`` when the file is missing, unreadable, or has no occupied seats
    — callers must fail open. An unknown edition name is a configuration
    error and raises.
    """
    path = Path(db_path) if db_path else Path(WAQF_DB)
    if not path.is_file():
        return None
    try:
        conn = sqlite3.connect(f'file:{path.as_posix()}?mode=ro', uri=True)
        try:
            columns = _edition_columns(conn, tuple(editions))
            occupied = ' OR '.join(
                f'({column} IS NOT NULL AND TRIM({column}) != \'\')'
                for column in columns
            )
            rows = conn.execute(
                'SELECT "السورة", "الآية", word_index FROM waqf '
                f'WHERE {occupied}'
            ).fetchall()
        finally:
            conn.close()
    except sqlite3.Error:
        return None
    seats: set[tuple[int, int, int]] = set()
    for surah, ayah, word_index in rows:
        try:
            seats.add((int(surah), int(ayah), int(word_index)))
        except (TypeError, ValueError):
            continue
    return frozenset(seats) if seats else None


def load_azhar_occupied_seats(
    db_path: str = '',
) -> frozenset[tuple[int, int, int]] | None:
    """Azhar-only occupancy (the original prior)."""
    return load_occupied_seats(db_path, AZHAR_ONLY)


def reset_azhar_occupancy_cache() -> None:
    """Drop the cached occupancy sets (tests / swapped DB path)."""
    load_occupied_seats.cache_clear()


def word_has_azhar_waqf(
    surah: int,
    ayah: int,
    word_position: int,
    *,
    db_path: str | Path | None = None,
) -> bool:
    """True if الأزهر occupies this 1-based word_index, or if the DB is unavailable."""
    occupied = load_occupied_seats('' if db_path is None else str(db_path))
    if not occupied:
        return True
    try:
        key = (int(surah), int(ayah), int(word_position))
    except (TypeError, ValueError):
        return True
    return key in occupied


def word_position_of(mark: Any) -> int | None:
    """1-based printed word_index from ``word_key`` (``surah:ayah:position``)."""
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


def _seat_position(mark: Any, script_db: str | None) -> int | None:
    """Position used for the occupancy lookup: printed-word index.

    QPC-indexed layouts already carry it in ``word_key``. For another word
    space pass its ``script_db`` and ornament tokens map to ``None``.
    """
    position = word_position_of(mark)
    if script_db is None or position is None:
        return position
    if isinstance(mark, dict):
        surah, ayah = mark.get('surah'), mark.get('ayah')
    else:
        surah, ayah = getattr(mark, 'surah', None), getattr(mark, 'ayah', None)
    if surah is None or ayah is None:
        return None
    from pipeline.cv_waqf.word_space import printed_position

    return printed_position(script_db, int(surah), int(ayah), position)


def partition_marks_by_azhar_occupancy(
    marks: list[Any],
    *,
    db_path: str | Path | None = None,
    editions: tuple[str, ...] = AZHAR_ONLY,
    script_db: str | None = None,
) -> tuple[list[Any], list[Any]]:
    """Split attached marks / dicts into kept vs prior-rejected.

    A mark is kept when any of ``editions`` (Azhar by default) prints a stop
    on its word. Empty or missing DB: return every mark as kept.
    """
    occupied = load_occupied_seats(
        '' if db_path is None else str(db_path), tuple(editions),
    )
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
        position = _seat_position(mark, script_db)
        if surah is None or ayah is None:
            kept.append(mark)
        elif position is None:
            # QPC words always have a position; a script-space ornament has
            # no printed seat, so it can never be a stop.
            (rejected if script_db is not None else kept).append(mark)
        elif (int(surah), int(ayah), int(position)) in occupied:
            kept.append(mark)
        else:
            rejected.append(mark)
    return kept, rejected


def reattach_rejected_marks(
    kept: list[Any],
    rejected: list[Any],
    words: list[Any],
    *,
    editions: tuple[str, ...] = AZHAR_ONLY,
    db_path: str | Path | None = None,
    script_db: str | None = None,
) -> tuple[list[Any], list[Any]]:
    """Move a prior-rejected mark to an adjacent occupied seat on its line.

    A stop sign printed at the junction of two words is often attached to the
    wrong one (measured on Kuwait: 68 of 203 undetected DB stops were found
    on the neighbouring word, 47 on the previous one). When the prior rejects
    such a mark, the adjacent word of the same line is tried: it must be an
    occupied seat that holds no kept mark. The next word is preferred (the
    measured majority), then the previous one. Marks with no such neighbour
    stay rejected.
    """
    occupied = load_occupied_seats(
        '' if db_path is None else str(db_path), tuple(editions),
    )
    if not occupied or not rejected:
        return list(kept), list(rejected)
    by_key = {w.word_key: w for w in words}
    taken = {m.word_key for m in kept}
    out_kept = list(kept)
    out_rejected: list[Any] = []
    # Highest confidence first so the better mark wins a contested seat.
    for mark in sorted(rejected, key=lambda m: -m.confidence):
        position = word_position_of(mark)
        moved = False
        if position is not None:
            for delta in (1, -1):
                key = f'{mark.surah}:{mark.ayah}:{position + delta}'
                word = by_key.get(key)
                if word is None or key in taken or word.line_number != mark.line_number:
                    continue
                seat = _seat_position(word, script_db) if script_db else position + delta
                if (
                    seat is None
                    or (int(mark.surah), int(mark.ayah), seat) not in occupied
                    or not getattr(word, 'is_content_word', True)
                ):
                    continue
                mark.word_id = word.word_id
                mark.word_key = word.word_key
                mark.text = word.text
                taken.add(key)
                out_kept.append(mark)
                moved = True
                break
        if not moved:
            out_rejected.append(mark)
    return out_kept, out_rejected
