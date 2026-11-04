"""Fetch a print's page scans from tafsir.app into its page cache at the 1024 working width.

    python3 -m pipeline.cv_waqf.fetch_scans aalalbayt [first last]
    python3 -m pipeline.cv_waqf.fetch_scans tajweed_maarifa [first last]

Writes ``p{page:03d}_w1024.jpg`` into the edition's ``page_cache_dir`` (data/refs, gitignored); pages already
there are skipped, so a stopped run resumes. Prints whose pages carry a margin column outside the ornamental
frame (the Dar al-Maarifa tajweed mushaf's word meanings, on alternating sides) are cropped to the frame first.
"""
from __future__ import annotations

import io
import sys
import time
import urllib.request
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]

SOURCES = {
    # مصحف آل البيت (Jordan, Ministry of Awqaf): scan N = printed page + 2, 620x877; a stray copy of page 598
    # sits at scan 573, so from page 571 on scan N = page + 3
    'aalalbayt': dict(url='https://tafsir.app/scans/m-aalalbayt/{n}.jpg', offset=2, shift={571: 3}, crop=False,
                      cache=ROOT / 'data' / 'refs' / 'aalalbayt' / 'cache'),
    # مصحف التجويد, Dar al-Maarifa (Damascus, Uthman Taha): scan N = printed page - 1, 1298x1870
    'tajweed_maarifa': dict(url='https://tafsir.app/scans/m-tajweed-orig/{n}.jpg', offset=-1, crop=True,
                            cache=ROOT / 'data' / 'refs' / 'tajweed_maarifa' / 'cache'),
}


def crop_to_frame(im: Image.Image, page: int) -> Image.Image:
    """The frame sits at fixed columns on each side of the spread (measured on scans 100-502): even pages
    have the margin column on the left, odd pages on the right."""
    w, h = im.size
    left, right = (0.150, 0.990) if page % 2 == 0 else (0.010, 0.850)
    return im.crop((int(left * w), 0, int(right * w), h))


def fetch(name: str, first: int = 1, last: int = 604) -> list[tuple[int, str]]:
    src = SOURCES[name]
    src['cache'].mkdir(parents=True, exist_ok=True)
    failed = []
    for page in range(first, last + 1):
        dst = src['cache'] / f'p{page:03d}_w1024.jpg'
        if dst.exists():
            continue
        offset = src['offset']
        for first_page, later in sorted(src.get('shift', {}).items()):
            if page >= first_page:
                offset = later
        url = src['url'].format(n=page + offset)
        for attempt in range(4):
            try:
                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (research; waqf sign study)'})
                im = Image.open(io.BytesIO(urllib.request.urlopen(req, timeout=60).read())).convert('RGB')
                if src['crop']:
                    im = crop_to_frame(im, page)
                im.resize((1024, round(im.height * 1024 / im.width)), Image.LANCZOS).save(dst, quality=92)
                break
            except Exception as error:                 # noqa: BLE001 - retry any network error
                if attempt == 3:
                    failed.append((page, str(error)))
                time.sleep(3 * (attempt + 1))
        time.sleep(0.3)                                # polite to the host
        if page % 50 == 0:
            print('fetched to', page, flush=True)
    print(name, 'failed:', failed or 'none')
    return failed


if __name__ == '__main__':
    args = sys.argv[1:]
    fetch(args[0], *map(int, args[1:3]))
