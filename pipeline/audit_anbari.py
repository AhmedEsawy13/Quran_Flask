#!/usr/bin/env python3
"""Audit ابن الأنباري's إيضاح الوقف والابتداء rows against the book.

The book grades stop by stop, usually with the verse number:
    (X) [n] حسن       والوقف على (X) [n] قبيح لأن …       ومثله: (Y) [n]
but it is also discursive: long grammar debates, citations of other surahs
(«{…} [الصافات: 130]»), and relayed opinions («وقال السجستاني: (X) تام، وهذا
غلط») that the regex builder stored as ابن الأنباري's own.

For every stored row this re-derives, from the sentence in the book:
  * the verse — the quote's own [n], else the last [n] before it in the
    surah (verse-count differences allow ±1);
  * the word — exact spelling first, then the pause-marked occurrence
    (audit_manar_mithl.head_seat), never "last occurrence wins";
  * the grade — the one after the quote, or the chain head's for «ومثله»;
  * the voice — «وقال/قال فلان:» opening the sentence makes it relayed.

Statuses: ok, moved (other word/verse), relayed (attribution), unplaced.
`--apply` writes seats/attributions and serves rows that verify.

Run:  python3 pipeline/audit_anbari.py [--apply]
"""
import argparse
import collections
import json
import os
import re
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import audit_manar_mithl as mm  # noqa: E402
import build_classical_waqf as rx  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, 'data', 'classical_waqf.db')
OUT = os.path.join(ROOT, 'pipeline', 'review', 'anbari_audit.jsonl')

_G = (r'(?:وقف\s+)?(لا يحسن الوقف|ليس بوقف|لا يوقف|التمام|التام|أتم|تمام|تام|كافٍ|كاف|'
      r'أحسن|حسن|صالح|قبيح)(?=[\s،.؛\]]|$)')
_GRADE_AFTER = re.compile(r'^[\s،:؛]*\[?' + _G)       # «[تام]» too
_MAP = {'التمام': 'تام', 'التام': 'تام', 'أتم': 'تام', 'تمام': 'تام', 'تام': 'تام',
        'كافٍ': 'كاف', 'كاف': 'كاف', 'أحسن': 'حسن', 'حسن': 'حسن', 'صالح': 'صالح',
        'قبيح': 'قبيح', 'لا يحسن الوقف': 'قبيح', 'ليس بوقف': 'لا', 'لا يوقف': 'لا'}
_MARK = re.compile(r'\[(\d{1,3})\]')
_MITHL = re.compile(r'(ومثله|ومثلها|وكذلك|وكذا)(?:\s+(?:الوقف\s+)?على)?(?:\s+قوله)?\s*:?\s*$')
# a chain head that is NOT a stop grade: «(X) [4] غير تام. وكذلك: (Y)»
_NEG_AFTER = re.compile(r'^[\s،:؛]*(?:وقف\s+)?(غير تام|ليس بتام|لا يتم|لا يحسن|لم يتم)')
# a sentence opened by someone else's voice
_RELAY = re.compile(r'(?:^|[.\n])\s*(?:و)?قال(?:ت)?\s+([^:.،(){}\[\]]{2,40}?)\s*:')
_ABOUT = re.compile(r'(?:وأنكر|وخالف|وزعم|ورد)')


# read by hand: the seat is right, the book spells the word differently
# (1:4 «ملك» for «مَٰلِكِ»، 2:110 «الزكاة» for «ٱلزَّكَوٰةَۚ»)
KEEP_SEAT = {(1, 'ملك', 'قبيح'), (2, 'الزكاة', 'حسن')}
# chains the walker cannot follow but the book grades (read by hand): 2:231 ×3
# run back to «(أو تسريح بإحسان) [229] حسن»; 3:93 «مثله»; 14:14, 21:24, 24:58
# carry the list's trailing grade; 53:55 follows «… تام. (بمن اتقى)»; 95:6.
HAND_CONFIRMED = {(2, 'ولا تمسكوهن ضرارا لتعتدوا', 'حسن'), (2, 'فقد ظلم نفسه', 'حسن'),
                  (2, 'يعظكم به', 'حسن'), (3, 'من قبل أن تنزل التوراة', 'حسن'),
                  (14, 'لنسكننكم الأرض من بعدهم', 'تام'), (21, 'ذكر من قبلي', 'حسن'),
                  (24, 'بعضكم على بعض', 'حسن'), (53, 'فبأي آلاء ربك تتمارى', 'تام'),
                  (95, 'أجر غير ممنون', 'حسن')}
