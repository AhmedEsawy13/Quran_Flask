"""Random-sample audit of the tajweed LETTER colouring on the Shamarly vector pages (same method as shamarly_word_audit.py).

The reader colours a tajweed letter by clipping the word's body ink to an x-interval (letters from the Kraken finder).
Hand-written letters overlap, so a vertical slice can miss part of the target letter or bleed into a neighbour. How
often? Draw a fixed-seed random sample of (word, letter, rule) from pages built with TJ_AUDIT_DIR (the letters the
builder painted), show each as an enlarged crop (plain ink | the body ink inside the interval painted), have a blind
judge answer OK / PARTIAL / BLEED / WRONG / UNSURE, hide known errors among them (planted: the interval moved one
letter over, or widened 2.5x) to measure the judge's recall, and score with a Clopper-Pearson bound:

    TJ_AUDIT_DIR=artifacts/shamarly-qvp/tajweed-audit SHAMARLY_SVG_OUT=<dir> .../shamarly_qvp_svg.py <pages>
    python pipeline/paw_split/shamarly_letter_audit.py build --svg-dir <dir> --out <audit dir> [--n 400] [--planted 70]
    # judges write <audit dir>/results/*.jsonl lines {"id", "verdict", "note"}
    python pipeline/paw_split/shamarly_letter_audit.py score --out <audit dir>
"""
from __future__ import annotations

import argparse
import json
import math
import random
import re
import sys
from html import unescape
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
from shamarly_word_audit import _box, clopper_pearson_upper, flatten  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
AUDIT_DUMP = ROOT / 'artifacts' / 'shamarly-qvp' / 'tajweed-audit'
SC = 8
PER_SHEET = 6
BAD = ('PARTIAL', 'BLEED', 'WRONG')
_WORD = re.compile(r'<g class="word" data-word-key="([^"]+)"[^>]*>(.*?)</g>', re.S)
_PATH = re.compile(r'<path ([^>]*?) d="([^"]+)"')
INK, GREY, PAINT = (25, 25, 25), (185, 185, 185), (215, 30, 140)


def page_words(svg_dir: Path, page: int, cache={}):
    if (svg_dir, page) not in cache:
        text = (svg_dir / f'{page:03d}.svg').read_text(encoding='utf-8')
        words = {}
        for m in _WORD.finditer(text):
            words[m.group(1)] = [('body' if 'data-kind="body"' in a else 'other', s) for a, d in _PATH.findall(m.group(2)) for s in flatten(d)]
        cache[(svg_dir, page)] = words
    return cache[(svg_dir, page)]


def mask(region, subs):
    x0, y0, x1, y1 = region
    w, h = int((x1 - x0) * SC), int((y1 - y0) * SC)
    acc = np.zeros((h, w), np.uint8)
    for s in subs:
        m = np.zeros((h, w), np.uint8)
        cv2.fillPoly(m, [np.array([[(x - x0) * SC, (y - y0) * SC] for x, y in s], np.int32)], 1)
        acc ^= m
    return acc > 0


def render(svg_dir: Path, page: int, key: str, interval: tuple[float, float]):
    words = page_words(svg_dir, page)
    mine = words[key]
    boxes = [_box(s) for _k, s in mine]
    x0, y0 = min(b[0] for b in boxes) - 9, min(b[1] for b in boxes) - 10
    x1, y1 = max(b[2] for b in boxes) + 9, max(b[3] for b in boxes) + 9
    region = (x0, y0, x1, y1)
    others = [s for k2, w in words.items() if k2 != key for _k, s in w]
    m_mine, m_oth = mask(region, [s for _k, s in mine]), mask(region, others)
    base = np.full(m_mine.shape + (3,), 255, np.uint8)
    base[m_oth] = GREY
    base[m_mine] = INK
    plain = base.copy()
    painted = base.copy()
    body = mask(region, [s for k, s in mine if k == 'body'])
    a, b = int((interval[0] - x0) * SC), int((interval[1] - x0) * SC)
    cols = np.zeros_like(body)
    cols[:, max(0, a):max(0, min(body.shape[1], b))] = True
    painted[body & cols] = PAINT
    if painted.shape[1] > 1500:
        k = 1500 / painted.shape[1]
        plain = cv2.resize(plain, None, fx=k, fy=k, interpolation=cv2.INTER_AREA)
        painted = cv2.resize(painted, None, fx=k, fy=k, interpolation=cv2.INTER_AREA)
    gap = np.full((plain.shape[0], 8, 3), 120, np.uint8)
    return np.hstack([plain, gap, painted])


def planted_interval(row: dict, rng: random.Random, kind: str) -> tuple[float, float]:
    a, b = row['x']
    w = b - a
    if kind == 'shift':
        d = w * rng.choice([-1.3, 1.3])
        return a + d, b + d
    c = (a + b) / 2
    return c - 1.25 * w, c + 1.25 * w


