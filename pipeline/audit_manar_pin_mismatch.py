#!/usr/bin/env python3
"""Flag منار rows whose note/quote names a different ayah-word than stop_word.

Last-match class: repeated mushaf words (مثلًا, كثيرًا, الذين, ما, …) plus a
note that quotes a DIFFERENT stop — e.g. note «الوقف على «ما»» pinned to مثلًا.

Prints: surah:ayah id old_wpos named_word actual_word grade HIGH|AMBIGUOUS

Never invents a word, ayah, wpos, or حكم. --apply only moves HIGH rows to the
named word's unique (or الأول/الثاني/…) recited wpos and the Uthmani stop_word
already at that seat.

HIGH = the pin's exact-norm token occurs more than once in the ayah, and the
note's «الوقف على / لا يوقف على …» names a different word that occurs once
(or with an ordinal). Prefix variants of the same stem (الله / والله) are
not mismatches. Other named-vs-pin disagreements stay AMBIGUOUS.

Run:
    python3 pipeline/audit_manar_pin_mismatch.py
    python3 pipeline/audit_manar_pin_mismatch.py --apply
"""
from __future__ import annotations

import argparse
import os
import re
import sqlite3
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'pipeline'))
os.environ.setdefault('RESEARCH_PRECOMPUTE', '1')

import app  # noqa: E402
import build_classical_waqf as rx  # noqa: E402

_STOP_NAME_RE = re.compile(
    r'(?:لا\s+(?:يحسن|يصلح|ينبغي)\s+)?'
    r'(?:كان\s+)?'
    r'(?:الوقف\s+على|لا\s+يوقف\s+على|يوقف\s+على)'
    r'\s*[«"\{]([^«»"\}]{1,80})[»"\}]'
)
_ORDINAL_RE = re.compile(r'(الأول[ى]?|الثاني[ة]?|الثالث[ة]?|الرابع[ة]?)')
_ORDINAL = {
    'الأول': 0, 'الأولى': 0,
    'الثاني': 1, 'الثانية': 1,
    'الثالث': 2, 'الثالثة': 2,
    'الرابع': 3, 'الرابعة': 3,
}
_WAQF_MARKS = (
    '\u06D6\u06D7\u06D8\u06D9\u06DA\u06DB\u06DC'
    '\u06DF\u06E0\u06E1\u06E2\u06E3\u06E4\u06EA\u06EB\u06EC\u06ED'
)


def last_arabic_word(phrase):
    words = rx.quote_words(phrase or '')
    return words[-1] if words else ''


def exact_hits(wnorm, named_norm):
    return [i for i, n in enumerate(wnorm) if n == named_norm]


def strip_waqf(tok):
    return (tok or '').rstrip(_WAQF_MARKS + ' ')


def ordinal_index(text):
    m = _ORDINAL_RE.search(text or '')
    if not m:
        return None
    return _ORDINAL.get(m.group(1))


def named_stops(note, quote):
    out = []
    blob = ' '.join(x for x in (note, quote) if x)
    for m in _STOP_NAME_RE.finditer(blob):
        raw = m.group(1).strip()
        n = last_arabic_word(raw)
        if n:
            out.append((n, raw))
    return out


def unique_keep_order(items):
    seen = set()
    out = []
    for n, raw in items:
        if n in seen:
            continue
        seen.add(n)
        out.append((n, raw))
    return out


def ayah_words(surah, ayah):
    _, words, _ = app._verse_word_texts(f'{surah}:{ayah}')
    return words, [rx.norm(w) for w in words]


def same_stem(a, b):
    return a == b or rx.match_word(a, b, 1)


def classify(row, words, wnorm):
    stop_n = rx.norm(row['stop_word'] or '')
    quote_n = last_arabic_word(row['quote'] or '')
    note = row['note'] or ''
    named = unique_keep_order(named_stops(note, row['quote'] or ''))
    pin_hits = exact_hits(wnorm, stop_n)
    pin_repeated = len(pin_hits) > 1

    extra = []
    if quote_n and not same_stem(quote_n, stop_n):
        qhits = exact_hits(wnorm, quote_n)
        if qhits and row['wpos'] not in qhits:
            extra.append((quote_n, row['quote'] or ''))

    if not named and not extra:
        return None

    if any(same_stem(n, stop_n) or row['wpos'] in exact_hits(wnorm, n) for n, _ in named):
        return None

    candidates = named or extra
    if len({c[0] for c in candidates}) != 1:
        n0, raw0 = candidates[0]
        return {
            'kind': 'AMBIGUOUS',
            'named': n0,
            'named_raw': raw0,
            'named_wpos': None,
            'pin_repeated': pin_repeated,
        }

    named_n, named_raw = candidates[0]
    if same_stem(named_n, stop_n):
        return None
    hits = exact_hits(wnorm, named_n)
    if not hits:
        hits = [i for i, n in enumerate(wnorm) if same_stem(n, named_n)]
    if not hits or row['wpos'] in hits:
        return None

    ord_i = ordinal_index(note)
    if len(hits) == 1:
        target = hits[0]
        kind = 'HIGH' if pin_repeated else 'AMBIGUOUS'
    elif ord_i is not None and 0 <= ord_i < len(hits):
        target = hits[ord_i]
        kind = 'HIGH' if pin_repeated else 'AMBIGUOUS'
    else:
        kind, target = 'AMBIGUOUS', None
    return {
        'kind': kind,
        'named': named_n,
        'named_raw': named_raw,
        'named_wpos': target,
        'pin_repeated': pin_repeated,
    }


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--db', default=os.path.join(ROOT, 'data', 'classical_waqf.db'))
    ap.add_argument('--source', default='manar')
    ap.add_argument('--apply', action='store_true',
                    help='rewrite HIGH pins to the named word wpos + Uthmani stop_word')
    args = ap.parse_args(argv)

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        'SELECT id, surah, ayah, wpos, stop_word, quote, grade, note '
        'FROM classical WHERE source=? ORDER BY surah, ayah, id',
        (args.source,),
    ).fetchall()

    cache = {}
    high, amb, applied = [], [], []
    for r in rows:
        key = (r['surah'], r['ayah'])
        if key not in cache:
            cache[key] = ayah_words(*key)
        words, wnorm = cache[key]
        if not words or r['wpos'] is None:
            continue
        info = classify(r, words, wnorm)
        if not info:
            continue
        actual = words[r['wpos']] if 0 <= r['wpos'] < len(words) else r['stop_word']
        rec = {
            **info,
            'id': r['id'],
            'surah': r['surah'],
            'ayah': r['ayah'],
            'old_wpos': r['wpos'],
            'actual': actual,
            'grade': r['grade'],
        }
        (high if info['kind'] == 'HIGH' else amb).append(rec)
        print(
            f"{r['surah']}:{r['ayah']} id={r['id']} old_wpos={r['wpos']} "
            f"named={info['named_raw']} actual={actual} grade={r['grade']} "
            f"{info['kind']}"
        )

    print(f'-- HIGH {len(high)}  AMBIGUOUS {len(amb)}  scanned {len(rows)}')

    if args.apply:
        for rec in high:
            wpos = rec['named_wpos']
            if wpos is None:
                continue
            words, _ = cache[(rec['surah'], rec['ayah'])]
            stop_word = words[wpos]
            conn.execute(
                'UPDATE classical SET wpos=?, stop_word=?, quote=? WHERE id=?',
                (wpos, stop_word, strip_waqf(stop_word), rec['id']),
            )
            applied.append(rec['id'])
        conn.commit()
        print(f'-- applied {len(applied)} ids: {applied}')
    conn.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
