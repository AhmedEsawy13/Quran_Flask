"""Waqf signs on split Maktoum pages (maktoom_split.py): same reading as mesaha_waqf.py - for every word,
the small black pieces above its end are read with the shipped waqf model (gate on: in this print the
signs are black like the text) and the strongest sign is kept.

    python3 pipeline/paw_split/maktoom_waqf.py 15 56 190 ...     # -> artifacts/maktoom-trace/waqf-NNN.json
"""
import glob
import json
import os
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np
from scipy import ndimage

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from pipeline.paw_split._common import ROOT, workdir  # noqa: E402
from pipeline.cv_waqf.classify import GlyphClassifier  # noqa: E402

MODEL = ROOT / 'models' / 'waqf_glyph_multiprint.onnx'
HAFS = ['المدينة الجديد', 'المدينة القديم', 'المدينة ١٤٢٧', 'الشمرلي', 'الأزهر', 'قطر', 'الكويت', 'البحرين', 'مسقط']
PITCH_AT_WORK = float(os.environ.get('PITCH_AT_WORK', '62'))
MIN_CONF = float(os.environ.get('MIN_CONF', '0.5'))
X_HI_FRAC = 0.45
ALIF_GAP = 0.3


def load_columns() -> dict:
    clean = lambda v: '' if (v or '').strip() in ('', 'ركوع') else v.strip()
    db = sqlite3.connect(ROOT / 'data' / 'mushaf_waqf.db')
    q = 'SELECT السورة, الآية, word_index, ' + ', '.join(f'"{c}"' for c in HAFS) + ' FROM waqf'
    return {(r[0], r[1], r[2]): dict(zip(HAFS, map(clean, r[3:]))) for r in db.execute(q)}


def layout_keys() -> dict:
    """global layout word id -> (surah, ayah, word position) from the cached app pages"""
    meta = {}
    for f in glob.glob('layout-*.json'):
        for line in json.load(open(f))['lines']:
            for w in line['words']:
                if not w['text'].startswith('\u06dd'):
                    meta[w['word_index']] = (w['surah'], w['ayah'])
    by = defaultdict(list)
    for i in sorted(meta):
        by[meta[i]].append(i)
    return {i: (k[0], k[1], n) for k, ids in by.items() for n, i in enumerate(ids, 1)}


