#!/usr/bin/env python3
"""Check «المدينة الجديد» against the pause signs printed on the QVP pages.

The reader draws the quran-engine QVP pages (KFGQPC Madani v4, 1441 AH) and
treats their printed signs as «المدينة الجديد» (frontend/lib/qvp.ts
QVP_PRINTED_WAQF_SOURCE), overlaying only where another print differs. So
the DB column must match the ink exactly.

    python3 pipeline/audit_qvp_waqf.py            # refresh data/qvp_waqf_ink.json, then compare
    python3 pipeline/audit_qvp_waqf.py --offline  # compare against the committed ink file only

Refreshing downloads the 604 pages of the pinned release (data/qvp_upstream.json)
into artifacts/qvp-pages/<release>/, checks every file's size against the CDN,
and extracts the signs with the reader's own decoder. Re-run after bumping the
QVP release. tests/test_qvp_waqf_ink.py runs the offline comparison.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PIN = ROOT / 'data' / 'qvp_upstream.json'
INK = ROOT / 'data' / 'qvp_waqf_ink.json'
DB = ROOT / 'data' / 'mushaf_waqf.db'
SCRIPT_DB = ROOT / 'data' / 'quran_script.db'
COLUMN = 'المدينة الجديد'


def _fetch(url: str, dest: Path) -> None:
    for _ in range(5):
        with urllib.request.urlopen(url, timeout=120) as resp:
            want = int(resp.headers.get('Content-Length') or 0)
            body = resp.read()
        if want and len(body) == want:
            dest.write_bytes(body)
            return
    raise SystemExit(f'{url}: incomplete download after 5 tries')


def refresh_ink() -> dict:
    pin = json.loads(PIN.read_text(encoding='utf-8'))['pages']
    release, cdn = pin['release'], pin['cdn']
    pages = ROOT / 'artifacts' / 'qvp-pages' / release
    pages.mkdir(parents=True, exist_ok=True)
    todo = [n for n in range(1, 605) if not (pages / f'{n:03d}.qvp').exists()]
    with ThreadPoolExecutor(8) as pool:
        list(pool.map(lambda n: _fetch(f'{cdn}/{release}/{n:03d}.qvp', pages / f'{n:03d}.qvp'), todo))
    out = subprocess.run(
        ['node', '--experimental-strip-types', '--no-warnings',
         str(ROOT / 'scripts' / 'qvp_extract_marks.ts'), str(pages)],
        check=True, capture_output=True, text=True,
    ).stdout
    ink = {'release': release, 'marks': json.loads(out)}
    INK.write_text(json.dumps(ink, ensure_ascii=False, sort_keys=True, indent=0) + '\n', encoding='utf-8')
    return ink


def compare(ink: dict) -> list[tuple]:
    """(surah, ayah, token, word, ink marks, DB marks) for every disagreement."""
    script = sqlite3.connect(SCRIPT_DB)
    words = {}
    for key, text in script.execute('SELECT word_key, text FROM words'):
        s, a, p = map(int, key.split(':'))
        words[(s, a, p)] = text
    hizb = {(s, a) for (s, a, p), t in words.items() if p == 1 and t.strip() == '۞'}

    # QVP numbers words without the ۞; token_index counts it.
    printed = {}
    for key, marks in ink['marks'].items():
        s, a, w = map(int, key.split(':'))
        printed[(s, a, w + ((s, a) in hizb))] = set(marks)
    conn = sqlite3.connect(DB)
    stored = {
        (s, a, t): {m.strip() for m in v.split(',') if m.strip()}
        for s, a, t, v in conn.execute(
            f'SELECT السورة, الآية, token_index, "{COLUMN}" FROM waqf WHERE coalesce("{COLUMN}","") <> ""')
    }
    return [(*k, words.get(k), sorted(printed.get(k, ())), sorted(stored.get(k, ())))
            for k in sorted(set(printed) | set(stored)) if printed.get(k, set()) != stored.get(k, set())]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--offline', action='store_true', help='use the committed ink file')
    args = ap.parse_args(argv)
    ink = json.loads(INK.read_text(encoding='utf-8')) if args.offline else refresh_ink()
    diffs = compare(ink)
    print(f'QVP {ink["release"]}: {len(ink["marks"])} words carry printed signs; '
          f'{len(diffs)} differ from «{COLUMN}»')
    for s, a, t, word, want, have in diffs:
        print(f'  {s}:{a} token {t} «{word}»: ink {"".join(want) or "—"}, DB {"".join(have) or "—"}')
    return 1 if diffs else 0


if __name__ == '__main__':
    sys.exit(main())
