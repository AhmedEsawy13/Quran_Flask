"""Pass/fail gate for a glyph model, judged on the fixed held-out pages.

    python -m pipeline.cv_waqf gate                       # the shipped model
    python -m pipeline.cv_waqf gate --model s0.onnx --model s1.onnx --model s2.onnx

Why it takes several models: one training run swings ±2.5 points from seed
alone, as much as the differences between designs, so a single run cannot
show a regression or an improvement. Several models passed together are one
*candidate* and are judged on their **mean**. Each metric is the mean over
the models given.

The floors sit below what the shipped CNN actually scores (three seeds:
Qatar 95.7-97.0% exact, 3-4 wrong, precision 97.7-98.3%; Bahrain 92.0-93.6%)
by about two to three standard errors of a binomial on that many seats
(~300 Qatar, ~125 Bahrain), so seed noise alone does not trip the gate but a
real loss does. Tighten them only with more seeds and more labelled seats.

It needs the cached page images and (for Bahrain) the hand labels, which are
local data, so it runs on a developer machine, not in CI. The threshold logic
is pure and unit-tested.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from pipeline.cv_waqf.compare_models import (
    _bahrain_labelled_pages,
    format_row,
    score_model,
)
from pipeline.cv_waqf.splits import multiprint_plan

#: ``metric -> (direction, limit)``; ``min`` = at least, ``max`` = at most.
FLOORS: dict[str, dict[str, tuple[str, float]]] = {
    'qatar': {
        'positive_exact_accuracy': ('min', 0.930),
        'wrong_symbol': ('max', 8.0),
        'precision': ('min', 0.960),
    },
    'bahrain': {
        'positive_exact_accuracy': ('min', 0.890),
    },
}


def mean_metrics(results: list[dict]) -> dict[str, dict[str, float]]:
    """Per-print mean of every numeric metric over ``results``."""
    if not results:
        raise ValueError('no results to average')
    means: dict[str, dict[str, float]] = {}
    for print_key in ('qatar', 'bahrain'):
        keys = results[0][print_key].keys()
        means[print_key] = {
            key: sum(float(r[print_key][key]) for r in results) / len(results)
            for key in keys
        }
    return means


def violations(
    means: dict[str, dict[str, float]],
    floors: dict[str, dict[str, tuple[str, float]]] = FLOORS,
) -> list[str]:
    """Human-readable failures; empty means the candidate passes."""
    failures = []
    for print_key, metrics in floors.items():
        for metric, (direction, limit) in metrics.items():
            value = means[print_key][metric]
            bad = value < limit if direction == 'min' else value > limit
            if bad:
                word = 'below' if direction == 'min' else 'above'
                failures.append(
                    f'{print_key} {metric} = {value:.3f} is {word} the '
                    f'{"floor" if direction == "min" else "ceiling"} {limit:g}'
                )
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--model', type=Path, action='append', default=None,
        help='ONNX to score; repeat to pass several seeds of one candidate. '
             'Default: the shipped multiprint model.',
    )
    parser.add_argument('--min-conf', type=float, default=0.55)
    parser.add_argument('--out', type=Path, default=None)
    args = parser.parse_args(argv)

    from pipeline.cv_waqf.config import SHARED_MULTIPRINT_MODEL_PATH

    models = args.model or [SHARED_MULTIPRINT_MODEL_PATH]
    plan = multiprint_plan(_bahrain_labelled_pages())
    results = []
    for model in models:
        result = score_model(model, min_conf=args.min_conf, plan=plan)
        results.append(result)
        print(format_row(result), flush=True)
    means = mean_metrics(results)
    failures = violations(means)
    print(
        f'\nmean of {len(results)} model(s): '
        f'Qatar exact {means["qatar"]["positive_exact_accuracy"]:.3f} '
        f'wrong {means["qatar"]["wrong_symbol"]:.1f} '
        f'precision {means["qatar"]["precision"]:.3f} | '
        f'Bahrain exact {means["bahrain"]["positive_exact_accuracy"]:.3f}'
    )
    if len(results) < 3:
        print(
            'note: fewer than 3 models; one run swings ±2.5 points, so a pass '
            'or fail here is weak evidence.'
        )
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(
            json.dumps({'results': results, 'means': means,
                        'violations': failures}, ensure_ascii=False, indent=2),
            encoding='utf-8',
        )
    if failures:
        print('GATE FAILED:')
        for line in failures:
            print(f'  - {line}')
        return 1
    print('GATE PASSED')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
