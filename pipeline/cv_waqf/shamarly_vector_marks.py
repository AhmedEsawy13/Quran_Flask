"""Small-mark clusters for الشمرلي pages, from its vector PDF (one-off export).

In the page image a waqf sign that touches a descender of the line above merges into one large ink
blob, and the line-component proposals skip it as too big. In the vector PDF the sign is still its
own small contours. This groups the small contours (ShemrlyMushaf's ``is_small_mark``) whose boxes are
within GAP points of each other and writes each group's box in the page images' 1024 px space, for
the detector to use as extra candidates.

    /Users/mac/Development/ShemrlyMushaf/.venv/bin/python pipeline/cv_waqf/shamarly_vector_marks.py
"""
import json
import sys
from pathlib import Path

SHEMRLY = Path('/Users/mac/Development/ShemrlyMushaf')
sys.path.insert(0, str(SHEMRLY))
import fitz  # noqa: E402
from extract_pdf_pages import (CONTENT_X0, CONTENT_X1, CONTENT_Y0, CONTENT_Y1,  # noqa: E402
                               is_quran_black, is_small_mark, split_contours)

OUT = Path(__file__).resolve().parents[2] / 'data' / 'refs' / 'shamarly_pdf' / 'mark_boxes.json'
GAP = 1.2


def clusters(boxes: list[list[float]]) -> list[list[float]]:
    boxes = [b[:] for b in boxes]
    merged = True
    while merged:
        merged = False
        out: list[list[float]] = []
        for b in boxes:
            for o in out:
                if b[0] <= o[2] + GAP and o[0] <= b[2] + GAP and b[1] <= o[3] + GAP and o[1] <= b[3] + GAP:
                    o[:] = [min(o[0], b[0]), min(o[1], b[1]), max(o[2], b[2]), max(o[3], b[3])]
                    merged = True
                    break
            else:
                out.append(b)
        boxes = out
    return boxes


def main() -> int:
    doc = fitz.open(SHEMRLY / 'BOOK_27111_1.pdf')
    pages = {}
    for pn in range(2, 523):
        page = doc[pn - 1]
        s = 1024 / page.rect.width
        small = []
        for d in page.get_drawings():
            if not is_quran_black(d):
                continue
            for c in split_contours(d):
                if CONTENT_X0 <= c.cx <= CONTENT_X1 and CONTENT_Y0 <= c.cy <= CONTENT_Y1 and is_small_mark(c):
                    small.append(list(c.bbox))
        pages[str(pn)] = [[round(v * s) for v in b] for b in clusters(small)]
    OUT.write_text(json.dumps({'source': 'BOOK_27111_1.pdf', 'units': 'px at 1024 width', 'gap_pt': GAP, 'pages': pages}))
    print(len(pages), 'pages;', sum(len(v) for v in pages.values()), 'clusters ->', OUT)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
