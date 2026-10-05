"""Re-derive a page's line breaks from the scan's own OCR text and geometry.

The Mesaha layout DB was imported from OCR and its line boundaries were never
reviewed (words are often several positions from their printed row). The
DjVu OCR (``data/mesaha-ocr``) stores each recognised word with its box. It is
noisy, but a monotone alignment of the OCR words (compared by dotless letter
shape) against the page's known text pins about a third of the words to an
exact row and x position, and those anchors are accurate (11 of 12 agreed with
hand labels). Rows are justified to one width, so between two anchors the
number of words that fit in the space left over is determined; the free words
are split across the rows in between by their estimated widths.

Public entry point: ``relayout_page_rows``. It returns ``None`` whenever it is
not sure (too few anchors, banner page, no OCR), so callers keep the layout's
own lines.
"""
from __future__ import annotations

import difflib
import re
import functools
import unicodedata
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from pipeline.cv_waqf.config import MESAHA_OCR_DIR

OCR_XML = MESAHA_OCR_DIR / 'mushafElMesaha_djvu.xml'
MIN_ANCHORS = 12          # fewer kept anchors: do not trust the result
MAX_ROW_ERROR = 0.30      # a row's words may miss its width by at most 30%
MAX_ROW_ERROR_HARD = 0.9  # beyond this the page is not trusted at all
MIN_ROW_WORDS, MAX_ROW_WORDS = 5, 14   # a justified row never holds fewer/more words
ALIGN_THRESHOLD = 0.7     # dotless-shape similarity for an OCR word to anchor
ALIGN_GAP = 0.15
MIN_RASM_LEN = 2

# Dotless letter shapes: the OCR loses and invents dots far more often than it
# misreads a skeleton.
_RASM = {}
for _grp, _rep in (
    ('بتثنيىئ', 'ب'), ('جحخ', 'ج'), ('دذ', 'د'), ('رز', 'ر'), ('سش', 'س'),
    ('صض', 'ص'), ('طظ', 'ط'), ('عغ', 'ع'), ('فق', 'ف'), ('ةه', 'ه'),
    ('وؤ', 'و'), ('كک', 'ك'),
):
    for _ch in _grp:
        _RASM[_ch] = _rep
_ALEF_LIKE = str.maketrans({'ٱ': 'ا', 'أ': 'ا', 'إ': 'ا', 'آ': 'ا'})
_URDU = str.maketrans({
    'ی': 'ي', 'ک': 'ك', 'ہ': 'ه', 'ھ': 'ه', 'ے': 'ي', 'ں': 'ن', 'ۃ': 'ه',
})


def _rasm(text: str) -> str:
    decomposed = unicodedata.normalize('NFD', text or '').translate(_URDU)
    letters = ''.join(
        ch for ch in decomposed.translate(_ALEF_LIKE)
        if 'ء' <= ch <= 'ي'
    )
    return ''.join(_RASM.get(ch, ch) for ch in letters if ch != 'ء')


@functools.lru_cache(maxsize=1)
def _ocr_objects():
    if not OCR_XML.is_file():
        return None
    return ET.parse(OCR_XML).getroot().findall('.//OBJECT')


@dataclass
class OcrWord:
    text: str
    rasm: str
    x0: float
    y0: float
    x1: float
    y1: float
    row: int = -1


def ocr_words(page: int, leaf_offset: int, image_width: float) -> list[OcrWord]:
    """OCR words of ``page`` scaled into the cached 1024-wide page image."""
    objects = _ocr_objects()
    if not objects:
        return []
    index = page + leaf_offset
    if not 0 <= index < len(objects):
        return []
    obj = objects[index]
    scale = float(obj.get('width') or 4124) / float(image_width)
    out: list[OcrWord] = []
    for word in obj.findall('.//WORD'):
        try:
            a, b, c, d = (int(v) for v in (word.get('coords') or '').split(','))
        except ValueError:
            continue
        xa, xb = sorted((a, c))
        ya, yb = sorted((b, d))
        text = word.text or ''
        out.append(OcrWord(
            text, _rasm(text), xa / scale, ya / scale, xb / scale, yb / scale,
        ))
    return out


