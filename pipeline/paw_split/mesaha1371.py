"""The 1371 AH / 1952 Mesaha print (second edition) against the 1342 AH / 1924 one.

The 1952 print reuses the 1924 plates: every page has the same lines and the same word positions (checked by
overlaying page 751). Only the surah headers and part of the waqf signs were redone. So instead of splitting the
1952 pages into words again, each 1952 page is laid onto its 1924 page (a homography from matched ink features)
and read with the 1924 page's word boxes.

Source scan: archive.org MmSL7H (Jordanian Ministry of Education reprint, 10th printing 1993, of the Survey
Authority print arranged and bound at the Dar al-Kutub press in 1371 AH / 1952); its HD image leaf i (0-based)
is layout page i + 1.

    python3 pipeline/paw_split/mesaha1371.py align 4 5 6 ...    # -> data/cv/pages/mesaha1371/pNNN_w1600.png
    python3 pipeline/paw_split/mesaha1371.py signs 4 5 6 ...    # -> artifacts/mesaha1371/waqf-NNN.json
    python3 pipeline/paw_split/mesaha1371.py cards 4 5 6 ...    # -> data/mesaha-waqf/mesaha-waqf-1371 (review cards)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from pipeline.paw_split._common import ROOT  # noqa: E402

SRC = ROOT / 'data' / 'cv' / 'pages' / 'mesaha1371' / 'src'
OUT = ROOT / 'data' / 'cv' / 'pages' / 'mesaha1371'
P1924 = ROOT / 'data' / 'cv' / 'pages' / 'mesaha'
TRACE = ROOT / 'artifacts' / 'mesaha-trace'
WORK = ROOT / 'artifacts' / 'mesaha1371'


def binarize(gray: np.ndarray) -> np.ndarray:
    """Ink 0, paper 255. The 1952 scan is on tinted paper with a coloured frame: a local threshold."""
    return cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 41, 25)


def render(page: int) -> np.ndarray:
    """The page's scan at its own resolution (1767 x 2656): leaf page - 1 of the item's HD image set,
    downloaded once into SRC."""
    path = SRC / f'MmSL7HD_{page - 1:04d}.jp2'
    if not path.exists():
        import time
        import urllib.request
        url = f'https://archive.org/download/MmSL7H/MmSL7HD_jp2.zip/MmSL7HD_jp2%2FMmSL7HD_{page - 1:04d}.jp2'
        tmp = path.with_suffix('.part')
        for attempt in range(5):            # archive.org now and then never answers: time out and retry
            try:
                with urllib.request.urlopen(url, timeout=60) as r:
                    tmp.write_bytes(r.read())
                break
            except OSError:
                if attempt == 4:
                    raise
                time.sleep(5 * (attempt + 1))
        tmp.rename(path)
    return cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)


def text_block(ref_b: np.ndarray, words: list[dict], bands: list) -> tuple[int, int]:
    """x range inside the 1924 frame: out from the text's middle, the nearest ink piece taller than half the
    page on each side (a frame rule; the same test the word split uses)."""
    h, w = ref_b.shape
    n, lab, st, _ = cv2.connectedComponentsWithStats((ref_b < 128).astype(np.uint8), 8)
    tall = np.zeros(n, bool)
    tall[1:] = st[1:, cv2.CC_STAT_HEIGHT] > 0.5 * h
    xs = [x for wd in words for x in (wd['x0'], wd['x1'])]
    lo, hi = int(min(xs)), int(max(xs))
    a, b = bands[len(bands) // 2]           # along a middle text line: the frame's top/bottom rules join the
    cols = tall[lab[int(a):int(b)]].any(0)  # side rules into one piece that spans every column
    left = next((x for x in range(lo, -1, -1) if cols[x]), 0)
    right = next((x for x in range(hi, w) if cols[x]), w)
    return left + 4, right - 4


def text_rows(d: dict, height: int) -> np.ndarray:
    """Rows that can hold text or its signs: each text line's band and the gap up to the line above it. A
    line under the frame's top or under a surah header keeps only 0.35 pitch above its band: the 1952
    frame and headers are redrawn, and their ornament there is no sign."""
    centres = [(a + b) / 2 for a, b in d['bands']]
    pitch = float(np.median(np.diff(centres))) if len(centres) > 1 else 155.0
    keep = np.zeros(height, bool)
    numbers = d.get('line_numbers') or list(range(1, len(d['bands']) + 1))
    for i, (a, b) in enumerate(d['bands']):
        follows_text = i > 0 and numbers[i] == numbers[i - 1] + 1
        top = d['bands'][i - 1][1] if follows_text else a - 0.35 * pitch
        keep[max(0, int(top)):min(height, int(b) + 1)] = True
    return keep


def border_cut(img: np.ndarray, d: dict, x0: int, x1: int) -> tuple[int, int]:
    """Tighten (x0, x1) to the 1952 frame: its border is redrawn and sits closer to the text than the 1924
    one. A column whose ink runs on, gaps closed, for over 2.5 line pitches is frame: text lines always leave
    a gap between them."""
    a0, b1 = int(d['bands'][0][0]), int(d['bands'][-1][1])
    centres = [(a + b) / 2 for a, b in d['bands']]
    pitch = float(np.median(np.diff(centres))) if len(centres) > 1 else 155.0
    ink = (img[a0:b1] < 128).astype(np.uint8)
    ink = cv2.morphologyEx(ink, cv2.MORPH_CLOSE, np.ones((25, 5), np.uint8))
    xs = [x for wd in d['words'] for x in (wd['x0'], wd['x1'])]
    lo, hi = int(min(xs)), int(max(xs))

    def longest(col):
        best = cur = 0
        for v in col:
            cur = cur + 1 if v else 0
            best = max(best, cur)
        return best
    frame = [x for x in list(range(x0, lo)) + list(range(hi, x1)) if longest(ink[:, x]) > 2.5 * pitch]
    left = max([x for x in frame if x < lo], default=x0 - 4) + 4
    right = min([x for x in frame if x > hi], default=x1 + 4) - 4
    return max(x0, left), min(x1, right)


def refine(warped: np.ndarray, ref_b: np.ndarray, d: dict, parts: int = 4, reach: int = 24) -> np.ndarray:
    """Follow a curved scan: one homography leaves pages photographed near the binding up to ~10 px off at the
    edges. Each text line (with the gap above it, where its signs sit) is cut into ``parts`` pieces across, and
    each piece is moved by the shift that best lays its ink on the 1924 ink."""
    h, w = warped.shape
    out = np.full_like(warped, 255)
    xs = [x for wd in d['words'] for x in (wd['x0'], wd['x1'])]
    lo, hi = max(0, int(min(xs)) - 60), min(w, int(max(xs)) + 60)
    edges = np.linspace(lo, hi, parts + 1).astype(int)
    covered = np.zeros_like(warped, bool)
    prev_bottom = None
    for a, b in d['bands']:
        top = int(prev_bottom if prev_bottom is not None and a - prev_bottom < 80 else a - 70)
        bot = int(b) + 6
        prev_bottom = b
        for x0, x1 in zip(edges[:-1], edges[1:]):
            ref = (ref_b[top:bot, x0:x1] < 128).astype(np.float32)
            y0, y1, xa, xb = max(0, top - reach), min(h, bot + reach), max(0, x0 - reach), min(w, x1 + reach)
            src = (warped[y0:y1, xa:xb] < 128).astype(np.float32)
            dy, dx = 0, 0
            if ref.sum() > 50 and src.shape[0] >= ref.shape[0] and src.shape[1] >= ref.shape[1]:
                score = cv2.matchTemplate(src, ref, cv2.TM_CCORR)
                _, _, _, (bx, by) = cv2.minMaxLoc(score)
                dx, dy = bx - (x0 - xa), by - (top - y0)
            sy0, sy1, sx0, sx1 = top + dy, bot + dy, x0 + dx, x1 + dx
            if 0 <= sy0 and sy1 <= h and 0 <= sx0 and sx1 <= w:
                out[top:bot, x0:x1] = np.minimum(out[top:bot, x0:x1], warped[sy0:sy1, sx0:sx1])
                covered[top:bot, x0:x1] = True
    out[~covered] = warped[~covered]
    return out


def align(page: int) -> dict:
    """Warp the 1952 page onto the 1924 page's pixels; return the fit's quality."""
    ref = cv2.imread(str(P1924 / f'p{page:03d}_w1600.jpg'), cv2.IMREAD_GRAYSCALE)
    ref_b = cv2.threshold(ref, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
    src = binarize(render(page))
    orb = cv2.ORB_create(12000)
    ka, da = orb.detectAndCompute(255 - ref_b, None)
    kb, db = orb.detectAndCompute(255 - src, None)
    matches = sorted(cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True).match(db, da), key=lambda m: m.distance)[:3000]
    pts_b = np.float32([kb[m.queryIdx].pt for m in matches])
    pts_a = np.float32([ka[m.trainIdx].pt for m in matches])
    H, inl = cv2.findHomography(pts_b, pts_a, cv2.RANSAC, 3.0)
    warped = cv2.warpPerspective(src, H, (ref.shape[1], ref.shape[0]), flags=cv2.INTER_LINEAR, borderValue=255)
    warped = np.where(warped < 128, 0, 255).astype(np.uint8)
    d = json.load(open(TRACE / f'paw-words-{page:03d}.json', encoding='utf-8'))
    warped = refine(warped, ref_b, d)
    # the 1952 scan's strokes come out about half as heavy as the 1924 scan's: thicken them by a pixel so
    # the sign model sees the stroke weight it knows
    warped = cv2.erode(warped, np.ones((2, 2), np.uint8))   # half a pixel each side: a full one pushes signs
    #   past the reader's size limit for a sign piece
    # the 1952 frame has its own border pattern, which binarizes to speckle right beside the line ends: keep
    # only what lies inside the 1924 frame's inner rules (the plates' text block is the same)
    x0, x1 = text_block(ref_b, d['words'], d['bands'])
    x0, x1 = border_cut(warped, d, x0, x1)
    warped[:, :x0] = 255
    warped[:, x1:] = 255
    warped[~text_rows(d, warped.shape[0])] = 255
    cv2.imwrite(str(OUT / f'p{page:03d}_w1600.png'), warped)
    # fit quality: the share of the 1952 text-block ink that falls on (or a pixel from) 1924 ink; changed
    # signs and headers are a small part, a misfit would scatter most of it
    a0, b1 = int(d['bands'][0][0]), int(d['bands'][-1][1])
    ink_a = cv2.dilate((ref_b[a0:b1] < 128).astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
    ink_b = warped[a0:b1] < 128
    fit = float((ink_a & ink_b).sum() / max(1, ink_b.sum()))
    return {'page': page, 'inliers': int(inl.sum()), 'fit': round(fit, 3)}


def page_signs(page: int, clf, key_of, columns) -> dict:
    """mesaha_waqf.page_signs on the aligned 1952 page, with the 1924 page's words, bands and pieces."""
    from scipy import ndimage
    from pipeline.paw_split import mesaha_waqf as mw

    img = cv2.imread(str(OUT / f'p{page:03d}_w1600.png'), cv2.IMREAD_GRAYSCALE)
    lab, n = ndimage.label(img < 128, structure=np.ones((3, 3)))
    # a 1952 piece belongs to the 1924 word whose pieces it overlaps most (the plates are the same)
    lab24 = np.load(TRACE / f'labels-{page:03d}.npz')['lab']
    d = json.load(open(TRACE / f'paw-words-{page:03d}.json', encoding='utf-8'))
    word_of24 = {pid: w for w in d['words'] for pid in w.get('pieces', [])}
    both = (lab > 0) & (lab24 > 0)
    pairs = np.stack([lab[both], lab24[both]], 1)
    best: dict[int, tuple[int, int]] = {}
    if len(pairs):
        uniq, cnt = np.unique(pairs, axis=0, return_counts=True)
        for (p52, p24), c in zip(uniq, cnt):
            if p24 in word_of24 and c > best.get(int(p52), (0, 0))[1]:
                best[int(p52)] = (int(p24), int(c))
    pieces_of: dict[int, list[int]] = {}
    for p52, (p24, _) in best.items():
        pieces_of.setdefault(word_of24[p24]['word_index'], []).append(p52)
    d52 = dict(d, words=[dict(w, pieces=pieces_of.get(w['word_index'], [])) for w in d['words']])
    WORK.mkdir(parents=True, exist_ok=True)
    (WORK / f'paw-words-{page:03d}.json').write_text(json.dumps(d52, ensure_ascii=False), encoding='utf-8')
    np.savez_compressed(WORK / f'labels-{page:03d}.npz', lab=lab.astype(np.int32))
    old = Path.cwd()
    import os
    os.chdir(WORK)
    try:
        orig = mw.ROOT / 'data' / 'cv' / 'pages' / 'mesaha'
        mw_imread = cv2.imread

        def imread(path, flags=None):   # mesaha_waqf reads the 1924 page image: hand it the 1952 one
            p = str(path)
            if p.startswith(str(orig)) and p.endswith(f'p{page:03d}_w1600.jpg'):
                p = str(OUT / f'p{page:03d}_w1600.png')
            return mw_imread(p, flags) if flags is not None else mw_imread(p)
        mw.cv2.imread = imread
        try:
            return mw.page_signs(page, clf, key_of, columns)
        finally:
            mw.cv2.imread = mw_imread
    finally:
        os.chdir(old)


