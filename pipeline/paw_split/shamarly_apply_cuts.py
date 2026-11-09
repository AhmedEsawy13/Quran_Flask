"""Apply the knife cuts the agents chose for fused outlines (shamarly_cut_pilot.py) through ShemrlyMushaf's own line-editor API.

    ~/Development/ShemrlyMushaf/.venv/bin/python pipeline/paw_split/shamarly_apply_cuts.py \
        --cases artifacts/shamarly-qvp/cut-empty [--root <output/pdf copy>] [--db <glyph_mappings.db copy>] [--dry-run-report]

For each case with a choice: the chord (page points) goes to the line glyph's frame, line_ownership.cut_line_outline cuts the
outline there (line-cuts.json of the page folder) and designates the pieces, and the two pieces are then GIVEN explicitly, the
one on the empty word's side to the empty word and the other to the neighbour that held the fused outline
(line_ownership.assign_line_outlines). Everything is written as editor «claude-knife». Run it first on copies of the database and
the page folders (--root/--db) and look at the rebuilt pages; the real run needs backups of both (ShemrlyMushaf/backups).
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

SH = Path.home() / 'Development' / 'ShemrlyMushaf'
sys.path.insert(0, str(SH))
EDITOR = 'claude-knife'
RUN = 'batch-rest'


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--cases', required=True, type=Path)
    ap.add_argument('--root', type=Path, default=SH / 'output' / 'pdf')
    ap.add_argument('--db', type=Path, default=SH / 'glyph_mappings.db')
    ap.add_argument('--suffix', default='')
    a = ap.parse_args()
    import line_cuts
    from line_moves import line_outlines
    from line_ownership import assign_line_outlines, cut_line_outline
    from pdf_glyph_editor import CONTENT_X0, PDF_TO_FONT, load_page_report
    from pdf_review_store import load_page_review

    info = json.loads((a.cases / 'truth' / f'shared{a.suffix}.json').read_text(encoding='utf-8'))
    picks = {}
    for f in sorted((a.cases / 'results').glob(f'cutter{a.suffix}_*.jsonl')):
        for line in f.read_text(encoding='utf-8').splitlines():
            if line.strip():
                r = json.loads(line)
                picks[r['id']] = r
    db = sqlite3.connect(a.db, timeout=60)
    db.row_factory = sqlite3.Row
    done = []
    for cid, c in sorted(info.items()):
        r = picks.get(cid)
        if not r or r['choice'] in ('none', None, 0):
            continue
        cand = c['cands'][int(r['choice']) - 1]
        page, ln = c['page'], c['line']
        page_dir = a.root / RUN / f'page-{page:03d}'
        report = load_page_report(page_dir)
        bottom = float(next(l for l in report['lines'] if int(l['line_number']) == ln)['bbox'][3])
        to_font = lambda p: ((p[0] - CONTENT_X0) * PDF_TO_FONT, (bottom - p[1]) * PDF_TO_FONT)
        p0, p1 = to_font(cand['p0']), to_font(cand['p1'])
        review = load_page_review(db, RUN, page, a.root)
        try:
            summary = cut_line_outline(db, RUN, page, page_dir, report, None, {'line_number': ln}, p0, p1, EDITOR, review, raw_frame=True)
        except Exception as exc:                                          # a chord the line editor refuses is reported, not forced
            print(cid, 'REFUSED:', exc)
            continue
        if summary.get('cut') != [c['oid']]:
            print(cid, 'cut a different outline', summary.get('cut'), 'wanted', c['oid'], '- undoing')
            for oid in summary.get('cut', []):
                line_cuts.remove_cut(page_dir, ln, int(oid.rsplit(':C', 1)[1]))
            continue
        # the pieces, by position: the one left of the other is nearer the left word
        pieces = {}
        for suffix, raw, _p in line_outlines(page_dir, report, ln):
            if f'L{ln}:{suffix}' in (c['oid'] + 'a', c['oid'] + 'b'):
                xs = [float(q[0]) for _op, args in raw for q in args if q is not None]
                pieces[f'L{ln}:{suffix}'] = sum(xs) / len(xs)
        left_piece, right_piece = sorted(pieces, key=pieces.get)
        empty_key = c['empty_key']
        neighbour = c['right'] if c['owner_side'] == 'right' else c['left']
        # the neighbour is on the owner_side of the empty word: right neighbour -> right piece stays with it
        moves = ({right_piece: neighbour, left_piece: empty_key} if c['owner_side'] == 'right'
                 else {left_piece: neighbour, right_piece: empty_key})
        review = load_page_review(db, RUN, page, a.root)
        summary2 = assign_line_outlines(db, RUN, page, page_dir, report, ln, moves, EDITOR, review)
        db.commit()
        done.append(cid)
        print(cid, f'page {page} line {ln}', c['oid'], '->', moves, '| words changed', summary2.get('words'))
    print(f'{len(done)} cuts applied: {done}')


if __name__ == '__main__':
    main()
