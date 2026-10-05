"""Build ``assets/mesaha_kraken_chars.json``: where Kraken placed every character of every printed Mesaha row.

Two steps, because Kraken lives in another environment (see ``kraken_read_rows.py``):

    python3 -m pipeline.cv_waqf.mesaha_kraken_chars crops  CROPS_DIR     # one PNG per printed row
    ShemrlyMushaf/.venv/bin/python pipeline/cv_waqf/kraken_read_rows.py CROPS_DIR
    python3 -m pipeline.cv_waqf.mesaha_kraken_chars merge  CROPS_DIR     # writes the asset

``crops`` cuts each printed row of the working page image (rows as the layout estimate places them, so
the crop does not depend on which words the layout assigns to it). ``merge`` turns Kraken's per-row
result into page coordinates. The cutter reads the asset through ``relayout.kraken_chars``.
"""

from __future__ import annotations

import argparse
import collections
import dataclasses
import json
from pathlib import Path

from pipeline.cv_waqf import geometry, layout_geo
from pipeline.cv_waqf.config import EDITIONS
from pipeline.cv_waqf.relayout import KRAKEN_CHARS_JSON

MODEL_ID = '10.5281/zenodo.7050296'


def make_crops(directory: Path, pages: list[int] | None = None) -> int:
    import cv2

    from pipeline.cv_waqf.pages import ensure_page_image
    from pipeline.cv_waqf.preprocess import preprocess_page

    spec = EDITIONS['المساحة']
    plain = dataclasses.replace(spec, kraken_word_windows=False)
    directory.mkdir(parents=True, exist_ok=True)
    meta: list[dict] = []
    for page in pages or range(spec.min_page, spec.max_page + 1):
        try:
            prepared = preprocess_page(cv2.imread(str(ensure_page_image(spec, page))), spec, page)
            words = layout_geo.estimate_layout_words(plain, page, prepared)
        except Exception as exc:                       # a page that cannot be prepared is left without rows
            print('skip page', page, exc)
            continue
        rows: dict[int, list] = collections.defaultdict(list)
        for word in words:
            rows[word.line_number].append(word)
        for line_number, row in rows.items():
            pitch = max(12, row[0].y1 - row[0].y0)
            baseline = row[0].y0 + (0.5 + geometry.LINE_CENTER_BIAS) * pitch
            y0 = max(0, int(baseline - 0.62 * pitch))
            y1 = min(prepared.bgr.shape[0], int(baseline + 0.38 * pitch))
            x0 = max(0, min(w.x0 for w in row) - 12)
            x1 = min(prepared.bgr.shape[1], max(w.x1 for w in row) + 12)
            if y1 - y0 < 8 or x1 - x0 < 8:
                continue
            name = f'p{page:03d}_r{line_number:02d}.png'
            cv2.imwrite(str(directory / name), cv2.cvtColor(prepared.bgr[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY))
            meta.append({
                'name': name, 'page': page, 'row': line_number, 'x0': x0, 'baseline': baseline,
                'width': int(prepared.bgr.shape[1]),
            })
    (directory / 'meta.json').write_text(json.dumps(meta))
    return len(meta)


def merge(directory: Path, out: Path = KRAKEN_CHARS_JSON) -> int:
    meta = json.loads((directory / 'meta.json').read_text())
    read = json.loads((directory / 'kraken_out.json').read_text())
    pages: dict[str, list] = collections.defaultdict(list)
    width = 0
    for item in meta:
        record = read.get(item['name'])
        if not record or not record['pred'].strip():
            continue
        width = width or int(item['width'])
        pages[str(item['page'])].append({
            'y': round(float(item['baseline']), 1),
            't': record['pred'],
            'x': [round(item['x0'] + x) for x in record['x']],
        })
    payload = {
        'format': 'mesaha-kraken-chars-v1',
        'engine': 'kraken',
        'model': MODEL_ID,
        'width': width,
        'pages': dict(pages),
    }
    out.write_text(json.dumps(payload, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    return sum(len(rows) for rows in pages.values())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('step', choices=('crops', 'merge'))
    parser.add_argument('directory', type=Path)
    parser.add_argument('--pages', help='comma-separated page numbers (default: every page)')
    args = parser.parse_args()
    if args.step == 'crops':
        pages = [int(p) for p in args.pages.split(',')] if args.pages else None
        print(make_crops(args.directory, pages), 'row crops')
    else:
        print(merge(args.directory), 'rows written to', KRAKEN_CHARS_JSON)


if __name__ == '__main__':
    main()
