# OpenCV 5 waqf mark detection

Offline pipeline that **audits** existing `mushaf_waqf.db` marks against printed
page images and **bootstraps** draft marks for editions that still need them.

Does **not** run inside the public Flask reading path.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt -r requirements/cv.txt
export PYTHONPATH=.
```

## Adding a print

An edition is one `EditionSpec` in `config.py`; nothing else names it.

- Its own models are found by convention: `models/waqf_glyph_<id>.onnx`
  (+ `_gate.onnx`) and `models/waqf_strip_<id>.onnx`. `model_fallback` lets a
  new print borrow another edition's model until it has its own; `run-page`
  reports which one ran in `model_source` (`own`, `transfer:<edition>`,
  `multiprint`, `shared`, `explicit`). See "One model for several prints".
- `measured_geometry=True` reads the text rows and word cuts from each page's
  ink (`geometry.py`) instead of the hand-tuned `text_*` fractions. It needs
  only the layout DB (which words are on which line) and works on any print
  with a frame; `text_*` stay as the fallback when a page gives no evidence.
- **`text_top`/`text_bottom` must be in the slot-box convention, not the ink
  extent** (the slot box sits ~0.56 line higher). Text rows are periodic, so
  a nominal band that is off by half a line lets the fit lock onto the
  *neighbouring* line on some pages: Qatar was set from its ink extent and
  10% of its pages aliased, which cost ~7 points of Qatar accuracy. Do not
  hand-tune them; run
  `python -m pipeline.cv_waqf calibrate-geometry --edition <print>` and paste
  the result (it recovers the true band to 0.0003 of page height from a
  start 0.6 line off, and flags stray pages).
- `image_kind='cache'` editions use whatever width is cached (Qatar: 2000px);
  the 1024px working copy is derived once beside it.

## One model for several prints

A new print does not need its own hand labels to get a usable model. What
transfers between prints is the glyph vocabulary; what does not is rendering,
so the model must be trained on crops cut *the way the detector cuts them*.
Crops sampled any other way (tight boxes, human-drawn boxes) fill the 48×48
input differently and score far worse at detect time.

```bash
# 1. Detector-window crops. Each candidate window the hybrid detector would
#    classify is labelled by which word's stop seat it sits on; the label
#    comes from an agreed mark (Madinah-family consensus for Qatar, the
#    edition's own column for Bahrain). Disputed words are never labelled.
#    Regenerate these whenever geometry changes: a wrong row alignment mislabels seats.
.venv/bin/python -m pipeline.cv_waqf candidate-crops --edition قطر \
  --page-list <pages> --consensus madinah --clear
.venv/bin/python -m pipeline.cv_waqf candidate-crops --edition البحرين \
  --page-list <pages> --consensus self --clear

# 2. Fixed pages so every model is scored on pages it never trained on.
.venv/bin/python -m pipeline.cv_waqf splits --groups-out /tmp/groups.json

# 3. Train the CNN pair (needs torch: pip install -r requirements/cv-train.txt;
#    ~20 min on CPU; byte-for-byte reproducible for a given seed).
.venv/bin/python -m pipeline.cv_waqf train-cnn --seed 0 --augment 2 \
  --cap-none 8000 --holdout-groups /tmp/groups.json \
  --crops data/cv/crops_candidates/bahrain \
  --crops data/cv/crops_candidates/qatar \
  --out models/waqf_glyph_multiprint.onnx

# 4. Score on pages no model trained on (both prints, one table).
.venv/bin/python -m pipeline.cv_waqf compare-models \
  --model models/waqf_glyph_multiprint.onnx
