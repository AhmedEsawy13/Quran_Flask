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


def build_library():
    words, marks = defaultdict(list), {}
    gaps, pitches = [], []
    for svg in sorted(SVG_DIR.glob('*.svg')):
        n = int(svg.stem)
        stats = json.loads((SVG_DIR / f'{n:03d}.json').read_text(encoding='utf-8'))
        off, empty = set(stats.get('count_off', [])), set(stats.get('empty', []))
        text = svg.read_text(encoding='utf-8')
        lines = [(m.start(), int(m.group(1))) for m in LINE.finditer(text)]
        per_line = defaultdict(list)
        for m in WORD.finditer(text):
            ln = max((l for pos, l in lines if pos < m.start()), default=0)
            ps = [(a, d) for a, d in PATH.findall(m.group(3)) if 'data-mark-family="waqf"' not in a]
            if not ps or m.group(1) in empty:
                continue
            bodies = [bbox(d) for a, d in ps if 'data-kind="body"' in a]
            allb = [bbox(d) for a, d in ps]
            box = (min(b[0] for b in allb), min(b[1] for b in allb), max(b[2] for b in allb), max(b[3] for b in allb))
            rec = {'key': m.group(1), 'text': unescape(m.group(2)), 'page': n, 'line': ln, 'box': box,
                   'bottom': max(b[3] for b in bodies) if bodies else box[3],
                   'paths': [(a, d) for a, d in ps], 'ok': m.group(1) not in off}
            per_line[(n, ln)].append(rec)
            words[rec['text']].append(rec)
        for mk in MARK.finditer(text):
            ps = PATH.findall(mk.group(2))
            if ps:
                ln = max((l for pos, l in lines if pos < mk.start()), default=0)
                marks.setdefault(mk.group(1), {'paths': ps, 'box': bbox(' '.join(d for _a, d in ps)), 'page': n, 'line': ln})
        for (pg, ln), recs in per_line.items():
            base = statistics.median(r['bottom'] for r in recs)
            for r in recs:
                r['baseline'] = base
            recs.sort(key=lambda r: -r['box'][2])
            gaps += [a['box'][0] - b['box'][2] for a, b in zip(recs, recs[1:])]
        bases = sorted(statistics.median(r['bottom'] for r in recs) for (pg, _l), recs in per_line.items() if pg == n)
        pitches += [b - a for a, b in zip(bases, bases[1:]) if 25 < b - a < 70]
    for m in marks.values():                               # line baseline of an ayah mark: its own bottom edge region
        m['baseline'] = m['box'][3] - 6
    return words, marks, statistics.median(g for g in gaps if -5 < g < 30), statistics.median(pitches)


def pick(words):
    """One copy per text: closest to the median ink width, preferring words that pass the count check."""
    chosen = {}
    for text, recs in words.items():
        pool = [r for r in recs if r['ok']] or recs
        med = statistics.median(r['box'][2] - r['box'][0] for r in pool)
        chosen[text] = min(pool, key=lambda r: abs((r['box'][2] - r['box'][0]) - med))
        chosen[text]['copies'] = len(recs)
    return chosen


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