# «والوقف التام في سورة الإخلاص والفلق والناس آخر السورة» (the book's last line)
BOOK_END = [(112, 'تام'), (113, 'تام'), (114, 'تام')]


def sections():
    out = {}
    for n, text in rx.anbari_sections(rx.load_book(rx.SOURCES['anbari'])):
        out[n] = out.get(n, '') + '\n' + re.sub(r'[ \t]+', ' ', mm.strip(text))
    return out


def squash(s):
    return re.sub(r'\s+', ' ', mm.strip(s or '')).strip()


def occurrences(text, quote):
    """Start offsets of «(quote)» in a section, whitespace-insensitive."""
    pat = r'\(\s*' + r'\s+'.join(re.escape(w) for w in squash(quote).split()) + r'\s*\)'
    return [(m.start(), m.end()) for m in re.finditer(pat, text)]


def verse_at(text, start, end, acount):
    own = _MARK.match(text[end:end + 12].lstrip())
    if own and 1 <= int(own.group(1)) <= acount:
        return int(own.group(1)), True
    prev = [int(m.group(1)) for m in _MARK.finditer(text, 0, start) if 1 <= int(m.group(1)) <= acount]
    return (prev[-1] if prev else 1), False


def grade_at(text, start, end):
    """(grade, via): the grade after the quote, or — for «ومثله/وكذلك (X)»
    and list items «، و (Y)» that follow one — the grade of the chain head."""
    tail = re.sub(r'^\s*\[\d{1,3}\]', '', text[end:end + 90])
    m = _GRADE_AFTER.match(tail)
    if m:
        return _MAP[m.group(1)], 'own'
    pos, linked = start, False
    for _ in range(20):
        gap_ok = _MITHL.search(text[max(0, pos - 16):pos])
        if not gap_ok and linked:
            gap_ok = re.search(r'[،,]\s*(?:و\s*)?$|\]\s*[،,]?\s*(?:و\s*)?$', text[max(0, pos - 8):pos])
        if not gap_ok:
            break
        linked = True
        prev = None
        for mm_ in re.finditer(r'\(([^()]{1,120})\)', text[max(0, pos - 600):pos]):
            prev = mm_
        if not prev:
            break
        ps = max(0, pos - 600) + prev.start()
        pe = max(0, pos - 600) + prev.end()
        head_tail = re.sub(r'^\s*\[\d{1,3}\]', '', text[pe:pe + 90])
        g = _GRADE_AFTER.match(head_tail)
        if g:
            return _MAP[g.group(1)], 'chain'
        if _NEG_AFTER.match(head_tail):
            return 'NEG', 'chain'
        pos = ps
    return None, None


def relayed_by(text, start):
    """Scholar whose «قال فلان: [الوقف على] (X)» is directly about this stop
    («وقال السجستاني: الوقف على قوله (سلام) تام. وهذا خطأ»). A grammar remark
    earlier in the sentence does not make the author's grade someone else's."""
    lead = text[max(0, start - 90):start]
    m = None
    for m_ in re.finditer(r'(?:و)?قال(?:ت)?\s+([^:.،(){}\[\]]{2,40}?)\s*:\s*', lead):
        m = m_
    if not m:
        return None
    between = lead[m.end():].strip()
    if re.fullmatch(r'(?:الوقف\s+)?(?:على\s+)?(?:قوله\s*:?)?', between):
        name = m.group(1).strip()
        if name not in ('قائل', 'له', 'لي', 'الله', 'تعالى', 'قوم', 'بعضهم'):
            return name
    return None


