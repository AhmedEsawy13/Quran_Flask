"""Fixed, reproducible page splits for comparing CV models fairly.

Every model is scored on pages it never trained on, and every model sees the
*same* such pages, so differences are the model's, not the split's.

* ``qatar_pages``   – 100 training / 50 held-out pages of Qatar (seed 2026).
* ``bahrain_holdout`` – every 4th hand-labelled Bahrain page.
"""
from __future__ import annotations

import random

FIRST_PAGE, LAST_PAGE = 3, 604  # skip the Fatiha/opening spreads
QATAR_SEED = 2026
QATAR_TRAIN, QATAR_HOLDOUT = 100, 50


def qatar_pages() -> tuple[list[int], list[int]]:
    """``(train, holdout)``, disjoint, sorted."""
    pool = list(range(FIRST_PAGE, LAST_PAGE + 1))
    random.Random(QATAR_SEED).shuffle(pool)
    train = sorted(pool[:QATAR_TRAIN])
    holdout = sorted(pool[QATAR_TRAIN:QATAR_TRAIN + QATAR_HOLDOUT])
    return train, holdout


def bahrain_holdout(labelled_pages: list[int]) -> tuple[list[int], list[int]]:
    """``(train, holdout)`` of hand-labelled Bahrain pages: every 4th held out."""
    pages = sorted(set(labelled_pages))
    holdout = [page for index, page in enumerate(pages) if index % 4 == 0]
    held = set(holdout)
    return [page for page in pages if page not in held], holdout


def group_ids(source: str, pages: list[int]) -> list[str]:
    """``source:pNNNN`` ids as ``train --holdout-groups`` expects."""
    return [f'{source}:p{page:04d}' for page in pages]


def multiprint_plan(bahrain_labelled_pages: list[int]) -> dict:
    """Everything the Qatar + Bahrain multi-print recipe needs, in one place.

    ``validation_groups`` are training pages set aside for picking the best
    epoch (every 7th Qatar / 10th Bahrain training page); ``*_eval`` pages
    are never trained on and are what the model is finally scored on.
    """
    q_train, q_eval = qatar_pages()
    b_train, b_eval = bahrain_holdout(bahrain_labelled_pages)
    return {
        'qatar_train': q_train,
        'qatar_eval': q_eval,
        'bahrain_train': b_train,
        'bahrain_eval': b_eval,
        'validation_groups': (
            group_ids('qatar', q_train[::7]) + group_ids('bahrain', b_train[::10])
        ),
    }


def main(argv: list[str] | None = None) -> int:
    import argparse
    import json
    from pathlib import Path

    from pipeline.cv_waqf.evaluate_hand import HAND_ROOT

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--groups-out', type=Path, default=None,
        help='write validation_groups here, for train --holdout-groups',
    )
    args = parser.parse_args(argv)
    labels = HAND_ROOT / 'bahrain' / 'labels.jsonl'
    pages = sorted({
        int(json.loads(line)['page'])
        for line in labels.read_text(encoding='utf-8').splitlines() if line
    }) if labels.is_file() else []
    plan = multiprint_plan(pages)
    if args.groups_out:
        args.groups_out.parent.mkdir(parents=True, exist_ok=True)
        args.groups_out.write_text(
            json.dumps(plan['validation_groups']), encoding='utf-8',
        )
    print(json.dumps({k: v for k, v in plan.items() if k != 'validation_groups'}))
    return 0
