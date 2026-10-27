"""Score the PAW split of Shamarly pages (shamarly_split.py) against the withheld Elgharib word glyphs,
next to ShemrlyMushaf's pipeline glyphs, and measure an "agree" gate: a pipeline glyph is accepted when
the PAW split's ink for the same word has the same shape.

Run with ShemrlyMushaf's venv (pymupdf, fontTools, its extract_pdf_pages):
    /Users/mac/Development/ShemrlyMushaf/.venv/bin/python pipeline/paw_split/shamarly_glyph_eval.py 204 212 ...
"""
import json
import sys
from pathlib import Path

import numpy as np

SHEMRLY = Path('/Users/mac/Development/ShemrlyMushaf')
sys.path.insert(0, str(SHEMRLY))
sys.path.insert(0, str(SHEMRLY / 'experiments'))
from extract_pdf_pages import DEFAULT_FONT_DIR, DEFAULT_GLYPH_DB, TemplateLibrary, TemplateShape, normalize_shape_mask, shape_distance  # noqa: E402
from scipy.ndimage import distance_transform_edt  # noqa: E402
from pipeline_gt_eval import render_glyph_mask  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / 'artifacts' / 'shamarly-trace'
EVAL = SHEMRLY / 'output' / 'pdf' / 'pipeline-eval'
GT_PASS = 0.10


def bodies(mask, keep=0.04):
    """Letter bodies only: components holding at least `keep` of the word's ink (dots, vowels and
    signs are small; the pipeline's errors are mostly whole letters given to a neighbour)."""
    import cv2
    n, lab, st, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), 8)
    if n <= 1:
        return mask
    tot = st[1:, 4].sum()
    big = [i for i in range(1, n) if st[i, 4] >= keep * tot]
    out = np.isin(lab, big)
    ys, xs = np.nonzero(out)
    return out[ys.min():ys.max() + 1, xs.min():xs.max() + 1]


def dist(a, b):
    na, aa = normalize_shape_mask(a)
    nb, ab = normalize_shape_mask(b)
    return float(shape_distance(na, aa, TemplateShape(nb, distance_transform_edt(~nb), ab)))


def word_masks(page):
    d = json.load(open(WORK / f'paw-words-{page:03d}.json'))
    lab = np.load(WORK / f'labels-{page:03d}.npz')['lab']
    out = {}
    for w in d['words']:
        if w['ring'] or not w.get('pieces'):
            continue
        m = np.isin(lab, w['pieces'])
        ys, xs = np.nonzero(m)
        if len(xs):
            out[w['word_index']] = m[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    return out


def main(pages):
    lib = TemplateLibrary(DEFAULT_GLYPH_DB, DEFAULT_FONT_DIR)
    rows = []
    for page in pages:
        pdir = EVAL / f'page-{page:03d}'
        report = json.load(open(pdir / 'report.json'))
        font = pdir / report['word_font']
        gate_auto = {g['word_index'] for g in json.load(open(pdir / 'accepted-glyphs.json')) if 'word_index' in g}
        cells = {c['word_index']: c for c in report['word_partition']['cells']
                 if isinstance(c.get('word_index'), int) and c.get('codepoint')}
        paw = word_masks(page)
        for g in json.load(open(pdir / 'gt-eval.json'))['words']:
            wi = g['word_index']
            ref = lib.by_word_index.get(wi)
            if ref is None:
                continue
            ref_shape = lib.shape(ref)
            r = {'page': page, 'word_index': wi, 'token': g['token'], 'pipe_gt': g['final'], 'gate': wi in gate_auto}
            if wi in paw:
                nm, asp = normalize_shape_mask(paw[wi])
                r['paw_gt'] = float(shape_distance(nm, asp, ref_shape))
                c = cells.get(wi)
                pm = render_glyph_mask(font, int(str(c['codepoint']).replace('U+', ''), 16)) if c else None
                if pm is not None:
                    pn, pa = normalize_shape_mask(pm)
                    r['agree'] = float(shape_distance(nm, asp, TemplateShape(pn, distance_transform_edt(~pn), pa)))
                    r['agree_body'] = max(dist(bodies(paw[wi]), bodies(pm)), dist(bodies(pm), bodies(paw[wi])))
            if not g['token'].strip('٠١٢٣٤٥٦٧٨٩'):
                continue          # verse numbers: the PAW split keeps them as rings
            rows.append(r)
    json.dump(rows, open(WORK / 'glyph-eval.json', 'w'), ensure_ascii=False, indent=1)
    n = len(rows)
    pipe = sum(r['pipe_gt'] < GT_PASS for r in rows)
    paw = sum(r.get('paw_gt', 9) < GT_PASS for r in rows)
    print(f'GT words {n} · pipeline pass {pipe} ({pipe / n:.1%}) · PAW split pass {paw} ({paw / n:.1%})')
    either = sum(min(r['pipe_gt'], r.get('paw_gt', 9)) < GT_PASS for r in rows)
    print(f'either right {either} ({either / n:.1%})')
    gate = [r for r in rows if r['gate']]
    print(f'current gate: {len(gate)} ({len(gate) / n:.1%}) at {sum(r["pipe_gt"] < GT_PASS for r in gate) / max(1, len(gate)):.1%}')
    for key in ('agree', 'agree_body'):
      print(key)
      for t in (0.03, 0.04, 0.06, 0.08, 0.10):
        acc = [r for r in rows if r.get(key, 9) < t]
        ok = sum(r['pipe_gt'] < GT_PASS for r in acc)
        both = [r for r in rows if r.get(key, 9) < t or r['gate']]
        okb = sum(r['pipe_gt'] < GT_PASS for r in both)
        print(f'agree<{t}: {len(acc)} ({len(acc) / n:.1%}) at {ok / max(1, len(acc)):.1%} · with gate {len(both)} ({len(both) / n:.1%}) at {okb / max(1, len(both)):.1%}')


if __name__ == '__main__':
    main([int(p) for p in sys.argv[1:]])
