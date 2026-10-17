"""Word spans per line for الشمرلي pages without a usable page font (one-off export).

ShemrlyMushaf's template-guided partition (vector contours + Elgharib glyphs of the same words on
other pages + ink gaps) never reached its own goal of perfect word glyphs (~43%), but its word
BOUNDARIES are good: on 96 held-out font pages, audits with its cuts scored 92.57% against 88.18% for
letter-count widths and 93.41% for the true font widths. Run blind (the page's own glyphs withheld),
one page per process, then merge the per-page outputs into data/refs/shamarly_pdf/word_cuts.json:

    <ShemrlyMushaf venv>/bin/python -I pipeline/cv_waqf/shamarly_word_cuts.py OUT.json PAGE [PAGE ...]

About 75-100 s per page.
"""
import json, sys, time
from pathlib import Path
S = Path('/Users/mac/Development/ShemrlyMushaf'); sys.path.insert(0, str(S))
import fitz
import extract_pdf_pages as E

out, pages = Path(sys.argv[1]), [int(p) for p in sys.argv[2:]]
model = E.WidthModel(S / 'glyph_mappings.db', S / 'static' / 'fonts')
templates = E.TemplateLibrary(S / 'glyph_mappings.db', S / 'static' / 'fonts', component_fallback=False, component_weight=0.32)
ranker = E.BoundaryRanker.load(S / 'output' / 'pdf' / 'boundary-ranker.json') if (S / 'output/pdf/boundary-ranker.json').exists() else None
doc = fitz.open(S / 'BOOK_27111_1.pdf')
res = json.loads(out.read_text()) if out.exists() else {}
scale = 3
for pn in pages:
    t = time.time()
    layout = E.load_layout(S / 'mushaf_layout_inferred.db', pn)
    held = {w for ln in layout if ln.first_word is not None and ln.last_word is not None for w in range(ln.first_word, ln.last_word + 1)}
    model.set_exclusions(held); templates.clear_candidate_cache(); templates.excluded_word_indices = held
    page = doc[pn - 1]
    img = E.render_pdf_page(page, scale); mask = E.black_mask(img)
    lines = E.extract_lines(page, layout, img, scale)
    rec = {'width_pt': float(page.rect.width), 'lines': {}}
    for line in lines:
        if line.layout.line_type != 'ayah':
            continue
        cells = E.template_guided_partition(line, model, templates, mask, scale, ranker=ranker)
        rec['lines'][str(line.layout.number)] = [[c.word_index, round(c.left, 2), round(c.right, 2), c.segmentation_method] for c in cells]
    res[str(pn)] = rec
    out.write_text(json.dumps(res))
    print(pn, len(rec['lines']), 'lines', round(time.time() - t, 1), 's', flush=True)
