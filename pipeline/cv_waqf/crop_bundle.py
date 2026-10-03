"""Pack the training crops into one compact, git-trackable file.

The detector-window crops (``crops_candidates/``) are ~23k tiny PNGs in an
ignored folder, and rebuilding them needs the page scans (gigabytes, also not
in git). That ties training to one machine. A bundle is the same data as a
single compressed ``.npz`` (uint8 pixels, labels, page groups) plus the
validation page groups, so any checkout can train on exactly these crops with
no scans, no hand labels and no local state:

    python -m pipeline.cv_waqf crop-bundle build --out data/cv/bundles/x.npz \\
        --crops data/cv/crops_candidates/bahrain --crops .../qatar
    python -m pipeline.cv_waqf train-cnn --bundle data/cv/bundles/x.npz --only qatar ...

Loading is bit-identical to ``train_classifier.load_grouped_dataset`` on the
source folders (checked in the tests), so a model trained from the bundle is
the model trained from the folders.

``load`` needs only numpy; ``build`` needs OpenCV (it reads the PNGs).
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import numpy as np

from pipeline.cv_waqf import CLASSES
from pipeline.cv_waqf.config import CROP_SIZE

FORMAT = 1
_GROUP = re.compile(r'^([a-z0-9_]+):p(\d{4})$')


def build(
    crop_roots: list[Path],
    out_path: Path,
    *,
    validation_groups: list[str],
    note: str = '',
) -> dict:
    """Write the bundle for ``crop_roots``; returns a summary."""
    from pipeline.cv_waqf.train_classifier import load_grouped_dataset

    x, y, groups = load_grouped_dataset(list(crop_roots))
    bad = [g for g in set(groups.tolist()) if not _GROUP.match(str(g))]
    if bad:
        raise ValueError(
            f'every crop must belong to a source:pNNNN page group; got {bad[:3]}'
        )
    pixels = np.rint((1.0 - x) * 255.0).astype(np.uint8)
    # Exactly invertible: the loader's own arithmetic must give x back.
    if not np.array_equal(1.0 - pixels.astype(np.float32) / 255.0, x):
        raise RuntimeError('crops are not 8-bit; the bundle would not round-trip')
    meta = {
        'format': FORMAT,
        'crop_size': CROP_SIZE,
        'classes': list(CLASSES),
        'validation_groups': list(validation_groups),
        'note': note,
    }
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        out_path,
        pixels=pixels,
        y=y.astype(np.int8),
        groups=np.asarray([str(g) for g in groups], dtype='<U24'),
        meta=np.asarray(json.dumps(meta, ensure_ascii=False)),
    )
    return summarize(out_path)


def _read(path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict]:
    with np.load(path, allow_pickle=False) as bundle:
        meta = json.loads(str(bundle['meta']))
        if meta.get('format') != FORMAT:
            raise ValueError(f'unsupported bundle format {meta.get("format")!r}')
        if meta['classes'] != list(CLASSES):
            raise ValueError(
                'bundle class order differs from CLASSES '
                f'({meta["classes"]} vs {list(CLASSES)}); rebuild the bundle'
            )
        return (
            bundle['pixels'], bundle['y'].astype(np.int64),
            bundle['groups'].astype(object), meta,
        )


def load(
    path: Path, *, only: str | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, list[str]]:
    """``(x, y, groups, validation_groups)``, ``x`` ink-positive float32.

    ``only`` keeps one print (``qatar``, ``bahrain`` ...), which is how a
    leave-one-edition-out run trains on a single print.
    """
    pixels, y, groups, meta = _read(Path(path))
    if only is not None:
        keep = np.asarray([str(g).split(':', 1)[0] == only for g in groups])
        if not keep.any():
            known = sorted({str(g).split(':', 1)[0] for g in groups})
            raise ValueError(f'no crops from {only!r}; bundle has {known}')
        pixels, y, groups = pixels[keep], y[keep], groups[keep]
    x = pixels.astype(np.float32) / 255.0
    x = 1.0 - x
    return x, y, groups, list(meta['validation_groups'])


def summarize(path: Path) -> dict:
    pixels, y, groups, meta = _read(Path(path))
    counts: dict[str, dict[str, int]] = {}
    for label_index, group in zip(y.tolist(), groups.tolist()):
        source = str(group).split(':', 1)[0]
        name = CLASSES[label_index]
        counts.setdefault(source, {})[name] = counts.setdefault(source, {}).get(name, 0) + 1
    return {
        'path': str(path),
        'bytes': Path(path).stat().st_size,
        'crops': int(len(y)),
        'pages': len({str(g) for g in groups.tolist()}),
        'by_source': counts,
        'validation_groups': len(meta['validation_groups']),
        'note': meta.get('note', ''),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='cmd', required=True)
    build_p = sub.add_parser('build', help='pack crop folders into a bundle')
    build_p.add_argument('--crops', type=Path, action='append', required=True)
    build_p.add_argument('--out', type=Path, required=True)
    build_p.add_argument(
        '--validation-groups', type=Path, required=True,
        help='JSON list from `splits --groups-out`',
    )
    build_p.add_argument('--note', default='')
    info_p = sub.add_parser('info', help='describe a bundle')
    info_p.add_argument('bundle', type=Path)
    args = parser.parse_args(argv)
    if args.cmd == 'build':
        groups = json.loads(args.validation_groups.read_text(encoding='utf-8'))
        result = build(args.crops, args.out, validation_groups=groups, note=args.note)
    else:
        result = summarize(args.bundle)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
