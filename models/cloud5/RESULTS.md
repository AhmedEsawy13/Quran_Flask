# Waqf glyph model v6 — cloud training results

Bundle `data/cv/bundles/multiprint_crops_v6.npz` (87,053 crops = v5 + Shamarly), rebuilt with
`python data/cv/bundles/merge_v6.py` on branch `cloud/waqf-v6-training` (commit be428e5). Training used
43,053 crops after `--cap-none 26000` (17,053 positives). Command (per seed, flags unchanged):

    python -m pipeline.cv_waqf train-cnn --bundle data/cv/bundles/multiprint_crops_v6.npz \
        --out models/cloud5/v6_s$SEED.onnx --seed $SEED --cap-none 26000 --augment 2 --epochs 25

| Model | Final gate val_acc | Final symbol val_acc | Wall time | Torch threads |
|---|---|---|---|---|
| v6_s0 | 0.936 | 0.917 | 7965 s | 1 (ran alongside s1) |
| v6_s1 | 0.930 | 0.918 | 8525 s | 1 (ran alongside s0) |
| v6_s2 | 0.932 | 0.915 | 4311 s | 4 (ran after s0/s1) |

Environment: CPU only, 4 cores, 16 GB RAM, Python 3.13.16, torch 2.14.1+cu130, OpenCV 5.

Notes
- Only validation accuracy on the bundle's own validation page groups is reported; whether v6 beats the
  shipped model is tested on the Mac against the held-out scans.
- At most two seeds trained at once. No out-of-memory.
- Unusual:
  - A first attempt at s0/s1 (started 2026-10-14 ~20:50 UTC) was killed at gate epoch 18-19 when the session's
    worker process was restarted; nothing had been written. All seeds were rerun from scratch.
  - For the rerun, train_cnn.py carried a local, opt-in per-epoch checkpoint/resume (WAQF_CKPT_DIR). No run
    actually needed to resume. With checkpointing the weights are bit-identical to a plain run (tested on
    synthetic data: uninterrupted, killed-and-resumed and plain runs all match). The patch is in
    tools/kaggle_waqf_v6/train_cnn_gpu_ckpt.patch.
  - s2 was accidentally started twice (a leftover launcher from the killed attempt); both copies ran the same
    seed and settings and logged the same epoch-1 accuracy (0.913). The duplicate was killed about 11 minutes in,
    before gate epoch 2; the surviving run continued alone. The overlap only slowed it (8 threads on 4 cores),
    so s2's wall time is a little inflated.
- Thread count is not a flag but may shift torch's numerics slightly between s0/s1 (1 thread) and s2 (4).
- Cloud torch builds are not byte-identical to the Mac's. A GPU (Kaggle) run of the same recipe would not be
  byte-identical to these CPU runs either.
- Pushed to cloud/waqf-v4-training-zm81hi (this session's branch). models/waqf_glyph_* untouched.
