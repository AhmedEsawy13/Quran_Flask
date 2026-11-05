"""Kraken word spans of Shamarly lines, cached for ShemrlyMushaf's word-owner model.

Kraken (printed-Arabic ``arabic_best.mlmodel``) reads each ayah line; its letters are aligned to the known text
and the gap between two words gives each word an x span [right edge, left edge] (PDF points; the line's own ends
are open). ``word_owner_model`` (ShemrlyMushaf) uses where an outline sits against these spans as features:
blind on its 9 eval pages words exact 90.4% -> 92.8% (three seeds; stock Kraken as good as one fine-tuned on
Shamarly lines).

    PYTHONPATH=<ShemrlyMushaf venv site-packages> /opt/homebrew/Cellar/python@3.13/3.13.2/bin/python3.13 \\
        pipeline/paw_split/shamarly_kraken_spans.py --run batch-rest [--pages 4 42 ...]

Output ``ShemrlyMushaf/output/pdf/kraken-spans/page-NNN.json``: {line: {word_index: [right, left, coverage]}};
pages already cached are skipped.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pymupdf  # noqa: E402

import shamarly_kraken_partition as K  # noqa: E402

SH = Path('/Users/mac/Development/ShemrlyMushaf')
OFFSET_PX = 30.0          # Kraken's gap sits ~30 px (300 dpi) right of the printed gap; fitted on the pilot pages


def line_spans(pdf_page, bbox, words, work: Path):
    x0, y0, x1, y1 = bbox
    cx0 = x0 - 3
    png = work / 'line.png'
    pdf_page.get_pixmap(clip=pymupdf.Rect(cx0, y0 - 2, x1 + 3, y1 + 2), matrix=pymupdf.Matrix(K.Z, K.Z),
                        alpha=False).save(png)
    text_words = [w for w in words if w['letters']]
    out = {}
    if not text_words:
        return out
    pred, xs = K.kraken_read(png)
    gaps, cov = K.line_gaps(text_words, pred, xs)
    pt = {k: (None if v is None else cx0 + (v - OFFSET_PX) / K.Z) for k, v in gaps.items()}
    for k, w in enumerate(text_words):
        right = pt.get(k - 1) if k > 0 else float('inf')
        left = pt.get(k) if k < len(text_words) - 1 else float('-inf')
        out[str(w['wi'])] = [right, left, round(cov, 3)]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--run', default='batch-rest', help='ShemrlyMushaf output/pdf/<run> with page-NNN/report.json')
    ap.add_argument('--pages', type=int, nargs='*')
    ap.add_argument('--out', default=str(SH / 'output' / 'pdf' / 'kraken-spans'))
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    runs = SH / 'output' / 'pdf' / a.run
    pages = a.pages or sorted(int(p.name[5:]) for p in runs.glob('page-*'))
    db = sqlite3.connect(SH / 'quran_script.db')
    doc = pymupdf.open(K.PDF)
    t0 = time.time()
    for n in pages:
        dst = out / f'page-{n:03d}.json'
        if dst.exists():
            continue
        rep = json.load(open(runs / f'page-{n:03d}' / 'report.json'))
        res = {}
        for l in rep['lines']:
            if l['line_type'] != 'ayah' or l.get('first_word_id') is None:
                continue
            rows = db.execute('SELECT word_index, text FROM words WHERE word_index BETWEEN ? AND ? ORDER BY word_index',
                              (l['first_word_id'], l['last_word_id'])).fetchall()
            words = [{'wi': wi, 'letters': K.norm_letters(t)} for wi, t in rows]
            try:
                res[str(l['line_number'])] = line_spans(doc[n - 1], l['bbox'], words, Path('/tmp'))
            except Exception as exc:                      # a line Kraken cannot take is left without spans
                print('skip', n, l['line_number'], exc, file=sys.stderr)
        json.dump(res, open(dst, 'w'))
        print(n, f'{time.time() - t0:.0f}s', flush=True)


if __name__ == '__main__':
    main()
