"""Stage 2 of the layout x glyphs x waqf prototype: draw an Old Madinah 1405 page (line breaks, stage 1:
shamarly_mix_pages.py) with Shamarly word outlines and another print's waqf signs.

    ~/Development/ShemrlyMushaf/.venv/bin/python pipeline/paw_split/shamarly_mix_render.py 3 100 250
        -> artifacts/shamarly-qvp/mix/mix-NNN.svg / .png and a printed summary

Glyph library: every word of the built Shamarly SVGs (artifacts/shamarly-qvp/svg, 318 pages), keyed by its text. Per
text the copy used is the one whose ink width is closest to the median of its copies, among words that pass the
builder's outline-count check when any does (a word printed once keeps its single, possibly stretched, shape). Each
word keeps its own shape: lines are justified by the space between words only; a line that does not fit is shrunk
uniformly. The Shamarly signs are left out and the chosen column's signs are drawn from the Uthmani Hafs font
(waqf_glyphs.json glyph_map), centred above their word, so the sign's SHAPE is that font's, not the print's.
"""
from __future__ import annotations

import json
import os
import re
import statistics
import sys
from collections import defaultdict
from html import unescape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SVG_DIR = ROOT / 'artifacts' / 'shamarly-qvp' / 'svg'
MIX = ROOT / 'artifacts' / 'shamarly-qvp' / 'mix'
SIGN_FONT = ROOT / 'static' / 'fonts' / 'uthmanic_hafs_v20.woff2'
GLYPHS = ROOT / 'data' / 'waqf_glyphs.json'

LINE = re.compile(r'<g class="line" data-line="(\d+)">')
WORD = re.compile(r'<g class="word" data-word-key="([^"]+)"[^>]*data-rasm-uthmani="([^"]*)"[^>]*>(.*?)</g>', re.S)
MARK = re.compile(r'<g class="ayah-mark" id="[^"]*" data-ayah-key="([^"]+)">(.*?)</g>', re.S)
PATH = re.compile(r'<path ([^>]*?) d="([^"]+)"')
NUM = re.compile(r'-?\d+\.?\d*')

PAGE_W = 435.0          # the Shamarly text block (88..523 pt)
RIGHT = 523.0
MIN_GAP = 2.0


def bbox(d: str):
    """Control-point bounding box of a path (the builder's outlines carry absolute coordinates)."""
    n = [float(v) for v in NUM.findall(d)]
    xs, ys = n[0::2], n[1::2]
    return (min(xs), min(ys), max(xs), max(ys))


def _subpaths(d: str):
    out = []
    for part in re.split(r'(?=M)', d):
        n = [float(v) for v in NUM.findall(part)]
        if len(n) >= 6:
            pts = list(zip(n[0::2], n[1::2]))
            area = sum(pts[i][0] * pts[(i + 1) % len(pts)][1] - pts[(i + 1) % len(pts)][0] * pts[i][1]
                       for i in range(len(pts))) / 2
            out.append({'d': part.strip(), 'pts': pts, 'area': area})
    return out


def _inside(pt, poly):
    x, y, c = pt[0], pt[1], False
    for i in range(len(poly)):
        (x1, y1), (x2, y2) = poly[i], poly[(i + 1) % len(poly)]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            c = not c
    return c


def compounds(paths):
    """Each outline with its own holes as one path, so a hole is only cut from its host.

    The builder joins every outline of a word into one path (and can put a hole in another path than its host), so
    the outlines of touching letters overlap and a hole can sit under a second outline: filled together they either
    fill the counter (nonzero) or punch the overlaps out (even-odd). Outlines are nested by containment (smallest
    outline whose control polygon holds the centroid); one wound against its parent is that parent's hole, unless the
    parent is itself a hole (a digit inside the ornament's ring is ink again). The ornament's ring is wound the other
    way round from the letters, so the winding sign alone says nothing.
    """
    subs = [sp for _a, d in paths for sp in _subpaths(d)]
    for sp in subs:
        sp['c'] = (sum(p[0] for p in sp['pts']) / len(sp['pts']), sum(p[1] for p in sp['pts']) / len(sp['pts']))
    subs.sort(key=lambda sp: -abs(sp['area']))
    done, hosts = [], []
    for sp in subs:
        parents = [q for q in done if abs(q['area']) > abs(sp['area']) and _inside(sp['c'], q['pts'])]
        parent = min(parents, key=lambda q: abs(q['area'])) if parents else None
        if parent is not None and parent['kind'] == 'host' and (sp['area'] > 0) != (parent['area'] > 0):
            sp['kind'] = 'hole'
            parent['holes'].append(sp['d'])
        else:
            sp['kind'], sp['holes'] = 'host', []
            hosts.append(sp)
        done.append(sp)
    return [' '.join([h['d']] + h['holes']) for h in hosts], 0


