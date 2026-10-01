"""Average several trained MLP glyph models into one ONNX, exactly.

Training noise between seeds is as large as the differences between model
designs (±2 points on 300 seats), so a single run is a poor thing to ship.
Averaging K models' logits is the same function as one MLP with the hidden
units concatenated and the output weights stacked and divided by K:

    mean_k( relu(x W1_k + b1_k) W2_k + b2_k )
        = relu(x [W1_1 | ... | W1_K] + [b1_1 ... b1_K]) · [W2_1/K ; ... ; W2_K/K]
          + mean_k(b2_k)

so the result is an ordinary Flatten→Gemm→Relu→Gemm graph that OpenCV DNN and
``GlyphClassifier`` load unchanged. A two-stage model is merged stage by
stage (gate with gates, symbol with symbols).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import onnx
from onnx import numpy_helper

from pipeline.cv_waqf.train_classifier import export_mlp_onnx


def read_mlp(path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """``(W1, B1, W2, B2)`` of a Flatten→Gemm→Relu→Gemm model."""
    graph = onnx.load(str(path)).graph
    weights = {init.name: numpy_helper.to_array(init) for init in graph.initializer}
    ops = [node.op_type for node in graph.node]
    if ops != ['Flatten', 'Gemm', 'Relu', 'Gemm']:
        raise ValueError(f'{path.name}: not a plain MLP (ops {ops})')
    return weights['W1'], weights['B1'], weights['W2'], weights['B2']


def merge_mlps(
    models: list[tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]],
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """One MLP whose logits equal the mean of ``models``' logits."""
    if not models:
        raise ValueError('nothing to merge')
    k = len(models)
    n_in, n_out = models[0][0].shape[0], models[0][2].shape[1]
    for w1, _b1, w2, _b2 in models:
        if w1.shape[0] != n_in or w2.shape[1] != n_out:
            raise ValueError('models disagree on input size or class count')
    return (
        np.concatenate([m[0] for m in models], axis=1),
        np.concatenate([m[1] for m in models]),
        np.concatenate([m[2] for m in models], axis=0) / k,
        np.mean([m[3] for m in models], axis=0),
    )


def _sidecar(path: Path) -> dict:
    return json.loads(path.with_suffix('.json').read_text(encoding='utf-8'))


def ensemble(paths: list[Path], out_path: Path) -> Path:
    """Merge two-stage MLP models ``paths`` into ``out_path`` (+ ``_gate``)."""
    metas = [_sidecar(path) for path in paths]
    first = metas[0]
    for meta in metas[1:]:
        if meta.get('classes') != first.get('classes'):
            raise ValueError('models were trained with different class lists')
    gate_paths = [
        path.parent / str(meta['gate_model']) for path, meta in zip(paths, metas)
    ]
    out_path = Path(out_path)
    gate_out = out_path.with_name(f'{out_path.stem}_gate{out_path.suffix}')
    gate_meta = _sidecar(gate_paths[0])
    export_mlp_onnx(
        *merge_mlps([read_mlp(path) for path in gate_paths]), gate_out,
        classes=gate_meta['classes'],
        metadata={
            key: value for key, value in gate_meta.items()
            if key not in {'classes', 'crop_size', 'hidden', 'input', 'output',
                           'input_layout', 'ink_as_positive'}
        } | {'ensemble': len(paths)},
    )
    metadata = {
        key: value for key, value in first.items()
        if key not in {'classes', 'crop_size', 'hidden', 'input', 'output',
                       'input_layout', 'ink_as_positive'}
    }
    metadata.update({'gate_model': gate_out.name, 'ensemble': len(paths)})
    export_mlp_onnx(
        *merge_mlps([read_mlp(path) for path in paths]), out_path,
        classes=first['classes'], metadata=metadata,
    )
    return out_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', type=Path, action='append', required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args(argv)
    out = ensemble(args.model, args.out)
    print(f'wrote {out} (+ gate) from {len(args.model)} models')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
