#!/usr/bin/env python3
"""One-time converter: the ORIGINAL Shamela book database (منار الهدى, Shamela
ID 6496 — a Microsoft Jet/Access .mdb, the same primary source OpenITI's
plaintext dump was itself digitized from) → a clean, authoritative per-surah
JSON source for build_classical_llm.py.

WHY this replaces the OpenITI-markdown slicer for منار specifically: the
Shamela DB carries the book's own table of contents (table t6496: title, page-
id, heading level) alongside its page-by-page text (table b6496). That gives
EXACT, unambiguous section boundaries — no more regex-guessing where one surah's
discussion ends and the next begins, which is what silently dropped النساء (a
single-hash header the OpenITI markdown's loader strips) and made قريش look
"unresolvable" (it turns out قريش has NO separate heading in منار at all — even
Shamela's own cataloguer filed it under سورة الفيل, confirming this is a real
authorial choice, not a parsing artifact — verified against the OpenITI copy
independently). The text is also fully vocalized (tashkeel) in the quotes,
vs. OpenITI's bare consonantal skeleton.

Requires `mdbtools` (brew install mdbtools) and the user-supplied `manar.mdb`
(Shamela's own export; a `.bok` file is the identical Jet-DB format renamed).
This script is run ONCE by a maintainer with the file in hand — its OUTPUT
(pipeline/classical_sources/manar_shamela_sections.json) is what's committed
and what build_classical_llm.py actually reads at build/extraction time; the
.mdb itself is never vendored (not redistributable, and this converter is only
needed again if a newer/cleaner Shamela export shows up).

Run:  python3 pipeline/convert_manar_shamela.py /path/to/manar.mdb
"""
import csv
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('RESEARCH_PRECOMPUTE', '1')
import build_classical_waqf as rx  # noqa: E402 — reuses surah_number()/ALIASES/clean_note

OUT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        'classical_sources', 'manar_shamela_sections.json')

# منار titles the shared ALIASES map (built for the OpenITI copy) doesn't cover —
# either a genuinely different name form, or (النساء) a header format the OTHER
# source's loader stripped so this gap was never noticed there either.
rx.ALIASES.update({
    'النساء': 4, 'المنافقين': 63, 'المنافقون': 63, 'الانشراح': 94, 'الشرح': 94,
    'لإيلاف قريش': 106, 'قريش': 106, 'الفلق': 113, 'الناس': 114, 'المطففين': 83,
    'التطفيف': 83, 'الرحيق': 83,
})
# «سورة الفيل» discusses قريش (106) immediately after, with NO separate heading
# of its own — confirmed a genuine authorial choice (independently verified in
# both the OpenITI copy and Shamela's own table of contents), not a parsing gap.
_COMBINED = {'الفلق والناس': (113, 114), 'سورة الفيل': (105, 106)}


def mdb_export(path, table):
    out = subprocess.run(['mdb-export', '-X', 'utf-8', path, table],
                         capture_output=True, check=True).stdout.decode('utf-8')
    # mdb-export's multi-line memo fields are properly quoted, but the csv
    # module still needs the stream opened/iterated in a way that doesn't
    # pre-split on embedded '\n' before the quote-aware parser sees it —
    # StringIO alone triggers "new-line character seen in unquoted field" on
    # this export; splitlines(keepends=True) + csv.reader over that avoids it.
    return list(csv.DictReader(out.splitlines(keepends=True)))


def clean_text(nass):
    # Shamela's own footnote-reference markup is «(¬N)» (a REFERENCE mark glyph
    # + digit), different from OpenITI's bare «(N)» — clean_note()'s regex only
    # strips the latter, so handle this format's marker first.
    nass = re.sub(r'\(\s*¬\s*\d+\s*\)', '', nass)
    return nass


def main():
    mdb_path = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser('~/Downloads/manar.mdb')
    if not os.path.exists(mdb_path):
        raise SystemExit(f'not found: {mdb_path} (pass the path to منار\'s Shamela .mdb/.bok)')

    toc = [t for t in mdb_export(mdb_path, 't6496') if t['id']]
    toc.sort(key=lambda t: int(t['id']))
    text_rows = {int(r['id']): r['nass'] for r in mdb_export(mdb_path, 'b6496') if r['id']}
    max_id = max(text_rows)

    surah_toc = [t for t in toc if t['tit'].startswith('سورة') or t['tit'] in _COMBINED]

    sections = {}   # surah_number(str) -> {"title":..., "text":..., "combined_with": [...]}
    last = 0
    missing_pages_report = []
    for t in surah_toc:
        title = t['tit']
        start_id = int(t['id'])
        # Bound by the NEXT toc entry of ANY kind (not just the next surah) — the
        # final surah otherwise has no surah-titled boundary and silently swallows
        # everything after it (خاتمة الكتاب + the bibliography, in this book).
        later = [int(o['id']) for o in toc if int(o['id']) > start_id]
        end_id = min(later) if later else max_id + 1
        nums = _COMBINED.get(title) or ((rx.surah_number(title, last),) if rx.surah_number(title, last) else ())
        nums = tuple(n for n in nums if n)
        if not nums:
            print(f'  WARNING: could not resolve title {title!r} — skipped', file=sys.stderr)
            continue
        last = max(last, max(nums))

        chunk_ids = [i for i in range(start_id, end_id) if i in text_rows]
        missing = [i for i in range(start_id, end_id) if i not in text_rows]
        if missing:
            missing_pages_report.append((title, missing))
        text = clean_text('\n'.join(text_rows[i] for i in sorted(chunk_ids)))

        for n in nums:
            sections[str(n)] = {'title': title, 'text': text,
                                'combined_with': [x for x in nums if x != n]}

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    json.dump(sections, open(OUT_PATH, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)

    all_surahs = set(range(1, 115))
    covered = {int(k) for k in sections}
    print(f'wrote {len(sections)} surah sections to {OUT_PATH}')
    print(f'coverage: {len(covered)}/114 surahs; missing entirely: {sorted(all_surahs - covered)}')
    if missing_pages_report:
        print('sections with internal page gaps in the source export (partial content):')
        for title, missing in missing_pages_report:
            print(f'  {title}: {len(missing)} page(s) missing (ids {missing})')


if __name__ == '__main__':
    main()