def page_signs(page: int, clf, key_of, columns) -> dict:
    d = json.load(open(f'paw-words-{page:03d}.json', encoding='utf-8'))
    lab = np.load(f'labels-{page:03d}.npz')['lab']
    gray = cv2.imread(str(ROOT / 'artifacts' / 'maktoom' / 'pages' / f'p{page:03d}.jpg'), cv2.IMREAD_GRAYSCALE)
    gray = cv2.resize(gray, (lab.shape[1], lab.shape[0]), interpolation=cv2.INTER_AREA)
    H, W = gray.shape
    pitch0 = float(np.median(np.diff([(a + b) / 2 for a, b in d['bands']])))
    s = PITCH_AT_WORK / pitch0                       # module attribute: qatar_scan_waqf reads at a larger size
    small = cv2.resize(gray, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
    ink = lab > 0
    bands = d['bands']
    pitch = float(np.median(np.diff([(a + b) / 2 for a, b in bands])))
    line_h = float(np.median([b - a for a, b in bands]))
    baselines = [int(a) + int(np.argmax(ink[int(a):int(b)].sum(1))) for a, b in bands]

    n = int(lab.max()) + 1
    area = np.bincount(lab.ravel(), minlength=n)
    boxes = ndimage.find_objects(lab)
    owner = {pid: w for w in d['words'] for pid in w.get('pieces', [])}

    def crop(cx, cy):
        X, Y = int(round(cx * s)), int(round(cy * s))
        patch = np.full((32, 32), 255, np.uint8)
        y0, x0 = Y - 16, X - 16
        sy0, sx0 = max(0, y0), max(0, x0)
        sub = small[sy0:Y + 16, sx0:X + 16]
        patch[sy0 - y0:sy0 - y0 + sub.shape[0], sx0 - x0:sx0 - x0 + sub.shape[1]] = sub
        return cv2.resize(patch, (48, 48), interpolation=cv2.INTER_AREA)

    # alif stems (tall, thin, standing on the baseline): a small piece just on top of one is its hamza or
    # madda, which the model reads as ج; a stop sign floats higher, clear of the letters
    alifs = []
    for pid in range(1, n):
        sl = boxes[pid - 1]
        if sl is None:
            continue
        h, wd = sl[0].stop - sl[0].start, sl[1].stop - sl[1].start
        if h > 0.4 * line_h and wd < 0.16 * line_h:
            alifs.append((sl[1].start, sl[1].stop, sl[0].start))

    def on_alif(px0, px1, py1):
        return any(min(ax1, px1) - max(ax0, px0) >= 0.4 * (px1 - px0) and -0.05 * line_h <= ay0 - py1 <= ALIF_GAP * line_h
                   for ax0, ax1, ay0 in alifs)

    words = [w for w in d['words'] if not w['ring'] and w.get('pieces')]
    rings = [w for w in d['words'] if w['ring'] and not w.get('star')]
    out = []
    for w in words:
        li = w['line'] - 1
        base = baselines[li]
        # the zone above the word's end: from its left edge (the end, RTL) a little into the gap, up to
        # the middle of its own right half; vertically between the line above and its own letter tops
        # along the word, 0 = its end (left edge), 1 = its start: checked signs sit at -0.24..0.31; a hamza on
        # the word's initial alif sits near 1, the next word's hamza below -0.3 (both read as ج)
        # a short word (بِهِۦ, رَبِّهِۦ, أُنثَىٰ) may carry its sign over any part of it: search at least
        # half a line pitch wide, and over the whole word when it is under 0.7 pitch
        width = max(w['x1'] - w['x0'], 0.5 * pitch)
        x_lo, x_hi = w['x0'] - 0.3 * width - 5, w['x0'] + X_HI_FRAC * width + 5
        if w['x1'] - w['x0'] < 0.7 * pitch:
            x_hi = max(x_hi, w['x1'] + 5)
        y_lo, y_hi = base - 0.95 * pitch, base - 0.2 * line_h
        cands = []
        for pid in range(1, n):
            sl = boxes[pid - 1]
            if sl is None or area[pid] < 20 or area[pid] > 0.06 * line_h * line_h:
                continue
            py0, py1, px0, px1 = sl[0].start, sl[0].stop, sl[1].start, sl[1].stop
            cx, cy = (px0 + px1) / 2, (py0 + py1) / 2
            if not (x_lo <= cx <= x_hi and y_lo <= cy <= y_hi) or py1 > base - 0.1 * line_h:
                continue
            if on_alif(px0, px1, py1):
                continue
            if any(abs(cx - (r['x0'] + r['x1']) / 2) <= 0.3 * (r['x1'] - r['x0']) and abs(cy - (bands[r['line'] - 1][0] + bands[r['line'] - 1][1]) / 2) < 0.8 * pitch
                   for r in rings):
                continue            # the medallion's top ornament (a sign may hang over its edge)
            o = owner.get(pid)
            if o is not None and o['line'] != w['line'] and o['line'] != w['line'] - 1:
                continue
            cands.append((pid, cx, cy))
        if not cands:
            continue
        preds = clf.predict_many_probs([crop(cx, cy) for _, cx, cy in cands])
        hits = sorted(((conf, label, pid, cx, cy) for (pid, cx, cy), (label, conf, _) in zip(cands, preds)
                       if label != 'none' and conf >= MIN_CONF), reverse=True)
        if not hits:
            continue
        conf, label, pid, cx, cy = hits[0]
        # the sign's size = every candidate piece inside the model's window (ج's head and dot are two
        # pieces; the strongest window is often centred on the dot)
        r_win = 16 / s
        parts = [(q, qx, qy) for q, qx, qy in cands if abs(qx - cx) <= r_win and abs(qy - cy) <= r_win]
        sign_area = int(sum(area[q] for q, _, _ in parts))
        cx = sum(qx * area[q] for q, qx, _ in parts) / max(1, sign_area)
        cy = sum(qy * area[q] for q, _, qy in parts) / max(1, sign_area)
        hint = columns.get(key_of.get(w['word_index']), {})
        out.append({'word_index': w['word_index'], 'key': ':'.join(map(str, key_of.get(w['word_index'], ()))), 'text': w['text'],
                    'line': w['line'], 'sign': label, 'conf': round(float(conf), 4), 'piece': int(pid),
                    'piece_area': sign_area, 'cx': round(cx), 'cy': round(cy),
                    'word_box': [round(w['x0']), round(w['x1'])], 'hint': hint})
    # one sign piece -> one word: if two words claim the same piece, the word the split gave it to keeps
    # it (a sign over a short word like بِهِۦ), else the word whose end is nearer
    def claim(r):
        own = owner.get(r['piece'])
        return (own is not None and own['word_index'] == r['word_index'], -abs(r['cx'] - r['word_box'][0]))

    by_piece = {}
    for r in out:
        prev = by_piece.get(r['piece'])
        if prev is None or claim(r) > claim(prev):
            by_piece[r['piece']] = r
    kept = sorted(by_piece.values(), key=lambda r: (r['line'], -r['word_box'][1]))
    return {'page': page, 'pitch': pitch, 'signs': kept}


def main(argv):
    clf = GlyphClassifier(MODEL)
    assert clf.ready, 'waqf model not loaded'
    workdir('maktoom-trace')
    key_of = layout_keys()
    columns = load_columns()
    for page in map(int, argv):
        res = page_signs(page, clf, key_of, columns)
        json.dump(res, open(f'waqf-{page:03d}.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print(page, 'signs', len(res['signs']), flush=True)


if __name__ == '__main__':
    main(sys.argv[1:])
