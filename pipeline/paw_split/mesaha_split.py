"""Split a Mesaha page (2062 px scan, data/cv/pages/mesaha/pNNN_w1600.jpg) into lines and words.

Same letter-group (PAW) alignment as the Qatar trace (../qatar-trace/split_paw.py): lines from a
12-line comb fitted to the ink inside the frame, words from the reviewed Mesaha layout rows
(line_text), verse medallions from the ring template, Kraken's stored spaces as a soft prior.

    /opt/homebrew/bin/python3 split_mesaha.py 15
"""
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))
from pipeline.paw_split._common import ROOT, QATAR_APP_ASSETS, workdir  # noqa: E402
workdir('mesaha-trace')

import json
import os
import sqlite3
import sys

import cv2
import numpy as np

from pipeline.cv_waqf.relayout import find_ayah_rings, kraken_chars  # noqa: E402
from pipeline.cv_waqf.layout_geo import _ids_between  # noqa: E402
from pipeline.cv_waqf.config import EDITIONS  # noqa: E402
_SCRIPT_DB = EDITIONS['المساحة'].script_db

PAGE = int(sys.argv[1]) if len(sys.argv) > 1 else 15
LAYOUT_DB = f'{ROOT}/data/mushaf-mesaha-layout.db'
img = cv2.imread(f'{ROOT}/data/cv/pages/mesaha/p{PAGE:03d}_w1600.jpg')
H, W = img.shape[:2]
gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
_t, _ = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
ink = gray < _t

# --- the frame's inner edge: scan out from the page centre to the first tall/wide frame rule ----
n0, lab0, st0, _ = cv2.connectedComponentsWithStats(ink.astype(np.uint8), 8)
rule = np.zeros(n0, bool)
rule[1:] = (st0[1:, cv2.CC_STAT_HEIGHT] > 0.5 * H) | (st0[1:, cv2.CC_STAT_WIDTH] > 0.5 * W)
is_rule = rule[lab0]
cy0, cx0 = H // 2, W // 2
def first(arr):
    idx = np.nonzero(arr)[0]
    return int(idx[0]) if len(idx) else None
_band = slice(cy0 - 200, cy0 + 200)
left = max(first(is_rule[_band, cx0::-1].any(0)) or cx0, 0)
right = first(is_rule[_band, cx0:].any(0)) or (W - cx0)
top = first(is_rule[cy0::-1, cx0 - 200:cx0 + 200].any(1)) or cy0
bottom = first(is_rule[cy0:, cx0 - 200:cx0 + 200].any(1)) or (H - cy0)
M = 8
bx0, bx1, by0, by1 = cx0 - left + M, cx0 + right - M, cy0 - top + M, cy0 + bottom - M
inside = np.zeros_like(ink); inside[by0:by1, bx0:bx1] = True
ink &= inside

# --- layout rows ----------------------------------------------------------------------------------
rows = sqlite3.connect(LAYOUT_DB).execute(
    'SELECT line_number, line_type, first_word_id, last_word_id, line_text FROM pages WHERE page_number=? ORDER BY line_number',
    (PAGE,)).fetchall()
DIGITS = set('٠١٢٣٤٥٦٧٨٩')
def is_number(t):
    return bool(t) and all(ch in DIGITS for ch in t)
if any(r[1] != 'ayah' for r in rows):
    sys.exit(f'page {PAGE}: header rows {[r[1] for r in rows if r[1] != "ayah"]} - only plain text pages for now')
line_tokens = []
for _ln, _type, a, b, text in rows:
    toks = text.split()                       # word ids count verse numbers and ۞ as tokens too
    # walk the script DB's reading order, not range(a, b + 1): its ids jump inside 2:285, 3:7, 38:79,
    # 39:5, 59:19 and 60:1 (the Shamarly fonts are keyed on that order, so the ids stay as they are)
    ids = _ids_between(_SCRIPT_DB, a, b)
    assert len(toks) == len(ids), (PAGE, _ln, len(toks), a, b)
    line_tokens.append(list(zip(ids, toks)))
NL = len(line_tokens)

# --- lines: a comb of NL evenly spaced rows fitted to the ink profile ------------------------------
_prof = np.convolve(ink[:, bx0:bx1].sum(1).astype(float), np.ones(25) / 25, mode='same')
_span = by1 - by0
_best = max(((sum(_prof[int(y0 + i * pt)] for i in range(NL)), y0, pt)
             for pt in np.arange(0.075 * _span, 0.095 * _span, 0.5)
             for y0 in range(by0, int(by1 - (NL - 1) * pt), 2)))
