"""Score glyph models on the fixed held-out pages of both prints.

Every model is evaluated on exactly the pages ``splits.multiprint_plan``
holds out (never trained on): Qatar against the Madinah-family consensus and
Bahrain against its hand labels, with each print's own seat prior on. One
table, so a candidate model is judged by what it does on pages it never saw,
on more than one print, and can be compared to the promoted one.

    python -m pipeline.cv_waqf compare-models \\
        --model models/waqf_glyph_multiprint.onnx --model /tmp/cnn.onnx
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from pipeline.cv_waqf.evaluate_consensus import evaluate_consensus
from pipeline.cv_waqf.evaluate_hand import (
    HAND_ROOT,
    evaluate_labels,
    load_anchored_labels,
)
from pipeline.cv_waqf.splits import multiprint_plan


def _bahrain_labelled_pages() -> list[int]:
    labels = HAND_ROOT / 'bahrain' / 'labels.jsonl'
    if not labels.is_file():
        return []
    return sorted({
        int(json.loads(line)['page'])
        for line in labels.read_text(encoding='utf-8').splitlines() if line
    })


def score_model(
    model: Path | None, *, min_conf: float = 0.55, plan: dict | None = None,
) -> dict:
    """Both held-out scores for one model (``None`` = each edition's default)."""
    plan = plan or multiprint_plan(_bahrain_labelled_pages())
    qatar = evaluate_consensus(
        'قطر', plan['qatar_eval'], min_conf=min_conf, model_path=model,
    )['summary']
    held = set(plan['bahrain_eval'])
    labels = [
        row for row in load_anchored_labels('bahrain') if row['page'] in held
    ]
    bahrain = evaluate_labels(
        'البحرين', labels, min_conf=min_conf, model_path=model,
    )['summary']
    return {
        'model': str(model) if model else 'edition defaults',
        'min_conf': min_conf,
        'qatar': {
            key: qatar[key] for key in (
                'positive_seats', 'correct', 'wrong_symbol', 'missing',
                'false_positive', 'positive_exact_accuracy', 'precision',
            )
        },
        'bahrain': {
            key: bahrain[key] for key in (
                'positive_seats', 'correct', 'wrong_symbol', 'missing',
                'false_positive_on_negative', 'negative_seats',
                'positive_exact_accuracy',
            )
        },
    }


def format_row(result: dict) -> str:
    q, b = result['qatar'], result['bahrain']
    return (
        f"{Path(result['model']).name:34s} "
        f"QATAR exact {q['positive_exact_accuracy']:.3f} "
        f"wrong {q['wrong_symbol']:3d} miss {q['missing']:3d} "
        f"FP {q['false_positive']:3d} prec {q['precision']:.3f} | "
        f"BAHRAIN exact {b['positive_exact_accuracy']:.3f} "
        f"wrong {b['wrong_symbol']:2d} miss {b['missing']:2d} "
        f"FP {b['false_positive_on_negative']:2d}/{b['negative_seats']}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', type=Path, action='append', default=None,
                        help='ONNX to score; repeat. Omit for edition defaults')
    parser.add_argument('--min-conf', type=float, default=0.55)
    parser.add_argument('--out', type=Path, default=None)
    args = parser.parse_args(argv)
    plan = multiprint_plan(_bahrain_labelled_pages())
    results = []
    for model in args.model or [None]:
        result = score_model(model, min_conf=args.min_conf, plan=plan)
        results.append(result)
        print(format_row(result), flush=True)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(
            json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8',
        )
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
