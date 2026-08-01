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

# Sync hand crops + ONNX to Supabase (other machines: pull-hand)
# Once: run pipeline/supabase_cv_waqf_hand.sql in Supabase SQL editor
python3 -m pipeline.cv_waqf status-hand --slug shamarly  # read-only check
python3 -m pipeline.cv_waqf push-hand --slug shamarly
python3 -m pipeline.cv_waqf pull-hand --slug shamarly

# Detect one page (line-by-line, above word-end band)
.venv-cv/bin/python -m pipeline.cv_waqf run-page --edition الشمرلي --page 5 --overlay

# Audit DB vs CV (reviewable report, no auto-merge)
.venv-cv/bin/python -m pipeline.cv_waqf audit --edition الشمرلي --pages 2-50

# Bootstrap draft plan for البحرين (human review before publish)
.venv-cv/bin/python -m pipeline.cv_waqf bootstrap --edition البحرين --pages 1-50
```

Outputs land under `artifacts/cv-waqf/`. The classifier is
`models/waqf_glyph.onnx` (OpenCV 5 DNN / `ENGINE_AUTO`).

## Tests

```bash
PYTHONPATH=. .venv-cv/bin/python -m pytest tests/test_cv_waqf.py --noconftest -q
```