KRAKEN_JSON = Path(__file__).parent / 'assets' / 'mesaha_kraken_lines.json'
KRAKEN_ROW_TOL = 0.45        # pitches between a Kraken line's y and a row's baseline
KRAKEN_MIN_FILL = 0.75       # a line shorter than this share of its row is a fragment
_ARABIC_LETTER = re.compile('[\u0621-\u064a\u0671]')


@functools.lru_cache(maxsize=1)
def _kraken_pages() -> dict:
    import json

    try:
        return json.loads(KRAKEN_JSON.read_text(encoding='utf-8')).get('pages') or {}
    except (OSError, ValueError):
        return {}


def kraken_row_tokens(
    page: int, image_width: float, row_baselines: list[float],
    row_extents: list[tuple[float, float]], pitch: float,
) -> dict[int, list[str]]:
    """Words of each printed row according to Kraken's printed-Arabic *line* OCR
    (``kraken_lines.json``; a line is a whole printed row, so its row follows
    from its y alone). Fragments (short lines, stop-sign strips, banners) are
    skipped; rows without a good line are absent."""
    lines = _kraken_pages().get(str(page)) or []
    scale = 4124.0 / float(image_width)
    best: dict[int, list[str]] = {}
    for line in lines:
        tokens = [
            t for t in str(line.get('text') or '').split()
            if len(_ARABIC_LETTER.findall(t)) >= 2
        ]
        if len(tokens) < 3:
            continue
        cy = float(line.get('y') or 0) / scale
        k = int(np.argmin([abs(cy - y) for y in row_baselines]))
        if abs(cy - row_baselines[k]) > KRAKEN_ROW_TOL * pitch:
            continue
        left, right = row_extents[k]
        if float(line.get('width') or 0) / scale < KRAKEN_MIN_FILL * (right - left):
            continue
        if k not in best or len(tokens) > len(best[k]):
            best[k] = tokens
    return best


def _token_alignment(tokens: list[tuple[str, int]], canon: list[str]) -> dict[int, int]:
    """Needleman-Wunsch of Kraken tokens (rasm, row) against the canonical words'
    rasm; returns ``canonical index -> row`` for the words that matched. Unlike
    ``align`` it keeps short words: both sequences are near-identical, so the
    sequence context settles which "من" is which."""
    n, m = len(tokens), len(canon)
    if not n or not m:
        return {}
    band = max(25, abs(n - m) + 20)
    NEG = -1e9
    dp = np.full((n + 1, m + 1), NEG)
    move = np.zeros((n + 1, m + 1), dtype=np.int8)
    dp[0, 0] = 0.0
    sim_cache: dict[tuple[str, str], float] = {}

    def sim(a: str, b: str) -> float:
        if not a or not b:
            return 0.0
        if a == b:
            return 1.0
        if abs(len(a) - len(b)) > 2:
            return 0.0
        key = (a, b)
        if key not in sim_cache:
            sim_cache[key] = _similarity(a, b)
        return sim_cache[key]

    for i in range(n + 1):
        for j in range(max(0, int(i * m / max(n, 1)) - band), min(m, int(i * m / max(n, 1)) + band) + 1):
            if i == 0:
                dp[0, j], move[0, j] = 0.0, 2     # words before the page start: free
                continue
            best, step = NEG, 0
            if i > 0 and dp[i - 1, j] > NEG:
                best, step = dp[i - 1, j] - 1.0, 1          # Kraken token with no canonical word
            if j > 0 and dp[i, j - 1] > NEG and dp[i, j - 1] - 1.0 > best:
                best, step = dp[i, j - 1] - 1.0, 2          # canonical word Kraken missed
            if i > 0 and j > 0 and dp[i - 1, j - 1] > NEG:
                s = sim(tokens[i - 1][0], canon[j - 1])
                v = dp[i - 1, j - 1] + (2 * s - 0.5 if s >= 0.75 else -1.0)
                if v > best:
                    best, step = v, 3
            dp[i, j], move[i, j] = best, step
    # Words after the page's end are free too: end where the last row is best.
    j = max(range(m + 1), key=lambda jj: dp[n, jj])
    i, out = n, {}
    while i > 0:
        step = move[i, j]
        if step == 3:
            if sim(tokens[i - 1][0], canon[j - 1]) >= 0.75:
                out[j - 1] = tokens[i - 1][1]
            i, j = i - 1, j - 1
        elif step == 1:
            i -= 1
        elif step == 2:
            j -= 1
        else:
            break
    return out


