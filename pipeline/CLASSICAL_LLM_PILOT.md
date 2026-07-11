# AI re-extraction of the classical waqf books — منار pilot

`build_classical_llm.py` re-extracts the classical waqf books with an LLM instead
of the regex/cursor pipeline in `build_classical_waqf.py`. It's offline / build-time
(zero AI at request time, same as `build_tafseer_local.py`).

## Why

The regex extractor pattern-matches a grade word next to a `{quote}`. That works
for entries printed in that exact shape but fails on the **discursive prose** these
books are mostly written in, so:

- the **علّة** (the reasoning — the point of the «لماذا يُوقف هنا؟» card) is empty or
  trimmed for most stops: منار 47% thin, مكتفى 78%, ابن الأنباري 68% (`<15` chars);
- `وكذا/ومثله` chains collapse to a bare `"و"`;
- whole surahs written as prose are **missed entirely** — e.g. منار's سورة الفاتحة
  classifies all 23 stops in prose («فالتامة أربعة: البسملة، والدين، ونستعين،
  والضالين …») and the regex extracted **0 rows** for it.

An LLM reads the prose and produces a clean `{ayah, stop_phrase, grade, reason,
reported_from}` per stop. A **deterministic** post-step then maps `stop_phrase → wpos`
with the same vetted `align_in_ayah()` the regex pipeline uses — which doubles as the
**anti-hallucination gate**: a phrase that isn't a verbatim run of words in that verse
is rejected. The علّة is kept **faithful** to the author's wording (cleaned/expanded
only — chains resolved, page-markers/poetry stripped), never reinterpreted.

## Pilot result (10 surahs, verified inline — no API key)

al-Fatiha + 91, 92, 93, 95, 96, 97, 108, 110, 112 → 83/83 stops aligned, 0 rejected,
63% carry a real علّة (al-Fatiha alone: 0 regex rows → 23, all with علّة). The two
«عليهم» in 1:7 disambiguate correctly (أنعمت عليهم → جائز @ w3, المغضوب عليهم → لا @
w6) — the exact repeated-word case the regex aligner mis-hit, solved because the
model gives the full phrase.

## The source: منار's OWN Shamela book database

`surah_blocks()` slices منار from `pipeline/classical_sources/manar_shamela_
sections.json` — converted (`pipeline/convert_manar_shamela.py`) from الأشموني's
own Shamela book database (Shamela ID 6496, a Microsoft Jet/Access file — the SAME
primary source OpenITI's plaintext dump was itself digitized from), not the OpenITI
markdown build_classical_waqf.py reads.

Why switch: the Shamela DB carries the book's own table of contents (exact page
boundaries — no title-matching guesswork), and the switch caught real gaps that
survived even after fixing header-detection on the OpenITI copy: **النساء and 5
other surahs were silently dropped** (a single-hash header format the OpenITI
loader strips), and **سورة قريش has no separate heading at all** — independently
confirmed by Shamela's own TOC (filed under سورة الفيل) — so that's a genuine
authorial choice, not a parsing bug. Coverage is now **114/114 surahs** (one
content gap survives: سورة مريم is missing 3 pages *in this particular Shamela
export* — a source-side gap, not a slicer bug; see the converter's stderr output).
The Shamela text is also fully vocalized (tashkeel) in quotes, vs. OpenITI's bare
consonantal skeleton — cross-checked byte-for-byte against the already-cached 10
surahs' source prose and it's identical content, just cleaner.

Re-running the converter (only needed if a newer/cleaner Shamela export shows up):
```bash
brew install mdbtools   # provides mdb-export, used to read the Access file
python3 pipeline/convert_manar_shamela.py /path/to/manar.mdb
```
The raw `.mdb`/`.bok` is never vendored (not redistributable); only the converted
JSON is committed. `build_classical_waqf.py` (the regex builder, used for all four
books incl. منار) and the other three books' AI extraction still read the OpenITI
markdown — unaffected.

## Run the full منار build (needs an API key)

```bash
# resumable + cached per surah, so re-runs are free and a crash just continues:
ANTHROPIC_API_KEY=sk-... python3 pipeline/build_classical_llm.py --book manar --api --write
```

- Writes to the **pilot db** `data/classical_waqf_llm.db` (NOT the shipped
  `classical_waqf.db`), under `source=manar_llm`, so nothing changes live yet.
- `--surahs 1,2,3` limits the run. `CLASSICAL_LLM_MODEL=…` overrides the model.
- Cached surahs (`pipeline/classical_llm_cache/manar_NNN.json`) are reused; delete a
  file to force re-extraction of that surah.

## Review before releasing

```bash
python3 -m pytest tests/test_classical_llm.py -v      # gates: lexicon, alignment, anti-hallucination
```

Compare per verse against the regex extraction (open both dbs), spot-check 2:255,
38:24, al-Fatiha. Only when satisfied, release into the shipped db:

```bash
python3 pipeline/build_classical_llm.py --book manar --write --db data/classical_waqf.db
# then rebuild research caches / restart as usual, and re-run the full test suite.
```

Note: the live `/api/classical-waqf` serves every `source` unfiltered, so releasing
means `manar_llm` will appear alongside (or replace) `manar` in the card — decide the
display/dedup policy in `waqf_guide.js` `loadMuktafa` before release.
