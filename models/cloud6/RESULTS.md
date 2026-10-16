# Waqf glyph model v7 — cloud training results

Bundle `data/cv/bundles/multiprint_crops_v7.npz` (59,725 crops, 72 MB) from branch `cloud/waqf-v7-training`
(commit 0a6ea73): v6 + 203 reviewed hard negatives x4 + قلى x2, ordinary none thinned to 40,000 in the bundle.
Command (per seed, flags as in data/cv/bundles/TRAIN_V7.md):

    python -m pipeline.cv_waqf train-cnn --bundle data/cv/bundles/multiprint_crops_v7.npz \
        --out models/cloud6/v7_s$SEED.onnx --seed $SEED --cap-none 0 --augment 2 --epochs 25

| Model | Final gate val_acc | Final symbol val_acc | Wall time | Torch threads |
|---|---|---|---|---|
| v7_s0 | 0.941 | 0.919 | 4249 s | 4 (alone) |
| v7_s1 | 0.946 | 0.911 | 4002 s | 4 (alone) |
| v7_s2 | 0.946 | 0.915 | 3678 s | 4 (alone) |

Gate: 59,725 crops (52,690 train / 7,035 val, 105,380 augmented). Symbol: 18,909 marks.
Environment: CPU only, 4 cores, 16 GB RAM, Python 3.13.16, torch 2.14.1+cu130, OpenCV 5.

Notes
- Only validation accuracy on the bundle's own validation page groups is reported; the real test (held-out
  pages, Madinah 1441 unseen print) is on the Mac. Val sets differ between v4/v5/v6/v7, so these numbers do
  not rank the rounds against each other.
- Unusual:
  - **Out of memory with two at once.** With `--cap-none 0` each run holds all 59,725 crops and peaks near
    8 GB (end-of-epoch validation). The first attempt ran s0 and s1 together: s0 was killed by the OOM killer
    after 312 s (before finishing gate epoch 1); s1 had done 1 gate epoch (val_acc 0.938). Both were stopped
    and all seeds rerun from scratch **one at a time** with 4 threads each, so all three ran under identical
    conditions. On a 16 GB box, v7 must run one seed at a time.
  - All three seeds have the identical train/val split (52,690 / 7,035). Expected: with `--cap-none 0` nothing
    is subsampled by seed and the bundle fixes the validation pages. Seeds still differ in initialisation,
    augmentation, batch order and dropout.
  - train_cnn.py carried the local opt-in per-epoch checkpoint (WAQF_CKPT_DIR, see
    tools/kaggle_waqf_v6/train_cnn_gpu_ckpt.patch); bit-identical to a plain run, and no run needed to resume.
- v4/v5/v6 seeds mostly ran with 1 thread; v7 used 4. Thread count is not a flag but can shift torch's
  numerics slightly. Cloud torch builds are not byte-identical to the Mac's.
- Pushed to cloud/waqf-v4-training-zm81hi (this session's branch). models/waqf_glyph_* untouched.