def _why(tag):
    LAST_DEBUG['kraken_fail'] = tag
    return None


def kraken_rows(
    *, page: int, image_width: float, texts: list[str], weights: list[float],
    row_extents: list[tuple[float, float]], row_baselines: list[float], pitch: float,
    anchors: list[tuple[int, OcrWord]] | None = None,
    forced: dict[int, int] | None = None,
) -> list[list[int]] | None:
    """Row membership straight from Kraken's lines, or ``None`` when it cannot be
    trusted.

    The words Kraken's lines matched (and the verse medallions, ``ring_rows``:
    word index -> row) pin their rows. Every other word sits between two pinned
    ones, so only the row *boundaries* are unknown: they are chosen, by dynamic
    programming over the rows, to fit each row's width (justified text fills its
    row) while keeping every pinned word in its row.
    """
    n_rows, n = len(row_extents), len(texts)
    by_row = kraken_row_tokens(page, image_width, row_baselines, row_extents, pitch)
    if len(by_row) < MIN_KRAKEN_ROWS:
        return _why('r1')
    tokens = [(_rasm(t), k) for k in sorted(by_row) for t in by_row[k]]
    matched = _token_alignment(tokens, [_rasm(t) for t in texts])
    if len(matched) < MIN_KRAKEN_MATCHES:
        return _why('r2')
    pinned = sorted(matched)
    if any(matched[a] > matched[b] for a, b in zip(pinned, pinned[1:])):
        return _why('r3')                                  # the rows must not decrease
    # Positioned anchors (DjVu words, verse medallions) keep only the ones whose
    # row agrees with what Kraken's matches allow at that point in the text.
    pos_anchor: dict[int, OcrWord] = {}
    k_first, k_last = pinned[0], pinned[-1]
    for j, w in anchors or []:
        if not k_first - MAX_EDGE_MISS <= j <= k_last + MAX_EDGE_MISS:
            continue                       # beyond Kraken's page: a stray anchor
        before = [matched[q] for q in pinned if q < j]
        after = [matched[q] for q in pinned if q > j]
        if (before and w.row < max(before)) or (after and w.row > min(after)):
            continue
        if j in matched and matched[j] != w.row:
            continue
        pos_anchor[j] = w
        matched.setdefault(j, w.row)
    pinned = sorted(matched)
    # The page may start/end a few words away from its first/last matched word
    # (Kraken skips short edge words); anything beyond is another page's.
    first_p, last_p = pinned[0], pinned[-1]
    s_lo, s_hi = max(0, first_p - MAX_EDGE_MISS), first_p
    e_lo, e_hi = last_p + 1, min(n, last_p + 1 + MAX_EDGE_MISS)
    # b[k] = index where row k+1 starts; b[n_rows-1] = the page's end.
    lo, hi = [0] * n_rows, [n] * n_rows
    for k in range(n_rows - 1):
        before = [j for j in pinned if matched[j] <= k]
        after = [j for j in pinned if matched[j] >= k + 1]
        lo[k] = (max(before) + 1) if before else 0
        hi[k] = min(after) if after else n
        if forced and k in forced:
            # A surah banner follows this row: row k+1 starts at the new surah's first word.
            if not lo[k] <= forced[k] <= hi[k]:
                return _why('rF')
            lo[k] = hi[k] = forced[k]
        if lo[k] > hi[k]:
            return _why('r4')
    lo[-1], hi[-1] = e_lo, e_hi
    cap = [r - l for l, r in row_extents]
    unit = sum(cap) / max(1.0, float(sum(weights[first_p:last_p + 1])))
    prefix = np.concatenate(([0.0], np.cumsum(weights))) * unit
    inf = float('inf')
    by_idx = sorted(pos_anchor)

    def row_cost(k: int, start: int, end: int) -> float:
        """Misfit of row ``k`` holding words ``start..end-1``: the words between
        its positioned anchors must fill the gaps between those anchors."""
        left, right = row_extents[k]
        x, at, c = right, start, 0.0
        for j in by_idx:
            if j < start:
                continue
            if j >= end:
                break
            w = pos_anchor[j]
            if w.row != k:
                c += 1.0
                continue
            seg = max(x - w.x1, 1.0)
            c += ((prefix[j] - prefix[at] - seg) / max(seg, pitch)) ** 2
            x, at = w.x0, j + 1
        seg = max(x - left, 1.0)
        return c + ((prefix[end] - prefix[at] - seg) / max(seg, pitch)) ** 2

    cost: list[dict[int, float]] = []
    back: list[dict[int, int]] = []
    for k in range(n_rows):
        cost.append({}); back.append({})
        starts = {st: 0.0 for st in range(s_lo, s_hi + 1)} if k == 0 else cost[k - 1]
        for end in range(lo[k], hi[k] + 1):
            best, arg = inf, -1
            for start, c in starts.items():
                if end <= start:
                    continue
                v = c + row_cost(k, start, end)
                if v < best:
                    best, arg = v, start
            if arg >= 0:
                cost[k][end], back[k][end] = best, arg
        if not cost[k]:
            return _why('r5')
    end = min(cost[-1], key=cost[-1].get)
    ends = [end]
    for k in range(n_rows - 1, 0, -1):
        ends.append(back[k][ends[-1]])
    first = back[0][ends[-1]]
    ends = ends[::-1]                                # b[0..n_rows-1]
    bounds = [first] + ends
    rows = [list(range(bounds[k], bounds[k + 1])) for k in range(n_rows)]
    sizes = [len(r) for r in rows]
    LAST_DEBUG.update(page=page, kraken=True, kept=len(matched), worst=0.0, sizes=sizes, matched=dict(matched), kraken_sizes=sizes)
    # The last row before a surah banner holds the end of a surah, however few words.
    short_ok = set(forced or ())
    if any(
        n < (1 if k in short_ok else MIN_ROW_WORDS) for k, n in enumerate(sizes)
    ) or max(sizes) > MAX_ROW_WORDS:
        return _why('r6')
    return rows


