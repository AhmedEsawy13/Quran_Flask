"""Rebuild data/cv/bundles/multiprint_crops_v6.npz from v5 + the Shamarly part (cloud branch only).

GitHub refuses files over 100 MB and v6 is 108 MB, so the branch carries v5 (89 MB, unchanged) and the
Shamarly crops (18 MB); this joins them before training:

    python data/cv/bundles/merge_v6.py
"""
import json
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent


def read(path):
    with np.load(path, allow_pickle=False) as z:
        return z['pixels'], z['y'], z['groups'], json.loads(str(z['meta']))


p5, y5, g5, m5 = read(HERE / 'multiprint_crops_v5.npz')
ps, ys, gs, ms = read(HERE / 'multiprint_crops_v6_shamarly_part.npz')
meta = dict(m5, validation_groups=list(m5['validation_groups']) + list(ms['validation_groups']), note=ms['note'])
pixels, y, groups = np.concatenate([p5, ps]), np.concatenate([y5, ys]), np.concatenate([g5, gs])
assert len(y) == ms['expected_total'], (len(y), ms['expected_total'])
out = HERE / 'multiprint_crops_v6.npz'
np.savez_compressed(out, pixels=pixels, y=y.astype(np.int8), groups=groups.astype('<U24'),
                    meta=np.asarray(json.dumps(meta, ensure_ascii=False)))
print(f'wrote {out} ({len(y)} crops)')
