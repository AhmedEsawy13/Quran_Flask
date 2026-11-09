"""Shamarly pages as quran-svg-structured SVGs straight from the vector PDF (beta pilot, like qatar_qvp_svg.py).

No tracing: the Shamarly print is a vector PDF (ShemrlyMushaf/BOOK_27111_1.pdf), so every word is drawn with the
PDF's own outlines. Which outline belongs to which word comes from ShemrlyMushaf's batch-rest run: each line's
outlines (L{line}:C{k}, the line font after knife cuts and moves) and their owners as glyph_mappings.db holds them
now (reviewer decisions + the word-owner model's auto-accept), via line_ownership.line_editor_payload.

Written in the structure quran-engine's svg2qvp reads: line > ayah-fragment > word > path[data-kind, data-mark,
data-mark-family]. A verse number token (٥) is the ayah-mark decoration that ends its fragment. Waqf signs become
marks of family "waqf", so the renderer's hideWaqf hides them. They are looked for page-wide (a sign can sit in the
band of the line above its word) from two sources: the Shamarly CV detector's marks, and every sign of the page's
«الشمرلي» waqf column above its word (the detector misses some). Candidates are groupings of small outlines; the
Shamarly classifier says whether a sign is there, and shape templates of this print's confirmed signs say which
grouping it is (the classifier's 24-px window also sees the sign above a letter). The prints' sign outlines are
close but not identical copies, so quran-svg-elements' exact outline-hash keying does not apply here. Basmalas are header_ink; the surah banner
keeps its lettering (name, ayah count) as header_ink and leaves the ornamental frame to the viewer (data-box).
Tajweed (shamarly_tajweed.py): the small outlines (marks) the quran-ws tajweed rules cover are emitted as their own
paths of family "diacritic", one per rule class in a word. NNN.tajweed.json holds {"marks": {word key: [class per
mark path, in path order]}, "letters": {word key: [[x0, x1, class]]}}: the letters the rules colour as page-space
x-intervals, which the reader paints by clipping the word's body paths to them (no outline is cut). 91% of the
(letter, side) targets of the 10 pilot pages find a mark outline (Kraken letter positions + a 32 px offset).
Each word also gets ShemrlyMushaf's text check (outline counts the text predicts): count_ok / count_off in the stats.

Units are PDF points; the viewBox is the text block.

    /opt/homebrew/bin/python3 pipeline/paw_split/shamarly_qvp_prep.py 4 42 ...     # detector + waqf column
    ~/Development/ShemrlyMushaf/.venv/bin/python pipeline/paw_split/shamarly_qvp_svg.py 4 42 ...
        -> artifacts/shamarly-qvp/svg/NNN.svg (+ NNN.json stats; waqf/templates.npz grows: run twice on a
           fresh set so every page is chosen with templates)
    qvp-convert svg2qvp svg/042.svg qvp/042.qvp qvp/042.words.json     # quran-engine crates/qvp-convert (v0.8.0)
        -> artifacts/shamarly-qvp/qvp/, served by /api/shamarly/qvp/NNN.qvp to the reader's «رسم الملف (تجريبي)»

Pilot (2026-11-05, pages 4 42 50 77 100 145 150 187 300 404): 1,499 words, every outline owned; svg→qvp→svg
round trip within 1 px; 92/92 signs of the waqf column tagged and hidden (5 of them missed by the detector;
2 detector false marks rejected), each checked by eye on a contact sheet; text check passes
42.5% of words (ShemrlyMushaf: ~97% precise; the rest are unchecked, not wrong). Ownership on these pages is the
word-owner model's auto-accept (~91% exact on its blind eval): page ink is exact, word boundaries may be off by a mark.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
import collections
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SHEMRLY = Path(os.environ.get('SHEMRLY_ROOT', Path.home() / 'Development' / 'ShemrlyMushaf'))
sys.path.insert(0, str(SHEMRLY))
RUN = os.environ.get('SHEMRLY_RUN', 'batch-rest')
OUT = Path(os.environ.get('SHAMARLY_SVG_OUT', ROOT / 'artifacts' / 'shamarly-qvp' / 'svg'))
WAQF = ROOT / 'artifacts' / 'shamarly-qvp' / 'waqf'
PDF = SHEMRLY / 'BOOK_27111_1.pdf'
ADOPT_PT = 6.0          # an unowned outline joins the nearest word whose ink is at most this far
DET_WIDTH = 1024.0       # the detector reads data/refs/shamarly_pdf/cache/pNNN_w1024.jpg (whole PDF page)
WAQF_MARK = {'ج': 'waqf_jaiz_mustawi_al_tarafayn', 'ق': 'waqf_jaiz_waqf_awla', 'ص': 'waqf_jaiz_wasl_awla',
             'م': 'waqf_lazim', 'ع': 'waqf_al_muanaqah', 'س': 'saktah',
             'لا': ''}   # «لا» is waqf_mamnu in quran-svg-elements' taxonomy v2, not yet in qvp-format (v0.8.0): family waqf, mark none
DIGITS = set('٠١٢٣٤٥٦٧٨٩')


def _d(raw, k: float, x0: float, bottom: float) -> str:
    """SVG path data in PDF points for a line-font recording (x from the content edge, y up from the line bottom)."""
    f = lambda p: f'{float(p[0]) / k + x0:.2f} {bottom - float(p[1]) / k:.2f}'
    out = []
    for op, args in raw:
        pts = [p for p in args if p is not None]
        if op == 'moveTo':
            out.append(f'M {f(pts[0])}')
        elif op == 'lineTo':
            out.append(f'L {f(pts[0])}')
        elif op == 'curveTo':
            out.append('C ' + ' '.join(f(p) for p in pts))
        elif op == 'qCurveTo':
            # TrueType implied on-curve points: expand to plain quadratics
            for i in range(len(pts) - 1):
                c = pts[i]
                e = pts[i + 1] if i == len(pts) - 2 else ((pts[i][0] + pts[i + 1][0]) / 2, (pts[i][1] + pts[i + 1][1]) / 2)
                out.append(f'Q {f(c)} {f(e)}')
        elif op in ('closePath', 'endPath'):
            out.append('Z')
    return ' '.join(out)


def _bbox_pt(raw, k, x0, bottom):
    xs = [float(p[0]) / k + x0 for _, a in raw for p in a if p is not None]
    ys = [bottom - float(p[1]) / k for _, a in raw for p in a if p is not None]
    return min(xs), min(ys), max(xs), max(ys)


SIGN_MIN_P = 0.3
SIGN_MAX_H = 15.5        # tallest sign piece, pt: a ق with its two dots is 13.2 (13.0 dropped them, e.g. 2:74:32 on page 11)
TC_MODEL = None
_CLF = {}


def _sign_prob(n: int, box_pt, sym: str) -> float:
    """The Shamarly waqf classifier's probability that the ink in box_pt (PDF points) is the sign `sym`."""
    return float(_sign_probs(n, box_pt).get(sym, 0.0))


