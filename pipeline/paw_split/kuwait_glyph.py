"""Word boxes on the Kuwait scan from the QPC v1 page fonts (the 1405 Madinah print, which Kuwait reprints).

Each layout page is drawn from its QCF v1 font (data/fonts/qcf_v1/pN.woff2, gitignored; quran.com CDN) one word glyph
at a time, using quran.com's per-word glyph codes (code_v1 + line_number, cached in artifacts/kuwait-glyph/codes).
Every line of the drawing is then laid onto the same line of the scan: the line's row is the scan's ink row, and
its x-scale and offset come from matching the two lines' column ink profiles. Each word's box on the scan follows.
The output has the same shape as the ink splits (paw-words-NNN.json + labels), so mesaha_waqf's sign reader and
qatar_scan_waqf's comparison work on it unchanged.

    python3 pipeline/paw_split/kuwait_glyph.py 100 50 ...     # -> artifacts/kuwait-scan/paw-words-NNN.json
"""
from __future__ import annotations

import io
import json
import sqlite3
import sys
import urllib.request
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from pipeline.paw_split._common import ROOT  # noqa: E402

FONTS = ROOT / 'data' / 'fonts' / 'qcf_v1'
CODES = ROOT / 'artifacts' / 'kuwait-glyph' / 'codes'
OUT = ROOT / 'artifacts' / 'kuwait-scan'
SCAN = ROOT / 'data' / 'cv' / 'pages' / 'kuwait'
LAYOUT = ROOT / 'data' / 'qpc-v1-15-lines.db'
SCRIPT_DB = ROOT / 'data' / 'mushaf-bahrain-layout.db'
EM = 120          # drawing size (px per em)


def codes(page: int) -> list[dict]:
    """[{line, code, type}] for the page's words in reading order (quran.com API, cached)."""
    path = CODES / f'p{page}.json'
    if not path.exists():
        CODES.mkdir(parents=True, exist_ok=True)
        url = (f'https://api.quran.com/api/v4/verses/by_page/{page}?words=true'
               '&word_fields=code_v1,line_number,page_number&per_page=60')
        with urllib.request.urlopen(url, timeout=60) as r:
            path.write_bytes(r.read())
    d = json.loads(path.read_text(encoding='utf-8'))
    # each word's id comes from its own verse and position, not from the layout's line contents: quran.com's
    # 1405 page lines differ from our qpc-v1-15-lines.db on pages 27, 177, 254, 443, 451 and 452
    out = []
    for v in d['verses']:
        merged = MERGED_PAIRS.get(v['verse_key'], ())
        for w in v['words']:
            # a joined glyph holds two words of our word table: every word after it is one position further on
            base = w['position'] + sum(m < w['position'] for m in merged)
            ids = [_key2id().get(f"{v['verse_key']}:{base + k}") for k in range(2 if w['position'] in merged else 1)]
            out.append({'line': w['line_number'], 'code': w['code_v1'], 'type': w['char_type_name'], 'ids': ids})
    return out


# page -> lines whose words come from our layout instead of quran.com: on these the Kuwait scan breaks the line
# where our layout does (the line fits the drawing 0.81/0.76 and 0.81/0.74 against 0.82/0.72 and 0.72/0.72)
USE_LAYOUT: dict[int, set[int]] = {177: {11, 12}, 443: {12, 13}}


# quran.com positions whose single glyph draws two words (the print joins them): verse -> positions
MERGED_PAIRS = {'2:181': (3,), '8:6': (4,), '13:37': (8,), '37:130': (3,)}


_KEY2ID: dict[str, int] = {}
_TEXT: dict[int, str] = {}


def _key2id() -> dict[str, int]:
    if not _KEY2ID:
        rows = sqlite3.connect(SCRIPT_DB).execute('SELECT word_key, word_index, text FROM words').fetchall()
        _KEY2ID.update({k: i for k, i, _ in rows})
        _TEXT.update({i: t for _, i, t in rows})
    return _KEY2ID


