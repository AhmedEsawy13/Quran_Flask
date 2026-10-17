"""Letter-body-only masks for الشمرلي pages, from its vector PDF (one-off export, experiment).

Dots, harakat and waqf signs are small separate contours in the PDF (ShemrlyMushaf's
``is_small_mark``). Leaving them out gives a mask where the gaps between words are not bridged
by marks. Written at the page images' 1024 px width as 1-bit PNGs.

    /Users/mac/Development/ShemrlyMushaf/.venv/bin/python pipeline/cv_waqf/shamarly_body_masks.py [first last]
"""
import sys
from pathlib import Path

SHEMRLY = Path('/Users/mac/Development/ShemrlyMushaf')
sys.path.insert(0, str(SHEMRLY))
import fitz  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402
from extract_pdf_pages import (CONTENT_X0, CONTENT_X1, CONTENT_Y0, CONTENT_Y1,  # noqa: E402
                               is_quran_black, is_small_mark, points_in_item, split_contours)

OUT = Path(__file__).resolve().parents[2] / 'data' / 'refs' / 'shamarly_pdf' / 'bodymask'


def main(first: int = 2, last: int = 522) -> int:
    doc = fitz.open(SHEMRLY / 'BOOK_27111_1.pdf')
    OUT.mkdir(parents=True, exist_ok=True)
    for pn in range(first, last + 1):
        page = doc[pn - 1]
        s = 1024 / page.rect.width
        img = Image.new('1', (1024, int(round(page.rect.height * s))), 0)
        draw = ImageDraw.Draw(img)
        for d in page.get_drawings():
            if not is_quran_black(d):
                continue
            for c in split_contours(d):
                if not (CONTENT_X0 <= c.cx <= CONTENT_X1 and CONTENT_Y0 <= c.cy <= CONTENT_Y1) or is_small_mark(c):
                    continue
                pts = [(p.x * s, p.y * s) for it in c.items for p in points_in_item(it)]
                if len(pts) >= 3:
                    draw.polygon(pts, fill=1)
        img.save(OUT / f'p{pn:03d}.png', optimize=True)
    print('wrote', last - first + 1, 'masks to', OUT)
    return 0


if __name__ == '__main__':
    raise SystemExit(main(*map(int, sys.argv[1:3])))