def next_marker(text, end, ayah, acount):
    for m in _MARK.finditer(text, end):
        v = int(m.group(1))
        if ayah < v <= acount:
            return v
    return acount


def seat(surah, ayah, quote, acount, upto, own, current=None):
    """The verse and word of a stop: its own [n] (±1), else forward from the
    last [n] to the next one; a multi-word quote found in exactly one verse of
    the surah is taken there (the book's numbers sometimes lag, 13:16 → 13:11).
    A single word is only trusted near its [n]. If nothing matches but the
    stored seat already spells the quote inside that window, keep it."""
    if '.' in quote:
        # «(غدا. إلا أن يشاء الله) [23، 24]»: the period is a verse break inside
        # the quote; the ruling is on the phrase's end («(قليلا. ملعونين)»)
        quote = quote.split('.')[-1].strip()
        ayah, own = ayah + 1, False
    words = rx.quote_words(quote, mm.hnorm)
    single = len(words) < 2
    order = [ayah, ayah + 1, ayah - 1]
    if not own and not single:
        order += list(range(ayah + 2, min(upto, ayah + 12) + 1))
    for a in order:
        if 1 <= a <= acount:
            w = mm.head_seat(surah, a, quote)
            if w is not None:
                return a, w
    if not single:
        found = [(a, w) for a in range(1, acount + 1)
                 for w in [mm.head_seat(surah, a, quote)] if w is not None]
        if len(found) == 1:
            return found[0]
    if current and current[0] and current[1] is not None and current[0] in order \
            and rx.pin_matches_wpos(surah, current[0], current[1], quote):
        return current
    return None, None


def audit(con):
    secs = sections()
    recs = []
    for r in con.execute("SELECT id, surah, ayah, wpos, quote, grade, conf, reported_from "
                         "FROM classical WHERE source='anbari' AND grade_raw NOT IN (?,?,?,?,?)",
                         tuple(BEFORE_RAW.values()) + ('آخر السورة',)).fetchall():
        rid, s, a, w, q, g, conf, rep = r
        text = secs.get(s, '')
        acount = rx.surah_ayah_count(s)
        best, best_neg, other = None, False, None
        for st, en in occurrences(text, q):
            gg, via = grade_at(text, st, en)
            if gg == 'NEG':
                best_neg = True
            elif gg and gg != g and other is None:
                other = (gg, st, en, via)
            if gg != g:
                continue
            va, own = verse_at(text, st, en, acount)
            cand = (abs((a or va) - va), st, en, va, own, via)
            if best is None or cand < best:
                best = cand
        rec = {'id': rid, 'surah': s, 'ayah': a, 'wpos': w, 'quote': q, 'grade': g,
               'conf': conf, 'reported_from': rep}
        if best is None and other:
            gg, st, en, via = other
            va, own = verse_at(text, st, en, acount)
            best = (0, st, en, va, own, via)
            rec['new_grade'] = gg
        if best is None:
            rec['status'] = 'negated_head' if best_neg else 'no_source_ruling'
            recs.append(rec)
            continue
        _, st, en, va, own, via = best
        na, nw = seat(s, va, q, acount, next_marker(text, en, va, acount), own, (a, w))
        who = relayed_by(text, st)
        rec.update(src_ayah=va, own_marker=own, via=via, new_ayah=na, new_wpos=nw,
                   relayed=who, context=text[max(0, st - 120):en + 100])
        if (s, squash(q), g) in KEEP_SEAT:
            na, nw = a, w
            rec.update(new_ayah=a, new_wpos=w)
        if na is None:
            rec['status'] = 'unplaced'
        elif rec.get('new_grade'):
            rec['status'] = 'regrade'
        elif (na, nw) != (a, w):
            rec['status'] = 'moved'
        elif (who or None) != (rep or None) and who:
            rec['status'] = 'relayed'
        else:
            rec['status'] = 'ok'
        recs.append(rec)
    return recs


# grade BEFORE the quote — the builder only reads grades after it
_BEFORE = re.compile(r'(لا يحسن|لم يحسن|يقبح|قبح|فيحسن|يحسن|حسن|يتم|تم|يكفي)\s+(?:أن\s+تقف|الوقف)\s+'
                     r'(?:ولا يتم\s+)?على\s*(?:قوله\s*:?\s*)?\(([^()]{1,100})\)')
