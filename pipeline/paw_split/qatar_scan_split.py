"""Split a page of the 604-page Qatar scan (data/cv/pages/qatar/pNNN_w2000.jpg, really 3299 x 4596) into lines and
words, to read its waqf signs word by word (pipeline/paw_split/qatar_scan_waqf.py), independently of the «قطر» column.

Same word method as qatar_split.py (the Qatar app's own 600 dpi pages), with the lines found on the scan itself:
the text block is the inside of the coloured frame, and the 15 printed rows (surah name and basmala take one row
each, as in every 15-line Madinah-layout print) are an evenly spaced comb fitted to the black ink. Verse rings are
the coloured medallions inside the block. The step of qatar_split.py that moves a sign to a word whose TEXT carries
a sign is left out: the layout text holds Madinah's signs, and this check must not lean on them.

    python3 pipeline/paw_split/qatar_scan_split.py 50      # -> artifacts/qatar-scan/paw-words-050.json, labels
"""
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))
from pipeline.paw_split._common import ROOT, workdir  # noqa: E402
workdir('qatar-scan')

import json
import os
import sqlite3
import sys

import cv2
import numpy as np

PAGE = int(sys.argv[1]) if len(sys.argv) > 1 else 50
QATAR_DB = f'{ROOT}/data/mushaf-qatar-layout.db'
SCRIPT_DB = f'{ROOT}/data/mushaf-bahrain-layout.db'
SLOTS = 15

img = cv2.imread(f'{ROOT}/data/cv/pages/qatar/p{PAGE:03d}_w2000.jpg')
H, W = img.shape[:2]
hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
# The scan's "black" text is a dark, tinted ink (saturation up to ~240, value under ~100); the frame and the
# verse rings are lighter colours. Brightness separates them, saturation does not.
coloured = (hsv[..., 1] >= 90) & (hsv[..., 2] >= 110) & (hsv[..., 2] < 235)
ink = (hsv[..., 2] < 110) & ~coloured

# --- text block: inside the coloured frame -------------------------------------------------------
# From each page edge inward: the frame is the first thick band where the colour fills most of the middle;
# the block starts where that band ends. (Out from the centre, a surah banner would be taken for the frame.)
def _inner_edge(frac, forward):
    idx = range(len(frac)) if forward else range(len(frac) - 1, -1, -1)
    it = iter(idx)
    for i in it:                                   # outer edge of the frame
        if frac[i] > 0.5:
            break
    last = i
    for i in it:                                   # through the frame, allowing thin gaps between its rules
        if frac[i] > 0.25:
            last = i
        elif abs(i - last) > 40:          # the thin inner rule sits ~20 px inside the thick band
            break
    return last


_byrow = np.convolve(coloured[:, int(0.3 * W):int(0.7 * W)].mean(1), np.ones(5) / 5, mode='same')
_bycol = np.convolve(coloured[int(0.3 * H):int(0.7 * H)].mean(0), np.ones(5) / 5, mode='same')
by0, by1 = _inner_edge(_byrow, True), _inner_edge(_byrow, False)
bx0, bx1 = _inner_edge(_bycol, True), _inner_edge(_bycol, False)
M = 6
bx0, bx1, by0, by1 = bx0 + M, bx1 - M, by0 + M, by1 - M
inside = np.zeros_like(ink); inside[by0:by1, bx0:bx1] = True
ink &= inside

# --- 15 rows: an evenly spaced comb over the ink profile ------------------------------------------
_prof = np.convolve(ink[:, bx0:bx1].sum(1).astype(float), np.ones(41) / 41, mode='same')
_span = by1 - by0
_best = max(((sum(_prof[int(y0 + i * pt)] for i in range(SLOTS)), y0, pt)
             for pt in np.arange(0.060 * _span, 0.070 * _span, 0.5)
             for y0 in range(by0, int(by0 + 0.06 * _span), 2) if y0 + (SLOTS - 1) * pt < by1))
