"""Shamarly pages as quran-svg-structured SVGs straight from the vector PDF (beta pilot, like qatar_qvp_svg.py).

No tracing: the Shamarly print is a vector PDF (ShemrlyMushaf/BOOK_27111_1.pdf), so every word is drawn with the
PDF's own outlines. Which outline belongs to which word comes from ShemrlyMushaf's batch-rest run: each line's
outlines (L{line}:C{k}, the line font after knife cuts and moves) and their owners as glyph_mappings.db holds them
now (reviewer decisions + the word-owner model's auto-accept), via line_ownership.line_editor_payload.

Written in the structure quran-engine's svg2qvp reads: line > ayah-fragment > word > path[data-kind, data-mark,
data-mark-family]. A verse number token (٥) is the ayah-mark decoration that ends its fragment. Waqf signs: the
Shamarly CV detector says which sign is near where, but its box can sit on the harakat under the sign; the small
outlines in a window around it (each with the dots inside it) are scored by the same Shamarly classifier and the best
one becomes a mark of family "waqf", so the renderer's hideWaqf hides it. Basmalas are header_ink; the surah banner
keeps its lettering (name, ayah count) as header_ink and leaves the ornamental frame to the viewer (data-box).
Each word also gets ShemrlyMushaf's text check (outline counts the text predicts): count_ok / count_off in the stats.

Units are PDF points; the viewBox is the text block.

    /opt/homebrew/bin/python3 -m pipeline.cv_waqf.run_page --edition الشمرلي --page 42 \\
        --json-out artifacts/shamarly-qvp/waqf/042.json
    ~/Development/ShemrlyMushaf/.venv/bin/python pipeline/paw_split/shamarly_qvp_svg.py 4 42 ...
        -> artifacts/shamarly-qvp/svg/NNN.svg (+ NNN.json stats)
    qvp-convert svg2qvp svg/042.svg qvp/042.qvp qvp/042.words.json     # quran-engine crates/qvp-convert (v0.8.0)
        -> artifacts/shamarly-qvp/qvp/, served by /api/shamarly/qvp/NNN.qvp to the reader's «رسم الملف (تجريبي)»

Pilot (2026-11-05, pages 4 42 50 77 100 145 150 187 300 404): 1,499 words, every outline owned; svg→qvp→svg
round trip within 1 px; 90/90 printed signs tagged (2 detector false marks rejected, p≈0); text check passes
42.5% of words (ShemrlyMushaf: ~97% precise; the rest are unchecked, not wrong). Ownership on these pages is the
word-owner model's auto-accept (~91% exact on its blind eval): page ink is exact, word boundaries may be off by a mark.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SHEMRLY = Path(os.environ.get('SHEMRLY_ROOT', Path.home() / 'Development' / 'ShemrlyMushaf'))
sys.path.insert(0, str(SHEMRLY))
RUN = os.environ.get('SHEMRLY_RUN', 'batch-rest')
OUT = Path(os.environ.get('SHAMARLY_SVG_OUT', ROOT / 'artifacts' / 'shamarly-qvp' / 'svg'))
WAQF = ROOT / 'artifacts' / 'shamarly-qvp' / 'waqf'
PDF = SHEMRLY / 'BOOK_27111_1.pdf'
DET_WIDTH = 1024.0       # the detector reads data/refs/shamarly_pdf/cache/pNNN_w1024.jpg (whole PDF page)
WAQF_MARK = {'ج': 'waqf_jaiz_mustawi_al_tarafayn', 'ق': 'waqf_jaiz_waqf_awla', 'ص': 'waqf_jaiz_wasl_awla',
             'م': 'waqf_lazim', 'ع': 'waqf_al_muanaqah', 'س': 'saktah',
             'لا': ''}   # QVP's mark taxonomy has no «لا» (the new Madinah print has none): family waqf, mark none
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
TC_MODEL = None
_CLF = {}


def _sign_prob(n: int, box_pt, sym: str) -> float:
    """The Shamarly waqf classifier's probability that the ink in box_pt (PDF points) is the sign `sym`."""
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
    return float(dict(zip(names, probs)).get(sym, 0.0))


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


