#!/usr/bin/env python3
"""المكتفى: rulings qualified by an ordinal — «{X} الأول كاف»، «الثاني تام»،
«في الموضعين»، «الأول والثاني تام».

The builder's grade regex expects the grade straight after the quote, so an
ordinal in between made الداني's ruling vanish («{مكر الله} الأول كاف»,
«{فإن مع العسر يسرا} الأول كاف … {إن مع العسر يسرا} الثاني تام») or, for a
«ومثله» item, collapsed «الثاني» onto the first occurrence.

المكتفى has no verse numbers, so each ruling is anchored on the nearest
preceding entry that has exactly one confident DB row; occurrences of the
quote are then counted from there (exact spelling only — a lone «كلا» must
not fold onto «ولا»), and a «الثاني» continues from its «الأول» sibling.
Rulings that do not resolve to enough occurrences are only reported.

Run:  python3 pipeline/audit_muktafa_ordinals.py [--apply]
"""
import argparse
import collections
import os
import re
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import audit_manar_mithl as mm  # noqa: E402  (hits_in_ayah, verse_words)
import build_classical_waqf as rx  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, 'data', 'classical_waqf.db')

_ORD_RE = re.compile(r'(?:\{([^{}]{1,80})\}|\(\(([^()]{1,60})\)\))\s*'
                     r'(الأول والثاني|في الموضعين|الأولى|الأول|الثانية|الثاني)([^{(]{0,40})')
_IDX = {'الأول': [0], 'الأولى': [0], 'الثاني': [1], 'الثانية': [1],
        'الأول والثاني': [0, 1], 'في الموضعين': [0, 1]}
_MITHL = re.compile(r'(ومثله|وكذلك|ومثلها|ونحوه)\s*[:،]?\s*$')
_SPAN = 5          # verses searched after the anchor

# Read by hand where the anchor rule cannot count (2026-09-26):
# «وحقت» الثانية (84:5) — no confident entry precedes it in the surah;
# «ويعفو عن كثير» الأول تام (42:30) — the book spells it without the alif
# (the second, 42:34, is تام only for «ويعلمُ» بالرفع, not Hafs).
MANUAL = [(84, 5, 2, 'وحقت', 'تام'), (42, 30, 9, 'ويعفو عن كثير', 'تام')]
# «ومثله {X} الثاني» items the builder put on the FIRST occurrence:
# (surah, ayah, wpos, quote) → (ayah, wpos).
MOVES = {
    (34, 53, 4, 'من قبل'): (54, 9),
    (4, 92, 32, 'وتحرير رقبة مؤمنة'): (92, 46),   # «وتحرير» — the one after «يصدقوا»
    (26, 108, 2, 'وأطيعون'): (110, 2),
    (37, 175, 2, 'فسوف يبصرون'): (179, 2),
    (56, 90, 5, 'أصحاب اليمين'): (91, 4),
}
# conf=0 rows (the cursor aligner could not pin them confidently), each read
# against its own surah's section (2026-09-26): all are الداني's rulings.
# None = the seat is right; a tuple moves it first.
REPAIR = {
    27: None, 260: None, 391: None, 463: None, 651: None, 1303: None, 2397: None,
    2542: None, 2640: None, 2740: None, 2798: None, 2992: None, 3079: None,
    3225: None, 3267: None, 3303: None, 3765: None, 4044: None, 4105: None,
    4320: None, 4403: None,
    524: (20, 13),        # «أأسلمتم» is «ءَأَسۡلَمۡتُمۡۚ», not «أَسۡلَمۡتُ وَجۡهِيَ»
    2693: (37, 18),       # «والأبصار» ends 24:37, not 24:36
}
REPORTED = {2542: 'الدينوري'}
# «{…} كاف عند أصحاب التمام … وهو عندي تام» (4:123): الداني's own verdict is تام
REGRADE = {877: 'تام'}     # «وقال الدينوري: ((ذلك هو الضلال البعيد يدعو)) تام»


