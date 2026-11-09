"""Pilot: can an agent cut a connected outline between its two words at the right place?

Where one PDF outline holds the ink of two words (a final letter fused into the next word) no whole-outline owner is right
and the outline needs a knife cut (ShemrlyMushaf line_cuts.py: a chord across the join). ShemrlyMushaf's auto-knife found 19
such outlines on the nine blind pages whose Elgharib word glyphs give an answer key (the two words' placed glyph outlines say
which ink is which word's). This builds those cases, offers each as a picture with numbered candidate chords (the narrowest
necks of the outline over nine angles), has agents pick one (or none), and scores the pick against the answer key:

    ~/Development/ShemrlyMushaf/.venv/bin/python pipeline/paw_split/shamarly_cut_pilot.py build --out artifacts/shamarly-qvp/cut-pilot
    # agents write <out>/results/*.jsonl lines {"id", "choice": <candidate number or "none">, "note"}
    ~/Development/ShemrlyMushaf/.venv/bin/python pipeline/paw_split/shamarly_cut_pilot.py score --out artifacts/shamarly-qvp/cut-pilot

A candidate is correct when its two sides carry at least 90% of the outline's ink that the answer key assigns to a word to
the right word (best of the two side-to-word matchings). Nothing is written to the ShemrlyMushaf databases.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sqlite3
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image
from shapely.geometry import LineString, Point, Polygon
from shapely.ops import split, unary_union

SH = Path.home() / 'Development' / 'ShemrlyMushaf'
sys.path[:0] = [str(SH), str(SH / 'output' / 'auto-knife')]
ROOT = Path(__file__).resolve().parents[2]
SC = 16
ANGLES = (-60, -45, -30, -15, 0, 15, 30, 45, 60)       # degrees from vertical (y down)
MAX_CANDIDATES = 10


def load_case(case):
    from joined import LAB, doc, glyph_polys
    from extract_pdf_pages import flatten_contour, is_quran_black, split_contours
    page = case['page']
    contours = [c for dd in doc[page - 1].get_drawings() if is_quran_black(dd) for c in split_contours(dd)]
    me = contours[case['outline']]
    poly = Polygon(flatten_contour(me, curve_steps=10)).buffer(0)
    lab = json.loads((LAB / f'page-{page:03d}.json').read_text(encoding='utf-8'))
    placed = {}
    for r in lab['words']:
        if r['word_index'] in case['words'] and r.get('offset'):
            placed[r['word_index']] = unary_union([Polygon(p).buffer(0) for p in glyph_polys(r['word_index'], *r['offset'])])
    others = [Polygon(flatten_contour(c, curve_steps=4)).buffer(0) for i, c in enumerate(contours)
              if i != case['outline'] and c.bbox[2] > poly.bounds[0] - 8 and c.bbox[0] < poly.bounds[2] + 8
              and c.bbox[3] > poly.bounds[1] - 8 and c.bbox[1] < poly.bounds[3] + 8]
    return poly, placed, others


def candidates(poly: Polygon):
    """Chords across the outline at its narrowest necks: [{'p0','p1','width','angle'}], best first."""
    x0, y0, x1, y1 = poly.bounds
    diag = math.hypot(x1 - x0, y1 - y0) + 6
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    found = []
    total = poly.area
    for ang in ANGLES:
        t = math.radians(ang)
        d = (math.sin(t), math.cos(t))                      # chord direction
        n = (math.cos(t), -math.sin(t))                     # the direction positions are measured along
        corners = [n[0] * x + n[1] * y for x, y in ((x0, y0), (x0, y1), (x1, y0), (x1, y1))]
        lo, hi = min(corners), max(corners)
        ts = np.arange(lo + 0.15 * (hi - lo), hi - 0.15 * (hi - lo), 0.25)
        widths = []
        for s in ts:
            px, py = n[0] * s + (cx - n[0] * (n[0] * cx + n[1] * cy)), n[1] * s + (cy - n[1] * (n[0] * cx + n[1] * cy))
            a, b = (px - d[0] * diag, py - d[1] * diag), (px + d[0] * diag, py + d[1] * diag)
            inter = LineString([a, b]).intersection(poly)
            if inter.is_empty or inter.geom_type != 'LineString':          # exactly one stretch of ink: the chord crosses twice
                widths.append(None)
                continue
            widths.append((inter.length, a, b))
        for i in range(1, len(ts) - 1):
            if widths[i] and widths[i - 1] and widths[i + 1] and widths[i][0] <= widths[i - 1][0] and widths[i][0] <= widths[i + 1][0]:
                w, a, b = widths[i]
                pieces = split(poly, LineString([a, b]))
                areas = sorted(p.area for p in pieces.geoms)
                if len(areas) == 2 and areas[0] >= 0.08 * total:
                    found.append({'p0': a, 'p1': b, 'width': w, 'angle': ang, 'mid': ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)})
    found.sort(key=lambda c: c['width'])
    kept = []
    for c in found:
        if all(math.hypot(c['mid'][0] - k['mid'][0], c['mid'][1] - k['mid'][1]) > 1.6 or abs(c['angle'] - k['angle']) > 25 for k in kept):
            kept.append(c)
        if len(kept) == MAX_CANDIDATES:
            break
    return kept


def accuracy(poly: Polygon, placed: dict, chord, rng: random.Random, n=1500) -> float:
    """Share of the answer-keyed ink on the right side of the chord (best of the two side-to-word matchings)."""
    words = list(placed)
    pieces = list(split(poly, LineString([chord['p0'], chord['p1']])).geoms)
    if len(pieces) != 2:
        return 0.0
    x0, y0, x1, y1 = poly.bounds
    pts, tries = [], 0
    while len(pts) < n and tries < n * 30:
        tries += 1
        p = Point(rng.uniform(x0, x1), rng.uniform(y0, y1))
        if poly.contains(p):
            pts.append(p)
    labelled = []
    for p in pts:
        who = [w for w in words if placed[w].contains(p)]
        if len(who) == 1:
            labelled.append((p, who[0], 0 if pieces[0].contains(p) else 1))
    if not labelled:
        return 0.0
    best = 0.0
    for flip in (0, 1):
        ok = sum(1 for _p, w, side in labelled if words.index(w) == (side ^ flip))
        best = max(best, ok / len(labelled))
    return best


def render(poly, others, cands):
    x0, y0, x1, y1 = poly.bounds
    ox, oy = x0 - 7, y0 - 7
    w, h = int((x1 - x0 + 14) * SC), int((y1 - y0 + 14) * SC)
    base = np.full((h, w, 3), 255, np.uint8)

    def fill(p, colour):
        geoms = p.geoms if p.geom_type == 'MultiPolygon' else [p]
        for g in geoms:
            if g.is_empty:
                continue
            cv2.fillPoly(base, [np.array([[(x - ox) * SC, (y - oy) * SC] for x, y in g.exterior.coords], np.int32)], colour)
    for o in others:
        fill(o, (190, 190, 190))
    fill(poly, (25, 25, 25))
    plain = base.copy()
    palette = [(220, 40, 40), (30, 120, 220), (30, 160, 60), (230, 130, 0), (160, 40, 200), (0, 170, 170), (200, 60, 120), (110, 110, 0),
               (60, 60, 200), (150, 80, 20)]
    for i, c in enumerate(cands):
        col = palette[i % len(palette)]
        seg = LineString([c['p0'], c['p1']]).intersection(poly.buffer(3.0))      # drawn only near the ink, applied full length
        pts = list(seg.coords) if seg.geom_type == 'LineString' and not seg.is_empty else [c['p0'], c['p1']]
        a = (int((pts[0][0] - ox) * SC), int((pts[0][1] - oy) * SC))
        b = (int((pts[-1][0] - ox) * SC), int((pts[-1][1] - oy) * SC))
        cv2.line(base, a, b, col, 3)
        top = a if a[1] < b[1] else b
        cv2.putText(base, str(i + 1), (max(2, top[0] - 8), max(18, top[1] - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.8, col, 2)
    gap = np.full((h, 10, 3), 120, np.uint8)
    img = np.hstack([plain, gap, base])
    if img.shape[1] > 1600:
        k = 1600 / img.shape[1]
        img = cv2.resize(img, None, fx=k, fy=k, interpolation=cv2.INTER_AREA)
    return img


def build(out: Path, seed: int) -> None:
    cases = json.loads((SH / 'output' / 'auto-knife' / 'joined-list.json').read_text(encoding='utf-8'))
    words = dict(sqlite3.connect(ROOT / 'data' / 'quran_script.db').execute('SELECT word_index, text FROM words').fetchall())
    for sub in ('sheets', 'results', 'truth'):
        (out / sub).mkdir(parents=True, exist_ok=True)
    meta, truth = [], {}
    for k, case in enumerate(cases):
        cid = f'j{k:02d}'
        poly, placed, others = load_case(case)
        cands = candidates(poly)
        rng = random.Random(seed + k)
        accs = [accuracy(poly, placed, c, rng) for c in cands] if len(placed) == 2 else []
        img = render(poly, others, cands)
        Image.fromarray(img).save(out / 'sheets' / f'{cid}.png')
        right, left = sorted(case['words'])
        meta.append({'id': cid, 'right_word': words.get(right, ''), 'left_word': words.get(left, ''), 'words_between': left - right - 1,
                     'candidates': len(cands)})
        truth[cid] = {'page': case['page'], 'outline': case['outline'], 'words': case['words'], 'accuracy': accs,
                      'widths': [c['width'] for c in cands], 'angles': [c['angle'] for c in cands]}
    (out / 'sheets' / 'cases.json').write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding='utf-8')
    (out / 'truth' / 'truth.json').write_text(json.dumps(truth, ensure_ascii=False), encoding='utf-8')
    good = sum(1 for t in truth.values() if t['accuracy'] and max(t['accuracy']) >= 0.9)
    print(f'{len(cases)} cases; a correct candidate (>=90% of keyed ink on the right sides) exists in {good}')


def score(out: Path) -> None:
    truth = json.loads((out / 'truth' / 'truth.json').read_text(encoding='utf-8'))
    picks = {}
    for f in sorted((out / 'results').glob('*.jsonl')):
        for line in f.read_text(encoding='utf-8').splitlines():
            if line.strip():
                r = json.loads(line)
                picks[r['id']] = r
    n = ok = bad = none = 0
    rows = []
    for cid, t in truth.items():
        accs = t['accuracy']
        best = max(accs) if accs else 0
        has = best >= 0.9
        p = picks.get(cid)
        if not p:
            continue
        n += 1
        choice = p['choice']
        if choice in ('none', None, 0):
            none += 1
            res = 'none'
        else:
            i = int(choice) - 1
            a = accs[i] if 0 <= i < len(accs) else 0
            res = 'RIGHT' if a >= 0.9 else 'wrong'
            ok += a >= 0.9
            bad += a < 0.9
        narrow = accs[0] if accs else 0
        rows.append((cid, t['page'], has, round(best, 2), res, round(narrow, 2), p.get('note', '')))
    print(f'{n} cases judged; a correct candidate exists in {sum(1 for r in rows if r[2])}')
    print(f'agent: right {ok}, wrong {bad}, none {none}')
    print(f'baseline narrowest neck: right in {sum(1 for r in rows if r[5] >= 0.9)} of {n}')
    for r in rows:
        print(r)


def _polys_of_d(d: str):
    """Closed polygons of an absolute M/L/C path (page points)."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from shamarly_word_audit import flatten
    return [Polygon(sub).buffer(0) for sub in flatten(d) if len(sub) >= 3]