def render(page, lib, marks, gap0, pitch, signs, sign_pt):
    layout = json.loads((MIX / f'layout-{page:03d}.json').read_text(encoding='utf-8'))
    body, missing, shrink, gaps, placed = [], [], [], [], 0
    top = 40.0
    for row, line in enumerate(layout['lines']):
        base_y = top + row * pitch
        items = []
        for w in line['words']:
            rec = lib.get(w['text'])
            if w['text'] and w['text'].strip().isdigit() or (w['text'] and set(w['text']) <= set('٠١٢٣٤٥٦٧٨٩')):
                ak = ':'.join(w['key'].split(':')[:2])
                mk = marks.get(ak)
                items.append({'w': w, 'box': mk['box'], 'base': mk['baseline'], 'paths': mk['paths'], 'kind': 'mark'} if mk
                             else {'w': w, 'box': None, 'kind': 'missing', 'width': 22.0})
            elif rec:
                items.append({'w': w, 'box': rec['box'], 'base': rec['baseline'], 'paths': rec['paths'], 'kind': 'word'})
            else:
                items.append({'w': w, 'box': None, 'kind': 'missing', 'width': 6.0 * max(2, len(w['text'] or w['layout_text']))})
        widths = [(i['box'][2] - i['box'][0]) if i['box'] else i['width'] for i in items]
        n = len(items)
        total = sum(widths)
        f = 1.0
        gap = (PAGE_W - total) / (n - 1) if n > 1 else 0
        if gap < MIN_GAP:
            f = (PAGE_W - MIN_GAP * (n - 1)) / total
            gap = MIN_GAP
        shrink.append(f)
        gaps.append(gap)
        cursor = RIGHT
        for it, wd in zip(items, widths):
            w = it['w']
            if it['kind'] == 'missing':
                body.append(f'<rect x="{cursor - wd * f:.1f}" y="{base_y - 22:.1f}" width="{wd * f:.1f}" height="26" '
                            f'fill="#f3c6c6" stroke="#c0392b" stroke-width="0.6"/>')
                missing.append(w['key'])
            else:
                x1, base = it['box'][2], it['base']
                ds, _loose = compounds(it['paths'])
                paths = ''.join(f'<path d="{d}"/>' for d in ds)
                body.append(f'<g transform="translate({cursor:.2f},{base_y:.2f}) scale({f:.4f}) translate({-x1:.2f},{-base:.2f})">{paths}</g>')
                placed += 1
                if w['sign'] and w['sign'] in signs and it['kind'] == 'word':
                    d, (bx0, by0, bx1, by1) = signs[w['sign']]
                    s = sign_pt / max(b[3] - b[1] for b in (v[1] for v in signs.values()))      # tallest sign = sign_pt pt
                    cx = cursor - wd * f / 2
                    top_y = base_y - (base - it['box'][1]) * f - 3                              # sign's bottom 3 pt over the ink
                    body.append(f'<g transform="translate({cx - s * (bx0 + bx1) / 2:.2f},{top_y + s * by0:.2f}) scale({s:.5f},{-s:.5f})" '
                                f'fill="#b0301c"><path d="{d}"/></g>')
            cursor -= wd * f + gap
    height = top + 15 * pitch + 20
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{RIGHT - PAGE_W - 20:.1f} 0 {PAGE_W + 40:.1f} {height:.1f}" '
           f'width="{(PAGE_W + 40) * 3:.0f}" height="{height * 3:.0f}"><rect x="0" y="0" width="1000" height="{height:.0f}" fill="#fbfaf6"/>'
           f'<g fill="#1a1a1a">{"".join(body)}</g></svg>')
    (MIX / f'mix-{page:03d}.svg').write_text(svg, encoding='utf-8')
    import fitz
    doc = fitz.open(stream=svg.encode(), filetype='svg')
    pix = doc[0].get_pixmap(matrix=fitz.Matrix(1, 1), alpha=False)
    pix.save(str(MIX / f'mix-{page:03d}.png'))
    n_words = sum(len(l['words']) for l in layout['lines'])
    print(f'page {page}: {n_words} items, {len(missing)} without a Shamarly copy {missing[:6]}; gap median {statistics.median(gaps):.1f} pt '
          f'(Shamarly natural {gap0:.1f}); lines shrunk {sum(1 for x in shrink if x < 1)}/{len(shrink)} min x{min(shrink):.2f}')


def main():
    pages = [int(p) for p in sys.argv[1:]] or [3, 100, 250]
    words, marks, gap0, pitch = build_library()
    lib = pick(words)
    print(f'library: {sum(len(v) for v in words.values())} word copies, {len(lib)} distinct texts, {len(marks)} ayah marks; '
          f'natural gap {gap0:.1f} pt, line pitch {pitch:.1f} pt')
    signs = sign_paths()
    for p in pages:
        render(p, lib, marks, gap0, pitch, signs, sign_pt=24.0)


if __name__ == '__main__':
    main()
