#!/usr/bin/env python3
"""المكتفى: blanket verse-end rulings — «ورؤوس الآي بعد كافية»، «وكذلك رؤوس
الآي إلى قوله {X}»، «والفواصل إلى آخر السورة تامة»، «ومثله رأس الآية».

الداني often grades a run of verse-ends at once instead of one by one. The
builder only reads {quote} + grade, so every verse-end covered this way had
no المكتفى ruling at all. This expands each statement to the verse-ends in
its scope that the book does NOT rule on specifically (an explicit {…}
ruling always wins):

  scope      «رأس الآية» (singular)        → the anchor verse's end
             «بعد/بعدها»                  → after the anchor, up to «إلى قوله
                                             {X}» if given, else the next
                                             blanket statement or surah end
             «إلى قوله {X}» / «إلى آخر
              السورة» / «إلى العشر»        → after the anchor up to that verse
             «قبل ذلك»، «بين ذلك»          → after the previous blanket
                                             statement (or surah start) up to
                                             the anchor
             «قبل وبعد» / no direction    → both of the above
  grade      stated in the statement (كافية، تامة، أتم، أكفى …), else the
             grade of the entry it follows («وكذلك/ومثله»)
  anchor     the verse of the nearest preceding entry with exactly one
             confident DB row

Rows are written with the statement itself as the note and grade_raw
«رؤوس الآي» so they read (and can be filtered) as general rulings.

Run:  python3 pipeline/audit_muktafa_blanket.py [--apply]
"""
import argparse
import collections
import os
import re
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import audit_manar_mithl as mm  # noqa: E402
import build_classical_waqf as rx  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, 'data', 'classical_waqf.db')
RAW = 'رؤوس الآي'

_SUBJ = re.compile(r'(رؤوس الآي|رءوس الآي|الفواصل|فواصلها|رأس الآية)')
_GRADE_WORDS = [('أكفى', 'كاف'), ('أتم', 'تام'), ('أحسن', 'حسن'),
                ('كافية', 'كاف'), ('تامة', 'تام'), ('حسنة', 'حسن'), ('حسان', 'حسن'),
                ('جائزة', 'جائز'), ('كاف', 'كاف'), ('تام', 'تام'), ('حسن', 'حسن')]
_GRADE_RE = re.compile(r'(?<![ء-ي])(' + '|'.join(g for g, _ in _GRADE_WORDS) + r')(?![ء-ي])')
_TRIGGER = re.compile(r'(وكذلك|ومثله|وكذا|ومثلها)\s*(?:الوقف\s+على\s+)?(?:رؤوس\s+|عامة\s+)?$')
_GRADE_BEFORE = re.compile(r'(والتمام|التمام|فالتمام)\s*$')
# «ورؤوس الآي من قوله {ولقد آتينا إبراهيم رشده} إلى آخر القصة كافية» —
# the story's end is not quoted: الأنبياء 51–73 (74 begins «ولوطا»).
MANUAL_RANGES = [(21, 51, 73, 'كاف', 'ورؤوس الآي من قوله {ولقد آتينا إبراهيم رشده} إلى آخر القصة كافية')]
_UPTO = re.compile(r'إلى\s+(?:قوله\s*:?\s*)?(?:\{([^{}]{1,80})\}|\(\(([^()]{1,60})\)\))')
# «وهو رأس آية»، «ليس برأس آية»، verse-count remarks — not rulings
_NOT = re.compile(r'(وهو|ليس ب|وليس ب|وهما|عند|في عدد|في غير)\s*$')


def strip_map(text):
    """Diacritic-free copy of text + index map back into the original."""
    out, idx = [], []
    for i, ch in enumerate(text):
        if not mm._HARAKAT.match(ch):
            out.append(ch)
            idx.append(i)
    idx.append(len(text))
    return ''.join(out), idx


