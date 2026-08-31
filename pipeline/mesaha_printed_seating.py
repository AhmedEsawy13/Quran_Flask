"""Per-page Mesaha printed-line seating from Kraken wide-line geometry.

Archive DjVu OCR is still the page-cut signal.  When Ahmed's local Kraken
line JSON is present (``artifacts/mesaha-kraken/pages/pNNN.json``, JPEG
space ~2062×3023) this module:

* treats a page as a true empty-top / low-start only when a banner is
  visible *and* the first wide ayah line sits at y ≥ 1100 — mid-page
  banners with ink at y ~ 600 keep the previous surah at the top;
* maps each wide Kraken line to a layout slot and wraps canonical words
  from the *start* of the next line's text, so an OCR merge/split in the
  middle of a line does not steal the wrap word;
* fails open (returns None) when the Kraken JSON *file* is missing, not
  when a present file's lines were dropped by a parser that did not
  understand the production keys.

Does not read or write mushaf DBs.  Does not touch البحرين CV waqf.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

try:
    from rapidfuzz.fuzz import partial_ratio_alignment
except ImportError as exc:  # pragma: no cover - importer also requires this
    raise SystemExit(
        'rapidfuzz is required for Mesaha printed-line seating. '
        'Install requirements-dev.txt first.'
    ) from exc

LINE_Y_MERGE = 162
WIDE_LINE_MIN_WIDTH = 900
WIDE_LINE_MIN_TOKENS = 4
WIDE_LINE_MIN_CHARS = 20
EMPTY_TOP_Y_JPEG = 1100
# High-body first line sits near JPEG y=600–650; last of 12 near ~2320–2480.
JPEG_TEXT_TOP = 600
JPEG_TEXT_BOTTOM = 2400
COLLAPSE_WORDS = 20
LINE_START_SCORE = 70.0
DEFAULT_KRAKEN_DIR = Path('artifacts/mesaha-kraken/pages')


@dataclass(frozen=True)
class KrakenLine:
    y: int
    x0: int
    x1: int
    text: str
    normalized: str
    n_tokens: int

    @property
    def width(self) -> int:
        return max(0, self.x1 - self.x0)


@dataclass(frozen=True)
class PageTextGeometry:
    """Kraken-derived page geometry in JPEG pixels."""

    wide_lines: tuple[KrakenLine, ...]
    first_wide_y: int | None
    has_banner: bool
    is_empty_top: bool

    @property
    def n_wide(self) -> int:
        return len(self.wide_lines)


@dataclass(frozen=True)
class SeatedLine:
    line_number: int
    line_type: str
    start_pos: int | None
    end_pos: int | None
    surah: int | None


@dataclass(frozen=True)
class PageSeating:
    lines: tuple[SeatedLine, ...]
    anchored: int


def normalize_letters(value: str) -> str:
    """Fold Arabic letters the same way the Mesaha DjVu importer does."""
    import unicodedata

    fold = str.maketrans({
        'ٱ': 'ا',
        'أ': 'ا',
        'إ': 'ا',
        'آ': 'ا',
        'ى': 'ي',
        'ئ': 'ي',
        'ؤ': 'و',
        'ة': 'ه',
        'ک': 'ك',
        'ی': 'ي',
        'ے': 'ي',
        'ھ': 'ه',
        'گ': 'ك',
        'پ': 'ب',
        'چ': 'ج',
    })
    value = unicodedata.normalize('NFKD', value or '').translate(fold)
    return ''.join(char for char in value if '\u0621' <= char <= '\u064a')


def slot_for_y(
    y: int,
    target_lines: int,
    text_top: int,
    text_bottom: int,
) -> int:
    """Map a vertical coordinate onto 1..target_lines using a page text band."""
    span = max(1, text_bottom - text_top)
    ratio = (y - text_top) / span
    return max(1, min(target_lines, round(1 + ratio * (target_lines - 1))))


def _int_points(value) -> list[tuple[int, int]]:
    points: list[tuple[int, int]] = []
    if not isinstance(value, (list, tuple)):
        return points
    for item in value:
        if isinstance(item, (list, tuple)) and len(item) >= 2:
            try:
                points.append((int(item[0]), int(item[1])))
            except (TypeError, ValueError):
                continue
    return points


def _bbox_from_raw(raw: dict) -> tuple[int, int, int, int] | None:
    """Return (x0, y0, x1, y1). Production Mesaha JSON has y/x0/x1/width, no bbox.

    A zero-height band (y0 == y1 == y) keeps the JPEG ``y`` field as the
    line coordinate (p20 first_wide_y=612, p97=1312). ``bbox`` is optional.
    """
    if 'x0' in raw and ('x1' in raw or 'width' in raw):
        try:
            x0 = int(raw['x0'])
            if 'x1' in raw:
                x1 = int(raw['x1'])
            else:
                x1 = x0 + int(raw['width'])
            y = int(raw['y']) if 'y' in raw else 0
        except (TypeError, ValueError):
            pass
        else:
            return min(x0, x1), y, max(x0, x1), y
    bbox = raw.get('bbox') or raw.get('box')
    if isinstance(bbox, (list, tuple)) and len(bbox) >= 4:
        try:
            x0, y0, x1, y1 = (int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3]))
        except (TypeError, ValueError):
            return None
        return min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)
    if isinstance(bbox, dict):
        try:
            if 'x0' in bbox and 'y0' in bbox:
                x0, y0 = int(bbox['x0']), int(bbox['y0'])
                x1 = int(bbox.get('x1', x0 + int(bbox.get('w', bbox.get('width', 0)))))
                y1 = int(bbox.get('y1', y0 + int(bbox.get('h', bbox.get('height', 0)))))
            else:
                x0 = int(bbox['x'])
                y0 = int(bbox['y'])
                x1 = x0 + int(bbox.get('w', bbox.get('width', 0)))
                y1 = y0 + int(bbox.get('h', bbox.get('height', 0)))
        except (KeyError, TypeError, ValueError):
            return None
        return min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)
    coords = raw.get('coords')
    if isinstance(coords, str) and coords.count(',') >= 3:
        try:
            a, b, c, d = (int(part) for part in coords.split(',')[:4])
        except ValueError:
            return None
        return min(a, c), min(b, d), max(a, c), max(b, d)
    boundary = _int_points(raw.get('boundary') or raw.get('polygon'))
    if len(boundary) >= 2:
        xs = [p[0] for p in boundary]
        ys = [p[1] for p in boundary]
        return min(xs), min(ys), max(xs), max(ys)
    baseline = _int_points(raw.get('baseline'))
    if len(baseline) >= 2:
        xs = [p[0] for p in baseline]
        ys = [p[1] for p in baseline]
        y = int(round(sum(ys) / len(ys)))
        return min(xs), y - 20, max(xs), y + 20
    return None


def _tokens_from_raw(raw: dict, text: str) -> list[str]:
    for key in ('words', 'tokens', 'recognition'):
        items = raw.get(key)
        if not isinstance(items, list) or not items:
            continue
        tokens: list[str] = []
        for item in items:
            if isinstance(item, str) and item.strip():
                tokens.append(item.strip())
            elif isinstance(item, dict):
                piece = str(item.get('text') or item.get('value') or '').strip()
                if piece:
                    tokens.append(piece)
        if tokens:
            return tokens
    return [part for part in text.split() if part]


def _iter_line_dicts(payload) -> Iterable[dict]:
    if isinstance(payload, list):
        for item in payload:
            yield from _iter_line_dicts(item)
        return
    if not isinstance(payload, dict):
        return
    nested = False
    if isinstance(payload.get('lines'), list):
        nested = True
        for line in payload['lines']:
            yield from _iter_line_dicts(line)
    if isinstance(payload.get('regions'), list):
        nested = True
        for region in payload['regions']:
            yield from _iter_line_dicts(region)
    if nested:
        return
    if any(
        key in payload
        for key in (
            'bbox', 'box', 'baseline', 'boundary', 'coords', 'text', 'y', 'x0',
        )
    ):
        yield payload


def kraken_lines_from_payload(payload) -> list[KrakenLine]:
    """Parse one Kraken page JSON object into JPEG-space line records."""
    source = list(_iter_line_dicts(payload))
    lines: list[KrakenLine] = []
    for raw in source:
        bbox = _bbox_from_raw(raw)
        text = str(raw.get('text') or raw.get('line') or '').strip()
        if bbox is None:
            continue
        x0, y0, x1, y1 = bbox
        tokens = _tokens_from_raw(raw, text)
        if not text:
            text = ' '.join(tokens)
        if not text and x1 - x0 < WIDE_LINE_MIN_WIDTH:
            continue
        if 'y' in raw:
            try:
                y = int(raw['y'])
            except (TypeError, ValueError):
                y = round((y0 + y1) / 2)
        else:
            y = round((y0 + y1) / 2)
        lines.append(KrakenLine(
            y=y,
            x0=x0,
            x1=x1,
            text=text,
            normalized=normalize_letters(text),
            n_tokens=len(tokens),
        ))
    if source and not lines:
        raise ValueError(
            'Kraken payload has '
            f'{len(source)} line records but none produced geometry; '
            'expected keys text,y,x0,x1[,width] (production) or bbox'
        )
    lines.sort(key=lambda line: (line.y, line.x0))
    return lines


def load_kraken_page(path: Path | str) -> list[KrakenLine]:
    payload = json.loads(Path(path).read_text(encoding='utf-8'))
    return kraken_lines_from_payload(payload)


def _x_overlap(left: KrakenLine, right: KrakenLine) -> int:
    return max(0, min(left.x1, right.x1) - max(left.x0, right.x0))


def _looks_full_ayah(line: KrakenLine) -> bool:
    if line.width < WIDE_LINE_MIN_WIDTH:
        return False
    return (
        line.n_tokens >= WIDE_LINE_MIN_TOKENS
        or len(line.normalized) >= WIDE_LINE_MIN_CHARS
    )


def _should_merge_lines(
    current: KrakenLine,
    incoming: KrakenLine,
    merge_px: int,
) -> bool:
    """Join same-line fragments; keep consecutive printed ayah rows apart.

    LINE_Y_MERGE=162 is wider than high-body leading (~150 JPEG). Two full-width
    ayah lines at that spacing are distinct print rows, not OCR splits.
    """
    dy = abs(incoming.y - current.y)
    if dy > merge_px:
        return False
    overlap = _x_overlap(current, incoming)
    min_width = min(current.width, incoming.width) or 1
    both_full = (
        _looks_full_ayah(current)
        and _looks_full_ayah(incoming)
        and overlap >= 0.6 * min_width
    )
    if both_full and dy > 90:
        return False
    return True


def merge_kraken_lines(
    lines: Sequence[KrakenLine],
    merge_px: int = LINE_Y_MERGE,
) -> list[KrakenLine]:
    """Join fragments that belong to the same printed line."""
    if not lines:
        return []
    ordered = sorted(lines, key=lambda line: (line.y, -line.x0))
    clusters: list[list[KrakenLine]] = [[ordered[0]]]
    for line in ordered[1:]:
        prev = clusters[-1]
        prev_y = int(round(sum(item.y for item in prev) / len(prev)))
        representative = KrakenLine(
            y=prev_y,
            x0=min(item.x0 for item in prev),
            x1=max(item.x1 for item in prev),
            text=' '.join(item.text for item in prev),
            normalized=''.join(item.normalized for item in prev),
            n_tokens=sum(item.n_tokens for item in prev),
        )
        if _should_merge_lines(representative, line, merge_px):
            clusters[-1].append(line)
        else:
            clusters.append([line])
    merged: list[KrakenLine] = []
    for group in clusters:
        reading = sorted(group, key=lambda item: -item.x0)
        text = ' '.join(item.text for item in reading if item.text).strip()
        normalized = ''.join(item.normalized for item in reading)
        if not normalized:
            normalized = normalize_letters(text)
        merged.append(KrakenLine(
            y=int(round(sum(item.y for item in group) / len(group))),
            x0=min(item.x0 for item in group),
            x1=max(item.x1 for item in group),
            text=text,
            normalized=normalized,
            n_tokens=sum(item.n_tokens for item in group),
        ))
    return merged


def line_looks_like_banner(line: KrakenLine) -> bool:
    text = line.normalized
    if not text:
        return False
    if 'سوره' in text or text.startswith('جزء') or text.startswith('حزب'):
        return True
    raw = line.text or ''
    if 'سورة' in raw:
        return True
    return False


def line_looks_like_basmala(line: KrakenLine) -> bool:
    text = line.normalized
    if not text:
        return False
    if text.startswith('بسمالله') or (
        text.startswith('بسم') and 'رحم' in text
    ):
        return True
    return False


def is_wide_ayah_line(line: KrakenLine) -> bool:
    if line.width < WIDE_LINE_MIN_WIDTH:
        return False
    if line.n_tokens < WIDE_LINE_MIN_TOKENS and len(line.normalized) < WIDE_LINE_MIN_CHARS:
        return False
    if line_looks_like_banner(line) or line_looks_like_basmala(line):
        return False
    return True


def page_text_geometry(
    lines: Sequence[KrakenLine],
    *,
    merge_px: int = LINE_Y_MERGE,
) -> PageTextGeometry:
    merged = merge_kraken_lines(lines, merge_px=merge_px)
    wide = tuple(line for line in merged if is_wide_ayah_line(line))
    first_wide_y = wide[0].y if wide else None
    has_banner_text = any(line_looks_like_banner(line) for line in merged)
    has_upper_nonwide = False
    if first_wide_y is not None:
        has_upper_nonwide = any(
            (not is_wide_ayah_line(line)) and line.y < first_wide_y
            for line in merged
        )
    has_banner = has_banner_text or has_upper_nonwide
    is_empty_top = (
        first_wide_y is not None
        and first_wide_y >= EMPTY_TOP_Y_JPEG
        and has_banner
    )
    return PageTextGeometry(
        wide_lines=wide,
        first_wide_y=first_wide_y,
        has_banner=has_banner,
        is_empty_top=is_empty_top,
    )


def load_kraken_geometries(
    kraken_dir: Path | str | None,
    *,
    page_min: int,
    page_max: int,
) -> dict[int, PageTextGeometry]:
    """Load per-page geometry. Missing files are skipped (fail open).

    A present file that cannot yield line geometry raises — that is the
    826-file / zero-line bug, not a missing-page fail-open.
    """
    if kraken_dir is None:
        return {}
    directory = Path(kraken_dir)
    if not directory.is_dir():
        return {}
    geometries: dict[int, PageTextGeometry] = {}
    for page in range(int(page_min), int(page_max) + 1):
        path = directory / f'p{page:03d}.json'
        if not path.is_file():
            continue
        lines = load_kraken_page(path)
        geometries[page] = page_text_geometry(lines)
    return geometries


def header_count_for_surah(surah: int) -> int:
    return 2 if int(surah) == 9 else 3


def clip_empty_top_page_starts(
    starts: list[int],
    words,
    geometries: dict[int, PageTextGeometry],
    starts_by_surah: dict[int, int],
    *,
    page_min: int,
) -> None:
    """Keep previous-surah leftover off true empty-top banner pages.

    Mutates ``starts`` in place. Mid-page banners (first_wide_y still ~600)
    are left alone so the printed previous surah stays on the page.
    """
    for offset in range(len(starts) - 1):
        page = int(page_min) + offset
        geometry = geometries.get(page)
        if geometry is None or not geometry.is_empty_top:
            continue
        lo = starts[offset]
        hi = starts[offset + 1] - 1
        if lo > hi or offset == 0:
            continue
        surah_here = [
            position
            for position in starts_by_surah.values()
            if lo <= position <= hi
        ]
        if not surah_here:
            continue
        clip_at = min(surah_here)
        if clip_at > lo:
            starts[offset] = clip_at
    for index in range(1, len(starts)):
        starts[index] = max(starts[index], starts[index - 1] + 1)


def _stream_chars(words, lo: int, hi: int) -> tuple[str, list[int]]:
    chars: list[str] = []
    pos_at: list[int] = []
    for position in range(lo, hi + 1):
        token = getattr(words[position], 'normalized', '') or ''
        if not token:
            continue
        chars.append(token)
        pos_at.extend([position] * len(token))
    return ''.join(chars), pos_at


def match_line_start(
    needle: str,
    words,
    lo: int,
    hi: int,
    *,
    score_cutoff: float = LINE_START_SCORE,
) -> int | None:
    """Canonical position where a Kraken line's letters begin."""
    if lo > hi or not needle:
        return None
    haystack, pos_at = _stream_chars(words, lo, hi)
    if not haystack or not pos_at:
        return None
    prefix = needle[:36] if len(needle) >= 12 else needle
    if not prefix:
        return None
    exact_at = haystack.find(prefix[: max(12, min(24, len(prefix)))])
    if exact_at >= 0:
        return pos_at[min(exact_at, len(pos_at) - 1)]
    result = partial_ratio_alignment(
        prefix, haystack, score_cutoff=score_cutoff,
    )
    if not result:
        return None
    start_char = min(max(int(result.dest_start), 0), len(pos_at) - 1)
    return pos_at[start_char]


