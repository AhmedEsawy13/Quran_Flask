"""Split a run of «الكويت (الحداد)» pages in order: each page starts at the word after the previous page's
last verse (its 'next_start'). The first page's start is the stream index of its first verse.

    python3 pipeline/paw_split/haddad_batch.py 4 30 --start-ayah 2:5
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TRACE = ROOT / 'artifacts' / 'haddad-trace'


def serious(d) -> list:
    """problems that would shift every later page: no line-break alignment, banners that do not match the
    surahs, or several words with no ink"""
    out = []
    if not d.get('inferred', True):
        out.append('not inferred')
    if d.get('banner_mismatch'):
        out.append('banner mismatch')
    if len(d['checks'].get('words_without_ink', [])) > 3:
        out.append(f"{len(d['checks']['words_without_ink'])} words without ink")
    return out


def main(argv):
    first, last = int(argv[0]), int(argv[1])
    stream = json.load(open(ROOT / 'artifacts' / 'haddad' / 'stream.json'))
    if '--start-ayah' in argv:
        s, a = map(int, argv[argv.index('--start-ayah') + 1].split(':'))
        start = next(k for k, w in enumerate(stream) if w[2] == s and w[3] == a)
    else:
        start = json.load(open(TRACE / f'paw-words-{first - 1:03d}.json'))['next_start']
    log = open(TRACE / 'batch.log', 'a')
    for p in range(first, last + 1):
        scan = ROOT / 'artifacts' / 'haddad' / 'pages' / f'p{p:03d}.jpg'
        while True:                                   # the download may still be running: wait for a size that holds
            if scan.exists() and scan.stat().st_size > 50_000:
                size = scan.stat().st_size
                time.sleep(4)
                if scan.stat().st_size == size:
                    break
            time.sleep(15)
        best = None
        for th in ('0.52', '0.6', '0.47'):          # a flagged page is retried with other ring thresholds
            env = dict(os.environ, HADDAD_START=str(start), RING_TH=th)
            r = subprocess.run([sys.executable, str(ROOT / 'pipeline' / 'paw_split' / 'haddad_split.py'), str(p)],
                               env=env, capture_output=True, text=True)
            out = TRACE / f'paw-words-{p:03d}.json'
            if r.returncode or not out.exists():
                time.sleep(10)                        # once more: a scan written while it was read
                r = subprocess.run([sys.executable, str(ROOT / 'pipeline' / 'paw_split' / 'haddad_split.py'), str(p)],
                                   env=env, capture_output=True, text=True)
            if r.returncode or not out.exists():
                print(f'page {p}: failed\n{r.stderr[-800:]}')
                return 1
            d = json.load(open(out))
            bad = serious(d)
            if best is None or len(bad) < len(best[1]):
                best = (d, bad, th, open(out).read())
            if not bad:
                break
        d, bad, th, raw = best
        (TRACE / f'paw-words-{p:03d}.json').write_text(raw)
        c = d['checks']
        flags = {k: v for k, v in c.items() if v and k not in ('moves', 'blue_pieces', 'blue_unowned', 'unclaimed_bodies')}
        rings = sum(w['ring'] for w in d['words'])
        line = (f"page {p}: {d['first_ayah'][0]}:{d['first_ayah'][1]}–{d['last_ayah'][0]}:{d['last_ayah'][1]}"
                f"{'+' if d['ends_in_verse'] else ''} rings {rings} words {sum(not w['ring'] for w in d['words'])}"
                f" headers {[h[0][0] + str(h[3]) for h in d.get('headers', [])]} th {th}"
                + (f' FLAGS {flags}' if flags else '') + (f' SERIOUS {bad}' if bad else ''))
        print(line, flush=True)
        log.write(line + '\n'); log.flush()
        if bad:
            print(f'stopping at page {p}: fix it, then resume with: haddad_batch.py {p} {last} --start-ayah '
                  f"{d['first_ayah'][0]}:{d['first_ayah'][1]} (if it starts a verse) or from page {p - 1}'s next_start")
            return 2
        start = d['next_start']
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