```

`models/waqf_glyph_multiprint.onnx` is what an edition without its own model
resolves to (own → `model_fallback` → multiprint → legacy shared).

**One training run is not evidence.** Five seeds of the *same* MLP recipe on
the *same* data score Qatar 0.887–0.943 and Bahrain 0.864–0.912 (±2–2.5
points on ~300 and ~125 seats), the same size as the differences between
model designs. Judge a change by several seeds. On the held-out pages,
min_conf 0.55, seat prior on:

| model | Qatar (50 pp, consensus) | Bahrain (54 pp, hand labels) |
|---|---|---|
| MLP, 5 single seeds | 88.7–94.3% exact (mean 91.0), 12–24 wrong | 86.4–91.2% (mean 89.4) |
| MLP, 3-seed ensemble | 94.0%, 8 wrong, prec 96.3% | 92.8% |
| **CNN, 3 seeds** | **95.7–97.0% (mean 96.5), 3–4 wrong, prec 97.7–98.3%** | **92.0–93.6% (mean 92.8)** |

The CNN (`train-cnn`) is shipped, seed 0 (the default; 97.0% / 93.6% is the
top of its own 3-seed range, so expect the means above, not those). It is
steadier than the MLP (1.3-point spread vs 5.6) and a single 2.6 MB model
instead of an ensemble, at 0.49 s/page against 0.31. torch and OpenCV cannot
share a process here (two OpenMP runtimes abort), so `train-cnn` runs data
preparation and training as two subprocesses; the exported ONNX is built by
hand from the weights and loads through the unchanged `GlyphClassifier`.

`ensemble-models` is the lightweight alternative when torch is unavailable:
averaging the logits of K MLPs is exactly one wider MLP (hidden units
concatenated, output weights stacked and divided by K), so it needs no
inference change. A CNN cannot be merged that way and is compared per seed.

**Gate.** `python -m pipeline.cv_waqf gate [--model m.onnx ...]` scores a
candidate on the held-out pages and exits non-zero below fixed floors (Qatar
≥ 93.0% exact, ≤ 8 wrong symbols, ≥ 96.0% precision; Bahrain ≥ 89.0% exact),
set a few standard errors under the shipped CNN's three seeds. Pass several
seeds of one candidate: it is judged on their **mean**, because one run is
noise. It needs the page scans and hand labels, so it runs on a developer
machine, not in CI.

**Training without the scans.** `crop-bundle build` packs the detector-window
crops into one compressed `.npz` (uint8 pixels, labels, page groups, and the
validation pages), which loads bit-identically to the folders it came from.
`train-cnn --bundle FILE [--only qatar]` trains from it on any machine, with
no scans, hand labels or local state, which is how a long run can be moved to a
cloud box. Scoring still needs the scans, so models trained elsewhere are
scored locally (cheap; training is the expensive part).

Read this honestly:

- **The Qatar column is a proxy.** Its reference is the marks Qatar,
  Madinah-new and Madinah-old agree on; disputed words are not scored, and a
  genuine Qatar-only stop on a consensus-empty word counts as a false
  positive. It ranks models fairly; it is not an accuracy claim. Score on the
  print's own hand labels (`evaluate-hand`) before trusting output.
- **Earlier leave-one-edition-out numbers are stale.** "Bahrain-only → Qatar
  51%", "Qatar-only → Bahrain 80%" and "3× more pages did not help" were
  measured before the Qatar geometry fix and with single runs, so they carry
  both the aliasing and ±2.5 points of seed noise. Re-run them (several
  seeds) before relying on them.
- Without the seat prior the detector alone fires on ~10% of empty words on
  *both* prints; see "The seat prior" for what it removes and what it costs.

## The seat prior

The detector alone fires on about 10% of empty words on every print, so a
mark is kept only if some *reference* edition prints a stop on that same word
(`EditionSpec.seat_prior_editions`, on with `azhar_seat_prior=True`). The
references are per print and never include the print's own column (config
refuses that, since the prior could then find nothing new).

Bahrain and Qatar use Azhar + المدينة الجديد + المدينة القديم. Whole-book
(602 pages each, min_conf 0.55, reference = the print's own column):

| prior | Bahrain real stops kept / false kept | Qatar real kept / false kept |
|---|---|---|
| Azhar only | 4076 / 71 (loses 12) | 4006 / 63 (loses 78) |
| **Azhar + Madinah** | **4088 / 80 (loses 0)** | **4030 / 70** |
| + الشمرلي | 4088 / 81 | 4032 / 71 |

It admits 52 more seats than Azhar alone (4870 → 4922) and recovers exactly
the edition-specific stops the prior existed to protect. الكويت's column adds
379 seats for almost no gain; and Azhar covers only 91.9% of Kuwait's own
stops, so Kuwait needs its own choice when it is added.

**What is still lost.** Qatar keeps a floor of ~54 real stops that no
reference edition prints. They are *not* queued for review: on 50 Qatar pages
the prior rejected 761 marks and 4 were real (2 of 93 even at confidence
≥ 0.99), so a review queue would be ~99% noise. `bootstrap` therefore records
the drop as `seat_prior_rejected` in the plan, and detect lists the rejected
marks under `azhar_rejected` (the `/cv-waqf` "rejected" toggle) so a human can
still look. Finding those stops needs a better classifier, not a looser prior.

## Commands

```bash
# Cache page JPEGs (Archive / Bahrain PDF)
.venv/bin/python -m pipeline.cv_waqf cache-pages --edition الشمرلي --pages 2-20
.venv/bin/python -m pipeline.cv_waqf cache-pages --edition البحرين --pages 1-20

