# paw_split — words as glyphs from raster mushaf pages

Cuts a page's ink into connected pieces and gives every piece to a word: letter bodies are aligned
in order with the text's letter groups (PAWs) per stretch between verse rings (DP), marks follow
their letter, then line-crossing rules move fathas, dammas and waqf signs that sit nearer the next
line. Outputs go to gitignored folders: `artifacts/mesaha-trace/`, `artifacts/qatar-attach/`.

## Mesaha (المساحة, 1342)

Pages `data/cv/pages/mesaha/pNNN_w1600.jpg` (2062 px), words from `data/mushaf-mesaha-layout.db`
(reviewed pages = `EDITIONS['المساحة'].trusted_layout_pages`; pages with header rows still exit).

    python3 pipeline/paw_split/mesaha_split.py 15                 # -> paw-words-015.json/.png, labels-015.npy
    python3 pipeline/paw_split/word_tiles.py mesaha-trace paw-words-015.json /tmp/t015   # check by eye
    python3 pipeline/paw_split/regress.py mesaha-trace 015 021 041 085 104 170 271 339 397 411
    python3 pipeline/paw_split/mesaha_debug_pieces.py 15 1 2       # pieces of words 1, 2

`regress.py` compares with the hand-checked `paw-words-NNN.truth.json` (1,009/1,009 words on those
ten pages, 2026-10-21). Run it after any change to the rules.

## Qatar (قطر) — app pages 1-49

Reads the Qatar mushaf app's bundled pages and verse regions in place (`QATAR_APP_ASSETS`).

    python3 pipeline/paw_split/qatar_split.py 33                  # -> paw-words-033.json, labels-033.npz
    python3 pipeline/paw_split/qatar_detect_shipped.py 3 49       # shipped detector -> shipped.json
    python3 pipeline/paw_split/qatar_register.py 3 49             # 1024 px scan -> app page fit
    python3 pipeline/paw_split/qatar_attach_eval.py               # seat attach vs ink-ownership attach

Kraken word spaces (review flags only): `qatar_binarize.py N`, `qatar_kraken_crops.py N`, then
`pipeline/cv_waqf/kraken_read_rows.py kraken_crops` in the ShemrlyMushaf venv, then `qatar_kraken_check.py N`.

Result (2026-10-21): ink-ownership attach does not beat the shipped seat attach (96.4% vs 98.9% on
pages 3-49, mostly training pages): signs overhang the gap after their word, and the 1024 px scan
only registers to the app page within a few pixels.

## Notes

- Word ids: walk `quran_script.db` reading order (`layout_geo._ids_between`), never
  `range(first, last + 1)` — ids jump inside 2:285, 3:7, 38:79, 39:5, 59:19, 60:1 by design.
- Mesaha alif = one thin stem through its upper and lower middle (wasla/hamza merge into the box);
  verse rings = a closed outline around a large empty inside, found line by line.
