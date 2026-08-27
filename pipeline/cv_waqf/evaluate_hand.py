"""Evaluate end-to-end mark + canonical-word accuracy on hand labels."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from pipeline.cv_waqf.config import (
    ARTIFACTS_ROOT,
    EDITIONS,
    PROPOSAL_MODES,
    ROOT,
    resolve_azhar_seat_prior,
    resolve_proposal_mode,
)
from pipeline.cv_waqf.run_page import detect_page

HAND_ROOT = ROOT / 'data' / 'cv' / 'crops_hand'


def load_anchored_labels(slug: str) -> list[dict]:
    path = HAND_ROOT / slug / 'labels.jsonl'
    if not path.is_file():
        return []
    rows: list[dict] = []
    for line in path.read_text(encoding='utf-8').splitlines():
        try:
            row = json.loads(line)
            page = int(row['page'])
            word_key = str(row.get('word_key') or '').strip()
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            continue
        if not word_key:
            continue
        rows.append({**row, 'page': page, 'word_key': word_key})
    return rows


def collapse_word_expectations(labels: list[dict]) -> tuple[list[dict], dict]:
    """Turn crop labels into one end-to-end expectation per Quran word.

    ``none`` is primarily a candidate-crop class.  A reviewer can therefore
    reject a false crop that was attached to the same word as a real mark.
    Counting both rows as word-level expectations makes that word
    simultaneously positive and negative.  Keep every crop for training, but
    collapse evaluation by ``(page, word_key)`` and let a confirmed positive
    take precedence over crop-level negatives.
    """
    grouped: dict[tuple[int, str], list[dict]] = {}
    for row in labels:
        key = (int(row['page']), str(row['word_key']))
        grouped.setdefault(key, []).append(row)

    collapsed: list[dict] = []
    conflicting_positive_seats = 0
    for rows in grouped.values():
        positives = [row for row in rows if row.get('symbol') != 'none']
        pool = positives or rows
        if len({str(row.get('symbol')) for row in positives}) > 1:
            conflicting_positive_seats += 1
        # Prefer the latest review when duplicate crops/edits exist.
        collapsed.append(max(
            pool,
            key=lambda row: (
                str(row.get('created_at') or ''),
                str(row.get('id') or ''),
            ),
        ))

    collapsed.sort(key=lambda row: (int(row['page']), str(row['word_key'])))
    return collapsed, {
        'raw_crop_labels': len(labels),
        'ignored_crop_or_duplicate_labels': len(labels) - len(collapsed),
        'conflicting_positive_seats': conflicting_positive_seats,
    }


def evaluate_labels(
    edition: str,
    labels: list[dict],
    *,
    min_conf: float = 0.70,
    model_path: Path | None = None,
    proposal_mode: str | None = None,
    azhar_prior: bool | None = None,
) -> dict:
    labels, collapse_stats = collapse_word_expectations(labels)
    proposal_mode = resolve_proposal_mode(edition, proposal_mode)
    use_azhar_prior = resolve_azhar_seat_prior(edition, azhar_prior)
    by_page: dict[int, list[dict]] = {}
    for row in labels:
        by_page.setdefault(int(row['page']), []).append(row)

    details: list[dict] = []
    totals = {
        **collapse_stats,
        'pages': len(by_page),
        'anchored_seats': len(labels),
        'positive_seats': sum(row.get('symbol') != 'none' for row in labels),
        'negative_seats': sum(row.get('symbol') == 'none' for row in labels),
        'correct': 0,
        'wrong_symbol': 0,
        'missing': 0,
        'false_positive_on_negative': 0,
        'correct_negative': 0,
    }
    for page, page_labels in sorted(by_page.items()):
        detect_kwargs = {
            'min_conf': min_conf,
            'proposal_mode': proposal_mode,
            'azhar_prior': use_azhar_prior,
        }
        if model_path is not None:
            detect_kwargs['model_path'] = model_path
        result = detect_page(edition, page, **detect_kwargs)
        detected = {
            str(mark.get('word_key') or ''): mark
            for mark in result.get('marks') or []
            if mark.get('word_key')
        }
        for expected in page_labels:
            actual = detected.get(expected['word_key'])
            symbol = expected.get('symbol')
            if symbol == 'none':
                kind = 'correct_negative' if actual is None else 'false_positive_on_negative'
            elif actual is None:
                kind = 'missing'
            elif actual.get('symbol') == symbol:
                kind = 'correct'
            else:
                kind = 'wrong_symbol'
            totals[kind] += 1
            details.append({
                'page': page,
                'word_key': expected['word_key'],
                'word_text': expected.get('word_text') or '',
                'expected': symbol,
                'actual': actual.get('symbol') if actual else None,
                'confidence': actual.get('confidence') if actual else None,
                'kind': kind,
            })

    positive = max(1, totals['positive_seats'])
    negative = max(1, totals['negative_seats'])
    totals['positive_exact_accuracy'] = round(totals['correct'] / positive, 4)
    totals['negative_accuracy'] = round(totals['correct_negative'] / negative, 4)
    return {
        'edition': edition,
        'min_conf': min_conf,
        'model': str(model_path) if model_path is not None else 'production',
        'proposal_mode': proposal_mode,
        'azhar_prior': use_azhar_prior,
        'summary': totals,
        'details': details,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--edition', required=True, choices=list(EDITIONS))
    parser.add_argument('--min-conf', type=float, default=0.70)
    parser.add_argument('--out', type=Path, default=None)
    parser.add_argument('--model', type=Path, default=None)
    parser.add_argument(
        '--proposal-mode',
        choices=sorted(PROPOSAL_MODES),
        default=None,
        help='override the edition default (hybrid for البحرين, narrow otherwise)',
    )
    parser.add_argument(
        '--azhar-prior',
        action=argparse.BooleanOptionalAction,
        default=None,
        help='override edition Azhar occupancy prior (on for البحرين)',
    )
    parser.add_argument(
        '--pages', default=None,
        help='optional comma/range page subset, for example 198,202,221,255',
    )
    args = parser.parse_args(argv)
    spec = EDITIONS[args.edition]
    labels = load_anchored_labels(spec.id)
    if args.pages:
        wanted = set(_parse_pages(args.pages))
        labels = [row for row in labels if row['page'] in wanted]
    if not labels:
        raise SystemExit(
            f'no anchored labels for {args.edition}; label target pages in /cv-waqf first'
        )
    report = evaluate_labels(
        args.edition, labels, min_conf=args.min_conf, model_path=args.model,
        proposal_mode=args.proposal_mode,
        azhar_prior=args.azhar_prior,
    )
    out = args.out or ARTIFACTS_ROOT / f'evaluate-hand-{spec.id}.json'
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report['summary'], ensure_ascii=False, indent=2))
    print(f'wrote {out}')
    return 0


def _parse_pages(spec: str) -> list[int]:
    pages: list[int] = []
    for part in spec.split(','):
        part = part.strip()
        if not part:
            continue
        if '-' in part:
            start, end = part.split('-', 1)
            pages.extend(range(int(start), int(end) + 1))
        else:
            pages.append(int(part))
    return pages


if __name__ == '__main__':
    raise SystemExit(main())