def _small(b):
    return (b[3] - b[1]) < 9.0 and (b[2] - b[0]) * (b[3] - b[1]) < 28.0


def _lower_profile_level(pts):
    """Median over x (1 pt columns) of the lowest point of one outline: the level of its long bottom run."""
    cols = {}
    for a, b in zip(pts, pts[1:] + pts[:1]):
        n = max(1, int(((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2) ** 0.5 / 0.5))
        for k in range(n):
            x, y = a[0] + (b[0] - a[0]) * k / n, a[1] + (b[1] - a[1]) * k / n
            c = int(x)
            if y > cols.get(c, -1e9):
                cols[c] = y
    return statistics.median(cols.values())


def word_geometry(paths):
    """(full ink box, body x-extent, baseline) of a word's outlines.

    The baseline is the level of the bottom run of the widest outline (the connected body stroke): inside the original
    lines that estimate is collinear within ~0.8 pt (median), where the bottom of the widest outline is 1.3 pt with a
    heavy tail (a final ي or ر tail drags it 12 pt down), the median bottom 4.6 pt and the lowest point 3.5 pt, because
    Shamarly's words ride up and down on the line. Never deeper than a descender can be below the ink's bottom edge.
    The body extent leaves out the small marks and tails that overhang, so spaces are measured on the letters.
    """
    subs = [sp for _a, d in paths for sp in _subpaths(d)]
    boxes = []
    for sp in subs:
        xs, ys = [q[0] for q in sp['pts']], [q[1] for q in sp['pts']]
        boxes.append((min(xs), min(ys), max(xs), max(ys), sp['area'], sp))
    full = (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))
    big = [b for b in boxes if b[4] > 0 and not _small(b[:4])] or boxes
    widest = max(big, key=lambda b: b[2] - b[0])
    base = _lower_profile_level(widest[5]['pts'])
    return full, (min(b[0] for b in big), max(b[2] for b in big)), min(base, full[3]) if base > full[3] - 17 else full[3] - 17


def line_baselines(recs):
    """Put every word of one source line on one baseline: a trimmed straight-line fit through the words' own estimates.

    Single-word estimates still miss now and then (a short word whose widest outline is a tail, a word the calligrapher
    stacked a few points high), so the line's fit decides where each word sits, at the word's own x.
    """
    if len(recs) < 4:
        level = statistics.median(r['est'] for r in recs)
        return lambda x: level
    xs = [(r['bx'][0] + r['bx'][1]) / 2 for r in recs]
    ys = [r['est'] for r in recs]
    keep = list(range(len(recs)))
    a_, b_ = statistics.median(ys), 0.0
    for _ in range(3):
        mx, my = statistics.fmean(xs[i] for i in keep), statistics.fmean(ys[i] for i in keep)
        den = sum((xs[i] - mx) ** 2 for i in keep) or 1.0
        b_ = sum((xs[i] - mx) * (ys[i] - my) for i in keep) / den
        a_ = my - b_ * mx
        res = sorted(abs(ys[i] - (a_ + b_ * xs[i])) for i in range(len(recs)))
        cut = res[int(0.7 * (len(res) - 1))]
        keep = [i for i in range(len(recs)) if abs(ys[i] - (a_ + b_ * xs[i])) <= max(cut, 0.5)] or keep
    return lambda x: a_ + b_ * x


