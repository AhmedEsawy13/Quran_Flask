"""Inputs for shamarly_qvp_svg.py that need this repo's Python (cv2/onnx detector, the app's waqf column).

Per page, into artifacts/shamarly-qvp/waqf/:
  NNN.json         the Shamarly waqf detector's marks (pipeline.cv_waqf.run_page)
  NNN.column.json  the «الشمرلي» waqf column as the reader serves it: {word_key: symbol}

The builder looks for every column sign on the page, not only where the detector fired: the detector misses
~10% of Shamarly signs, and a sign it misses would stay in the ink when the reader hides waqf.

    /opt/homebrew/bin/python3 pipeline/paw_split/shamarly_qvp_prep.py 4 42 ...
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
OUT = ROOT / 'artifacts' / 'shamarly-qvp' / 'waqf'
VERSION = 'الشمرلي'


def column(client, page: int) -> dict[str, str]:
    data = client.get(f'/api/shamarly/page/{page}?mushaf_version={VERSION}').get_json() or {}
    out = {}
    for line in data.get('lines') or []:
        for w in line.get('words') or []:
            sym = w.get('waqf_symbols')
            if isinstance(sym, list):
                sym = ''.join(x.get('symbols') or '' for x in sym if x.get('version') == VERSION)
            if isinstance(sym, str) and sym.strip() and w.get('word_key'):
                out[w['word_key']] = sym.strip()
    return out


def main(pages: list[int]) -> None:
    os.environ.pop('SUPABASE_URL', None)          # the local column, not the cloud's
    from app import app
    from pipeline.cv_waqf.run_page import detect_page
    OUT.mkdir(parents=True, exist_ok=True)
    client = app.test_client()
    for page in pages:
        det = detect_page(VERSION, page)
        (OUT / f'{page:03d}.json').write_text(json.dumps(det, ensure_ascii=False), encoding='utf-8')
        col = column(client, page)
        (OUT / f'{page:03d}.column.json').write_text(json.dumps(col, ensure_ascii=False), encoding='utf-8')
        print(page, 'detector', len(det['marks']), 'column', len(col), flush=True)


if __name__ == '__main__':
    main([int(a) for a in sys.argv[1:]])
