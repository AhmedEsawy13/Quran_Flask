"""Whole-book run for the two prints that follow the old Madinah 1405 signs: Wathiq Billah and Sheikh Maktoum.

    python3 pipeline/paw_split/book_run.py fetch   wathiq|maktoom [first last]
    python3 pipeline/paw_split/book_run.py split   wathiq|maktoom [--jobs N] [first last]
    python3 pipeline/paw_split/book_run.py waqf    wathiq|maktoom
    python3 pipeline/paw_split/book_run.py compare wathiq|maktoom
    python3 pipeline/paw_split/book_run.py pack    wathiq|maktoom     # -> data/cloud_runs/<book>/ (to commit)
    python3 pipeline/paw_split/book_run.py all     wathiq|maktoom [--jobs N]

Each step skips pages it already has, so a stopped run resumes. Needs opencv, numpy, scipy only: word text
comes from data/refs/madinah_dk_words.json.gz, line breaks from data/qpc-v1-15-lines.db, the reference signs
from the «المدينة القديم» column of data/mushaf_waqf.db.
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
import urllib.request
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from pipeline.paw_split._common import dk_page  # noqa: E402

HERE = Path(__file__).resolve().parent
PAGES = range(1, 605)
BOOKS = {
    # scan N = printed page + 4 (tafsir.app serves 1779x2274 JPGs)
    'wathiq': dict(pages=ROOT / 'artifacts' / 'tafsir-app' / 'alwathiq', trace=ROOT / 'artifacts' / 'wathiq-trace',
                   url=lambda p: f'https://tafsir.app/scans/m-alwathiq/{p + 4}.jpg',
                   split=[HERE / 'wathiq_batch.py'], waqf=HERE / 'wathiq_waqf.py',
                   # the sakta's small س is printed red (like the other small letters), not blue: the
                   # blue-sign reader cannot see it (checked by eye: 18:1, 69:28, 75:27, 83:14)
                   red_sakta=True),
    # archive.org leaf n{page-1} at full size (4967x7017); the split works at 1779 px
    'maktoom': dict(pages=ROOT / 'artifacts' / 'maktoom' / 'pages', trace=ROOT / 'artifacts' / 'maktoom-trace',
                    url=lambda p: f'https://archive.org/download/356835683586MAKTOOM/page/n{p - 1}.jpg',
                    split=[HERE / 'maktoom_split.py'], waqf=HERE / 'maktoom_waqf.py'),
}
REF = 'المدينة القديم'


def _range(args):
    nums = [int(a) for a in args if a.isdigit()]
    return range(nums[0], nums[1] + 1) if len(nums) == 2 else PAGES


def _jobs(args):
    return int(args[args.index('--jobs') + 1]) if '--jobs' in args else max(1, (os.cpu_count() or 2) - 1)


def fetch(book, args):
    b = BOOKS[book]
    b['pages'].mkdir(parents=True, exist_ok=True)
    failed = []
    for p in _range(args):
        out = b['pages'] / f'p{p:03d}.jpg'
        if out.exists() and out.stat().st_size > 10_000:
            continue
        for attempt in range(4):
            try:
                req = urllib.request.Request(b['url'](p), headers={'User-Agent': 'Mozilla/5.0 (research; Quran waqf study)'})
                data = urllib.request.urlopen(req, timeout=120).read()
                if len(data) < 10_000:
                    raise ValueError(f'{len(data)} bytes')
                out.write_bytes(data)
                break
            except Exception as e:                       # noqa: BLE001 - retry any network error
                if attempt == 3:
                    failed.append((p, str(e)))
                time.sleep(5 * (attempt + 1))
        time.sleep(0.5)                                  # polite to both hosts
        if p % 50 == 0:
            print('fetched to', p, flush=True)
    print('fetch done; failed:', failed or 'none')


def split(book, args):
    b = BOOKS[book]
    b['trace'].mkdir(parents=True, exist_ok=True)
    # write every page's layout cache first: parallel splits read their neighbours' caches
    for p in PAGES:
        cache = b['trace'] / f'layout-{p:03d}.json'
        if not cache.exists():
            cache.write_text(json.dumps(dk_page(p), ensure_ascii=False))
    todo = [p for p in _range(args) if (b['pages'] / f'p{p:03d}.jpg').exists()
            and not (b['trace'] / f'paw-words-{p:03d}.json').exists()]
    print(book, 'split', len(todo), 'pages,', _jobs(args), 'jobs', flush=True)
    errors = {}

    def one(p):
        r = subprocess.run([sys.executable, *map(str, b['split']), str(p)], capture_output=True, text=True, cwd=ROOT)
        if r.returncode:
            errors[p] = r.stderr.strip().splitlines()[-1:] or ['exit %d' % r.returncode]
        return p

    with ThreadPoolExecutor(_jobs(args)) as ex:
        for n, p in enumerate(ex.map(one, todo), 1):
            if n % 25 == 0:
                print('split', n, '/', len(todo), flush=True)
    log = b['trace'] / 'split-errors.json'
    old = json.loads(log.read_text()) if log.exists() else {}
    old = {k: v for k, v in old.items() if not (b['trace'] / f'paw-words-{int(k):03d}.json').exists()}
    old.update({str(k): v for k, v in errors.items()})
    log.write_text(json.dumps(old, ensure_ascii=False, indent=1))
    print('split errors:', len(old))


def waqf(book, args):
    b = BOOKS[book]
    todo = sorted(int(f.name[10:13]) for f in b['trace'].glob('paw-words-*.json')
                  if not (b['trace'] / f'waqf-{f.name[10:13]}.json').exists())
    for i in range(0, len(todo), 50):               # one model load per 50 pages
        subprocess.run([sys.executable, str(b['waqf']), *map(str, todo[i:i + 50])], check=True, cwd=ROOT)


def _keys():
    """global layout word id -> 'surah:ayah:position' (verse rings excluded), as maktoom_waqf.layout_keys"""
    meta = {}
    for p in PAGES:
        for line in dk_page(p)['lines']:
            for w in line['words']:
                if not w['text'].startswith('۝'):
                    meta[w['word_index']] = (w['surah'], w['ayah'])
    by = defaultdict(list)
    for i in sorted(meta):
        by[meta[i]].append(i)
    return {i: f'{k[0]}:{k[1]}:{n}' for k, ids in by.items() for n, i in enumerate(ids, 1)}


OTHERS = ['المدينة الجديد', 'المدينة ١٤٢٧', 'الشمرلي', 'الأزهر', 'قطر', 'الكويت', 'البحرين']


def _reference():
    """key -> (old Madinah sign, does any other Hafs print mark this word)"""
    clean = lambda v: '' if (v or '').strip() in ('', 'ركوع') else v.strip()
    db = sqlite3.connect(ROOT / 'data' / 'mushaf_waqf.db')
    q = f'SELECT السورة, الآية, word_index, "{REF}", ' + ', '.join(f'"{c}"' for c in OTHERS) + ' FROM waqf'
    return {f'{r[0]}:{r[1]}:{r[2]}': (clean(r[3]), any(clean(v) for v in r[4:])) for r in db.execute(q)}


def compare(book, args):
    """Every sign the print shows vs the old Madinah column: same / other symbol / print only / not found.
    Differences (not noise) go to compare-diffs.json for review."""
    b = BOOKS[book]
    key_of, ref = _keys(), _reference()
    rows, stats = [], Counter()
    pages = sorted(int(f.name[5:8]) for f in b['trace'].glob('waqf-*.json'))
    for p in pages:
        d = json.loads((b['trace'] / f'paw-words-{p:03d}.json').read_text())
        found = {}
        for s in json.loads((b['trace'] / f'waqf-{p:03d}.json').read_text())['signs']:
            k = key_of.get(s['word_index'])
            if k and (k not in found or s['conf'] > found[k]['conf']):
                found[k] = s
        page_keys = {key_of[w['word_index']] for w in d['words'] if not w['ring'] and w['word_index'] in key_of}
        for k in sorted(page_keys, key=lambda t: tuple(map(int, t.split(':')))):
            (col, elsewhere), s = ref.get(k, ('', False)), found.get(k)
            if not col and not s:
                continue
            got = s['sign'] if s else ''
            kind = 'same' if got == col else 'missed' if not got else 'print_only' if not col else 'other_symbol'
            if b.get('red_sakta') and 'س' in col.split(','):
                rest = ','.join(c for c in col.split(',') if c != 'س')
                if got == rest:
                    kind = 'sakta_red'   # the rest matches; the sakta itself is red ink the reader skips
            # the reader fires on vowels and hamzas too: a sign no print has at this word is noise unless
            # it is very sure; only those and signs another print shares are worth a look
            if kind == 'print_only' and not (elsewhere or s['conf'] >= 0.999):
                kind = 'print_only_noise'
            stats[kind] += 1
            if kind not in ('same', 'print_only_noise', 'sakta_red'):
                rows.append({'page': p, 'key': k, 'text': s['text'] if s else '', 'old_madinah': col,
                             'read': got, 'conf': s['conf'] if s else None, 'kind': kind})
    errs = json.loads((b['trace'] / 'split-errors.json').read_text()) if (b['trace'] / 'split-errors.json').exists() else {}
    flags = []
    for p in pages:
        c = json.loads((b['trace'] / f'paw-words-{p:03d}.json').read_text()).get('checks', {})
        n = sum(len(c.get(k, [])) for k in ('words_without_ink', 'unclaimed_bodies', 'forced_lines'))
        if n:
            flags.append(p)
    summary = {'book': book, 'pages_done': len(pages), 'split_errors': sorted(map(int, errs)),
               'pages_with_split_flags': flags, 'signs': dict(stats),
               'by_pair': Counter(f"{r['old_madinah'] or '-'}->{r['read'] or '-'}" for r in rows).most_common()}
    (b['trace'] / 'compare-summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=1))
    (b['trace'] / 'compare-diffs.json').write_text(json.dumps(rows, ensure_ascii=False, indent=1))
    print(json.dumps({k: v for k, v in summary.items() if k != 'pages_with_split_flags'}, ensure_ascii=False),
          '\npages with split flags:', len(flags), '· differences:', len(rows))


def pack(book, args):
    """Copy what the Mac needs back (word boxes, signs, comparison) to data/cloud_runs/<book>/ for git."""
    b = BOOKS[book]
    out = ROOT / 'data' / 'cloud_runs' / book
    out.mkdir(parents=True, exist_ok=True)
    for pat in ('paw-words-*.json', 'waqf-*.json', 'compare-*.json', 'split-errors.json'):
        for f in b['trace'].glob(pat):
            shutil.copy2(f, out / f.name)
    # sign crops of every difference, so the review needs no page images
    diffs = json.loads((b['trace'] / 'compare-diffs.json').read_text())
    crops = out / 'diff-crops'
    crops.mkdir(exist_ok=True)
    import cv2
    for r in diffs:
        if r['kind'] == 'missed':
            continue
        p = r['page']
        for s in json.loads((b['trace'] / f'waqf-{p:03d}.json').read_text())['signs']:
            if s['text'] == r['text'] and s['sign'] == r['read']:
                img = cv2.imread(str(b['pages'] / f'p{p:03d}.jpg'))
                d = json.loads((b['trace'] / f'paw-words-{p:03d}.json').read_text())
                W = d.get('width') or 1779
                k = img.shape[1] / W
                cx, cy = (s.get('cx'), s.get('cy')) if 'cx' in s else ((s['box'][0] + s['box'][2]) / 2, (s['box'][1] + s['box'][3]) / 2)
                R = 90
                x0, y0 = int(max(0, (cx - R) * k)), int(max(0, (cy - R) * k))
                crop = img[y0:int((cy + R) * k), x0:int((cx + R) * k)]
                if crop.size:
                    cv2.imwrite(str(crops / f"{r['key'].replace(':', '-')}.jpg"),
                                cv2.resize(crop, (2 * R, int(2 * R * crop.shape[0] / max(1, crop.shape[1])))))
                break
    print('packed', book, '->', out.relative_to(ROOT))


def main(argv):
    step, book, rest = argv[0], argv[1], argv[2:]
    assert book in BOOKS, f'book is one of {list(BOOKS)}'
    steps = ['fetch', 'split', 'waqf', 'compare', 'pack'] if step == 'all' else [step]
    for s in steps:
        globals()[s](book, rest)


if __name__ == '__main__':
    main(sys.argv[1:])
