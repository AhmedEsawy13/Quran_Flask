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

**The shipped `waqf_glyph_multiprint` is the Bahrain + Qatar + Kuwait model**
(round-2 `models/cloud2/kuwait_s1`, bundle v3; same weights as Kuwait's own
model). Its gate on the held-out pages: Qatar 97.3% exact / 5 wrong / 98.0%
precision, Bahrain 94.4% (seed 1 is the best of three; the three-seed mean is
Qatar 96.6%, Bahrain 93.3%, GATE PASSED, i.e. level with the old two-print
model on Qatar). Its benefit is on prints never trained on, which is not yet
measured; score it against the old model on the Mesaha hand labels
(`evaluate-hand`) when they exist. The old two-print model is in git history
(`git show 90320fd:models/waqf_glyph_multiprint.onnx`). When copying a cloud
model into `models/`, rewrite `gate_model` in its `.json` to the new file name.

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
- **Leave-one-edition-out (CNN, 2 seeds each; post geometry fix).** Trained
  on one print's crops only (`train-cnn --bundle … --only bahrain|qatar`,
  `--cap-none 8000 --augment 2 --epochs 25`), scored on both prints'
  held-out pages with `compare-models` (models in `models/loeo/`, training
  log in `models/loeo/RESULTS.md`). Exact-match %, mean of the 2 seeds with
  the per-seed range:

  | trained on → scored on | exact (mean) | per seed | wrong | missed | false pos |
  |---|---|---|---|---|---|
  | Bahrain-only → Qatar (unseen print) | **80.7%** | 75.3 / 86.0 | 20 / 16 | 54 / 26 | 0 / 0 |
  | Qatar-only → Bahrain (unseen print) | **84.0%** | 79.2 / 88.8 | 12 / 3 | 14 / 11 | 2 / 3 of 65 |
  | Bahrain-only → Bahrain (in-distribution) | 92.0% | 92.0 / 92.0 | 3 / 2 | 7 / 8 | 2 / 2 of 65 |
  | Qatar-only → Qatar (in-distribution) | 93.3% | 93.3 / 93.3 | 9 / 8 | 11 / 12 | 1 / 2 |
  | *shipped CNN, both prints (3 seeds)* | | Qatar 95.7–97.0, Bahrain 92.0–93.6 | | | |

  Reading it: an unseen print costs ~12–16 points against the in-distribution
  number, almost all as *missed* stops (54 and 26 misses on Qatar), not false
  marks, and the two seeds disagree by 6–10 points, so treat the means as
  ±5. The old "Bahrain-only → Qatar 51%, Qatar-only → Bahrain 80%" figures
  were pre-fix single runs; the real gap is much smaller on the Qatar side
  (51 → 81) and about the same on the Bahrain side. Qatar-only is also 2–3
  points under the shipped CNN on Qatar itself (93.3 vs 95.7–97.0): it did
  not see Bahrain's crops, and these models were trained on a different torch
  build (Linux, not byte-identical to the Mac one, per `RESULTS.md`). The
  "3× more pages did not help" claim from the same pre-fix era is still
  untested with the CNN.
- Without the seat prior the detector alone fires on ~10% of empty words on
  *both* prints; see "The seat prior" for what it removes and what it costs.

## Kuwait retraining (cloud)

`data/cv/bundles/multiprint_crops_v2.npz` = v1 (Bahrain + Qatar) plus 23.6k
Kuwait detector-window crops cut from 200 training pages (`splits.kuwait_pages`,
seed 2027; 100 more pages are held out and never in the bundle). Kuwait labels
are the print's own column as synced from the cloud on 2026-10-04. The bundle
has 60 validation page groups (31 from v1 plus every 7th Kuwait page). Train
off-machine (this Mac has no torch), three seeds fixed in advance:

```bash
for s in 0 1 2; do
  python -m pipeline.cv_waqf train-cnn --bundle data/cv/bundles/multiprint_crops_v2.npz \
    --out models/cloud/kuwait_s$s.onnx --seed $s --cap-none 8000 --augment 2 --epochs 25
done
```

Score locally (needs the scans): `compare-models --model models/cloud/kuwait_s0.onnx ...`
for Bahrain/Qatar (must not regress: Qatar ≥ 95.7, Bahrain ≥ 92.0 exact) and the
audit on the 100 Kuwait hold-out pages against the column.

**Kuwait cloud models** (`models/cloud/`, trained on the v2 bundle; scored on the
100 held-out Kuwait pages against the synced Kuwait column, hybrid + prior +
reattach, min_conf 0.55; there are no Kuwait hand labels, so this is a column
proxy). `kuwait` = all three prints, `kuwait_only` = Kuwait crops only:

