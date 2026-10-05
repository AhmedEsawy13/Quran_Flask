"""Alternative ways to split one printed row, for when the reviewer says the row is not right.

The cutter weighs several kinds of evidence (the ink gaps, the width model, the scan's OCR boxes, a second reader).
Re-running it gives the same answer, so the alternatives change what it trusts: on the rows where the default
disagreed with the scan OCR, one of these gave a better split in about half, and the second-reader one in the most
(76 rows better, 1 worse). The reviewer looks at them and adopts the one that is right.
"""
from __future__ import annotations

# (id, label shown, cutter options for ``layout_geo.estimate_layout_words(cutter=...)``)
STRATEGIES = (
    ('reader', 'يثق بالقارئ الثاني أكثر', {
        'anchors': False, 'windows': True, 'window_sigma': 0.08, 'window_cap': 40.0, 'window_slack': 0.04,
        'position_sigma': 0.5,
    }),
    ('gaps', 'من الفراغات بين الحروف فقط', {
        'anchors': False, 'windows': False, 'position_sigma': 0.5, 'gap_reward': 3.0, 'virtual_penalty': 3.0,
    }),
    ('widths', 'من العرض المتوقع للكلمات', {
        'anchors': False, 'windows': False, 'position_sigma': 0.03, 'gap_reward': 0.3,
    }),
    ('avoid', 'بعيدًا عن التقطيع الحالي', {}),
)
SAME = 0.10          # cuts closer than this (line pitches) are the same cut


def distinct(current: list[float], options: list[dict], pitch: float) -> list[dict]:
    """Keep the options that differ from the current cuts, and from each other, by more than ``SAME`` pitches."""
    kept: list[dict] = []
    for option in options:
        cuts = option['cuts']
        moved = sum(1 for a, b in zip(cuts, current) if abs(a - b) > SAME * pitch)
        if not moved:
            continue
        if any(len(o['cuts']) == len(cuts) and all(abs(a - b) <= SAME * pitch for a, b in zip(cuts, o['cuts'])) for o in kept):
            continue
        kept.append({**option, 'moved': moved})
    return kept


def valid_row(cuts: list[float], right_edge: float, left_edge: float, min_word: float) -> bool:
    """The cuts run right to left, each word at least ``min_word`` wide, all inside the row."""
    edges = [right_edge, *cuts, left_edge]
    return all(a - b >= min_word for a, b in zip(edges, edges[1:]))


def compute(page: int, row: list[dict], pins: dict[tuple[str, str], float]) -> list[dict]:
    """The distinct alternative splits of ``row`` (its words, right to left, as the tool shows them)."""
    import cv2

    from pipeline.cv_waqf import layout_geo
    from pipeline.cv_waqf.config import EDITIONS
    from pipeline.cv_waqf.pages import ensure_page_image
    from pipeline.cv_waqf.preprocess import preprocess_page

    if len(row) < 2:
        return []
    spec = EDITIONS['المساحة']
    line = row[0]['line']
    pitch = max(12.0, (row[0]['box'][3] - row[0]['box'][1]) / 0.85)
    current = [float(w['box'][0]) for w in row[:-1]]
    prepared = preprocess_page(cv2.imread(str(ensure_page_image(spec, page))), spec, page)
    before = layout_geo.FIXED_CUTS
    layout_geo.FIXED_CUTS = dict(pins)
    try:
        options = []
        for sid, label, opts in STRATEGIES:
            cutter = dict(opts)
            if sid == 'avoid':
                cutter['avoid'] = {(a['key'], b['key']): [x] for a, b, x in zip(row, row[1:], current)}
            words = {w.word_key: w for w in layout_geo.estimate_layout_words(spec, page, prepared, cutter=cutter) if w.line_number == line}
            if any(w['key'] not in words for w in row):
                continue
            options.append({'id': sid, 'label': label, 'cuts': [float(words[w['key']].x0) for w in row[:-1]]})
    finally:
        layout_geo.FIXED_CUTS = before
    return distinct(current, options, pitch)