def _sign_probs(n: int, box_pt) -> dict:
    """The classifier's probability of every class (signs and, when the model has it, none) for the ink in box_pt."""
    import cv2
    sys.path.insert(0, str(ROOT))
    from pipeline.cv_waqf.candidates import Candidate, crop_candidate
    from pipeline.cv_waqf.classify import GlyphClassifier
    from pipeline.cv_waqf.config import CROP_SIZE, resolve_edition_model
    if 'clf' not in _CLF:
        _CLF['clf'] = GlyphClassifier(model_path=resolve_edition_model('الشمرلي')[0])
    if _CLF.get('page') != n:
        _CLF['page'] = n
        _CLF['gray'] = cv2.imread(str(ROOT / 'data' / 'refs' / 'shamarly_pdf' / 'cache' / f'p{n:03d}_w1024.jpg'),
                                  cv2.IMREAD_GRAYSCALE)
    clf = _CLF['clf']
    s = DET_WIDTH / 595.22
    # the detector classifies fixed 24 px windows (pad 4); give it the same view, centred on the candidate
    cx, cy = (box_pt[0] + box_pt[2]) / 2 * s, (box_pt[1] + box_pt[3]) / 2 * s
    side = max(24, int(round(max(box_pt[2] - box_pt[0], box_pt[3] - box_pt[1]) * s)) + 2)
    cand = Candidate(int(round(cx - side / 2)), int(round(cy - side / 2)), side, side, side * side)
    crop = crop_candidate(_CLF['gray'], cand, size=CROP_SIZE)
    _label, _conf, probs = clf.predict_many_probs([crop])[0]
    names = clf.symbol_classes if len(probs) == len(clf.symbol_classes) else clf.classes
    return {str(a): float(b) for a, b in zip(names, probs)}


def _banner_name(n: int, top: float, bot: float, bx0: float, bx1: float):
    """The banner's lettering (surah name, its ayah count): the filled vector drawings in the middle cartouche.
    The ornamental frame (strokes, wide fills) stays out: QVP draws one ink, the viewer dresses the banner."""
    import pymupdf
    pg = pymupdf.open(PDF)[n - 1]
    mid0, mid1 = bx0 + 0.25 * (bx1 - bx0), bx1 - 0.25 * (bx1 - bx0)
    out = []
    for dr in pg.get_drawings():
        r, fill = dr['rect'], dr.get('fill')
        if not fill or 'f' not in dr['type'] or not (top - 2 <= r.y0 and r.y1 <= bot + 2):
            continue
        if not (mid0 <= (r.x0 + r.x1) / 2 <= mid1) or r.width > 0.5 * (bx1 - bx0) or max(fill) > 0.9:
            continue
        segs, last = [], None
        f = lambda p: f'{p.x:.2f} {p.y:.2f}'
        for it in dr['items']:
            if it[0] == 're':
                q = it[1]
                segs.append(f'M {q.x0:.2f} {q.y0:.2f} L {q.x1:.2f} {q.y0:.2f} L {q.x1:.2f} {q.y1:.2f} L {q.x0:.2f} {q.y1:.2f} Z')
                last = None
                continue
            if it[0] == 'qu':
                q = it[1]
                segs.append(f'M {f(q.ul)} L {f(q.ur)} L {f(q.lr)} L {f(q.ll)} Z')
                last = None
                continue
            start = it[1]
            if last is None or abs(start.x - last.x) > 1e-3 or abs(start.y - last.y) > 1e-3:
                if segs and last is not None:
                    segs.append('Z')
                segs.append(f'M {f(start)}')
            if it[0] == 'l':
                segs.append(f'L {f(it[2])}')
                last = it[2]
            elif it[0] == 'c':
                segs.append(f'C {f(it[2])} {f(it[3])} {f(it[4])}')
                last = it[4]
        if last is not None:
            segs.append('Z')
        if segs:
            out.append((' '.join(segs), bool(dr.get('even_odd'))))
    return out


TEMPLATES: dict[str, list] = {}      # symbol -> [(normalised mask, aspect)] of signs confirmed in this print
TEMPLATE_FILE = WAQF / 'templates.npz'
SHAPE_MAX = 0.24          # a detector sign's cluster vs this print's confirmed signs
COLUMN_SHAPE_MAX = 0.15   # a sign found only from the column must look like one: no detector behind it


def _group_mask(raws, k, x0, bottoms):
    """Binary mask of a set of outlines (line-font recordings), 10 px per PDF point; holes cut out."""
    import cv2
    import numpy as np
    polys = []
    for raw, bottom in zip(raws, bottoms):
        pts, cur = [], None
        for op, args in raw:
            ps = [(float(p[0]) / k + x0, bottom - float(p[1]) / k) for p in args if p is not None]
            if op == 'moveTo':
                cur = ps[0]; pts.append([cur])
            elif op in ('lineTo', 'qCurveTo', 'curveTo') and ps and pts:
                if op == 'curveTo' and len(ps) == 3:
                    a, b, c = ps
                    for t in (0.25, 0.5, 0.75, 1.0):
                        u = 1 - t
                        pts[-1].append((u**3 * cur[0] + 3*u*u*t*a[0] + 3*u*t*t*b[0] + t**3 * c[0],
                                        u**3 * cur[1] + 3*u*u*t*a[1] + 3*u*t*t*b[1] + t**3 * c[1]))
                    cur = c
                else:
                    pts[-1].extend(ps); cur = ps[-1]
        polys.extend(p for p in pts if len(p) >= 3)
    if not polys:
        return np.zeros((1, 1), bool)
    allp = np.concatenate([np.array(p) for p in polys])
    ox, oy = allp[:, 0].min() - 1, allp[:, 1].min() - 1
    w = int((allp[:, 0].max() - ox + 1) * 10) + 2; h = int((allp[:, 1].max() - oy + 1) * 10) + 2
    mask = np.zeros((h, w), np.uint8)
    for p in polys:
        layer = np.zeros_like(mask)
        cv2.fillPoly(layer, [np.round((np.array(p) - (ox, oy)) * 10).astype(np.int32)], 1)
        mask ^= layer
    return mask.astype(bool)


