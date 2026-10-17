"""Full-line context images for book-audit review cards.

A card's small crop is centred on the detector's box (or, for a missed mark, on the word's
estimated position), and on some pages that box sits a little off the printed sign. The line view
shows the whole width of the text, about five lines high, with the card's word framed in green
and the detector's box in red, so a reviewer can always find the actual mark.
"""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path

GREEN, RED = (40, 150, 40), (40, 40, 220)


def _band(h: int, cy: float, line_h: float) -> tuple[int, int]:
    # five lines: the estimated word position can be a whole line off on some pages
    y0 = int(max(0, cy - 2.7 * line_h))
    y1 = int(min(h, cy + 2.3 * line_h))
    return y0, y1


def write_line_views(edition: str, out_dir: Path, items: list[dict]) -> dict[str, str]:
    """{crop name: line-view file name} for ``items`` (dicts with page, word_key, crop, box?)."""
    import cv2

    from pipeline.cv_waqf.config import EDITIONS
    from pipeline.cv_waqf.layout_geo import estimate_layout_words
    from pipeline.cv_waqf.pages import ensure_page_image
    from pipeline.cv_waqf.preprocess import load_bgr, preprocess_page

    spec = EDITIONS[edition]
    crops = out_dir / 'crops'
    by_page: dict[int, list[dict]] = defaultdict(list)
    for i in items:
        by_page[int(i['page'])].append(i)
    out: dict[str, str] = {}
    for page, cards in sorted(by_page.items()):
        try:
            prep = preprocess_page(load_bgr(ensure_page_image(spec, page)), spec, page=page)
            words = {w.word_key: w for w in estimate_layout_words(spec, page, prep)}
        except Exception as exc:  # noqa: BLE001 — one page must not stop the queue
            print(f'  line view p{page}: {exc!r}')
            continue
        img = cv2.cvtColor(prep.gray, cv2.COLOR_GRAY2BGR)
        h = img.shape[0]
        top, bottom = spec.band_for_page(page)
        line_h = h * (bottom - top) / 15.0
        for i in cards:
            name = Path(i['crop']).stem + '_line.jpg'
            w = words.get(i['word_key'])
            box = i.get('box')
            ys = [v for v in ((w.y0 + w.y1) / 2 if w else None, (box[1] + box[3]) / 2 if box else None) if v is not None]
            if not ys:
                continue
            y0, y1 = _band(h, sum(ys) / len(ys), line_h)
            view = img[y0:y1].copy()
            if w:
                cv2.rectangle(view, (w.x0 - 3, w.y0 - y0 - 3), (w.x1 + 3, w.y1 - y0 + 3), GREEN, 2)
            if box:
                cv2.rectangle(view, (box[0] - 3, box[1] - y0 - 3), (box[2] + 3, box[3] - y0 + 3), RED, 2)
            cv2.imwrite(str(crops / name), view, [cv2.IMWRITE_JPEG_QUALITY, 85])
            out[i['crop']] = name
    return out
