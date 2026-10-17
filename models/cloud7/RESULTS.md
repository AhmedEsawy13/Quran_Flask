# Waqf glyph model v8 — cloud training results

Bundle `data/cv/bundles/multiprint_crops_v8.npz` (65,313 crops, 79 MB) from branch `cloud/waqf-v8-training`
(commit c6cc321): v7 with the Shamarly part re-cut from corrected word positions (same 420 training pages)
plus 113 newly reviewed hard negatives x4. Command (per seed, flags as in data/cv/bundles/TRAIN_V8.md):

    python -m pipeline.cv_waqf train-cnn --bundle data/cv/bundles/multiprint_crops_v8.npz \
        --out models/cloud7/v8_s$SEED.onnx --seed $SEED --cap-none 0 --augment 2 --epochs 25

| Model | Final gate val_acc | Final symbol val_acc | Wall time | Torch threads |
|---|---|---|---|---|
| v8_s0 | 0.954 | 0.924 | 4814 s | 4 (alone) |
| v8_s1 | 0.956 | 0.930 | 4716 s | 4 (alone) |
| v8_s2 | 0.955 | 0.930 | 4451 s | 4 (alone) |

Gate: 65,313 crops (57,819 train / 7,494 val, 115,638 augmented). Symbol: 19,152 marks.
Environment: CPU only, 4 cores, 16 GB RAM, Python 3.13.16, torch 2.14.1+cu130, OpenCV 5.

Notes
- Only validation accuracy on the bundle's own validation page groups is reported; the real test (held-out
  pages, Madinah 1441 unseen print) is on the Mac. The validation set changed again (7,494 vs v7's 7,035, and
  re-cut Shamarly crops), so these numbers do not rank v8 against v7 or earlier rounds.
- Seeds ran one at a time, as TRAIN_V8.md asks; no out-of-memory (peak about 7-8 GB with one run).
- Unusual:
  - The first launch of s0 wrote to the wrong folder (models/cloud6/, a typo in my run script). It was stopped
    about 1 minute in, before any model file was written, and restarted from scratch into models/cloud7/.
    No files outside models/cloud7/ were created or changed.
  - All three seeds have the identical train/val split (expected with `--cap-none 0`, as in v7).
  - train_cnn.py carried the local opt-in per-epoch checkpoint (WAQF_CKPT_DIR, see
    tools/kaggle_waqf_v6/train_cnn_gpu_ckpt.patch); bit-identical to a plain run, and no run needed to resume.
- Cloud torch builds are not byte-identical to the Mac's.
- Pushed to cloud/waqf-v4-training-zm81hi (this session's branch). models/waqf_glyph_* untouched.