def font(page: int):
    from fontTools.ttLib import TTFont
    from PIL import ImageFont
    f = TTFont(FONTS / f'p{page}.woff2')
    f.flavor = None
    buf = io.BytesIO()
    f.save(buf)
    buf.seek(0)
    return ImageFont.truetype(buf, EM), f


def draw_line(fnt, ttf, glyph_codes: list[str]) -> tuple[np.ndarray, list[tuple[int, int]]]:
    """The line drawn right to left; each word's (x0, x1) span in the drawing."""
    from PIL import Image, ImageDraw
    cmap, hm, upm = ttf.getBestCmap(), ttf['hmtx'], ttf['head'].unitsPerEm
    adv = [sum(hm[cmap[ord(ch)]][0] for ch in c if ord(ch) in cmap) * EM / upm for c in glyph_codes]
    width = int(sum(adv)) + 2 * EM
    img = Image.new('L', (width, 3 * EM), 255)
    d = ImageDraw.Draw(img)
    x = width - EM
    spans = []
    for c, a in zip(glyph_codes, adv):
        x -= a
        d.text((x, EM), c, font=fnt, fill=0)
        spans.append((int(x), int(x + a)))
    return 255 - np.asarray(img), spans


def scan_rows(ink: np.ndarray, n: int, strict: bool = True) -> list[int]:
    """The n text rows: the first evenly spaced run of full-width ink rows (the short header row above is dropped)."""
    from scipy.signal import find_peaks
    H, W = ink.shape
    x0, x1 = int(0.135 * W), int(0.868 * W)
    sm = np.convolve(ink[:, x0:x1].sum(1).astype(float), np.ones(15) / 15, mode='same')
    pk, _ = find_peaks(sm, distance=int(0.035 * H), prominence=sm.max() * 0.1)

    def width(y):
        cols = np.nonzero(ink[max(0, y - 15):y + 15, x0:x1].any(0))[0]
        return (cols[-1] - cols[0]) / (x1 - x0) if len(cols) else 0
    pk = [int(y) for y in pk if width(y) > 0.6]
    if not strict:
        return pk
    for k in range(len(pk) - n + 1):
        d = np.diff(pk[k:k + n])
        if max(d) <= 1.2 * np.median(d) and min(d) >= 0.8 * np.median(d):
            return pk[k:k + n]
    return pk[:n]


def extent(profile: np.ndarray, frac: float = 0.02) -> tuple[int, int]:
    """First and last column holding ink (ignoring stray specks)."""
    on = np.nonzero(profile > frac * (profile.max() or 1))[0]
    return (int(on[0]), int(on[-1])) if len(on) else (0, len(profile) - 1)


def _score(profile_scan, d, off):
    ps = np.zeros(len(profile_scan), dtype=float)
    o = int(round(off))
    seg = d[max(0, -o):max(0, -o) + len(ps) - max(0, o)]
    ps[max(0, o):max(0, o) + len(seg)] = seg
    a = profile_scan.astype(float)
    return float((a * ps).sum() / (np.sqrt((a * a).sum() * (ps * ps).sum()) or 1))


def fit_x(profile_scan: np.ndarray, profile_draw: np.ndarray) -> tuple[float, float, float]:
    """(scale, offset, score): scan x = scale * draw x + offset. Madinah lines are justified to the full width, so
    the two lines' ink extents give a first map (a margin ornament can stretch the scan's extent); a search of
    +-8% scale and +-25 px around it then keeps the map whose column ink profiles agree best."""
    s0, s1 = extent(profile_scan)
    d0, d1 = extent(profile_draw)
    scale0 = (s1 - s0) / max(1, d1 - d0)
    best = (scale0, s0 - scale0 * d0, -1.0)
    for scale in scale0 * np.arange(0.92, 1.081, 0.005):
        d = cv2.resize(profile_draw.reshape(1, -1).astype(np.float32), (max(2, int(len(profile_draw) * scale)), 1))[0]
        for anchor in (s0 - scale * d0, s1 - scale * d1):
            for off in np.arange(anchor - 25, anchor + 26, 1):
                sc = _score(profile_scan, d, off)
                if sc > best[2]:
                    best = (float(scale), float(off), sc)
    return best