def _interpolate_starts(
    starts: list[int | None],
    page_start: int,
    page_end: int,
) -> list[int] | None:
    n = len(starts)
    filled: list[int | None] = list(starts)
    filled[0] = page_start
    sentinel = page_end + 1
    points = [
        (index, value)
        for index, value in enumerate(filled)
        if value is not None
    ]
    points.append((n, sentinel))
    for (left_i, left_s), (right_i, right_s) in zip(points, points[1:]):
        gap = right_i - left_i
        count = gap
        if count < 1:
            return None
        if right_s - left_s < count:
            return None
        for step in range(1, gap):
            filled[left_i + step] = left_s + math.ceil(
                (right_s - left_s) * step / count
            )
    result: list[int] = []
    previous = page_start - 1
    remaining_after = n
    for index, value in enumerate(filled):
        remaining_after = n - index
        latest = page_end - remaining_after + 1
        earliest = previous + 1
        if value is None:
            return None
        current = max(earliest, min(int(value), latest))
        result.append(current)
        previous = current
    return result


def kraken_wrap_boundaries(
    words,
    page_start: int,
    page_end: int,
    wide_lines: Sequence[KrakenLine],
    *,
    score_cutoff: float = LINE_START_SCORE,
) -> list[int] | None:
    """Inclusive canonical end position for each wide line.

    Wrap locks come from the *start* of line N+1, not from OCR token
    counts on line N.  A merge or split in the middle of a line therefore
    cannot pull the next printed line's first word backward.
    """
    n = len(wide_lines)
    if n < 1 or page_start > page_end:
        return None
    if n > page_end - page_start + 1:
        return None
    typical = max(4, (page_end - page_start + 1) // n)
    starts: list[int | None] = [page_start]
    previous = page_start
    matched_after_first = 0
    for index in range(1, n):
        remaining = n - index
        latest = page_end - remaining + 1
        earliest = previous + 1
        if earliest > latest:
            starts.append(None)
            continue
        needle = wide_lines[index].normalized
        window_hi = min(latest, earliest + typical * 3)
        position = match_line_start(
            needle, words, earliest, window_hi, score_cutoff=score_cutoff,
        )
        if position is None:
            position = match_line_start(
                needle, words, earliest, latest, score_cutoff=score_cutoff,
            )
        starts.append(position)
        if position is not None:
            previous = position
            matched_after_first += 1
    filled = _interpolate_starts(starts, page_start, page_end)
    if filled is None:
        return None
    # Require a real wrap lock on at least half of the interior lines so a
    # page of failed OCR does not silently even-split (fail open instead).
    if n >= 3 and matched_after_first < (n - 1) / 2:
        return None
    ends = [filled[index + 1] - 1 for index in range(n - 1)]
    ends.append(page_end)
    for first, last in zip(filled, ends):
        if last < first:
            return None
    return ends


def _coverage_ok(lines: Sequence[SeatedLine], page_start: int, page_end: int) -> bool:
    cursor = page_start
    for line in lines:
        if line.line_type != 'ayah' or line.start_pos is None or line.end_pos is None:
            continue
        if line.start_pos != cursor or line.end_pos < line.start_pos:
            return False
        cursor = line.end_pos + 1
    return cursor == page_end + 1


def _empty_line(line_number: int, surah: int | None) -> SeatedLine:
    return SeatedLine(
        line_number=line_number,
        line_type='ayah',
        start_pos=None,
        end_pos=None,
        surah=surah,
    )


def _split_collapsed_ayahs(
    placed: list[SeatedLine | None],
    target_lines: int,
) -> list[SeatedLine | None]:
    """Split a 20+ word ayah into a following empty slot (leftover packing)."""
    changed = True
    while changed:
        changed = False
        for index, line in enumerate(placed):
            if (
                line is None
                or line.line_type != 'ayah'
                or line.start_pos is None
                or line.end_pos is None
            ):
                continue
            n_words = line.end_pos - line.start_pos + 1
            if n_words < COLLAPSE_WORDS:
                continue
            empty_at = next(
                (
                    later
                    for later in range(index + 1, target_lines)
                    if placed[later] is None
                    or (
                        placed[later].line_type == 'ayah'
                        and placed[later].start_pos is None
                    )
                ),
                None,
            )
            if empty_at is None:
                continue
            # Shift empty/None down so the split neighbour sits in empty_at.
            for slide in range(empty_at, index + 1, -1):
                placed[slide] = placed[slide - 1]
            mid = line.start_pos + n_words // 2 - 1
            mid = max(line.start_pos, min(mid, line.end_pos - 1))
            placed[index] = SeatedLine(
                line_number=index + 1,
                line_type='ayah',
                start_pos=line.start_pos,
                end_pos=mid,
                surah=line.surah,
            )
            placed[index + 1] = SeatedLine(
                line_number=index + 2,
                line_type='ayah',
                start_pos=mid + 1,
                end_pos=line.end_pos,
                surah=line.surah,
            )
            changed = True
            break
    return placed


def seat_printed_page(
    *,
    words,
    page_start: int,
    page_end: int,
    starts_by_surah: dict[int, int],
    geometry: PageTextGeometry,
    target_lines: int = 12,
) -> PageSeating | None:
    """Seat one page from Kraken wide lines. None = fail open to DjVu path."""
    if page_start > page_end or not geometry.wide_lines:
        return None
    ends = kraken_wrap_boundaries(
        words, page_start, page_end, geometry.wide_lines,
    )
    if ends is None:
        return None

    ayah_specs: list[tuple[int, int, int]] = []
    cursor = page_start
    for last in ends:
        ayah_specs.append((cursor, last, int(getattr(words[cursor], 'surah'))))
        cursor = last + 1
    if cursor != page_end + 1:
        return None

    stream: list[SeatedLine] = []
    for start_pos, end_pos, surah in ayah_specs:
        if start_pos == starts_by_surah.get(surah):
            count = header_count_for_surah(surah)
            kinds = ['surah_name', 'surah_info']
            if count == 3:
                kinds.append('basmallah')
            for kind in kinds:
                stream.append(SeatedLine(
                    line_number=0,
                    line_type=kind,
                    start_pos=None,
                    end_pos=None,
                    surah=surah,
                ))
        stream.append(SeatedLine(
            line_number=0,
            line_type='ayah',
            start_pos=start_pos,
            end_pos=end_pos,
            surah=surah,
        ))

    if len(stream) > target_lines:
        return None

    placed: list[SeatedLine | None] = [None] * target_lines
    first_ayah = next(
        (index for index, row in enumerate(stream) if row.line_type == 'ayah'),
        0,
    )
    if geometry.is_empty_top:
        header_prefix = stream[:first_ayah]
        body = stream[first_ayah:]
        first_y = geometry.first_wide_y
        first_slot = 1
        if first_y is not None:
            first_slot = slot_for_y(
                first_y, target_lines, JPEG_TEXT_TOP, JPEG_TEXT_BOTTOM,
            )
        first_slot = max(first_slot, len(header_prefix) + 1)
        first_slot = min(first_slot, target_lines - len(body) + 1)
        for index, header in enumerate(header_prefix):
            placed[index] = header
        for offset, row in enumerate(body):
            slot = first_slot - 1 + offset
            if slot >= target_lines:
                return None
            placed[slot] = row
    else:
        if len(stream) > target_lines:
            return None
        for index, row in enumerate(stream):
            placed[index] = row

    default_surah = int(getattr(words[page_start], 'surah'))
    placed = _split_collapsed_ayahs(placed, target_lines)
    lines: list[SeatedLine] = []
    for index in range(target_lines):
        row = placed[index]
        if row is None:
            row = _empty_line(index + 1, default_surah)
        lines.append(SeatedLine(
            line_number=index + 1,
            line_type=row.line_type,
            start_pos=row.start_pos,
            end_pos=row.end_pos,
            surah=row.surah if row.surah is not None else default_surah,
        ))
    if not _coverage_ok(lines, page_start, page_end):
        return None
    return PageSeating(lines=tuple(lines), anchored=len(geometry.wide_lines))


def geometry_from_wide_specs(
    specs: Sequence[tuple[int, str, int, int]],
    *,
    banner_text: str | None = None,
    banner_y: int = 400,
    basmala_text: str | None = None,
    basmala_y: int = 1180,
) -> PageTextGeometry:
    """Test helper: (y, text, x0, x1) wide lines plus optional banner/basmala."""
    lines: list[KrakenLine] = []
    if banner_text:
        lines.append(KrakenLine(
            y=banner_y,
            x0=400,
            x1=1600,
            text=banner_text,
            normalized=normalize_letters(banner_text),
            n_tokens=max(1, len(banner_text.split())),
        ))
    if basmala_text:
        lines.append(KrakenLine(
            y=basmala_y,
            x0=200,
            x1=1800,
            text=basmala_text,
            normalized=normalize_letters(basmala_text),
            n_tokens=max(1, len(basmala_text.split())),
        ))
    for y, text, x0, x1 in specs:
        tokens = [part for part in text.split() if part]
        lines.append(KrakenLine(
            y=y,
            x0=x0,
            x1=x1,
            text=text,
            normalized=normalize_letters(text),
            n_tokens=len(tokens),
        ))
    return page_text_geometry(lines)
