"""Exact line bands for الشمرلي from its vector PDF (one-off export).

The Shamarly print exists as a vector PDF (BOOK_27111_1.pdf, the same file our page images
are rendered from). The ShemrlyMushaf project's ``extract_lines`` splits every page's black
contours into its text lines (~100% recall in that project). This writes, per page and layout
line, the line's baseline centre and band in PDF points plus the page width, so the CV
pipeline can place lines exactly instead of estimating them (surah banners are ~1.6 lines tall
and broke the uniform grid).

Run with the ShemrlyMushaf venv (it has fitz/scipy and the extractor):

    /Users/mac/Development/ShemrlyMushaf/.venv/bin/python pipeline/cv_waqf/shamarly_vector_lines.py
"""
import json
import sys
from pathlib import Path

SHEMRLY = Path('/Users/mac/Development/ShemrlyMushaf')
sys.path.insert(0, str(SHEMRLY))
import fitz  # noqa: E402
from extract_pdf_pages import extract_lines, load_layout, render_pdf_page  # noqa: E402

OUT = Path(__file__).resolve().parents[2] / 'data' / 'refs' / 'shamarly_pdf' / 'vector_lines.json'
SCALE = 2


def main() -> int:
    doc = fitz.open(SHEMRLY / 'BOOK_27111_1.pdf')
    pages, failed = {}, []
    for page_number in range(2, 523):
        try:
            layout = load_layout(SHEMRLY / 'mushaf_layout_inferred.db', page_number)
            page = doc[page_number - 1]
            image = render_pdf_page(page, SCALE)
            lines = extract_lines(page, layout, image, SCALE)
        except Exception as exc:  # noqa: BLE001
            failed.append((page_number, repr(exc)))
            continue
        pages[str(page_number)] = {
            'width_pt': float(page.rect.width),
            'lines': [{
                'line_number': ln.layout.number, 'line_type': ln.layout.line_type,
                'center': round(float(ln.center_y), 2),
                'top': round(float(ln.band_top), 2), 'bottom': round(float(ln.band_bottom), 2),
                'x0': round(min((c.bbox[0] for c in ln.contours), default=0.0), 2),
                'x1': round(max((c.bbox[2] for c in ln.contours), default=0.0), 2),
                'contours': len(ln.contours),
            } for ln in lines],
        }
    OUT.write_text(json.dumps({'source': 'BOOK_27111_1.pdf', 'units': 'pdf points', 'pages': pages}, ensure_ascii=False))
    print(f'{len(pages)} pages written to {OUT}; failed {len(failed)}: {failed[:5]}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