| model | Kuwait exact | wrong | missed | extra | Qatar exact | Bahrain exact |
|---|---|---|---|---|---|---|
| shipped multiprint | 91.5% | 44 | 25 | 7 | 97.0% | 93.6% |
| kuwait s0 / s1 / s2 | 92.1 / 94.8 / 93.0% | 54 / 29 / 46 | 10 / 13 / 11 | 10 / 7 / 9 | 95.7 / 96.0 / 95.7% | 90.4 / 94.4 / 92.8% |
| **kuwait mean** | **93.3%** | 43 | **11.3** | 8.7 | 95.8% | 92.5% |
| kuwait_only s0 / s1 / s2 | 92.3 / 95.2 / 92.6% | 38 / 27 / 40 | 24 / 12 / 20 | 6 / 8 / 8 | 72.7 / 85.0 / 78.0% | 72.0 / 69.6 / 71.2% |
| **kuwait_only mean** | **93.4%** | 35 | 18.7 | 7.3 | 78.8% | 70.9% |

Seeds differ by about 3 points on Kuwait, so the 1–2 point gains over the shipped
model are within noise; the halved miss count (25 → 10–13 on every seed) is not.
**Round 2 installed (`models/cloud2/kuwait_s1` = Kuwait's own model).** Trained on
502 Kuwait pages with the reviewed column (bundle v3, `--cap-none 14000`). 100
held-out pages, mean of 3 seeds, round 1 -> round 2: corrected column exact
95.2% -> 96.4% (wrong 28 -> 22, missed 11.3 -> 7.3, extra 3.7 -> 6.0);
pre-review column 93.3% -> 94.6% (wrong 43 -> 36). Seed 1 is the best seed on
both (97.7% / 95.8%) and on Qatar (97.3%) and Bahrain (94.4%); expect about the
family mean, 96.4% / 94.6%, not the best seed. The three seeds pass `gate`
(Qatar 96.6%, 6.3 wrong, 97.2% precision; Bahrain 93.3%). Extras rose (6 vs 3.7):
checked as likely real stops the column lacks, not yet confirmed. No Kuwait hand
labels, so both columns remain proxies.

Round 1 (superseded): `kuwait_s1` was Kuwait's own model (`models/waqf_glyph_kuwait*`); Bahrain
keeps its own model and Qatar the shared multiprint. Expect about the family
mean (93.3%), not seed 1's 94.8%, since the seed was picked on these pages.
The three `kuwait` seeds pass `gate` on their mean (Qatar 95.8% / 7.3 wrong /
96.9% precision, Bahrain 92.5%).

**Round 2 (Kuwait, `multiprint_crops_v3.npz`).** After the review corrections
(Kuwait column synced 2026-10-04, 105 changes) the Kuwait crops were regenerated
from 502 pages (every page except the 100 held-out, `splits.kuwait_extended_train`)
and the `none` crops subsampled to 22k. `--cap-none` caps the *total* `none`
crops at random, so the cap is raised to 14000 to keep the positive : none ratio
of round 1 (positives went from ~3k to ~5.3k):

```bash
for s in 0 1 2; do
  python -m pipeline.cv_waqf train-cnn --bundle data/cv/bundles/multiprint_crops_v3.npz \
    --out models/cloud2/kuwait_s$s.onnx --seed $s --cap-none 14000 --augment 2 --epochs 25
done
```

Scoring caveat: the corrected column now agrees with `kuwait_s1` by construction
(only marks the reviewer ticked as "model is correct" were changed). Score every
model on the 100 held-out pages against **both** the corrected column and the
pre-review column (`data/mushaf_waqf.backup_sync_20261004T112314Z.db`); the true
gain lies between the two. `kuwait_s1` itself: 94.8% (pre-review) / 96.7%
(corrected). No Kuwait hand labels exist yet, so neither is ground truth.

## Mesaha (المساحة): status

Scan: 827 pages, 12 lines, clean black-on-white, frame + ornament band.
What is in place (all behind the Mesaha spec, nothing else changes):

- `strip_frame=True`: `preprocess.strip_frame` whitens the frame (grown by 4 px,
  its anti-aliased edge otherwise survives as a grey halo the adaptive threshold
  reads as ink), the ornament band and everything outside the inner rule. Found
  on 138 / 138 sampled pages; a closed frame is required, otherwise the page is
  left untouched.
- Per-parity text band (`text_band_even`, `band_for_page`): odd 0.1232/0.7393,
  even 0.0954/0.7115, spread +-0.1 line.
- Printed-word mapping (`word_space.printed_position`): the Shemrly word space
  counts ornaments (`۞`, ayah numerals) as words, so its positions run ahead of
  the waqf table's `word_index`. Counting only tokens that contain an Arabic
  letter reproduces `word_index` for 11,699 / 12,445 rows (94%; the rest are the
  known mis-indexed or duplicate rows). Used by the seat prior and re-attachment
  for every non-QPC edition.
- Bug fixed: `edition_marks_for_ayahs('المساحة')` read a non-existent column,
  which SQLite treats as a string literal, so every Mesaha "reference mark" was
  the text المساحة (normalised to م). All Mesaha audits before this fix were
  meaningless. It now borrows `mushaf_version` (Shemrly) and raises on an
  unknown column.

Line breaks (`relayout.py`, `ocr_relayout=True`). The Mesaha layout DB was
imported from OCR and never reviewed (221 pages graded high, 364 medium, 241
low; on page 61 its last line holds 87 words), so words sat several positions
from their printed row. The relayout re-derives row membership from three
things the scan itself provides: the DjVu OCR words (aligned to the page's
known text by dotless letter shape; accurate anchors for ~30% of words), the
verse-end medallions (template-matched, accepted only when the best N beat the
next by a margin, N = number of verse-number tokens), and the justified row
widths (words between two anchors are split across the rows in between by a
per-letter width model fitted from the anchors, 15.5% mean error per word
against 21% for letter count). Anchors that make a row implausible are
dropped; the result is used only when every row holds 5-14 words, otherwise
the layout's own lines are kept. Against 37 hand labels (5 pages): the nearest
word is the one you chose 38% -> 59% of the time (top-6 81% -> 89%); page 61
6/14 -> 12/14. Used on 67% of 49 sampled pages, ~0.2 s per page. Surah-opening
pages with poor OCR (62, 445) fall back. Validation is thin: only 3 labelled
pages are eligible, so more labels are the best way to check it.

**Kraken line OCR (2026-10-05).** `local/mesaha-kraken-fuse` (Aug 30) had already
run Kraken's printed-Arabic model (zenodo 7050296) over every Mesaha page on
Kaggle; its output is committed as `assets/mesaha_kraken_lines.json` (one entry
per OCR line: `y`, `text`, `width`, DjVu scale). It is far better than the
DjVu OCR: on the 59 reviewed pages 98.6% of printed rows have a Kraken line,
93.8% of them >= 0.8 similar to the true row text (median 0.968). The relayout
now uses it first (`kraken_rows`, falling back to the DjVu path):

1. Each good line (>= 3 Arabic words, >= 75% of the row width) is a printed
   row, from its y alone. Its words are aligned to the canonical text by a
   semi-global Needleman-Wunsch (`_token_alignment`; leading/trailing canonical
   words are free, so a repeated word cannot tie with its twin on the
   neighbouring page; short words are kept, the sequence context settles them).
2. Matched words pin their rows; verse medallions and DjVu anchors add x
   positions when they agree with the pins. Everything else lies between two
   pins, so only the row *boundaries* are unknown: a DP over the rows picks
   them to make every row's words fill its width (`row_cost`).
3. The page's own word list is wrong by dozens of words on some pages (page 390
   starts at 18:58 where the print starts at 18:61), so the alignment is offered
   `EXTENSION_WORDS = 80` words of each neighbouring page and the page starts
   and ends where Kraken's text does (`MAX_EDGE_MISS` words of slack).

