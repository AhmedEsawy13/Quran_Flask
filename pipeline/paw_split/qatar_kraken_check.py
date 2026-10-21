"""How well do Kraken's word gaps (its emitted spaces) match the verified word boundaries of a page?

For each line: Kraken's space x positions (mapped back to page px) vs the boundaries of the
letter-group split (the midpoint between neighbouring words' ink extents, verse rings included).
Reports per line the words read, spaces found, and boundaries matched within a tolerance."""
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))
from pipeline.paw_split._common import ROOT, QATAR_APP_ASSETS, workdir  # noqa: E402
workdir('qatar-attach')

import json
import sys

import numpy as np

PAGE = int(sys.argv[1]) if len(sys.argv) > 1 else 33
meta = {m['name']: m for m in json.load(open('kraken_crops/meta.json'))}
kr = json.load(open('kraken_crops/kraken_out.json'))
d = json.load(open(f'paw-words-{PAGE:03d}.json'))
spacing = float(np.median(np.diff([(a + b) / 2 for a, b in d['bands']])))
TOL = 0.25 * spacing

total_b = matched_b = total_sp = useful_sp = 0
spaces_by_line = {}
for name, r in sorted(kr.items()):
    m = meta[name]
    li = m['line']
    xs = [m['x0'] + x / m['scale'] for ch, x in zip(r['pred'], r['x']) if ch == ' ']
    spaces_by_line[li] = xs
    words = sorted((w for w in d['words'] if w['line'] == li and w['x1'] > 0), key=lambda w: -w['x1'])
    bounds = [(a['x0'] + b['x1']) / 2 for a, b in zip(words, words[1:])]
    hit = sum(any(abs(s - b) <= TOL for s in xs) for b in bounds)
    good_sp = sum(any(abs(s - b) <= TOL for b in bounds) for s in xs)
    total_b += len(bounds); matched_b += hit; total_sp += len(xs); useful_sp += good_sp
    print(f'line {li:2d}: {len(words):2d} words · {len(bounds):2d} boundaries · Kraken spaces {len(xs):2d} · '
          f'boundaries matched {hit:2d} · spaces on a boundary {good_sp:2d} · read: {r["pred"][:60]}')
print(f'\nboundaries matched by a Kraken space: {matched_b}/{total_b} ({matched_b / max(1, total_b):.0%}) · '
      f'Kraken spaces that sit on a real boundary: {useful_sp}/{total_sp} ({useful_sp / max(1, total_sp):.0%}) · '
      f'tolerance {TOL:.0f}px')
json.dump({str(k): v for k, v in spaces_by_line.items()}, open(f'kraken-spaces-{PAGE:03d}.json', 'w'))