def build_shared(out: Path, svg_dir: Path, n: int) -> None:
    """Cases from outlines BOTH neighbouring words claim (the pipeline's own evidence of fused ink); the big ones."""
    import glob
    import re
    words = dict(sqlite3.connect(ROOT / 'data' / 'quran_script.db').execute('SELECT word_index, text FROM words').fetchall())
    pool = []
    for f in sorted(glob.glob(str(svg_dir / '???.json'))):
        st = json.loads(Path(f).read_text(encoding='utf-8'))
        for so in st.get('shared_outlines', []):
            b = so['box']
            if (b[2] - b[0]) * (b[3] - b[1]) >= 100 and max(b[2] - b[0], b[3] - b[1]) >= 12:
                pool.append((int(Path(f).stem), so))
    random.Random(20261111).shuffle(pool)
    pool = pool[:n]
    for sub in ('sheets', 'results', 'truth'):
        (out / sub).mkdir(parents=True, exist_ok=True)
    meta, info = [], {}
    for k, (page, so) in enumerate(pool):
        cid = f's{k:02d}'
        polys = _polys_of_d(so['d'])
        poly = max(polys, key=lambda p: p.area)
        svg = (svg_dir / f'{page:03d}.svg').read_text(encoding='utf-8')
        near = []
        for m in re.finditer(r'<path [^>]*? d="([^"]+)"', svg):
            for q in _polys_of_d(m.group(1)):
                b = q.bounds
                if b[2] > poly.bounds[0] - 8 and b[0] < poly.bounds[2] + 8 and b[3] > poly.bounds[1] - 8 and b[1] < poly.bounds[3] + 8 \
                        and not q.equals(poly) and q.area < 3000:
                    near.append(q)
        cands = candidates(poly)
        Image.fromarray(render(poly, near, cands)).save(out / 'sheets' / f'{cid}.png')
        wis = sorted(int(o.split(':')[1]) for o in so['owners'])
        meta.append({'id': cid, 'right_word': words.get(wis[0], ''), 'left_word': words.get(wis[1], ''), 'words_between': 0, 'candidates': len(cands)})
        info[cid] = {'page': page, 'oid': so['oid'], 'line': so['line'], 'owners': so['owners'], 'words': wis, 'd': so['d'],
                     'cands': [{'p0': list(c['p0']), 'p1': list(c['p1']), 'width': c['width'], 'angle': c['angle']} for c in cands]}
    # the cases with an answer key whose two words are neighbours (Elgharib placed glyphs): scored objectively
    joined = json.loads((SH / 'output' / 'auto-knife' / 'joined-list.json').read_text(encoding='utf-8'))
    for k, case in enumerate(c for c in joined if abs(c['words'][1] - c['words'][0]) == 1 and words.get(c['words'][0], '').strip() and
                             not words[c['words'][0]].strip()[0] in '٠١٢٣٤٥٦٧٨٩' and not words.get(c['words'][1], ' ').strip()[0] in '٠١٢٣٤٥٦٧٨٩'):
        cid = f't{k:02d}'
        poly, placed, others = load_case(case)
        cands = candidates(poly)
        rng = random.Random(7 + k)
        Image.fromarray(render(poly, others, cands)).save(out / 'sheets' / f'{cid}.png')
        wis = sorted(case['words'])
        meta.append({'id': cid, 'right_word': words.get(wis[0], ''), 'left_word': words.get(wis[1], ''), 'words_between': 0, 'candidates': len(cands)})
        info[cid] = {'page': case['page'], 'words': wis, 'poly': [list(p) for p in poly.exterior.coords], 'cands': [
            {'p0': list(c['p0']), 'p1': list(c['p1']), 'width': c['width'], 'angle': c['angle']} for c in cands],
            'accuracy': [accuracy(poly, placed, c, rng) for c in cands]}
    (out / 'sheets' / 'cases.json').write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding='utf-8')
    (out / 'truth' / 'shared.json').write_text(json.dumps(info, ensure_ascii=False), encoding='utf-8')
    print(f'{len(pool)} shared big outlines -> sheets (pool of qualifying: see log)')


