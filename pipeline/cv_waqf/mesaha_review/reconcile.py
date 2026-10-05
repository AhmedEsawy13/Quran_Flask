"""Re-open finished pages after the proposals changed, and tag the proposals that moved.

    PYTHONPATH=. python3 -m pipeline.cv_waqf.mesaha_review.reconcile OLD_PAGES.json [--apply]

When the attachment or the models change, a page the reviewer already finished can hold proposals
they never saw. A finished page treats anything unreviewed as "not a mark", so such a page would
silently lose them. This lists them, tags each proposal that sits next to a word the reviewer
rejected (the same detection, now on the right word: ``moved_from``), and with ``--apply`` takes
those pages out of ``done.json`` so the tool shows them again. The reviewer's decisions are kept.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

DATA = Path(__file__).resolve().parents[3] / 'artifacts' / 'cv-waqf' / 'mesaha-selflearn'


def reconcile(old_pages: list[dict], new_pages: list[dict], verdicts: dict, done: list[int]) -> dict:
    """``{'pages': annotated new pages, 'reopen': [pages], 'report': {...}}``; pure."""
    old = {p['page']: p for p in old_pages}
    new = {p['page']: p for p in new_pages}
    reopen, report = [], {'moved': 0, 'new_items': 0, 'lost_marks': []}
    for page in done:
        if page not in new:
            continue
        index = {w['key']: i for i, w in enumerate(new[page]['words'])}
        rejected = {
            k.split(':', 1)[1] for k, v in verdicts.items() if k.startswith(f'{page}:') and v == '-'
        }
        old_symbol = {q['key']: q['symbol'] for q in (old.get(page) or {}).get('proposals', [])}
        unresolved = 0
        for q in new[page]['proposals']:
            if verdicts.get(f"{page}:{q['key']}") is not None or q['default'] != 'review':
                continue
            unresolved += 1
            for a in rejected:
                if (a in index and q['key'] in index and abs(index[a] - index[q['key']]) == 1
                        and old_symbol.get(a) == q['symbol']):
                    word = new[page]['words'][index[a]]
                    q['moved_from'] = {'key': a, 'text': word['text']}
                    report['moved'] += 1
                    break
        report['new_items'] += unresolved
        if unresolved:
            reopen.append(page)
        # a mark the reviewer ended with that is no longer proposed on its word
        keys = {q['key'] for q in new[page]['proposals']}
        for q in (old.get(page) or {}).get('proposals', []):
            v = verdicts.get(f"{page}:{q['key']}")
            final = v if v is not None else (q['symbol'] if q['default'] == 'accept' else None)
            if final and final != '-' and q['key'] not in keys:
                report['lost_marks'].append((page, q['key'], final))
    return {'pages': new_pages, 'reopen': reopen, 'report': report}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('old_pages')
    parser.add_argument('--apply', action='store_true', help='write pages.json (tags) and re-open the pages')
    args = parser.parse_args(argv)
    old = json.loads(Path(args.old_pages).read_text(encoding='utf-8'))
    new = json.loads((DATA / 'pages.json').read_text(encoding='utf-8'))
    verdicts = json.loads((DATA / 'verdicts.json').read_text(encoding='utf-8')) if (DATA / 'verdicts.json').is_file() else {}
    done = json.loads((DATA / 'done.json').read_text(encoding='utf-8')) if (DATA / 'done.json').is_file() else []
    out = reconcile(old, new, verdicts, done)
    print(json.dumps(out['report'], ensure_ascii=False))
    print('pages to re-open:', out['reopen'])
    if args.apply:
        (DATA / 'pages.json').write_text(json.dumps(out['pages'], ensure_ascii=False), encoding='utf-8')
        (DATA / 'done.json').write_text(json.dumps(sorted(set(done) - set(out['reopen']))), encoding='utf-8')
        print('re-opened', len(out['reopen']), 'pages')
    return 0


if __name__ == '__main__':
    sys.exit(main())
