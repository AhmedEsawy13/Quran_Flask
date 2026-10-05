"""Blind test of the waqf detector on fully hand-labelled pages.

A page counts as *complete* when its labeller says every printed mark is recorded
(``/cv-waqf`` page toggle, ``complete_pages.json``). On such a page every word the labeller
did not mark is a true negative, so a detected mark with no label is a false positive: that is
what ``evaluate-hand`` cannot measure (it only scores labelled seats).

    python -m pipeline.cv_waqf blind-eval --edition المساحة [--model M] [--no-azhar-prior]

The labeller must not have seen the model's output on these pages: ``/cv-waqf`` label mode shows
only words near the click, never detections.
"""
from __future__ import annotations

import argparse
import collections
import json
from pathlib import Path

from pipeline.cv_waqf.config import ARTIFACTS_ROOT, EDITIONS, ROOT

HAND_ROOT = ROOT / 'data' / 'cv' / 'crops_hand'
COMPLETE_FILE = 'complete_pages.json'


def load_complete_pages(slug: str) -> list[int]:
    path = HAND_ROOT / slug / COMPLETE_FILE
    try:
        return sorted({int(p) for p in json.loads(path.read_text(encoding='utf-8')).get('pages', [])})
    except (OSError, ValueError, TypeError):
        return []


def positives_by_page(labels: list[dict], pages: set[int]) -> dict[int, dict[str, dict]]:
    """``{page: {word_key: label}}`` of the positive labels; the latest label per word wins.
    ``none`` rows (rejected crops) are not marks and are ignored."""
    out: dict[int, dict[str, dict]] = {p: {} for p in pages}
    for row in sorted(labels, key=lambda r: (str(r.get('created_at') or ''), str(r.get('id') or ''))):
        page = int(row['page'])
        key = str(row.get('word_key') or '')
        if page not in pages or not key:
            continue
        if row.get('symbol') == 'none':
            continue
        out[page][key] = row
    return out


def score_pages(truth: dict[int, dict[str, dict]], detected: dict[int, dict[str, dict]]) -> dict:
    """Score detections against complete pages.

    ``truth[page][word_key]`` has the labelled ``symbol``; ``detected[page][word_key]`` the
    detector's ``symbol`` and ``confidence``. Every detection with no label is a false positive.
    """
    per_page = []
    tot = collections.Counter()
    by_symbol: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    confusion: collections.Counter = collections.Counter()
    misses, wrong, false_pos = [], [], []
    for page in sorted(truth):
        t, d = truth[page], detected.get(page, {})
        c = collections.Counter()
        for key, label in t.items():
            sym = label['symbol']
            hit = d.get(key)
            if hit is None:
                c['missed'] += 1
                by_symbol[sym]['missed'] += 1
                misses.append({'page': page, 'word_key': key, 'word_text': label.get('word_text', ''), 'expected': sym})
            elif hit['symbol'] == sym:
                c['correct'] += 1
                by_symbol[sym]['correct'] += 1
            else:
                c['wrong_symbol'] += 1
                by_symbol[sym]['wrong_symbol'] += 1
                confusion[(sym, hit['symbol'])] += 1
                wrong.append({'page': page, 'word_key': key, 'word_text': label.get('word_text', ''),
                              'expected': sym, 'actual': hit['symbol'], 'confidence': hit.get('confidence')})
        for key, hit in d.items():
            if key not in t:
                c['false_positive'] += 1
                false_pos.append({'page': page, 'word_key': key, 'word_text': hit.get('word_text', ''),
                                  'actual': hit['symbol'], 'confidence': hit.get('confidence')})
        c['labelled'] = len(t)
        c['detected'] = len(d)
        per_page.append({'page': page, **c})
        tot.update(c)
    labelled = tot['labelled']
    detected_n = tot['detected']
    return {
        'pages': len(truth),
        'labelled_marks': labelled,
        'detected_marks': detected_n,
        'correct': tot['correct'],
        'wrong_symbol': tot['wrong_symbol'],
        'missed': tot['missed'],
        'false_positive': tot['false_positive'],
        'recall': round(tot['correct'] / labelled, 4) if labelled else None,
        'found': round((tot['correct'] + tot['wrong_symbol']) / labelled, 4) if labelled else None,
        'precision': round(tot['correct'] / detected_n, 4) if detected_n else None,
        'by_symbol': {s: dict(c) for s, c in sorted(by_symbol.items())},
        'confusion': {f'{a}->{b}': n for (a, b), n in confusion.most_common()},
        'per_page': per_page,
        'missed_marks': misses,
        'wrong_marks': wrong,
        'false_positives': sorted(false_pos, key=lambda r: -(r['confidence'] or 0)),
    }


