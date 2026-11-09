"""Score the Shamarly word-owner model against the exact outline labels of ShemrlyMushaf's blind pages
(output/exact-labels/page-NNN.json, extracted from the Elgharib word glyphs; output/pdf/pipeline-eval/ holds the
extraction), and measure how much the outline-count text check (text_check.py) can say about those words.

Run with the ShemrlyMushaf venv, from this repository's root:

    ~/Development/ShemrlyMushaf/.venv/bin/python pipeline/paw_split/shamarly_owner_eval.py [pages ...]

Words exact = every labelled outline of the word has the word as owner and no other word's outline does
(exact_score.py's definition). 2026-11-09, nine blind pages (1,361 words): 91.92% exact, 98.95% of outlines.

The text check cannot drive a repair: on the TRUE outlines of the words the model got right only 552/1,251 (44.1%)
pass it, and of the 110 it got wrong only 25 (22.7%) would pass even after a perfect fix. A search that hands
outlines across word boundaries until both neighbours pass (tried the same day) made 6 moves on these pages:
3 wrong->right, 3 right->wrong, so it was dropped.
"""
from __future__ import annotations

import collections
import json
import sqlite3
import sys
from pathlib import Path

SHEMRLY = Path.home() / 'Development' / 'ShemrlyMushaf'
sys.path.insert(0, str(SHEMRLY))
sys.path.insert(0, str(Path(__file__).resolve().parent))
RUN = 'pipeline-eval'
LABELS = SHEMRLY / 'output' / 'exact-labels'


def main() -> None:
    from line_moves import line_outlines
    from line_ownership import line_editor_payload
    from pdf_glyph_editor import CONTENT_X0, PDF_TO_FONT, load_page_report
    from pdf_review_store import DEFAULT_OUTPUT_ROOT, load_page_review, page_directory
    from word_owner_model import line_owner
    import text_check
    from shamarly_qvp_svg import _bbox_pt

    pages = [int(p) for p in sys.argv[1:]] or [204, 212, 219, 245, 251, 337, 371, 373, 481]
    model = json.loads(text_check.MODEL_PATH.read_text(encoding='utf-8'))
    predict = lambda t: text_check.predict(model, t)
    db = sqlite3.connect(SHEMRLY / 'glyph_mappings.db', timeout=60)
    db.row_factory = sqlite3.Row
    sdb = sqlite3.connect(SHEMRLY / 'quran_script.db')
    text_of = {i: t for i, t in sdb.execute('SELECT word_index, text FROM words')}
    layout = sqlite3.connect(SHEMRLY / 'mushaf_layout_inferred.db')

    tot = collections.Counter()
    for n in pages:
        lab = json.loads((LABELS / f'page-{n:03d}.json').read_text(encoding='utf-8'))
        truth = [(b, lab['labels'].get(str(i))) for i, b in enumerate(lab['pdf_outlines'])]
        page_dir = page_directory(RUN, n, DEFAULT_OUTPUT_ROOT)
        report = load_page_report(page_dir)
        review = load_page_review(db, RUN, n, DEFAULT_OUTPUT_ROOT)
        ltypes = dict(layout.execute('SELECT line_number, line_type FROM pages WHERE page_number=?', (n,)).fetchall())
        own, gt, small = {}, {}, {}
        for line in report['lines']:
            ln = int(line['line_number'])
            if ltypes.get(ln) != 'ayah':
                continue
            payload = line_editor_payload(db, RUN, n, page_dir, report, ln, review)
            owners, _source = line_owner(payload, report, n)
            comp = {c['id']: c for c in payload['components']}
            bottom = float(line['bbox'][3])
            wi_of = {w['key']: w['word_index'] for w in payload['words']}
            box = {}
            for suffix, raw, _p in line_outlines(page_dir, report, ln):
                box[f'L{ln}:{suffix}'] = _bbox_pt(raw, PDF_TO_FONT, CONTENT_X0, bottom)
            owner = {o: k for o, k in owners.items() if o in box}
            for oid in box:                                    # a hole goes with the outline it sits in
                host = (comp.get(oid) or {}).get('hole_of')
                if host and host in owner:
                    owner[oid] = owner[host]
            for o, b0 in box.items():                          # truth by box centre, as exact_score.py does
                c = ((b0[0] + b0[2]) / 2, (b0[1] + b0[3]) / 2)
                b, w = min(truth, key=lambda t: abs((t[0][0] + t[0][2]) / 2 - c[0]) + abs((t[0][1] + t[0][3]) / 2 - c[1]))
                if abs((b[0] + b[2]) / 2 - c[0]) + abs((b[1] + b[3]) / 2 - c[1]) < 0.8:
                    gt[o] = w
                    small[o] = (b0[3] - b0[1]) < 9.0 and (b0[2] - b0[0]) * (b0[3] - b0[1]) < 28.0
            own.update({o: wi_of.get(k) for o, k in owner.items()})

        words, wrong_in = collections.defaultdict(lambda: [0, 0, 0]), collections.Counter()
        for o, w in gt.items():
            if w is None:
                continue
            words[w][0] += 1
            words[w][1] += own.get(o) == w
            words[w][2] += small[o]
            if own.get(o) not in (None, w):
                wrong_in[own[o]] += 1
        exact = {w for w, (k, g, _s) in words.items() if k == g and wrong_in[w] == 0}
        for w, (k, _g, s) in words.items():                   # does the text check pass on the word's TRUE outlines?
            if w in text_of:
                kind = 'right' if w in exact else 'wrong'
                tot[kind] += 1
                tot[f'{kind}_pass'] += predict(text_of[w]) == (k, s)
        outl = sum(1 for o, w in gt.items() if w is not None and own.get(o) == w)
        n_out = sum(1 for w in gt.values() if w is not None)
        print(f'page {n}: words exact {len(exact)}/{len(words)}   outlines right {outl}/{n_out}', flush=True)
        tot.update(words=len(words), exact=len(exact), outlines=n_out, outlines_right=outl)
    print(f'\nALL: words exact {tot["exact"]}/{tot["words"]} = {tot["exact"] / tot["words"]:.2%};  outlines right '
          f'{tot["outlines_right"] / tot["outlines"]:.2%}')
    for kind in ('right', 'wrong'):
        print(f'text check on the TRUE outlines of words the model got {kind}: {tot[f"{kind}_pass"]}/{tot[kind]} pass')


if __name__ == '__main__':
    main()
