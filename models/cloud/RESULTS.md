# Kuwait CNN training (cloud, CPU)

Bundle: data/cv/bundles/multiprint_crops_v2.npz. Flags: `--cap-none 8000 --augment 2 --epochs 25`, seeds 0/1/2.
Environment: Linux, 4 cores, Python 3.11.15, torch 2.14.1+cu130, OpenCV 5.0.0.
All 6 runs ran concurrently (OMP_NUM_THREADS=1) on 4 cores, so wall times are inflated by contention.
`models/waqf_glyph_multiprint*` untouched.

| model | seed | gate val_acc (n) | symbol val_acc (n) | wall |
|---|---|---|---|---|
| kuwait (all prints in v2) | 0 | 0.938 (11108) | 0.911 (3108) | 3021 s |
| kuwait | 1 | 0.949 (11108) | 0.908 (3108) | 3021 s |
| kuwait | 2 | 0.940 (11108) | 0.913 (3108) | 2997 s |
| kuwait_only (`--only kuwait`) | 0 | 0.963 (9390) | 0.879 (1390) | 2535 s |
| kuwait_only | 1 | 0.965 (9390) | 0.865 (1390) | 2481 s |
| kuwait_only | 2 | 0.955 (9390) | 0.870 (1390) | 2557 s |

Means (3 seeds): kuwait gate 0.942 / symbol 0.911; kuwait_only gate 0.961 / symbol 0.871.

Caveat: the two recipes validate on different page sets and sizes, so these val_acc numbers
are not a like-for-like comparison. They are in-distribution validation only; they say
nothing about whole-page detection accuracy. Score with compare-models / hand labels on the Mac.