def _shape(mask):
    from extract_pdf_pages import normalize_shape_mask
    return normalize_shape_mask(mask)


def _shape_dist(shape, sym):
    from extract_pdf_pages import TemplateShape, shape_distance
    from scipy.ndimage import distance_transform_edt
    best = 1.5
    for tm, ta in TEMPLATES.get(sym, []):
        best = min(best, float(shape_distance(shape[0], shape[1], TemplateShape(tm, distance_transform_edt(~tm), ta))))
    return best


def _load_templates():
    import numpy as np
    if TEMPLATES or not TEMPLATE_FILE.exists():
        return
    z = np.load(TEMPLATE_FILE, allow_pickle=True)
    for sym, items in z['templates'].item().items():
        TEMPLATES[sym] = [(m, float(a)) for m, a in items]


def _save_templates():
    import numpy as np
    np.savez_compressed(TEMPLATE_FILE, templates=np.array({k: v[:40] for k, v in TEMPLATES.items()}, dtype=object))


VX0 = 82.0                # the page's left edge in PDF points (the SVG viewBox origin)
TAJWEED = os.environ.get('SHAMARLY_TAJWEED', '1') != '0'
TJ_OFFSET_PX = float(os.environ.get('TJ_OFFSET_PX', '32'))   # Kraken's letter positions sit ~32 px (300 dpi) off the printed letters
_TJ: dict = {}


def _tajweed_state():
    """Rule data, the Kraken helpers and the PDF, loaded once."""
    if not _TJ:
        import pymupdf
        import shamarly_kraken_partition as K
        import shamarly_tajweed as TJ
        _TJ.update(K=K, TJ=TJ, tj=TJ.Tajweed(lambda c: K.MAP.get(K.base(c), K.base(c)), K.is_letter),
                   doc=pymupdf.open(PDF), ayah_words={})
    return _TJ


def _ayah_words(keys, ak):
    st = _tajweed_state()
    if ak not in st['ayah_words']:
        st['ayah_words'][ak] = [(wi, t) for wi, (k, t) in keys.items() if k.rsplit(':', 1)[0] == ak
                                and any(st['K'].is_letter(c) for c in t)]
    return st['ayah_words'][ak]


def line_tajweed(n, ln, words, keys, RAW, BOX, COMP, OWNER, sign_of, line_of, key_of_owner_word, bottom):
    """({outline id: tajweed class} for the marks, {word_index: [(x0, x1, class)]} for the letters) of one line."""
    import pymupdf
    st = _tajweed_state()
    K, TJ, tj = st['K'], st['TJ'], st['tj']
    outs = [o for o in RAW if line_of[o] == ln]
    if not outs:
        return {}, {}
    lw = [(w['word_index'], keys[w['word_index']][1]) for w in words if w['word_index'] in keys]
    letters = TJ.letter_bounds
    x0 = min(BOX[o][0] for o in outs) - 3
    x1 = max(BOX[o][2] for o in outs) + 3
    png = Path('/tmp') / f'shamarly_tj_line_{os.getpid()}.png'      # one per process: parallel builds shared one file and read each other's lines
    st['doc'][n - 1].get_pixmap(clip=pymupdf.Rect(x0, bottom - 46, x1, bottom + 2), matrix=pymupdf.Matrix(K.Z, K.Z),
                                alpha=False).save(png)
    bounds = letters(png, x0, lw, K, TJ_OFFSET_PX)
    if not bounds:
        return {}, {}
    marks = {}
    for ak in {keys[wi][0].rsplit(':', 1)[0] for wi, _ in lw}:
        marks.update(tj.ayah_marks(ak, _ayah_words(keys, ak)))
    # the writing line: the densest row of the line's ink (letters sit on it; marks hang above or below)
    import cv2
    import numpy as np
    gray = cv2.imread(str(png), cv2.IMREAD_GRAYSCALE)
    rows = np.convolve((gray < 128).sum(axis=1).astype(float), np.ones(9) / 9, 'same')
    body_y = (bottom - 46) + float(rows.argmax()) / K.Z
    wi_of_key = {w['key']: w['word_index'] for w in words}
    res = {}
    hit = set()
    line_wis = {wi for wi, _ in lw}
    targets = {(wi, j, side) for (wi, j), sd in marks.items() if wi in line_wis for side in sd}
    for o in outs:
        if not COMP[o].get('is_mark') or o not in OWNER or o in sign_of:
            continue
        wi = wi_of_key.get(OWNER[o])
        if wi is None:
            continue
        cx = (BOX[o][0] + BOX[o][2]) / 2
        cy = (BOX[o][1] + BOX[o][3]) / 2
        cand = [(j, b) for (w_, j), b in bounds.items() if w_ == wi]
        if not cand:
            continue
        j = min(cand, key=lambda t: 0.0 if t[1][0] <= cx <= t[1][1] else min(abs(cx - t[1][0]), abs(cx - t[1][1])))[0]
        rule = (marks.get((wi, j)) or {}).get('above' if cy < body_y else 'below')
        if rule:
            res[o] = rule[0]
            hit.add((wi, j, 'above' if cy < body_y else 'below'))
    st['cov'] = (len(targets), len(hit & targets))
    # the letters the rules colour: their x-intervals, neighbours of one class merged into one
    lcls = {}
    for ak in {keys[wi][0].rsplit(':', 1)[0] for wi, _ in lw}:
        lcls.update(tj.ayah_letters(ak, _ayah_words(keys, ak)))
    by_word: dict = {}
    for (wi, j), cls in lcls.items():
        if wi in line_wis and (wi, j) in bounds:
            by_word.setdefault(wi, []).append((*bounds[(wi, j)], cls[0]))
    letters_out = {}
    audit = []                                # every (word, letter, class, x-interval) this line paints (TJ_AUDIT_DIR)
    for wi, items in by_word.items():
        for (w2, j), cls in lcls.items():
            if w2 == wi and (wi, j) in bounds:
                chars = [c for c in keys[wi][1] if K.is_letter(c)]
                audit.append({'key': keys[wi][0], 'j': j, 'letter': chars[j] if j < len(chars) else '', 'class': cls[0],
                              'x': [round(bounds[(wi, j)][0], 2), round(bounds[(wi, j)][1], 2)], 'text': keys[wi][1], 'line': ln})
    st['audit_line'] = audit
    for wi, items in by_word.items():
        merged = []
        for xa, xb, c in sorted(items):
            if merged and merged[-1][2] == c and xa - merged[-1][1] < 0.6:
                merged[-1] = (merged[-1][0], xb, c)
            else:
                merged.append((xa, xb, c))
        letters_out[wi] = merged
    st['letters'] = (len(lcls), sum(len(v) for v in letters_out.values()))
    if os.environ.get('TJ_DUMP') == f'{n}:{ln}':
        im = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
        for (wi, j), (xa, xb) in bounds.items():
            cv2.line(im, (int((xa - x0) * K.Z), 0), (int((xa - x0) * K.Z), 14), (0, 160, 0), 2)
        cv2.line(im, (0, int((body_y - (bottom - 46)) * K.Z)), (im.shape[1], int((body_y - (bottom - 46)) * K.Z)), (0, 140, 255), 1)
        for o in outs:
            b_ = BOX[o]
            col = (0, 0, 230) if COMP[o].get('is_mark') else (230, 120, 0)
            cv2.rectangle(im, (int((b_[0] - x0) * K.Z), int((b_[1] - (bottom - 46)) * K.Z)),
                          (int((b_[2] - x0) * K.Z), int((b_[3] - (bottom - 46)) * K.Z)), col, 1)
        cv2.imwrite('/tmp/tj_dump.png', im)
    if os.environ.get('TJ_DIAG'):
        why = collections.Counter()
        for (wi, j, side) in targets - hit:
            b = bounds.get((wi, j))
            mine = [o for o in outs if OWNER.get(o) and wi_of_key.get(OWNER[o]) == wi and COMP[o].get('is_mark') and o not in sign_of]
            if b is None:
                why['letter not placed'] += 1
            elif not mine:
                why['word has no small outline'] += 1
            else:
                inn = [o for o in mine if b[0] <= (BOX[o][0] + BOX[o][2]) / 2 <= b[1]]
                if not inn:
                    why['no small outline in the letter interval'] += 1
                else:
                    sides = {'above' if (BOX[o][1] + BOX[o][3]) / 2 < body_y else 'below' for o in inn}
                    why['outline there but other side' if side not in sides else 'other'] += 1
                    if side not in sides and os.environ.get('TJ_DIAG') == '2':
                        print('  other-side', keys[wi][1], 'letter', j, 'want', side, 'found',
                              [(round((BOX[o][1] + BOX[o][3]) / 2 - body_y, 1), round(BOX[o][2] - BOX[o][0], 1)) for o in inn], file=sys.stderr)
        st.setdefault('why', collections.Counter()).update(why)
    return res, letters_out


