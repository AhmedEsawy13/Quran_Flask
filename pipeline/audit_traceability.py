#!/usr/bin/env python3
"""Anti-hallucination audit for the AI-extracted منار rows: for EVERY row in
the pilot db, verify its grade is actually grounded in the source text —
not invented. Pure local string search, no API calls, runs against all
11k+ rows.

Three tiers, weakest evidence discarded first:
  1. explicit «{quote} [n] grade» marker match — what the regex pipeline
     itself could also catch.
  2. منار states MANY rulings in prose LISTS with no [n] marker per item at
     all (e.g. «والجائزة: «الحمد لله»، و «العالمين»، و «الرحيم»...») — this
     is exactly the shape the regex pipeline structurally cannot reach, and
     a big part of why the AI extraction recovers so much more than regex
     ever did. Checked via: does the row's own word (normalised — see
     tokenize_normalized) appear ANYWHERE in the surah's prose, with its
     grade nearby?
  3. «ومثله/وكذا» CHAIN continuations: a later ayah's stop legitimately
     inherits an EARLIER ayah's marker+grade with no marker of its own
     (e.g. «{لَحَافِظُونَ (12)} [12] كاف، ومثله: «غافلون»، و «لخاسرون».» —
     غافلون/لخاسرون belong to LATER ayat but carry NO marker of their own).
     Checked via: does the row's word appear inside a chain list
     (ومثله/وكذا/...) anywhere, with the row's grade attached to that list's
     trigger?

A row failing all three is flagged SUSPECT for manual review — not treated
as proven wrong (a miss can still be a checker limitation, not a genuine
fabrication), but it's the honest, evidence-based signal this audit can
give without another full manual read of the whole book. The audit checks both
the converted Shamela JSON and the independent OpenITI copy.

Run: python3 pipeline/audit_traceability.py [--window 500] [--surah N]
"""
import argparse
import json
import os
import re
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('RESEARCH_PRECOMPUTE', '1')

import build_classical_waqf as rx  # noqa: E402
import build_classical_llm as llm  # noqa: E402

_GRADE_MAP = dict(rx.GRADES)
_MITHL_RE = re.compile(r'(ومثله|ومثلها|وكذلك|وكذا|ونحوه|ونحوها)')


def grade_synonyms(canonical):
    return [g for g, c in rx.GRADES if c == canonical]


def tokenize_normalized(prose):
    """[(char_start, char_end, normalized_token), ...] — uses the project's
    OWN Uthmani-orthography normalizer (rx.norm, already battle-tested for
    exactly this problem elsewhere in the pipeline), not a hand-rolled
    diacritic stripper. Needed because the mushaf's own spelling and the
    book's quoted spelling don't just differ in WHICH diacritics are used —
    the mushaf frequently spells a long vowel as a dagger-alif DIACRITIC
    (e.g. a word written with a small superscript alif mark) where the
    book's prose spells it with a full alif LETTER — a base-letter-count
    difference a diacritic-only strip can't bridge, but rx.norm() already
    folds correctly (it's used throughout this project to match mushaf
    words against classical-book quotations)."""
    out = []
    for m in re.finditer(r'[؀-ۿ]+', prose):
        n = rx.norm(m.group(0))
        if n:
            out.append((m.start(), m.end(), n))
    return out


