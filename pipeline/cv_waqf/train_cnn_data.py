"""OpenCV side of CNN training: load crops, split by page, augment, hand over.

Writes an ``.npz`` that ``train_cnn`` (torch, a separate process) consumes.
``train-cnn`` runs both. See ``train_cnn`` for why they cannot share a
process.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

from pipeline.cv_waqf import CLASSES
from pipeline.cv_waqf.train_classifier import (
    augment_crops,
    load_grouped_dataset,
    split_by_page_group,
)


def prepare(
    crops: list[Path],
    out_npz: Path,
    *,
    holdout: set[str] | None = None,
    cap_none: int = 0,
    augment: int = 2,
    seed: int = 0,
) -> dict:
    x, y, groups = load_grouped_dataset(crops)
    if cap_none > 0:
        none_rows = np.flatnonzero(y == list(CLASSES).index('none'))
        if len(none_rows) > cap_none:
            rng = np.random.default_rng(seed)
            drop = rng.choice(
                none_rows, size=len(none_rows) - cap_none, replace=False,
            )
            keep = np.setdiff1d(np.arange(len(y)), drop)
            x, y, groups = x[keep], y[keep], groups[keep]
    train_i, val_i = split_by_page_group(groups, seed=seed, holdout=holdout)
    # Copies of training crops only, so validation stays real.
    aug_x = augment_crops(x[train_i], augment, seed=seed)
    aug_src = np.tile(train_i, augment) if augment > 0 else np.empty(0, np.int64)
    out_npz.parent.mkdir(parents=True, exist_ok=True)
    np.savez(
        out_npz, x=x.astype(np.float32), y=y, train_idx=train_i, val_idx=val_i,
        aug_x=aug_x.astype(np.float32), aug_src=aug_src.astype(np.int64),
    )
    return {
        'crops': int(len(y)), 'groups': len(set(groups.tolist())),
        'train': int(len(train_i)), 'val': int(len(val_i)),
        'augmented': int(len(aug_x)),
    }


def main(argv: list[str] | None = None) -> int:
    """``train-cnn``: prepare data here, train in a torch-only subprocess."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--crops', type=Path, action='append', required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--epochs', type=int, default=25)
    parser.add_argument('--seed', type=int, default=0)
    parser.add_argument('--augment', type=int, default=2)
    parser.add_argument('--cap-none', type=int, default=0)
    parser.add_argument('--holdout-groups', type=Path, default=None)
    args = parser.parse_args(argv)
    holdout = (
        set(json.loads(args.holdout_groups.read_text(encoding='utf-8')))
        if args.holdout_groups else None
    )
    with tempfile.TemporaryDirectory() as tmp:
        bundle = Path(tmp) / 'cnn_data.npz'
        info = prepare(
            args.crops, bundle, holdout=holdout, cap_none=args.cap_none,
            augment=args.augment, seed=args.seed,
        )
        print(f'prepared {info}', flush=True)
        return subprocess.run(
            [
                sys.executable, '-m', 'pipeline.cv_waqf.train_cnn',
                '--data', str(bundle), '--out', str(args.out),
                '--epochs', str(args.epochs), '--seed', str(args.seed),
            ],
            check=False,
        ).returncode


if __name__ == '__main__':
    raise SystemExit(main())