def build_library():
    words, marks = defaultdict(list), {}
    gaps, pitches, sign_sizes, orn = [], [], defaultdict(list), []
    for svg in sorted(SVG_DIR.glob('*.svg')):
        n = int(svg.stem)
        stats = json.loads((SVG_DIR / f'{n:03d}.json').read_text(encoding='utf-8'))
        off, empty = set(stats.get('count_off', [])), set(stats.get('empty', []))
        text = svg.read_text(encoding='utf-8')
        lines = [(m.start(), int(m.group(1))) for m in LINE.finditer(text)]
        per_line = defaultdict(list)
        for m in WORD.finditer(text):
            ln = max((l for pos, l in lines if pos < m.start()), default=0)
            raw = PATH.findall(m.group(3))
            for a, d in raw:                                       # the print's own sign sizes, per sign class
                if 'data-mark-family="waqf"' in a:
                    b = bbox(d)
                    sign_sizes[re.search(r'data-mark="([^"]*)"', a).group(1)].append((b[2] - b[0], b[3] - b[1]))
            ps = [(a, d) for a, d in raw if 'data-mark-family="waqf"' not in a]
            if not ps or m.group(1) in empty:
                continue
            full, bx, est = word_geometry(ps)
            rec = {'key': m.group(1), 'text': unescape(m.group(2)), 'page': n, 'line': ln, 'box': full, 'bx': bx,
                   'est': est, 'paths': ps, 'ok': m.group(1) not in off}
            per_line[(n, ln)].append(rec)
            words[rec['text']].append(rec)
        fits = {}
        for (pg, ln), recs in per_line.items():
            fits[ln] = line_baselines(recs)
            for r in recs:
                r['baseline'] = fits[ln]((r['bx'][0] + r['bx'][1]) / 2)
            recs.sort(key=lambda r: -r['bx'][1])
            gaps += [a['bx'][0] - b['bx'][1] for a, b in zip(recs, recs[1:])]
        for mk in MARK.finditer(text):
            ps = PATH.findall(mk.group(2))
            if ps:
                ln = max((l for pos, l in lines if pos < mk.start()), default=0)
                box = bbox(' '.join(d for _a, d in ps))
                marks.setdefault(mk.group(1), {'paths': ps, 'box': box, 'bx': (box[0], box[2]), 'page': n, 'line': ln})
                if ln in fits:                                     # where a ring sits against its line's baseline
                    orn.append(fits[ln]((box[0] + box[2]) / 2) - (box[1] + box[3]) / 2)
        bases = sorted(statistics.median(r['baseline'] for r in recs) for (pg, _l), recs in per_line.items() if pg == n)
        pitches += [b - a for a, b in zip(bases, bases[1:]) if 25 < b - a < 70]
    ring_lift = statistics.median(orn)
    for m in marks.values():                                       # a ring's "baseline": its centre sits ring_lift above it
        m['baseline'] = (m['box'][1] + m['box'][3]) / 2 + ring_lift
    return words, marks, statistics.median(g for g in gaps if -5 < g < 30), statistics.median(pitches), sign_sizes


def pick(words):
    """One copy per text: closest to the median ink width, preferring words that pass the count check."""
    chosen = {}
    for text, recs in words.items():
        pool = [r for r in recs if r['ok']] or recs
        med = statistics.median(r['bx'][1] - r['bx'][0] for r in pool)
        chosen[text] = min(pool, key=lambda r: abs((r['bx'][1] - r['bx'][0]) - med))
        chosen[text]['copies'] = len(recs)
    return chosen


WAQF_MARK = {'ج': 'waqf_jaiz_mustawi_al_tarafayn', 'ق': 'waqf_jaiz_waqf_awla', 'ص': 'waqf_jaiz_wasl_awla',
             'م': 'waqf_lazim', 'ع': 'waqf_al_muanaqah', 'س': 'saktah', 'لا': ''}
QATAR_SVG = ROOT / 'artifacts' / 'qatar-qvp' / 'svg'