CARD_SET = 'mesaha-waqf-1371'
DECISION_EDITION = 'المساحة ١٣٧١ · فحص'


def card_image(page: int, word: dict, d: dict, r: dict | None, path: Path) -> None:
    """The word in the 1924 print (top) and the 1952 print (bottom), same crop; the 1952 sign read boxed."""
    pitch = float(np.median(np.diff([(a + b) / 2 for a, b in d['bands']])))
    a, b = d['bands'][word['line'] - 1]
    wx0, wx1 = int(word['x0']), int(word['x1'])
    x0, x1 = int(max(0, wx0 - 0.8 * pitch)), int(wx1 + 0.8 * pitch)
    y0, y1 = int(max(0, a - 0.8 * pitch)), int(b + 0.15 * pitch)
    tiles = []
    for src, label in ((P1924 / f'p{page:03d}_w1600.jpg', '1342'), (OUT / f'p{page:03d}_w1600.png', '1371')):
        img = cv2.imread(str(src))
        cv2.line(img, (wx0, int(b)), (wx1, int(b)), (200, 120, 0), 3)
        if label == '1371' and r:
            h = 0.33 * pitch
            cv2.rectangle(img, (int(r['cx'] - h), int(r['cy'] - h)), (int(r['cx'] + h), int(r['cy'] + h)), (0, 0, 230), 3)
        crop = img[y0:y1, x0:min(x1, img.shape[1])]
        crop = cv2.resize(crop, (360, max(1, int(crop.shape[0] * 360 / max(1, crop.shape[1])))), interpolation=cv2.INTER_AREA)
        crop = cv2.copyMakeBorder(crop, 0, 4, 0, 0, cv2.BORDER_CONSTANT, value=(255, 255, 255))
        cv2.putText(crop, label, (6, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 200), 2)
        tiles.append(crop)
    cv2.imwrite(str(path), np.vstack(tiles), [cv2.IMWRITE_JPEG_QUALITY, 72])