# Optional: Mesaha DjVu word boxes for training anchors
.venv/bin/python -m pipeline.cv_waqf mesaha-boxes --page-start 2 --page-end 100

# After hand-labeling in /cv-waqf (mode تسمية):
.venv/bin/python -m pipeline.cv_waqf train --crops data/cv/crops_hand/shamarly

# Build crops from every trusted edition whose matching scan is cached.
# Madinah/Azhar deliberately refuse to use a substitute print image.
.venv/bin/python -m pipeline.cv_waqf sample-crops --trusted-all --pages 40

# Shared model: repeat --crops; validation is split by whole printed page.
.venv/bin/python -m pipeline.cv_waqf train \
  --crops data/cv/crops_labeled/shamarly \
  --crops data/cv/crops_hand/bahrain \
  --crops data/cv/crops_hand/mesaha

# Safer two-stage model for noisy target scans: first reject non-marks, then
# classify only accepted waqf glyphs. This writes MODEL_gate.onnx beside MODEL.
.venv/bin/python -m pipeline.cv_waqf train --two-stage \
  --crops data/cv/crops_hand/bahrain \
  --out artifacts/cv-waqf/bahrain_two_stage.onnx

# Or preserve a proven symbol classifier and train only the binary veto gate.
.venv/bin/python -m pipeline.cv_waqf train --two-stage \
  --crops data/cv/crops_hand/bahrain \
  --reuse-symbol-model artifacts/cv-waqf/demo-bahrain/waqf_glyph_demo_current.onnx \
  --out artifacts/cv-waqf/bahrain_gated_current.onnx

# Promoted Bahrain-only model (automatically selected by run-page/UI).
.venv/bin/python -m pipeline.cv_waqf train --two-stage \
  --crops data/cv/crops_hand/bahrain \
  --reuse-symbol-model artifacts/cv-waqf/demo-bahrain/waqf_glyph_demo_current.onnx \
  --out models/waqf_glyph_bahrain.onnx

# Above-word strip detector for البحرين (replaces the 48×48 CC-crop MLP at
# detect time when the ONNX is present). One 32×64 strip per layout word,
# small conv net, exported ONNX for OpenCV 5 DNN. Train-only extra: torch.
# Page-grouped split matches the MLP trainer. Does not replace models/waqf_glyph_bahrain.onnx
# — that gated MLP remains the fallback when the strip ONNX is absent.
# A real Bahrain strip net is not in git; train locally on hand labels +
# cached pages (data/cv/crops_hand/bahrain is gitignored).
.venv/bin/pip install -r requirements/cv-train.txt
.venv/bin/python -m pipeline.cv_waqf train-strip \
  --crops data/cv/crops_hand/bahrain
# writes models/waqf_strip_bahrain.onnx + .json sidecar
# If that file is absent, run-page / evaluate-hand / bootstrap keep gated MLP + hybrid.

# Sync hand crops + ONNX to Supabase (other machines: pull-hand)
# Once: run pipeline/supabase_cv_waqf_hand.sql in Supabase SQL editor
python3 -m pipeline.cv_waqf status-hand --slug shamarly  # read-only check
python3 -m pipeline.cv_waqf push-hand --slug shamarly
python3 -m pipeline.cv_waqf pull-hand --slug shamarly

# Qatar (scans cached at 2000px; resolves to the multi-print model)
.venv/bin/python -m pipeline.cv_waqf run-page --edition قطر --page 198 --overlay

