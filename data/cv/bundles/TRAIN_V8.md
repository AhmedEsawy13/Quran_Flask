# v8 training (cloud)

Bundle: `data/cv/bundles/multiprint_crops_v8.npz` (65,313 crops, 79 MB; built by `build_v8.py`, which needs
the Mac-local page images, so it is here for the record only).

v8 = v7 with its Shamarly part rebuilt: v7's Shamarly crops were cut with wrong word positions (a whole line
off under surah banners, letter-count word splits); they are replaced by crops re-sampled with the corrected
positions (same 420 training pages), plus 113 newly reviewed hard negatives x4 (Shamarly 78, others 35).
`none` is already thinned inside the bundle, so **train with `--cap-none 0`**.

Never in the bundle: every v4/v5/v6 held-out page, and Madinah 1441 (the unseen test print).

**Run ONE seed at a time** (two at once ran out of memory on the 16 GB box with v7). Per seed (0, 1, 2):

    python -m pipeline.cv_waqf train-cnn --bundle data/cv/bundles/multiprint_crops_v8.npz \
        --out models/cloud7/v8_s$SEED.onnx --seed $SEED --cap-none 0 --augment 2 --epochs 25

Then write `models/cloud7/RESULTS.md` (val accuracies, wall time, anything unusual), commit models/cloud7 and push.
Do not touch models/waqf_glyph_*.