def sign_library(sign_sizes):
    """{sign: {'d': outline moved to (0,0), 'w', 'h'}} drawn at the size this print gives that sign.

    The outlines are the chosen print's own where we have them (Qatar's traced pages: ج ص ق); the others come from the
    Uthmani Hafs font. Either way the height is the median Shamarly height of that sign, so a sign is as big as the
    print's own, not as big as a font's em.
    """
    def local(d):
        n = [float(v) for v in NUM.findall(d)]
        x0, y0 = min(n[0::2]), min(n[1::2])
        return re.sub(r'-?\d+\.?\d*', lambda m: m.group(0), d), (x0, y0, max(n[0::2]) - x0, max(n[1::2]) - y0)

    def move(d, x0, y0):
        out, i = [], 0
        for tok in re.finditer(r'[A-Za-z]|-?\d+\.?\d*', d):
            t = tok.group(0)
            if t.isalpha():
                out.append(t)
                i = 0
            else:
                out.append(f'{float(t) - (x0 if i % 2 == 0 else y0):.2f}')
                i += 1
        return ' '.join(out)

    lib, per_mark = {}, defaultdict(list)
    for svg in sorted(QATAR_SVG.glob('*.svg')):
        for m in re.finditer(r'<path data-kind="mark" data-mark="([^"]*)" data-mark-family="waqf" d="([^"]+)"', svg.read_text(encoding='utf-8')):
            if m.group(1):
                _d, (x0, y0, w, h) = local(m.group(2))
                if w > 1 and h > 1:
                    per_mark[m.group(1)].append((w * h, m.group(2), (x0, y0, w, h)))
    for sym, mark in WAQF_MARK.items():
        want = statistics.median(h for _w, h in sign_sizes[mark]) if sign_sizes.get(mark) else 9.0
        if per_mark.get(mark):
            _a, d, (x0, y0, w, h) = sorted(per_mark[mark])[len(per_mark[mark]) // 2]    # the median-size traced sign
            k = want / h
            lib[sym] = {'d': move(d, x0, y0), 'w': w * k, 'h': want, 'k': k, 'src': 'qatar'}
    glyphs = sign_paths()
    for sym, (d, (bx0, by0, bx1, by1)) in glyphs.items():
        if sym in lib or sym not in WAQF_MARK:
            continue
        want = statistics.median(h for _w, h in sign_sizes[WAQF_MARK[sym]]) if sign_sizes.get(WAQF_MARK[sym]) else 9.0
        k = want / (by1 - by0)
        lib[sym] = {'d': d, 'w': (bx1 - bx0) * k, 'h': want, 'k': k, 'src': 'font', 'font': (bx0, by0, bx1, by1)}
    return lib


def sign_paths():
    from fontTools.pens.boundsPen import BoundsPen
    from fontTools.pens.svgPathPen import SVGPathPen
    from fontTools.ttLib import TTFont
    font = TTFont(SIGN_FONT)
    cmap, gs = font.getBestCmap(), font.getGlyphSet()
    gmap = json.loads(GLYPHS.read_text(encoding='utf-8'))['glyph_map']
    out = {}
    for sym, ch in gmap.items():
        name = cmap.get(ord(ch[0]))
        if not name or sym in out:
            continue
        pen, bp = SVGPathPen(gs), BoundsPen(gs)
        gs[name].draw(pen)
        gs[name].draw(bp)
        d = pen.getCommands()
        if d and bp.bounds:
            out[sym] = (d, bp.bounds)           # (xmin, ymin, xmax, ymax) in font units
    return out


BAND = (-22, 5)         # rows (pt relative to the word's baseline) the optical gap is measured over
CLEAR = 1.0             # the tightest row between two words keeps at least this much white


def profile(paths, base):
    """{row: (leftmost x, rightmost x)} of a word's ink in 1 pt rows around its baseline (marks above the band ignored)."""
    rows = {}
    for sp in (sp for _a, d in paths for sp in _subpaths(d)):
        pts = sp['pts']
        for p, q in zip(pts, pts[1:] + pts[:1]):
            n = max(1, int(((q[0] - p[0]) ** 2 + (q[1] - p[1]) ** 2) ** 0.5 / 0.5))
            for k in range(n):
                x, y = p[0] + (q[0] - p[0]) * k / n, p[1] + (q[1] - p[1]) * k / n
                r = int(y - base // 1) if False else int((y - base) // 1)
                if BAND[0] <= r <= BAND[1]:
                    lo, hi = rows.get(r, (x, x))
                    rows[r] = (min(lo, x), max(hi, x))
    return rows


def pair_gap(a, b):
    """For a (right) and b (left): (mean, min) over shared rows of the white between a's left edge and b's right edge,
    measured from the two bodies' extents, so extent gap d gives optical gap d + mean."""
    if not (a.get('prof') and b.get('prof')):
        return 0.0, 0.0
    ra, rb = a['prof'], b['prof']
    vals = [(ra[r][0] - a['bx'][0]) + (b['bx'][1] - rb[r][1]) for r in ra if r in rb]
    if len(vals) < 3:
        return 0.0, 0.0
    return sum(vals) / len(vals), min(vals)


def space_line(items, width):
    """Extent gaps d_i between neighbouring items (reading order, right to left), and the line's shrink factor.

    The white between two words is measured as an area (the mean over the rows both words have ink in of the distance
    between their facing edges), not between their extreme points, and that optical gap is the same for every pair on
    the line; a pair whose tightest row would drop below CLEAR keeps CLEAR there and the others share the rest.
    """
    n = len(items)
    bodies = [(i['bx'][1] - i['bx'][0]) if i['bx'] else i['width'] for i in items]
    if n < 2:
        return [], 1.0, bodies, 0.0
    m, bound = [], []
    for a, b in zip(items, items[1:]):
        mean, low = pair_gap(a, b)
        m.append(mean)
        bound.append(CLEAR - low)                           # smallest extent gap that keeps CLEAR in the tightest row
    total = sum(bodies)
    if total + sum(bound) > width:
        return bound, (width - sum(bound)) / total, bodies, 0.0
    fixed, free = {}, set(range(n - 1))
    while True:
        g = (width - total - sum(fixed.values()) + sum(m[i] for i in free)) / max(1, len(free))
        over = [i for i in free if g - m[i] < bound[i]]
        if not over:
            d = [fixed[i] if i in fixed else g - m[i] for i in range(n - 1)]
            return d, 1.0, bodies, g
        for i in over:
            fixed[i] = bound[i]
            free.discard(i)


STRETCH_W = float(os.environ.get('MIX_STRETCH_W', 8.0))         # weight of a copy being wider than the text's natural (25th percentile) copy
GAP_W = float(os.environ.get('MIX_GAP_W', 0.03))            # weight of the line's mean gap leaving GAP_GOAL
GAP_GOAL = float(os.environ.get('MIX_GAP_GOAL', 8.0))          # pt between bodies the line should end up with
MAX_COPIES = 8
DEBUG = '--debug' in sys.argv
_CAND = {}


def candidates(text, words):
    """[(width, stretch penalty, record)] for a text: its copies that pass the count check (all when none does),
    at most MAX_COPIES of them spread over the widths; a copy's penalty grows with how much wider it is than the text's
    25th-percentile copy (a justified line stretches words, rarely squeezes them). No penalty with fewer than 3 copies."""
    if text in _CAND:
        return _CAND[text]
    recs = words.get(text, [])
    pool = [r for r in recs if r['ok']] or recs
    out, seen = [], set()
    for r in sorted(pool, key=lambda r: r['bx'][1] - r['bx'][0]):
        w = round(r['bx'][1] - r['bx'][0])
        if w not in seen:
            seen.add(w)
            out.append((w, r))
    if len(out) > MAX_COPIES:
        out = [out[round(i * (len(out) - 1) / (MAX_COPIES - 1))] for i in range(MAX_COPIES)]
    ws = sorted(r['bx'][1] - r['bx'][0] for r in pool)
    nat = ws[len(ws) // 4] if len(ws) >= 3 else None
    _CAND[text] = [(w, STRETCH_W * max(0.0, ((r['bx'][1] - r['bx'][0]) / nat - 1)) ** 2 if nat else 0.0, r) for w, r in out]
    return _CAND[text]


def fit_line(texts, fixed, words, width):
    """Pick one copy per word so the line fills its width with the least stretch and a mean gap near GAP_GOAL.

    A knapsack over the sum of the words' widths (1 pt steps): the cheapest stretch penalty for every reachable total,
    then the total whose gap (width - total) / (n - 1) costs least. ``fixed[i]`` is a width for items that have only one
    choice (verse rings, missing words); None otherwise. Returns [record or None], and the chosen gap.
    """
    n = len(texts)
    opts = []
    for t, fx in zip(texts, fixed):
        if fx is not None:
            opts.append([(int(round(fx)), 0.0, None)])
        else:
            opts.append(candidates(t, words) or [(int(round(6.0 * max(2, len(t)))), 0.0, None)])
    cap = int(width) - 3 * (n - 1)
    INF = float('inf')
    dp = [{} for _ in range(n + 1)]
    dp[0][0] = (0.0, None)
    for i in range(n):
        for tot, (pen, _bp) in dp[i].items():
            for k, (w, pn, _r) in enumerate(opts[i]):
                t2 = tot + w
                if t2 > cap:
                    continue
                if t2 not in dp[i + 1] or pen + pn < dp[i + 1][t2][0]:
                    dp[i + 1][t2] = (pen + pn, (tot, k))
    if not dp[n]:                                           # nothing fits: the narrowest copy of everything
        pick_ = [min(o, key=lambda c: c[0]) for o in opts]
        return [c[2] for c in pick_], 0.0
    best, best_cost = None, INF
    for tot, (pen, _bp) in dp[n].items():
        g = (width - tot) / (n - 1) if n > 1 else GAP_GOAL
        cost = pen + GAP_W * (g - GAP_GOAL) ** 2
        if cost < best_cost:
            best, best_cost = tot, cost
    chosen, tot = [], best
    for i in range(n, 0, -1):
        prev, k = dp[i][tot][1]
        chosen.append(opts[i - 1][k][2])
        tot = prev
    chosen.reverse()
    return chosen, (width - best) / (n - 1) if n > 1 else 0.0


KASHIDA_OVER = float(os.environ.get('MIX_KASHIDA_OVER', 9.5))     # a line looser than this (pt, optical) is tightened with kashida
KASHIDA_MAX = 1.6                                                  # a flat run is lengthened by at most this factor
ZONE_MIN, ZONE_THICK, ZONE_FLAT = 3.0, 8.0, 1.5


def flat_zones(rec):
    """x-runs (source coordinates) where the word's letters are only a thin flat stroke: the kashida a calligrapher
    lengthens. Columns of 1 pt where the ink spans at most ZONE_THICK pt vertically and its top and bottom edges stay
    within ZONE_FLAT pt of the run's median, in runs of at least ZONE_MIN pt. Marks and dots are not considered."""
    if 'zones' in rec:
        return rec['zones']
    cols = {}
    for _a, d in rec['paths']:
        for sp in _subpaths(d):
            xs, ys = [q[0] for q in sp['pts']], [q[1] for q in sp['pts']]
            if sp['area'] <= 0 or _small((min(xs), min(ys), max(xs), max(ys))):
                continue
            pts = sp['pts']
            for p, q in zip(pts, pts[1:] + pts[:1]):
                n = max(1, int(((q[0] - p[0]) ** 2 + (q[1] - p[1]) ** 2) ** 0.5 / 0.5))
                for k in range(n):
                    x, y = p[0] + (q[0] - p[0]) * k / n, p[1] + (q[1] - p[1]) * k / n
                    lo, hi = cols.get(int(x), (y, y))
                    cols[int(x)] = (min(lo, y), max(hi, y))
    zones, run = [], []

    def close():
        if len(run) >= ZONE_MIN:
            tops, bots = sorted(c[1][0] for c in run), sorted(c[1][1] for c in run)
            mt, mb = tops[len(tops) // 2], bots[len(bots) // 2]
            if all(abs(c[1][0] - mt) <= ZONE_FLAT and abs(c[1][1] - mb) <= ZONE_FLAT for c in run):
                zones.append((run[0][0], run[-1][0] + 1))
    for x in sorted(cols):
        lo, hi = cols[x]
        if hi - lo <= ZONE_THICK and (not run or x == run[-1][0] + 1):
            run.append((x, (lo, hi)))
        else:
            close()
            run = [(x, (lo, hi))] if hi - lo <= ZONE_THICK else []
    close()
    rec['zones'] = zones
    return zones


def _map_x(d, fx, dx_small=None):
    out, i = [], 0
    for tok in re.finditer(r'[A-Za-z]|-?\d+\.?\d*', d):
        t = tok.group(0)
        if t.isalpha():
            out.append(t)
            i = 0
        else:
            v = float(t)
            out.append(f'{fx(v) if i % 2 == 0 else v:.2f}' if dx_small is None else f'{v + dx_small:.2f}' if i % 2 == 0 else t)
            i += 1
    return ' '.join(out)


def widen(rec, extra):
    """The word with its flat runs lengthened by ``extra`` pt in all (shared in proportion to run length): big outlines are
    warped piecewise, marks and dots keep their shape and move with the stretch under them. Returns a new record."""
    zones = flat_zones(rec)
    cap = sum(b - a for a, b in zones) * (KASHIDA_MAX - 1)
    if not zones or extra <= 0:
        return rec
    extra = min(extra, cap)
    total = sum(b - a for a, b in zones)
    scale = 1 + extra / total

    def fx(x):
        out = x
        for a, b in zones:
            if x >= b:
                out += (scale - 1) * (b - a)
            elif x > a:
                out += (scale - 1) * (x - a)
        return out
    paths = []
    for attrs, d in rec['paths']:
        parts = []
        for sp in _subpaths(d):
            xs, ys = [q[0] for q in sp['pts']], [q[1] for q in sp['pts']]
            if _small((min(xs), min(ys), max(xs), max(ys))):
                cx = (min(xs) + max(xs)) / 2
                parts.append(_map_x(sp['d'], None, fx(cx) - cx))
            else:
                parts.append(_map_x(sp['d'], fx))
        paths.append((attrs, ' '.join(parts)))
    full, bx, _base = word_geometry(paths)
    new = dict(rec)
    new.update({'paths': paths, 'box': full, 'bx': bx})
    new.pop('zones', None)
    return new


def render(page, lib, marks, gap0, pitch, signs, color='#1a1a1a', words=None, fit=True):
    layout = json.loads((MIX / f'layout-{page:03d}.json').read_text(encoding='utf-8'))
    body, missing, shrink, gaps_all, line_gap, stretched, counted, stretched_lines = [], [], [], [], [], 0, 0, []
    top = 40.0
    rects, pending = {}, []
    for row, line in enumerate(layout['lines']):
        base_y = top + row * pitch
        ring = [bool(w['text']) and set(w['text']) <= set('٠١٢٣٤٥٦٧٨٩') for w in line['words']]
        recs = [lib.get(w['text']) for w in line['words']]
        if fit and words is not None:
            def ring_width(w):
                mk = marks.get(':'.join(w['key'].split(':')[:2]))
                return (mk['bx'][1] - mk['bx'][0]) if mk else 22.0
            fixed = [ring_width(w) if r else None for w, r in zip(line['words'], ring)]
            chosen, _g = fit_line([w['text'] for w in line['words']], fixed, words, PAGE_W)
            recs = [None if r else c for r, c in zip(ring, chosen)]
        items = []
        for w, r_, rec in zip(line['words'], ring, recs):
            if r_:
                mk = marks.get(':'.join(w['key'].split(':')[:2]))
                items.append({'w': w, 'box': mk['box'], 'bx': mk['bx'], 'base': mk['baseline'], 'paths': mk['paths'], 'kind': 'mark'} if mk
                             else {'w': w, 'box': None, 'bx': None, 'kind': 'missing', 'width': 22.0})
            elif rec:
                items.append({'w': w, 'box': rec['box'], 'bx': rec['bx'], 'base': rec['baseline'], 'paths': rec['paths'], 'kind': 'word', 'rec': rec})
            else:
                items.append({'w': w, 'box': None, 'bx': None, 'kind': 'missing', 'width': 6.0 * max(2, len(w['text'] or w['layout_text']))})
        for it in items:
            if it['kind'] == 'word':
                it['prof'] = profile(it['paths'], it['base'])
        gaps, f, bodies, g_opt = space_line(items, PAGE_W)
        if fit and g_opt > KASHIDA_OVER:                    # too loose: lengthen flat runs a little in every word that has one
            need = (g_opt - KASHIDA_OVER) * (len(items) - 1)
            caps = [(sum(b - a for a, b in flat_zones(it['rec'])) * (KASHIDA_MAX - 1)) if it['kind'] == 'word' else 0.0 for it in items]
            take = min(need, sum(caps))
            if take > 0:
                for it, cap in zip(items, caps):
                    if cap > 0:
                        new = widen(it['rec'], take * cap / sum(caps))
                        it.update({'paths': new['paths'], 'box': new['box'], 'bx': new['bx'], 'prof': profile(new['paths'], it['base'])})
                gaps, f, bodies, g_opt = space_line(items, PAGE_W)
                stretched_lines.append(take)
        shrink.append(f)
        gaps_all += gaps
        if gaps:
            line_gap.append(sum(gaps) / len(gaps))
        for it in items:                                   # how stretched the words used are (vs the text's 25th-percentile copy)
            if it['kind'] == 'word' and words is not None:
                ws = sorted(r['bx'][1] - r['bx'][0] for r in (words.get(it['w']['text']) or []))
                if len(ws) >= 3:
                    counted += 1
                    stretched += (it['bx'][1] - it['bx'][0]) > 1.3 * ws[len(ws) // 4]
        cursor = RIGHT
        for k, (it, bw) in enumerate(zip(items, bodies)):
            w = it['w']
            if it['kind'] == 'missing':
                body.append(f'<rect x="{cursor - bw * f:.1f}" y="{base_y - 22:.1f}" width="{bw * f:.1f}" height="26" '
                            f'fill="#f3c6c6" stroke="#c0392b" stroke-width="0.6"/>')
                missing.append(w['key'])
            else:
                x1, base = it['bx'][1], it['base']
                ds, _loose = compounds(it['paths'])
                if DEBUG:                                  # a hue per word, its small outlines in the opposite hue
                    import colorsys
                    hue = (k * 0.381966) % 1.0
                    def col(hh, l):
                        r, g, b = colorsys.hls_to_rgb(hh % 1.0, l, 0.85)
                        return f'#{int(r * 255):02x}{int(g * 255):02x}{int(b * 255):02x}'
                    inner = ''.join(f'<path d="{d}" fill="{col(hue + 0.5, 0.42) if _small(bbox(d)) else col(hue, 0.30)}"/>' for d in ds)
                else:
                    inner = ''.join(f'<path d="{d}"/>' for d in ds)
                body.append(f'<g transform="translate({cursor:.2f},{base_y:.2f}) scale({f:.4f}) translate({-x1:.2f},{-base:.2f})">'
                            + inner + '</g>')
                for _a, d_ in it['paths']:                 # ink rectangles of this word as placed (for sign clearance)
                    for sp in _subpaths(d_):
                        xs_, ys_ = [q[0] for q in sp['pts']], [q[1] for q in sp['pts']]
                        rects.setdefault(row, []).append((cursor + (min(xs_) - x1) * f, base_y + (min(ys_) - base) * f,
                                                          cursor + (max(xs_) - x1) * f, base_y + (max(ys_) - base) * f, id(it)))
                sg = signs.get(w['sign']) if it['kind'] == 'word' else None
                if sg:
                    pending.append((row, it, cursor, f, base_y, sg))
            cursor -= bw * f + (gaps[k] * f if k < len(gaps) else 0)
    for row, it, cursor, f, base_y, sg in pending:
        # above the last letters (the left end of the word), over the ink that is really there; where that spot is under
        # ink of the line above (or of a neighbour), the sign slides along the word's left end to the clearest spot
        x1, base = it['bx'][1], it['base']
        others = [r for rr in (row - 1, row) for r in rects.get(rr, []) if not (rr == row and r[4] == id(it))]
        best = None
        for off in (0, 4, -4, 8, -8, 12, 16):
            sx = it['bx'][0] + min(max(0.18 * (it['bx'][1] - it['bx'][0]), 6.0), 12.0) + off
            if not it['bx'][0] <= sx <= it['bx'][1]:
                continue
            half = sg['w'] / (2 * f) + 1.0                     # the sign's own width, so a tall mark beside it counts
            tops = [q[1] for _a, d in it['paths'] for sp in _subpaths(d) for q in sp['pts'] if sx - half <= q[0] <= sx + half]
            top_src = min(tops) if tops else it['box'][1]
            cx = cursor - (x1 - sx) * f
            bottom = base_y + (top_src - base) * f - 2.0
            box = (cx - sg['w'] / 2 - 0.5, bottom - sg['h'] - 0.5, cx + sg['w'] / 2 + 0.5, bottom + 0.5)
            hit = sum(max(0.0, min(box[2], r[2]) - max(box[0], r[0])) * max(0.0, min(box[3], r[3]) - max(box[1], r[1])) for r in others)
            if best is None or hit < best[0]:
                best = (hit, cx, bottom)
            if hit == 0:
                break
        _hit, cx, bottom = best
        if sg['src'] == 'qatar':
            body.append(f'<g transform="translate({cx - sg["w"] / 2:.2f},{bottom - sg["h"]:.2f}) scale({sg["k"]:.4f})">'
                        f'<path d="{sg["d"]}" fill="{color}"/></g>')
        else:
            fx0, fy0, fx1, fy1 = sg['font']
            body.append(f'<g transform="translate({cx - sg["k"] * (fx0 + fx1) / 2:.2f},{bottom + sg["k"] * fy0:.2f}) '
                        f'scale({sg["k"]:.5f},{-sg["k"]:.5f})"><path d="{sg["d"]}" fill="{color}"/></g>')
    height = top + 15 * pitch + 20
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{RIGHT - PAGE_W - 20:.1f} 0 {PAGE_W + 40:.1f} {height:.1f}" '
           f'width="{(PAGE_W + 40) * 3:.0f}" height="{height * 3:.0f}"><rect x="0" y="0" width="1000" height="{height:.0f}" fill="#fbfaf6"/>'
           f'<g fill="{color}">{"".join(body)}</g></svg>')
    tag = '-debug' if DEBUG else ''
    (MIX / f'mix-{page:03d}{tag}.svg').write_text(svg, encoding='utf-8')
    import fitz
    doc = fitz.open(stream=svg.encode(), filetype='svg')
    pix = doc[0].get_pixmap(matrix=fitz.Matrix(1, 1), alpha=False)
    pix.save(str(MIX / f'mix-{page:03d}{tag}.png'))
    n_words = sum(len(l['words']) for l in layout['lines'])
    sp = statistics.pstdev(gaps_all) if len(gaps_all) > 1 else 0
    print(f'page {page}: {n_words} items, {len(missing)} without a Shamarly copy {missing[:6]}; body gap median {statistics.median(gaps_all):.1f} pt, '
          f'lines shrunk {sum(1 for x in shrink if x < 1)}/{len(shrink)}; mean gap per line {statistics.mean(line_gap):.1f} pt, '
          f'std across lines {statistics.pstdev(line_gap):.1f} (range {min(line_gap):.1f}..{max(line_gap):.1f}); '
          f'words >1.3x natural width: {stretched}/{counted} ({stretched / max(1, counted):.0%}); kashida on {len(stretched_lines)} lines, '
          f'{statistics.mean(stretched_lines) if stretched_lines else 0:.0f} pt per line')


def main():
    pages = [int(p) for p in sys.argv[1:] if p.isdigit()] or [3, 100, 250]
    words, marks, gap0, pitch, sign_sizes = build_library()
    lib = pick(words)
    print(f'library: {sum(len(v) for v in words.values())} word copies, {len(lib)} distinct texts, {len(marks)} ayah marks; '
          f'natural body gap {gap0:.1f} pt, line pitch {pitch:.1f} pt')
    signs = sign_library(sign_sizes)
    print('signs:', {k: (v['src'], round(v['h'], 1)) for k, v in signs.items()})
    color = '#b0301c' if '--red-signs' in sys.argv else '#1a1a1a'
    for p in pages:
        render(p, lib, marks, gap0, pitch, signs, color, words, fit='--median' not in sys.argv)


if __name__ == '__main__':
    main()