def _similarity(a: str, b: str) -> float:
    if a == b:
        return 1.0
    return difflib.SequenceMatcher(None, a, b, autojunk=False).ratio()


def align(ocr: list[OcrWord], canon_rasm: list[str]) -> dict[int, int]:
    """Monotone alignment; returns ``canonical index -> OCR index``."""
    n, m = len(ocr), len(canon_rasm)
    score = np.zeros((n, m))
    for i, word in enumerate(ocr):
        if len(word.rasm) < MIN_RASM_LEN:
            continue
        for j, target in enumerate(canon_rasm):
            if len(target) < MIN_RASM_LEN or abs(len(word.rasm) - len(target)) > 2:
                continue
            s = _similarity(word.rasm, target)
            if s >= ALIGN_THRESHOLD:
                score[i, j] = s
    dp = np.zeros((n + 1, m + 1))
    move = np.zeros((n + 1, m + 1), dtype=np.int8)
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            best, step = dp[i - 1, j] - ALIGN_GAP, 1
            if dp[i, j - 1] - ALIGN_GAP > best:
                best, step = dp[i, j - 1] - ALIGN_GAP, 2
            if score[i - 1, j - 1] > 0 and dp[i - 1, j - 1] + score[i - 1, j - 1] > best:
                best, step = dp[i - 1, j - 1] + score[i - 1, j - 1], 3
            dp[i, j], move[i, j] = best, step
    i, j, pairs = n, m, {}
    while i > 0 and j > 0:
        if move[i, j] == 3:
            pairs[j - 1] = i - 1
            i, j = i - 1, j - 1
        elif move[i, j] == 1:
            i -= 1
        else:
            j -= 1
    return pairs


WIDTHS_JSON = Path(__file__).parent / 'assets' / 'mesaha_letter_widths.json'


@functools.lru_cache(maxsize=1)
def _letter_widths() -> dict[str, float]:
    import json

    try:
        return json.loads(WIDTHS_JSON.read_text(encoding='utf-8'))['coef']
    except (OSError, ValueError, KeyError):
        return {}