def occurrences(surah, after, quote):
    """Exact-spelling end seats of quote after (ayah, wpos), reading order."""
    a0, w0 = after
    out = []
    for a in range(a0, min(a0 + _SPAN, rx.surah_ayah_count(surah)) + 1):
        out += [(a, h) for h in mm.hits_in_ayah(surah, a, quote, True) if a > a0 or h > w0]
    return out


def resolve(con):
    body = rx.normalize_muktafa_headings(rx.load_book(rx.SOURCES['muktafa']))
    found, unresolved = [], []
    last = 0
    for sec in re.split(r'\n### \| ', body):
        title, _, text = sec.partition('\n')
        if 'سورة' not in title and 'أم القرآن' not in title:
            continue
        surah = rx.surah_number(title, last)
        if surah is None:
            continue
        last = surah
        entries = rx.parse_muktafa_entries(text)
        sibling = {}
        for m in _ORD_RE.finditer(text):
            quote = rx.clean_note(m.group(1) or m.group(2), limit=200)
            ordinal = m.group(3)
            tail = mm.strip(m.group(4)).lstrip(' ،.[')
            gm = rx.GRADE_RE.match(tail)
            grade = dict(rx.GRADES)[gm.group(1)] if gm else None
            prev = [e for e in entries if e['pos'] < m.start()]
            if grade is None and prev and _MITHL.search(mm.strip(text[max(0, m.start() - 14):m.start()])):
                grade = prev[-1]['grade']
            if grade is None:
                continue
            key = rx.norm(' '.join(rx.quote_words(quote)[-2:]))
            if key in sibling and _IDX[ordinal] == [1]:
                seats = occurrences(surah, sibling[key], quote)[:1]
            else:
                anchor = None
                for e in reversed(prev):
                    rows = con.execute("SELECT ayah, wpos FROM classical WHERE source='muktafa' "
                                       "AND conf=1 AND grade_raw<>'رؤوس الآي' AND surah=? AND quote=?", (surah, e['quote'])).fetchall()
                    if len(rows) == 1:
                        anchor = rows[0]
                        break
                cands = occurrences(surah, anchor, quote) if anchor else []
                idx = _IDX[ordinal]
                seats = [cands[i] for i in idx] if len(cands) > max(idx) else []
            rec = {'surah': surah, 'quote': quote, 'ordinal': ordinal, 'grade': grade,
                   'note': rx.clean_note(text[m.end(3):m.end(3) + 300])}
            if not seats:
                unresolved.append(rec)
                continue
            sibling[key] = seats[-1]
            for a, w in seats:
                found.append(dict(rec, ayah=a, wpos=w))
    return found, unresolved


# «وقال نافع {بل أحياء} تام» — no colon, so the builder's reported_scholar()
# (which needs «وقال فلان:») missed it and the row reads as الداني's own.
_RELAYED = re.compile(r'(?:^|[\s.،])و?قال(?:ت)?\s+([^{}:.،()]{2,45}?)\s*'
                      r'(?:\{([^{}]{1,80})\}|\(\(([^()]{1,60})\)\))\s*(تام|كاف|حسن|أتم|أكفى|قبيح)')
RELAYED_SEAT = {(4, 'غفورا رحيما'): 23}     # the passage is on 4:23, not 4:152


def relayed_rows(con):
    """[(row id, scholar)] for المكتفى rows that are someone else's ruling."""
    body = rx.normalize_muktafa_headings(rx.load_book(rx.SOURCES['muktafa']))
    out, last = [], 0
    for sec in re.split(r'\n### \| ', body):
        title, _, text = sec.partition('\n')
        if 'سورة' not in title and 'أم القرآن' not in title:
            continue
        surah = rx.surah_number(title, last)
        if not surah:
            continue
        last = surah
        for m in _RELAYED.finditer(mm.strip(text)):
            name = re.sub(r'\s+', ' ', m.group(1)).strip()
            quote = (m.group(2) or m.group(3)).strip()
            rows = con.execute("SELECT id, ayah FROM classical WHERE source='muktafa' AND surah=? "
                               "AND quote=? AND grade_raw<>'رؤوس الآي'", (surah, quote)).fetchall()
            want = RELAYED_SEAT.get((surah, quote))
            rows = [r for r in rows if want is None or r[1] == want]
            if len(rows) == 1:
                out.append((rows[0][0], name))
    return out


