"""Step 1 of the waqf plan: does attaching each detected sign to the word that OWNS its ink beat the
shipped seat-based attach? Same detections, same v7 classes (shipped.json from detect_page('قطر')).

A  shipped: kept marks as detect_page returns them
B  kept marks re-attached by ink ownership
C  kept + Azhar-rejected marks re-attached by ink ownership, then the Azhar check again
Scored per word against the قطر column of mushaf_waqf.db on the pages split (3-49)."""
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))
from pipeline.paw_split._common import ROOT, QATAR_APP_ASSETS, workdir  # noqa: E402
workdir('qatar-attach')

import json, sqlite3, sys, collections
import cv2, numpy as np
from pipeline.cv_waqf.azhar_prior import partition_marks_by_azhar_occupancy
from pipeline.cv_waqf.config import EDITIONS

APP = QATAR_APP_ASSETS
LAYOUT = f'{ROOT}/data/mushaf-bahrain-layout.db'
WAQF = f'{ROOT}/data/mushaf_waqf.db'
PRIOR = EDITIONS['قطر'].seat_prior_editions
key_of = dict(sqlite3.connect(LAYOUT).execute('SELECT word_index, word_key FROM words'))
column = {f'{s}:{a}:{w}': q.strip() for s, a, w, q in sqlite3.connect(WAQF).execute(
    'SELECT السورة, الآية, word_index, "قطر" FROM waqf WHERE "قطر" IS NOT NULL AND "قطر" != \'\'')}
shipped = json.load(open('shipped.json')); reg = json.load(open('register.json'))

def owner_key(page, d, lab, baselines, box):
    r = reg[str(page)]
    x0, y0, x1, y1 = box
    X0, X1 = (x0 - r['sx']) / r['s'], (x1 - r['sx']) / r['s']
    Y0, Y1 = (y0 - r['sy']) / r['s'], (y1 - r['sy']) / r['s']
    pad = 0.15 * max(X1 - X0, Y1 - Y0)
    sub = lab[max(0, int(Y0 - pad)):int(Y1 + pad), max(0, int(X0 - pad)):int(X1 + pad)]
    ids, cnt = np.unique(sub[sub > 0], return_counts=True)
    word_of = {pid: w for w in d['words'] if not w['ring'] for pid in w.get('pieces', [])}
    best = max(((c, i) for i, c in zip(ids, cnt) if int(i) in word_of), default=None)
    if best is None:
        return None
    pid = int(best[1]); w = word_of[pid]
    ys, xs = np.nonzero(lab == pid)
    cy, cx = ys.mean(), xs.mean()
    # a waqf sign sits ABOVE its word: below its owner's baseline it is the next line's word's
    if w['line'] < len(d['bands']) and cy > baselines[w['line'] - 1]:
        below = [v for v in d['words'] if v['line'] == w['line'] + 1 and not v['ring']]
        if below:
            w = min(below, key=lambda v: max(0.0, v['x0'] - cx, cx - v['x1']))
    return key_of.get(w['word_index'])

def one_per_word(marks):
    best = {}
    for m in marks:
        if m['word_key'] not in best or m['confidence'] > best[m['word_key']]['confidence']:
            best[m['word_key']] = m
    return list(best.values())

variants = {'A shipped': [], 'B kept re-attached': [], 'C kept+rejected re-attached, prior again': []}
page_keys = set()
moved = 0
for page in range(3, 50):
    d = json.load(open(f'paw-words-{page:03d}.json'))
    lab = np.load(f'labels-{page:03d}.npz')['lab']
    page_keys |= {key_of[w['word_index']] for w in d['words'] if not w['ring'] and w['word_index'] in key_of}
    g = cv2.cvtColor(cv2.imread(f'{APP}/pages/page-{page:03d}.webp'), cv2.COLOR_BGR2GRAY)
    ink = g < 128
    baselines = [int(a) + int(np.argmax(ink[int(a):int(b)].sum(1))) for a, b in d['bands']]
    kept, rej = shipped[str(page)]['marks'], shipped[str(page)]['rejected']
    variants['A shipped'] += kept
    def reat(ms):
        global moved
        out = []
        for m in ms:
            k = owner_key(page, d, lab, baselines, m['box'])
            m2 = dict(m)
            if k and k != m['word_key']:
                s_, a_, w_ = map(int, k.split(':'))
                m2.update(word_key=k, surah=s_, ayah=a_); moved += 1
            out.append(m2)
        return out
    variants['B kept re-attached'] += one_per_word(reat(kept))
    both = one_per_word(reat(kept) + reat(rej))
    kk, _ = partition_marks_by_azhar_occupancy(both, editions=PRIOR)
    variants['C kept+rejected re-attached, prior again'] += kk

truth = {k: v for k, v in column.items() if k in page_keys}
print('column signs on pages 3-49:', len(truth), '· marks re-keyed:', moved)
for name, marks in variants.items():
    got = {m['word_key']: m['symbol'] for m in marks}
    c = collections.Counter()
    for k, v in truth.items():
        c['exact' if got.get(k) == v else ('wrong sign' if k in got else 'missed')] += 1
    c['extra'] = sum(1 for k in got if k not in truth and k in page_keys)
    print(f"{name:45s} exact {c['exact']:3d} ({c['exact'] / len(truth):.1%}) · wrong sign {c['wrong sign']:2d} · missed {c['missed']:3d} · extra {c['extra']:3d}")