def page(n: int) -> dict:
    from pdf_glyph_editor import CONTENT_X0, PDF_TO_FONT, load_page_report
    from pdf_review_store import DEFAULT_OUTPUT_ROOT, load_page_review, page_directory
    from line_moves import line_outlines
    from line_ownership import line_editor_payload

    # SHEMRLY_GLYPH_DB / SHEMRLY_OUTPUT_ROOT point a build at a scratch copy of the database and page folders (dry runs)
    db = sqlite3.connect(os.environ.get('SHEMRLY_GLYPH_DB', SHEMRLY / 'glyph_mappings.db'), timeout=60)
    db.row_factory = sqlite3.Row
    out_root = Path(os.environ['SHEMRLY_OUTPUT_ROOT']) if os.environ.get('SHEMRLY_OUTPUT_ROOT') else DEFAULT_OUTPUT_ROOT
    page_dir = page_directory(RUN, n, out_root)
    report = load_page_report(page_dir)
    review = load_page_review(db, RUN, n, out_root)
    sdb = sqlite3.connect(SHEMRLY / 'quran_script.db')
    keys = {i: (k, t) for i, k, t in sdb.execute('SELECT word_index, word_key, text FROM words')}
    layout = sqlite3.connect(SHEMRLY / 'mushaf_layout_inferred.db').execute(
        'SELECT line_number, line_type, surah_number FROM pages WHERE page_number=? ORDER BY line_number', (n,)).fetchall()
    k = PDF_TO_FONT
    x0 = CONTENT_X0

    signs = []
    wpath = WAQF / f'{n:03d}.json'
    if wpath.exists():
        s = 595.22 / DET_WIDTH
        for m in json.load(open(wpath, encoding='utf-8'))['marks']:
            b = m['box']
            signs.append(((b[0] * s, b[1] * s, b[2] * s, b[3] * s), m['symbol'], m['word_key']))

    import text_check
    global TC_MODEL
    if TC_MODEL is None:
        TC_MODEL = json.loads(text_check.MODEL_PATH.read_text(encoding='utf-8'))
    lines = {int(l['line_number']): l for l in report['lines']}
    stats = {'words': 0, 'paths': 0, 'waqf': 0, 'waqf_signs': len(signs), 'rings': 0,
             'headers': 0, 'empty': [], 'count_ok': 0, 'count_off': [], 'unowned': 0, 'shared': 0, 'lines': len(lines)}
    out = ['VIEWBOX']
    frag = {}

    # 1. every outline of every text line, in page points, with its owner word
    RAW, COMP, OWNER, BOX, BOTTOM, PAYLOAD = {}, {}, {}, {}, {}, {}
    for ln, ltype, _sid in layout:
        line = lines.get(ln)
        if ltype == 'surah_name' or line is None:
            continue
        BOTTOM[ln] = float(line['bbox'][3])
        payload = PAYLOAD[ln] = line_editor_payload(db, RUN, n, page_dir, report, ln, review)
        comp = {c['id']: c for c in payload['components']}
        for suffix, raw, _p in line_outlines(page_dir, report, ln):
            oid = f'L{ln}:{suffix}'
            RAW[oid], COMP[oid] = raw, comp.get(oid, {})
            BOX[oid] = _bbox_pt(raw, k, x0, BOTTOM[ln])
            ks = payload['owners'].get(oid) or []
            if not ks:
                stats['unowned'] += 1
                continue
            if len(ks) > 1:
                stats['shared'] += 1
                stats.setdefault('shared_outlines', []).append({'oid': oid, 'owners': list(ks), 'line': ln})
            OWNER[oid] = ks[0]
        for oid, c in comp.items():          # a hole goes with the outline it sits in
            host = c.get('hole_of')
            if host and host in OWNER:
                OWNER[oid] = OWNER[host]
    line_of = {oid: int(oid[1:].split(':')[0]) for oid in RAW}
    # An outline nobody owns would be ink missing from the page (a lost dot or harakat): it goes to the nearest word of
    # its line when one's ink is within ADOPT_PT, and is listed (adopted / unowned_left) so it can be looked at.
    stats['adopted'], stats['unowned_left'] = [], []
    for oid in [o for o in RAW if o not in OWNER]:
        ln_ = line_of[oid]
        near = []
        for o2, key2 in OWNER.items():
            if line_of[o2] == ln_ and o2 != oid:
                bx_, by_ = BOX[oid], BOX[o2]
                dx = max(bx_[0] - by_[2], by_[0] - bx_[2], 0.0)
                dy = max(bx_[1] - by_[3], by_[1] - bx_[3], 0.0)
                near.append((dx + 0.5 * dy, key2))
        best = min(near, default=None)
        if best and best[0] <= ADOPT_PT:
            OWNER[oid] = best[1]
            stats['adopted'].append([oid, best[1], [round(v, 1) for v in BOX[oid]]])
        else:
            stats['unowned_left'].append([oid, [round(v, 1) for v in BOX[oid]]])
    for oid, c in COMP.items():              # holes follow a host that was just adopted
        host = c.get('hole_of')
        if host and host in OWNER and oid not in OWNER:
            OWNER[oid] = OWNER[host]
    # Words that own no ink at all (their pieces are fused into a neighbour's outline): record the big outlines of the two
    # neighbouring words (the one read before, to the right, and the one read after, to the left) with their paths, for the
    # knife pilot (stats['empty_ctx']). The cell is only a rough guide to where the word sits.
    stats['empty_ctx'] = []
    kinds_ = {ln_: lt_ for ln_, lt_, _s in layout}
    for ln_, payload in PAYLOAD.items():
        if kinds_.get(ln_) != 'ayah':
            continue
        order = sorted(payload['words'], key=lambda w: -w['cell'][0])                 # reading order, right to left
        have = {OWNER[o] for o in OWNER if line_of[o] == ln_ and not (COMP[o] or {}).get('hole_of')}
        for i_, w_ in enumerate(order):
            if w_['key'] in have:
                continue
            c0, c1 = sorted((w_['cell'][0] / k + x0, w_['cell'][1] / k + x0))
            neigh = {}
            for side, j_ in (('right', i_ - 1), ('left', i_ + 1)):
                if 0 <= j_ < len(order):
                    nk = order[j_]['key']
                    outs = [{'oid': o, 'box': [round(v, 2) for v in BOX[o]], 'd': _d(RAW[o], PDF_TO_FONT, CONTENT_X0, BOTTOM[ln_])}
                            for o in OWNER if line_of[o] == ln_ and OWNER[o] == nk and not (COMP[o] or {}).get('hole_of')
                            and (BOX[o][2] - BOX[o][0]) * (BOX[o][3] - BOX[o][1]) >= 25]
                    neigh[side] = {'word': nk, 'word_index': order[j_]['word_index'], 'outlines': outs}
            stats['empty_ctx'].append({'word': w_['key'], 'word_index': w_['word_index'], 'line': ln_, 'cell': [round(c0, 2), round(c1, 2)],
                                       'neighbours': neigh})
    key_of_owner = {}                        # owner key ('word:123') -> word_key
    for ln, payload in PAYLOAD.items():
        for w in payload['words']:
            key_of_owner[w['key']] = keys.get(w['word_index'], ('0:0:0', ''))[0]

    # 2. waqf signs, page-wide (a sign can sit in the band of the line above its word). The detector's box is
    # only near the sign (it can sit on the harakat under it), and the detector misses some signs, so every sign
    # of the page's «الشمرلي» column is looked for above its word as well. Candidates are small outlines in the
    # window, each with the outlines whose centre lies inside it (dots, holes); the Shamarly waqf classifier picks
    # the one that reads best as the sign. The whole sign goes to the word that owns its main outline.
    def centre(bx):
        return (bx[0] + bx[2]) / 2, (bx[1] + bx[3]) / 2
    sign_of: dict[str, int] = {}
    found: list[tuple[str, str, tuple]] = []          # (symbol, source, group box) per tagged sign

    # Sign pieces: small outlines (a sign's letters, dots, holes). صلى is wide, so the line font's own is_mark
    # test is not used. Each piece offers a few groupings (alone; with the pieces inside or just above it, ق's
    # dots; with pieces under 0.5 pt away), so a sign is taken whole without swallowing the harakat beside it.
    def small(o):
        b = BOX[o]
        return (b[3] - b[1]) <= SIGN_MAX_H and (b[2] - b[0]) <= 22.0
    pieces = [o for o in RAW if small(o) and o in OWNER]
    near: dict[str, list[str]] = {o: [] for o in pieces}
    for a_i, a in enumerate(pieces):
        A = BOX[a]
        for b in pieces[a_i + 1:]:
            B = BOX[b]
            if line_of[a] == line_of[b] and A[0] - 0.5 <= B[2] and B[0] - 0.5 <= A[2] and A[1] - 0.5 <= B[3] and B[1] - 0.5 <= A[3]:
                near[a].append(b); near[b].append(a)

    def groupings(o):
        out = {frozenset([o])}
        b = BOX[o]
        out.add(frozenset([o] + [q for q in pieces if q != o and line_of[q] == line_of[o]
                                 and b[0] - 1.0 <= centre(BOX[q])[0] <= b[2] + 1.0
                                 and b[1] - 3.0 <= centre(BOX[q])[1] <= b[3] + 0.8
                                 and (BOX[q][2] - BOX[q][0]) * (BOX[q][3] - BOX[q][1]) < 0.6 * (b[2] - b[0]) * (b[3] - b[1])]))
        seen, todo = {o}, [o]
        while todo:
            for q in near[todo.pop()]:
                if q not in seen:
                    seen.add(q); todo.append(q)
        out.add(frozenset(seen))
        return out

    def look(win, sym):
        """(p, main, group, box, shape distance) of the best sign grouping in the window: the classifier's
        probability first (24-px window), then the most complete grouping, then the topmost."""
        groups = set()
        for o in pieces:
            if o not in sign_of and win[0] <= centre(BOX[o])[0] <= win[2] and win[1] <= centre(BOX[o])[1] <= win[3]:
                groups |= {g for g in groupings(o) if not (g & sign_of.keys())}
        scored = []
        for g in groups:
            g = sorted(g)
            gb = (min(BOX[o][0] for o in g), min(BOX[o][1] for o in g), max(BOX[o][2] for o in g), max(BOX[o][3] for o in g))
            # a sign is 6-16 pt across; a lone dot or hole (~2 pt) is not one, however its window scores
            if (gb[2] - gb[0]) > 24 or (gb[3] - gb[1]) > SIGN_MAX_H + 1 or max(gb[2] - gb[0], gb[3] - gb[1]) < 4.0:
                continue
            p = _sign_prob(n, gb, sym)
            if os.environ.get('SIGN_DEBUG'):
                print('   cand', sym, [round(v, 1) for v in gb], len(g), round(p, 3), file=sys.stderr)
            if p >= SIGN_MIN_P:
                scored.append((p, g, gb))
        if not scored:
            return (0.0, None, None, None, 9.0)
        # The 24-px window also sees the sign above a letter, so a letter piece can score as high as the sign.
        # With this print's confirmed signs as templates the closest shape wins (a fuller grouping on near
        # ties); before there are any, the topmost of the best-scoring (signs sit above the letters).
        if TEMPLATES.get(sym):
            rows = [(_shape_dist(_shape(_group_mask([RAW[o] for o in g], k, x0, [BOTTOM[line_of[o]] for o in g])), sym),
                     p, g, gb) for p, g, gb in scored]
            low = min(r[0] for r in rows)
            dist, p, g, gb = max((r for r in rows if r[0] <= low + 0.02), key=lambda r: (len(r[2]), -r[0]))
            return (p, g[0], g, gb, dist)
        top = max(round(p, 2) for p, _g, _gb in scored)
        p, g, gb = min((t for t in scored if round(t[0], 2) == top), key=lambda t: (t[2][1], -len(t[1])))
        return (p, g[0], g, gb, 5.0)

    owner_of_key = {v: k_ for k_, v in key_of_owner.items()}
    colpath = WAQF / f'{n:03d}.column.json'
    col = json.load(open(colpath, encoding='utf-8')) if colpath.exists() else {}

    def column_key(wk, sym):
        """The word the «الشمرلي» column gives this sign: the detector's own key can be a word off, and the
        outline nearest the sign can belong to the neighbouring word (the sign sits between two words)."""
        if wk in col or not col:
            return wk
        s_, a_, w_ = wk.split(':')
        near = [k_ for k_, v in col.items() if v == sym and k_.rsplit(':', 1)[0] == f'{s_}:{a_}'
                and abs(int(k_.rsplit(':', 1)[1]) - int(w_)) <= 2]
        return near[0] if len(near) == 1 else wk

    def tag(p, main, g, gb, sym, source, wk=None):
        if source == 'detector' and p >= 0.99:
            TEMPLATES.setdefault(sym, []).append(
                _shape(_group_mask([RAW[o] for o in g], k, x0, [BOTTOM[line_of[o]] for o in g])))
        i = len(found)
        found.append((sym, source, gb))
        home = owner_of_key.get(column_key(wk, sym)) if wk else None
        for o in g:
            sign_of[o] = i
            OWNER[o] = home or OWNER[main]
        stats.setdefault('waqf_p', []).append(round(p, 2))

    misses = []
    for sb, sym, wk in signs:                      # detector marks
        if os.environ.get('SIGN_DEBUG'):
            w_ = (sb[0] - 22, sb[1] - 14, sb[2] + 22, sb[3] + 1)
            for o in RAW:
                b_ = BOX[o]
                if w_[0] <= (b_[0] + b_[2]) / 2 <= w_[2] and w_[1] <= (b_[1] + b_[3]) / 2 <= w_[3]:
                    print('   ink', wk, sym, o, [round(v, 1) for v in b_], 'owned' if o in OWNER else 'UNOWNED',
                          'small' if small(o) else 'big', file=sys.stderr)
        p, main, g, gb, dist = look((sb[0] - 22, sb[1] - 14, sb[2] + 22, sb[3] + 1), sym)
        if main:
            tag(p, main, g, gb, sym, 'detector', wk)
            stats.setdefault('det_dist', []).append(round(dist, 3) if dist < 5 else None)
        else:
            misses.append(['detector', wk, sym, round(p, 2), round(dist, 3)])
    stats['column_signs'] = len(col)
    ink_of_key: dict[str, list[str]] = {}
    for o, ow in OWNER.items():
        if o not in sign_of and not COMP[o].get('is_mark'):
            ink_of_key.setdefault(key_of_owner.get(ow, ''), []).append(o)
    stats['column_added'] = []
    for wk, sym in col.items():
        body = ink_of_key.get(wk)
        if not body or sym not in WAQF_MARK:
            if body is None:
                misses.append(['column', wk, sym, 'word not on page'])
            continue
        owned = [o for o, ow in OWNER.items() if key_of_owner.get(ow) == wk]      # the split may hand it the sign
        wx0 = min(BOX[o][0] for o in owned); wx1 = max(BOX[o][2] for o in owned)
        wy0 = min(BOX[o][1] for o in body); wy1 = max(BOX[o][3] for o in body)
        win = (wx0 - 8, wy0 - 18, wx1 + 8, wy0 + 0.45 * (wy1 - wy0))
        # already tagged near this word? (the same sign within ~25 pt; the column and the detector's word keys
        # can differ by a word, and a sign can sit in the band of the line above)
        if any(s_ == sym and win[0] - 25 <= centre(gb)[0] <= win[2] + 25 and win[1] - 8 <= centre(gb)[1] <= win[3] + 8
               for s_, _src, gb in found):
            continue
        if os.environ.get('SIGN_DEBUG'):
            print('COLUMN', wk, sym, [round(v, 1) for v in win], file=sys.stderr)
        p, main, g, gb, dist = look(win, sym)
        # without the detector, the shape must agree too: a harakah near a real sign can pass the classifier
        if main and dist < COLUMN_SHAPE_MAX:
            tag(p, main, g, gb, sym, 'column', wk)
            stats['column_added'].append([wk, sym, round(p, 2), round(dist, 3)])
        else:
            misses.append(['column', wk, sym, round(p, 2), round(dist, 3)])
    stats['waqf_missed'] = misses
    if os.environ.get('SIGN_AUDIT'):
        # recall audit: every sign-sized group of outlines the page still has unclaimed, with the classifier's view
        audit = {'tagged': [{'sym': sym, 'src': src, 'box': [round(v, 2) for v in gb]} for sym, src, gb in found],
                 'unclaimed': []}
        seen_boxes = set()
        for o in pieces:
            if o in sign_of:
                continue
            for g in groupings(o):
                if g & sign_of.keys():
                    continue
                g = sorted(g)
                gb = (min(BOX[q][0] for q in g), min(BOX[q][1] for q in g), max(BOX[q][2] for q in g), max(BOX[q][3] for q in g))
                if (gb[2] - gb[0]) > 24 or (gb[3] - gb[1]) > SIGN_MAX_H + 1 or max(gb[2] - gb[0], gb[3] - gb[1]) < 4.0:
                    continue
                key = tuple(round(v, 1) for v in gb)
                if key in seen_boxes:
                    continue
                seen_boxes.add(key)
                pr = _sign_probs(n, gb)
                sym, p = max(((a, b) for a, b in pr.items() if a != 'none'), key=lambda t: t[1])
                audit['unclaimed'].append({'sym': sym, 'p': round(p, 3), 'none': round(pr.get('none', 0.0), 3),
                                           'box': [round(v, 2) for v in gb], 'line': line_of[o], 'n': len(g),
                                           'word': key_of_owner.get(OWNER.get(o, ''), '')})
        adir = ROOT / 'artifacts' / 'shamarly-qvp' / 'audit'
        adir.mkdir(parents=True, exist_ok=True)
        (adir / f'{n:03d}.json').write_text(json.dumps(audit, ensure_ascii=False), encoding='utf-8')

    def sign_for(oid):
        return sign_of.get(oid)

    # 3. the page
    tj_side: dict[str, list[str]] = {}
    tj_letters: dict[str, list] = {}
    audit_rows: list = []
    for ln, ltype, sid in layout:
        if ltype == 'surah_name':
            # the banner sits between the neighbouring text lines; the viewer draws it (box), its lettering kept
            above = max((l['bbox'][3] for m, l in lines.items() if m < ln), default=None)
            below = min((l['bbox'][1] for m, l in lines.items() if m > ln), default=None)
            top = above if above is not None else (below - 1.9 * 43.0)
            bot = below if below is not None else top + 1.9 * 43.0
            bx0, bx1 = 88.0, 517.0
            out.append(f'<g class="surah-name" data-line="{ln}" data-sid="{sid or ""}" '
                       f'data-box="{bx0:.1f} {top:.1f} {bx1 - bx0:.1f} {bot - top:.1f}">')
            for d, evenodd in _banner_name(n, top, bot, bx0, bx1):
                out.append(f'<path data-kind="header_ink"{" fill-rule=\"evenodd\"" if evenodd else ""} d="{d}"/>')
            out.append('</g>')
            stats['headers'] += 1
            continue
        if ln not in PAYLOAD:
            continue
        payload = PAYLOAD[ln]
        D = lambda o: _d(RAW[o], k, x0, BOTTOM[line_of[o]])
        words = sorted(payload['words'], key=lambda w: -w['cell'][0])        # reading order
        if ltype == 'basmallah':
            ink = [o for o in RAW if line_of[o] == ln and o in OWNER]
            out.append(f'<g class="basmalah" data-line="{ln}">')
            if ink:
                out.append('<path data-kind="header_ink" d="' + ' '.join(D(o) for o in ink) + '"/>')
            out.append('</g>')
            stats['headers'] += 1
            continue
        tj_of, tj_letters_of = {}, {}
        if TAJWEED and ltype == 'ayah':
            try:
                tj_of, tj_letters_of = line_tajweed(n, ln, words, keys, RAW, BOX, COMP, OWNER, sign_of, line_of, None, BOTTOM[ln])
                tt, th = _TJ['cov']
                # letter positions that fall off the page (or are twice as wide as a letter) mean the line's letter
                # finder lost its place: no colours on that line beats colours on the wrong letters
                bad = any(a < VX0 - 3 or b > 526 or b - a > 60 for iv in tj_letters_of.values() for a, b, _c in iv)
                if bad:
                    stats.setdefault('tj_bad_lines', []).append(ln)
                    tj_of, tj_letters_of = {}, {}
                else:
                    audit_rows.extend(_TJ.get('audit_line', []))
                    stats['tj_targets'] = stats.get('tj_targets', 0) + tt
                    stats['tj_hit'] = stats.get('tj_hit', 0) + th
            except Exception as exc:                          # a line without colours, not a failed page
                print('tajweed skip', n, ln, exc, file=sys.stderr)
        out.append(f'<g class="line" data-line="{ln}">')
        open_ayah = None
        for w in words:
            wi = w['word_index']
            wkey, text = keys.get(wi, ('0:0:0', w.get('token') or ''))
            s_, a_, _ = wkey.split(':')
            ak = f'{s_}:{a_}'
            mine = [o for o in RAW if OWNER.get(o) == w['key']]
            if text and set(text) <= DIGITS | {'۝'}:
                if open_ayah:
                    out.append('</g>')
                    open_ayah = None
                if not mine:                                   # a ring with no ink would be an empty group qvp-convert can't encode
                    stats.setdefault('ringless', []).append(ak)
                    continue
                rid = f'ayah-mark-{n}-{ak.replace(":", "-")}'
                out.append(f'<g class="ayah-mark" id="{rid}" data-ayah-key="{ak}">')
                out.append('<path data-kind="ayah_mark_ornament" d="' + ' '.join(D(o) for o in mine) + '"/>')
                out.append('</g>')
                frag[ak] = rid
                stats['rings'] += 1
                continue
            if open_ayah != ak:
                if open_ayah:
                    out.append('</g>')
                out.append(f'<g class="ayah-fragment" data-ayah-key="{ak}">')
                open_ayah = ak
            out.append(f'<g class="word" data-word-key="{wkey}" data-word-id="{wi}" '
                       f'data-rasm-uthmani="{escape(text, quote=True)}">')
            body, waqf = [], {}
            for o in mine:
                si = sign_for(o)
                if si is None:
                    body.append(o)
                else:
                    waqf.setdefault(si, []).append(o)
            tjm: dict[str, list[str]] = collections.OrderedDict()
            if tj_of:
                for o in body:
                    if o in tj_of:
                        tjm.setdefault(tj_of[o], []).append(o)
                body = [o for o in body if o not in tj_of]
            # A counter must be cut from its own letter only. All outlines of a word in one path overlap where letters
            # touch, so a counter under a neighbour's outline fills in (nonzero) or the overlaps are punched out
            # (even-odd): each body outline gets its own path with its own holes, and a hole goes with its host even
            # when the host is a tajweed mark or sign (the pipeline's hole_of).
            groups = {'body': body, 'waqf': waqf, 'tj': tjm}
            where = {o: ('body', None) for o in body}
            where.update({o: ('waqf', si) for si, os_ in waqf.items() for o in os_})
            where.update({o: ('tj', cls) for cls, os_ in tjm.items() for o in os_})
            for o in [o for o in where if (COMP.get(o) or {}).get('hole_of') in where]:
                host = COMP[o]['hole_of']
                if where[o] != where[host]:
                    kind, key = where[o]
                    (groups[kind][key] if key is not None else groups[kind]).remove(o)
                    kind, key = where[host]
                    (groups[kind][key] if key is not None else groups[kind]).append(o)
                    where[o] = where[host]
            held = {o for o in body if (COMP.get(o) or {}).get('hole_of') in where and where[COMP[o]['hole_of']] == ('body', None)}
            body_paths, slivers = [], []
            for o in body:
                if o in held:
                    continue
                bx = BOX[o]
                if bx[2] - bx[0] < 0.1 or bx[3] - bx[1] < 0.1:         # a zero-width contour: qvp-convert cannot box it alone
                    slivers.append(o)
                    continue
                body_paths.append([o] + [h for h in held if COMP[h]['hole_of'] == o])
            # an outline the pipeline did not flag as a hole but that is wound against the letter it sits in (area < 0) is
            # filled in when it stands alone in its own path: it goes into the smallest body path whose outline surrounds it
            def _signed_area(o):
                nums = [float(v) for v in re.findall(r'-?\d+\.?\d*', D(o))]
                pts = list(zip(nums[0::2], nums[1::2]))
                return sum(pts[i][0] * pts[(i + 1) % len(pts)][1] - pts[(i + 1) % len(pts)][0] * pts[i][1] for i in range(len(pts))) / 2
            for grp in [g for g in body_paths if len(g) == 1 and _signed_area(g[0]) < 0]:
                cx, cy = (BOX[grp[0]][0] + BOX[grp[0]][2]) / 2, (BOX[grp[0]][1] + BOX[grp[0]][3]) / 2
                hosts = [g for g in body_paths if g is not grp and BOX[g[0]][0] <= cx <= BOX[g[0]][2] and BOX[g[0]][1] <= cy <= BOX[g[0]][3]
                         and _signed_area(g[0]) > 0]
                if hosts:
                    min(hosts, key=lambda g: (BOX[g[0]][2] - BOX[g[0]][0]) * (BOX[g[0]][3] - BOX[g[0]][1])).extend(grp)
                    body_paths.remove(grp)
                    stats['holes_merged'] = stats.get('holes_merged', 0) + 1
            if slivers:
                (body_paths[0] if body_paths else body_paths.append([]) or body_paths[0]).extend(slivers)
            for group in body_paths:
                out.append('<path data-kind="body" d="' + ' '.join(D(x) for x in group) + '"/>')
                stats['paths'] += 1
            for si, os_ in waqf.items():
                if not os_:                                    # its outlines were holes that went to their hosts
                    continue
                out.append(f'<path data-kind="mark" data-mark="{WAQF_MARK.get(found[si][0], "")}" '
                           f'data-mark-family="waqf" d="' + ' '.join(D(o) for o in os_) + '"/>')
                stats['paths'] += 1
                stats['waqf'] += 1
            if wi in tj_letters_of:                            # page-space x (the viewBox starts at VX0)
                tj_letters[wkey] = [[round(a - VX0, 2), round(b - VX0, 2), c] for a, b, c in tj_letters_of[wi]]
                stats['tajweed_letters'] = stats.get('tajweed_letters', 0) + len(tj_letters[wkey])
            for cls, os_ in tjm.items():                      # tajweed-coloured marks: their own paths, in this order
                if not os_:                                    # a class whose only outlines were holes of other paths
                    continue
                out.append('<path data-kind="mark" data-mark="" data-mark-family="diacritic" d="'
                           + ' '.join(D(o) for o in os_) + '"/>')
                tj_side.setdefault(wkey, []).append(cls)
                stats['paths'] += 1
                stats['tajweed_marks'] = stats.get('tajweed_marks', 0) + len(os_)
            if not body:
                stats['empty'].append(wkey)
            # ShemrlyMushaf's text check: a correctly cut word has the outline counts its text predicts
            # (flags ~94% of wrong words on its blind eval pages); the waqf sign may or may not be in the text
            tot = len(mine)
            small = sum(1 for o in mine if (BOX[o][3] - BOX[o][1]) < 9.0
                        and (BOX[o][2] - BOX[o][0]) * (BOX[o][3] - BOX[o][1]) < 28.0)
            nw = sum(len(v) for v in waqf.values())
            need = text_check.predict(TC_MODEL, text)
            if need in ((tot, small), (tot - nw, small - nw)):
                stats['count_ok'] += 1
            else:
                stats['count_off'].append(wkey)
            out.append('</g>')
            stats['words'] += 1
        if open_ayah:
            out.append('</g>')
        out.append('</g>')
    out.append('</svg>')

    ys0 = [float(l['bbox'][1]) for l in lines.values()]
    ys1 = [float(l['bbox'][3]) for l in lines.values()]
    box_tops = [float(m.group(1)) for m in re.finditer(r'data-box="[\d.]+ ([\d.]+) ', '\n'.join(out))]
    vy0 = min(ys0 + box_tops) - 6
    vy1 = max(ys1) + 6
    vx0, vx1 = VX0, 523.0
    out[0] = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{vx0:.1f} {vy0:.1f} {vx1 - vx0:.1f} {vy1 - vy0:.1f}" '
              f'data-page="{n}" data-edition="shamarly">')
    svg = '\n'.join(out)
    for ak, rid in frag.items():
        svg = svg.replace(f'class="ayah-fragment" data-ayah-key="{ak}">',
                          f'class="ayah-fragment" data-ayah-key="{ak}" data-ayah-mark="{rid}">')
    OUT.mkdir(parents=True, exist_ok=True)
    if os.environ.get('TJ_AUDIT_DIR'):
        Path(os.environ['TJ_AUDIT_DIR']).mkdir(parents=True, exist_ok=True)
        (Path(os.environ['TJ_AUDIT_DIR']) / f'{n:03d}.json').write_text(json.dumps(audit_rows, ensure_ascii=False), encoding='utf-8')
    (OUT / f'{n:03d}.tajweed.json').write_text(json.dumps({'marks': tj_side, 'letters': tj_letters}, ensure_ascii=False), encoding='utf-8')
    (OUT / f'{n:03d}.svg').write_text(svg, encoding='utf-8')
    for so in stats.get('shared_outlines', []):                  # the joined outlines, for the knife pilot (shamarly_cut_pilot.py)
        so['d'] = _d(RAW[so['oid']], PDF_TO_FONT, CONTENT_X0, BOTTOM[line_of[so['oid']]])
        so['box'] = [round(v, 2) for v in BOX[so['oid']]]
    stats['bytes'] = len(svg.encode())
    (OUT / f'{n:03d}.json').write_text(json.dumps(stats, ensure_ascii=False), encoding='utf-8')
    return stats


if __name__ == '__main__':
    _load_templates()
    for arg in sys.argv[1:]:
        print(arg, page(int(arg)), flush=True)
    _save_templates()
