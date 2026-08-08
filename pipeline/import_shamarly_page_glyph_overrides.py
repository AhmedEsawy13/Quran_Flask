#!/usr/bin/env python3
"""Build explicit Shemrly page-glyph overrides from ShemrlyMushaf exports.

The page fonts are not universally one-glyph-per-Quran-token.  Printed forms
may combine two database tokens, split one token into two glyphs, or carry a
separate sajdah ornament.  This importer aligns the reference page manifests
to this application's canonical ``word_key`` values and writes overrides only
for pages where the old count-and-zip inference would be wrong.

The reference project is required only while regenerating the tracked JSON::

    python3 pipeline/import_shamarly_page_glyph_overrides.py \
        --reference-root /path/to/ShemrlyMushaf
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import unicodedata
from pathlib import Path

from fontTools.ttLib import TTFont

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from modules import layout_engine  # noqa: E402


LAYOUT_DB = ROOT / "data" / "mushaf_layout_inferred.db"
SCRIPT_DB = ROOT / "data" / "quran_script.db"
FONT_DIR = ROOT / "static" / "fonts"
DEFAULT_OUTPUT = ROOT / "data" / "shamarly_page_glyph_overrides.json"
CODEPOINT_BASE = 0xFB50
WAQF_MARKS = set("ۖۗۘۙۚۛۜ")
ORNAMENTS = set("۩۞*")


def _normalized(token: str) -> str:
    result = []
    for char in unicodedata.normalize("NFKD", token or ""):
        if (
            unicodedata.combining(char)
            or char in WAQF_MARKS
            or char in ORNAMENTS
            or char == "ـ"
        ):
            continue
        result.append("ا" if char in "ٱأإآ" else char)
    return "".join(result)


def _ornaments(token: str) -> str:
    return "".join(char for char in (token or "") if char in ORNAMENTS)


def _is_ornament(token: str) -> bool:
    return bool(token) and all(char in ORNAMENTS or char.isspace() for char in token)


def _word_ids_for_page_rows(word_map: dict, rows: list[sqlite3.Row]) -> list[int]:
    result: list[int] = []
    seen: set[int] = set()
    positions = word_map["position_by_id"]
    ordered = word_map["ordered_ids"]
    for row in rows:
        first = row["first_word_id"]
        last = row["last_word_id"]
        if first is None or last is None:
            continue
        start = positions.get(int(first))
        end = positions.get(int(last))
        if start is None or end is None:
            if row["line_type"] != "ayah":
                continue
            raise ValueError(
                f"Unknown endpoint on page {row['page_number']}, line {row['line_number']}"
            )
        if start > end:
            raise ValueError(
                f"Reversed endpoint on page {row['page_number']}, line {row['line_number']}"
            )
        for word_id in ordered[start : end + 1]:
            if word_id not in seen:
                seen.add(word_id)
                result.append(word_id)
    return result


def _reference_words(manifest: dict) -> list[dict]:
    return [
        word
        for line in manifest.get("lines", [])
        if line.get("line_type") == "ayah"
        for word in line.get("words", [])
        if word.get("word_index") is not None
    ]


def _align_page(
    page: int,
    reference_words: list[dict],
    current_ids: list[int],
    word_map: dict,
) -> dict[int, tuple[int, ...] | None]:
    current = [(word_id, word_map["id2tok"][word_id]) for word_id in current_ids]
    expected: dict[int, tuple[int, ...] | None] = {}
    ref_pos = current_pos = 0
    previous_word_id: int | None = None

    while ref_pos < len(reference_words) and current_pos < len(current):
        reference = reference_words[ref_pos]
        word_id, token = current[current_pos]
        reference_text = str(reference.get("text") or "")
        current_text = str(token.get("text_original") or token.get("text") or "")
        reference_norm = _normalized(reference_text)
        current_norm = _normalized(current_text)
        codepoint = int(str(reference["codepoint"])[2:], 16)

        if (
            _is_ornament(reference_text)
            and _is_ornament(current_text)
            and _ornaments(reference_text) == _ornaments(current_text)
        ):
            expected[word_id] = (codepoint,)
            previous_word_id = word_id
            ref_pos += 1
            current_pos += 1
        elif reference_norm and reference_norm == current_norm:
            expected[word_id] = (codepoint,)
            previous_word_id = word_id
            ref_pos += 1
            current_pos += 1
        elif _is_ornament(reference_text):
            if previous_word_id is None:
                raise ValueError(f"Page {page}: leading unmatched reference ornament")
            previous = expected.get(previous_word_id)
            if previous is None:
                raise ValueError(f"Page {page}: ornament follows a fallback token")
            expected[previous_word_id] = (*previous, codepoint)
            ref_pos += 1
        elif _is_ornament(current_text):
            # The Quran token exists but this print has no dedicated page glyph.
            expected[word_id] = None
            previous_word_id = word_id
            current_pos += 1
        elif (
            current_pos + 1 < len(current)
            and reference_norm
            == current_norm
            + _normalized(
                current[current_pos + 1][1].get("text_original")
                or current[current_pos + 1][1].get("text")
                or ""
            )
        ):
            # One printed ligature represents two canonical Quran tokens.
            expected[word_id] = (codepoint,)
            expected[current[current_pos + 1][0]] = ()
            previous_word_id = current[current_pos + 1][0]
            ref_pos += 1
            current_pos += 2
        elif (
            ref_pos + 1 < len(reference_words)
            and reference_norm + _normalized(reference_words[ref_pos + 1].get("text") or "")
            == current_norm
        ):
            # One canonical token is printed by two adjacent page glyphs.
            next_codepoint = int(str(reference_words[ref_pos + 1]["codepoint"])[2:], 16)
            expected[word_id] = (codepoint, next_codepoint)
            previous_word_id = word_id
            ref_pos += 2
            current_pos += 1
        else:
            raise ValueError(
                f"Page {page}: cannot align reference {reference_text!r} "
                f"to canonical {current_text!r}"
            )

    while ref_pos < len(reference_words) and _is_ornament(
        str(reference_words[ref_pos].get("text") or "")
    ):
        if previous_word_id is None or expected.get(previous_word_id) is None:
            raise ValueError(f"Page {page}: unmatched trailing reference ornament")
        codepoint = int(str(reference_words[ref_pos]["codepoint"])[2:], 16)
        expected[previous_word_id] = (*expected[previous_word_id], codepoint)
        ref_pos += 1

    while current_pos < len(current) and _is_ornament(
        str(current[current_pos][1].get("text_original") or current[current_pos][1].get("text") or "")
    ):
        expected[current[current_pos][0]] = None
        current_pos += 1

    if ref_pos != len(reference_words) or current_pos != len(current):
        raise ValueError(
            f"Page {page}: alignment ended at reference {ref_pos}/{len(reference_words)}, "
            f"canonical {current_pos}/{len(current)}"
        )
    return expected


def _inferred_map(page: int, all_page_ids: list[int]) -> dict[int, tuple[int, ...]]:
    font_path = FONT_DIR / f"Shemrly-Page{page:03d}.woff2"
    font = TTFont(font_path)
    try:
        codepoints = sorted(
            codepoint
            for codepoint in (font.getBestCmap() or {})
            if codepoint > CODEPOINT_BASE
        )
    finally:
        font.close()
    if len(codepoints) != len(all_page_ids):
        return {}
    return {
        word_id: (codepoint,)
        for word_id, codepoint in zip(all_page_ids, codepoints)
    }


def build_overrides(reference_root: Path) -> dict:
    manifest_dir = reference_root / "exports" / "web" / "pages"
    if not manifest_dir.is_dir():
        raise FileNotFoundError(f"Reference page manifests not found: {manifest_dir}")

    word_map = layout_engine.script_word_map(str(SCRIPT_DB))
    layout = sqlite3.connect(f"file:{LAYOUT_DB.resolve()}?mode=ro", uri=True)
    layout.row_factory = sqlite3.Row
    pages: dict[str, dict] = {}
    try:
        for font_path in sorted(FONT_DIR.glob("Shemrly-Page*.woff2")):
            page = int(font_path.stem.removeprefix("Shemrly-Page"))
            manifest_path = manifest_dir / f"Page{page:03d}.json"
            if not manifest_path.exists():
                manifest_path = manifest_dir / f"Page{page}.json"
            if not manifest_path.exists():
                raise FileNotFoundError(f"Missing reference manifest for page {page}")

            rows = layout.execute(
                """
                SELECT page_number, line_number, line_type, first_word_id, last_word_id
                FROM pages WHERE page_number = ? ORDER BY line_number
                """,
                (page,),
            ).fetchall()
            all_ids = _word_ids_for_page_rows(word_map, rows)
            ayah_ids = _word_ids_for_page_rows(
                word_map, [row for row in rows if row["line_type"] == "ayah"]
            )
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            expected = _align_page(page, _reference_words(manifest), ayah_ids, word_map)
            inferred = _inferred_map(page, all_ids)
            if all(inferred.get(word_id) == glyphs for word_id, glyphs in expected.items()):
                continue

            font = TTFont(font_path)
            try:
                supported = set(font.getBestCmap() or {})
            finally:
                font.close()
            for glyphs in expected.values():
                if glyphs is not None and any(codepoint not in supported for codepoint in glyphs):
                    raise ValueError(f"Page {page}: override references a missing font glyph")

            glyphs_by_key = {}
            fallback_keys = []
            suppressed_keys = []
            for word_id, glyphs in expected.items():
                word_key = word_map["id2tok"][word_id]["word_key"]
                if glyphs is None:
                    fallback_keys.append(word_key)
                elif not glyphs:
                    suppressed_keys.append(word_key)
                else:
                    glyphs_by_key[word_key] = " ".join(f"{cp:04X}" for cp in glyphs)
            pages[str(page)] = {
                "glyphs": glyphs_by_key,
                "fallback": fallback_keys,
                "suppressed": suppressed_keys,
            }
    finally:
        layout.close()

    return {
        "version": 1,
        "source": "ShemrlyMushaf exports/web/pages manifests aligned by Quran text",
        "pages": pages,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    payload = build_overrides(args.reference_root.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {len(payload['pages'])} Shemrly page overrides to {args.output}")


if __name__ == "__main__":
    main()