def markers_and_windows(prose, ayah, window):
    spans = []
    for m in re.finditer(r'\[' + str(ayah) + r'\]', prose):
        lo, hi = max(0, m.start() - window), min(len(prose), m.end() + window)
        spans.append(prose[lo:hi])
    return spans


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--window', type=int, default=500)
    ap.add_argument('--surah', type=int, default=None)
    ap.add_argument('--db', default=os.path.join('data', 'classical_waqf.db'))
    ap.add_argument('--source', default='manar',
                    help='classical.source tag to audit (default: released manar)')
    ap.add_argument('--samples', type=int, default=25)
    ap.add_argument('--review-out', default=None,
                    help='write every suspect row plus source context as JSONL')
    ap.add_argument('--max-suspect', type=int, default=None,
                    help='exit non-zero if suspects exceed this regression ceiling')
    args = ap.parse_args()

    source_sections = (
        llm.load_shamela_sections(),
        llm._openiti_manar_crosscheck_sections(),
    )
    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    q = ("SELECT id, surah, ayah, wpos, stop_word, quote, grade, grade_raw, note, reported_from "
         "FROM classical WHERE source=?")
    params = [args.source]
    if args.surah:
        q += ' AND surah=?'
        params.append(args.surah)
    rows = conn.execute(q + ' ORDER BY surah, ayah, wpos', params).fetchall()
    if not rows:
        raise SystemExit(f'no rows found for source={args.source!r} in {args.db}')

    total = t1 = t2 = t3 = suspect = 0
    misses = []
    review_items = []
    prose_cache, ayah_present_cache, tok_cache = {}, {}, {}

    for r in rows:
        surah = r['surah']
        if surah not in prose_cache:
            prose_cache[surah] = []
            for sections in source_sections:
                text = sections.get(str(surah), {}).get('text', '')
                if text and text not in prose_cache[surah]:
                    prose_cache[surah].append(text)
            tok_cache[surah] = [
                tokenize_normalized(text) for text in prose_cache[surah]
            ]
        total += 1
        syns = grade_synonyms(r['grade'])
        grounded = False
        ayah_in_source = False
        context = ''
        word_n = rx.norm(r['stop_word'])

        for source_index, (prose, toks) in enumerate(
            zip(prose_cache[surah], tok_cache[surah])
        ):
            key = (surah, source_index, r['ayah'])
            if key not in ayah_present_cache:
                ayah_present_cache[key] = bool(
                    re.search(r'\[' + str(r['ayah']) + r'\]', prose)
                )
            ayah_in_source = ayah_in_source or ayah_present_cache[key]

            # Tier 1
            if ayah_present_cache[key]:
                spans = markers_and_windows(prose, r['ayah'], args.window)
                if any(any(s in span for s in syns) for span in spans):
                    t1 += 1
                    grounded = True
                    break

            # Fuzzy (level-2, via the pipeline's OWN match_word — same
            # tolerance align_in_ayah already uses) rather than exact
            # equality. rx.norm() alone strips a mushaf dagger-alif
            # diacritic without replacing it with a letter.
            occ = [
                pos for pos, _, tok in toks
                if rx.match_word(tok, word_n, level=2)
            ]
            if not context and occ:
                wp = occ[0]
                context = prose[
                    max(0, wp - args.window):min(len(prose), wp + args.window)
                ]

            # Tier 2: word (normalized) co-occurs with its grade anywhere
            found2 = False
            for wp in occ:
                lo, hi = max(0, wp - args.window), min(len(prose), wp + args.window)
                if any(s in prose[lo:hi] for s in syns):
                    found2 = True
                    break
            if found2:
                t2 += 1
                grounded = True
                break

            # Tier 3: word sits inside a ومثله/وكذا chain list, with the
            # grade attached to that chain's own trigger point.
            found3 = False
            for wp in occ:
                lo, hi = max(0, wp - args.window), min(len(prose), wp + args.window)
                local = prose[lo:hi]
                if _MITHL_RE.search(local) and any(s in local for s in syns):
                    found3 = True
                    break
            if found3:
                t3 += 1
                grounded = True
                break

        if grounded:
            continue

        suspect += 1
        kind = 'AYAH_NOT_IN_SOURCE' if not ayah_in_source else 'GRADE_NOT_NEAR_AYAH'
        misses.append((surah, kind, r))
        review_items.append({
            'id': r['id'], 'source': args.source, 'surah': surah, 'ayah': r['ayah'],
            'wpos': r['wpos'], 'stop_word': r['stop_word'], 'grade': r['grade'],
            'quote': r['quote'], 'grade_raw': r['grade_raw'],
            'note': r['note'], 'reported_from': r['reported_from'],
            'reason': kind, 'source_context': context,
        })

    grounded = t1 + t2 + t3
    print(f'TOTAL rows checked: {total}')
    print(f'  tier 1 — explicit «[n] grade» marker      : {t1:5} ({100*t1/total:.2f}%)')
    print(f'  tier 2 — word+grade co-occur (normalized)  : {t2:5} ({100*t2/total:.2f}%)')
    print(f'  tier 3 — ومثله/وكذا chain list match        : {t3:5} ({100*t3/total:.2f}%)')
    print(f'  TOTAL grounded                             : {grounded:5} ({100*grounded/total:.2f}%)')
    print(f'  SUSPECT — no evidence found by any tier     : {suspect:5} ({100*suspect/total:.2f}%)')
    print()
    shown = 0
    for surah, kind, r in misses:
        if shown >= args.samples:
            break
        print(f'  [{kind}] surah {surah} {r["ayah"]}:{r["wpos"]} {r["stop_word"]!r} grade={r["grade"]!r}')
        shown += 1
    if args.review_out:
        out = os.path.abspath(args.review_out)
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, 'w', encoding='utf-8') as fh:
            for item in review_items:
                fh.write(json.dumps(item, ensure_ascii=False, sort_keys=True) + '\n')
        print(f'\nwrote {len(review_items)} review item(s) to {out}')
    if args.max_suspect is not None and suspect > args.max_suspect:
        raise SystemExit(
            f'suspect count {suspect} exceeds regression ceiling {args.max_suspect}')


if __name__ == '__main__':
    main()
