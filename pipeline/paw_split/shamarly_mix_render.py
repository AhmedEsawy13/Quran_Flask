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
        return [], 1.0, bodies
    m, bound = [], []
    for a, b in zip(items, items[1:]):
        mean, low = pair_gap(a, b)
        m.append(mean)
        bound.append(CLEAR - low)                           # smallest extent gap that keeps CLEAR in the tightest row
    total = sum(bodies)
    if total + sum(bound) > width:
        return bound, (width - sum(bound)) / total, bodies
    fixed, free = {}, set(range(n - 1))
    while True:
        g = (width - total - sum(fixed.values()) + sum(m[i] for i in free)) / max(1, len(free))
        over = [i for i in free if g - m[i] < bound[i]]
        if not over:
            d = [fixed[i] if i in fixed else g - m[i] for i in range(n - 1)]
            return d, 1.0, bodies
        for i in over:
            fixed[i] = bound[i]
            free.discard(i)


def render(page, lib, marks, gap0, pitch, signs, color='#1a1a1a'):
    layout = json.loads((MIX / f'layout-{page:03d}.json').read_text(encoding='utf-8'))
    body, missing, shrink, gaps_all = [], [], [], []
    top = 40.0
    for row, line in enumerate(layout['lines']):
        base_y = top + row * pitch
        items = []
        for w in line['words']:
            rec = lib.get(w['text'])
            if w['text'] and set(w['text']) <= set('٠١٢٣٤٥٦٧٨٩'):
                mk = marks.get(':'.join(w['key'].split(':')[:2]))
                items.append({'w': w, 'box': mk['box'], 'bx': mk['bx'], 'base': mk['baseline'], 'paths': mk['paths'], 'kind': 'mark'} if mk
                             else {'w': w, 'box': None, 'bx': None, 'kind': 'missing', 'width': 22.0})
            elif rec:
                items.append({'w': w, 'box': rec['box'], 'bx': rec['bx'], 'base': rec['baseline'], 'paths': rec['paths'], 'kind': 'word'})
            else:
                items.append({'w': w, 'box': None, 'bx': None, 'kind': 'missing', 'width': 6.0 * max(2, len(w['text'] or w['layout_text']))})
        for it in items:
            if it['kind'] == 'word':
                it['prof'] = profile(it['paths'], it['base'])
        gaps, f, bodies = space_line(items, PAGE_W)
        shrink.append(f)
        gaps_all += gaps
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
                body.append(f'<g transform="translate({cursor:.2f},{base_y:.2f}) scale({f:.4f}) translate({-x1:.2f},{-base:.2f})">'
                            + ''.join(f'<path d="{d}"/>' for d in ds) + '</g>')
                sg = signs.get(w['sign']) if it['kind'] == 'word' else None
                if sg:
                    # above the last letters (the left end of the word), just over the ink that is really there
                    sx = it['bx'][0] + min(max(0.18 * (it['bx'][1] - it['bx'][0]), 6.0), 12.0)
                    tops = [q[1] for _a, d in it['paths'] for sp in _subpaths(d) for q in sp['pts'] if sx - 7 <= q[0] <= sx + 7]
                    top_src = min(tops) if tops else it['box'][1]
                    cx = cursor - (x1 - sx) * f
                    bottom = base_y + (top_src - base) * f - 2.0
                    if sg['src'] == 'qatar':
                        body.append(f'<g transform="translate({cx - sg["w"] / 2:.2f},{bottom - sg["h"]:.2f}) scale({sg["k"]:.4f})">'
                                    f'<path d="{sg["d"]}" fill="{color}"/></g>')
                    else:
                        fx0, fy0, fx1, fy1 = sg['font']
                        body.append(f'<g transform="translate({cx - sg["k"] * (fx0 + fx1) / 2:.2f},{bottom + sg["k"] * fy0:.2f}) '
                                    f'scale({sg["k"]:.5f},{-sg["k"]:.5f})"><path d="{sg["d"]}" fill="{color}"/></g>')
            cursor -= bw * f + (gaps[k] * f if k < len(gaps) else 0)
    height = top + 15 * pitch + 20
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{RIGHT - PAGE_W - 20:.1f} 0 {PAGE_W + 40:.1f} {height:.1f}" '
           f'width="{(PAGE_W + 40) * 3:.0f}" height="{height * 3:.0f}"><rect x="0" y="0" width="1000" height="{height:.0f}" fill="#fbfaf6"/>'
           f'<g fill="{color}">{"".join(body)}</g></svg>')
    (MIX / f'mix-{page:03d}.svg').write_text(svg, encoding='utf-8')
    import fitz
    doc = fitz.open(stream=svg.encode(), filetype='svg')
    pix = doc[0].get_pixmap(matrix=fitz.Matrix(1, 1), alpha=False)
    pix.save(str(MIX / f'mix-{page:03d}.png'))
    n_words = sum(len(l['words']) for l in layout['lines'])
    sp = statistics.pstdev(gaps_all) if len(gaps_all) > 1 else 0
    print(f'page {page}: {n_words} items, {len(missing)} without a Shamarly copy {missing[:6]}; body gap median {statistics.median(gaps_all):.1f} pt, '
          f'std {sp:.1f}; lines shrunk {sum(1 for x in shrink if x < 1)}/{len(shrink)} min x{min(shrink):.2f}')


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
        render(p, lib, marks, gap0, pitch, signs, color)


if __name__ == '__main__':
    main()
