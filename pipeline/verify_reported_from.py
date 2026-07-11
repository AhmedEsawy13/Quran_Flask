#!/usr/bin/env python3
"""Verify/repair the `reported_from` field on already-extracted منار rows —
DETERMINISTIC pass (not LLM-based; see below for why).

WHY: spot-checking المائدة 5:1 found a real misattribution — the source reads
«{وأنتم حرم} [1] كاف، وقال نافع: تام» (منار's OWN view is كاف; نافع is cited
holding the DIFFERENT opinion تام), but the extraction tagged reported_from=
نافع onto the كاف row — backwards, since نافع actually held تام, not كاف.
The extraction prompt has since been tightened with an explicit worked
example of exactly this pattern (see build_messages() in build_classical_
llm.py), so newly-extracted surahs shouldn't repeat it — but the 442 rows
already extracted under the old, vaguer prompt need re-checking.

An EARLIER version of this script asked the LLM to re-verify each claim
against the surah's full source prose. Tested it directly against the KNOWN
المائدة 5:1 bug: it CONFIRMED the wrong attribution instead of fixing it. Not
reliable enough to ship, so this is a deterministic pattern check instead —
the specific error class here («GRADE1، وقال NAME: GRADE2» with GRADE1≠GRADE2)
has a fixed, regex-detectable signature, unlike the open-ended extraction
task itself (which genuinely needs an LLM's reading comprehension).

WHAT: for every cached row with reported_from=NAME, scan that surah's source
prose for literal «(و)قال NAME: GRADE» citations and collect which grade(s)
NAME is actually cited holding. If the row's own grade isn't among them
(and at least one citation for NAME WAS found — i.e. this isn't a case we
simply can't verify this way), the attribution is deterministically wrong:
clear reported_from on that row. Conservative by design (only corrects
clear mismatches; leaves anything unverifiable alone — see
reported_scholar()'s own "under-tag, don't over-tag" precedent in
build_classical_waqf.py, same principle applied here).

Patches directly into the existing per-surah cache JSON files
(pipeline/classical_llm_cache/manar_NNN[_cNN].json) — the same files
build_classical_llm.py reads, so a subsequent --write picks up the fix with
no re-extraction needed.

Run:
    python3 pipeline/verify_reported_from.py --book manar --apply
    # without --apply: dry-run report only, no files changed.
"""
import argparse
import glob
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('RESEARCH_PRECOMPUTE', '1')

import build_classical_waqf as rx  # noqa: E402
import build_classical_llm as b  # noqa: E402 — reuses _SHAMELA_SECTIONS/CACHE_DIR

_GRADE_ALT = '|'.join(re.escape(g) for g, _ in rx.GRADES)
_CITED_RE = re.compile(r'(?:و)?قالت?\s+([^:؛.{}()\d]{2,35}):\s*(?:وقف\s+)?(' + _GRADE_ALT + r')\b')
_GRADE_MAP = dict(rx.GRADES)


def cited_grades_in_text(text):
    """{normalized_name: {canonical_grade, ...}} for every literal
    «(و)قال NAME: GRADE» citation found in this surah's source prose."""
    out = {}
    for m in _CITED_RE.finditer(text):
        name = re.sub(r'^(الشيخ|الإمام)\s+', '', m.group(1).strip())
        canon = _GRADE_MAP.get(m.group(2), m.group(2))
        out.setdefault(name, set()).add(canon)
    return out


def find_name_grades(cited, claimed_name):
    """Exact match first, then a loose substring match either direction
    (names sometimes carry/omit a title or nasab the citation regex didn't
    strip) — returns None if genuinely not found (unverifiable, leave alone)."""
    if claimed_name in cited:
        return cited[claimed_name]
    for name, grades in cited.items():
        if claimed_name in name or name in claimed_name:
            return grades
    return None


def collect_claims(book):
    """{surah: [(file_path, index_in_file, row_dict), ...]} for every cached
    row that currently has reported_from set, across all of that surah's
    chunk files."""
    by_surah = {}
    for f in sorted(glob.glob(os.path.join(b.CACHE_DIR, f'{book}_*.json'))):
        m = re.match(rf'{book}_(\d{{3}})', os.path.basename(f))
        if not m:
            continue
        surah = int(m.group(1))
        rows = json.load(open(f, encoding='utf-8'))
        if not isinstance(rows, list):
            continue
        for i, r in enumerate(rows):
            if isinstance(r, dict) and r.get('reported_from'):
                by_surah.setdefault(surah, []).append((f, i, r))
    return by_surah


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--book', default='manar')
    ap.add_argument('--apply', action='store_true', help='patch the cache files (else dry-run report only)')
    args = ap.parse_args()

    sections = json.load(open(b._SHAMELA_SECTIONS, encoding='utf-8')) if args.book == 'manar' else {}
    by_surah = collect_claims(args.book)
    total = sum(len(v) for v in by_surah.values())
    print(f'{len(by_surah)} surahs have reported_from rows, {total} total claims.\n')

    confirmed = corrected = unverifiable = ambiguous = 0
    for surah in sorted(by_surah):
        prose = sections.get(str(surah), {}).get('text', '')
        cited = cited_grades_in_text(prose)
        for fpath, row_idx, row in by_surah[surah]:
            name, grade = row['reported_from'], row['grade']
            grades = find_name_grades(cited, name)
            if grades is None:
                unverifiable += 1
                continue
            if grade in grades:
                confirmed += 1
                continue
            if len(grades) > 1:
                # This scholar is cited holding DIFFERENT grades at different
                # verses in this surah (e.g. أبو عمرو, cited constantly, has
                # a distinct opinion per stop) — the citation-collection here
                # is surah-wide, not tied to this row's own position, so
                # "not among the grades found" is NOT reliable evidence of a
                # mismatch when the name is genuinely multi-valued. Report as
                # ambiguous rather than guess; don't touch the file.
                ambiguous += 1
                print(f'  AMBIGUOUS surah {surah} {row["ayah"]}:{row["stop_phrase"]!r} [{grade}] '
                      f'{name!r} cited holding {sorted(grades)} elsewhere in this surah — not cleared')
                continue
            # High confidence: NAME is cited in this surah holding exactly
            # ONE grade throughout, and it isn't this row's grade — clear
            # rather than guess a replacement (safe: removes a false claim
            # without risking a new, equally-unverified one).
            corrected += 1
            print(f'  surah {surah} {row["ayah"]}:{row["stop_phrase"]!r} [{grade}] '
                  f'{name!r} cited holding {sorted(grades)} (not {grade!r}) → clearing')
            if args.apply:
                file_rows = json.load(open(fpath, encoding='utf-8'))
                file_rows[row_idx]['reported_from'] = None
                json.dump(file_rows, open(fpath, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)

    print(f'\n{confirmed} confirmed correct, {corrected} corrected (cleared), '
          f'{ambiguous} ambiguous (multi-valued name, left as-is), '
          f'{unverifiable} unverifiable by this pattern (left as-is).')
    if corrected and not args.apply:
        print('(dry run — pass --apply to patch the cache files with these corrections)')


if __name__ == '__main__':
    main()