def page(n: int) -> dict:
    from pdf_glyph_editor import CONTENT_X0, PDF_TO_FONT, load_page_report
    from pdf_review_store import DEFAULT_OUTPUT_ROOT, load_page_review, page_directory
    from line_moves import line_outlines
    from line_ownership import line_editor_payload

    db = sqlite3.connect(SHEMRLY / 'glyph_mappings.db', timeout=60)
    db.row_factory = sqlite3.Row
    page_dir = page_directory(RUN, n, DEFAULT_OUTPUT_ROOT)
    report = load_page_report(page_dir)
    review = load_page_review(db, RUN, n, DEFAULT_OUTPUT_ROOT)
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
    stats = {'words': 0, 'paths': 0, 'waqf': 0, 'waqf_signs': len(signs), 'waqf_unmatched': [], 'rings': 0,
             'headers': 0, 'empty': [], 'count_ok': 0, 'count_off': [], 'unowned': 0, 'shared': 0, 'lines': len(lines)}
    out = ['VIEWBOX']
    frag = {}
    used_signs = set()
    best_low = {}

    for ln, ltype, sid in layout:
        if ltype == 'surah_name':
            # the banner sits between the neighbouring text lines; the viewer draws it (box), black ink kept
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
        line = lines.get(ln)
        if line is None:
            continue
        bottom = float(line['bbox'][3])
        payload = line_editor_payload(db, RUN, n, page_dir, report, ln, review)
        raws = {f'L{ln}:{suffix}': raw for suffix, raw, _p in line_outlines(page_dir, report, ln)}
        comp = {c['id']: c for c in payload['components']}
        key_of = {w['key']: w for w in payload['words']}
        owner = {}
        for oid in raws:
            ks = payload['owners'].get(oid) or []
            if not ks:
                stats['unowned'] += 1
                continue
            if len(ks) > 1:
                stats['shared'] += 1
            owner[oid] = ks[0]
        # a hole goes with the outline it sits in
        for oid, c in comp.items():
            host = c.get('hole_of')
            if host and host in owner:
                owner[oid] = owner[host]
        boxes = {oid: _bbox_pt(raw, k, x0, bottom) for oid, raw in raws.items()}

        # The detector's box (~14 pt) is only near the sign: it can sit on the harakat under it. Candidates are the
        # small outlines in a window reaching up from the box, each with the outlines whose centre lies inside it
        # (dots, holes); the waqf classifier picks the candidate that reads best as the detected sign. The whole
        # sign goes to the word that owns its main outline.
        def centre(bx):
            return (bx[0] + bx[2]) / 2, (bx[1] + bx[3]) / 2

        def group_of(main):
            mb = boxes[main]
            return [o for o in raws if o == main or (
                comp.get(o, {}).get('is_mark') and o not in sign_of
                and mb[0] - 0.8 <= centre(boxes[o])[0] <= mb[2] + 0.8 and mb[1] - 0.8 <= centre(boxes[o])[1] <= mb[3] + 0.8)]
        sign_of = {}
        for i, (sb, sym, _wk) in enumerate(signs):
            if i in used_signs:
                continue
            cand = [o for o in raws if comp.get(o, {}).get('is_mark') and o in owner and o not in sign_of
                    and sb[0] - 22 <= centre(boxes[o])[0] <= sb[2] + 22 and sb[1] - 14 <= centre(boxes[o])[1] <= sb[3] + 1]
            if not cand:
                continue
            scored = []
            for main in cand:
                g = group_of(main)
                gx0 = min(boxes[o][0] for o in g); gy0 = min(boxes[o][1] for o in g)
                gx1 = max(boxes[o][2] for o in g); gy1 = max(boxes[o][3] for o in g)
                scored.append((_sign_prob(n, (gx0, gy0, gx1, gy1), sym), main, g))
            p, main, g = max(scored, key=lambda t: t[0])
            if p < SIGN_MIN_P:
                best_low[i] = max(best_low.get(i, 0.0), p)
                continue
            stats.setdefault('waqf_p', []).append(round(p, 2))
            for o in g:
                sign_of[o] = i
                owner[o] = owner[main]
            used_signs.add(i)

        def sign_for(oid):
            return sign_of.get(oid)

        words = sorted(payload['words'], key=lambda w: -w['cell'][0])        # reading order
        if ltype == 'basmallah':
            ink = [raws[o] for o in raws if o in owner]
            out.append(f'<g class="basmalah" data-line="{ln}">')
            if ink:
                out.append('<path data-kind="header_ink" d="' + ' '.join(_d(r, k, x0, bottom) for r in ink) + '"/>')
            out.append('</g>')
            stats['headers'] += 1
            continue
        out.append(f'<g class="line" data-line="{ln}">')
        open_ayah = None
        for w in words:
            wi = w['word_index']
            wkey, text = keys.get(wi, ('0:0:0', w.get('token') or ''))
            s_, a_, _ = wkey.split(':')
            ak = f'{s_}:{a_}'
            mine = [o for o in raws if owner.get(o) == w['key']]
            if text and set(text) <= DIGITS | {'۝'}:
                if open_ayah:
                    out.append('</g>')
                    open_ayah = None
                rid = f'ayah-mark-{n}-{ak.replace(":", "-")}'
                out.append(f'<g class="ayah-mark" id="{rid}" data-ayah-key="{ak}">')
                if mine:
                    out.append('<path data-kind="ayah_mark_ornament" d="'
                               + ' '.join(_d(raws[o], k, x0, bottom) for o in mine) + '"/>')
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
            if body:
                out.append('<path data-kind="body" d="' + ' '.join(_d(raws[o], k, x0, bottom) for o in body) + '"/>')
                stats['paths'] += 1
            for si, os_ in waqf.items():
                out.append(f'<path data-kind="mark" data-mark="{WAQF_MARK.get(signs[si][1], "")}" '
                           f'data-mark-family="waqf" d="' + ' '.join(_d(raws[o], k, x0, bottom) for o in os_) + '"/>')
                stats['paths'] += 1
                stats['waqf'] += 1
            if not body:
                stats['empty'].append(wkey)
            # ShemrlyMushaf's text check: a correctly cut word has the outline counts its text predicts
            # (flags ~94% of wrong words on its blind eval pages); the waqf sign may or may not be in the text
            tot = len(mine)
            small = sum(1 for o in mine if (boxes[o][3] - boxes[o][1]) < 9.0
                        and (boxes[o][2] - boxes[o][0]) * (boxes[o][3] - boxes[o][1]) < 28.0)
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
    stats['waqf_unmatched'] = [[signs[i][2], signs[i][1], round(best_low.get(i, 0.0), 2)]
                               for i in range(len(signs)) if i not in used_signs]

    ys0 = [float(l['bbox'][1]) for l in lines.values()]
    ys1 = [float(l['bbox'][3]) for l in lines.values()]
    import re
    box_tops = [float(m.group(1)) for m in re.finditer(r'data-box="[\d.]+ ([\d.]+) ', '\n'.join(out))]
    vy0 = min(ys0 + box_tops) - 6
    vy1 = max(ys1) + 6
    vx0, vx1 = 82.0, 523.0
    out[0] = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{vx0:.1f} {vy0:.1f} {vx1 - vx0:.1f} {vy1 - vy0:.1f}" '
              f'data-page="{n}" data-edition="shamarly">')
    svg = '\n'.join(out)
    for ak, rid in frag.items():
        svg = svg.replace(f'class="ayah-fragment" data-ayah-key="{ak}">',
                          f'class="ayah-fragment" data-ayah-key="{ak}" data-ayah-mark="{rid}">')
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f'{n:03d}.svg').write_text(svg, encoding='utf-8')
    stats['bytes'] = len(svg.encode())
    (OUT / f'{n:03d}.json').write_text(json.dumps(stats, ensure_ascii=False), encoding='utf-8')
    return stats


if __name__ == '__main__':
    for arg in sys.argv[1:]:
        print(arg, page(int(arg)), flush=True)