def detect_marks(edition: str, pages: list[int], *, min_conf: float, model_path: Path | None,
                 azhar_prior: bool | None, proposal_mode: str | None) -> dict[int, dict[str, dict]]:
    from pipeline.cv_waqf.run_page import detect_page

    out: dict[int, dict[str, dict]] = {}
    for page in pages:
        kwargs = {'min_conf': min_conf, 'proposal_mode': proposal_mode, 'azhar_prior': azhar_prior}
        if model_path is not None:
            kwargs['model_path'] = model_path
        result = detect_page(edition, page, **kwargs)
        out[page] = {
            str(m['word_key']): {'symbol': m.get('symbol'), 'confidence': m.get('confidence'),
                                 'word_text': m.get('word_text') or m.get('text') or ''}
            for m in result.get('marks') or [] if m.get('word_key')
        }
    return out


def format_summary(report: dict) -> str:
    pct = lambda v: 'n/a' if v is None else f'{100 * v:.1f}%'
    lines = [
        f"pages {report['pages']} · labelled marks {report['labelled_marks']} · detected {report['detected_marks']}",
        f"recall (right symbol) {pct(report['recall'])} · found at all {pct(report['found'])} · "
        f"precision {pct(report['precision'])}",
        f"correct {report['correct']} · wrong symbol {report['wrong_symbol']} · "
        f"missed {report['missed']} · false positives {report['false_positive']}",
        'by symbol: ' + ', '.join(
            f"{s} {c.get('correct', 0)}/{sum(c.values())}" for s, c in report['by_symbol'].items()),
    ]
    if report['confusion']:
        lines.append('confusions: ' + ', '.join(f'{k} ×{n}' for k, n in report['confusion'].items()))
    return '\n'.join(lines)


def main(argv: list[str] | None = None) -> int:
    from pipeline.cv_waqf.evaluate_hand import _parse_pages, load_anchored_labels

    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--edition', required=True, choices=list(EDITIONS))
    parser.add_argument('--pages', default=None, help='default: the pages marked complete in /cv-waqf')
    parser.add_argument('--min-conf', type=float, default=0.55)
    parser.add_argument('--model', type=Path, default=None)
    parser.add_argument('--proposal-mode', default=None)
    parser.add_argument('--azhar-prior', action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument('--out', type=Path, default=None)
    args = parser.parse_args(argv)
    spec = EDITIONS[args.edition]
    pages = _parse_pages(args.pages) if args.pages else load_complete_pages(spec.id)
    if not pages:
        raise SystemExit('no complete pages: label a page in /cv-waqf and tick "الصفحة مكتملة" first')
    truth = positives_by_page(load_anchored_labels(spec.id), set(pages))
    empty = [p for p, t in truth.items() if not t]
    if empty:
        print(f'note: complete pages with no labels at all (a page with no marks?): {empty}')
    detected = detect_marks(
        args.edition, pages, min_conf=args.min_conf, model_path=args.model,
        azhar_prior=args.azhar_prior, proposal_mode=args.proposal_mode,
    )
    report = score_pages(truth, detected)
    report.update(edition=args.edition, model=str(args.model) if args.model else 'production',
                  min_conf=args.min_conf, azhar_prior=args.azhar_prior)
    out = args.out or ARTIFACTS_ROOT / f'blind-eval-{spec.id}.json'
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(format_summary(report))
    print(f'wrote {out}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