def apply_choices(out: Path) -> None:
    """Cut each case where its agent chose, and draw the two pieces in two colours with the two words' texts (for a verifier)."""
    info = json.loads((out / 'truth' / 'shared.json').read_text(encoding='utf-8'))
    picks = {}
    for f in sorted((out / 'results').glob('cutter_*.jsonl')):
        for line in f.read_text(encoding='utf-8').splitlines():
            if line.strip():
                r = json.loads(line)
                picks[r['id']] = r
    (out / 'after').mkdir(exist_ok=True)
    made = 0
    for cid, c in info.items():
        r = picks.get(cid)
        if not r or r['choice'] in ('none', None, 0):
            continue
        cand = c['cands'][int(r['choice']) - 1]
        poly = Polygon(c['poly']) if 'poly' in c else max(_polys_of_d(c['d']), key=lambda p: p.area)
        pieces = list(split(poly, LineString([cand['p0'], cand['p1']])).geoms)
        if len(pieces) != 2:
            continue
        x0, y0, x1, y1 = poly.bounds
        ox, oy = x0 - 7, y0 - 7
        w, h = int((x1 - x0 + 14) * SC), int((y1 - y0 + 14) * SC)
        img = np.full((h, w, 3), 255, np.uint8)
        plain = np.full((h, w, 3), 255, np.uint8)
        cv2.fillPoly(plain, [np.array([[(x - ox) * SC, (y - oy) * SC] for x, y in poly.exterior.coords], np.int32)], (25, 25, 25))
        for piece, colour in zip(sorted(pieces, key=lambda p: -p.centroid.x), ((30, 90, 220), (225, 110, 20))):     # right piece blue, left orange
            cv2.fillPoly(img, [np.array([[(x - ox) * SC, (y - oy) * SC] for x, y in piece.exterior.coords], np.int32)], colour)
        img = np.hstack([plain, np.full((h, 10, 3), 120, np.uint8), img])
        if img.shape[1] > 1300:
            k = 1300 / img.shape[1]
            img = cv2.resize(img, None, fx=k, fy=k, interpolation=cv2.INTER_AREA)
        Image.fromarray(img).save(out / 'after' / f'{cid}.png')
        made += 1
    print(f'{made} cut pictures in {out / "after"}')


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('cmd', choices=['build', 'score', 'build-shared', 'apply'])
    ap.add_argument('--out', required=True, type=Path)
    ap.add_argument('--seed', type=int, default=20261111)
    ap.add_argument('--svg-dir', type=Path, default=None)
    ap.add_argument('--n', type=int, default=24)
    a = ap.parse_args()
    {'build': lambda: build(a.out, a.seed), 'score': lambda: score(a.out), 'build-shared': lambda: build_shared(a.out, a.svg_dir, a.n),
     'apply': lambda: apply_choices(a.out)}[a.cmd]()