def word_width(text: str) -> float:
    """Expected printed width of a word in line pitches (letters + marks).

    Fitted from ~4,100 OCR-anchored Mesaha words (mean error 15.5% per word,
    against 21% for \"letter count + 0.5\"). Falls back to the letter count.
    """
    coef = _letter_widths()
    letters = 0
    total = coef.get('bias', 0.0)
    for ch in unicodedata.normalize('NFD', text or ''):
        if unicodedata.combining(ch) or ch == '\u0670':
            total += coef.get('m_' + ch, 0.0)
        elif '\u0621' <= ch <= '\u064a' or ch == '\u0671':
            letters += 1
            ch = {'ٱ': 'ا', 'أ': 'ا', 'إ': 'ا', 'آ': 'ا'}.get(ch, ch)
            total += coef.get('l_' + ch, 0.0)
    if not coef:
        return 0.5 + max(1, letters)
    if letters == 0:                  # verse-number medallion
        return max(0.5, coef.get('bias', 0.5) + 0.5)
    return max(0.25, total)


MIN_KRAKEN_ROWS, MIN_KRAKEN_MATCHES = 6, 40
MAX_EDGE_MISS = 6          # words Kraken may skip at the page's first/last row
EXTENSION_WORDS = 80       # neighbouring-page words offered to the alignment each side
USE_KRAKEN = True          # fuse Kraken line OCR (see kraken_words)
LAST_DEBUG: dict = {}   # last decision, for diagnostics and tests
RING_TEMPLATE = Path(__file__).parent / 'assets' / 'mesaha_ayah_ring.png'
RING_MIN_SCORE = 0.33
RING_MIN_MARGIN = 0.04


@functools.lru_cache(maxsize=1)
def _ring_template():
    import cv2

    img = cv2.imread(str(RING_TEMPLATE), cv2.IMREAD_GRAYSCALE)
    return None if img is None else 255 - img.astype(np.float32)


def find_ayah_rings(gray, expected: int) -> list[tuple[float, float, float, float]] | None:
    """Boxes of the ``expected`` verse-end medallions on a page, or ``None``.

    The medallion is one printed glyph (digits vary), so an outline template
    finds it. The page's text says how many there are; the best ``expected``
    matches are accepted only when they beat the next one by a clear margin,
    which keeps a false ring from becoming an anchor.
    """
    import cv2

    tmpl = _ring_template()
    if tmpl is None or expected <= 0:
        return None
    target = 255 - gray.astype(np.float32)
    best = None
    for sx in (1.0, 0.8, 1.2):
        t = cv2.resize(tmpl, None, fx=sx, fy=1.0, interpolation=cv2.INTER_AREA)
        res = cv2.matchTemplate(target, t, cv2.TM_CCOEFF_NORMED)
        full = np.full(target.shape, -1.0, np.float32)
        h, w = res.shape
        oy, ox = t.shape[0] // 2, t.shape[1] // 2
        full[oy:oy + h, ox:ox + w] = res
        best = full if best is None else np.maximum(best, full)
    found = []
    work = best.copy()
    for _ in range(expected + 1):
        _s, score, _m, loc = cv2.minMaxLoc(work)
        x, y = loc
        found.append((float(x), float(y), float(score)))
        work[max(0, y - 22):y + 22, max(0, x - 22):x + 22] = -1
    chosen, nxt = found[:expected], found[expected]
    if chosen[-1][2] < RING_MIN_SCORE or chosen[-1][2] - nxt[2] < RING_MIN_MARGIN:
        return None
    half_w, half_h = tmpl.shape[1] / 2.0, tmpl.shape[0] / 2.0
    return [(x - half_w, y - half_h, x + half_w, y + half_h) for x, y, _ in chosen]


def _consistent_chain(anchors: list[tuple[int, OcrWord]]) -> list[tuple[int, OcrWord]]:
    """Longest subset in reading order: row never decreases, and inside a row
    each next anchor lies to the left (RTL)."""
    n = len(anchors)
    if n == 0:
        return []
    weight = [5 if a[1].text == '<ring>' else 1 for a in anchors]
    best = list(weight)
    prev = [-1] * n
    for j in range(n):
        wj = anchors[j][1]
        for i in range(j):
            wi = anchors[i][1]
            ok = wi.row < wj.row or (wi.row == wj.row and wi.x0 > wj.x0)
            if ok and best[i] + weight[j] > best[j]:
                best[j], prev[j] = best[i] + weight[j], i
    k = int(np.argmax(best))
    chain = []
    while k != -1:
        chain.append(anchors[k])
        k = prev[k]
    return chain[::-1]