_, _y0, _pt = _best
# each row settles on its own ink peak within a quarter pitch (the rows are not perfectly even on the scan)
_r = int(0.25 * _pt)
SLOT_CENTRES = [max(range(int(_y0 + i * _pt) - _r, int(_y0 + i * _pt) + _r + 1), key=lambda y: _prof[y]) for i in range(SLOTS)]
PITCH = float(_pt)

# --- layout tokens per line (ayah rows only; a header row keeps its slot) -------------------------
q = sqlite3.connect(QATAR_DB)
rows = q.execute("SELECT line_number, first_word_id, last_word_id FROM pages WHERE page_number=? AND line_type='ayah' "
                 "AND first_word_id IS NOT NULL ORDER BY line_number", (PAGE,)).fetchall()
s = sqlite3.connect(SCRIPT_DB)
text = dict(s.execute('SELECT word_index, text FROM words WHERE word_index BETWEEN ? AND ?', (rows[0][1], rows[-1][2])))
line_tokens = [[(wi, text[wi]) for wi in range(a, b + 1)] for _, a, b in rows]
LINE_NUMBERS = [r[0] for r in rows]
bands = [(SLOT_CENTRES[n - 1] - 0.42 * PITCH, SLOT_CENTRES[n - 1] + 0.30 * PITCH) for n in LINE_NUMBERS]
print('page', PAGE, 'pitch', round(PITCH, 1), 'text rows', len(rows))

# --- ink pieces, verse rings ---------------------------------------------------------------------
inside = np.zeros_like(ink); inside[int(by0):int(by1), int(bx0):int(bx1)] = True
n, lab, st, cen = cv2.connectedComponentsWithStats((ink & inside).astype(np.uint8), 8)
pieces = []
for i in range(1, n):
    x, y, w, h, a = (int(v) for v in st[i])
    if w > 0.5 * (bx1 - bx0) or h > 0.5 * (by1 - by0) or a < 6:      # frame rules, specks
        continue
    pieces.append({'id': i, 'x0': x, 'x1': x + w, 'y0': y, 'y1': y + h, 'cx': cen[i][0], 'cy': cen[i][1], 'area': a})
col = (coloured & inside).astype(np.uint8)
cn, cl, cs, cc = cv2.connectedComponentsWithStats(cv2.dilate(col, np.ones((9, 9), np.uint8)), 8)
RING_SIZES = []
rings = [dict(x0=int(cs[i][0]), x1=int(cs[i][0] + cs[i][2]), cy=cc[i][1]) for i in range(1, cn)
         if 0.45 * PITCH < cs[i][2] < 0.95 * PITCH and 0.5 * PITCH < cs[i][3] < 1.05 * PITCH]

line_h = np.median([b - a for a, b in bands])
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
    touches = p['y0'] - 0.04 * line_h <= base <= p['y1'] + 0.04 * line_h
    small = (p['y1'] - p['y0']) < 0.42 * line_h and p['area'] < 0.06 * line_h * line_h
    p['mark'] = small and not touches
# The hamza of إ hangs just under its alif, down at the baseline, so it looks like a short letter:
# a small piece right below a tall thin alif (and mostly within its columns) is that alif's mark.
alifs = [q for q in pieces if not q['mark'] and (q['y1'] - q['y0']) > 0.5 * line_h and (q['x1'] - q['x0']) < 0.2 * line_h]
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


def weight(token):
    return max(1.0, sum(ch in LETTERS for ch in token))



# --- text letter-groups (PAWs) ------------------------------------------------------------------
ALIFS = set('اأإآٱ')
NON_JOIN = set('اأإآٱدذرزوؤةى')


def paws(token):
    """The word's connected letter groups, in reading order. A hamza on the line (ء) joins neither
    side, so it is a small group of its own: the text then decides which word it belongs to."""
    letters = [ch for ch in token if ch in LETTERS]
    groups, cur = [], []
    for ch in letters:
        if ch == 'ء':
            if cur:
                groups.append(''.join(cur)); cur = []
            groups.append('ء')
            continue
        cur.append(ch)
        if ch in NON_JOIN:
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
    return max(0.6, len(group) * 1.0 - 0.3 * sum(ch in ALIFS for ch in group))


