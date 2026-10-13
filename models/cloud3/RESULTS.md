# Waqf glyph model v4 — cloud training results

Bundle `data/cv/bundles/multiprint_crops_v4.npz` (55,785 crops, 9,785 positives).
Command (per seed, flags unchanged):

    python -m pipeline.cv_waqf train-cnn --bundle data/cv/bundles/multiprint_crops_v4.npz \
        --out models/cloud3/v4_s$s.onnx --seed $s --cap-none 26000 --augment 2 --epochs 25

| Model | Final gate val_acc | Final symbol val_acc | Wall time |
|---|---|---|---|
| v4_s0 | 0.946 | 0.919 | 8962 s |
| v4_s1 | 0.948 | 0.918 | 9323 s |
| v4_s2 | 0.947 | 0.914 | 5989 s |

Environment: CPU only, 4 cores, 16 GB RAM, Python 3.13.16, torch 2.14.1+cu130, OpenCV 5.

Notes
- val_acc is on the bundle's own validation page groups (training-split holdout), not on the
  held-out scan pages. These numbers do NOT show whether v4 beats the shipped model; that needs
  scoring on the Mac against the Bahrain/Kuwait/Qatar held-out pages.
- s0 and s1 ran in parallel with 1 thread each (OMP_NUM_THREADS=1). s2's first attempt was
  killed by the out-of-memory killer when three runs shared the 16 GB; it was rerun with the same
  flags and 2 threads, mostly alone, hence the shorter wall time. Thread count does not change
  the flags, but torch thread scheduling may make it differ slightly from a 1-thread run.
- Cloud torch builds are not byte-identical to the Mac's.
- Pushed to cloud/waqf-v4-training-zm81hi (the branch assigned to this session).