_, _y0, _pt = _best
centres = [max(range(int(_y0 + i * _pt) - 12, int(_y0 + i * _pt) + 13), key=lambda y: _prof[y]) for i in range(NL)]
PITCH = float(_pt)
bands = [(c - 0.36 * PITCH, c + 0.30 * PITCH) for c in centres]

# --- ink pieces, verse rings ------------------------------------------------------------------------
n, lab, st, cen = cv2.connectedComponentsWithStats(ink.astype(np.uint8), 8)
pieces = []
for i in range(1, n):
    x, y, w, h, a = (int(v) for v in st[i])
    if a < 4 or (h > 0.6 * PITCH and w < 0.08 * PITCH) or (w > 0.6 * PITCH and h < 0.08 * PITCH):   # specks; frame-rule bits
        continue
    pieces.append({'id': i, 'x0': x, 'x1': x + w, 'y0': y, 'y1': y + h, 'cx': cen[i][0], 'cy': cen[i][1], 'area': a})
n_rings = sum(is_number(t) for toks in line_tokens for _, t in toks)
_s = 1024 / W
_small = cv2.resize(np.where(ink, 0, 255).astype(np.uint8), None, fx=_s, fy=_s, interpolation=cv2.INTER_AREA)
# Verse medallions, line by line: the layout text says how many each line holds, so take that many
# best template matches inside the line's band (one page-wide cut-off fails on pages with many short
# verses, where real rings and the best non-ring spots score alike).
from pipeline.cv_waqf.relayout import _ring_template
_tmpl = _ring_template()
_target = 255 - _small.astype(np.float32)
_score = None
for _sx in (1.0, 0.85, 1.15):
    _t = cv2.resize(_tmpl, None, fx=_sx, fy=1.0, interpolation=cv2.INTER_AREA)
    _res = cv2.matchTemplate(_target, _t, cv2.TM_CCOEFF_NORMED)
    _full = np.full(_target.shape, -1.0, np.float32)
    _oy, _ox = _t.shape[0] // 2, _t.shape[1] // 2
    _full[_oy:_oy + _res.shape[0], _ox:_ox + _res.shape[1]] = _res
    _score = _full if _score is None else np.maximum(_score, _full)
