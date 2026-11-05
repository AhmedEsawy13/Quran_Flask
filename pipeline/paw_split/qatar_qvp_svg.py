"""Qatar mushaf pages as quran-svg-structured SVGs, traced from the print (beta for /mushaf-editor).

Input, per page (pipeline/paw_split/qatar_scan_split.py and qatar_scan_waqf.py, gitignored artifacts/qatar-scan):
  paw-words-NNN.json  words with their ink pieces (ids into labels-NNN.npz), verse rings
  labels-NNN.npz      the page's ink pieces as a label image on the 2000 px scan (data/cv/pages/qatar)
  waqf-NNN.json       which piece of which word is a waqf sign, and the sign

Every word's pieces are traced into cubic Béziers with DigitalKhatt/mushafanalyzer's tracer (MIT,
~/Development/mushafanalyzer, tools/tracing: contour_to_beziers) and written in the structure quran-engine's
svg2qvp converter reads: line > ayah-fragment > word > path[data-kind, data-mark, data-mark-family]. Waqf signs are
marks of family "waqf", so the QVP renderer's hideWaqf hides them. A verse ring (the coloured medallion and its digits)
is an ayah-mark decoration of its line.

    python3 pipeline/paw_split/qatar_qvp_svg.py 451 452 ...      # -> artifacts/qatar-qvp/svg/NNN.svg
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from pathlib import Path

import cv2
import numpy as np
from scipy import ndimage

ROOT = Path(__file__).resolve().parents[2]
ANALYZER = Path(os.environ.get('MUSHAF_ANALYZER', Path.home() / 'Development' / 'mushafanalyzer'))
sys.path.insert(0, str(ANALYZER / 'tools' / 'tracing'))
from png_to_ttf_no_potrace import (FitConfig, contour_to_beziers, find_contours_with_hierarchy,  # noqa: E402
                                   skip_tiny_hole_subtrees)

SCAN = ROOT / 'data' / 'cv' / 'pages' / 'qatar'
SPLIT = ROOT / 'artifacts' / 'qatar-scan'
OUT = Path(os.environ.get('QATAR_SVG_OUT', ROOT / 'artifacts' / 'qatar-qvp' / 'svg'))
WORDS_DB = ROOT / 'data' / 'mushaf-bahrain-layout.db'
LAYOUT_DB = ROOT / 'data' / 'mushaf-qatar-layout.db'
UNIT = 10.0          # scan px per SVG unit: the 3336 px page becomes ~334 units wide, like quran-svg's 345
# mushafanalyzer's defaults are for a ~94 px qalam stroke; Qatar's 2000 px scan has ~15 px
STROKE = 15.0 / 94.0
CFG = FitConfig(tol=8.0 * STROKE * 1.5, min_arc_height=6.0 * STROKE * 1.5, straight_seg_tol=9.0 * STROKE * 1.5)
MIN_HOLE = 500.0 * STROKE * STROKE
PAD = 6
WAQF_MARK = {'ج': 'waqf_jaiz_mustawi_al_tarafayn', 'ق': 'waqf_jaiz_waqf_awla', 'ص': 'waqf_jaiz_wasl_awla',
             'م': 'waqf_lazim', 'ع': 'waqf_al_muanaqah', 'س': 'saktah', 'لا': 'unknown'}


def trace(mask: np.ndarray, ox: float, oy: float) -> str:
    """Path data (SVG units) for a binary mask whose top-left sits at scan pixel (ox, oy)."""
    bw = cv2.copyMakeBorder(mask.astype(np.uint8) * 255, PAD, PAD, PAD, PAD, cv2.BORDER_CONSTANT, value=0)
    nodes = find_contours_with_hierarchy(bw)
    skip = skip_tiny_hole_subtrees(nodes, MIN_HOLE)
    parts = []
    for i, n in enumerate(nodes):
        if i in skip or len(n.pts) < 8:
            continue
        bez = contour_to_beziers(pts_np=n.pts, is_hole=n.is_hole, cfg=CFG)
        if not bez.cubics:
            continue
        f = lambda p: f'{(p[0] + ox - PAD) / UNIT:.1f} {(p[1] + oy - PAD) / UNIT:.1f}'
        c0 = bez.cubics[0]
        seg = [f'M {f(c0[0])}'] + [f'C {f(c[1])} {f(c[2])} {f(c[3])}' for c in bez.cubics] + ['Z']
        parts.append(' '.join(seg))
    return ' '.join(parts)


def piece_d(lab: np.ndarray, ids: list[int], boxes: dict) -> str:
    x0 = min(boxes[i][0] for i in ids); y0 = min(boxes[i][1] for i in ids)
    x1 = max(boxes[i][2] for i in ids); y1 = max(boxes[i][3] for i in ids)
    return trace(np.isin(lab[y0:y1, x0:x1], ids), x0, y0)


def page(n: int) -> dict:
    d = json.load(open(SPLIT / f'paw-words-{n:03d}.json', encoding='utf-8'))
    lab = np.load(SPLIT / f'labels-{n:03d}.npz')['lab']
    sign_of = {}
    wpath = SPLIT / f'waqf-{n:03d}.json'
    if wpath.exists():
        for s in json.load(open(wpath, encoding='utf-8'))['signs']:
            sign_of[s['piece']] = s['sign']
    keys = dict(sqlite3.connect(WORDS_DB).execute('SELECT word_index, word_key FROM words'))
    H, W = lab.shape
    boxes = {}
    for sl_i, sl in enumerate(ndimage.find_objects(lab), 1):
        if sl is not None:
            boxes[sl_i] = (sl[1].start, sl[0].start, sl[1].stop, sl[0].stop)
    pitch = float(d['pitch'])
    bands = {ln: b for ln, b in zip(d['line_numbers'], d['bands'])}
    img = cv2.imread(str(SCAN / f'p{n:03d}_w2000.jpg'))
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    coloured = (hsv[..., 1] >= 90) & (hsv[..., 2] >= 110) & (hsv[..., 2] < 235)

    out = ['VIEWBOX']
    stats = {'words': 0, 'paths': 0, 'waqf': 0, 'rings': 0, 'headers': 0, 'empty': []}
    frag = {}
    # surah banners and basmalas: the layout's header rows; their area lies between the text lines around them
    hdr_rows = sqlite3.connect(LAYOUT_DB).execute(
        "SELECT line_number, line_type, surah_number FROM pages WHERE page_number=? AND line_type IN ('surah_name','basmallah')",
        (n,)).fetchall()
    kinds = {ln: t for ln, t, _ in hdr_rows}
    surah_of = {ln: sn for ln, _, sn in hdr_rows}
    header_pieces = set()
    owned = {p for w in d['words'] for p in w['pieces']}
    # the text block: inside the coloured frame (first dense coloured band from each edge, then its end)
    def inner(profile, forward):
        idx = list(range(len(profile))) if forward else list(range(len(profile) - 1, -1, -1))
        k = next((j for j, i in enumerate(idx) if profile[i] > 0.5), 0)
        last = idx[k]
        for i in idx[k:]:
            if profile[i] > 0.25:
                last = i
            elif abs(i - last) > 40:
                break
        return last
    colp = np.convolve(coloured[int(0.3 * H):int(0.7 * H)].mean(0), np.ones(5) / 5, 'same')
    rowp = np.convolve(coloured[:, int(0.3 * W):int(0.7 * W)].mean(1), np.ones(5) / 5, 'same')
    tx0, tx1 = inner(colp, True) + 8, inner(colp, False) - 8
    ty0 = inner(rowp, True) + 8
    header_top = []
    runs, run = [], []
    for ln in range(1, 16):
        if ln in kinds:
            run.append(ln)
        elif run:
            runs.append(run); run = []
    if run:
        runs.append(run)
    for run in runs:
        before, after = bands.get(run[0] - 1), bands.get(run[-1] + 1)
        top = before[1] if before else max(0.0, (after[0] - (len(run) + 0.3) * pitch) if after else ty0)
        header_top.append(top)
        bot = after[0] if after else top + len(run) * pitch
        step = (bot - top) / len(run)
        for k, ln in enumerate(run):
            y0, y1 = int(max(0, top + k * step)), int(min(H, top + (k + 1) * step))
            if y1 - y0 < 10:
                continue
            def inside(bx, margin):
                cy, cx = (bx[1] + bx[3]) / 2, (bx[0] + bx[2]) / 2
                return y0 + margin <= cy < y1 - margin and tx0 <= cx <= tx1
            ink = [i for i, bx in boxes.items()
                   if inside(bx, 0.25 * pitch if i in owned else 0)]
            header_pieces.update(ink)
            if kinds[ln] == 'surah_name':
                # the multicoloured banner does not trace well in one colour: the viewer draws it (surah-name font);
                # its box is given in SVG units so the viewer can place it
                out.append(f'<g class="surah-name" data-line="{ln}" data-sid="{surah_of.get(ln) or ""}" '
                           f'data-box="{tx0 / UNIT:.1f} {y0 / UNIT:.1f} {(tx1 - tx0) / UNIT:.1f} {(y1 - y0) / UNIT:.1f}">')
                mid0, mid1 = tx0 + 0.3 * (tx1 - tx0), tx1 - 0.3 * (tx1 - tx0)
                name_ink = [i for i in ink if mid0 <= (boxes[i][0] + boxes[i][2]) / 2 <= mid1]
                if name_ink:  # the print's own calligraphic surah name; the banner's ornament is left to the viewer
                    dd = piece_d(lab, name_ink, boxes)
                    if dd:
                        out.append(f'<path data-kind="header_ink" d="{dd}"/>')
                out.append('</g>')
            else:
                out.append(f'<g class="basmalah" data-line="{ln}">')
                if ink:
                    dd = piece_d(lab, ink, boxes)
                    if dd:
                        out.append(f'<path data-kind="header_ink" d="{dd}"/>')
                out.append('</g>')
            stats['headers'] += 1
    for ln in sorted({w['line'] for w in d['words']}):
        ws = sorted((w for w in d['words'] if w['line'] == ln), key=lambda w: -float(w['x1']))   # reading order
        out.append(f'<g class="line" data-line="{ln}">')
        a, b = bands.get(ln, (0, 0))
        open_ayah = None
        for w in ws:
            key = keys.get(w['word_index'], '0:0:0')
            s, ay, _ = key.split(':')
            ak = f'{s}:{ay}'
            if w['ring']:
                rid = f'ayah-mark-{n}-{ak.replace(":", "-")}'
                if open_ayah:
                    out[-1] = out[-1]   # keep
                    out.append('</g>')
                    open_ayah = None
                # the medallion: coloured ink inside the ring's box, plus its digits
                x0, x1 = int(w['x0']) - 4, int(w['x1']) + 4
                y0, y1 = int(a - 0.15 * pitch), int(b + 0.15 * pitch)
                # keep the medallion only: coloured pieces that do not run the crop's full height (the frame's rules)
                x0, y0 = max(0, x0), max(0, y0)
                x1, y1 = min(W, x1), min(H, y1)
                crop = np.ascontiguousarray(coloured[y0:y1, x0:x1], dtype=np.uint8)
                if crop.size == 0 or crop.shape[0] < 3 or crop.shape[1] < 3:
                    crop = np.zeros((3, 3), np.uint8)
                nl, cl, st, _ = cv2.connectedComponentsWithStats(crop, 8)
                keep = [i for i in range(1, nl) if st[i][3] < 0.95 * crop.shape[0] and st[i][4] > 15
                        and not (st[i][2] < 6 and st[i][3] > 3 * st[i][2])]      # thin frame-rule slivers
                ring = trace(np.isin(cl, keep), x0, y0) if keep else ''
                digits = piece_d(lab, w['pieces'], boxes) if w['pieces'] else ''
                out.append(f'<g class="ayah-mark" id="{rid}" data-ayah-key="{ak}">')
                if ring:
                    out.append(f'<path data-kind="ayah_mark_ornament" d="{ring}"/>')
                if digits:
                    out.append(f'<path data-kind="ayah_number" d="{digits}"/>')
                out.append('</g>')
                stats['rings'] += 1
                frag[ak] = rid
                continue
            if open_ayah != ak:
                if open_ayah:
                    out.append('</g>')
                out.append(f'<g class="ayah-fragment" data-ayah-key="{ak}">')
                open_ayah = ak
            out.append(f'<g class="word" data-word-key="{key}" data-word-id="{w["word_index"]}" '
                       f'data-rasm-uthmani="{w["text"]}">')
            body, waqf = [], []
            for p in w['pieces']:
                if p in header_pieces:
                    continue
                (waqf if p in sign_of else body).append(p)
            if body:
                dd = piece_d(lab, body, boxes)
                if dd:
                    out.append(f'<path data-kind="body" d="{dd}"/>'); stats['paths'] += 1
            for p in waqf:
                dd = piece_d(lab, [p], boxes)
                if dd:
                    out.append(f'<path data-kind="mark" data-mark="{WAQF_MARK.get(sign_of[p], "unknown")}" '
                               f'data-mark-family="waqf" d="{dd}"/>'); stats['paths'] += 1; stats['waqf'] += 1
            if not body:
                stats['empty'].append(key)
            out.append('</g>')
            stats['words'] += 1
        if open_ayah:
            out.append('</g>')
        out.append('</g>')
    out.append('</svg>')
    # the page box: the text block inside the frame (headers included), with a small margin
    by0 = min(header_top + [float(b[0]) for b in bands.values()]) - 0.1 * pitch
    by1 = max(float(b[1]) for b in bands.values()) + 0.35 * pitch
    vx0, vx1 = tx0 - 0.15 * pitch, tx1 + 0.15 * pitch
    out[0] = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{vx0 / UNIT:.1f} {by0 / UNIT:.1f} {(vx1 - vx0) / UNIT:.1f} '
              f'{(by1 - by0) / UNIT:.1f}" data-page="{n}">')
    svg = '\n'.join(out)
    # link each ayah fragment to the medallion that ends it on this page
    for ak, rid in frag.items():
        svg = svg.replace(f'class="ayah-fragment" data-ayah-key="{ak}">', f'class="ayah-fragment" data-ayah-key="{ak}" data-ayah-mark="{rid}">')
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f'{n:03d}.svg').write_text(svg, encoding='utf-8')
    stats['bytes'] = len(svg.encode())
    (OUT / f'{n:03d}.json').write_text(json.dumps(stats, ensure_ascii=False), encoding='utf-8')
    return stats


if __name__ == '__main__':
    for arg in sys.argv[1:]:
        print(arg, page(int(arg)), flush=True)
