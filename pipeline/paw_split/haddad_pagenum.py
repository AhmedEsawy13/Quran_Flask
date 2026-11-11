"""Read the printed page number at the foot of every «الكويت (الحداد)» scan (artifacts/haddad/pages/pNNN.jpg,
named by archive leaf - 2) and list the scans whose number is not their name: the archive has leaves out of
order (p384.jpg is printed page 386, p386.jpg is 384). Digits are matched against templates cut from pages
4-30, whose numbers are known (the pilot checked their text).

    python3 pipeline/paw_split/haddad_pagenum.py      # -> artifacts/haddad/pagenum.json {file page: printed page}
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
PAGES = ROOT / 'artifacts' / 'haddad' / 'pages'
AR = '٠١٢٣٤٥٦٧٨٩'


def digits(p: int) -> list[np.ndarray]:
    im = cv2.imread(str(PAGES / f'p{p:03d}.jpg'), cv2.IMREAD_GRAYSCALE)
    h, w = im.shape
    # the number sits centred below the frame: search the band under the frame's bottom
    band = im[h - 420:h - 120, w // 2 - 300:w // 2 + 300]
    ink = (band < 110).astype(np.uint8)
    n, lab, st, _ = cv2.connectedComponentsWithStats(ink, 8)
    comps = [(st[i, 0], st[i, 1], st[i, 2], st[i, 3], i) for i in range(1, n) if st[i, 4] > 40 and 8 <= st[i, 3] < 90 and st[i, 2] < 80 and st[i, 2] < 300]
    if not comps:
        return []
    # keep the row of components nearest the band's lower part (the frame ornament is above)
    ys = sorted(c[1] + c[3] / 2 for c in comps)
    yc = max(ys)
    row = [c for c in comps if abs(c[1] + c[3] / 2 - yc) < 40]
    row.sort(key=lambda c: c[0])                         # left to right = most significant first
    out = []
    for x, y, cw, ch, i in row:
        g = (lab[y:y + ch, x:x + cw] == i).astype(np.float32)
        s = 28.0 / max(cw, ch)
        g = cv2.resize(g, (max(1, int(cw * s)), max(1, int(ch * s))), interpolation=cv2.INTER_AREA)
        canvas = np.zeros((32, 32), np.float32)
        oy, ox = (32 - g.shape[0]) // 2, (32 - g.shape[1]) // 2
        canvas[oy:oy + g.shape[0], ox:ox + g.shape[1]] = g
        out.append(canvas)
    return out


def main() -> int:
    lib = {d: [] for d in range(10)}
    for p in range(4, 31):
        ds = digits(p)
        want = [int(c) for c in str(p)]
        if len(ds) == len(want):
            for g, d in zip(ds, want):
                lib[d].append(g)
    missing = [d for d, v in lib.items() if not v]
    assert not missing, f'no template for digits {missing}'
    def classify(g):
        best = max(((float((g * t).sum() / (np.linalg.norm(g) * np.linalg.norm(t) + 1e-6)), d) for d, ts in lib.items() for t in ts))
        return best[1], best[0]
    result, odd = {}, []
    for f in sorted(PAGES.glob('p*.jpg')):
        p = int(f.stem[1:])
        if p < 4:
            continue
        ds = digits(p)
        reads = [classify(g) for g in ds]
        num = int(''.join(str(d) for d, _ in reads)) if reads else None
        conf = min((c for _, c in reads), default=0)
        result[p] = {'printed': num, 'conf': round(conf, 3)}
        if num != p:
            odd.append((p, num, round(conf, 3)))
    json.dump(result, open(ROOT / 'artifacts' / 'haddad' / 'pagenum.json', 'w'), indent=0)
    print(f'{len(result)} scans read; number differs from the file name on {len(odd)}:')
    for o in odd:
        print('  file', o[0], '-> printed', o[1], 'conf', o[2])
    return 0


if __name__ == '__main__':
    sys.exit(main())