# Detect one page (line-by-line, above word-end band)
.venv/bin/python -m pipeline.cv_waqf run-page --edition الشمرلي --page 5 --overlay

# البحرين uses the above-word strip ONNX when
# models/waqf_strip_bahrain.onnx is present (one strip per layout word).
# If that file is missing, البحرين defaults to hybrid proposals
# (above-word band + line-component candidates) with the gated edition model:
# models/waqf_glyph_bahrain.onnx + waqf_glyph_bahrain_gate.onnx.
# On 44 labeled pages, gated MLP + hybrid:
#   0.55 → 217/238 correct, 31 FP, 15 missing
#   0.85 → 214/238 correct, 14 FP
# Remaining MLP FPs are 0.97+ fatha-sized glyphs — a cutoff cannot reach 0 FP,
# which is why the strip detector classifies the above-word band instead of a
# 48×48 isolated crop. So detect/UI still run at 0.55 (review candidates);
# bootstrap/auto-set writes only confidence >= 0.85. Other editions stay
# narrow + 0.70 auto-set. --proposal-mode, --min-conf, and --model remain
# explicit overrides; --model pointing at the gated MLP disables strip.
# Azhar occupancy prior (البحرين only): after attach, keep a mark only if
# الأزهر has some waqf on that same word_index (ignore the Azhar glyph;
# do not use token_index — 353 DB rows differ). On the
# same 44-page hand set at 0.55 this cuts FP 31 → 6 and correct 217 → 213.
# The 4 dropped "TPs" are not البحرين DB seats. Global recall cost: 12
# البحرين-only DB seats with empty الأزهر. --no-azhar-prior disables it.
.venv/bin/python -m pipeline.cv_waqf run-page --edition البحرين --page 198
.venv/bin/python -m pipeline.cv_waqf run-page \
  --edition البحرين --page 198 --proposal-mode narrow
.venv/bin/python -m pipeline.cv_waqf run-page \
  --edition البحرين --page 198 --no-azhar-prior
.venv/bin/python -m pipeline.cv_waqf run-page \
  --edition الشمرلي --page 5 --proposal-mode hybrid

# Audit DB vs CV (reviewable report, no auto-merge)
.venv/bin/python -m pipeline.cv_waqf audit --edition الشمرلي --pages 2-50

# Target-edition holdout: scores only reviewer-confirmed word anchors.
# البحرين uses hybrid proposals unless --proposal-mode is passed, and the
# Azhar occupancy prior unless --no-azhar-prior is passed.
.venv/bin/python -m pipeline.cv_waqf evaluate-hand --edition البحرين
.venv/bin/python -m pipeline.cv_waqf evaluate-hand --edition المساحة

# Diagnose geometry separately from classification. Reports proposal recall,
# proposal-to-word recall, and manual-box-to-word accuracy.
.venv/bin/python -m pipeline.cv_waqf evaluate-candidates \
  --edition البحرين --pages 198,202,221,255

# Mine safe lower-word-body windows as target-print `none` examples.
.venv/bin/python -c "from pathlib import Path; from pipeline.cv_waqf.build_crops import mine_component_negatives; mine_component_negatives('البحرين', [2,3,30], Path('artifacts/cv-waqf/hard-negatives'))"

# Deterministic calibration queue: six Quran regions + special/dense/sparse pages.
# --cache renders only the selected pages from the already-downloaded Bahrain PDF.
.venv/bin/python -m pipeline.cv_waqf review-queue \
  --edition البحرين --size 30 --cache

# Bootstrap draft plan for البحرين (human review before publish).
# Auto-set uses confidence >= 0.85; lower-conf hybrid hits stay in
# review_candidates / the /cv-waqf detect list and are not written.
.venv/bin/python -m pipeline.cv_waqf bootstrap --edition البحرين --pages 1-50
```

Outputs land under `artifacts/cv-waqf/`. The classifier is
`models/waqf_glyph.onnx` (OpenCV 5 DNN / `ENGINE_AUTO`).

## Tests

```bash
PYTHONPATH=. .venv/bin/python -m pytest tests/test_cv_waqf.py tests/test_cv_waqf_strip.py --noconftest -q
```