def apply(con, found):
    cur = con.cursor()
    stats = collections.Counter()
    for (s, a0, w0, q), (a, w) in MOVES.items():
        stats['moved'] += cur.execute(
            "UPDATE classical SET ayah=?, wpos=?, stop_word=? WHERE source='muktafa' AND surah=? "
            "AND ayah=? AND wpos=? AND quote=? AND grade_raw<>'رؤوس الآي'",
            (a, w, mm.verse_words(s, a)[w], s, a0, w0, q)).rowcount
    for rid, seat in REPAIR.items():
        row = cur.execute("SELECT surah, ayah, wpos FROM classical WHERE id=? AND conf=0", (rid,)).fetchone()
        if not row:
            continue
        s, a, w = row
        if seat:
            a, w = seat
        cur.execute("UPDATE classical SET ayah=?, wpos=?, stop_word=?, conf=1, reported_from=? WHERE id=?",
                    (a, w, mm.verse_words(s, a)[w], REPORTED.get(rid), rid))
        stats['repaired'] += 1
    for rid, name in relayed_rows(con):
        stats['relayed_labelled'] += cur.execute(
            "UPDATE classical SET reported_from=? WHERE id=? AND COALESCE(reported_from,'')<>?",
            (name, rid, name)).rowcount
    for rid, g in REGRADE.items():
        stats['regraded_own'] += cur.execute(
            "UPDATE classical SET grade=?, grade_raw=? WHERE id=? AND grade<>?", (g, g, rid, g)).rowcount
    rows = [(r['surah'], r['ayah'], r['wpos'], r['quote'], r['grade'], r['note']) for r in found]
    rows += [(s, a, w, q, g, f'{q} {g}') for s, a, w, q, g in MANUAL]
    for s, a, w, q, g, note in rows:
        have = cur.execute("SELECT id, grade FROM classical WHERE source='muktafa' AND surah=? "
                           "AND ayah=? AND wpos=?", (s, a, w)).fetchall()
        if any(h[1] == g for h in have):
            continue
        if len(have) == 1 and q == cur.execute("SELECT quote FROM classical WHERE id=?",
                                               (have[0][0],)).fetchone()[0]:
            # the «ومثله» item inherited the head's grade; the book grades it here
            cur.execute("UPDATE classical SET grade=?, grade_raw=? WHERE id=?", (g, g, have[0][0]))
            stats['regraded'] += 1
            continue
        seq = (cur.execute("SELECT seq FROM classical WHERE source='muktafa' AND surah=? AND "
                           "(ayah<? OR (ayah=? AND wpos<=?)) ORDER BY ayah DESC, wpos DESC LIMIT 1",
                           (s, a, a, w)).fetchone() or (0,))[0]
        cur.execute("INSERT INTO classical (source, surah, ayah, wpos, stop_word, quote, grade, "
                    "grade_raw, note, seq, conf, reported_from) VALUES ('muktafa',?,?,?,?,?,?,?,?,?,1,NULL)",
                    (s, a, w, mm.verse_words(s, a)[w], q, g, g, note, seq))
        stats['inserted'] += 1
    con.commit()
    return stats


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--db', default=DB)
    ap.add_argument('--apply', action='store_true')
    args = ap.parse_args(argv)
    con = sqlite3.connect(args.db)
    found, unresolved = resolve(con)
    for r in found:
        w = mm.verse_words(r['surah'], r['ayah'])
        print(f"{r['surah']}:{r['ayah']}:{r['wpos']} «{r['quote']}» {r['ordinal']} {r['grade']} "
              f"[{' '.join(w[max(0, r['wpos'] - 2):r['wpos'] + 1])}]")
    print(f'{len(found)} resolved seats; unresolved: '
          + '، '.join(f"{r['surah']} «{r['quote']}» {r['ordinal']}" for r in unresolved))
    if args.apply:
        print('applied:', dict(apply(con, found)))
    con.close()


if __name__ == '__main__':
    main()
