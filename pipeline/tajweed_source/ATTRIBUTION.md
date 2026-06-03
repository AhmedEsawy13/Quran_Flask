# Tajweed source data — attribution

These files are build-time inputs for `pipeline/build_tajweed_local.py`, which
produces `QUL_data/tajweed_local.db` (the local tajweed-coloring data that
replaces the former quran.com `/api/v4/.../uthmani_tajweed` network call).

## `tajweed.hafs.uthmani-pause-sajdah.json`
Tajweed annotations (riwayat Hafs) with exact per-ayah codepoint character
indices for each rule.

- Source: https://github.com/cpfair/quran-tajweed
- License: **Creative Commons Attribution 4.0 International (CC-BY 4.0)**
  https://creativecommons.org/licenses/by/4.0/
- The `start`/`end` indices index into the Tanzil.net Uthmani ayah text below.

## `quran-uthmani.txt`
Tanzil.net Uthmani Qur'an text (the exact snapshot the annotations were built
against — downloaded via the cpfair repo, ca. 2017-04-06).

- Source: https://tanzil.net/download/
- Terms: https://tanzil.net/download/ (Tanzil.net terms of use)
- Used here only as the coordinate system for the annotation offsets; the
  displayed text in the app comes from `QUL_data/quran_script.db`, not from this
  file.

Attribution is surfaced to end users via the tajweed legend (see templates).