_BEFORE_T = re.compile(r'(?:الوقف التام|التمام|وقف التمام)\s+(?:على\s*)?(?:قوله\s*:?\s*)?\(([^()]{1,100})\)')
# grade_raw of grade-before rows: the row audit verifies these by
# missing_before_rulings(), not by the grade-after reading
BEFORE_RAW = {'حسن': 'يحسن الوقف', 'قبيح': 'لا يحسن الوقف', 'تام': 'يتم الوقف', 'كاف': 'يكفي الوقف'}
_BEFORE_MAP = {'لا يحسن': 'قبيح', 'لم يحسن': 'قبيح', 'يقبح': 'قبيح', 'قبح': 'قبيح', 'فيحسن': 'حسن',
               'يحسن': 'حسن', 'حسن': 'حسن', 'يتم': 'تام', 'تم': 'تام', 'يكفي': 'كاف'}


def clause(text, start, end):
    a = max(text.rfind('.', 0, start), text.rfind('\n', 0, start)) + 1
    b = text.find('.', end)
    return re.sub(r'\s+', ' ', text[a:(b if 0 <= b - end < 200 else end + 60)]).strip()


def missing_before_rulings(con):
    """[(surah, ayah, wpos, grade, quote, note)] for grade-before rulings
    («فعلى هذا المذهب يحسن الوقف على (الم)») with no row of that grade on
    the word. Counterfactuals («ولو حسن … لحسن») and negations
    («لا يتم …») are not rulings."""
    out, seen = [], set()
    for surah, text in sections().items():
        acount = rx.surah_ayah_count(surah)
        found = [(m, _BEFORE_MAP[m.group(1)], m.group(2)) for m in _BEFORE.finditer(text)]
        found += [(m, 'تام', m.group(1)) for m in _BEFORE_T.finditer(text)]
        for m, g, q in found:
            raw = BEFORE_RAW[g]
            pre = text[max(0, m.start() - 12):m.start()]
            if re.search(r'(?:ولو|لو|فلو)\s*$', pre) or text[max(0, m.start() - 1):m.start()] == 'ل':
                continue                       # «ولو حسن …»، «لحسن …»
            if g != 'قبيح' and re.search(r'(?:لا|لم|ولا)\s*$', pre):
                continue                       # «ولا يحسن»
            qs = m.end() - len(q) - 1
            va, own = verse_at(text, qs, m.end(), acount)
            a, w = seat(surah, va, q, acount, next_marker(text, m.end(), va, acount), own)
            if a is None or (surah, a, w, g) in seen:
                continue
            seen.add((surah, a, w, g))
            if con.execute("SELECT 1 FROM classical WHERE source='anbari' AND surah=? AND ayah=? "
                           "AND wpos=? AND grade=?", (surah, a, w, g)).fetchone():
                continue
            out.append((surah, a, w, g, raw, squash(q), clause(text, m.start(), m.end())))
    return out


def missing_graded_entries(con):
    """Graded quotes («(X) [n] [تام]»، «وكذلك على (Y)») with no row of that
    grade on their word. Skips other-surah citations («[النحل: 81]»، «في سورة
    سبأ») and quotes opened by someone else's «قال فلان:»."""
    out, seen = [], set()
    for surah, text in sections().items():
        acount = rx.surah_ayah_count(surah)
        for m in re.finditer(r'\(([^()]{2,120})\)', text):
            if re.search(r'\[[^\]\d]{2,20}:\s*\d', text[m.end():m.end() + 30]) or \
                    re.search(r'في سورة', text[max(0, m.start() - 70):m.start()]):
                continue
            g, via = grade_at(text, m.start(), m.end())
            if not g or g == 'NEG' or relayed_by(text, m.start()):
                continue
            q = m.group(1)
            va, own = verse_at(text, m.start(), m.end(), acount)
            a, w = seat(surah, va, q, acount, next_marker(text, m.end(), va, acount), own)
            if a is None or (surah, a, w, g) in seen:
                continue
            seen.add((surah, a, w, g))
            if con.execute("SELECT 1 FROM classical WHERE source='anbari' AND surah=? AND ayah=? "
                           "AND wpos=? AND grade=?", (surah, a, w, g)).fetchone():
                continue
            out.append((surah, a, w, g, squash(q), clause(text, m.start(), m.end())))
    return out