def is_hamza(p):
    """A hamza on the line: small, roughly square, sitting at the baseline (not above or below)."""
    w, h = p['x1'] - p['x0'], p['y1'] - p['y0']
    base = baselines[p['line']]
    return 0.12 * line_h < h < 0.4 * line_h and 0.5 < w / max(h, 1) < 1.6 and p['y1'] >= base - 0.15 * line_h and p['y0'] <= base


def alif_like(p):
    w, h = p['x1'] - p['x0'], p['y1'] - p['y0']
    return h > 0.45 * line_h and w < 0.32 * h


KRAKEN = {}
if os.path.exists(f'kraken-spaces-{PAGE:03d}.json'):
    KRAKEN = {int(k) - 1: v for k, v in json.load(open(f'kraken-spaces-{PAGE:03d}.json')).items()}
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
        actual = max(1.0, sum(p['x1'] - p['x0'] for p in ps))
        expect = max(1.0, scale * sum(units(g) for g in gs))
        return np.log(actual / expect) ** 2

    def shape_cost(ps, gs):
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
                c = pen + (width_cost(ps, gs) + shape_cost(ps, gs) if dg else 0.0)
                if dg and spaces and 0 < i and 0 < k:
                    gap = (bodies[i - 1]['x0'] + bodies[i]['x1']) / 2
                    near = min((abs(x - gap) for x in spaces), default=1e9) <= KR_TOL
                    new_word = seq[k][0] != seq[k - 1][0]
                    if new_word and not near:
                        c += 0.5        # a word split where Kraken read no space
                    elif not new_word and near:
                        c += 0.5        # Kraken read a space inside one word
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
            i, k = pi, pk
    for w in words:
        own = [p for p in bodies if p['id'] in w['pieces']]
        w['x0'] = float(min((p['x0'] for p in own), default=0)); w['x1'] = float(max((p['x1'] for p in own), default=0))
    words_out.extend(words)

# --- words per line ----------------------------------------------------------------------------
words_out = []
forced_lines = set()
for li, tokens in enumerate(line_tokens):
    bodies = sorted((p for p in pieces if p['line'] == li and not p['mark']), key=lambda p: -p['x1'])
    line_rings = sorted((r for r in rings if r['line'] == li), key=lambda r: -r['x1'])
    # spans between rings (RTL): tokens between verse markers
    # Stretches of words between anchors (RTL): line edges and verse rings, matched in order.
    line_right = max([p['x1'] for p in bodies] + [r['x1'] for r in line_rings] or [bx1])
    line_left = min([p['x0'] for p in bodies] + [r['x0'] for r in line_rings] or [bx0])
    ring_tokens = [i for i, (_, t) in enumerate(tokens) if t.startswith('۝')]
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
        span = [p for p in bodies if left - 2 <= p['cx'] <= right + 2 and not p.get('taken')] + hamza_marks
        align_stretch(li, toks, span)

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
        w = min(cands, key=lambda w: 0 if w['x0'] <= p['cx'] <= w['x1'] else min(abs(p['cx'] - w['x0']), abs(p['cx'] - w['x1'])))
        w.setdefault('pieces', []).append(p['id'])

# (qatar_split.py's text-driven waqf move is left out: see the module docstring)


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
    if w is None or not p['mark'] or w['line'] >= len(bands):
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
    if w is None or not p['mark']:
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

np.savez_compressed(f'labels-{PAGE:03d}.npz', lab=lab.astype(np.uint16))
json.dump({'page': PAGE, 'bands': bands, 'line_numbers': LINE_NUMBERS, 'pitch': PITCH, 'words': words_out}, open(f'paw-words-{PAGE:03d}.json', 'w'), ensure_ascii=False, indent=1)

print('words', sum(not w['ring'] for w in words_out), '· rings', sum(w['ring'] for w in words_out),
      '· layout tokens', sum(len(t) for t in line_tokens), '· rings found', len(rings), '· forced lines', sorted(forced_lines))
