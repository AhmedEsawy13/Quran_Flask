"""Logical page geometry: line bands + fractional word boxes (no pixel DB)."""
from __future__ import annotations

import sqlite3
import unicodedata
from dataclasses import dataclass
from functools import lru_cache

from pipeline.cv_waqf.config import EditionSpec
from pipeline.cv_waqf.preprocess import PreparedPage


@dataclass
class LayoutWord:
    word_id: int
    word_key: str
    word_id_space: str
    surah: int
    ayah: int
    text: str
    line_number: int
    word_on_line: int
    words_on_line: int
    # Estimated pixel box in full-page coords (may be approximate).
    x0: int
    y0: int
    x1: int
    y1: int

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2.0

    @property
    def cy(self) -> float:
        return (self.y0 + self.y1) / 2.0

    @property
    def is_content_word(self) -> bool:
        """Verse-number ornaments are layout tokens, never waqf owners."""
        return any('\u0621' <= char <= '\u064a' for char in self.text)

    @property
    def has_waqf_seat(self) -> bool:
        """Whether the trusted source script prints a stop on this word."""
        return any(char in 'ۘۗۖۚۙۛۜ' for char in self.text)


def load_page_lines(spec: EditionSpec, page: int) -> list[dict]:
    conn = sqlite3.connect(spec.layout_db)
    conn.row_factory = sqlite3.Row
    try:
        columns = {
            str(row[1])
            for row in conn.execute('PRAGMA table_info(pages)').fetchall()
        }
        line_text = 'line_text' if 'line_text' in columns else "'' AS line_text"
        rows = conn.execute(
            f'''
            SELECT page_number, line_number, line_type, is_centered,
                   first_word_id, last_word_id, surah_number, {line_text}
            FROM pages
            WHERE page_number = ?
            ORDER BY line_number ASC
            ''',
            (page,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _word_rows(spec: EditionSpec, word_ids: list[int]) -> dict[int, dict]:
    if not word_ids:
        return {}
    conn = sqlite3.connect(spec.script_db)
    conn.row_factory = sqlite3.Row
    try:
        q = ','.join('?' * len(word_ids))
        rows = conn.execute(
            f'SELECT word_index, word_key, surah, ayah, text FROM words '
            f'WHERE word_index IN ({q})',
            word_ids,
        ).fetchall()
        return {int(r['word_index']): dict(r) for r in rows}
    finally:
        conn.close()


def _word_key_position(word_key: str, fallback: int) -> int:
    try:
        return int(str(word_key or '').rsplit(':', 1)[-1])
    except (TypeError, ValueError):
        return int(fallback)


@lru_cache(maxsize=8)
def _ordered_word_ids(script_db: str) -> tuple[tuple[int, ...], dict[int, int]]:
    """Return one script DB's IDs in canonical Quran reading order.

    Kept inside the Flask-free CV package because ``modules.layout_engine``
    intentionally imports Flask's request-scoped DB helper.
    """
    conn = sqlite3.connect(script_db)
    try:
        rows = conn.execute(
            'SELECT word_index, word_key, surah, ayah FROM words'
        ).fetchall()
    finally:
        conn.close()
    ordered = sorted(
        rows,
        key=lambda row: (
            int(row[2]), int(row[3]),
            _word_key_position(row[1], row[0]), int(row[0]),
        ),
    )
    ids = tuple(int(row[0]) for row in ordered)
    return ids, {word_id: pos for pos, word_id in enumerate(ids)}


def _ids_between(script_db: str, first_id: int, last_id: int) -> list[int]:
    ids, positions = _ordered_word_ids(script_db)
    lo = positions.get(int(first_id))
    hi = positions.get(int(last_id))
    if lo is None or hi is None or hi < lo:
        return []
    return list(ids[lo:hi + 1])


def _arabic_width_weight(text: str) -> float:
    """Cheap, font-independent proxy for a shaped Arabic word's advance."""
    decomposed = unicodedata.normalize('NFD', text or '')
    letters = sum(
        1 for char in decomposed
        if not unicodedata.combining(char) and '\u0621' <= char <= '\u064a'
    )
    # Keep verse-number ornaments and other non-letter layout tokens visible
    # in the sequence instead of collapsing their slot to zero.
    return 0.5 + max(1, letters)


def _observed_line_bounds(
    prepared: PreparedPage,
    line_top: int,
    line_bot: int,
) -> tuple[int, int]:
    """Estimate the printed line's horizontal span from its lower ink body.

    Marks and harakat live higher in the row and would make the span unstable.
    The middle/lower strip consistently contains the Arabic skeleton.
    """
    import numpy as np

    x0, _band_y0, x1, _band_y1 = prepared.band_box
    line_h = max(1, line_bot - line_top)
    body_y0 = line_top + int(0.40 * line_h)
    body_y1 = line_top + int(0.75 * line_h)
    roi = prepared.binary[body_y0:body_y1, x0:x1]
    if roi.size == 0:
        return x0, x1
    ink_columns = np.flatnonzero(np.any(roi > 0, axis=0))
    if ink_columns.size < 2:
        return x0, x1
    # The extreme columns often belong to a projecting dot/terminal stroke.
    # A small line-height-relative inset better approximates word advances.
    inset = max(3, int(0.14 * line_h))
    observed_left = x0 + int(ink_columns[0]) + inset
    observed_right = x0 + int(ink_columns[-1]) + 1 - inset
    if observed_right - observed_left < max(80, int(0.35 * (x1 - x0))):
        return x0, x1
    return observed_left, observed_right


def estimate_layout_words(
    spec: EditionSpec,
    page: int,
    prepared: PreparedPage,
) -> list[LayoutWord]:
    """Place each layout word in an estimated ROI inside the text band.

    RTL: word_on_line=1 is the rightmost slot on the line.
    """
    lines = load_page_lines(spec, page)
    ayah_lines = [
        ln for ln in lines
        if ln.get('line_type') in (None, '', 'ayah', 'verse')
        or (
            ln.get('first_word_id') is not None
            and ln.get('last_word_id') is not None
            and (ln.get('line_type') or '') not in (
                'surah_name', 'surah_info', 'basmallah', 'basmala',
            )
        )
    ]
    # Keep only rows with a word span.
    ayah_lines = [
        ln for ln in ayah_lines
        if ln.get('first_word_id') is not None and ln.get('last_word_id') is not None
    ]
    if not ayah_lines:
        return []

    # Local ``word_index`` values are identifiers, not a globally contiguous
    # counter.  In particular quran_script.db has deliberate numeric gaps.
    # Walk the owning script database's canonical reading order instead of
    # constructing ``range(first_id, last_id + 1)``.
    id_space = (
        'qpc-layout-global-v1'
        if spec.word_space == 'qpc'
        else 'quran-script-stable-v1'
    )
    all_ids: list[int] = []
    spans: list[tuple[dict, list[int]]] = []
    for ln in ayah_lines:
        first_id = int(ln['first_word_id'])
        last_id = int(ln['last_word_id'])
        ids = _ids_between(spec.script_db, first_id, last_id)
        if not ids:
            continue
        spans.append((ln, ids))
        all_ids.extend(ids)
    meta = _word_rows(spec, all_ids)

    x0, y0, x1, y1 = prepared.band_box
    band_h = max(1, y1 - y0)
    # Preserve physical page rows.  Compressing only the ayah rows over the
    # whole band is wrong whenever a surah heading/basmallah occupies a row:
    # all words below it are then attached one or more lines too high.
    page_line_numbers = [
        int(ln['line_number']) for ln in lines
        if ln.get('line_number') is not None
    ]
    first_line = min(page_line_numbers, default=1)
    last_line = max(page_line_numbers, default=first_line + len(spans) - 1)
    line_slots = max(1, last_line - first_line + 1)
    out: list[LayoutWord] = []
    for ln, ids in spans:
        line_slot = max(0, int(ln['line_number']) - first_line)
        line_top = y0 + int(band_h * line_slot / line_slots)
        line_bot = y0 + int(band_h * (line_slot + 1) / line_slots)
        # Slight inset so mark crops sit above the baseline.
        word_top = line_top
        word_bot = line_bot
        n = len(ids)
        line_left, line_right = _observed_line_bounds(
            prepared, line_top, line_bot,
        )
        line_width = max(1, line_right - line_left)
        weights = [
            _arabic_width_weight(str((meta.get(wid) or {}).get('text') or ''))
            for wid in ids
        ]
        total_weight = max(1.0, sum(weights))
        cumulative_weight = 0.0
        for i, wid in enumerate(ids):
            # RTL: index 0 is rightmost.  Use the observed printed line span
            # and Arabic-letter weights; equal slots place long words and
            # short particles at systematically wrong x coordinates.
            weight = weights[i]
            wx1 = line_right - int(line_width * cumulative_weight / total_weight)
            cumulative_weight += weight
            wx0 = line_right - int(line_width * cumulative_weight / total_weight)
            info = meta.get(wid) or {}
            out.append(LayoutWord(
                word_id=wid,
                word_key=str(info.get('word_key') or ''),
                word_id_space=id_space,
                surah=int(info.get('surah') or ln.get('surah_number') or 0),
                ayah=int(info.get('ayah') or 0),
                text=str(info.get('text') or ''),
                line_number=int(ln['line_number']),
                word_on_line=i + 1,
                words_on_line=n,
                x0=min(wx0, wx1),
                y0=word_top,
                x1=max(wx0, wx1),
                y1=word_bot,
            ))
    return out


def mark_roi_for_word(
    word: LayoutWord,
    *,
    pad_x: int = 4,
    pad_y: int = 3,
) -> tuple[int, int, int, int]:
    """ROI above the left (end) edge of an RTL word — waqf seat, not letter body.

    Kept high in the line band so kasra/vowel marks on the letters themselves
    fall outside the search window.
    """
    line_h = max(8, word.y1 - word.y0)
    seat = max(10, min(20, int(0.22 * line_h)))
    cx = word.x0
    # Upper fifth of the line — printed stops sit above the skeleton.
    cy = word.y0 + int(0.12 * line_h)
    return (
        max(0, cx - seat - pad_x),
        max(0, cy - seat - pad_y),
        cx + max(6, seat // 3) + pad_x,
        cy + seat + pad_y,
    )
