"""Word tiles with the expected text under each, for checking a split by eye.

    python3 pipeline/paw_split/word_tiles.py mesaha-trace paw-words-015.json /tmp/t015
(work folder under artifacts/, the split JSON, output prefix -> PREFIX-1.png, -2.png, ...).
Arabic labels need Pillow with raqm and an Arabic font (PAW_TILE_FONT, default amiri-quran.ttf)."""
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))
from pipeline.paw_split._common import workdir  # noqa: E402
import json, sys, os, cv2, numpy as np
from PIL import Image, ImageDraw, ImageFont
workdir(sys.argv[1])
src, prefix = sys.argv[2], sys.argv[3]
d = json.load(open(src)); lab = np.load('labels-%03d.npy' % d['page']) if os.path.exists('labels-%03d.npy' % d['page']) else np.load('labels-%03d.npz' % d['page'])['lab']
font = ImageFont.truetype(os.environ.get('PAW_TILE_FONT', os.path.expanduser('~/Library/Fonts/amiri-quran.ttf')), 26, layout_engine=ImageFont.Layout.RAQM)
words = [w for w in d['words'] if not w['ring']]
ys, xs = np.nonzero(lab); L = lab[ys, xs]; o = np.argsort(L, kind='stable'); L, ys, xs = L[o], ys[o], xs[o]
st = np.searchsorted(L, np.arange(lab.max() + 2))
def box(k): a, b = st[k], st[k + 1]; return xs[a:b].min(), ys[a:b].min(), xs[a:b].max() + 1, ys[a:b].max() + 1
TW, TH = 230, 190
tiles = []
for i, w in enumerate(words, 1):
    ids = [k for k in w.get('pieces', []) if st[k + 1] > st[k]]
    tile = np.full((TH, TW), 255, np.uint8)
    if ids:
        bb = [box(k) for k in ids]
        x0, y0, x1, y1 = min(b[0] for b in bb), min(b[1] for b in bb), max(b[2] for b in bb), max(b[3] for b in bb)
        t = np.where(np.isin(lab[y0:y1, x0:x1], ids), 0, 255).astype(np.uint8)
        s = min(210 / t.shape[1], 110 / t.shape[0], 1.0)
        t = cv2.resize(t, (max(1, int(t.shape[1] * s)), max(1, int(t.shape[0] * s))), interpolation=cv2.INTER_AREA)
        tile[22:22 + t.shape[0], (TW - t.shape[1]) // 2:(TW - t.shape[1]) // 2 + t.shape[1]] = t
    im = Image.fromarray(tile); dr = ImageDraw.Draw(im)
    dr.text((TW // 2, TH - 30), w['text'], font=font, fill=110, anchor='mm', direction='rtl')
    dr.text((4, 2), str(i), fill=0)
    tile = np.array(im); cv2.rectangle(tile, (0, 0), (TW - 1, TH - 1), 180, 1)
    tiles.append(tile)
N = 40
for sh in range(0, len(tiles), N):
    chunk = tiles[sh:sh + N]
    while len(chunk) % 8: chunk.append(np.full((TH, TW), 255, np.uint8))
    cv2.imwrite(f'{prefix}-{sh // N + 1}.png', np.vstack([np.hstack(chunk[r:r + 8][::-1]) for r in range(0, len(chunk), 8)]))
print('sheets', (len(tiles) + N - 1) // N)
