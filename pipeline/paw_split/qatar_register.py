"""Fit cache(1024 px scan) -> app page coordinates per page: scale from line pitch, shift by phase correlation.
Writes register.json {page: {s, dx, dy, overlap}}: app_xy = cache_xy / s + (dx, dy)."""
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))
from pipeline.paw_split._common import ROOT, QATAR_APP_ASSETS, workdir  # noqa: E402
workdir('qatar-attach')

import json, sys
import cv2, numpy as np
APP = QATAR_APP_ASSETS
CACHE = str(ROOT / 'data/cv/pages/qatar') + '/p{:03d}_w1024.jpg'

def pitch(ink, lo, hi, n=15):
    prof = np.convolve(ink.sum(1).astype(float), np.ones(5) / 5, mode='same')
    H = len(prof)
    best = max(((sum(prof[int(y0 + i * pt)] for i in range(n)), pt) for pt in np.arange(lo, hi, 0.1)
                for y0 in range(0, int(H - (n - 1) * pt), 1)))
    return best[1]

out = {}
for page in range(int(sys.argv[1]), int(sys.argv[2]) + 1):
    d = json.load(open(f'paw-words-{page:03d}.json'))
    app_pitch = float(np.median(np.diff([(a + b) / 2 for a, b in d['bands']])))
    c = cv2.imread(CACHE.format(page), cv2.IMREAD_GRAYSCALE)
    cink = (c < 128).astype(np.float32)
    cp = pitch(cink[:, 150:870], 62, 75)
    s = cp / app_pitch                                   # cache px per app px
    img = cv2.imread(f'{APP}/pages/page-{page:03d}.webp')
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    a = cv2.resize((g < 128).astype(np.float32), None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
    H, W = max(a.shape[0], cink.shape[0]), max(a.shape[1], cink.shape[1])
    A = np.zeros((H, W), np.float32); A[:a.shape[0], :a.shape[1]] = a
    C = np.zeros((H, W), np.float32); C[:cink.shape[0], :cink.shape[1]] = cink
    (sx, sy), resp = cv2.phaseCorrelate(A, C)            # C ≈ A shifted by (sx, sy)
    M = np.float32([[1, 0, sx], [0, 1, sy]])
    A2 = cv2.warpAffine(A, M, (W, H))
    overlap = float(((A2 > 0.5) & (C > 0.5)).sum() / max(1, (C > 0.5).sum()))
    # cache = app*s + (sx, sy)  ->  app = (cache - (sx, sy)) / s
    out[page] = {'s': s, 'sx': sx, 'sy': sy, 'overlap': round(overlap, 3)}
    print(page, round(s, 4), round(sx, 1), round(sy, 1), 'overlap', round(overlap, 3), flush=True)
json.dump(out, open('register.json', 'w'), indent=1)