def page(page_no: int) -> dict:
    img = cv2.imread(str(SCAN / f'p{page_no:03d}_w1024.jpg'))
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    ink = g < cv2.threshold(g, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[0]
    H, W = ink.shape
    layout = sqlite3.connect(LAYOUT).execute(
        "SELECT line_number, line_type, first_word_id, last_word_id FROM pages WHERE page_number=? ORDER BY line_number",
        (page_no,)).fetchall()
    n_slots = len(layout)
    all_rows = scan_rows(ink, n_slots + 2, strict=False)
    words = codes(page_no)
    fnt, ttf = font(page_no)
    _key2id()
    text = _TEXT
    x0, x1 = int(0.135 * W), int(0.868 * W)
    drawn_lines = {}
    for ln, kind, a, b in layout:
        if kind != 'ayah' or a is None:
            continue
        line_words = [w for w in words if w['line'] == ln]
        if ln in USE_LAYOUT.get(page_no, ()):
            # this line's words as OUR layout has them (to test which of the two matches the scan)
            by_first = {w['ids'][0]: w for w in words if w['ids'] and w['ids'][0] is not None}
            line_words, i, ids = [], 0, list(range(a, b + 1))
            while i < len(ids) and ids[i] in by_first:
                line_words.append(by_first[ids[i]]); i += len(by_first[ids[i]]['ids'])
        if not line_words:
            continue
        drawn_lines[ln] = (line_words, *draw_line(fnt, ttf, [w['code'] for w in line_words]))

    def place(rows, only=None):
        pitch = float(np.median(np.diff(rows))) if len(rows) > 1 else 76.0
        bands, line_numbers, out, fits = [], [], [], []
        for (ln, kind, a, b), y in zip(layout, rows):
            if ln not in drawn_lines or (only is not None and ln not in only):
                continue
            line_words, drawn, spans = drawn_lines[ln]
            band = ink[int(y - 0.45 * pitch):int(y + 0.35 * pitch), x0:x1]
            scale, off, score = fit_x(band.sum(0).astype(float), drawn.astype(float).sum(0))
            fits.append(round(score, 3))
            bands.append((y - 0.42 * pitch, y + 0.30 * pitch))
            line_numbers.append(ln)
            li = len(bands)
            for (sx0, sx1), w in zip(spans, line_words):
                ids = [i for i in w['ids'] if i is not None]
                if not ids:            # a final verse ring our word table folds into the word before it
                    continue
                # a joined glyph is split between its words in proportion to their letters
                weights = [max(1, len(text.get(i, ''))) for i in ids]
                cut = sx1
                for i, wt in zip(ids, weights):        # right to left: the first word is on the right
                    nxt = cut - (sx1 - sx0) * wt / sum(weights)
                    out.append({'line': li, 'word_index': i, 'text': text.get(i, ''), 'ring': w['type'] == 'end',
                                'x0': x0 + off + scale * nxt, 'x1': x0 + off + scale * cut})
                    cut = nxt
        return pitch, bands, line_numbers, out, fits

    # the n text rows: the evenly spaced run of full-width rows whose lines match the drawing best (a header row
    # or the page-number band can pass as a full-width row)
    # The rows: an evenly spaced grid of n_slots rows (banner and basmala rows keep their slot but are not text
    # rows the peak search sees). Pitch from the spacing of the full-width rows found; each found row, taken as
    # each slot in turn, proposes a grid; the grids whose ayah slots hold the most ink are checked against the
    # drawing, and the one whose lines match it best wins (a short header row or the page-number band above or
    # below the text can pass as a row).
    gaps = np.diff(all_rows)
    pitch0 = float(np.median([g for g in gaps if 0.03 * H < g < 0.07 * H] or [0.052 * H]))
    sm = np.convolve(ink[:, x0:x1].sum(1).astype(float), np.ones(9) / 9, mode='same')
    ayah_slots = [i for i, (ln, kind, a_, b_) in enumerate(layout) if ln in drawn_lines]
    # the frame: the text rows sit between the header row (inside the frame's top) and the page-number band
    # (inside its bottom); the catchword under the page is outside it
    nf, lf, sf, _ = cv2.connectedComponentsWithStats(ink.astype(np.uint8), 8)
    fi = max(range(1, nf), key=lambda i: sf[i, 3] if sf[i, 3] > 0.5 * H else 0)
    ftop, fbot = int(sf[fi, 1]), int(sf[fi, 1] + sf[fi, 3])
    lo, hi = ftop + 1.2 * pitch0, fbot - 0.8 * pitch0
    grids = set()
    for y in all_rows:
        for j in range(n_slots):
            for pt in (pitch0 * 0.99, pitch0, pitch0 * 1.01):
                g = tuple(int(round(y + (i - j) * pt)) for i in range(n_slots))
                if g[0] > lo and g[-1] < hi:
                    grids.add(g)
    def snap(g):
        # each row onto its own ink peak within a fifth of a pitch, measured from the row above (the scan's rows
        # are not perfectly even, and a fixed grid drifts off by the bottom of the page)
        r = int(0.2 * pitch0)
        out = []
        for i, y in enumerate(g):
            guess = y if i == 0 else out[-1] + pitch0
            out.append(max(range(int(guess) - r, int(guess) + r + 1), key=lambda t: sm[min(max(t, 0), H - 1)]))
        return out
    # every slot carries ink, banner and basmala rows too: rank grids on all of them
    ranked = sorted(grids, key=lambda g: -sum(sm[min(max(y, 0), H - 1)] for y in g))[:16]
    probe = {layout[i][0] for i in (ayah_slots[0], ayah_slots[len(ayah_slots) // 2], ayah_slots[-1])}
    quick = []
    for g in ranked:
        rows = snap(g)
        res = place(rows, only=probe)
        quick.append((float(np.mean(res[4])) if res[4] else 0, rows))
    cands = []
    tried = set()
    for _, rows in sorted(quick, reverse=True)[:2]:
        # the chosen grid and the same grid a row up and down: a row shift can look almost as good on 3 lines
        for shift in (0, -1, 1):
            r = snap([int(y + shift * pitch0) for y in rows])
            if tuple(r) in tried or r[0] < lo - 0.3 * pitch0 or r[-1] > hi + 0.3 * pitch0:
                continue
            tried.add(tuple(r))
            res = place(r)
            cands.append((float(np.mean(res[4])) if res[4] else 0, r, res))
    if not cands:
        raise ValueError(f'page {page_no}: no row grid')
    _, _, (pitch, bands, line_numbers, out, fits) = max(cands)
    # pieces: every ink piece goes to the word whose box holds its centre on its line (signs are read by position)
    n, lab, st, cen = cv2.connectedComponentsWithStats(ink.astype(np.uint8), 8)
    for w in out:
        w['pieces'] = []
    centres = [(a + b) / 2 for a, b in bands]
    for i in range(1, n):
        if st[i, 4] < 4 or st[i, 2] > 0.5 * W or st[i, 3] > 0.5 * H:
            continue
        cx, cy = cen[i]
        li = int(np.argmin([abs(cy - c) for c in centres])) + 1 if centres else 0
        if abs(cy - centres[li - 1]) > 0.5 * pitch:
            continue
        hit = next((w for w in out if w['line'] == li and w['x0'] - 2 <= cx <= w['x1'] + 2), None)
        if hit is not None:
            hit['pieces'].append(i)
    OUT.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(OUT / f'labels-{page_no:03d}.npz', lab=lab.astype(np.int32))
    res = {'page': page_no, 'bands': bands, 'line_numbers': line_numbers, 'pitch': pitch, 'words': out, 'fit': fits}
    (OUT / f'paw-words-{page_no:03d}.json').write_text(json.dumps(res, ensure_ascii=False), encoding='utf-8')
    return {'page': page_no, 'lines': len(fits), 'fit_min': min(fits) if fits else None,
            'fit_mean': round(float(np.mean(fits)), 3) if fits else None}


if __name__ == '__main__':
    for p in map(int, sys.argv[1:]):
        try:
            print(json.dumps(page(p)), flush=True)
        except Exception as e:  # noqa: BLE001
            print(p, 'error', e, flush=True)