Results (reviewed pages 2-60, run with the reviewed-page skip off): Kraken used
on 52 of 59 pages, 94.1% of their rows exactly right (DjVu-only: 91.9% with
about half the coverage), 99.6% of words on the right row. On the 16 random
pages the user spot-checked (row-level verdicts, blank = wrong): the relayout
now runs on 13 instead of 8; hand labels page 277 first suggestion 2/6 -> 6/6.
Remaining errors are single short words at a row edge that Kraken did not read.

**Kraken relayout, round 2 (fresh random pages, user verdicts).** 16 random
pages 63-827 (seed 2027, not used for tuning): the relayout produced rows on 15
(all Kraken), **167 / 177 rows right (94.4%)**, 10 / 15 pages fully right; the
10 wrong rows are single short words at a row edge (a verse's first word left at
the previous row's end: "بل", "لا"; Kraken does not read the row's first token
and the width fit cannot settle a 1-word difference). On 14 reviewed pages, the
detector's marks land on the same word as under the reviewed layout 96.5% of
the time (251 / 260; DjVu relayout 93.8%, old OCR import 48.5%). Whole book
63-827: Kraken 619 pages, DjVu 17, fallback to the layout's own rows 129 (83.1%
coverage; mostly isolated pages, size-gate failures `r6`).

