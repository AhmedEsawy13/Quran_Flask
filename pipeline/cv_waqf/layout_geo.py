"""Logical page geometry: line bands + fractional word boxes (no pixel DB)."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from pipeline.cv_waqf.config import EditionSpec
from pipeline.cv_waqf.preprocess import PreparedPage


@dataclass
class LayoutWord:
    word_id: int
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


def load_page_lines(spec: EditionSpec, page: int) -> list[dict]:
    conn = sqlite3.connect(spec.layout_db)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            '''
            SELECT page_number, line_number, line_type, is_centered,
                   first_word_id, last_word_id, surah_number, line_text
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
            f'SELECT word_index, surah, ayah, text FROM words '
            f'WHERE word_index IN ({q})',
            word_ids,
        ).fetchall()
        return {int(r['word_index']): dict(r) for r in rows}
    finally:
        conn.close()


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

    all_ids: list[int] = []
    spans: list[tuple[dict, list[int]]] = []
    for ln in ayah_lines:
        first_id = int(ln['first_word_id'])
        last_id = int(ln['last_word_id'])
        if last_id < first_id:
            continue
        ids = list(range(first_id, last_id + 1))
        spans.append((ln, ids))
        all_ids.extend(ids)
    meta = _word_rows(spec, all_ids)

    x0, y0, x1, y1 = prepared.band_box
    band_h = max(1, y1 - y0)
    band_w = max(1, x1 - x0)
    n_lines = len(spans)
    out: list[LayoutWord] = []
    for line_i, (ln, ids) in enumerate(spans):
        line_top = y0 + int(band_h * line_i / n_lines)
        line_bot = y0 + int(band_h * (line_i + 1) / n_lines)
        # Slight inset so mark crops sit above the baseline.
        word_top = line_top
        word_bot = line_bot
        n = len(ids)
        for i, wid in enumerate(ids):
            # RTL: index 0 is rightmost.
            right_frac = i / n
            left_frac = (i + 1) / n
            wx1 = x1 - int(band_w * right_frac)
            wx0 = x1 - int(band_w * left_frac)
            info = meta.get(wid) or {}
            out.append(LayoutWord(
                word_id=wid,
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
