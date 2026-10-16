# v7 training (cloud)

Bundle: `data/cv/bundles/multiprint_crops_v7.npz` (59,725 crops, 72 MB; built by `build_v7.py`, which needs the
Mac-local page images, so it is here for the record only).

v7 = v6 with:
- 203 hard negatives x4: detector windows where v6 reported a mark that is not printed (reviewed cards), labelled none;
- قلى x2 in training groups (v6 read قلى as ج on the Madinah-style prints);
- ordinary none thinned to 40,000 inside the bundle, so **train with `--cap-none 0`** (a cap would throw hard
  negatives away at random).

Never in the bundle: every v4/v5/v6 held-out page, and Madinah 1441 (the unseen test print).

Per seed (0, 1, 2), at most two at a time:

    python -m pipeline.cv_waqf train-cnn --bundle data/cv/bundles/multiprint_crops_v7.npz \
        --out models/cloud6/v7_s$SEED.onnx --seed $SEED --cap-none 0 --augment 2 --epochs 25

Then write `models/cloud6/RESULTS.md` (val accuracies, wall time, anything unusual), commit models/cloud6 and push.
Do not touch models/waqf_glyph_*.
