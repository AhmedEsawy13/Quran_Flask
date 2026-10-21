"""Tiles for chosen words only: python3 pick_tiles.py WORK OUT.png PAGE:WORD [PAGE:WORD ...] (1-based words, rings excluded)."""
import json, os, sys
from pathlib import Path
import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from pipeline.paw_split._common import workdir  # noqa: E402

workdir(sys.argv[1])
font = ImageFont.truetype(os.environ.get('PAW_TILE_FONT', os.path.expanduser('~/Library/Fonts/amiri-quran.ttf')), 24,
                          layout_engine=ImageFont.Layout.RAQM)
tiles, cache = [], {}
for spec in sys.argv[3:]:
    page, k = map(int, spec.split(':'))
    if page not in cache:
        d = json.load(open(f'paw-words-{page:03d}.json', encoding='utf-8'))
        lab = np.load(f'labels-{page:03d}.npz')['lab']
        cache[page] = ([w for w in d['words'] if not w['ring']], lab)
    words, lab = cache[page]; w = words[k - 1]
    tile = np.full((170, 220), 255, np.uint8)
    if w.get('pieces'):
        m = np.isin(lab, w['pieces']); ys, xs = np.nonzero(m)
        t = np.where(m[ys.min():ys.max() + 1, xs.min():xs.max() + 1], 0, 255).astype(np.uint8)
        s = min(200 / t.shape[1], 100 / t.shape[0], 1.0)
        t = cv2.resize(t, (max(1, int(t.shape[1] * s)), max(1, int(t.shape[0] * s))), interpolation=cv2.INTER_AREA)
        tile[20:20 + t.shape[0], (220 - t.shape[1]) // 2:(220 - t.shape[1]) // 2 + t.shape[1]] = t
    im = Image.fromarray(tile); dr = ImageDraw.Draw(im)
    dr.text((110, 145), w['text'], font=font, fill=110, anchor='mm', direction='rtl'); dr.text((3, 2), spec, fill=0)
    tile = np.array(im); cv2.rectangle(tile, (0, 0), (219, 169), 180, 1); tiles.append(tile)
while len(tiles) % 8:
    tiles.append(np.full((170, 220), 255, np.uint8))
cv2.imwrite(sys.argv[2], np.vstack([np.hstack(tiles[r:r + 8][::-1]) for r in range(0, len(tiles), 8)]))
