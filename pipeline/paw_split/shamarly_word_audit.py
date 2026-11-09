"""Random-sample audit of word ownership on the Shamarly vector pages (the method of Itqan d/961).

How many words of the served pages (artifacts/shamarly-qvp/svg) own exactly their own ink? Ground truth for the
whole book does not exist, so (1) draw a fixed-seed random sample of words, (2) show each on an enlarged crop with
the ink the system gave it in red, a waqf sign it was given in blue, every other word's ink in grey (plain ink beside
it), (3) have a judge (an LLM agent reading the sheet) answer OK / MISSING / EXTRA / BOTH / UNSURE, (4) hide known
errors among the real items (planted: a small piece of the word turned grey, or a neighbour's small piece turned
red) to measure how many errors the judge actually catches, and (5) score:

    python pipeline/paw_split/shamarly_word_audit.py build --out <dir> [--n 1000] [--planted 120] [--seed 20261109]
    # judges write <dir>/results/*.jsonl lines {"id": ..., "verdict": ..., "note": ...}
    python pipeline/paw_split/shamarly_word_audit.py score --out <dir>

Items are shuffled and named by opaque ids; the truth (which are planted, which words) is in <dir>/truth/truth.json,
which judges are never told about. Needs numpy + opencv + Pillow.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import re
from html import unescape
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
SVG_DIR = ROOT / 'artifacts' / 'shamarly-qvp' / 'svg'
SC = 7                       # pixels per PDF point
PER_SHEET = 6
VERDICTS = ('OK', 'MISSING', 'EXTRA', 'BOTH', 'UNSURE')

_WORD = re.compile(r'<g class="word" data-word-key="([^"]+)"[^>]*data-rasm-uthmani="([^"]*)"[^>]*>(.*?)</g>', re.S)
_PATH = re.compile(r'<path ([^>]*?) d="([^"]+)"')
_TOK = re.compile(r'[MLCQZ]|-?\d+\.?\d*')


def flatten(d: str) -> list[list[tuple[float, float]]]:
    """Sub-paths of an SVG path (M L C Q Z, absolute) as point lists."""
    toks, i, subs, cur, pos = _TOK.findall(d), 0, [], [], (0.0, 0.0)

    def num():
        nonlocal i
        i += 1
        return float(toks[i - 1])

    while i < len(toks):
        t = toks[i]
        i += 1
        if t == 'M':
            if cur:
                subs.append(cur)
            pos = (num(), num())
            cur = [pos]
        elif t == 'L':
            pos = (num(), num())
            cur.append(pos)
        elif t == 'C':
            p1, p2, p3 = (num(), num()), (num(), num()), (num(), num())
            for s in range(1, 9):
                u = s / 8
                a, b, c, e = (1 - u) ** 3, 3 * u * (1 - u) ** 2, 3 * u * u * (1 - u), u ** 3
                cur.append((a * pos[0] + b * p1[0] + c * p2[0] + e * p3[0], a * pos[1] + b * p1[1] + c * p2[1] + e * p3[1]))
            pos = p3
        elif t == 'Q':
            p1, p2 = (num(), num()), (num(), num())
            for s in range(1, 7):
                u = s / 6
                a, b, c = (1 - u) ** 2, 2 * u * (1 - u), u * u
                cur.append((a * pos[0] + b * p1[0] + c * p2[0], a * pos[1] + b * p1[1] + c * p2[1]))
            pos = p2
        elif t == 'Z' and cur:
            subs.append(cur)
            cur = []
    if cur:
        subs.append(cur)
    return [s for s in subs if len(s) >= 3]


def _box(sub):
    xs, ys = [p[0] for p in sub], [p[1] for p in sub]
    return min(xs), min(ys), max(xs), max(ys)


def _area(sub) -> float:
    x0, y0, x1, y1 = _box(sub)
    return (x1 - x0) * (y1 - y0)


_cache: dict[int, list[dict]] = {}


def page_words(page: int) -> list[dict]:
    """[{key, text, subs: [(kind, sub-path)]}] of one built page, in reading order."""
    if page not in _cache:
        svg = (SVG_DIR / f'{page:03d}.svg').read_text(encoding='utf-8')
        words = []
        for m in _WORD.finditer(svg):
            subs = []
            for p in _PATH.finditer(m.group(3)):
                kind = 'sign' if 'data-mark-family="waqf"' in p.group(1) else 'ink'
                subs += [(kind, s) for s in flatten(p.group(2))]
            if subs:
                words.append({'key': m.group(1), 'text': unescape(m.group(2)), 'subs': subs})
        _cache[page] = words
    return _cache[page]


COL = {'bg': (255, 255, 255), 'ink': (25, 25, 25), 'mine': (30, 30, 215), 'sign': (200, 90, 0), 'other': (170, 170, 170)}


def _render(region, groups, scale=SC) -> np.ndarray:
    """groups: [(color, [sub-paths])] drawn in order (xor within a group so holes stay open)."""
    x0, y0, x1, y1 = region
    w, h = int((x1 - x0) * scale), int((y1 - y0) * scale)
    img = np.full((h, w, 3), 255, np.uint8)
    for color, subs in groups:
        acc = np.zeros((h, w), np.uint8)
        for s in subs:
            m = np.zeros((h, w), np.uint8)
            cv2.fillPoly(m, [np.array([[(x - x0) * scale, (y - y0) * scale] for x, y in s], np.int32)], 1)
            acc ^= m
        img[acc > 0] = color
    return img


def render_item(page: int, index: int, planted: str | None, rng: random.Random):
    """(image, planted detail) for word `index` of a page; `planted` is None, 'missing' or 'extra'."""
    words = page_words(page)
    me = words[index]
    boxes = [_box(s) for _k, s in me['subs']]
    bx0, by0, bx1, by1 = min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)
    region = (bx0 - 9, by0 - 10, bx1 + 9, by1 + 9)
    detail = None
    mine = [s for k, s in me['subs'] if k == 'ink']
    signs = [s for k, s in me['subs'] if k == 'sign']
    others = [s for j, w in enumerate(words) if j != index for _k, s in w['subs']]
    small_mine = [s for s in mine if _area(s) < 30]
    if planted == 'missing':
        if not small_mine:
            return None
        gone = rng.choice(small_mine)
        mine = [s for s in mine if s is not gone]
        others = others + [gone]
        detail = 'missing'
    elif planted == 'extra':
        near = [s for s in others if region[0] < (_box(s)[0] + _box(s)[2]) / 2 < region[2]
                and region[1] < (_box(s)[1] + _box(s)[3]) / 2 < region[3] and _area(s) < 30]
        if not near:
            return None
        take = rng.choice(near)
        others = [s for s in others if s is not take]
        mine = mine + [take]
        detail = 'extra'
    plain = _render(region, [(COL['ink'], [s for _k, s in me['subs']] + others)])
    colored = _render(region, [(COL['other'], others), (COL['mine'], mine), (COL['sign'], signs)])
    gap = np.full((plain.shape[0], 8, 3), 120, np.uint8)
    img = np.hstack([plain, gap, colored])
    if img.shape[1] > 1500:
        k = 1500 / img.shape[1]
        img = cv2.resize(img, (1500, max(1, int(img.shape[0] * k))), interpolation=cv2.INTER_AREA)
    return img, detail


def build(out: Path, n: int, planted_n: int, seed: int) -> None:
    pages = sorted(int(p.stem) for p in SVG_DIR.glob('[0-9]*.svg'))
    pool = [(p, i) for p in pages for i in range(len(page_words(p)))]
    rng = random.Random(seed)
    chosen = rng.sample(pool, n + planted_n * 2)
    real, spare = chosen[:n], chosen[n:]
    items = [{'page': p, 'index': i, 'planted': None} for p, i in real]
    made = 0
    for k, (p, i) in enumerate(spare):
        if made >= planted_n:
            break
        mode = 'missing' if made % 2 == 0 else 'extra'
        if render_item(p, i, mode, random.Random(seed + k)) is not None:
            items.append({'page': p, 'index': i, 'planted': mode, 'planted_seed': seed + k})
            made += 1
    rng.shuffle(items)
    for number, it in enumerate(items):
        it['id'] = f'w{number:04d}'
    for sub in ('sheets', 'results', 'truth'):
        (out / sub).mkdir(parents=True, exist_ok=True)
    cells, truth = [], {}
    for it in items:
        r = render_item(it['page'], it['index'], it['planted'], random.Random(it.get('planted_seed', 0)))
        img = r[0]
        w = page_words(it['page'])[it['index']]
        header = np.full((18, img.shape[1], 3), 235, np.uint8)
        cv2.putText(header, it['id'], (4, 13), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)
        cells.append((np.vstack([header, img]), {'id': it['id'], 'text': w['text']}))
        truth[it['id']] = {'page': it['page'], 'key': w['key'], 'planted': it['planted']}
    for s in range(0, len(cells), PER_SHEET):
        chunk = cells[s:s + PER_SHEET]
        width = max(c.shape[1] for c, _ in chunk)
        canvas = np.full((sum(c.shape[0] + 6 for c, _ in chunk), width, 3), 255, np.uint8)
        y = 0
        for c, _ in chunk:
            canvas[y:y + c.shape[0], :c.shape[1]] = c
            y += c.shape[0] + 6
        name = f'sheet_{s // PER_SHEET:03d}'
        Image.fromarray(canvas[:, :, ::-1]).save(out / 'sheets' / f'{name}.png')
        (out / 'sheets' / f'{name}.json').write_text(json.dumps([m for _, m in chunk], ensure_ascii=False), encoding='utf-8')
    (out / 'truth' / 'truth.json').write_text(json.dumps({'seed': seed, 'n_real': n, 'items': truth}, ensure_ascii=False), encoding='utf-8')
    print(f'{len(items)} items ({n} real + {len(items) - n} planted) on {math.ceil(len(items) / PER_SHEET)} sheets in {out}')


def clopper_pearson_upper(k: int, n: int, conf: float = 0.95) -> float:
    """Exact one-sided upper bound of a binomial proportion (bisection on the cdf)."""
    if k >= n:
        return 1.0
    alpha = 1 - conf
    lo, hi = k / n, 1.0
    for _ in range(80):
        p = (lo + hi) / 2
        cdf = sum(math.comb(n, j) * p ** j * (1 - p) ** (n - j) for j in range(k + 1))
        if cdf > alpha:
            lo = p
        else:
            hi = p
    return hi


def score(out: Path) -> None:
    truth = json.loads((out / 'truth' / 'truth.json').read_text(encoding='utf-8'))['items']
    verdicts: dict[str, dict] = {}
    for f in sorted((out / 'results').glob('*.jsonl')):
        for line in f.read_text(encoding='utf-8').splitlines():
            if line.strip():
                row = json.loads(line)
                verdicts[row['id']] = row
    missing = [i for i in truth if i not in verdicts]
    real = [i for i, t in truth.items() if t['planted'] is None and i in verdicts]
    planted = [i for i, t in truth.items() if t['planted'] and i in verdicts]
    flagged = lambda i: verdicts[i]['verdict'] in ('MISSING', 'EXTRA', 'BOTH')
    unsure = [i for i in real if verdicts[i]['verdict'] == 'UNSURE']
    bad = [i for i in real if flagged(i)]
    print(f'judged {len(verdicts)} of {len(truth)} (not yet judged: {len(missing)})')
    n = len(real)
    print(f'real words {n}: OK {n - len(bad) - len(unsure)}, flagged {len(bad)}, unsure {len(unsure)}')
    if planted:
        caught = [i for i in planted if flagged(i)]
        d = len(caught) / len(planted)
        for mode in ('missing', 'extra'):
            ps = [i for i in planted if truth[i]['planted'] == mode]
            print(f'  planted {mode}: caught {sum(1 for i in ps if flagged(i))}/{len(ps)}')
        print(f'judge recall d = {d:.1%} on {len(planted)} planted errors')
    else:
        d = None
    if n:
        p = len(bad) / n
        print(f'flagged rate {p:.2%}  (95% one-sided upper bound {clopper_pearson_upper(len(bad), n):.2%})')
        if d:
            print(f'corrected for judge recall: ~{p / d:.2%} of words wrong (flagged rate / d)')
    by_page: dict[int, int] = {}
    for i in bad:
        by_page[truth[i]['page']] = by_page.get(truth[i]['page'], 0) + 1
    (out / 'flagged.json').write_text(json.dumps(
        [{'id': i, **truth[i], 'verdict': verdicts[i]['verdict'], 'note': verdicts[i].get('note', '')} for i in bad],
        ensure_ascii=False, indent=1), encoding='utf-8')
    print('flagged items written to', out / 'flagged.json')


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('cmd', choices=['build', 'score'])
    ap.add_argument('--out', required=True, type=Path)
    ap.add_argument('--n', type=int, default=1000)
    ap.add_argument('--planted', type=int, default=120)
    ap.add_argument('--seed', type=int, default=20261109)
    a = ap.parse_args()
    build(a.out, a.n, a.planted, a.seed) if a.cmd == 'build' else score(a.out)