_hw, _hh = _tmpl.shape[1] / 2.0, _tmpl.shape[0] / 2.0
# First choice: the medallion's own shape - one closed outline around a large empty inside (inner hole
# ~0.45 of its box; letters <= 0.04). The template only fills in where a scan broke the outline.
_n0, _lab0, _st0, _ = cv2.connectedComponentsWithStats(ink.astype(np.uint8), 8)
_shape_rings = []
for _i in range(1, _n0):
    _x, _y, _w, _h, _a = (int(v) for v in _st0[_i])
    if not (0.35 * PITCH < _w < 0.9 * PITCH and 0.3 * PITCH < _h < 0.8 * PITCH):
        continue
    _m = (_lab0[_y:_y + _h, _x:_x + _w] == _i).astype(np.uint8)
    _cn, _hi = cv2.findContours(_m, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    _hole = max((cv2.contourArea(c) for c, hh in zip(_cn, _hi[0]) if hh[3] >= 0), default=0)
    # A medallion is 0.49-0.52 pitch wide, 0.44-0.47 tall (aspect 1.08-1.16): with a closed outline it
    # has a big hole; a scan can break the outline (p459 ١٨), but its middle stays empty (digits are
    # separate pieces), while letters of that size carry ink through the middle or are much flatter.
    _ring_size = 0.48 * PITCH < _w < 0.55 * PITCH and 0.43 * PITCH < _h < 0.50 * PITCH and 1.0 < _w / _h < 1.25
    _centre = _m[int(0.25 * _h):int(0.75 * _h), int(0.25 * _w):int(0.75 * _w)].sum() / max(1, int(_m.sum()))
    if _hole / (_w * _h) > 0.25 or (_ring_size and _centre < 0.08):
        _shape_rings.append((_x, _x + _w, _y + _h / 2.0))
rings = []
RING_SHORT = []
for _li, _toks in enumerate(line_tokens):
    _k = sum(is_number(t) for _, t in _toks)
    if not _k:
        continue
    _cy = centres[_li] * _s
    _y0, _y1 = int(_cy - 0.35 * PITCH * _s), int(_cy + 0.35 * PITCH * _s)
    _band = _score.copy(); _band[:_y0] = -1; _band[_y1:] = -1
    _band[:, :int(bx0 * _s)] = -1; _band[:, int(bx1 * _s):] = -1
    _found = []
    for _x0r, _x1r, _cyr in sorted((r for r in _shape_rings if _y0 / _s <= r[2] <= _y1 / _s), key=lambda r: -r[1])[:_k]:
        _cx = (_x0r + _x1r) / 2 * _s
        _found.append((_cx, _cyr * _s, 1.0))
        _band[max(0, int(_cyr * _s) - 22):int(_cyr * _s) + 22, max(0, int(_cx - 1.6 * _hw)):int(_cx + 1.6 * _hw)] = -1
    for _ in range(_k - len(_found)):
        _, _v, _, (_x, _y) = cv2.minMaxLoc(_band)
        if _v < 0.25:
            break
        _found.append((_x, _y, _v))
        _band[max(0, _y - 22):_y + 22, max(0, int(_x - 1.6 * _hw)):int(_x + 1.6 * _hw)] = -1
    if len(_found) < _k:
        print(f'page {PAGE} line {_li + 1}: {_k} verse numbers but {len(_found)} rings found')
        RING_SHORT.append(_li + 1)
    for _x, _y, _v in _found:
        rings.append(dict(x0=(_x - _hw) / _s, x1=(_x + _hw) / _s, cy=_y / _s))

line_h = np.median([b - a for a, b in bands])
KR_SHIFT = float(os.environ.get('KR_SHIFT', '-0.112'))
KR_PEN = float(os.environ.get('KR_PEN', '0'))   # Kraken spaces: review flags only; as a DP cost they moved a correct alif (p15)
centres = [(a + b) / 2 for a, b in bands]
# Baseline of each line = its densest ink row. A letter body reaches the baseline; dots and
# harakat sit clear above or below it (short letters such as ز ر و ن are as small as a mark).
baselines = []
for a, b in bands:
    rows = ink[int(a):int(b), int(bx0):int(bx1)].sum(1)
    baselines.append(int(a) + int(np.argmax(rows)))
for p in pieces:
    p['line'] = int(np.argmin([abs(p['cy'] - c) for c in centres]))
    base = baselines[p['line']]
    touches = p['y0'] - 0.04 * line_h <= base <= p['y1'] + 0.12 * line_h   # an alif can end at the top of the thick baseline stroke
    small = (p['y1'] - p['y0']) < 0.42 * line_h and p['area'] < 0.06 * line_h * line_h
    flat = (p['y1'] - p['y0']) < 0.1 * line_h and (p['x1'] - p['x0']) < 0.4 * line_h   # small waw ۥ stroke, dots on the baseline
    p['mark'] = small and (not touches or flat)
# The hamza of إ hangs just under its alif, down at the baseline, so it looks like a short letter:
# a small piece right below a tall thin alif (and mostly within its columns) is that alif's mark.
alifs = [q for q in pieces if not q['mark'] and (q['y1'] - q['y0']) > 0.4 * line_h and (q['x1'] - q['x0']) < 0.2 * line_h]
for p in pieces:
    if p['mark'] or p['area'] >= 0.03 * line_h * line_h:
        continue
    for q in alifs:
        ov = min(q['x1'], p['x1']) - max(q['x0'], p['x0'])
        if q['line'] == p['line'] and 0 <= p['y0'] - q['y1'] < 0.12 * line_h and ov >= 0.5 * (q['x1'] - q['x0']):
            p['mark'] = True
            break
for r in rings:
    r['line'] = int(np.argmin([abs(r['cy'] - c) for c in centres]))

WAQF_MIN_AREA = 0.025 * line_h * line_h   # waqf signs ~1,030-1,190 px on p33; other gap marks <= 515
LETTERS = set('ءآأؤإئابةتثجحخدذرزسشصضطظعغفقكلمنهوىيٱ')
SMALL_SIGNS = set('ۥۦٰۧ')   # small letters printed as their own piece (not tanween: that is a mark)


def weight(token):
    return max(1.0, sum(ch in LETTERS for ch in token))



# --- text letter-groups (PAWs) ------------------------------------------------------------------
ALIFS = set('اأإآٱ')
NON_JOIN = set('اأإآٱدذرزوؤةى')


def paws(token):
    """The word's connected letter groups, in reading order. A hamza on the line (ء) joins neither
    side, so it is a small group of its own: the text then decides which word it belongs to."""
    if token == '۞':
        return ['۞']                         # the hizb star printed inline
    letters = [ch for ch in token if ch in LETTERS]
    groups, cur = [], []
    for k, ch in enumerate(letters):
        if ch == 'ء':
            if cur:
                groups.append(''.join(cur)); cur = []
            groups.append('ء')
            continue
        cur.append(ch)
        # ى inside a word (فَتَىٰهَا, هُدَىٰهُمۡ) is written as a joining tooth: it only ends a group at the end
        if ch in NON_JOIN and not (ch == 'ى' and k < len(letters) - 1):
            groups.append(''.join(cur)); cur = []
    if cur:
        groups.append(''.join(cur))
    return groups or ['']


def units(group):
    """Expected width in letter units; a lone alif is thin."""
    if group in ALIFS:
        return 0.35
    if group == 'ء':
        return 0.3
    if group == '۞':
        return 0.7
    return max(0.6, len(group) * 1.0 - 0.3 * sum(ch in ALIFS for ch in group))


def is_hamza(p):
    """A hamza on the line: small, roughly square, sitting at the baseline (not above or below)."""
    w, h = p['x1'] - p['x0'], p['y1'] - p['y0']
    base = baselines[p['line']]
    return 0.12 * line_h < h < 0.4 * line_h and 0.5 < w / max(h, 1) < 1.6 and p['y1'] >= base - 0.15 * line_h and p['y0'] <= base


def is_star(p):
    """The inline hizb star: one roughly square piece about a third of the line high."""
    w, h = p['x1'] - p['x0'], p['y1'] - p['y0']
    return (0.2 * line_h < h < 0.5 * line_h and 0.7 < w / max(h, 1) < 1.4
            and p['y1'] > baselines[p['line']] - 0.15 * line_h)     # down among the letters, not a high hamza

def alif_like(p):
    """A tall piece that is a thin stem through its upper AND lower middle: an alif, even with a
    hamza or wasla merged on top or a hamza underneath (they widen the box, not the stem). A final
    م's tail is thin only below its head; the alif also stands up from the baseline."""
    h = p['y1'] - p['y0']
    if h <= 0.33 * line_h:                      # a final alif after و can be short (0.39 line)
        return False
    if 'stem' not in p:
        m = lab[p['y0']:p['y1'], p['x0']:p['x1']] == p['id']
        widths = m.sum(1)
        up, low = widths[int(0.3 * h):int(0.5 * h) + 1], widths[int(0.5 * h):int(0.75 * h) + 1]
        p['stem'] = float(max(np.median(up), np.median(low))) if len(up) and len(low) else 1e9
        band = m[int(0.4 * h):int(0.75 * h) + 1].astype(np.int8)
        runs = (np.diff(band, axis=1) == 1).sum(1) + band[:, 0]          # ink runs per row
        if len(runs) and np.mean(runs == 1) < 0.8:
            p['stem'] = 1e9         # two strokes per row (the sides of a ن bowl): not a stem
    return p['stem'] < 0.085 * line_h and p['y0'] < baselines[p['line']] - 0.22 * line_h


KRAKEN = {}
for _row in (kraken_chars(PAGE, W) if os.environ.get('NO_KRAKEN') != '1' else []):
    _li = int(np.argmin([abs(_row['y'] - b) for b in baselines]))
    if abs(_row['y'] - baselines[_li]) < 0.4 * PITCH:
        KRAKEN.setdefault(_li, []).extend(x + KR_SHIFT * PITCH for ch, x in zip(_row['text'], _row['x']) if ch == ' ')
KR_TOL = 0.25 * (np.median(np.diff([(a + b) / 2 for a, b in bands])) if len(bands) > 1 else line_h)


def align_stretch(li, toks, span):
    """Match the stretch's letter bodies (right to left) to its words' letter groups and give each
    body to the word of the group it matches. DP over (bodies used, groups used)."""
    seq = []                                                   # (word position, group text)
    for wpos, (_, t) in enumerate(toks):
        for g in paws(t):
            seq.append((wpos, g))
    bodies = sorted(span, key=lambda p: -p['x1'])
    spaces = KRAKEN.get(li, [])
    m, n = len(bodies), len(seq)
    total_units = sum(units(g) for _, g in seq) or 1.0
    ink_width = sum(p['x1'] - p['x0'] for p in bodies) or 1.0
    scale = ink_width / total_units                           # px per letter unit
    INF = float('inf')

    def width_cost(ps, gs):
        if len(gs) == 1 and gs[0] in ALIFS and len(ps) == 1 and alif_like(ps[0]):
            return 0.0              # a lone alif is a thin stem whatever the letter width
        actual = max(1.0, sum(p['x1'] - p['x0'] for p in ps))
        expect = max(1.0, scale * sum(units(g) for g in gs))
        return np.log(actual / expect) ** 2

    def shape_cost(ps, gs):
        if gs == ['۞'] or '۞' in gs:
            return 0.0 if gs == ['۞'] and len(ps) == 1 and is_star(ps[0]) else 3.0
        hamza = len(gs) == 1 and gs[0] == 'ء'
        if hamza:
            return 0.0 if len(ps) == 1 and is_hamza(ps[0]) else 2.5
        lone = len(gs) == 1 and gs[0] in ALIFS
        tall = len(ps) == 1 and alif_like(ps[0])
        if lone and not tall:
            return 2.0
        if tall and not lone and not any(ch in ALIFS or ch in 'لك' for g in gs for ch in g):
            return 1.5
        return 0.0

    moves = [(1, 1, 0.0), (2, 1, 0.6), (3, 1, 1.4), (1, 2, 0.9), (1, 0, 1.2)]   # (bodies, groups, penalty)
    best = np.full((m + 1, n + 1), INF); back = {}
    best[0, 0] = 0.0
    for i in range(m + 1):
        for k in range(n + 1):
            if best[i, k] == INF:
                continue
            for db, dg, pen in moves:
                ni, nk = i + db, k + dg
                if ni > m or nk > n:
                    continue
                ps, gs = bodies[i:ni], [g for _, g in seq[k:nk]]
                if not dg and ps[0]['area'] < 0.03 * line_h * line_h and ps[0]['y1'] - ps[0]['y0'] < 0.3 * line_h:
                    pen = 0.3       # a small body the text has no group for (dagger alif, tanween on the line)
                c = pen + (width_cost(ps, gs) + shape_cost(ps, gs) if dg else 0.0)
                if dg and spaces and 0 < i and 0 < k:
                    gap = (bodies[i - 1]['x0'] + bodies[i]['x1']) / 2
                    near = min((abs(x - gap) for x in spaces), default=1e9) <= KR_TOL
                    new_word = seq[k][0] != seq[k - 1][0]
                    if new_word and not near:
                        c += KR_PEN     # a word split where Kraken read no space
                    elif not new_word and near:
                        c += KR_PEN     # Kraken read a space inside one word
                if best[i, k] + c < best[ni, nk]:
                    best[ni, nk] = best[i, k] + c; back[(ni, nk)] = (i, k, db, dg)
    words = [{'line': li + 1, 'word_index': wi, 'text': t, 'pieces': [], 'ring': False} for wi, t in toks]
    if best[m, n] == INF:
        forced_lines.add(li + 1)
        print(f'  line {li + 1}: no alignment for {len(toks)} words, {n} groups, {m} bodies', [t for _, t in toks])
    else:
        i, k = m, n
        while (i, k) != (0, 0):
            pi, pk, db, dg = back[(i, k)]
            if dg:
                # bodies of a group (or of two touching groups) go to the first group's word
                for p in bodies[pi:i]:
                    words[seq[pk][0]]['pieces'].append(p['id'])
            elif (bodies[pi]['area'] >= 0.03 * line_h * line_h
                  and bodies[pi]['y0'] < baselines[li] - 0.1 * line_h):   # a letter rises above the line;
                                                                       # a hamza/kasra under an alif does not
                # a real letter body no word of the text accounts for: the layout's line break or a
                # word's text may be wrong (p346: the print's line ends one word later than the layout)
                UNCLAIMED.append({'line': li + 1, 'x0': bodies[pi]['x0'], 'x1': bodies[pi]['x1'], 'area': bodies[pi]['area']})
            i, k = pi, pk
            if os.environ.get('DBG_LINE') == str(li + 1):
                print('   ', [p['id'] for p in bodies[pi:pi + db]], [g for _, g in seq[pk:pk + dg]], round(best[pi + db, pk + dg] - best[pi, pk], 2))
    for w in words:
        own = [p for p in bodies if p['id'] in w['pieces']]
        w['x0'] = float(min((p['x0'] for p in own), default=0)); w['x1'] = float(max((p['x1'] for p in own), default=0))
    words_out.extend(words)

# --- words per line ----------------------------------------------------------------------------
words_out = []
forced_lines = set()
UNCLAIMED = []
for li, tokens in enumerate(line_tokens):
    bodies = sorted((p for p in pieces if p['line'] == li and not p['mark']), key=lambda p: -p['x1'])
    line_rings = sorted((r for r in rings if r['line'] == li), key=lambda r: -r['x1'])
    # spans between rings (RTL): tokens between verse markers
    # Stretches of words between anchors (RTL): line edges and verse rings, matched in order.
    line_right = max([p['x1'] for p in bodies] + [r['x1'] for r in line_rings] or [bx1])
    line_left = min([p['x0'] for p in bodies] + [r['x0'] for r in line_rings] or [bx0])
    ring_tokens = [i for i, (_, t) in enumerate(tokens) if is_number(t)]
    if len(ring_tokens) != len(line_rings):
        print(f'line {li + 1}: {len(ring_tokens)} verse tokens but {len(line_rings)} rings found')
    stretches, start_i, right = [], 0, line_right
    for n_ring, ti in enumerate(ring_tokens):
        r = line_rings[n_ring] if n_ring < len(line_rings) else None
        left = r['x1'] if r else line_left
        stretches.append((tokens[start_i:ti], right, left))
        if r:
            words_out.append({'line': li + 1, 'word_index': tokens[ti][0], 'text': tokens[ti][1],
                              'x0': r['x0'], 'x1': r['x1'], 'ring': True})
        right = r['x0'] if r else left
        start_i = ti + 1
    stretches.append((tokens[start_i:], right, line_left))
    for toks, right, left in stretches:
        if not toks:
            continue
        wants_hamza = any(g == 'ء' for _, t in toks for g in paws(t))
        hamza_marks = [p for p in pieces if wants_hamza and p['line'] == li and p['mark'] and is_hamza(p)
                       and left - 2 <= p['cx'] <= right + 2]
        star_marks = [p for p in pieces if any(t == '۞' for _, t in toks) and p['line'] == li and p['mark'] and is_star(p)
                      and left - 2 <= p['cx'] <= right + 2]
        span = [p for p in bodies if left - 2 <= p['cx'] <= right + 2 and not p.get('taken')] + hamza_marks + star_marks
        align_stretch(li, toks, span)

for w in words_out:
    if w['text'] == '۞':
        w['ring'] = True; w['star'] = True
# ink inside a verse ring (its black digits) belongs to the ring token
for p in pieces:
    ring = next((w for w in words_out if w['ring'] and w['line'] == p['line'] + 1 and w['x0'] - 4 <= p['cx'] <= w['x1'] + 4), None)
    if ring is not None:
        ring.setdefault('pieces', []).append(p['id']); p['taken'] = True
# a mark joins the word owning the letter body it sits over (most x-overlap, then nearest)
owner_of = {pid: w for w in words_out if not w['ring'] for pid in w.get('pieces', [])}
by_id = {p['id']: p for p in pieces}
for p in pieces:
    if p.get('taken') or p['id'] in owner_of or not p['mark']:
        continue
    cands = [by_id[pid] for pid in owner_of if by_id[pid]['line'] == p['line']]
    if not cands:
        continue
    def score(b):
        overlap = max(0, min(b['x1'], p['x1']) - max(b['x0'], p['x0']))
        return (-overlap, abs((b['x0'] + b['x1']) / 2 - p['cx']) + 0.3 * abs(b['cy'] - p['cy']))
    owner_of[p['id']] = owner_of[min(cands, key=score)['id']]
    owner_of[p['id']].setdefault('pieces', []).append(p['id'])
# bodies left unmatched (skipped fragments) go to the nearest word on their line
for p in pieces:
    if p.get('taken') or p['id'] in owner_of:
        continue
    cands = [w for w in words_out if w['line'] == p['line'] + 1 and not w['ring'] and w.get('pieces')]
    if cands:
        # nearest by edge gap; a word whose text spells a small letter or tanween (ۥ ۦ ٰ ٍ ٖ ...) wins a near-tie
        def gap(w):
            d = 0 if w['x0'] <= p['cx'] <= w['x1'] else min(abs(p['cx'] - w['x0']), abs(p['cx'] - w['x1']))
            return d - (0.15 * line_h if any(ch in SMALL_SIGNS for ch in w['text']) else 0)
        w = min(cands, key=gap)
        w.setdefault('pieces', []).append(p['id'])

# Waqf signs sit high above their word, nearer the line above, so the text decides: for each word
# whose text has a waqf sign, look in the gap above it for a waqf-sized mark that a word on the
# line above (whose text has none) took, and move the largest one down.
WAQF_CHARS = set('ۖۗۚۛۘۙ')
word_of_piece = {pid: w for w in words_out if not w['ring'] for pid in w.get('pieces', [])}
debug = []
moved = 0
for w in [w for w in words_out if not w['ring'] and any(ch in WAQF_CHARS for ch in w['text'])]:
    li = w['line'] - 1
    if li == 0:
        continue
    top, base = baselines[li - 1], baselines[li]
    cands = []
    for pid, owner in word_of_piece.items():
        p = by_id[pid]
        if owner['line'] != w['line'] - 1 or any(ch in WAQF_CHARS for ch in owner['text']) or not p['mark']:
            continue
        if not (w['x0'] - 10 <= p['cx'] <= w['x1'] + 10 and top < p['cy'] < base):
            continue
        cands.append(p)
        debug.append((w['text'], owner['text'], int(p['x1'] - p['x0']), int(p['y1'] - p['y0']), p['area'],
                      round((p['cy'] - top) / (base - top), 2)))
    big = [p for p in cands if p['area'] >= WAQF_MIN_AREA]
    if big:
        p = max(big, key=lambda q: q['area'])
        owner = word_of_piece[p['id']]
        owner['pieces'].remove(p['id']); w['pieces'].append(p['id']); word_of_piece[p['id']] = w; moved += 1
print('waqf signs moved down to their word:', moved)

# A hamza under إ sits just below its alif, under the baseline: it is that word's, never the next
# line's. Mark such pieces so the line-crossing rules below leave them alone.
_alifs = [q for q in pieces if not q['mark'] and alif_like(q)]
for p in pieces:
    if p['mark'] and any(q['line'] == p['line'] and 0 <= p['y0'] - q['y1'] + 0.05 * line_h < 0.25 * line_h
                         and min(q['x1'], p['x1']) - max(q['x0'], p['x0']) >= 0.4 * (p['x1'] - p['x0']) for q in _alifs):
        p['under_alif'] = True

# Marks under a line are kasra-family strokes (thin, ~0.12-0.17 of the line height). A mark below its
# line that is taller, or has a hole (the loop of a damma or tanween damm, a waqf letter), is printed
# over the word on the NEXT line: move it there, with any small fragment beside it (the dot of ج).
def has_hole(p):
    sub = (lab[p['y0']:p['y1'], p['x0']:p['x1']] == p['id']).astype(np.uint8)
    cnts, hier = cv2.findContours(sub, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    return hier is not None and any(h[3] >= 0 for h in hier[0])
word_of_piece = {pid: w for w in words_out if not w['ring'] for pid in w.get('pieces', [])}
moved_down = 0
for p in list(pieces):
    w = word_of_piece.get(p['id'])
    if w is None or not p['mark'] or w['line'] >= len(bands) or p.get('under_alif'):
        continue
    li = w['line'] - 1
    if p['cy'] <= baselines[li] + 0.15 * line_h:          # not below its line
        continue
    tall = (p['y1'] - p['y0']) > 0.24 * line_h
    if not (tall or has_hole(p)):
        continue
    below = [v for v in words_out if v['line'] == w['line'] + 1 and not v['ring'] and v.get('pieces')]
    target = next((v for v in below if v['x0'] - 5 <= p['cx'] <= v['x1'] + 5), None)
    if target is None:
        continue
    pad = 0.3 * max(p['x1'] - p['x0'], p['y1'] - p['y0'])
    group = [q for q in pieces if q['id'] == p['id'] or (word_of_piece.get(q['id']) is w and q['mark'] and q['area'] < 0.25 * p['area']
             and p['x0'] - pad <= q['cx'] <= p['x1'] + pad and p['y0'] - pad <= q['cy'] <= p['y1'] + pad)]
    for q in group:
        if q['id'] in w['pieces']:
            w['pieces'].remove(q['id']); target['pieces'].append(q['id']); word_of_piece[q['id']] = target
    moved_down += 1
print('tall or looped marks moved to the line below:', moved_down)

# Between two lines a kasra of the upper line and a fatha of the lower one look alike. Every mark in
# the gap goes to the line whose letter bodies it sits closer to, measured straight up / down in its
# own columns (a kasra hangs just under its letter; a fatha, damma or waqf sign sits just over its).
word_of_piece = {pid: w for w in words_out if not w['ring'] for pid in w.get('pieces', [])}
body_line = np.zeros(lab.max() + 1, np.int16)
for pid, w in word_of_piece.items():
    if not by_id[pid]['mark']:
        body_line[pid] = w['line']
line_img = body_line[lab]
reassigned = 0
for p in pieces:
    w = word_of_piece.get(p['id'])
    if w is None or not p['mark'] or p.get('under_alif'):
        continue
    L = w['line']                                    # 1-based
    if not (L < len(bands) and p['cy'] > baselines[L - 1]):   # only down: high waqf signs and dammas
        continue                                                  # can sit nearer the descenders above
    up, down = L, L + 1
    if not (baselines[up - 1] < p['cy'] < baselines[down - 1]):
        continue
    cols = line_img[:, max(0, p['x0'] - 3):p['x1'] + 3]
    above = np.where((cols[:p['y0']] == up).any(1))[0]
    below = np.where((cols[p['y1']:] == down).any(1))[0]
    du = p['y0'] - above.max() if len(above) else 1e9
    dl = below.min() if len(below) else 1e9
    want = up if du <= dl else down
    if want == L or min(du, dl) > 0.6 * line_h:
        continue
    # the lower word whose span is nearest (a tanween at a word's end can overhang its span)
    cands = [v for v in words_out if v['line'] == want and not v['ring'] and v.get('pieces')]
    dist = lambda v: max(0.0, v['x0'] - p['cx'], p['cx'] - v['x1'])
    target = min(cands, key=dist, default=None)
    if target is None or dist(target) > 0.2 * line_h:
        continue
    w['pieces'].remove(p['id']); target['pieces'].append(p['id']); word_of_piece[p['id']] = target
    reassigned += 1
print('gap marks reassigned to the nearer line:', reassigned)

# Review flags from Kraken: a word with a Kraken space inside its ink, or a word boundary with no
# Kraken space near it (only on lines Kraken read).
for li, spaces in KRAKEN.items():
    words = sorted((w for w in words_out if w['line'] == li + 1 and w['x1'] > 0), key=lambda w: -w['x1'])
    for a_w, b_w in zip(words, words[1:]):
        gap = (a_w['x0'] + b_w['x1']) / 2
        if not a_w['ring'] and not b_w['ring'] and min((abs(x - gap) for x in spaces), default=1e9) > KR_TOL:
            b_w.setdefault('doubt', []).append('no Kraken space before this word')
    for w in words:
        if not w['ring'] and [x for x in spaces if w['x0'] + KR_TOL < x < w['x1'] - KR_TOL]:
            w.setdefault('doubt', []).append('Kraken space inside')
print('words flagged by Kraken for review:', sum(bool(w.get('doubt')) for w in words_out))

SUFFIX = os.environ.get('PAW_SUFFIX', '')       # mesaha_batch.py's second (Kraken-cost) pass writes paw-words-NNN.kr.json
if not SUFFIX:
    np.savez_compressed(f'labels-{PAGE:03d}.npz', lab=lab.astype(np.uint16))
if os.path.exists(f'labels-{PAGE:03d}.npy'):
    os.remove(f'labels-{PAGE:03d}.npy')        # older uncompressed copy
checks = {
    'lines_short_of_rings': RING_SHORT,                       # a verse number with no medallion found
    'forced_lines': sorted(forced_lines),                     # no letter-group alignment: rough cuts
    'words_without_ink': [w['text'] for w in words_out if not w['ring'] and not w.get('pieces')],
    'kraken_flags': sum(bool(w.get('doubt')) for w in words_out),
    'unclaimed_bodies': UNCLAIMED,                            # letter bodies the text has no letter for
}
json.dump({'page': PAGE, 'bands': bands, 'words': words_out, 'checks': checks},
          open(f'paw-words-{PAGE:03d}{SUFFIX}.json', 'w'), ensure_ascii=False, indent=1)

# --- picture: every word in its own colour ----------------------------------------------------------
if os.environ.get('PAW_PNG') == '1':          # optional picture: every word in its own colour (slow)
  PAL = [(180, 111, 31), (12, 65, 194), (61, 128, 21), (176, 63, 126), (92, 35, 180), (134, 124, 14), (0, 106, 138), (105, 85, 71)]
  out = np.full_like(img, 255)
  for li in range(len(bands)):
    for j, w in enumerate(x for x in words_out if x['line'] == li + 1):
        colour = (40, 40, 200) if w['ring'] else PAL[j % len(PAL)]
        for pid in w.get('pieces', []):
            out[lab == pid] = colour
  cv2.imwrite(f'paw-words-{PAGE:03d}.png', out)
print('page', PAGE, '· words', sum(not w['ring'] for w in words_out), '· rings', sum(w['ring'] for w in words_out),
      '· layout tokens', sum(len(t) for t in line_tokens), '· rings found', len(rings), '· forced lines', sorted(forced_lines),
      '· pitch', round(PITCH, 1))