# no grade in the book for these («ومثله» is grammatical there): keep held
HOLD = {(5, 'والجروح قصاص'), (7, 'وهم يلعبون'), (7, 'وجاءوا بسحر عظيم'),
        (28, 'ما كان لهم الخيرة'), (69, 'ولا بقول كاهن')}


def held_by_neighbours(con):
    """[(id, ayah, wpos)] for held rows whose word occurs exactly once between
    the verses of the served rulings discussed just before and after it in
    the book (the range may span at most 3 verses)."""
    import bisect
    secs = sections()
    anchors = collections.defaultdict(list)
    for s_, a, q in con.execute("SELECT surah, ayah, quote FROM classical WHERE source='anbari' "
                                "AND conf=1 AND ayah IS NOT NULL"):
        for st, _ in occurrences(secs.get(s_, ''), q):
            anchors[s_].append((st, a))
    for v in anchors.values():
        v.sort()
    out = []
    for rid, s_, q in con.execute("SELECT id, surah, quote FROM classical WHERE source='anbari' "
                                  "AND conf=0").fetchall():
        if (s_, squash(q)) in HOLD:
            continue
        occ = occurrences(secs.get(s_, ''), q)
        if not occ:
            continue
        pos = occ[0][0]
        anc = anchors[s_]
        i = bisect.bisect_left(anc, (pos, 0))
        if i == 0 or i >= len(anc):
            continue
        lo, hi = sorted((anc[i - 1][1], anc[i][1]))
        if hi - lo > 3:
            continue
        hits = [(a, w) for a in range(lo, hi + 1) for w in mm.hits_in_ayah(s_, a, q, True)]
        if len(hits) == 1:
            out.append((rid,) + hits[0])
    return out


