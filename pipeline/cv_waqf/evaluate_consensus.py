"""Score detections on a print that has no hand labels, against a consensus.

For prints that follow the Madinah layout and stops (قطر, الكويت), a word
where every reference edition prints the same mark is almost certainly
marked, and a word every reference leaves empty is almost certainly empty.
Words the references disagree on are *disputed* — real differences between
prints live there — so they are never scored.

This is a proxy, not ground truth: a genuine print-only stop on a
consensus-empty word counts as a false positive. It is meant for comparing
models on the same unseen pages, not for absolute accuracy claims; the honest
number still comes from ``evaluate-hand`` on the print's own hand labels.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from pipeline.cv_waqf.config import ARTIFACTS_ROOT, EDITIONS, PROPOSAL_MODES
from pipeline.cv_waqf.layout_geo import estimate_layout_words
from pipeline.cv_waqf.pages import ensure_page_image
from pipeline.cv_waqf.preprocess import load_bgr, preprocess_page
from pipeline.cv_waqf.run_page import detect_page
from pipeline.cv_waqf.sample_crops import (
    MADINAH_FAMILY_CONSENSUS,
    consensus_marks,
)


def evaluate_consensus(
    edition: str,
    pages: list[int],
    *,
    consensus: tuple[str, ...] = MADINAH_FAMILY_CONSENSUS,
    min_conf: float = 0.55,
    model_path: Path | None = None,
    proposal_mode: str | None = None,
    azhar_prior: bool | None = None,
) -> dict:
    spec = EDITIONS[edition]
    totals = {
        'pages': 0, 'positive_seats': 0, 'correct': 0, 'wrong_symbol': 0,
        'missing': 0, 'negative_words': 0, 'false_positive': 0,
        'disputed_detections': 0, 'detections': 0,
    }
    details: list[dict] = []
    for page in pages:
        detect_kwargs = {
            'min_conf': min_conf,
            'proposal_mode': proposal_mode,
            'azhar_prior': azhar_prior,
        }
        if model_path is not None:
            detect_kwargs['model_path'] = model_path
        result = detect_page(edition, page, **detect_kwargs)
        words = estimate_layout_words(
            spec, page, preprocess_page(load_bgr(ensure_page_image(spec, page)), spec, page=page),
        )
        content = {w.word_id: w for w in words if w.is_content_word and w.word_key}
        ayah_keys = sorted({(w.surah, w.ayah) for w in content.values()})
        agreed, marked_any = consensus_marks(
            consensus, ayah_keys, spec.script_db,
        )
        positives = {
            wid: sym for (_s, _a, wid), sym in agreed.items() if wid in content
        }
        disputed = {
            wid for (_s, _a, wid) in marked_any
            if wid in content and wid not in positives
        }
        detected = {int(m['word_id']): m for m in result.get('marks') or []}

        totals['pages'] += 1
        totals['detections'] += len(detected)
        for wid, sym in positives.items():
            totals['positive_seats'] += 1
            mark = detected.get(wid)
            if mark is None:
                totals['missing'] += 1
                details.append({'page': page, 'word_id': wid, 'kind': 'missing', 'db': sym})
            elif mark['symbol'] == sym:
                totals['correct'] += 1
            else:
                totals['wrong_symbol'] += 1
                details.append({
                    'page': page, 'word_id': wid, 'kind': 'wrong',
                    'db': sym, 'cv': mark['symbol'],
                    'confidence': mark['confidence'],
                })
        negatives = set(content) - set(positives) - disputed
        totals['negative_words'] += len(negatives)
        for wid, mark in detected.items():
            if wid in negatives:
                totals['false_positive'] += 1
                details.append({
                    'page': page, 'word_id': wid, 'kind': 'false_positive',
                    'cv': mark['symbol'], 'confidence': mark['confidence'],
                })
            elif wid in disputed:
                totals['disputed_detections'] += 1

    pos = max(1, totals['positive_seats'])
    neg = max(1, totals['negative_words'])
    totals['positive_exact_accuracy'] = round(totals['correct'] / pos, 4)
    totals['recall_any_symbol'] = round(
        (totals['correct'] + totals['wrong_symbol']) / pos, 4,
    )
    totals['false_positive_rate'] = round(totals['false_positive'] / neg, 4)
    denominator = max(1, totals['correct'] + totals['wrong_symbol'] + totals['false_positive'])
    totals['precision'] = round(totals['correct'] / denominator, 4)
    return {
        'edition': edition,
        'consensus': list(consensus),
        'min_conf': min_conf,
        'model': str(model_path) if model_path else 'edition default',
        'summary': totals,
        'details': details,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--edition', required=True, choices=list(EDITIONS))
    parser.add_argument('--pages', required=True, help='e.g. 12,40-45')
    parser.add_argument('--min-conf', type=float, default=0.55)
    parser.add_argument('--model', type=Path, default=None)
    parser.add_argument('--proposal-mode', choices=sorted(PROPOSAL_MODES), default=None)
    parser.add_argument(
        '--azhar-prior', action=argparse.BooleanOptionalAction, default=None,
    )
    parser.add_argument('--out', type=Path, default=None)
    args = parser.parse_args(argv)
    from pipeline.cv_waqf.evaluate_hand import _parse_pages
    report = evaluate_consensus(
        args.edition, _parse_pages(args.pages), min_conf=args.min_conf,
        model_path=args.model, proposal_mode=args.proposal_mode,
        azhar_prior=args.azhar_prior,
    )
    out = args.out or ARTIFACTS_ROOT / f'evaluate-consensus-{EDITIONS[args.edition].id}.json'
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report['summary'], ensure_ascii=False, indent=2))
    print(f'wrote {out}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
