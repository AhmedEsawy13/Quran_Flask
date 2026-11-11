"""Build data/mushaf-kuwait-haddad-layout.db («الكويت (الحداد)», 662 pages) from the split pages
(artifacts/haddad-trace/paw-words-NNN.json), in the schema of the other layout DBs (qpc-v1-15-lines.db):
pages(page_number, line_number, line_type, is_centered, first_word_id, last_word_id, surah_number), with
Digital Khatt word ids (verse numbers included), so the editor reads it like البحرين's.

Lines are numbered top to bottom: surah banner, basmala and text lines as printed. A text line is centred
when its ink spans under 80% of the text width (a surah's last short line). Pages 2-3 (الفاتحة, البقرة 1-4,
in ornamental frames) come from PRESET below, read off the scan.

    python3 pipeline/paw_split/haddad_layout_db.py            # -> data/mushaf-kuwait-haddad-layout.db
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TRACE = ROOT / 'artifacts' / 'haddad-trace'
OUT = ROOT / 'data' / 'mushaf-kuwait-haddad-layout.db'
PAGES = range(2, 663)
CENTRED = 0.8
# The two opening pages, read off the scan: tokens per printed line (verse numbers counted), in stream order
# from الفاتحة's first word. p2: banner, then 1:1 (the basmala is its verse 1) .. 1:7 on six lines; p3: banner,
# basmala, 2:1-4 on five lines.
OPENING = {2: [('surah_name', 1), 5, 8, 7, 6, 5, 5], 3: [('surah_name', 2), ('basmallah', 2), 8, 6, 6, 6, 6]}


def _opening() -> dict:
    stream = json.load(open(ROOT / 'artifacts' / 'haddad' / 'stream.json'))
    out, k = {}, 0
    for p, spec in OPENING.items():
        rows = []
        for item in spec:
            if isinstance(item, tuple):
                rows.append((item[0], None, None, item[1] if item[0] == 'surah_name' else None, 1))
            else:
                rows.append(('ayah', stream[k][0], stream[k + item - 1][0], None, 1))
                k += item
        out[p] = rows
    assert stream[k][2:] == [2, 5], stream[k]          # p4 opens at 2:5
    return out


PRESET: dict[int, list] = {}


def page_lines(p: int) -> list[tuple]:
    if p in PRESET:
        return PRESET[p]
    d = json.load(open(TRACE / f'paw-words-{p:03d}.json'))
    words = d['words']
    xs = [w for w in words if w.get('pieces')]
    left, right = min(w['x0'] for w in xs), max(w['x1'] for w in xs)
    rows = []
    for li, (a, b) in enumerate(d['bands'], 1):
        ws = [w for w in words if w['line'] == li]
        if not ws:
            continue
        span = max(w['x1'] for w in ws if w.get('pieces') or w['ring']) - min(w['x0'] for w in ws if w.get('pieces') or w['ring'])
        # 37:182's verse number has a made-up id in the export (90037182; no slot between 62233 and 62234):
        # the other layouts end that line on 62233, so ids past the word map are skipped
        ids = [w['word_index'] for w in ws if w['word_index'] <= 83668]
        rows.append(((a + b) / 2, ('ayah', min(ids), max(ids), None, int(span < CENTRED * (right - left)))))
    for kind, y0, y1, su in d.get('headers', []):
        rows.append(((y0 + y1) / 2, (kind, None, None, su if kind == 'surah_name' else None, 1)))
    return [r for _, r in sorted(rows, key=lambda t: t[0])]


def main() -> int:
    PRESET.update(_opening())
    missing = [p for p in PAGES if p not in PRESET and not (TRACE / f'paw-words-{p:03d}.json').exists()]
    if missing:
        print(f'{len(missing)} pages not split yet, e.g. {missing[:10]}')
    tmp = OUT.with_suffix('.tmp')
    tmp.unlink(missing_ok=True)
    db = sqlite3.connect(tmp)
    db.execute('CREATE TABLE pages (page_number INTEGER, line_number INTEGER, line_type TEXT, is_centered INTEGER, '
               'first_word_id INTEGER, last_word_id INTEGER, surah_number INTEGER)')
    db.execute('CREATE TABLE info (name TEXT, number_of_pages INTEGER, lines_per_page INTEGER, font_name TEXT)')
    db.execute("INSERT INTO info VALUES ('مصحف دولة الكويت بخط محمد سعد الحداد ١٤٢١', 662, 13, 'Digital Khatt')")
    prev_last = None
    gaps = []
    for p in PAGES:
        if p in missing:
            continue
        for n, (kind, a, b, su, centred) in enumerate(page_lines(p), 1):
            db.execute('INSERT INTO pages VALUES (?,?,?,?,?,?,?)', (p, n, kind, centred, a, b, su))
            if kind == 'ayah':
                if prev_last is not None and a != prev_last + 1:
                    gaps.append((p, n, prev_last, a))
                prev_last = b
    db.commit()
    db.close()
    tmp.replace(OUT)
    print(f'wrote {OUT.name}: {len(PAGES) - len(missing)} pages; word-id gaps between lines: {gaps[:10]}{" ..." if len(gaps) > 10 else ""} ({len(gaps)})')
    return 0


if __name__ == '__main__':
    sys.exit(main())