def build(svg_dir: Path, out: Path, n: int, planted_n: int, seed: int) -> None:
    pool = []
    for f in sorted(AUDIT_DUMP.glob('*.json')):
        page = int(f.stem)
        if not (svg_dir / f'{page:03d}.svg').exists():
            continue
        for row in json.loads(f.read_text(encoding='utf-8')):
            if row['key'] in page_words(svg_dir, page):
                pool.append({'page': page, **row})
    rng = random.Random(seed)
    chosen = rng.sample(pool, n + planted_n)
    items = [{**r, 'planted': None} for r in chosen[:n]]
    for k, r in enumerate(chosen[n:]):
        items.append({**r, 'planted': 'shift' if k % 2 == 0 else 'wide'})
    rng.shuffle(items)
    for sub in ('sheets', 'results', 'truth'):
        (out / sub).mkdir(parents=True, exist_ok=True)
    cells, truth = [], {}
    for number, it in enumerate(items):
        it['id'] = f'l{number:04d}'
        interval = tuple(it['x']) if not it['planted'] else planted_interval(it, random.Random(seed + number), it['planted'])
        img = render(svg_dir, it['page'], it['key'], interval)
        header = np.full((18, img.shape[1], 3), 235, np.uint8)
        cv2.putText(header, it['id'], (4, 13), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)
        letters = [c for c in it['text'] if 'ء' <= c <= 'ي' or c in 'ٱٰ']
        cells.append((np.vstack([header, img]), {'id': it['id'], 'word': it['text'], 'rule': it['class'],
                                                 'target_letter': it['letter'], 'letter_number_from_right': it['j'] + 1,
                                                 'letters_of_the_word_from_right': letters}))
        truth[it['id']] = {k: it[k] for k in ('page', 'key', 'j', 'letter', 'class', 'planted')}
    for s in range(0, len(cells), PER_SHEET):
        chunk = cells[s:s + PER_SHEET]
        width = max(c.shape[1] for c, _ in chunk)
        canvas = np.full((sum(c.shape[0] + 6 for c, _ in chunk), width, 3), 255, np.uint8)
        y = 0
        for c, _ in chunk:
            canvas[y:y + c.shape[0], :c.shape[1]] = c
            y += c.shape[0] + 6
        name = f'sheet_{s // PER_SHEET:03d}'
        Image.fromarray(canvas).save(out / 'sheets' / f'{name}.png')
        (out / 'sheets' / f'{name}.json').write_text(json.dumps([m for _, m in chunk], ensure_ascii=False), encoding='utf-8')
    (out / 'truth' / 'truth.json').write_text(json.dumps({'seed': seed, 'n_real': n, 'pool': len(pool), 'items': truth}, ensure_ascii=False),
                                              encoding='utf-8')
    print(f'{len(items)} items ({n} real + {len(items) - n} planted) from a pool of {len(pool)} on {math.ceil(len(items) / PER_SHEET)} sheets')


def score(out: Path) -> None:
    truth = json.loads((out / 'truth' / 'truth.json').read_text(encoding='utf-8'))['items']
    verdicts = {}
    for f in sorted((out / 'results').glob('*.jsonl')):
        for line in f.read_text(encoding='utf-8').splitlines():
            if line.strip():
                row = json.loads(line)
                verdicts[row['id']] = row
    real = [i for i, t in truth.items() if t['planted'] is None and i in verdicts]
    planted = [i for i, t in truth.items() if t['planted'] and i in verdicts]
    bad = [i for i in real if verdicts[i]['verdict'] in BAD]
    unsure = [i for i in real if verdicts[i]['verdict'] == 'UNSURE']
    n = len(real)
    counts = {v: sum(1 for i in real if verdicts[i]['verdict'] == v) for v in ('OK',) + BAD + ('UNSURE',)}
    print(f'judged {len(verdicts)} of {len(truth)}; real letters {n}: {counts}')
    d = None
    if planted:
        for kind in ('shift', 'wide'):
            ps = [i for i in planted if truth[i]['planted'] == kind]
            print(f'  planted {kind}: caught {sum(1 for i in ps if verdicts[i]["verdict"] in BAD)}/{len(ps)}')
        d = sum(1 for i in planted if verdicts[i]['verdict'] in BAD) / len(planted)
        print(f'judge recall d = {d:.1%} on {len(planted)} planted errors')
    if n:
        p = len(bad) / n
        print(f'flagged rate {p:.1%}  (95% one-sided upper bound {clopper_pearson_upper(len(bad), n):.1%}); unsure {len(unsure)}')
        if d:
            print(f'corrected for judge recall: ~{min(1.0, p / d):.1%} of painted letters wrong')
    by_class = {}
    for i in real:
        c = truth[i]['class']
        by_class.setdefault(c, [0, 0])
        by_class[c][0] += 1
        by_class[c][1] += i in bad
    for c, (t, b) in sorted(by_class.items(), key=lambda kv: -kv[1][0]):
        print(f'  {c:22s} {b}/{t} flagged')
    (out / 'flagged.json').write_text(json.dumps([{'id': i, **truth[i], 'verdict': verdicts[i]['verdict'], 'note': verdicts[i].get('note', '')}
                                                  for i in bad], ensure_ascii=False, indent=1), encoding='utf-8')


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('cmd', choices=['build', 'score'])
    ap.add_argument('--out', required=True, type=Path)
    ap.add_argument('--svg-dir', type=Path)
    ap.add_argument('--n', type=int, default=400)
    ap.add_argument('--planted', type=int, default=70)
    ap.add_argument('--seed', type=int, default=20261110)
    a = ap.parse_args()
    build(a.svg_dir, a.out, a.n, a.planted, a.seed) if a.cmd == 'build' else score(a.out)
