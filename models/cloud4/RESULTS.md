# Waqf glyph model v5 — cloud training results

Bundle `data/cv/bundles/multiprint_crops_v5.npz` (71,808 crops), from branch `cloud/waqf-v5-training`
(commit 1043d1a). Training used 39,808 crops after `--cap-none 26000` (13,808 positives).
Command (per seed, flags unchanged):

    python -m pipeline.cv_waqf train-cnn --bundle data/cv/bundles/multiprint_crops_v5.npz \
        --out models/cloud4/v5_s$SEED.onnx --seed $SEED --cap-none 26000 --augment 2 --epochs 25

| Model | Final gate val_acc | Final symbol val_acc | Wall time | Torch threads |
|---|---|---|---|---|
| v5_s0 | 0.947 | 0.922 | 6942 s | 1 (ran alongside s1) |
| v5_s1 | 0.946 | 0.923 | 7043 s | 1 (ran alongside s0) |
| v5_s2 | 0.941 | 0.918 | 2545 s | 4 (ran alone) |

Environment: CPU only, 4 cores, 16 GB RAM, Python 3.13.16, torch 2.14.1+cu130, OpenCV 5.

Notes
- Only validation accuracy on the bundle's own validation page groups is reported. It does not say
  whether v5 beats the shipped model; that is tested on the Mac against the held-out scans.
- At most two seeds ran at once (no out-of-memory this time).
- Unusual: s2 was first started with 1 thread, aborted about 7 minutes in (at gate epoch 2, killed on
  purpose) and restarted from scratch with 4 threads once s0 and s1 had finished and the cores were
  idle. Same flags and seed; the thread count is not a flag but may change torch's numerics slightly.
  The 2545 s wall time covers the restarted run only.
- Training ran from a local checkout of cloud/waqf-v5-training; only models/cloud4/ is pushed here, to
  cloud/waqf-v4-training-zm81hi (this session's branch). models/waqf_glyph_* untouched.
- Cloud torch builds are not byte-identical to the Mac's.
