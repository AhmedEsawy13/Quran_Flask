"""Derive an edition's nominal text band from sample pages.

``geometry.fit_line_grid`` searches a narrow window around the spec's
``text_top``/``text_bottom``, and those must follow the slot-box convention
(the ink block is ~0.56 line lower). This fits a sample of pages with a wide
window, recentres on the median, refits narrowly, and reports the values to
paste into the ``EditionSpec`` plus how many pages still disagree.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from pipeline.cv_waqf import geometry
from pipeline.cv_waqf.config import EDITIONS, EditionSpec
from pipeline.cv_waqf.layout_geo import load_page_lines
from pipeline.cv_waqf.pages import ensure_page_image


def _page_inputs(spec: EditionSpec, page: int):
    import cv2

    try:
        image = cv2.imread(str(ensure_page_image(spec, page)))
    except Exception:  # noqa: BLE001 - an uncached page is just skipped
        return None
    if image is None:
        return None
    lines = load_page_lines(spec, page)
    word_lines = [
        line for line in lines
        if line.get('first_word_id') is not None
        and (line.get('line_type') or '') not in ('surah_name', 'basmallah')
    ]
    if not word_lines or not lines:
        return None
    first = min(int(line['line_number']) for line in lines)
    slots = [int(line['line_number']) - first for line in word_lines]
    return image, geometry.text_ink_mask(image), slots


def calibrate(spec: EditionSpec, pages: list[int], *, lines: int = 15) -> dict:
    """Suggested ``(text_top, text_bottom)`` and fit quality over ``pages``."""
    samples = []
    for page in pages:
        got = _page_inputs(spec, page)
        if got is not None:
            samples.append((page, *got))
    if len(samples) < 5:
        raise ValueError(f'{spec.id}: need >=5 cached pages, got {len(samples)}')

    def fit(center_top: float, center_pitch_frac: float, reach: float):
        rows = []
        for page, image, mask, slots in samples:
            height = image.shape[0]
            grid = geometry.fit_line_grid(
                mask, slots,
                nominal_top=center_top * height,
                nominal_pitch=center_pitch_frac * height,
                reach=reach,
            )
            rows.append((page, grid.top / height, grid.pitch / height, grid))
        return rows

    pitch0 = (spec.text_bottom - spec.text_top) / lines
    wide = fit(spec.text_top, pitch0, reach=1.0)
    top = float(np.median([row[1] for row in wide]))
    pitch = float(np.median([row[2] for row in wide]))
    narrow = fit(top, pitch, reach=geometry.DEFAULT_REACH)
    tops = np.array([row[1] for row in narrow])
    pitches = np.array([row[2] for row in narrow])
    top, pitch = float(np.median(tops)), float(np.median(pitches))
    spread = (tops - top) / pitch
    stray = [row[0] for row, off in zip(narrow, spread) if abs(off) > 0.25]
    return {
        'edition': spec.mushaf_version,
        'pages_used': len(samples),
        'text_top': round(top, 4),
        'text_bottom': round(top + lines * pitch, 4),
        'current': [spec.text_top, spec.text_bottom],
        'offset_from_current_lines': round((top - spec.text_top) / pitch, 3),
        'spread_lines_p5_p95': [
            round(float(np.percentile(spread, 5)), 3),
            round(float(np.percentile(spread, 95)), 3),
        ],
        'stray_pages': stray,
        'unfitted_pages': [row[0] for row in narrow if not row[3].fitted],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--edition', required=True, choices=list(EDITIONS))
    parser.add_argument('--pages', default='3-604:7',
                        help='range with optional :step, e.g. 3-604:7')
    parser.add_argument('--out', type=Path, default=None)
    args = parser.parse_args(argv)
    span, _, step = args.pages.partition(':')
    start, _, end = span.partition('-')
    pages = list(range(int(start), int(end or start) + 1, int(step or 1)))
    report = calibrate(EDITIONS[args.edition], pages)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.out:
        args.out.write_text(json.dumps(report, ensure_ascii=False), encoding='utf-8')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
