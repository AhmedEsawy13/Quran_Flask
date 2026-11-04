# Cloud run: Wathiq Billah + Sheikh Maktoum, whole book

Goal: split all 604 pages of both prints into words, read their waqf signs with the shipped model, and
compare every sign with the old Madinah 1405 column («المدينة القديم»). In the 27-page pilots both prints
matched old Madinah on every sign (175/175), so the expected result is "same" almost everywhere; the
differences are what the user reviews afterwards. Nothing in the app or the databases changes.

## Setup

```bash
pip install opencv-python-headless numpy scipy
```

Downloads need network access to `tafsir.app` and `archive.org`. If the environment blocks them, stop and
report: the user has to allow these hosts in the environment's network settings.

## Run (each step resumes where it stopped)

```bash
python3 pipeline/paw_split/book_run.py all wathiq --jobs 4
python3 pipeline/paw_split/book_run.py all maktoom --jobs 4
```

- `fetch`: Wathiq ~604 JPGs from tafsir.app (~0.4 MB each); Maktoum ~604 JPGs from archive.org (~3.8 MB
  each, ~2.3 GB). Re-run `fetch` if pages failed; the list of failures is printed at the end.
- `split`: about 16 s per Wathiq page (it retries line-break moves), a few seconds per Maktoum page.
  Errors go to `artifacts/<book>-trace/split-errors.json`; a page that fails is skipped, not retried.
- `waqf`, `compare`, `pack`: minutes.

If memory runs out, use `--jobs 2`.

## What to report back

1. Push `data/cloud_runs/wathiq/` and `data/cloud_runs/maktoom/` (word boxes, signs, comparison, crops of
   each difference). Do NOT commit page images or anything under `artifacts/`.
2. Paste the two `compare` summary lines into the session/commit message: pages done, split errors,
   pages with split flags, and the sign counts (`same`, `other_symbol`, `missed`, `print_only`,
   `print_only_noise`).

Pilot numbers to compare against (27 pages): Wathiq same 175, no differences; Maktoum same 163,
missed 8, other_symbol 4, print_only 8 (all checked by eye in the pilot: the model's errors, not the
print's), print_only_noise 199 (vowels and hamzas the reader fires on; no print marks them).
