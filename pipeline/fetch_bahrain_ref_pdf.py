#!/usr/bin/env python3
"""Download the printed مصحف البحرين PDF used as the mushaf-editor reference.

Source (islamhouse):
  https://d1.islamhouse.com/data/ar/ih_books/single_02/ar-mushaf-albahrains.pdf

Saves to data/refs/ar-mushaf-albahrains.pdf (gitignored — ~43MB).
Mushaf page N maps to PDF index N+4 (page 1 = PDF page 6 / index 5).
"""

from __future__ import annotations

import os
import sys
import urllib.request

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT_DIR)

from core.config import BAHRAIN_REF_PDF, BAHRAIN_REF_PDF_URL  # noqa: E402

MIN_BYTES = 10_000_000


def main() -> int:
    os.makedirs(os.path.dirname(BAHRAIN_REF_PDF), exist_ok=True)
    if os.path.isfile(BAHRAIN_REF_PDF) and os.path.getsize(BAHRAIN_REF_PDF) >= MIN_BYTES:
        print(f"Already present: {BAHRAIN_REF_PDF} ({os.path.getsize(BAHRAIN_REF_PDF)} bytes)")
        return 0

    tmp = BAHRAIN_REF_PDF + '.partial'
    print(f"Downloading {BAHRAIN_REF_PDF_URL}")
    print(f" → {BAHRAIN_REF_PDF}")
    try:
        urllib.request.urlretrieve(BAHRAIN_REF_PDF_URL, tmp)
    except Exception as e:
        print(f"ERROR: download failed: {e}")
        if os.path.isfile(tmp):
            os.remove(tmp)
        return 1

    size = os.path.getsize(tmp)
    if size < MIN_BYTES:
        print(f"ERROR: file too small ({size} bytes) — aborting")
        os.remove(tmp)
        return 1

    os.replace(tmp, BAHRAIN_REF_PDF)
    print(f"Saved {size} bytes")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