def build_cards(pages: list[int]) -> dict:
    """Review cards for the words whose 1952 sign differs from the 1924 «المساحة» column (words some print
    marks, the 1924 review's sign rules)."""
    import random
    import sqlite3
    from collections import Counter
    from pipeline.cv_waqf.word_space import printed_position
    from pipeline.paw_split.mesaha_waqf import SCRIPT_DB, load_columns
    from pipeline.paw_split.mesaha_waqf_review import counts
    out = ROOT / 'data' / 'mesaha-waqf' / CARD_SET
    (out / 'cards').mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(ROOT / 'data' / 'mushaf_waqf.db')
    col = {(s_, a_, w_): (m or '').strip() for s_, a_, w_, m in db.execute(
        'SELECT "السورة", "الآية", word_index, "المساحة" FROM waqf')}
    hints = load_columns()
    key_of = dict(sqlite3.connect(SCRIPT_DB).execute('SELECT word_index, word_key FROM words'))
    cards = []
    for page in pages:
        d = json.load(open(TRACE / f'paw-words-{page:03d}.json', encoding='utf-8'))
        signs = {r['word_index']: r for r in json.load(open(WORK / f'waqf-{page:03d}.json', encoding='utf-8'))['signs']}
        for w in d['words']:
            key = key_of.get(w['word_index'])
            if not key or w['ring']:
                continue
            s_, a_, n_ = map(int, key.split(':'))
            pos = printed_position(SCRIPT_DB, s_, a_, n_)
            if not pos:
                continue
            m24 = col.get((s_, a_, pos), '')
            hint = {k: v for k, v in hints.get((s_, a_, pos), {}).items() if v}
            if not (m24 or hint):
                continue
            r = signs.get(w['word_index'])
            m52 = r['sign'] if r and counts(r, hint) else ''
            if m52 == m24:
                continue
            old = hint.get('المدينة القديم', '')
            group = 'A' if m52 and m52 == old else 'B' if m52 else 'N'
            cid = f'{page:03d}-{w["word_index"]}'
            card_image(page, w, d, r if m52 else None, out / 'cards' / f'{cid}.jpg')
            cards.append({'id': cid, 'page': page, 'line': w['line'], 'word_index': w['word_index'], 'key': key,
                          'text': w['text'], 'group': group, 'model': m52 or None, 'conf': r['conf'] if r else None,
                          'hint': {'المساحة ١٣٤٢': m24, **hint} if m24 else hint,
                          'suggest': m52 or (old if old != m24 else '')})
    random.Random(7).shuffle(sample := [c['id'] for c in cards if c['group'] == 'A'])
    data = {'pages': pages, 'decision_edition': DECISION_EDITION, 'cards': cards,
            'a_sample': sample[:max(1, min(100, len(sample) // 2))]}
    (out / 'data.json').write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding='utf-8')
    return dict(Counter(c['group'] for c in cards))


EXTRA_SET = 'mesaha-waqf-1371-la'


def build_extra_cards() -> dict:
    """Cards for the signs 1952 adds on words no print marks (extra_marks.json: the «لا» before a verse ring),
    so the reviewer can confirm each one. Same decision store as the main 1952 set."""
    from collections import Counter
    extra = json.loads((ROOT / 'data' / 'mesaha-waqf' / CARD_SET / 'extra_marks.json').read_text(encoding='utf-8'))
    out = ROOT / 'data' / 'mesaha-waqf' / EXTRA_SET
    (out / 'cards').mkdir(parents=True, exist_ok=True)
    cards = []
    for x in extra:
        if x.get('word_index') is None:          # 2:2, read off the opening page by eye
            continue
        page = x['page']
        d = json.load(open(TRACE / f'paw-words-{page:03d}.json', encoding='utf-8'))
        w = next(v for v in d['words'] if v['word_index'] == x['word_index'])
        r = next((v for v in json.load(open(WORK / f'waqf-{page:03d}.json', encoding='utf-8'))['signs']
                  if v['word_index'] == x['word_index']), None)
        cid = f'{page:03d}-{x["word_index"]}'
        card_image(page, w, d, r, out / 'cards' / f'{cid}.jpg')
        cards.append({'id': cid, 'page': page, 'line': w['line'], 'word_index': x['word_index'], 'key': x['key'],
                      'text': x['text'], 'group': 'B', 'model': x['mark'], 'conf': r['conf'] if r else None,
                      'hint': {}, 'suggest': x['mark']})
    data = {'pages': sorted({c['page'] for c in cards}), 'decision_edition': DECISION_EDITION, 'cards': cards, 'a_sample': []}
    (out / 'data.json').write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding='utf-8')
    return dict(Counter(c['model'] for c in cards))


def main(argv: list[str]) -> int:
    cmd, pages = argv[0], [int(x) for x in argv[1:]]
    OUT.mkdir(parents=True, exist_ok=True)
    SRC.mkdir(parents=True, exist_ok=True)
    WORK.mkdir(parents=True, exist_ok=True)
    if cmd == 'align':
        from concurrent.futures import ProcessPoolExecutor
        with ProcessPoolExecutor(6) as ex:
            for r in ex.map(align, pages):
                print(json.dumps(r), flush=True)
        return 0
    if cmd == 'signs':
        import sqlite3
        from pipeline.cv_waqf.classify import GlyphClassifier
        from pipeline.paw_split import mesaha_waqf as mw
        clf = GlyphClassifier(mw.MODEL)
        assert clf.ready
        key_of = dict(sqlite3.connect(mw.SCRIPT_DB).execute('SELECT word_index, word_key FROM words'))
        columns = mw.load_columns()
        for page in pages:
            res = page_signs(page, clf, key_of, columns)
            (WORK / f'waqf-{page:03d}.json').write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding='utf-8')
            print(page, 'signs', len(res['signs']), flush=True)
        return 0
    if cmd == 'cards':
        print(CARD_SET, build_cards(pages))
        return 0
    if cmd == 'extra-cards':
        print(EXTRA_SET, build_extra_cards())
        return 0
    raise SystemExit(f'unknown command {cmd!r}')


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
