"""What the reviewer's hand-set cuts say about the word cutter.

    PYTHONPATH=. python3 -m pipeline.cv_waqf.mesaha_review.cut_labels stats
    PYTHONPATH=. python3 -m pipeline.cv_waqf.mesaha_review.cut_labels tune

``stats`` reports how many cuts were corrected, by how much, and how many of them the doubt flag had caught.
``tune`` re-runs the cutter on the corrected pages with each setting of its knobs (how much to trust the second
reader, the OCR, the width model, the gaps) and scores every setting by its distance from the corrected cuts, so the
hand-set weights can be replaced by ones that fit real labels. Neither changes any data.
"""
from __future__ import annotations

import argparse
import functools
import itertools
import json
import os
import random
import sys
from pathlib import Path

DATA = Path(os.environ.get('MESAHA_REVIEW_DATA') or Path(__file__).resolve().parents[3] / 'artifacts' / 'cv-waqf' / 'mesaha-selflearn')
MISS = 0.15      # a cut this far (in line pitches) from where the reviewer put it is a miss


def _read(name: str, default):
    try:
        return json.loads((DATA / name).read_text(encoding='utf-8'))
    except FileNotFoundError:
        return default


def label_rows() -> list[dict]:
    """One row per corrected cut: page, keys, the cutter's x, the reviewer's x, the shift in pitches, its doubt."""
    pages = {p['page']: p for p in _read('pages.json', [])}
    rows = []
    for key, value in _read('cuts.json', {}).items():
        page_text, _, pair = key.partition(':')
        right_key, _, left_key = pair.partition('|')
        page = pages.get(int(page_text))
        word = next((w for w in (page or {}).get('words', []) if w['key'] == right_key), None)
        pitch = max(12.0, (word['box'][3] - word['box'][1]) / 0.85) if word else 79.0
        rows.append({'page': int(page_text), 'right': right_key, 'left': left_key, 'was': value.get('was'),
                     'x': float(value['x']), 'doubt': value.get('doubt'), 'via': value.get('via') or 'drag', 'pitch': pitch,
                     'shift': (float(value['x']) - float(value['was'])) / pitch if value.get('was') is not None else None})
    return rows


def stats() -> dict:
    rows = label_rows()
    shifts = sorted(abs(r['shift']) for r in rows if r['shift'] is not None)
    known = [r for r in rows if r['doubt'] is not None]
    marks = _read('reviewed_marks.json', {}).get('marks', {})
    marked_cut_words = {(int(pg), key) for pg, ms in marks.items() for key in ms}
    on_marked = sum(1 for r in rows if (r['page'], r['right']) in marked_cut_words or (r['page'], r['left']) in marked_cut_words)
    out = {
        'corrected cuts': len(rows),
        '  dragged by hand': sum(1 for r in rows if r['via'] == 'drag'),
        '  from an adopted alternative split': sum(1 for r in rows if r['via'].startswith('resplit')),
        'pages': len({r['page'] for r in rows}),
        'median |shift| (pitches)': round(shifts[len(shifts) // 2], 3) if shifts else None,
        'moved by more than 0.15 pitch': sum(1 for s in shifts if s > MISS),
        'the doubt flag had caught (doubt >= 0.5)': sum(1 for r in known if r['doubt'] >= 0.5),
        'with a doubt recorded': len(known),
        'next to a mark on a finished page': on_marked,
    }
    return out


SHIPPED = {'window_slack': 0.08, 'window_sigma': 0.15, 'window_cap': 9.0, 'position_sigma': 0.06, 'gap_reward': 1.0}
GRID = {
    'window_slack': (0.04, 0.08, 0.12),
    'window_sigma': (0.08, 0.15, 0.30),
    'window_cap': (4.0, 9.0, 16.0),
    'position_sigma': (0.04, 0.06, 0.10),
    'gap_reward': (0.5, 1.0, 2.0),
}


def tune(max_runs: int = 120) -> list[tuple[float, float, dict]]:
    """Score cutter settings by their distance from the corrected cuts (the corrected cuts are held out)."""
    import cv2

    from pipeline.cv_waqf import geometry, layout_geo
    from pipeline.cv_waqf.config import EDITIONS
    from pipeline.cv_waqf.pages import ensure_page_image
    from pipeline.cv_waqf.preprocess import preprocess_page

    spec = EDITIONS['المساحة']
    rows = label_rows()
    if not rows:
        return []
    layout_geo.FIXED_CUTS = {}                       # score the cutter on its own, not on the labels
    prepared = {pg: preprocess_page(cv2.imread(str(ensure_page_image(spec, pg))), spec, pg) for pg in {r['page'] for r in rows}}
    base = geometry.segment_line_words
    results = []
    names = list(GRID)
    shipped = tuple(SHIPPED[n] for n in names)
    combos = list(itertools.product(*(GRID[n] for n in names)))
    random.Random(0).shuffle(combos)
    for values in [shipped, *combos[:max_runs]]:
        setting = dict(zip(names, values))
        geometry.segment_line_words = functools.partial(base, **setting)
        try:
            errors = []
            for pg, prep in prepared.items():
                words = layout_geo.estimate_layout_words(spec, pg, prep)
                by_key = {w.word_key: w for w in words}
                for r in (r for r in rows if r['page'] == pg):
                    w = by_key.get(r['right'])
                    if w is not None:
                        errors.append(abs(w.x0 - r['x']) / r['pitch'])
        finally:
            geometry.segment_line_words = base
        if errors:
            results.append((sum(errors) / len(errors), sum(e > MISS for e in errors) / len(errors), setting))
    return sorted(results, key=lambda item: (item[1], item[0]))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('step', choices=('stats', 'tune'))
    args = parser.parse_args()
    if args.step == 'stats':
        for key, value in stats().items():
            print(f'{key:45s} {value}')
        return 0
    results = tune()
    if not results:
        print('no corrected cuts yet')
        return 1
    for mean, miss, setting in results[:8]:
        print(f'mean error {mean:.3f} pitch | misses {miss:.0%} | {setting}')
    mean, miss, _ = next(r for r in results if r[2] == SHIPPED)
    print(f'shipped settings: mean error {mean:.3f} pitch | misses {miss:.0%}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