**Relayout drafts in the layout DB (2026-10-05).** `python -m pipeline.cv_waqf.mesaha_drafts
[--apply]` writes the relayout's rows for the covered pages (63-827) into
`data/mushaf-mesaha-layout.db` (what Layout Studio edits; Supabase, the reviewed store, is not
touched; pages 2-62 are left alone). 636 pages drafted (619 Kraken, 17 DjVu). The relayout can
move a page's first/last word, so boundaries are reconciled to keep the DB's exact canonical
continuity (every word on exactly one page; two layout tests pin it): between two drafts the next
page's first word wins; an untouched (fallback) neighbour's edge rows are trimmed/extended to the
draft's boundary (90 pages; 60 rows emptied, i.e. NULL-word `ayah` rows, where the old page held
far more than the draft's edge row). Provenance is in the new table `relayout_drafts` (page,
kind `draft`|`neighbour-edge`, source, flags); `layout_import_confidence` (the import's record)
is unchanged. Review order: `artifacts/cv-waqf/mesaha-relayout-drafts/review_queue.csv`
(emptied rows, moved edges, boundary notes, DjVu, then Kraken drafts). These are drafts: about a
third of pages still have a one-word row error. **Safety:** `--apply` asks Supabase which pages are
already saved/reviewed in Layout Studio (plus the local progress table) and never rewrites them: those
pages stay fixed and their neighbours' edges meet them (it stops if Supabase cannot be reached;
`--offline` skips the check). A draft row that spans two surahs is rejected by Studio's save
validation (a surah change needs its banner row), so such pages (96, 97, 283, 419, 420, 783) are kept
as imported and their neighbours meet them.

**Reviewed layout (Supabase, 2026-10-05).** The reviewed Mesaha layout lives in
the cloud (`editor_layout_pages`, edition `mesaha`), not in the local
OCR-import DB; pull it with `layout_persistence.working_db_path(MESAHA,
force=True)` (backs nothing up: copy `data/mushaf-mesaha-layout.db` first).
Pages 2-62 are there (61 and 62 still in progress: page 61's last row holds 86
words), so `trusted_layout_pages=(2, 60)` skips the relayout on 2-60. Those 59
pages are the first real test of it: the old OCR import put **85.6%** of words
on the right row (all 59 pages had errors); the relayout, run from the OCR and
the images only, puts **99.5%** on the row the reviewer chose (98.6% on the 21
pages where it differed from the layout at all). Against the 37 hand labels
with the reviewed layout the first suggestion is the right word on page 4 5/5,
page 61 12/12 of 14 either way.

Open: Mesaha prints many more stop signs than the Shemrly column records (about
10 per page detected vs 4 per page in the column), so that column is **not** a
usable reference and the multiprint model without a prior is about half false
positives (verse ornament `*`, hamza, dagger alef, letter parts). Next step:
hand-label ~20 Mesaha pages in `/cv-waqf`, then score, and train Mesaha crops
(the ornaments become `none` examples).

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
the edition-specific stops the prior existed to protect.

**الكويت** uses the same prior. The earlier "Azhar covers only 91.9% of
Kuwait's stops" counted the 363 `ركوع` rows, which are section markers, not
waqf signs (the classifier has no class for them and no other edition records
them). On waqf signs only, Azhar + Madinah covers 4654 of Kuwait's 4670 seats
(99.66%, 16 lost). `audit` now leaves `ركوع` out of the reference.

Kuwait (Archive scan, leaf = page + 3; the scan is served at 1146 px and
resampled to 1024 on download), shipped multiprint model, hybrid proposals +
prior, min_conf 0.55, 40 unseen pages (12–597 step 15) vs the Kuwait DB column:
228 / 263 exact (86.7%), 24 wrong symbol (mostly ق→ج 7, ج→ص 5, لا→ج 4),
11 missed, 7 extra. All 7 extras are real `صلى` printed on the scan and absent
from the DB column (Azhar has ج on each), so true precision is ≈ 90.7% and the
Kuwait column is missing roughly one stop every six pages. Without the prior
the same model adds ~15 false marks per page (frame ornaments, headers,
harakat); narrow proposals find almost nothing (8 / 89 on 10 pages).

Whole book (604 pages, same settings, text_left/right 0.06/0.94): 4160 / 4670
waqf seats exact (89.1%), 307 wrong symbol, 203 missed, 161 not in the DB.
Spot checks: 12 / 12 sampled not-in-DB marks at confidence ≥ 0.99 (131 such)
are real printed stops the column lacks; below 0.99 about half are real
(often a `لا` read as ج) and half are frame ornament or letter dots. The wrong
symbols are mostly the model: Kuwait's `قلى` (ق→ج 101, ق→ص 51) and `لا`
(لا→ج 46) glyphs differ from Bahrain/Qatar's, so it needs Kuwait crops, but
some are DB errors (the print has ج where the column copies Madinah's ص).
Review list: `artifacts/cv-waqf/kuwait-book/review.html` (not in git).

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
