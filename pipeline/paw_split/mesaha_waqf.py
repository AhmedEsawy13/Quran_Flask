"""Waqf signs on split Mesaha pages: for every word, read the small ink pieces printed above its end
with the shipped waqf model, and keep the strongest sign.

The split (mesaha_split.py) gives each word's exact ink extent. A sign sits above the word's last
letter and may hang into the gap after it (Mesaha is right-to-left: the word's end is its left
edge). Each candidate piece is cut the way the model was trained: a 24 px window around the piece on
the page scaled to 1024 px wide (pad 4 -> 32 px -> 48x48).

Every word is read. Words that another Hafs print marks ("union" words; on fully checked pages all
of Mesaha's signs sit on them) are the main candidates; a confident sign on any other word is kept
as a safety-check hit.

    python3 pipeline/paw_split/mesaha_waqf.py 5 9 48 ...        # pages -> waqf-NNN.json
"""
import json
import sqlite3
import sys
from pathlib import Path

import cv2
import numpy as np
from scipy import ndimage

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from pipeline.paw_split._common import ROOT, workdir  # noqa: E402
from pipeline.cv_waqf.classify import GlyphClassifier  # noqa: E402
from pipeline.cv_waqf.config import EDITIONS  # noqa: E402
from pipeline.cv_waqf.word_space import printed_position  # noqa: E402

MODEL = ROOT / 'models' / 'waqf_glyph_multiprint.onnx'
SCRIPT_DB = EDITIONS['المساحة'].script_db
HAFS = ['المدينة الجديد', 'المدينة القديم', 'المدينة ١٤٢٧', 'الشمرلي', 'الأزهر', 'قطر', 'الكويت', 'البحرين']
WORK_WIDTH = 1024
MIN_CONF = 0.5


def load_columns() -> dict:
    clean = lambda v: '' if (v or '').strip() in ('', 'ركوع') else v.strip()
    db = sqlite3.connect(ROOT / 'data' / 'mushaf_waqf.db')
    q = 'SELECT السورة, الآية, word_index, ' + ', '.join(f'"{c}"' for c in HAFS) + ' FROM waqf'
    return {(r[0], r[1], r[2]): dict(zip(HAFS, map(clean, r[3:]))) for r in db.execute(q)}


def page_signs(page: int, clf, key_of, columns) -> dict:
    d = json.load(open(f'paw-words-{page:03d}.json', encoding='utf-8'))
    lab = np.load(f'labels-{page:03d}.npz')['lab']
    gray = cv2.imread(str(ROOT / 'data' / 'cv' / 'pages' / 'mesaha' / f'p{page:03d}_w1600.jpg'), cv2.IMREAD_GRAYSCALE)
    H, W = gray.shape
    s = WORK_WIDTH / W
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
        return any(min(ax1, px1) - max(ax0, px0) >= 0.4 * (px1 - px0) and -0.05 * line_h <= ay0 - py1 <= 0.3 * line_h
                   for ax0, ax1, ay0 in alifs)

    words = [w for w in d['words'] if not w['ring'] and w.get('pieces')]
    out = []
    for w in words:
        li = w['line'] - 1
        base = baselines[li]
        # the zone above the word's end: from its left edge (the end, RTL) a little into the gap, up to
        # the middle of its own right half; vertically between the line above and its own letter tops
        # along the word, 0 = its end (left edge), 1 = its start: checked signs sit at -0.24..0.31; a hamza on
        # the word's initial alif sits near 1, the next word's hamza below -0.3 (both read as ج)
        # a short word (بِهِۦ) is narrower than its sign, which may sit over any part of it: search at
        # least half a line pitch wide, and over the whole word
        width = max(w['x1'] - w['x0'], 0.5 * pitch)
        x_lo, x_hi = w['x0'] - 0.3 * width - 5, w['x0'] + 0.45 * width + 5
        if w['x1'] - w['x0'] < 0.5 * pitch:
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
        sa, sy, sw = key_of.get(w['word_index'], '0:0:0').split(':')
        pos = printed_position(SCRIPT_DB, int(sa), int(sy), int(sw)) if sa != '0' else None
        hint = columns.get((int(sa), int(sy), pos), {}) if pos else {}
        out.append({'word_index': w['word_index'], 'key': key_of.get(w['word_index']), 'text': w['text'],
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


def main(argv: list[str]) -> int:
    pages = [int(x) for x in argv]
    clf = GlyphClassifier(MODEL)
    assert clf.ready, 'waqf model not loaded'
    key_of = dict(sqlite3.connect(SCRIPT_DB).execute('SELECT word_index, word_key FROM words'))
    columns = load_columns()
    workdir('mesaha-trace')
    for page in pages:
        res = page_signs(page, clf, key_of, columns)
        json.dump(res, open(f'waqf-{page:03d}.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print(page, 'signs', len(res['signs']), flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
