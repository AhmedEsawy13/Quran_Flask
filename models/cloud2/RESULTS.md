# Kuwait CNN training, round 2 (cloud, CPU)

Bundle: data/cv/bundles/multiprint_crops_v3.npz (19,279 crops after the none cap, 761 page groups).
Exact command (S = 0, 1, 2; the three ran in parallel on 4 cores, OMP_NUM_THREADS=1 MKL_NUM_THREADS=1):

    python -m pipeline.cv_waqf train-cnn --bundle data/cv/bundles/multiprint_crops_v3.npz \
      --out models/cloud2/kuwait_s$S.onnx --seed $S --cap-none 14000 --augment 2 --epochs 25

Environment: Linux, Python 3.11.15, torch 2.14.1+cu130, OpenCV 5.0.0.
No --only variant trained. models/waqf_glyph_* untouched.

| seed | gate val_acc | symbol val_acc | wall |
|---|---|---|---|
| 0 | 0.939 (n=19279) | 0.892 (n=5279) | 3273 s |
| 1 | 0.935 (n=19279) | 0.893 (n=5279) | 3300 s |
| 2 | 0.935 (n=19279) | 0.899 (n=5279) | 3398 s |
| mean | 0.936 | 0.895 | |

Caveats: the validation page set differs per seed and differs from round 1 (3108 symbol
samples there, 5279 here), so these are not directly comparable to models/cloud
(round 1 symbol mean 0.911). In-distribution validation only; score on real
Kuwait pages with compare-models on the Mac.