def _split_counts(
    weights: list[float], capacities: list[float], scale: float,
) -> list[int]:
    """Split ``weights`` (reading order) into ``len(capacities)`` consecutive
    parts so each part's width (weight * scale) is close to its capacity."""
    parts = len(capacities)
    n = len(weights)
    if parts == 1:
        return [n]
    prefix = np.concatenate(([0.0], np.cumsum(weights)))
    inf = float('inf')
    # dp[p][i]: best cost placing the first i words into the first p parts.
    dp = [[inf] * (n + 1) for _ in range(parts + 1)]
    back = [[0] * (n + 1) for _ in range(parts + 1)]
    dp[0][0] = 0.0
    for p in range(1, parts + 1):
        cap = max(capacities[p - 1], 1.0)
        for i in range(n + 1):
            for k in range(i + 1):
                if dp[p - 1][k] == inf:
                    continue
                width = (prefix[i] - prefix[k]) * scale
                cost = dp[p - 1][k] + ((width - cap) / cap) ** 2
                if cost < dp[p][i]:
                    dp[p][i], back[p][i] = cost, k
    counts, i = [], n
    for p in range(parts, 0, -1):
        k = back[p][i]
        counts.append(i - k)
        i = k
    return counts[::-1]


def relayout_page_rows(
    *,
    page: int,
    leaf_offset: int,
    image_width: float,
    texts: list[str],
    weights: list[float],
    row_extents: list[tuple[float, float]],
    row_baselines: list[float],
    pitch: float,
    rings: list[tuple[float, float, float, float]] | None = None,
    ring_word_idx: list[int] | None = None,
    nominal: tuple[int, int] | None = None,
    use_kraken: bool = True,
    forced_boundaries: dict[int, int] | None = None,
) -> list[list[int]] | None:
    """Row membership for the page's words, or ``None`` when not trustworthy.

    ``texts`` may carry words of the neighbouring pages around the page's own
    (``nominal`` = inclusive index range of the page's own words); Kraken's text
    then decides where the page really starts and ends. Without Kraken only
    the nominal words are used.

    ``texts``/``weights`` are the page's words in reading order;
    ``row_extents[k]`` is ``(left, right)`` ink extent of printed row ``k``
    (the same row count as ``row_baselines``). Returns one list of word
    indexes per row.
    """
    n_rows = len(row_extents)
    words = ocr_words(page, leaf_offset, image_width)
    if not texts or n_rows < 2:
        return None
    for word in words:
        cy = (word.y0 + word.y1) / 2
        k = int(np.argmin([abs(cy - y) for y in row_baselines]))
        word.row = k if abs(cy - row_baselines[k]) <= 0.7 * pitch else -1
    if not words and not USE_KRAKEN:
        return None
    words = sorted(
        (w for w in words if w.row >= 0), key=lambda w: (w.row, -(w.x0 + w.x1) / 2),
    )
    pairs = align(words, [_rasm(t) for t in texts]) if words else {}
    found = {j: words[i] for j, i in pairs.items()}
    if rings and ring_word_idx and len(rings) == len(ring_word_idx):
        placed = []
        for box in rings:
            cy = (box[1] + box[3]) / 2
            k = int(np.argmin([abs(cy - y) for y in row_baselines]))
            if abs(cy - row_baselines[k]) <= 0.7 * pitch:
                placed.append(OcrWord('<ring>', '', box[0], box[1], box[2], box[3], k))
        if len(placed) == len(ring_word_idx):
            placed.sort(key=lambda w: (w.row, -(w.x0 + w.x1) / 2))
            for j, w in zip(ring_word_idx, placed):
                found[j] = w   # a ring beats an OCR guess for the same word
    anchors = _consistent_chain(sorted(found.items()))
    if USE_KRAKEN and use_kraken:
        rows = kraken_rows(
            page=page, image_width=image_width, texts=texts, weights=weights,
            row_extents=row_extents, row_baselines=row_baselines, pitch=pitch,
            anchors=anchors, forced=forced_boundaries,
        )
        if rows is not None and all(rows):
            LAST_DEBUG['source'] = 'kraken'
            return [sorted(r) for r in rows]
        if nominal is not None:
            a, b = nominal
            ring_n = (
                [j - a for j in ring_word_idx] if ring_word_idx else ring_word_idx
            )
            sub = relayout_page_rows(
                page=page, leaf_offset=leaf_offset, image_width=image_width,
                texts=texts[a:b + 1], weights=weights[a:b + 1],
                row_extents=row_extents, row_baselines=row_baselines, pitch=pitch,
                rings=rings, ring_word_idx=ring_n, use_kraken=False,
            )
            if sub is not None:
                LAST_DEBUG['source'] = 'djvu'
            return None if sub is None else [[j + a for j in r] for r in sub]
    if len(anchors) < MIN_ANCHORS:
        return None

    total_cap = sum(right - left for left, right in row_extents)
    scale = total_cap / max(1.0, float(sum(weights)))

    # Virtual anchors fence the page: just before word 0 at the first row's
    # right end, just after the last word at the last row's left end.
    fence_start = (-1, OcrWord('', '', row_extents[0][1], 0, row_extents[0][1], 0, 0))
    fence_end = (
        len(texts),
        OcrWord('', '', row_extents[-1][0], 0, row_extents[-1][0], 0, n_rows - 1),
    )

    def assign(kept):
        """Rows for one anchor set, and the worst relative width error of any
        part (a row whose words do not fill it) with the segment it is in."""
        rows_: list[list[int]] = [[] for _ in range(n_rows)]
        chain = [fence_start, *kept, fence_end]
        worst, worst_at = 0.0, 0
        for pos, ((ia, a), (ib, b)) in enumerate(zip(chain, chain[1:])):
            if ia >= 0:
                rows_[a.row].append(ia)
            between = list(range(ia + 1, ib))
            if not between:
                continue
            if a.row == b.row:
                rows_[a.row].extend(between)
                width = sum(weights[i] for i in between) * scale
                cap = max(1.0, a.x0 - b.x1)
                err = abs(width - cap) / max(cap, pitch)
            else:
                caps = [a.x0 - row_extents[a.row][0]]
                caps += [
                    row_extents[k][1] - row_extents[k][0]
                    for k in range(a.row + 1, b.row)
                ]
                caps.append(row_extents[b.row][1] - b.x1)
                counts = _split_counts([weights[i] for i in between], caps, scale)
                cursor, err = 0, 0.0
                for offset, (count, cap) in enumerate(zip(counts, caps)):
                    chunk = between[cursor:cursor + count]
                    rows_[a.row + offset].extend(chunk)
                    width = sum(weights[i] for i in chunk) * scale
                    err = max(err, abs(width - cap) / max(cap, pitch))
                    cursor += count
            if err > worst:
                worst, worst_at = err, pos
        return rows_, worst, worst_at

    kept = list(anchors)
    rows, worst, at = assign(kept)
    # Drop the anchor next to the least plausible stretch until every row's
    # words roughly fill it (a wrong anchor drags its neighbours' rows with it).
    for _ in range(200):
        if worst <= MAX_ROW_ERROR or len(kept) <= MIN_ANCHORS:
            break
        candidates = [i for i in (at - 1, at) if 0 <= i < len(kept)]
        best = None
        for i in candidates:
            trial = kept[:i] + kept[i + 1:]
            t_rows, t_worst, t_at = assign(trial)
            if best is None or t_worst < best[1]:
                best = (i, t_worst, t_rows, t_at)
        if best is None or best[1] >= worst:
            break
        kept.pop(best[0])
        rows, worst, at = best[2], best[1], best[3]
    LAST_DEBUG.update(page=page, kept=len(kept), worst=round(worst, 2), sizes=[len(r) for r in rows])
    if len(kept) < MIN_ANCHORS:
        return None
    sizes = [len(r) for r in rows]
    if min(sizes) < MIN_ROW_WORDS or max(sizes) > MAX_ROW_WORDS:
        return None
    if worst > MAX_ROW_ERROR_HARD:
        return None
    for k in range(n_rows):
        rows[k] = sorted(set(rows[k]))
    LAST_DEBUG['source'] = 'djvu'
    return rows
