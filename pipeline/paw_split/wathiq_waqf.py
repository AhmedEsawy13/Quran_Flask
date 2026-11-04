"""Read the waqf sign on every Wathiq word that carries one (blue pieces from wathiq_split.py).

The print colours its signs blue, so each sign is cut from a sign-only image (blue ink -> black on
white, nothing else on the page) and read with the shipped waqf model at the size it was trained on:
a 32 px window on the page scaled so the line pitch matches the training prints, resized to 48x48.

    python3 pipeline/paw_split/wathiq_waqf.py 15 56 190 ...      # -> artifacts/wathiq-trace/waqf-NNN.json
"""
import json
import os
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from pipeline.paw_split._common import ROOT, workdir  # noqa: E402
from pipeline.cv_waqf.classify import GlyphClassifier  # noqa: E402

MODEL = ROOT / 'models' / 'waqf_glyph_multiprint.onnx'
PITCH_AT_WORK = float(os.environ.get('PITCH_AT_WORK', '62'))   # line pitch at the model's working size (58-82 tried; 62 best)


MASKS = {'strict': (35, 35), 'loose': (20, 25)}     # blue: B > R + d, chroma > c


def is_streak(b):
    return (b[3] - b[1]) > 40 and (b[2] - b[0]) < 15


def read(clf, small, xs0, ys0, xs1, ys1, s):
    X, Y = int(round((xs0 + xs1) / 2 * s)), int(round((ys0 + ys1) / 2 * s))
    patch = np.full((32, 32), 255, np.uint8)
    y0, x0 = Y - 16, X - 16
    sy0, sx0 = max(0, y0), max(0, x0)
    sub = small[sy0:Y + 16, sx0:X + 16]
    patch[sy0 - y0:sy0 - y0 + sub.shape[0], sx0 - x0:sx0 - x0 + sub.shape[1]] = sub
    crop = cv2.resize(patch, (48, 48), interpolation=cv2.INTER_AREA)
    label, conf, probs = clf.predict_many_probs([crop])[0]
    # a blue piece is always a sign: when the gate says 'none', take the likeliest symbol anyway
    ranked = sorted(((c, float(p)) for c, p in zip(clf.classes, probs) if c != 'none'), key=lambda t: -t[1])
    gate_none = label == 'none'
    if gate_none:
        label, conf = ranked[0][0], ranked[0][1] / max(1e-9, sum(p for _, p in ranked))
    return label, conf, gate_none, ranked[:2], crop


def main(argv):
    clf = GlyphClassifier(MODEL)
    assert clf.ready
    workdir(os.environ.get('PAW_WORK', 'wathiq-trace'))
    for page in map(int, argv):
        d = json.load(open(f'paw-words-{page:03d}.json'))
        img = cv2.imread(str(ROOT / 'artifacts' / 'tafsir-app' / 'alwathiq' / f'p{page:03d}.jpg')).astype(int)
        B, G, R = img[..., 0], img[..., 1], img[..., 2]
        chroma = img.max(2) - img.min(2)
        pitch = float(np.median(np.diff([(a + b) / 2 for a, b in d['bands']])))
        s = PITCH_AT_WORK / pitch if PITCH_AT_WORK else 1024 / img.shape[1]
        smalls = {}
        for name, (dr, dc) in MASKS.items():
            blue = (B > R + dr) & (B >= G - 5) & (chroma > dc)
            smalls[name] = cv2.resize(np.where(blue, 0, 255).astype(np.uint8), None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
        out = []
        for w in d['words']:
            if w['ring'] or not w.get('signs'):
                continue
            # a thin tall blue run is a streak in the scan (p372), not part of a sign: it drags the crop off the sign
            boxes = [b for b in w['signs'] if not is_streak(b)] or w['signs']
            xs0, ys0, xs1, ys1 = (f([b[k] for b in boxes]) for k, f in ((0, min), (1, min), (2, max), (3, max)))
            reads = {name: read(clf, small, xs0, ys0, xs1, ys1, s) for name, small in smalls.items()}
            # faint signs (قلى, صلى) lose strokes under the strict mask and read as ج; the loose mask keeps
            # them but merges stray ink around a small م (-> ج) and dots next to صلى (-> ع)
            st, lo = reads['strict'], reads['loose']
            use = st if st[0] == 'م' or (st[0] == 'ص' and lo[0] == 'ع') else lo
            label, conf, gate_none, top2, crop = use
            # the gate already said 'not a sign' and the ink is a sliver or a streak: scan noise
            if gate_none and (xs1 - xs0 <= 10 or ys1 - ys0 <= 6 or ys1 - ys0 > 40):
                continue
            out.append({'word_index': w['word_index'], 'text': w['text'], 'line': w['line'], 'sign': label,
                        'conf': round(float(conf), 4), 'box': [xs0, ys0, xs1, ys1],
                        'top2': [(c, round(float(p), 3)) for c, p in top2], 'gate_none': gate_none,
                        'strict': st[0], 'loose': lo[0]})
            cv2.imwrite(f'sign-{page:03d}-{w["word_index"]}.png', crop)
        json.dump({'page': page, 'scale': s, 'signs': out}, open(f'waqf-{page:03d}.json', 'w'), ensure_ascii=False, indent=1)
        print(page, len(out), flush=True)


if __name__ == '__main__':
    main(sys.argv[1:])
