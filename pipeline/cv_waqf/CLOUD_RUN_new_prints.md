# Cloud run: two new Hafs prints vs old Madinah (waqf signs)

Read every waqf sign of two prints with the shipped model and list where they differ from «المدينة القديم»
(both prints follow the 1405 line breaks). Nothing in the app or the databases changes.

| Edition key | id | Print | Source |
|---|---|---|---|
| `آل البيت` | aalalbayt | مصحف آل البيت (Jordan, Ministry of Awqaf), 620 px scans | tafsir.app `m-aalalbayt` |
| `التجويد دار المعرفة` | tajweed_maarifa | مصحف التجويد, Dar al-Maarifa, Damascus (Uthman Taha), colour | tafsir.app `m-tajweed-orig` |

Tested on the Mac, pages 3-45: Al al-Bayt 89.7% of signs equal to old Madinah, tajweed 91.1%
(misses are mostly faint ج/ص the model did not read, not real differences).

## Setup

```bash
pip install opencv-python-headless numpy pillow scipy
```
Install anything else an ImportError names. Downloads need `tafsir.app`; if blocked, stop and report.

## Run (each step resumes)

```bash
python3 -m pipeline.cv_waqf.fetch_scans aalalbayt
python3 -m pipeline.cv_waqf book-audit --edition "آل البيت" --workers 4 --out data/cloud_runs/aalalbayt-audit
python3 -m pipeline.cv_waqf book-review --edition "آل البيت" --dir data/cloud_runs/aalalbayt-audit

python3 -m pipeline.cv_waqf.fetch_scans tajweed_maarifa
python3 -m pipeline.cv_waqf book-audit --edition "التجويد دار المعرفة" --workers 4 --out data/cloud_runs/tajweed_maarifa-audit
python3 -m pipeline.cv_waqf book-review --edition "التجويد دار المعرفة" --dir data/cloud_runs/tajweed_maarifa-audit
```
Pages land in `data/refs/<id>/cache` (gitignored, ~100-200 MB each). If memory runs out use `--workers 2`.

## Then look at the differences by eye

Each audit item has a crop (`crop` in pages.jsonl). For every `symbol_differs` and `not_in_db` item, and a
sample of 50 `cv_missed` items per print, open the crop (and the page image if needed) and classify it:
**real** (the print really differs from old Madinah: name the sign it prints), **reader** (the model misread or
missed a sign that is printed as old Madinah has it), **position** (sign is there, attached to the wrong word),
or **unsure**. Write `data/cloud_runs/<id>-audit/REVIEW.md` (counts per class + the list of real ones with
verse:word, the print's sign and old Madinah's) and `review-by-eye.json`.

## Report back

Commit and push `data/cloud_runs/` (pages.jsonl, summary.json, review.html, crops, REVIEW.md) — never
`data/refs/` page images. Put both prints' match/wrong/missing/extra counts and the number of «real»
differences in the commit message.
