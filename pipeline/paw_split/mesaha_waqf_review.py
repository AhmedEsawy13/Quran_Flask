"""Review cards for the Mesaha waqf signs read by mesaha_waqf.py.

Groups (a sign "counts" at confidence >= 0.99 and real-sign size: ص/ق >= 330 px, others >= 100 px;
on six fully checked pages this kept 53/53 true signs and dropped all but one of 43 harakat):
  A  a word other Hafs prints mark, the sign read = old Madinah's or Shamarly's sign  -> accept in bulk
  B  a word other prints mark, the sign read differs from both                        -> review
  N  a word other prints mark (old Madinah or Shamarly), no sign read                -> review
(A confident sign on a word no other print marks was never a real sign on the 33-page pilot, 0 of 15:
a shadda, hamza or iqlab mim. Those words get no card.)

Writes data/mesaha-waqf/<out>/data.json + cards/*.jpg (committed: the cloud app serves them), reviewed in the app at
/mushaf-editor/mesaha-waqf (modules/mesaha_waqf_review.py; decisions saved in the cloud).

    python3 pipeline/paw_split/mesaha_waqf_review.py mesaha-waqf-pilot 5 9 48 ...
"""
import json
import random
import sqlite3
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from pipeline.paw_split._common import ROOT  # noqa: E402
from pipeline.paw_split.mesaha_waqf import SCRIPT_DB, load_columns  # noqa: E402
from pipeline.cv_waqf.word_space import printed_position  # noqa: E402

TRACE = ROOT / 'artifacts' / 'mesaha-trace'
MIN_SIGN_CONF = 0.99
PRIOR_SIGN_CONF = 0.7      # enough when another print has the same sign on the word
MIN_AREA = {'ص': 330, 'ق': 330}
CARD_WIDTH = 380          # px; the cards are committed, so kept small
SIGNS = ['ص', 'ق', 'ج', 'م', 'لا', 'س', 'ع']


def counts(r, hint=None) -> bool:
    """A real sign: confident, or fairly sure (>= 0.7) and the sign another print has on this word.
    Not for ج: harakat inside a word read as ج at 0.7-0.97 (7 of 8 such cards were false)."""
    if r['piece_area'] < MIN_AREA.get(r['sign'], 100):
        return False
    if r['conf'] >= MIN_SIGN_CONF:
        return True
    return r['sign'] != 'ج' and r['conf'] >= PRIOR_SIGN_CONF and r['sign'] in (hint or {}).values()


def card_image(page, word, d, sign_box, path):
    """The word with a little of each neighbour and the line above: the word itself tinted, its
    baseline underlined, the sign the model read boxed in red."""
    img = cv2.imread(str(ROOT / 'data' / 'cv' / 'pages' / 'mesaha' / f'p{page:03d}_w1600.jpg'))
    pitch = float(np.median(np.diff([(a + b) / 2 for a, b in d['bands']])))
    a, b = d['bands'][word['line'] - 1]
    wx0, wx1 = int(word['x0']), int(word['x1'])
    x0 = int(max(0, wx0 - 0.9 * pitch)); x1 = int(min(img.shape[1], wx1 + 0.9 * pitch))
    y0 = int(max(0, a - 0.8 * pitch)); y1 = int(min(img.shape[0], b + 0.15 * pitch))
    ty0 = int(max(0, a - 0.55 * pitch))
    tint = img[ty0:int(b), wx0:wx1]
    tint[:] = cv2.addWeighted(tint, 0.78, np.full_like(tint, (120, 230, 255)), 0.22, 0)
    cv2.line(img, (wx0, int(b)), (wx1, int(b)), (200, 120, 0), 3)
    if sign_box:
        cx, cy, half = sign_box
        cv2.rectangle(img, (int(cx - half), int(cy - half)), (int(cx + half), int(cy + half)), (0, 0, 230), 3)
    crop = img[y0:y1, x0:x1]
    scale = min(1.0, CARD_WIDTH / max(1, crop.shape[1]))
    crop = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    cv2.imwrite(str(path), crop, [cv2.IMWRITE_JPEG_QUALITY, 72])


def main(argv):
    out_name, pages = argv[0], [int(x) for x in argv[1:]]
    out = ROOT / 'data' / 'mesaha-waqf' / out_name
    (out / 'cards').mkdir(parents=True, exist_ok=True)
    key_of = dict(sqlite3.connect(SCRIPT_DB).execute('SELECT word_index, word_key FROM words'))
    columns = load_columns()
    cards = []
    for page in pages:
        d = json.load(open(TRACE / f'paw-words-{page:03d}.json', encoding='utf-8'))
        signs = {r['word_index']: r for r in json.load(open(TRACE / f'waqf-{page:03d}.json', encoding='utf-8'))['signs']}
        pitch = float(np.median(np.diff([(a + b) / 2 for a, b in d['bands']])))
        for w in d['words']:
            if w['ring'] or not w.get('pieces'):
                continue
            key = key_of.get(w['word_index'])
            hint = {}
            if key:
                s, a, n = map(int, key.split(':'))
                pos = printed_position(SCRIPT_DB, s, a, n)
                hint = columns.get((s, a, pos), {}) if pos else {}
            union = any(hint.values())
            r = signs.get(w['word_index'])
            sign = r['sign'] if r and counts(r, hint) else None
            old, sham = hint.get('المدينة القديم', ''), hint.get('الشمرلي', '')
            if union and sign and sign in (old, sham):
                group = 'A'
            elif union and sign:
                group = 'B'
            elif union and not sign and (old or sham):
                group = 'N'
            else:
                # a confident sign on a word no other print marks ("C") was a shadda, hamza or
                # iqlab mim in all 15 pilot cards, so those are not shown
                continue
            cid = f'{page:03d}-{w["word_index"]}'
            box = (r['cx'], r['cy'], 0.33 * pitch) if r and sign else None
            card_image(page, w, d, box, out / 'cards' / f'{cid}.jpg')
            cards.append({'id': cid, 'page': page, 'line': w['line'], 'word_index': w['word_index'], 'key': key,
                          'text': w['text'], 'group': group, 'model': sign,
                          'conf': r['conf'] if r else None,
                          'hint': {k: v for k, v in hint.items() if v}, 'suggest': sign or old or sham or ''})
    random.Random(7).shuffle(sample := [c['id'] for c in cards if c['group'] == 'A'])
    data = {'pages': pages, 'cards': cards, 'a_sample': sample[:max(1, min(100, len(sample) // 2))]}
    (out / 'data.json').write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding='utf-8')
    from collections import Counter
    print(out, '· cards', Counter(c['group'] for c in cards))
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
