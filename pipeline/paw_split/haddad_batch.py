"""Split a run of «الكويت (الحداد)» pages in order: each page starts at the word after the previous page's
last verse (its 'next_start'). The first page's start is the stream index of its first verse.

    python3 pipeline/paw_split/haddad_batch.py 4 30 --start-ayah 2:5
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TRACE = ROOT / 'artifacts' / 'haddad-trace'


def main(argv):
    first, last = int(argv[0]), int(argv[1])
    stream = json.load(open(ROOT / 'artifacts' / 'haddad' / 'stream.json'))
    if '--start-ayah' in argv:
        s, a = map(int, argv[argv.index('--start-ayah') + 1].split(':'))
        start = next(k for k, w in enumerate(stream) if w[2] == s and w[3] == a)
    else:
        start = json.load(open(TRACE / f'paw-words-{first - 1:03d}.json'))['next_start']
    for p in range(first, last + 1):
        env = dict(os.environ, HADDAD_START=str(start))
        r = subprocess.run([sys.executable, str(ROOT / 'pipeline' / 'paw_split' / 'haddad_split.py'), str(p)],
                           env=env, capture_output=True, text=True)
        out = TRACE / f'paw-words-{p:03d}.json'
        if r.returncode or not out.exists():
            print(f'page {p}: failed\n{r.stderr[-800:]}')
            return 1
        d = json.load(open(out))
        c = d['checks']
        flags = {k: v for k, v in c.items() if v and k not in ('moves', 'blue_pieces', 'blue_unowned', 'unclaimed_bodies')}
        rings = sum(w['ring'] for w in d['words'])
        print(f"page {p}: {d['first_ayah'][0]}:{d['first_ayah'][1]}–{d['last_ayah'][0]}:{d['last_ayah'][1]}{'+' if d['ends_in_verse'] else ''} {'' if d['inferred'] else 'NOT-INFERRED '}"
              f"rings {rings} words {sum(not w['ring'] for w in d['words'])} unclaimed {len(c['unclaimed_bodies'])}"
              + (f' FLAGS {flags}' if flags else ''))
        start = d['next_start']
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
