"""Kraken-guided word partition of Shamarly lines, scored against the withheld Elgharib glyphs.

The Shamarly lines are vector outlines and the text is known, so the only open question is where each word's
ink starts and ends. A printed-Arabic recogniser (Kraken, ``arabic_best.mlmodel``) reads each line; its
letters are aligned to the known letters, and the gap between the last letter of one word and the first of
the next marks the cut. Outlines go to the cell they fall in whole (a closed contour is never clipped);
small outlines (dots, harakat) go with the nearest letter body.

Scored like ShemrlyMushaf's own pipeline-eval: a word passes when its ink has shape distance < 0.10 to the
withheld Elgharib reference glyph (``gt-eval.json``). Run with ShemrlyMushaf's venv:

    ~/Development/ShemrlyMushaf/.venv/bin/python pipeline/paw_split/shamarly_kraken_partition.py \\
        --pages 204 212 219 ... [--offset 32]
"""
from __future__ import annotations

import argparse
import difflib
import json
import sys
import unicodedata
import warnings
from pathlib import Path

import numpy as np

warnings.filterwarnings('ignore')
SHEMRLY = Path('/Users/mac/Development/ShemrlyMushaf')
sys.path.insert(0, str(SHEMRLY))
sys.path.insert(0, str(SHEMRLY / 'experiments'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from extract_pdf_pages import (DEFAULT_FONT_DIR, DEFAULT_GLYPH_DB, TemplateLibrary,  # noqa: E402
                               normalize_shape_mask, shape_distance)
from line_moves import line_outlines  # noqa: E402
from line_ownership import is_mark  # noqa: E402
from pdf_glyph_editor import CONTENT_X0, PDF_TO_FONT, load_page_report, _line_entry  # noqa: E402
from shamarly_qvp_svg import _bbox_pt, _group_mask  # noqa: E402

PDF = SHEMRLY / 'BOOK_27111_1.pdf'
EVAL = SHEMRLY / 'output' / 'pdf' / 'pipeline-eval'
MODEL = Path.home() / 'Library/Application Support/htrmopo/b4a70336-339f-508b-abf4-24b698091dd7/arabic_best.mlmodel'
DPI = 300
Z = DPI / 72
MAP = {'ٱ': 'ا', 'أ': 'ا', 'إ': 'ا', 'آ': 'ا', 'ى': 'ي', 'ی': 'ي', 'ة': 'ه', 'ک': 'ك', 'ؤ': 'و', 'ئ': 'ي'}
GT_PASS = 0.10


def base(ch):
    return unicodedata.normalize('NFD', ch)[0]


def is_letter(ch):
    b = base(ch)
    return unicodedata.category(b).startswith('L') or b == 'ء'


def norm_letters(text):
    return [MAP.get(base(c), base(c)) for c in text if is_letter(c)]


_NET = {}


def kraken_read(png_path):
    from kraken import rpred
    from kraken.containers import BaselineLine, Segmentation
    from kraken.lib.models import load_any
    from PIL import Image
    if 'net' not in _NET:
        _NET['net'] = load_any(str(MODEL), train=False, device='cpu')
    image = Image.open(png_path).convert('RGB')
    w, h = image.size
    by = int(0.66 * h)
    seg = Segmentation(type='baselines', imagename=str(png_path), text_direction='horizontal-rl', script_detection=False,
                       lines=[BaselineLine(id='l', baseline=[(2, by), (w - 2, by)],
                                           boundary=[(2, 2), (w - 3, 2), (w - 3, h - 3), (2, h - 3)], base_dir='R')])
    rec = list(rpred.rpred(_NET['net'], image, seg, bidi_reordering=False))[0]
    xs = [sum(p[0] for p in cut) / len(cut) for cut in rec.cuts]
    return rec.prediction, xs


def line_gaps(words, prediction, xs):
    """Estimated x (crop px) of the gap after each word, in image order: [(word index in `words`, x or None)].
    `words` are in reading order (right to left); the result is keyed by the word on the RIGHT of the gap."""
    pred = [(MAP.get(base(c), base(c)), i) for i, c in enumerate(prediction) if is_letter(c)]
    img = list(reversed(range(len(words))))                      # image order, left to right
    flat, owner = [], []
    for wi in img:
        for c in reversed(words[wi]['letters']):
            flat.append(c)
            owner.append(wi)
    sm = difflib.SequenceMatcher(None, [c for c, _ in pred], flat, autojunk=False)
    got = {}
    for a, b, size in sm.get_matching_blocks():
        for t in range(size):
            if pred[a + t][1] < len(xs):
                got[b + t] = xs[pred[a + t][1]]
    first, last = {}, {}
    for fi, o in enumerate(owner):
        first.setdefault(o, fi)
        last[o] = fi
    out = {}
    cov = len(got) / max(1, len(flat))
    for left, right in zip(img, img[1:]):            # `left` is on the left in the image = the later word
        if left not in last or right not in first:
            continue
        xl, xr = got.get(last[left]), got.get(first[right])
        out[right] = ((xl + xr) / 2) if (xl is not None and xr is not None) else None
    return out, cov


def run_page(page, lib, offset_px, use_kraken=True, boundaries_from=None):
    import pymupdf
    pdir = EVAL / f'page-{page:03d}'
    report = load_page_report(pdir)
    pdf_page = pymupdf.open(PDF)[page - 1]
    cells = [c for c in report['word_partition']['cells'] if isinstance(c.get('word_index'), int)]
    by_line = {}
    for c in cells:
        by_line.setdefault(c['line_number'], []).append(c)
    gt = {g['word_index']: g for g in json.load(open(pdir / 'gt-eval.json'))['words']}
    work = Path('/tmp/kraken_eval') / f'p{page:03d}'
    work.mkdir(parents=True, exist_ok=True)
    masks = {}
    stats = {'lines': 0, 'gaps': 0, 'gaps_est': 0}
    for ln, cs in sorted(by_line.items()):
        entry = _line_entry(report, ln)
        if entry.get('line_type') != 'ayah':
            continue
        cs = sorted(cs, key=lambda c: -c['cell'][0])                 # reading order, right to left
        words = [{'wi': c['word_index'], 'token': c['token'], 'letters': norm_letters(c['token']),
                  'ring': not any(is_letter(ch) for ch in c['token']), 'pcell': c['cell']} for c in cs]
        x0, y0, x1, y1 = entry['bbox']
        cx0 = x0 - 3
        bottom = float(y1)
        png = work / f'line-{ln:02d}.png'
        if not png.exists():
            pdf_page.get_pixmap(clip=pymupdf.Rect(cx0, y0 - 2, x1 + 3, y1 + 2), matrix=pymupdf.Matrix(Z, Z),
                                alpha=False).save(png)
        text_words = [w for w in words if not w['ring']]
        gaps = {}
        if use_kraken and text_words:
            pred, xs = kraken_read(png)
            g, _cov = line_gaps(text_words, pred, xs)
            for k, v in g.items():
                gaps[text_words[k]['wi']] = None if v is None else cx0 + (v - offset_px) / Z      # pt
        # boundaries between consecutive text words (reading order): x of the gap after words[i] (to its left)
        raws = {suffix: raw for suffix, raw, _p in line_outlines(pdir, report, ln)}
        K = PDF_TO_FONT
        box = {s: _bbox_pt(r, K, CONTENT_X0, bottom) for s, r in raws.items()}
        line_h = (y1 - y0) * K
        small = {s for s, b in box.items() if is_mark((b[2] - b[0]) * K, (b[3] - b[1]) * K, line_h)}
        rings = [w['pcell'] for w in words if w['ring']]
        # cell edges: right edge of word i = left edge of word i-1; `cut[i]` = x between word i-1 (right) and i
        order = [w for w in words]
        cut = {}
        for i in range(1, len(order)):
            a, b = order[i - 1], order[i]
            pipe_edge = (a['pcell'][0] + b['pcell'][1]) / 2
            kx = None
            if not a['ring'] and not b['ring']:
                # gap estimated "after" `a` = between a (right) and b (left): keyed by the right word's index
                kx = gaps.get(a['wi'])
            stats['gaps'] += 1
            cut[i] = kx if kx is not None else pipe_edge
            stats['gaps_est'] += kx is not None
        stats['lines'] += 1

        # monotone: cut[i] (between word i-1 on the right and word i) must lie left of cut[i-1]
        prev = float('inf')
        for i in range(1, len(order)):
            cut[i] = min(cut[i], prev - 0.5)
            prev = cut[i]

        def word_of(xc):
            for i in range(len(order)):
                hi = cut.get(i, float('inf'))
                lo = cut.get(i + 1, float('-inf'))
                if lo <= xc < hi:
                    return i
            return len(order) - 1

        # bodies by centre; marks to the nearest body horizontally
        assign = {}
        for s, b in box.items():
            xc = (b[0] + b[2]) / 2
            if any(r[0] - 1 <= xc <= r[1] + 1 for r in rings):
                continue
            if s not in small:
                assign[s] = word_of(xc)
        body_spans = [(box[s][0], box[s][2], assign[s]) for s in assign]
        for s in small:
            b = box[s]
            xc = (b[0] + b[2]) / 2
            if any(r[0] - 1 <= xc <= r[1] + 1 for r in rings) or not body_spans:
                continue
            best = min(body_spans, key=lambda t: 0 if t[0] <= xc <= t[1] else min(abs(xc - t[0]), abs(xc - t[1])))
            assign[s] = best[2]
        for i, w in enumerate(order):
            if w['ring']:
                continue
            sel = [s for s, wi in assign.items() if wi == i]
            if sel:
                masks[w['wi']] = _group_mask([raws[s] for s in sel], K, CONTENT_X0, [bottom] * len(sel))
    # score
    passed = tot = 0
    rows = {}
    for wi, g in gt.items():
        if not g['token'].strip('٠١٢٣٤٥٦٧٨٩') or wi not in lib.by_word_index:
            continue
        ref_shape = lib.shape(lib.by_word_index[wi])
        d = 9.0
        db = 9.0
        if wi in masks and masks[wi].any():
            nm, asp = normalize_shape_mask(masks[wi])
            d = float(shape_distance(nm, asp, ref_shape))
            from shamarly_glyph_eval import bodies, dist
            ref_mask = ref_shape.mask
            if ref_mask is not None:
                db = max(dist(bodies(masks[wi]), bodies(ref_mask)), dist(bodies(ref_mask), bodies(masks[wi])))
        rows[wi] = (d, g['final'], db)
        tot += 1
        passed += d < GT_PASS
    return rows, stats


def verify_page(page, offset_px):
    """Per word of the shipped pipeline's partition: how far its two cell edges are from Kraken's gaps (pt)."""
    import pymupdf
    pdir = EVAL / f'page-{page:03d}'
    report = load_page_report(pdir)
    pdf_page = pymupdf.open(PDF)[page - 1]
    cells = [c for c in report['word_partition']['cells'] if isinstance(c.get('word_index'), int)]
    by_line = {}
    for c in cells:
        by_line.setdefault(c['line_number'], []).append(c)
    gate_auto = {g['word_index'] for g in json.load(open(pdir / 'accepted-glyphs.json')) if 'word_index' in g}
    gt = {g['word_index']: g['final'] for g in json.load(open(pdir / 'gt-eval.json'))['words']}
    work = Path('/tmp/kraken_eval') / f'p{page:03d}'
    work.mkdir(parents=True, exist_ok=True)
    out = []
    for ln, cs in sorted(by_line.items()):
        entry = _line_entry(report, ln)
        if entry.get('line_type') != 'ayah':
            continue
        cs = sorted(cs, key=lambda c: -c['cell'][0])
        words = [{'wi': c['word_index'], 'token': c['token'], 'letters': norm_letters(c['token']),
                  'ring': not any(is_letter(ch) for ch in c['token']), 'pcell': c['cell']} for c in cs]
        x0, y0, x1, y1 = entry['bbox']
        cx0 = x0 - 3
        png = work / f'line-{ln:02d}.png'
        if not png.exists():
            pdf_page.get_pixmap(clip=pymupdf.Rect(cx0, y0 - 2, x1 + 3, y1 + 2), matrix=pymupdf.Matrix(Z, Z),
                                alpha=False).save(png)
        text_words = [w for w in words if not w['ring']]
        if not text_words:
            continue
        pred, xs = kraken_read(png)
        g, cov = line_gaps(text_words, pred, xs)
        kgap = {text_words[k]['wi']: (None if v is None else cx0 + (v - offset_px) / Z) for k, v in g.items()}
        for i, w in enumerate(words):
            if w['ring'] or w['wi'] not in gt:
                continue
            errs = []
            if i > 0 and not words[i - 1]['ring']:                      # edge shared with the word on the right
                k = kgap.get(words[i - 1]['wi'])
                errs.append(None if k is None else abs((words[i - 1]['pcell'][0] + w['pcell'][1]) / 2 - k))
            else:
                errs.append(0.0)                                      # line edge or ring: nothing to disagree with
            if i + 1 < len(words) and not words[i + 1]['ring']:         # edge shared with the word on the left
                k = kgap.get(w['wi'])
                errs.append(None if k is None else abs((w['pcell'][0] + words[i + 1]['pcell'][1]) / 2 - k))
            else:
                errs.append(0.0)
            out.append({'page': page, 'wi': w['wi'], 'gt': gt[w['wi']], 'gate': w['wi'] in gate_auto,
                        'errs': errs, 'cov': cov})
    return out


def main_verify(pages, offset):
    rows = []
    for p in pages:
        rows += verify_page(p, offset)
    json.dump(rows, open('/tmp/kraken_eval/verify.json', 'w'))
    n = len(rows)
    ok = lambda r: r['gt'] < GT_PASS
    print(f'words {n}  shipped pipeline right {sum(map(ok, rows))} ({100 * sum(map(ok, rows)) / n:.1f}%)')
    g = [r for r in rows if r['gate']]
    print(f'current auto gate: {len(g)} ({100 * len(g) / n:.1f}%) at {100 * sum(map(ok, g)) / max(1, len(g)):.1f}%')
    for tol in (2.0, 3.0, 4.5, 6.0, 9.0):
        agree = [r for r in rows if all(e is not None and e <= tol for e in r['errs'])]
        dis = [r for r in rows if any(e is not None and e > tol for e in r['errs'])]
        unk = n - len(agree) - len(dis)
        uni = [r for r in rows if r['gate'] or r in agree]
        print(f'tol {tol:>4}pt  agree {len(agree)} ({100 * len(agree) / n:.0f}%) at {100 * sum(map(ok, agree)) / max(1, len(agree)):.1f}%'
              f' | disagree {len(dis)} right only {100 * sum(map(ok, dis)) / max(1, len(dis)):.1f}% | unknown {unk}'
              f' | gate+agree {len(uni)} ({100 * len(uni) / n:.0f}%) at {100 * sum(map(ok, uni)) / max(1, len(uni)):.1f}%')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--pages', type=int, nargs='+', required=True)
    ap.add_argument('--offset', type=float, nargs='+', default=[32.0], help='crop px; several = sweep')
    ap.add_argument('--no-kraken', action='store_true', help='cells from the pipeline only (control)')
    ap.add_argument('--verify', action='store_true', help='check the shipped pipeline partition against Kraken gaps')
    a = ap.parse_args()
    if a.verify:
        return main_verify(a.pages, a.offset[0])
    lib = TemplateLibrary(DEFAULT_GLYPH_DB, DEFAULT_FONT_DIR)
    for off in a.offset:
        tot = kp = pp = kb = 0
        line = []
        for page in a.pages:
            rows, st = run_page(page, lib, off, use_kraken=not a.no_kraken)
            n = len(rows)
            k = sum(d < GT_PASS for d, _, _ in rows.values())
            kb += sum(b < GT_PASS for _, _, b in rows.values())
            p = sum(f < GT_PASS for _, f, _ in rows.values())
            tot += n; kp += k; pp += p
            line.append(f'{page}: {k}/{n} (pipe {p}) est {st["gaps_est"]}/{st["gaps"]}')
        print(f'offset {off:g}px  partition {kp}/{tot} = {100 * kp / tot:.1f}%   bodies-only {100 * kb / tot:.1f}%   shipped pipeline {pp}/{tot} = {100 * pp / tot:.1f}%')
        print('   ' + ' | '.join(line), flush=True)


if __name__ == '__main__':
    main()
