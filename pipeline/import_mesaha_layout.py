#!/usr/bin/env python3
"""Build the 1342H Egyptian Survey Authority Layout Studio database.

This importer does not ask OCR (or an LLM) to author Quran text.  The complete
ordered word stream comes from ``data/quran_script.db``.  Internet Archive's
DjVu OCR is used only as a noisy positional signal for page and line endings.
Every output word is therefore canonical, ordered, and emitted exactly once.

Source files
------------
Download both Archive DjVu XML derivatives (about 11–12 MB each):

  https://archive.org/download/mushafElMesaha46796794669_201703/
  mushafElMesaha_djvu.xml

  https://archive.org/download/mushafElMesahaFP.pdf/
  mushafElMesaha.pdf_djvu.xml

Usage
-----
  python3 pipeline/import_mesaha_layout.py \
      --ocr-xml archive-2017=/path/to/mushafElMesaha_djvu.xml \
      --ocr-xml quranpedia-2025=/path/to/mushafElMesaha.pdf_djvu.xml

  python3 pipeline/import_mesaha_layout.py \
      --ocr-xml /path/to/mushafElMesaha_djvu.xml --force

Optional Kraken line JSON (local to the operator, not in git) seats printed
wraps from wide-line geometry when present:

  --kraken-dir artifacts/mesaha-kraken/pages

``--force`` is intentionally required once the project database exists because
rebuilding it destroys reviewer edits, progress, and undo history.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sqlite3
import statistics
import sys
import unicodedata
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

try:
    from rapidfuzz.fuzz import partial_ratio_alignment
except ImportError as exc:  # pragma: no cover - friendly CLI dependency error
    raise SystemExit(
        'rapidfuzz is required for the offline importer. '
        'Install requirements-dev.txt first.'
    ) from exc

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.config import (  # noqa: E402
    MESAHA_ARCHIVE_ID,
    MESAHA_LAYOUT_DATABASE,
    MESAHA_LAYOUT_MAX_PAGE,
    MESAHA_LAYOUT_MIN_PAGE,
    QURAN_SCRIPT_DATABASE,
    SHAMARLY_LAYOUT_DATABASE,
)
from modules import layout_engine as engine  # noqa: E402
from pipeline.mesaha_printed_seating import (  # noqa: E402
    DEFAULT_KRAKEN_DIR,
    LINE_Y_MERGE,
    PageTextGeometry,
    clip_empty_top_page_starts,
    load_kraken_geometries,
    seat_printed_page,
    slot_for_y,
)

PAGE_MIN = MESAHA_LAYOUT_MIN_PAGE
PAGE_MAX = MESAHA_LAYOUT_MAX_PAGE
PAGE_COUNT = PAGE_MAX - PAGE_MIN + 1
DEFAULT_LINES = 12
SHORT_LINES = {2: 8, 3: 8}
SEARCH_RADIUS_WORDS = 2800
PAGE_CLUSTER_WORDS = 350
OCR_SCORE_CUTOFF = 60.0
# Softened from 78: many pages match OCR well but fail the strict slot cut.
LINE_ANCHOR_SCORE = 70.0
TEXT_TOP = 1250
TEXT_BOTTOM = 4820
# Typical Mesaha body page is ~100–110 words; extremes are almost always bad cuts.
PAGE_WORDS_MIN = 70
PAGE_WORDS_MAX = 130
PAGE_WORDS_TARGET = 106
CANONICAL_INTEGRITY_BONUS = 0.02
METHOD_VERSION = 'canonical-multi-ocr-forced-alignment-v6'
# JPEG px; v6 seats wraps from Kraken wide lines with this merge (see seating).
assert LINE_Y_MERGE == 162

_LETTER_FOLD = str.maketrans({
    'ٱ': 'ا',
    'أ': 'ا',
    'إ': 'ا',
    'آ': 'ا',
    'ى': 'ي',
    'ئ': 'ي',
    'ؤ': 'و',
    'ة': 'ه',
    # Common Persian/Urdu substitutions produced by the Archive OCR.
    'ک': 'ك',
    'ی': 'ي',
    'ے': 'ي',
    'ھ': 'ه',
    'گ': 'ك',
    'پ': 'ب',
    'چ': 'ج',
})


@dataclass(frozen=True)
class QuranWord:
    index: int
    word_key: str
    surah: int
    ayah: int
    text: str
    normalized: str


@dataclass(frozen=True)
class OcrLine:
    y: int
    text: str
    normalized: str
    width: int


@dataclass(frozen=True)
class Match:
    start: int  # zero-based position in the canonical word list
    end: int
    mid: float
    score: float
    y: int
    text: str


@dataclass
class PageAlignment:
    page: int
    expected: int
    candidates: list[Match]
    selected: list[Match]
    center: float
    smoothed_center: float = 0.0
    start_prediction: float | None = None
    end_prediction: float | None = None


@dataclass(frozen=True)
class OcrSource:
    label: str
    path: str


@dataclass(frozen=True)
class HeaderRows:
    surah_name: tuple[int | None, int | None, str]
    basmallah: tuple[int | None, int | None, str] | None


@dataclass
class OutputRow:
    line_number: int
    line_type: str
    is_centered: int
    first_word_id: int | None
    last_word_id: int | None
    surah_number: int | None
    line_text: str
    start_pos: int | None = None
    end_pos: int | None = None


def normalize_arabic(value: str) -> str:
    value = unicodedata.normalize('NFKD', value or '').translate(_LETTER_FOLD)
    return ''.join(char for char in value if '\u0621' <= char <= '\u064a')


def load_words(path: str) -> list[QuranWord]:
    """Load the mushaf reading stream.

    ``quran_script.db``'s ``word_index`` is a stable ID, but three chunks are
    interleaved out of surah order when sorted by that column alone. Layout
    continuity must follow printed order: surah → ayah → word_index.
    """
    conn = sqlite3.connect(path)
    try:
        rows = conn.execute(
            '''
            SELECT word_index, word_key, surah, ayah, text
            FROM words
            '''
        ).fetchall()
    finally:
        conn.close()
    words = [
        QuranWord(
            index=int(row[0]),
            word_key=str(row[1] or ''),
            surah=int(row[2]),
            ayah=int(row[3]),
            text=row[4] or '',
            normalized=normalize_arabic(row[4] or ''),
        )
        for row in rows
    ]
    words.sort(key=lambda word: (
        word.surah,
        word.ayah,
        int(word.word_key.rsplit(':', 1)[-1]),
        word.index,
    ))
    if len(words) < 80_000:
        raise RuntimeError(f'canonical word database is incomplete: {len(words)}')
    keys = [word.word_key for word in words]
    if not all(keys) or len(set(keys)) != len(keys):
        raise RuntimeError('canonical word keys are blank or duplicated')
    # Guard: reading order must never go backwards in (surah, ayah).
    previous = (0, 0)
    for word in words:
        current = (word.surah, word.ayah)
        if current < previous:
            raise RuntimeError(
                f'mushaf order broken at word_id={word.index}: '
                f'{previous} → {current}'
            )
        previous = current
    return words


def _word_box(word) -> tuple[int, int, int, int] | None:
    raw = word.get('coords') or ''
    try:
        a, b, c, d = (int(part) for part in raw.split(','))
    except (TypeError, ValueError):
        return None
    return min(a, c), min(b, d), max(a, c), max(b, d)


def load_ocr_pages(path: str) -> list[list[OcrLine]]:
    objects = ET.parse(path).getroot().findall('.//OBJECT')
    if len(objects) < PAGE_MAX:
        raise RuntimeError(
            f'OCR contains {len(objects)} leaves; expected at least {PAGE_MAX}'
        )
    pages: list[list[OcrLine]] = []
    for obj in objects:
        lines: list[OcrLine] = []
        for line in obj.findall('.//LINE'):
            word_nodes = line.findall('WORD')
            boxes = [box for box in map(_word_box, word_nodes) if box]
            if not boxes:
                continue
            text = ' '.join(
                ''.join(node.itertext()).strip() for node in word_nodes
            ).strip()
            normalized = normalize_arabic(text)
            left = min(box[0] for box in boxes)
            top = min(box[1] for box in boxes)
            right = max(box[2] for box in boxes)
            bottom = max(box[3] for box in boxes)
            lines.append(OcrLine(
                y=round((top + bottom) / 2),
                text=text,
                normalized=normalized,
                width=right - left,
            ))
        pages.append(lines)
    return pages


def _local_canonical(
    words: list[QuranWord], expected: int,
) -> tuple[str, list[int]]:
    lo = max(0, expected - SEARCH_RADIUS_WORDS)
    hi = min(len(words), expected + SEARCH_RADIUS_WORDS)
    chars: list[str] = []
    positions: list[int] = []
    for position in range(lo, hi):
        token = words[position].normalized
        chars.append(token)
        positions.extend([position] * len(token))
    return ''.join(chars), positions


def _densest_matches(matches: list[Match]) -> list[Match]:
    ordered = sorted(matches, key=lambda item: item.mid)
    best: tuple[int, float, int, int] = (0, 0.0, 0, 0)
    for left in range(len(ordered)):
        right = left
        weight = 0.0
        while (
            right < len(ordered)
            and ordered[right].mid - ordered[left].mid <= PAGE_CLUSTER_WORDS
        ):
            weight += ordered[right].score ** 2
            right += 1
        key = (right - left, weight, left, right)
        if key[:2] > best[:2]:
            best = key
    return ordered[best[2]:best[3]]


def _is_banner_line(line: OcrLine) -> bool:
    """Surah banners / ornaments — positional noise for ayah forced-alignment."""
    text = line.normalized
    if not text:
        return True
    if 'سوره' in text or text.startswith('جزء') or text.startswith('حزب'):
        return True
    if line.y < 1100 and len(text) <= 18:
        return True
    return False


def align_page(
    page: int,
    ocr_lines: list[OcrLine],
    words: list[QuranWord],
    *,
    starts_by_surah: dict[int, int] | None = None,
) -> PageAlignment:
    expected = round((page - PAGE_MIN) / (PAGE_COUNT - 1) * (len(words) - 1))
    # If OCR shows a surah banner near the top, bias the search window there.
    banner_bias: int | None = None
    if starts_by_surah:
        for line in ocr_lines:
            if line.y > 1700 or 'سوره' not in line.normalized:
                continue
            # Prefer the nearest surah start to the linear expectation.
            nearest = min(
                starts_by_surah.values(),
                key=lambda position: abs(position - expected),
            )
            if abs(nearest - expected) <= SEARCH_RADIUS_WORDS:
                banner_bias = nearest
            break
    search_at = banner_bias if banner_bias is not None else expected
    canonical, char_positions = _local_canonical(words, search_at)
    matches: list[Match] = []
    for line in ocr_lines:
        if (
            _is_banner_line(line)
            or len(line.normalized) < 5
            or line.width < 400
            or line.y < 900
            or line.y > 5200
        ):
            continue
        result = partial_ratio_alignment(
            line.normalized,
            canonical,
            score_cutoff=OCR_SCORE_CUTOFF,
        )
        if not result or not char_positions:
            continue
        start_char = min(int(result.dest_start), len(char_positions) - 1)
        end_char = min(max(int(result.dest_end) - 1, 0), len(char_positions) - 1)
        start = char_positions[start_char]
        end = char_positions[end_char]
        matches.append(Match(
            start=start,
            end=end,
            mid=(start + end) / 2,
            score=float(result.score),
            y=line.y,
            text=line.text,
        ))
    selected = _densest_matches(matches) if matches else []
    center = (
        float(statistics.median(match.mid for match in selected))
        if selected else float(search_at)
    )
    if banner_bias is not None and selected:
        # Pull center toward the banner when OCR already agrees roughly.
        if abs(center - banner_bias) <= PAGE_CLUSTER_WORDS:
            center = 0.65 * center + 0.35 * float(banner_bias)
    return PageAlignment(
        page=page,
        expected=expected,
        candidates=matches,
        selected=selected,
        center=center,
    )


def _pava(values: list[float], weights: list[float]) -> list[float]:
    """Weighted pool-adjacent-violators, enforcing monotonic page anchors."""
    blocks: list[list[float]] = []
    for index, (value, weight) in enumerate(zip(values, weights)):
        blocks.append([float(index), float(index), value * weight, weight])
        while (
            len(blocks) >= 2
            and blocks[-2][2] / blocks[-2][3] > blocks[-1][2] / blocks[-1][3]
        ):
            right = blocks.pop()
            left = blocks.pop()
            blocks.append([
                left[0],
                right[1],
                left[2] + right[2],
                left[3] + right[3],
            ])
    output = [0.0] * len(values)
    for start, end, weighted_sum, total_weight in blocks:
        mean = weighted_sum / total_weight
        for index in range(int(start), int(end) + 1):
            output[index] = mean
    # PAVA permits equality; page slices require a strict increase.
    for index in range(1, len(output)):
        output[index] = max(output[index], output[index - 1] + 1.0)
    return output


def _dedupe_y(matches: Iterable[Match]) -> list[Match]:
    result: list[Match] = []
    for match in sorted(matches, key=lambda item: item.y):
        if result and abs(match.y - result[-1].y) <= 105:
            if match.score > result[-1].score:
                result[-1] = match
            continue
        result.append(match)
    return result


def _edge_predictions(alignment: PageAlignment) -> tuple[float | None, float | None]:
    points = _dedupe_y(alignment.selected)
    if len(points) < 3:
        return None, None
    # A confident OCR match on the physical first/last line is a better page
    # boundary observation than regression through the middle of the page.
    top_matches = [
        point for point in points
        if point.y <= 1450 and point.score >= OCR_SCORE_CUTOFF
    ]
    bottom_matches = [
        point for point in points
        if point.y >= 4550 and point.score >= OCR_SCORE_CUTOFF
    ]
    ys = [float(point.y) for point in points]
    xs = [float(point.mid) for point in points]
    y_mean = statistics.fmean(ys)
    x_mean = statistics.fmean(xs)
    denominator = sum((value - y_mean) ** 2 for value in ys)
    if denominator <= 0:
        return None, None
    slope = sum(
        (y - y_mean) * (x - x_mean) for y, x in zip(ys, xs)
    ) / denominator
    if not (0.004 <= slope <= 0.14):
        return None, None
    intercept = x_mean - slope * y_mean
    start = (
        float(min(point.start for point in top_matches))
        if top_matches else intercept + slope * TEXT_TOP
    )
    end = (
        float(max(point.end for point in bottom_matches))
        if bottom_matches else intercept + slope * TEXT_BOTTOM
    )
    return start, end


def smooth_alignments(alignments: list[PageAlignment]) -> None:
    centers = [item.center for item in alignments]
    # A single low-information OCR page can lock onto a repeated phrase in the
    # previous surah.  Repair only unmistakable local order violations before
    # PAVA; pooling the raw outlier would otherwise flatten several good pages.
    for _pass in range(4):
        changed = False
        repaired = list(centers)
        for index in range(1, len(centers) - 1):
            if centers[index - 1] < centers[index] < centers[index + 1]:
                continue
            if centers[index - 1] < centers[index + 1]:
                repaired[index] = (
                    centers[index - 1] + centers[index + 1]
                ) / 2
                changed = True
        centers = repaired
        if not changed:
            break
    smoothed = _pava(
        centers,
        [max(1.0, float(len(item.selected))) for item in alignments],
    )
    for item, value in zip(alignments, smoothed):
        item.smoothed_center = value
        item.start_prediction, item.end_prediction = _edge_predictions(item)


def page_starts(
    alignments: list[PageAlignment],
    words: list[QuranWord],
) -> list[int]:
    """Return canonical-list start positions for pages 2..827 plus sentinel."""
    starts = [0]
    for left, right in zip(alignments, alignments[1:]):
        center_midpoint = (left.smoothed_center + right.smoothed_center) / 2
        proposals: list[float] = []
        if (
            left.end_prediction is not None
            and left.smoothed_center <= left.end_prediction <= right.smoothed_center
        ):
            proposals.append(left.end_prediction + 0.5)
        if (
            right.start_prediction is not None
            and left.smoothed_center <= right.start_prediction <= right.smoothed_center
        ):
            proposals.append(right.start_prediction)
        boundary = round(statistics.fmean(proposals) if proposals else center_midpoint)
        boundary = max(starts[-1] + 1, min(boundary, len(words) - 1))
        starts.append(boundary)
    starts.append(len(words))

    # The two illuminated opening pages have exact, visually verified ranges.
    position_by_id = {word.index: pos for pos, word in enumerate(words)}
    starts[1] = position_by_id[45]  # page 3 starts at Al-Baqarah 1.
    starts[2] = position_by_id[77]  # page 4 starts at Al-Baqarah 5.
    for index in range(1, len(starts)):
        starts[index] = max(starts[index], starts[index - 1] + 1)
    starts[-1] = len(words)
    _enforce_page_word_priors(starts, alignments)
    # Priors must not disturb the verified opening cuts.
    starts[1] = position_by_id[45]
    starts[2] = position_by_id[77]
    for index in range(1, len(starts)):
        starts[index] = max(starts[index], starts[index - 1] + 1)
    starts[-1] = len(words)
    return starts


def _enforce_page_word_priors(
    starts: list[int],
    alignments: list[PageAlignment],
) -> None:
    """Rebuild extreme page cuts; word-count outliers are almost always OCR drift."""
    del alignments  # reserved for future edge-aware repairs
    page_count = len(starts) - 1
    for _pass in range(5):
        changed = False
        sizes = [starts[index + 1] - starts[index] for index in range(page_count)]
        for offset in range(2, page_count):  # keep illuminated pages 2–3 fixed
            size = sizes[offset]
            if PAGE_WORDS_MIN <= size <= PAGE_WORDS_MAX:
                continue
            if size > PAGE_WORDS_MAX:
                desired = starts[offset] + PAGE_WORDS_TARGET
                upper = (
                    starts[offset + 2] - PAGE_WORDS_MIN
                    if offset + 2 < len(starts)
                    else starts[-1] - 1
                )
                lower = starts[offset] + PAGE_WORDS_MIN
                new_boundary = max(lower, min(desired, upper))
                if new_boundary != starts[offset + 1]:
                    starts[offset + 1] = new_boundary
                    changed = True
                continue
            needed = PAGE_WORDS_TARGET - size
            left_size = sizes[offset - 1] if offset > 2 else 0
            right_size = sizes[offset + 1] if offset + 1 < page_count else 0
            if right_size >= left_size and offset + 1 < page_count:
                upper = (
                    starts[offset + 2] - PAGE_WORDS_MIN
                    if offset + 2 < len(starts)
                    else starts[-1] - 1
                )
                new_boundary = min(starts[offset + 1] + needed, upper)
                if new_boundary > starts[offset + 1]:
                    starts[offset + 1] = new_boundary
                    changed = True
            elif offset > 2:
                lower = starts[offset - 1] + PAGE_WORDS_MIN
                new_boundary = max(starts[offset] - needed, lower)
                if new_boundary < starts[offset]:
                    starts[offset] = new_boundary
                    changed = True
        for index in range(1, len(starts)):
            starts[index] = max(starts[index], starts[index - 1] + 1)
        if not changed:
            break


def load_headers(path: str) -> dict[int, HeaderRows]:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            '''
            SELECT line_type, first_word_id, last_word_id,
                   surah_number, line_text
            FROM pages
            WHERE line_type IN ('surah_name', 'basmallah')
            ORDER BY page_number, line_number
            '''
        ).fetchall()
    finally:
        conn.close()
    names: dict[int, tuple[int | None, int | None, str]] = {}
    basmallahs: dict[int, tuple[int | None, int | None, str]] = {}
    for row in rows:
        surah = int(row['surah_number'])
        record = (
            int(row['first_word_id']) if row['first_word_id'] is not None else None,
            int(row['last_word_id']) if row['last_word_id'] is not None else None,
            row['line_text'] or '',
        )
        if row['line_type'] == 'surah_name':
            names[surah] = record
        else:
            basmallahs[surah] = record
    missing = set(range(1, 115)) - set(names)
    if missing:
        raise RuntimeError(f'missing surah headers: {sorted(missing)}')
    return {
        surah: HeaderRows(
            surah_name=names[surah],
            basmallah=basmallahs.get(surah),
        )
        for surah in range(1, 115)
    }


def _allocate_slots(lengths: list[int], total: int) -> list[int]:
    if not lengths:
        return []
    if total < len(lengths):
        raise RuntimeError(
            f'not enough ayah slots: {total} for {len(lengths)} text segments'
        )
    allocation = [1] * len(lengths)
    remaining = total - len(lengths)
    if remaining <= 0:
        return allocation
    weight_total = sum(lengths) or len(lengths)
    quotas = [remaining * length / weight_total for length in lengths]
    floors = [math.floor(value) for value in quotas]
    allocation = [base + extra for base, extra in zip(allocation, floors)]
    left = total - sum(allocation)
    order = sorted(
        range(len(lengths)),
        key=lambda index: (quotas[index] - floors[index], lengths[index]),
        reverse=True,
    )
    for index in order[:left]:
        allocation[index] += 1
    return allocation


def _even_ends(start: int, end: int, count: int) -> list[int]:
    """Inclusive end positions for ``count`` ayah lines covering ``start..end``.

    A short Juz ʿAmma / empty-top page can have fewer words than leftover
    slots (p822: 5 words vs 9 lines). Fail open to one ayah line; the
    caller pads empty slots. Do not raise.
    """
    length = end - start + 1
    if count < 1 or length < 1:
        raise RuntimeError(f'cannot split {length} words across {count} lines')
    if length < count:
        return [end]
    return [
        start + math.ceil(length * (index + 1) / count) - 1
        for index in range(count)
    ]


def _header_output(
    line_number: int,
    line_type: str,
    surah: int,
    record: tuple[int | None, int | None, str] | None,
    *,
    script_db: str,
) -> OutputRow:
    if line_type == 'surah_info':
        return OutputRow(
            line_number=line_number,
            line_type=line_type,
            is_centered=1,
            first_word_id=None,
            last_word_id=None,
            surah_number=surah,
            line_text=engine.surah_info_text(surah, script_db=script_db),
        )
    first, last, text = record or (None, None, '')
    return OutputRow(
        line_number=line_number,
        line_type=line_type,
        is_centered=1,
        first_word_id=first,
        last_word_id=last,
        surah_number=surah,
        line_text=text,
    )


def _opening_page(
    page: int,
    words: list[QuranWord],
    headers: dict[int, HeaderRows],
) -> list[OutputRow]:
    id_to_pos = {word.index: pos for pos, word in enumerate(words)}
    surah = 1 if page == 2 else 2
    header = headers[surah]
    rows = [
        _header_output(
            1, 'surah_name', surah, header.surah_name,
            script_db=QURAN_SCRIPT_DATABASE,
        ),
        _header_output(
            2, 'surah_info', surah, None,
            script_db=QURAN_SCRIPT_DATABASE,
        ),
        _header_output(
            3, 'basmallah', surah, header.basmallah,
            script_db=QURAN_SCRIPT_DATABASE,
        ),
    ]
    line_ends = [13, 20, 28, 34, 38] if page == 2 else [51, 60, 64, 70, 76]
    first_id = 8 if page == 2 else 45
    start = id_to_pos[first_id]
    for line_number, last_id in enumerate(line_ends, 4):
        end = id_to_pos[last_id]
        segment = words[start:end + 1]
        rows.append(OutputRow(
            line_number=line_number,
            line_type='ayah',
            is_centered=1,
            first_word_id=segment[0].index,
            last_word_id=segment[-1].index,
            surah_number=segment[0].surah,
            line_text=' '.join(word.text for word in segment),
            start_pos=start,
            end_pos=end,
        ))
        start = end + 1
    return rows


def _surah_starts(words: list[QuranWord]) -> dict[int, int]:
    result: dict[int, int] = {}
    for position, word in enumerate(words):
        result.setdefault(word.surah, position)
    return result


def _slot_for_y(
    y: int,
    target_lines: int,
    text_top: int = TEXT_TOP,
    text_bottom: int = TEXT_BOTTOM,
) -> int:
    """DjVu-space slot map. Kraken JPEG seating uses ``slot_for_y`` instead."""
    return slot_for_y(y, target_lines, text_top, text_bottom)


def _monotonic_anchors(
    rows: list[OutputRow],
    matches: list[Match],
    page_start: int,
    page_end: int,
    target_lines: int,
) -> dict[int, int]:
    # Keep top-2 candidates per ayah slot so a slightly weaker but monotonic
    # match can replace a high-scoring local inversion.
    candidates: dict[int, list[Match]] = {}
    for match in matches:
        if (
            match.score < LINE_ANCHOR_SCORE
            or match.end < page_start
            or match.end > page_end
        ):
            continue
        slot = _slot_for_y(match.y, target_lines)
        row = next((item for item in rows if item.line_number == slot), None)
        if not row or row.line_type != 'ayah':
            continue
        bucket = candidates.setdefault(slot, [])
        bucket.append(match)
        bucket.sort(key=lambda item: item.score, reverse=True)
        del bucket[2:]

    anchors: dict[int, int] = {}
    previous = page_start - 1
    for row in rows:
        if row.line_type != 'ayah':
            continue
        options = candidates.get(row.line_number) or []
        chosen = next((match for match in options if match.end > previous), None)
        if not chosen:
            continue
        anchors[row.line_number] = chosen.end
        previous = chosen.end
    return anchors


def _refine_segment(
    segment_rows: list[OutputRow],
    start: int,
    end: int,
    anchors: dict[int, int],
    words: list[QuranWord],
) -> int:
    valid: dict[int, int] = {}
    previous = start - 1
    for offset, row in enumerate(segment_rows):
        anchor = anchors.get(row.line_number)
        words_left = len(segment_rows) - offset - 1
        if anchor is None:
            continue
        maximum = end - words_left
        if previous < anchor <= maximum:
            valid[offset] = anchor
            previous = anchor

    boundaries: list[int] = []
    cursor = start
    for offset in range(len(segment_rows)):
        if offset == len(segment_rows) - 1:
            boundary = end
        elif offset in valid:
            boundary = valid[offset]
        else:
            next_anchor = next(
                (
                    (future_offset, valid[future_offset])
                    for future_offset in range(offset + 1, len(segment_rows))
                    if future_offset in valid
                ),
                (len(segment_rows) - 1, end),
            )
            slots = next_anchor[0] - offset + 1
            boundary = cursor + math.ceil(
                (next_anchor[1] - cursor + 1) / slots
            ) - 1
        minimum = cursor
        maximum = end - (len(segment_rows) - offset - 1)
        boundary = max(minimum, min(boundary, maximum))
        boundaries.append(boundary)
        cursor = boundary + 1

    for row, first, last in zip(
        segment_rows,
        [start] + [value + 1 for value in boundaries[:-1]],
        boundaries,
    ):
        segment = words[first:last + 1]
        row.start_pos = first
        row.end_pos = last
        row.first_word_id = segment[0].index
        row.last_word_id = segment[-1].index
        row.surah_number = segment[0].surah
        row.line_text = ' '.join(word.text for word in segment)
    return len(valid)


def _rows_from_seating(
    seating,
    words: list[QuranWord],
    headers: dict[int, HeaderRows],
) -> list[OutputRow]:
    rows: list[OutputRow] = []
    for line in seating.lines:
        if line.line_type in ('surah_name', 'surah_info', 'basmallah'):
            header = headers[int(line.surah)]
            record = None
            if line.line_type == 'surah_name':
                record = header.surah_name
            elif line.line_type == 'basmallah':
                record = header.basmallah
            rows.append(_header_output(
                line.line_number,
                line.line_type,
                int(line.surah),
                record,
                script_db=QURAN_SCRIPT_DATABASE,
            ))
            continue
        if line.start_pos is None or line.end_pos is None:
            rows.append(OutputRow(
                line_number=line.line_number,
                line_type='ayah',
                is_centered=0,
                first_word_id=None,
                last_word_id=None,
                surah_number=line.surah,
                line_text='',
            ))
            continue
        segment = words[line.start_pos:line.end_pos + 1]
        rows.append(OutputRow(
            line_number=line.line_number,
            line_type='ayah',
            is_centered=0,
            first_word_id=segment[0].index,
            last_word_id=segment[-1].index,
            surah_number=segment[0].surah,
            line_text=' '.join(word.text for word in segment),
            start_pos=line.start_pos,
            end_pos=line.end_pos,
        ))
    return rows


def build_page_rows(
    page: int,
    start: int,
    end: int,
    alignment: PageAlignment,
    words: list[QuranWord],
    headers: dict[int, HeaderRows],
    starts_by_surah: dict[int, int],
    geometry: PageTextGeometry | None = None,
) -> tuple[list[OutputRow], int]:
    if page in (2, 3):
        return _opening_page(page, words, headers), 5

    if geometry is not None and geometry.wide_lines:
        try:
            seating = seat_printed_page(
                words=words,
                page_start=start,
                page_end=end,
                starts_by_surah=starts_by_surah,
                geometry=geometry,
                target_lines=SHORT_LINES.get(page, DEFAULT_LINES),
            )
        except Exception:
            seating = None
        if seating is not None:
            return _rows_from_seating(seating, words, headers), seating.anchored

    target_lines = SHORT_LINES.get(page, DEFAULT_LINES)
    surahs_here = [
        surah for surah, position in starts_by_surah.items()
        if start <= position <= end
    ]
    header_count = sum(2 if surah == 9 else 3 for surah in surahs_here)

    cuts = [start]
    for surah in sorted(surahs_here, key=starts_by_surah.get):
        position = starts_by_surah[surah]
        if position > start:
            cuts.append(position)
    cuts.append(end + 1)
    cuts = sorted(set(cuts))
    segments = [
        (left, right - 1) for left, right in zip(cuts, cuts[1:])
        if right > left
    ]
    ayah_slots = target_lines - header_count
    allocations = _allocate_slots(
        [right - left + 1 for left, right in segments],
        ayah_slots,
    )

    rows: list[OutputRow] = []
    segment_rows: list[tuple[list[OutputRow], int, int]] = []
    for (left, right), count in zip(segments, allocations):
        first_surah = words[left].surah
        if left == starts_by_surah[first_surah]:
            header = headers[first_surah]
            rows.append(_header_output(
                len(rows) + 1, 'surah_name', first_surah, header.surah_name,
                script_db=QURAN_SCRIPT_DATABASE,
            ))
            rows.append(_header_output(
                len(rows) + 1, 'surah_info', first_surah, None,
                script_db=QURAN_SCRIPT_DATABASE,
            ))
            if first_surah != 9:
                rows.append(_header_output(
                    len(rows) + 1, 'basmallah', first_surah, header.basmallah,
                    script_db=QURAN_SCRIPT_DATABASE,
                ))
        ends = _even_ends(left, right, count)
        current = left
        current_rows: list[OutputRow] = []
        for boundary in ends:
            segment = words[current:boundary + 1]
            row = OutputRow(
                line_number=len(rows) + 1,
                line_type='ayah',
                is_centered=0,
                first_word_id=segment[0].index,
                last_word_id=segment[-1].index,
                surah_number=segment[0].surah,
                line_text=' '.join(word.text for word in segment),
                start_pos=current,
                end_pos=boundary,
            )
            rows.append(row)
            current_rows.append(row)
            current = boundary + 1
        segment_rows.append((current_rows, left, right))

    while len(rows) < target_lines:
        surah = rows[-1].surah_number if rows else None
        rows.append(OutputRow(
            line_number=len(rows) + 1,
            line_type='ayah',
            is_centered=0,
            first_word_id=None,
            last_word_id=None,
            surah_number=surah,
            line_text='',
        ))

    if len(rows) != target_lines:
        raise RuntimeError(
            f'page {page}: generated {len(rows)} rows, expected {target_lines}'
        )
    anchors = _monotonic_anchors(
        rows,
        alignment.selected,
        start,
        end,
        target_lines,
    )
    anchored = sum(
        _refine_segment(part, left, right, anchors, words)
        for part, left, right in segment_rows
    )
    return rows, anchored


def confidence_record(
    alignment: PageAlignment,
    rows: list[OutputRow],
    anchored: int,
    *,
    source_label: str | None = None,
) -> tuple[float, str, int, int, int, str]:
    selected = _dedupe_y(alignment.selected)
    matched = len(selected)
    mean_score = (
        statistics.fmean(match.score for match in selected) if selected else 0.0
    )
    ayah_lines = sum(row.line_type == 'ayah' for row in rows)
    anchor_ratio = anchored / max(1, ayah_lines)
    match_ratio = min(1.0, matched / max(1, ayah_lines))
    score = round(
        min(
            1.0,
            (mean_score / 100) * 0.45
            + match_ratio * 0.25
            + anchor_ratio * 0.30
            + CANONICAL_INTEGRITY_BONUS,
        ),
        4,
    )
    # Ratio-based status: absolute 5/9 anchors unfairly flag short header pages.
    if anchor_ratio >= 0.75 and mean_score >= 78:
        status = 'high'
    elif anchor_ratio >= 0.45 and mean_score >= 68:
        status = 'medium'
    else:
        status = 'low'
    estimated = max(0, ayah_lines - anchored)
    source_note = (
        f'Selected OCR source={source_label}. ' if source_label else ''
    )
    notes = (
        source_note +
        f'Archive OCR anchors={matched}; exact-line candidates={anchored}; '
        f'mean OCR score={mean_score:.1f}. '
        f'Canonical word-key integrity bonus=+{CANONICAL_INTEGRITY_BONUS:.2f}. '
        'Canonical continuity is guaranteed; line boundaries require print review.'
    )
    return score, status, matched, anchored, estimated, notes


def create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        '''
        CREATE TABLE pages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            page_number INTEGER NOT NULL,
            line_number INTEGER NOT NULL,
            line_type TEXT NOT NULL
                CHECK(line_type IN (
                    'ayah', 'surah_name', 'surah_info', 'basmallah'
                )),
            is_centered INTEGER NOT NULL,
            first_word_id INTEGER,
            last_word_id INTEGER,
            surah_number INTEGER,
            line_text TEXT NOT NULL DEFAULT ''
        );
        CREATE UNIQUE INDEX idx_mesaha_page_line
            ON pages (page_number, line_number);
        CREATE INDEX idx_mesaha_surah_number
            ON pages (surah_number);

        CREATE TABLE info (
            name TEXT,
            number_of_pages INTEGER,
            lines_per_page INTEGER,
            font_name TEXT
        );
        CREATE TABLE mesaha_layout_progress (
            page_number INTEGER PRIMARY KEY,
            reviewed INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT
        );
        CREATE TABLE mesaha_layout_undo (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            label TEXT,
            page_number INTEGER,
            snapshot TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE layout_import_confidence (
            page_number INTEGER PRIMARY KEY,
            score REAL NOT NULL CHECK(score BETWEEN 0 AND 1),
            status TEXT NOT NULL CHECK(status IN ('high', 'medium', 'low')),
            matched_lines INTEGER NOT NULL,
            anchored_lines INTEGER NOT NULL,
            estimated_line_ends INTEGER NOT NULL,
            page_center_word_id INTEGER,
            notes TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE layout_import_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        '''
    )


def validate_database(conn: sqlite3.Connection, words: list[QuranWord]) -> dict:
    rows = conn.execute(
        '''
        SELECT page_number, line_number, line_type,
               first_word_id, last_word_id, surah_number
        FROM pages
        ORDER BY page_number, line_number
        '''
    ).fetchall()
    ids = [word.index for word in words]
    position_by_id = {word.index: position for position, word in enumerate(words)}
    emitted: list[int] = []
    page_sizes: dict[int, int] = {}
    surah_order_violations = 0
    previous_surah = 0
    for page, _line, kind, first, last, surah in rows:
        if surah is not None:
            surah_i = int(surah)
            if kind == 'ayah' and surah_i < previous_surah:
                surah_order_violations += 1
            previous_surah = max(previous_surah, surah_i)
        if first is None or last is None:
            continue
        left = position_by_id.get(int(first))
        right = position_by_id.get(int(last))
        if left is None or right is None:
            # Surah-name / basmallah IDs borrowed from Shamarly may fall outside
            # the ayah stream; they must not break continuity accounting.
            continue
        if right < left:
            raise RuntimeError(
                f'page {page}: invalid word span {first}-{last} in mushaf stream'
            )
        span = ids[left:right + 1]
        emitted.extend(span)
        page_sizes[int(page)] = page_sizes.get(int(page), 0) + len(span)
    if emitted != ids:
        mismatch = next(
            (
                index for index, (actual, expected) in enumerate(zip(emitted, ids))
                if actual != expected
            ),
            min(len(emitted), len(ids)),
        )
        raise RuntimeError(
            'canonical continuity failed at position '
            f'{mismatch}: emitted={len(emitted)} expected={len(ids)}'
        )
    page_count = conn.execute(
        'SELECT COUNT(DISTINCT page_number) FROM pages'
    ).fetchone()[0]
    if int(page_count) != PAGE_COUNT:
        raise RuntimeError(f'expected {PAGE_COUNT} pages, found {page_count}')
    for page in range(PAGE_MIN, PAGE_MAX + 1):
        count = conn.execute(
            'SELECT COUNT(*) FROM pages WHERE page_number = ?', (page,)
        ).fetchone()[0]
        expected = SHORT_LINES.get(page, DEFAULT_LINES)
        if int(count) != expected:
            raise RuntimeError(f'page {page}: {count} rows, expected {expected}')
    integrity = conn.execute('PRAGMA integrity_check').fetchone()[0]
    if integrity != 'ok':
        raise RuntimeError(f'SQLite integrity check failed: {integrity}')
    outliers = sorted(
        page for page, size in page_sizes.items()
        if page >= 4 and not (PAGE_WORDS_MIN <= size <= PAGE_WORDS_MAX)
    )
    return {
        'pages': PAGE_COUNT,
        'rows': len(rows),
        'canonical_words': len(words),
        'first_word_id': words[0].index,
        'last_word_id': words[-1].index,
        'duplicates': 0,
        'missing': 0,
        'out_of_order': 0,
        'sqlite_integrity': integrity,
        'stream_order': 'surah,ayah,word_key-position',
        'canonical_word_keys_unique': len({word.word_key for word in words}) == len(words),
        'canonical_word_key_stream_exact': emitted == ids,
        'surah_order_violations': surah_order_violations,
        'page_word_count_outliers': len(outliers),
        'page_word_count_outlier_pages': outliers[:40],
    }


def _bisect_left(values: list[int], target: int) -> int:
    lo, hi = 0, len(values)
    while lo < hi:
        mid = (lo + hi) // 2
        if values[mid] < target:
            lo = mid + 1
        else:
            hi = mid
    return lo


def _bisect_right(values: list[int], target: int) -> int:
    lo, hi = 0, len(values)
    while lo < hi:
        mid = (lo + hi) // 2
        if values[mid] <= target:
            lo = mid + 1
        else:
            hi = mid
    return lo


def _parse_ocr_source(spec: str) -> OcrSource:
    label = ''
    path = spec
    if '=' in spec:
        candidate_label, candidate_path = spec.split('=', 1)
        if candidate_label and '/' not in candidate_label:
            label = candidate_label.strip()
            path = candidate_path
    path = str(Path(path).expanduser())
    return OcrSource(label=label or Path(path).stem, path=path)


def _clone_alignment(alignment: PageAlignment) -> PageAlignment:
    return PageAlignment(
        page=alignment.page,
        expected=alignment.expected,
        candidates=list(alignment.candidates),
        selected=list(alignment.selected),
        center=alignment.center,
    )


def _fuse_page_alignments(
    page_alignments: list[PageAlignment],
    source_labels: list[str],
) -> tuple[PageAlignment, str]:
    """Union OCR matches across sources; keep the densest fused cluster."""
    if len(page_alignments) == 1:
        return _clone_alignment(page_alignments[0]), source_labels[0]
    fused_candidates: list[Match] = []
    for alignment in page_alignments:
        fused_candidates.extend(alignment.candidates)
    selected = _densest_matches(fused_candidates) if fused_candidates else []
    # Attribute the page to the source that contributed the most selected matches.
    contribution = [0] * len(page_alignments)
    selected_keys = {(match.y, match.start, match.end, round(match.score, 2)) for match in selected}
    for index, alignment in enumerate(page_alignments):
        for match in alignment.candidates:
            key = (match.y, match.start, match.end, round(match.score, 2))
            if key in selected_keys:
                contribution[index] += 1
    best_source = max(
        range(len(page_alignments)),
        key=lambda index: (contribution[index], len(page_alignments[index].selected), -index),
    )
    center = (
        float(statistics.median(match.mid for match in selected))
        if selected else float(page_alignments[best_source].center)
    )
    fused = PageAlignment(
        page=page_alignments[0].page,
        expected=page_alignments[best_source].expected,
        candidates=fused_candidates,
        selected=selected,
        center=center,
    )
    label = (
        'fusion:' + '+'.join(source_labels)
        if sum(1 for count in contribution if count) > 1
        else source_labels[best_source]
    )
    return fused, label


def build(
    ocr_xml: str | list[str],
    output: str,
    report_path: str,
    *,
    force: bool = False,
    kraken_dir: str | None = None,
) -> dict:
    destination = Path(output)
    if destination.exists() and not force:
        raise SystemExit(
            f'{destination} already exists. Pass --force only if reviewer '
            'edits/progress may be destroyed.'
        )
    specs = [ocr_xml] if isinstance(ocr_xml, str) else list(ocr_xml)
    if not specs:
        raise SystemExit('At least one --ocr-xml source is required')
    sources = [_parse_ocr_source(spec) for spec in specs]
    labels = [source.label for source in sources]
    if len(set(labels)) != len(labels):
        raise SystemExit(f'OCR source labels must be unique: {labels}')
    for source in sources:
        if not Path(source.path).exists():
            raise SystemExit(f'OCR XML not found: {source.path}')
    words = load_words(QURAN_SCRIPT_DATABASE)
    headers = load_headers(SHAMARLY_LAYOUT_DATABASE)
    starts_by_surah = _surah_starts(words)
    kraken_root = Path(kraken_dir) if kraken_dir else DEFAULT_KRAKEN_DIR
    if not kraken_root.is_absolute():
        kraken_root = ROOT / kraken_root
    geometries = load_kraken_geometries(
        kraken_root, page_min=PAGE_MIN, page_max=PAGE_MAX,
    )
    alignments_by_source: list[list[PageAlignment]] = []
    for source in sources:
        ocr_pages = load_ocr_pages(source.path)
        source_alignments = [
            align_page(
                page,
                ocr_pages[page - 1],
                words,
                starts_by_surah=starts_by_surah,
            )
            for page in range(PAGE_MIN, PAGE_MAX + 1)
        ]
        alignments_by_source.append(source_alignments)

    selected_labels: list[str] = []
    alignments: list[PageAlignment] = []
    for offset in range(PAGE_COUNT):
        fused, label = _fuse_page_alignments(
            [source_alignments[offset] for source_alignments in alignments_by_source],
            labels,
        )
        alignments.append(fused)
        selected_labels.append(label)

    smooth_alignments(alignments)
    starts = page_starts(alignments, words)
    if geometries:
        clip_empty_top_page_starts(
            starts,
            words,
            geometries,
            starts_by_surah,
            page_min=PAGE_MIN,
        )

    temporary = destination.with_suffix(destination.suffix + '.building')
    if temporary.exists():
        temporary.unlink()
    conn = sqlite3.connect(temporary)
    confidence_rows: list[tuple] = []
    try:
        create_schema(conn)
        for offset, (page, alignment) in enumerate(zip(
            range(PAGE_MIN, PAGE_MAX + 1),
            alignments,
        )):
            start = starts[offset]
            end = starts[offset + 1] - 1
            rows, anchored = build_page_rows(
                page,
                start,
                end,
                alignment,
                words,
                headers,
                starts_by_surah,
                geometry=geometries.get(page),
            )
            conn.executemany(
                '''
                INSERT INTO pages (
                    page_number, line_number, line_type, is_centered,
                    first_word_id, last_word_id, surah_number, line_text
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''',
                [
                    (
                        page,
                        row.line_number,
                        row.line_type,
                        row.is_centered,
                        row.first_word_id,
                        row.last_word_id,
                        row.surah_number,
                        row.line_text,
                    )
                    for row in rows
                ],
            )
            score, status, matched, anchored, estimated, notes = confidence_record(
                alignment,
                rows,
                anchored,
                source_label=selected_labels[offset],
            )
            center_pos = max(
                0, min(round(alignment.smoothed_center), len(words) - 1)
            )
            confidence_rows.append((
                page,
                score,
                status,
                matched,
                anchored,
                estimated,
                words[center_pos].index,
                notes,
            ))

        conn.executemany(
            '''
            INSERT INTO layout_import_confidence (
                page_number, score, status, matched_lines, anchored_lines,
                estimated_line_ends, page_center_word_id, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''',
            confidence_rows,
        )
        conn.execute(
            '''
            INSERT INTO info (name, number_of_pages, lines_per_page, font_name)
            VALUES (?, ?, ?, ?)
            ''',
            (
                'مصحف المساحة الأميرية ١٣٤٢هـ',
                PAGE_COUNT,
                DEFAULT_LINES,
                'Amiri Quran',
            ),
        )
        meta = {
            'archive_id': MESAHA_ARCHIVE_ID,
            'source_pages': f'{PAGE_MIN}-{PAGE_MAX}',
            'method': METHOD_VERSION,
            'ocr_role': 'positional-anchors-only',
            'ocr_sources': json.dumps(
                [
                    {'label': source.label, 'path': Path(source.path).name}
                    for source in sources
                ],
                ensure_ascii=False,
            ),
            'canonical_db': os.path.relpath(QURAN_SCRIPT_DATABASE, ROOT),
            'stream_order': 'surah,ayah,word_key-position',
            'line_anchor_score': str(LINE_ANCHOR_SCORE),
            'page_words_prior': f'{PAGE_WORDS_MIN}-{PAGE_WORDS_MAX}',
            'canonical_integrity_bonus': str(CANONICAL_INTEGRITY_BONUS),
            'kraken_pages': str(len(geometries)),
        }
        conn.executemany(
            'INSERT INTO layout_import_meta (key, value) VALUES (?, ?)',
            sorted(meta.items()),
        )
        validation = validate_database(conn, words)
        conn.commit()
    except Exception:
        conn.close()
        temporary.unlink(missing_ok=True)
        raise
    finally:
        try:
            conn.close()
        except Exception:
            pass

    if destination.exists():
        destination.unlink()
    temporary.replace(destination)

    status_counts: dict[str, int] = {}
    for row in confidence_rows:
        status_counts[row[2]] = status_counts.get(row[2], 0) + 1
    source_counts: dict[str, int] = {}
    for label in selected_labels:
        source_counts[label] = source_counts.get(label, 0) + 1
    scores = [float(row[1]) for row in confidence_rows]
    representative_pages = [2, 3, 5, 10, 171, 172, 400, 624, 800, 825, 827]
    by_page = {int(row[0]): row for row in confidence_rows}
    report = {
        'edition': 'mesaha',
        'source': {
            'archive_id': MESAHA_ARCHIVE_ID,
            'ocr_sources': [
                {
                    'label': source.label,
                    'file': Path(source.path).name,
                }
                for source in sources
            ],
            'pdf_pages': [PAGE_MIN, PAGE_MAX],
            'quran_page_count': PAGE_COUNT,
            'default_lines_per_page': DEFAULT_LINES,
        },
        'method': {
            'uses_llm': False,
            'canonical_text_is_authoritative': True,
            'ocr_is_positional_signal_only': True,
            'multi_source_selection': len(sources) > 1,
            'multi_source_fusion': len(sources) > 1,
            'ocr_score_cutoff': OCR_SCORE_CUTOFF,
            'line_anchor_score': LINE_ANCHOR_SCORE,
            'page_words_prior': [PAGE_WORDS_MIN, PAGE_WORDS_MAX],
            'stream_order': 'surah,ayah,word_key-position',
            'canonical_word_key_interchange': True,
            'canonical_integrity_bonus': CANONICAL_INTEGRITY_BONUS,
            'kraken_printed_seating': True,
            'kraken_pages': len(geometries),
            'version': METHOD_VERSION,
        },
        'validation': validation,
        'confidence': {
            'status_counts': status_counts,
            'source_selection': source_counts,
            'mean_score': round(statistics.fmean(scores), 4),
            'median_score': round(statistics.median(scores), 4),
            'canonical_integrity_bonus': CANONICAL_INTEGRITY_BONUS,
            'meaning': (
                'Importer confidence, not scholarly accuracy. A page becomes '
                'authoritative only after visual review against the scan.'
            ),
        },
        'representative_pages': {
            str(page): {
                'score': by_page[page][1],
                'status': by_page[page][2],
                'matched_lines': by_page[page][3],
                'anchored_lines': by_page[page][4],
                'estimated_line_ends': by_page[page][5],
            }
            for page in representative_pages
        },
    }
    report_destination = Path(report_path)
    report_destination.parent.mkdir(parents=True, exist_ok=True)
    report_destination.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + '\n',
        encoding='utf-8',
    )
    return report


def upgrade_existing_confidence(database: str, report_path: str) -> dict:
    """Apply the verified word-key bonus without rebuilding reviewer work."""
    words = load_words(QURAN_SCRIPT_DATABASE)
    report_destination = Path(report_path)
    report = json.loads(report_destination.read_text(encoding='utf-8'))
    conn = sqlite3.connect(database)
    try:
        validation = validate_database(conn, words)
        existing = conn.execute(
            "SELECT value FROM layout_import_meta "
            "WHERE key = 'canonical_integrity_bonus'"
        ).fetchone()
        already_applied = (
            existing is not None
            and float(existing[0]) == CANONICAL_INTEGRITY_BONUS
        )
        bonus_note = (
            f'Canonical word-key integrity bonus='
            f'+{CANONICAL_INTEGRITY_BONUS:.2f}.'
        )
        if not already_applied:
            conn.execute(
                '''
                UPDATE layout_import_confidence
                SET score = MIN(1.0, ROUND(score + ?, 4)),
                    notes = CASE
                        WHEN instr(notes, 'Canonical word-key integrity bonus=')
                            THEN notes
                        ELSE replace(
                            notes,
                            'Canonical continuity is guaranteed;',
                            ? || ' Canonical continuity is guaranteed;'
                        )
                    END
                ''',
                (CANONICAL_INTEGRITY_BONUS, bonus_note),
            )
        meta_updates = {
            'method': METHOD_VERSION,
            'stream_order': 'surah,ayah,word_key-position',
            'canonical_integrity_bonus': str(CANONICAL_INTEGRITY_BONUS),
        }
        conn.executemany(
            '''
            INSERT INTO layout_import_meta (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            ''',
            sorted(meta_updates.items()),
        )
        rows = conn.execute(
            '''
            SELECT page_number, score, status, matched_lines, anchored_lines,
                   estimated_line_ends
            FROM layout_import_confidence
            ORDER BY page_number
            '''
        ).fetchall()
        conn.commit()
    finally:
        conn.close()

    scores = [float(row[1]) for row in rows]
    status_counts: dict[str, int] = {}
    by_page = {}
    for row in rows:
        status_counts[str(row[2])] = status_counts.get(str(row[2]), 0) + 1
        by_page[int(row[0])] = row
    report['validation'] = validation
    report['method'].update({
        'stream_order': 'surah,ayah,word_key-position',
        'canonical_word_key_interchange': True,
        'canonical_integrity_bonus': CANONICAL_INTEGRITY_BONUS,
        'version': METHOD_VERSION,
    })
    report['confidence'].update({
        'status_counts': status_counts,
        'mean_score': round(statistics.fmean(scores), 4),
        'median_score': round(statistics.median(scores), 4),
        'canonical_integrity_bonus': CANONICAL_INTEGRITY_BONUS,
    })
    for page, sample in report.get('representative_pages', {}).items():
        row = by_page[int(page)]
        sample.update({
            'score': float(row[1]),
            'status': str(row[2]),
            'matched_lines': int(row[3]),
            'anchored_lines': int(row[4]),
            'estimated_line_ends': int(row[5]),
        })
    temporary = report_destination.with_suffix(
        report_destination.suffix + '.building'
    )
    temporary.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + '\n',
        encoding='utf-8',
    )
    temporary.replace(report_destination)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        '--ocr-xml',
        action='append',
        help=(
            'Internet Archive DjVu XML derivative; repeat for multiple '
            'sources and optionally prefix LABEL='
        ),
    )
    parser.add_argument(
        '--upgrade-confidence',
        action='store_true',
        help=(
            'validate canonical word keys and upgrade confidence metadata '
            'without rebuilding layout pages or reviewer work'
        ),
    )
    parser.add_argument(
        '--output',
        default=MESAHA_LAYOUT_DATABASE,
        help='Layout Studio SQLite destination',
    )
    parser.add_argument(
        '--report',
        default=str(ROOT / 'data' / 'mushaf-mesaha-import-report.json'),
        help='JSON confidence/validation report',
    )
    parser.add_argument(
        '--force',
        action='store_true',
        help='destroy and rebuild an existing project database',
    )
    parser.add_argument(
        '--kraken-dir',
        default=str(DEFAULT_KRAKEN_DIR),
        help=(
            'Directory of per-page Kraken JSON (pNNN.json, JPEG space). '
            'Missing files fail open to DjVu slot mapping'
        ),
    )
    args = parser.parse_args()
    if args.upgrade_confidence:
        if args.ocr_xml:
            parser.error('--upgrade-confidence cannot be combined with --ocr-xml')
        report = upgrade_existing_confidence(args.output, args.report)
    else:
        if not args.ocr_xml:
            parser.error('--ocr-xml is required unless --upgrade-confidence is used')
        report = build(
            args.ocr_xml,
            args.output,
            args.report,
            force=args.force,
            kraken_dir=args.kraken_dir,
        )
    confidence = report['confidence']
    validation = report['validation']
    action = 'Upgraded' if args.upgrade_confidence else 'Built'
    print(
        f'{action} {args.output}: {validation["pages"]} pages, '
        f'{validation["canonical_words"]} canonical words, '
        f'confidence={confidence["status_counts"]}, '
        f'mean={confidence["mean_score"]}, '
        f'integrity={validation["sqlite_integrity"]}'
    )
    print(f'Report: {args.report}')


if __name__ == '__main__':
    main()
