"""Read single-line crops with Kraken and write where it placed every character.

Standalone on purpose: it imports nothing from this repository, so it runs in any environment that has
``kraken`` and Pillow (the one the Shemrly project keeps, ``ShemrlyMushaf/.venv``). The repository's own
environment does not carry Kraken.

    ShemrlyMushaf/.venv/bin/python pipeline/cv_waqf/kraken_read_rows.py CROPS_DIR

``CROPS_DIR`` holds ``meta.json`` (a list of ``{"name": <png file>}``) and the PNGs, as written by
``python -m pipeline.cv_waqf.mesaha_kraken_chars crops``. The result is ``CROPS_DIR/kraken_out.json``:
``{name: {"pred": text in display order, "x": emission x per character, "size": [w, h]}}``.

The recogniser is the printed-Arabic model Mesaha's line OCR already uses (``arabic_best.mlmodel``,
Zenodo 10.5281/zenodo.7050296). It is a baseline-line model, so each crop is handed to it as a baseline
line (the writing line about two thirds of the way down) and not as a bare box, which it reads far worse.
"""

from __future__ import annotations

import json
import sys
import time
import warnings
from pathlib import Path

warnings.filterwarnings('ignore')

MODEL = Path.home() / 'Library/Application Support/htrmopo/b4a70336-339f-508b-abf4-24b698091dd7/arabic_best.mlmodel'
BASELINE_FRACTION = 0.66     # the writing line sits about two thirds down a row crop


def main(directory: str) -> None:
    from PIL import Image
    from kraken import rpred
    from kraken.containers import BaselineLine, Segmentation
    from kraken.lib.models import load_any

    root = Path(directory)
    network = load_any(str(MODEL), train=False, device='cpu')
    meta = json.loads((root / 'meta.json').read_text())
    out: dict[str, dict] = {}
    started = time.time()
    for done, item in enumerate(meta, 1):
        image = Image.open(root / item['name']).convert('RGB')
        w, h = image.size
        by = int(BASELINE_FRACTION * h)
        segmentation = Segmentation(
            type='baselines', imagename=str(root / item['name']), text_direction='horizontal-rl',
            script_detection=False,
            lines=[BaselineLine(
                id='l', baseline=[(2, by), (w - 2, by)],
                boundary=[(2, 2), (w - 3, 2), (w - 3, h - 3), (2, h - 3)], base_dir='R',
            )],
        )
        try:
            records = list(rpred.rpred(network, image, segmentation, bidi_reordering=False))
        except Exception as exc:               # a crop Kraken cannot take is simply left unread
            print('skip', item['name'], exc, file=sys.stderr)
            continue
        if not records:
            continue
        record = records[0]
        xs = [round(sum(p[0] for p in cut) / len(cut), 1) for cut in record.cuts]
        out[item['name']] = {'pred': record.prediction, 'x': xs, 'size': [w, h]}
        if done % 500 == 0:
            print(f'{done}/{len(meta)} rows, {time.time() - started:.0f}s', flush=True)
    (root / 'kraken_out.json').write_text(json.dumps(out, ensure_ascii=False))
    print(f'{len(out)} rows read in {time.time() - started:.0f}s')


if __name__ == '__main__':
    main(sys.argv[1])
