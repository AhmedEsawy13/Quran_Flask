#!/usr/bin/env python3
"""Build QUL_data/tajweed_local.db — local tajweed-coloring data.

Replaces the former quran.com `/api/v4/.../uthmani_tajweed` network call.

Inputs (vendored under pipeline/tajweed_source/, both CC-BY / Tanzil terms):
  * tajweed.hafs.uthmani-pause-sajdah.json  — cpfair annotations, per-ayah
        codepoint [start,end) spans, riwayat Hafs.  (CC-BY 4.0)
  * quran-uthmani.txt                       — Tanzil Uthmani text the spans
        index into ("surah|ayah|text" lines).  (Tanzil terms)

Output:
  QUL_data/tajweed_local.db  →  table tajweed(verse_key TEXT PK, html TEXT)

The emitted HTML matches the shape the front-end already consumes from
quran.com's `text_uthmani_tajweed` field, i.e. runs of plain text interleaved
with `<tajweed class="...">…</tajweed>` spans, so static/script.js needs no
change. cpfair rule ids are remapped to the CSS class names already defined in
static/styles.css.
"""
import json
import os
import re
import sqlite3

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(BASE, "pipeline", "tajweed_source")
TANZIL_TXT = os.path.join(SRC, "quran-uthmani.txt")
ANN_JSON = os.path.join(SRC, "tajweed.hafs.uthmani-pause-sajdah.json")
OUT_DB = os.path.join(BASE, "QUL_data", "tajweed_local.db")

# cpfair rule id  ->  CSS class used in static/styles.css
RULE_MAP = {
    "ghunnah": "ghunnah",
    "idghaam_ghunnah": "idgham_ghunnah",
    "idghaam_no_ghunnah": "idgham_wo_ghunnah",
    "idghaam_mutajanisayn": "idgham_mutajanisayn",
    "idghaam_mutaqaribayn": "idgham_mutaqaribayn",
    "idghaam_shafawi": "idgham_shafawi",
    "ikhfa": "ikhafa",
    "ikhfa_shafawi": "ikhafa_shafawi",
    "iqlab": "iqlab",
    "madd_2": "madda_normal",
    "madd_246": "madda_permissible",
    "madd_muttasil": "madda_obligatory",
    "madd_munfasil": "madda_munfasil",
    "madd_6": "madda_necessary",
    "qalqalah": "qalaqah",
    "hamzat_wasl": "ham_wasl",
    "lam_shamsiyyah": "laam_shamsiyah",
    "silent": "slnt",
}

# Tanzil prepends the basmala to ayah 1 of every surah except al-Fatiha (1,
# where it is its own ayah) and at-Tawba (9, no basmala). The displayed text
# (quran_script.db) does not include it on those opening ayat, so strip the
# first four words there to keep word counts aligned with the front-end.
#
# Matched diacritic-insensitively: a couple of surahs (95, 97) spell the first
# word with an extra shadda ("بِّسْمِ"), so an exact-string compare would miss
# them.
_MARKS = re.compile("[" + "".join(chr(c) for c in
    list(range(0x0610, 0x061B)) + list(range(0x064B, 0x0660)) +
    [0x0670] + list(range(0x06D6, 0x06EE)) + [0x0640]) + "]")
_ALEFS = {0x0671: "ا", 0x0625: "ا", 0x0623: "ا", 0x0622: "ا"}


def _bare(word):
    return _MARKS.sub("", word).translate(_ALEFS)


BASMALA_BARE = ["بسم", "الله", "الرحمن", "الرحيم"]

_TAG = {"&": "&amp;", "<": "&lt;", ">": "&gt;"}


def esc(s):
    return "".join(_TAG.get(c, c) for c in s)


def load_tanzil():
    text = {}
    with open(TANZIL_TXT, encoding="utf-8") as fh:
        for line in fh:
            line = line.rstrip("\n")
            if "|" not in line:
                continue
            s, a, t = line.split("|", 2)
            text[(int(s), int(a))] = t
    return text


def strip_basmala(surah, ayah, text):
    """Return (text, cut) with the leading basmala removed on surah openings.

    `cut` is the number of leading codepoints dropped (0 if nothing stripped),
    so annotation offsets can be shifted to match.
    """
    if ayah != 1 or surah in (1, 9):
        return text, 0
    words = text.split(" ")
    if len(words) < 5:
        return text, 0
    if [_bare(w) for w in words[:4]] != BASMALA_BARE:
        return text, 0
    # length of the first 4 words + the 4 spaces that follow them
    cut = sum(len(w) for w in words[:4]) + 4
    return text[cut:], cut


def build_html(text, annotations):
    """Render one ayah's Tanzil text into interleaved plain/colored runs."""
    cls = [None] * len(text)
    # Last writer wins on overlap; cpfair spans are essentially non-overlapping.
    for an in annotations:
        c = RULE_MAP.get(an["rule"])
        if not c:
            continue
        for i in range(max(an["start"], 0), min(an["end"], len(text))):
            cls[i] = c

    out = []
    i = 0
    n = len(text)
    while i < n:
        c = cls[i]
        j = i
        while j < n and cls[j] == c:
            j += 1
        chunk = esc(text[i:j])
        out.append(chunk if c is None else f'<tajweed class="{c}">{chunk}</tajweed>')
        i = j
    return "".join(out)


def main():
    tanzil = load_tanzil()
    with open(ANN_JSON, encoding="utf-8") as fh:
        ann = json.load(fh)

    os.makedirs(os.path.dirname(OUT_DB), exist_ok=True)
    if os.path.exists(OUT_DB):
        os.remove(OUT_DB)
    con = sqlite3.connect(OUT_DB)
    con.execute("CREATE TABLE tajweed (verse_key TEXT PRIMARY KEY, html TEXT NOT NULL)")

    rows = []
    stripped = 0
    for obj in ann:
        s, a = obj["surah"], obj["ayah"]
        text = tanzil.get((s, a))
        if text is None:
            continue
        anns = obj["annotations"]
        text, cut = strip_basmala(s, a, text)
        if cut:
            stripped += 1
            anns = [
                {**x, "start": x["start"] - cut, "end": x["end"] - cut}
                for x in anns
                if x["end"] > cut
            ]
        rows.append((f"{s}:{a}", build_html(text, anns)))

    con.executemany("INSERT INTO tajweed (verse_key, html) VALUES (?, ?)", rows)
    con.commit()
    con.close()
    print(f"wrote {len(rows)} ayat to {OUT_DB} (basmala stripped on {stripped} openings)")


if __name__ == "__main__":
    main()