def apply(con, recs):
    """Write the audit's decisions:
      moved / ok      → seat updated; a held row that verifies is served
                        (a lone word without its own [n] stays held — the
                        book's opening discussion of البقرة jumps verses);
      regrade         → the grade the book actually gives («[تام]» heads);
      relayed         → labelled with the scholar («وقال السجستاني: …»);
      negated_head    → deleted («(X) غير تام. وكذلك: (Y)» is not a ruling);
      no_source_ruling→ held (conf=0): no graded sentence supports it."""
    cur = con.cursor()
    st = collections.Counter()
    for r in recs:
        rid = r['id']
        if r['status'] == 'negated_head':
            cur.execute('DELETE FROM classical WHERE id=?', (rid,))
            st['deleted_negated'] += 1
            continue
        if (r['surah'], squash(r['quote']), r['grade']) in HAND_CONFIRMED:
            continue
        if r['status'] in ('no_source_ruling', 'unplaced'):
            if r['conf'] == 1 and r['status'] == 'no_source_ruling':
                cur.execute('UPDATE classical SET conf=0 WHERE id=?', (rid,))
                st['held_unsupported'] += 1
            continue
        a, w = r['new_ayah'], r['new_wpos']
        word = mm.verse_words(r['surah'], a)[w]
        serve = r['conf'] == 1 or r.get('own_marker') or len(rx.quote_words(r['quote'], mm.hnorm)) >= 2
        grade = r.get('new_grade') or r['grade']
        rep = r.get('relayed') or r.get('reported_from')
        before = cur.execute('SELECT ayah, wpos, grade, conf, COALESCE(reported_from,"") FROM classical '
                             'WHERE id=?', (rid,)).fetchone()
        after = (a, w, grade, 1 if serve else r['conf'], rep or '')
        if before != after:
            cur.execute('UPDATE classical SET ayah=?, wpos=?, stop_word=?, grade=?, grade_raw=?, conf=?, '
                        'reported_from=? WHERE id=?',
                        (a, w, word, grade, grade, after[3], rep, rid))
            st[r['status'] + ('_served' if serve and r['conf'] == 0 else '')] += 1
    con.commit()
    for surah, a, w, g, raw, q, note in missing_before_rulings(con):
        seq = (cur.execute("SELECT seq FROM classical WHERE source='anbari' AND surah=? AND "
                           "(ayah<? OR (ayah=? AND wpos<=?)) ORDER BY ayah DESC, wpos DESC LIMIT 1",
                           (surah, a, a, w)).fetchone() or (0,))[0]
        cur.execute("INSERT INTO classical (source, surah, ayah, wpos, stop_word, quote, grade, grade_raw, "
                    "note, seq, conf, reported_from) VALUES ('anbari',?,?,?,?,?,?,?,?,?,1,?)",
                    (surah, a, w, mm.verse_words(surah, a)[w], q, g, raw, rx.clean_note(note, limit=400),
                     seq, None))
        st['inserted_grade_before'] += 1
    for surah, a, w, g, q, note in missing_graded_entries(con):
        seq = (cur.execute("SELECT seq FROM classical WHERE source='anbari' AND surah=? AND "
                           "(ayah<? OR (ayah=? AND wpos<=?)) ORDER BY ayah DESC, wpos DESC LIMIT 1",
                           (surah, a, a, w)).fetchone() or (0,))[0]
        cur.execute("INSERT INTO classical (source, surah, ayah, wpos, stop_word, quote, grade, grade_raw, "
                    "note, seq, conf, reported_from) VALUES ('anbari',?,?,?,?,?,?,?,?,?,1,NULL)",
                    (surah, a, w, mm.verse_words(surah, a)[w], q, g, g, rx.clean_note(note, limit=400), seq))
        st['inserted_graded'] += 1
    for rid, a, w in held_by_neighbours(con):
        s_ = cur.execute('SELECT surah FROM classical WHERE id=?', (rid,)).fetchone()[0]
        cur.execute('UPDATE classical SET ayah=?, wpos=?, stop_word=?, conf=1 WHERE id=?',
                    (a, w, mm.verse_words(s_, a)[w], rid))
        st['served_by_neighbours'] += 1
    for surah, g in BOOK_END:
        a = rx.surah_ayah_count(surah)
        w = len(mm.verse_words(surah, a)) - 1
        if not cur.execute("SELECT 1 FROM classical WHERE source='anbari' AND surah=? AND ayah=? AND wpos=?",
                           (surah, a, w)).fetchone():
            word = mm.verse_words(surah, a)[w]
            cur.execute("INSERT INTO classical (source, surah, ayah, wpos, stop_word, quote, grade, grade_raw, "
                        "note, seq, conf, reported_from) VALUES ('anbari',?,?,?,?,?,?,?,?,?,1,NULL)",
                        (surah, a, w, word, word, g, 'آخر السورة',
                         'والوقف التام في سورة الإخلاص والفلق والناس آخر السورة', 99999))
            st['inserted_book_end'] += 1
    con.commit()
    # identical rulings on the same word collapse (the builder double-emits
    # «والوقف على (X) قبيح» when a sentence repeats the quote)
    st['merged'] = mm.merge_duplicates(con, ('anbari',))
    return st


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--db', default=DB)
    ap.add_argument('--apply', action='store_true')
    args = ap.parse_args(argv)
    con = sqlite3.connect(args.db)
    recs = audit(con)
    with open(OUT, 'w', encoding='utf-8') as f:
        for r in recs:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')
    print(len(recs), 'rows:', dict(collections.Counter(r['status'] for r in recs)))
    print('by conf:', dict(collections.Counter((r['status'], r['conf']) for r in recs)))
    if args.apply:
        print('applied:', dict(apply(con, recs)))
    else:
        print('grade-before rulings to add:', len(missing_before_rulings(con)),
              '| graded entries to add:', len(missing_graded_entries(con)))


if __name__ == '__main__':
    main()