def statement_text(plain, start, end):
    """The clause as the book words it: from just after the previous
    sentence/quote boundary (so «وكذلك …»/«ورؤوس …» keep their lead-in)."""
    lead = plain[max(0, start - 30):start]
    cut = max(lead.rfind(c) for c in '.}])،')
    begin = start - len(lead) + cut + 1 if cut >= 0 else start - len(lead)
    text = re.sub(r'\s+', ' ', plain[begin:end])
    text = re.split(r'\s(?:و?قال)\s', text)[0]        # not a relayed opinion after it
    return text.strip(' .،[]')


def verse_end_seat(surah, ayah):
    words = mm.verse_words(surah, ayah)
    return (ayah, len(words) - 1) if words else None


def find_verse(surah, after_ayah, quote):
    for a in range(after_ayah, rx.surah_ayah_count(surah) + 1):
        if mm.hits_in_ayah(surah, a, quote, True) or mm.hits_in_ayah(surah, a, quote, False):
            return a
    return None


def statements(con):
    body = rx.normalize_muktafa_headings(rx.load_book(rx.SOURCES['muktafa']))
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
        plain, idx = strip_map(text)
        for m in _SUBJ.finditer(plain):
            head = plain[max(0, m.start() - 30):m.start()]
            if _NOT.search(head):
                continue
            # the statement: to the sentence end, but through one «إلى قوله {X}»
            rest = plain[m.end():m.end() + 120]
            up = _UPTO.match(rest.lstrip(' :'), 0) or _UPTO.search(rest[:40])
            stop = re.search(r'[.\n]|\{|\(\(', rest)
            span = rest[:stop.start()] if stop else rest[:60]
            if up and (not stop or up.start() <= stop.start() + 12):
                span = rest[:up.end() + 40].split('.')[0]
                tail_after = rest[up.end():up.end() + 30].split('.')[0]
            else:
                tail_after = ''
            subject = m.group(1)
            trig = _TRIGGER.search(head)
            gm = _GRADE_RE.search(re.sub(r'\{[^{}]*\}|\(\([^()]*\)\)', ' ', span)) or _GRADE_RE.search(tail_after)
            pos = idx[m.start()]
            prev = [e for e in entries if e['pos'] < pos]
            if 'من قوله' in span:
                continue          # «من قوله {X} إلى آخر القصة» — MANUAL_RANGES
            if _GRADE_BEFORE.search(head):
                grade = 'تام'
            elif gm:
                grade = dict(_GRADE_WORDS)[gm.group(1)]
            elif trig and prev:
                grade = prev[-1]['grade']
            else:
                continue
            def unique_ayah(e):
                rows = con.execute("SELECT ayah FROM classical WHERE source='muktafa' AND conf=1 "
                                   "AND grade_raw<>'رؤوس الآي' AND surah=? AND quote=?", (surah, e['quote'])).fetchall()
                return rows[0][0] if len(rows) == 1 else None

            anchor = next((a for a in (unique_ayah(e) for e in reversed(prev)) if a), 0)
            # head of the «ومثله» chain the statement closes
            j = len(prev) - 1
            while j > 0 and re.search(r'(ومثله|وكذلك|ومثلها|ونحوه)\s*[:،]?\s*$',
                                      mm.strip(text[max(0, prev[j]['pos'] - 14):prev[j]['pos']])):
                j -= 1
            head_a = next((a for a in (unique_ayah(e) for e in reversed(prev[:j + 1])) if a), anchor)
            n = rx.surah_ayah_count(surah)
            if subject == 'رأس الآية':
                verses = [anchor] if anchor else []
            elif re.search(r'عامة\s*$', head):
                verses = list(range(1, n + 1))      # «وكذلك عامة فواصلها»
            else:
                bare = re.sub(r'\{[^{}]*\}?|\(\([^()]*\)\)', ' ', span)
                has = lambda w: re.search(r'(?<![ء-ي])[وف]?' + w + r'(?![ء-ي])', bare) is not None
                before = has('قبل') or has('بين')
                after = (has('بعد') or has('بعدها') or bool(up) or has('آخر') or has('العشر')
                         or not before)
                end = None       # open «بعد»: up to the next statement's anchor
                if up:
                    x = find_verse(surah, max(anchor, 1), up.group(1) or up.group(2))
                    end = x if x else anchor
                elif has('العشر'):
                    end = min(n, (anchor // 10 + 1) * 10)
                elif has('آخر'):
                    end = n
                verses = list(range(min(head_a, anchor), anchor + 1)) if before else []
                if after:
                    verses.append(('after', anchor, end))
            yield {'surah': surah, 'anchor': anchor, 'grade': grade, 'pos': pos,
                   'statement': statement_text(plain, m.start(), m.end() + len(span)),
                   'verses': verses}


def expand(con):
    """[(surah, ayah, wpos, grade, statement)] for unruled verse-ends."""
    stmts = list(statements(con))
    by_surah = collections.defaultdict(list)
    for st in stmts:
        by_surah[st['surah']].append(st)
    ruled = {(s, a, w) for s, a, w in con.execute(
        "SELECT surah, ayah, wpos FROM classical WHERE source='muktafa' AND wpos IS NOT NULL")}
    out, seen = [], set()
    for surah, sts in by_surah.items():
        n = rx.surah_ayah_count(surah)
        for i, st in enumerate(sts):
            verses = []
            for v in st['verses']:
                if isinstance(v, tuple):
                    _, a0, end = v
                    if end is None:
                        later = [t['anchor'] for t in sts[i + 1:] if t['anchor'] > a0]
                        end = later[0] if later else n
                    verses += list(range(a0 + 1, end + 1))
                else:
                    verses.append(v)
            for a in verses:
                seat = verse_end_seat(surah, a) if 1 <= a <= n else None
                if not seat or (surah, *seat) in ruled or (surah, *seat) in seen:
                    continue
                seen.add((surah, *seat))
                out.append((surah, seat[0], seat[1], st['grade'], st['statement']))
    for surah, a0, a1, g, statement in MANUAL_RANGES:
        for a in range(a0, a1 + 1):
            seat = verse_end_seat(surah, a)
            if seat and (surah, *seat) not in ruled and (surah, *seat) not in seen:
                seen.add((surah, *seat))
                out.append((surah, seat[0], seat[1], g, statement))
    return stmts, out


def note_for(statement):
    return rx.clean_note(f'حكم عام: «{statement}»', limit=300)


def apply(con, rows):
    cur = con.cursor()
    n = 0
    for s, a, w, g, statement in rows:
        seq = (cur.execute("SELECT seq FROM classical WHERE source='muktafa' AND surah=? AND "
                           "(ayah<? OR (ayah=? AND wpos<=?)) ORDER BY ayah DESC, wpos DESC LIMIT 1",
                           (s, a, a, w)).fetchone() or (0,))[0]
        word = mm.verse_words(s, a)[w]
        cur.execute("INSERT INTO classical (source, surah, ayah, wpos, stop_word, quote, grade, "
                    "grade_raw, note, seq, conf, reported_from) VALUES ('muktafa',?,?,?,?,?,?,?,?,?,1,NULL)",
                    (s, a, w, word, word, g, RAW, note_for(statement), seq))
        n += 1
    con.commit()
    return n


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--db', default=DB)
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--samples', type=int, default=0)
    args = ap.parse_args(argv)
    con = sqlite3.connect(args.db)
    stmts, rows = expand(con)
    print(f'{len(stmts)} blanket statements → {len(rows)} unruled verse-ends',
          dict(collections.Counter(r[3] for r in rows)))
    for st in stmts[:args.samples]:
        print(f"  {st['surah']}:{st['anchor']} {st['grade']} «{st['statement']}» → {st['verses']}")
    if args.apply:
        print('inserted', apply(con, rows))
    con.close()


if __name__ == '__main__':
    main()
