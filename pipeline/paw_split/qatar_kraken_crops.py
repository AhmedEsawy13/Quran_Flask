"""Cut a page's lines (from the ink-only image: frame and verse-ring colours removed) into crops
Kraken's baseline-line model can read: the writing line about two thirds of the way down, a row
~90 px tall like the Mesaha crops. Writes kraken_crops/meta.json + PNGs for kraken_read_rows.py."""
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))
from pipeline.paw_split._common import ROOT, QATAR_APP_ASSETS, workdir  # noqa: E402
workdir('qatar-attach')

import json
import sys
from pathlib import Path

import cv2
import numpy as np

PAGE = int(sys.argv[1]) if len(sys.argv) > 1 else 33
ink = cv2.imread(f'ink-{PAGE:03d}.pbm' if __import__('os').path.exists(f'ink-{PAGE:03d}.pbm') else 'ink.pbm', cv2.IMREAD_GRAYSCALE)
d = json.load(open(f'paw-words-{PAGE:03d}.json'))
H, W = ink.shape
bands = d['bands']
spacing = float(np.median(np.diff([(a + b) / 2 for a, b in bands])))
xs = [v for w in d['words'] for v in (w['x0'], w['x1']) if v]
X0, X1 = int(min(xs)) - 30, int(max(xs)) + 30
out = Path('kraken_crops'); out.mkdir(exist_ok=True)
SCALE = 90 / spacing
meta = []
for li, (a, b) in enumerate(bands, 1):
    rows = (ink[int(a):int(b), X0:X1] < 128).sum(1)
    base = int(a) + int(np.argmax(rows))                    # densest ink row = baseline
    top, bot = int(base - 0.66 * spacing), int(base + 0.34 * spacing)
    crop = ink[max(0, top):min(H, bot), X0:X1]
    crop = cv2.resize(crop, None, fx=SCALE, fy=SCALE, interpolation=cv2.INTER_AREA)
    name = f'line-{li:02d}.png'
    cv2.imwrite(str(out / name), crop)
    meta.append({'name': name, 'line': li, 'x0': X0, 'top': max(0, top), 'scale': SCALE})
(out / 'meta.json').write_text(json.dumps(meta))
print(len(meta), 'crops · scale', round(SCALE, 3), '· crop size', crop.shape)
