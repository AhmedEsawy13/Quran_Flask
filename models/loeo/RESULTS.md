# Leave-one-edition-out CNN training (cloud, CPU)

Environment: Linux, 4 CPU cores, Python 3.11.15, torch 2.14.1+cu130, OpenCV 5.0.0, numpy 2.4.6.
Bundle: data/cv/bundles/multiprint_crops_v1.npz. Flags: `--cap-none 8000 --augment 2 --epochs 25`.
The four LOEO runs ran in parallel with OMP_NUM_THREADS=1 / MKL_NUM_THREADS=1.

| model | seed | gate val_acc (n) | symbol val_acc (n) | wall time |
|---|---|---|---|---|
| bahrain_only_s0 | 0 | 0.974 (9113) | 0.917 (1113) | 1430 s |
| bahrain_only_s1 | 1 | 0.973 (9113) | 0.944 (1113) | 1433 s |
| qatar_only_s0 | 0 | 0.979 (8480) | 0.920 (605) | 1333 s |
| qatar_only_s1 | 1 | 0.978 (8480) | 0.920 (605) | 1193 s |
| both (no --only), determinism check | 0 | 0.958 (9718) | 0.923 (1718) | 403 s (4 threads, run alone) |

These val_acc figures are on each model's own validation pages (in-distribution),
not cross-edition. Cross-edition scoring is done on the Mac with `compare-models`.

Determinism check: `cmp /tmp/both_s0.onnx models/waqf_glyph_multiprint.onnx` -> **NOT identical**
(first difference at byte 891). Expected across Linux/CUDA-build torch vs the Mac build.
The shipped models/waqf_glyph_multiprint* files were not touched.
Pushed to branch cloud/loeo-training-jwizie (the session's designated branch).
