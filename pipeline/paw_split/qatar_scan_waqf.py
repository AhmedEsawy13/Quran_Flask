"""Waqf signs on the split Qatar scan pages (qatar_scan_split.py), read word by word with the shipped waqf model
(mesaha_waqf.page_signs, the reader used for both Mesaha prints), and compared with the «قطر» column.

    python3 pipeline/paw_split/qatar_scan_waqf.py signs 50 51 ...     # -> artifacts/qatar-scan/waqf-NNN.json
    python3 pipeline/paw_split/qatar_scan_waqf.py compare 50 51 ...   # reading vs «قطر» on words any print marks
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from pipeline.paw_split._common import ROOT  # noqa: E402

WORK = ROOT / 'artifacts' / 'qatar-scan'
SCRIPT_DB = ROOT / 'data' / 'mushaf-bahrain-layout.db'     # the Qatar layout's word ids; word n of a verse = waqf position n
HAFS = ['المدينة الجديد', 'المدينة القديم', 'المدينة ١٤٢٧', 'الشمرلي', 'الأزهر', 'قطر', 'الكويت', 'البحرين', 'المساحة']


def columns() -> dict:
    clean = lambda v: '' if (v or '').strip() in ('', 'ركوع') else v.strip()  # noqa: E731
    db = sqlite3.connect(ROOT / 'data' / 'mushaf_waqf.db')
    q = 'SELECT "السورة", "الآية", word_index, ' + ', '.join(f'"{c}"' for c in HAFS) + ' FROM waqf'
    return {(r[0], r[1], r[2]): dict(zip(HAFS, map(clean, r[3:]))) for r in db.execute(q)}


def read_signs(pages: list[int]) -> None:
    import cv2
    from pipeline.cv_waqf.classify import GlyphClassifier
    from pipeline.paw_split import mesaha_waqf as mw
    clf = GlyphClassifier(mw.MODEL)
    assert clf.ready
    key_of = dict(sqlite3.connect(SCRIPT_DB).execute('SELECT word_index, word_key FROM words'))
    real = cv2.imread

    def imread(path, flags=None):          # page_signs opens the Mesaha page: hand it the Qatar scan
        p = str(path)
        if '/data/cv/pages/mesaha/' in p:
            p = str(ROOT / 'data' / 'cv' / 'pages' / 'qatar' / Path(p).name.replace('_w1600.jpg', '_w2000.jpg'))
        return real(p, flags) if flags is not None else real(p)
    old = Path.cwd()
    os.chdir(WORK)
    mw.cv2.imread = imread
    # page_signs looks hints up by Mesaha printed position; the comparison below uses the Qatar keys instead
    mw.printed_position = lambda db, s, a, n: None
    mw.X_HI_FRAC = 1.0                     # Qatar sets some signs over the middle or start of the word
    mw.ALIF_GAP = 0.12                     # ... and close over a final alif (98.0% vs 96.7% on the 20-page pilot)
    try:
        for page in pages:
            res = mw.page_signs(page, clf, key_of, {})
            (WORK / f'waqf-{page:03d}.json').write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding='utf-8')
            print(page, 'signs', len(res['signs']), flush=True)
    finally:
        mw.cv2.imread = real
        os.chdir(old)


def compare(pages: list[int]) -> dict:
    """On every word some Hafs print marks: the sign read (1924 review rules) against «قطر»."""
    from pipeline.paw_split.mesaha_waqf_review import counts
    cols = columns()
    key_of = dict(sqlite3.connect(SCRIPT_DB).execute('SELECT word_index, word_key FROM words'))
    same, diffs = 0, []
    for page in pages:
        d = json.load(open(WORK / f'paw-words-{page:03d}.json', encoding='utf-8'))
        signs = {r['word_index']: r for r in json.load(open(WORK / f'waqf-{page:03d}.json', encoding='utf-8'))['signs']}
        for w in d['words']:
            k = key_of.get(w['word_index'])
            if w['ring'] or not k:
                continue
            s, a, n = map(int, k.split(':'))
            hint = {c: v for c, v in cols.get((s, a, n), {}).items() if v}
            if not hint:
                continue
            r = signs.get(w['word_index'])
            read = r['sign'] if r and counts(r, {c: v for c, v in hint.items() if c != 'قطر'}) else ''
            col = hint.get('قطر', '')
            if read == col:
                same += 1
            else:
                diffs.append({'page': page, 'key': k, 'text': w['text'], 'word_index': w['word_index'], 'line': w['line'],
                              'qatar': col, 'read': read, 'conf': r['conf'] if r else None, 'r': r,
                              'others': {c: v for c, v in hint.items() if c != 'قطر'}})
    return {'same': same, 'diffs': diffs}


def main(argv: list[str]) -> int:
    cmd, pages = argv[0], [int(x) for x in argv[1:]]
    if cmd == 'signs':
        read_signs(pages)
    elif cmd == 'compare':
        r = compare(pages)
        n = r['same'] + len(r['diffs'])
        print(f"words any print marks: {n} · reading = «قطر» {r['same']} ({100 * r['same'] / max(1, n):.1f}%) · differ {len(r['diffs'])}")
        print(Counter(f"{x['qatar'] or '-'}→{x['read'] or '-'}" for x in r['diffs']).most_common(12))
        (WORK / 'compare.json').write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding='utf-8')
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
