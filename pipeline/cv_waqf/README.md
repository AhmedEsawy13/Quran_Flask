# OpenCV 5 waqf mark detection

Offline pipeline that **audits** existing `mushaf_waqf.db` marks against printed
page images and **bootstraps** draft marks for editions that still need them.

Does **not** run inside the public Flask reading path.

## Setup

```bash
python3 -m venv .venv-cv
.venv-cv/bin/pip install -r requirements-cv.txt
export PYTHONPATH=.
```

## Commands

```bash
# Cache page JPEGs (Archive / Bahrain PDF)
.venv-cv/bin/python -m pipeline.cv_waqf cache-pages --edition الشمرلي --pages 2-20
.venv-cv/bin/python -m pipeline.cv_waqf cache-pages --edition البحرين --pages 1-20

# Optional: Mesaha DjVu word boxes for training anchors
.venv-cv/bin/python -m pipeline.cv_waqf mesaha-boxes --page-start 2 --page-end 100

# After hand-labeling in /cv-waqf (mode تسمية):
.venv-cv/bin/python -m pipeline.cv_waqf train --crops data/cv/crops_hand/shamarly

# Build crops from every trusted edition whose matching scan is cached.
# Madinah/Azhar deliberately refuse to use a substitute print image.
.venv-cv/bin/python -m pipeline.cv_waqf sample-crops --trusted-all --pages 40

# Shared model: repeat --crops; validation is split by whole printed page.
.venv-cv/bin/python -m pipeline.cv_waqf train \
  --crops data/cv/crops_labeled/shamarly \
  --crops data/cv/crops_hand/bahrain \
  --crops data/cv/crops_hand/mesaha

# Safer two-stage model for noisy target scans: first reject non-marks, then
# classify only accepted waqf glyphs. This writes MODEL_gate.onnx beside MODEL.
.venv-cv/bin/python -m pipeline.cv_waqf train --two-stage \
  --crops data/cv/crops_hand/bahrain \
  --out artifacts/cv-waqf/bahrain_two_stage.onnx

# Or preserve a proven symbol classifier and train only the binary veto gate.
.venv-cv/bin/python -m pipeline.cv_waqf train --two-stage \
  --crops data/cv/crops_hand/bahrain \
  --reuse-symbol-model artifacts/cv-waqf/demo-bahrain/waqf_glyph_demo_current.onnx \
  --out artifacts/cv-waqf/bahrain_gated_current.onnx

# Promoted Bahrain-only model (automatically selected by run-page/UI).
.venv-cv/bin/python -m pipeline.cv_waqf train --two-stage \
  --crops data/cv/crops_hand/bahrain \
  --reuse-symbol-model artifacts/cv-waqf/demo-bahrain/waqf_glyph_demo_current.onnx \
  --out models/waqf_glyph_bahrain.onnx

# Sync hand crops + ONNX to Supabase (other machines: pull-hand)
# Once: run pipeline/supabase_cv_waqf_hand.sql in Supabase SQL editor
python3 -m pipeline.cv_waqf status-hand --slug shamarly  # read-only check
python3 -m pipeline.cv_waqf push-hand --slug shamarly
python3 -m pipeline.cv_waqf pull-hand --slug shamarly

# Detect one page (line-by-line, above word-end band)
.venv-cv/bin/python -m pipeline.cv_waqf run-page --edition الشمرلي --page 5 --overlay

# البحرين defaults to hybrid proposals (above-word band + line-component
# candidates) with the gated edition model:
# models/waqf_glyph_bahrain.onnx + waqf_glyph_bahrain_gate.onnx.
# On 44 labeled pages, gated + hybrid:
#   0.55 → 217/238 correct, 31 FP, 15 missing
#   0.85 → 214/238 correct, 14 FP
# Remaining FPs are 0.97+ fatha-sized glyphs — a cutoff cannot reach 0 FP.
# So detect/UI still run at 0.55 (review candidates); bootstrap/auto-set
# writes only confidence >= 0.85. Other editions stay narrow + 0.70 auto-set.
# --proposal-mode and --min-conf remain explicit overrides.
.venv-cv/bin/python -m pipeline.cv_waqf run-page --edition البحرين --page 198
.venv-cv/bin/python -m pipeline.cv_waqf run-page \
  --edition البحرين --page 198 --proposal-mode narrow
.venv-cv/bin/python -m pipeline.cv_waqf run-page \
  --edition الشمرلي --page 5 --proposal-mode hybrid

# Audit DB vs CV (reviewable report, no auto-merge)
.venv-cv/bin/python -m pipeline.cv_waqf audit --edition الشمرلي --pages 2-50

# Target-edition holdout: scores only reviewer-confirmed word anchors.
# البحرين uses hybrid proposals unless --proposal-mode is passed.
.venv-cv/bin/python -m pipeline.cv_waqf evaluate-hand --edition البحرين
.venv-cv/bin/python -m pipeline.cv_waqf evaluate-hand --edition المساحة

# Diagnose geometry separately from classification. Reports proposal recall,
# proposal-to-word recall, and manual-box-to-word accuracy.
.venv-cv/bin/python -m pipeline.cv_waqf evaluate-candidates \
  --edition البحرين --pages 198,202,221,255

# Mine safe lower-word-body windows as target-print `none` examples.
.venv-cv/bin/python -c "from pathlib import Path; from pipeline.cv_waqf.build_crops import mine_component_negatives; mine_component_negatives('البحرين', [2,3,30], Path('artifacts/cv-waqf/hard-negatives'))"

# Deterministic calibration queue: six Quran regions + special/dense/sparse pages.
# --cache renders only the selected pages from the already-downloaded Bahrain PDF.
.venv-cv/bin/python -m pipeline.cv_waqf review-queue \
  --edition البحرين --size 30 --cache

# Bootstrap draft plan for البحرين (human review before publish).
# Auto-set uses confidence >= 0.85; lower-conf hybrid hits stay in
# review_candidates / the /cv-waqf detect list and are not written.
.venv-cv/bin/python -m pipeline.cv_waqf bootstrap --edition البحرين --pages 1-50
```

Outputs land under `artifacts/cv-waqf/`. The classifier is
`models/waqf_glyph.onnx` (OpenCV 5 DNN / `ENGINE_AUTO`).

## Tests

```bash
PYTHONPATH=. .venv-cv/bin/python -m pytest tests/test_cv_waqf.py --noconftest -q
```
