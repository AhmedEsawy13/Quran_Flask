#!/usr/bin/env python3
"""Audit منار الهدى's «ومثله / وكذا» inherited rulings against the released DB.

منار states a ruling on a quote that carries its own verse marker, then extends
the SAME ruling to later stops with «ومثله «X»»، «وكذا «Y»»، «، و «Z»». Those
items have no [n] of their own; they sit in the same verse or a following one,
before the next verse the book marks. The LLM extraction resolved them by
reading; this audit re-resolves them mechanically and checks each against the
released rows.

For every head entry  {Q} [n] GRADE … ومثله «X»، وكذا «Y» …  it:
  1. takes the inherited grade (the head's, unless the item carries its own
     grade right after it, e.g. «وكذا «X» حسن»);
  2. searches X from just after Q's word through the verse before the next
     line's [n] (the book never skips past the next marked verse), keeping the
     FIRST occurrence in reading order; a phrase found nowhere in that span is
     `unaligned` (often a qirāʾa, grammar or rasm aside, not a stop);
  3. compares with the manar rows at that (ayah, wpos).

Statuses: ok, grade_mismatch (row there, different grade), missing (no row at
that word), unaligned. Conditional items («عند من…»، «إن…»، «على…») are
flagged because منار often gives them a different grade in the alternative.

Run:  python3 pipeline/audit_manar_mithl.py [--out pipeline/review/manar_mithl.jsonl]
"""
import argparse
import collections
import json
import os
import re
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_classical_waqf as rx  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SECTIONS = os.path.join(ROOT, 'pipeline', 'classical_sources', 'manar_shamela_sections.json')
DB = os.path.join(ROOT, 'data', 'classical_waqf.db')

_HARAKAT = re.compile('[ً-ْٰـ]')
# a head entry: {quote} [n] then a grade (possibly after a short gap)
_HEAD_RE = re.compile(r'\{([^{}]{1,120})\}\s*\[(\d{1,3})\]')
_ITEM_RE = re.compile(r'«([^«»]{1,80})»|\{([^{}]{1,120})\}')
_TRIGGER_RE = re.compile(r'(ومثله|ومثلها|وكذا|وكذلك|ونظيره|ونظيرها)(?:\s*ب)?\s*[:،]?\s*$')
_CONT_RE = re.compile(r'^[\s،,]*و\s*(?:ب\s*)?$')
_COND_RE = re.compile(r'^[\s،]*(?:عند|إن|ان|لمن|على|إذا|اذا|إلا|لو)\b')
# text between the grade word and the trigger may not start a new topic
_PLURAL = {'حسان': 'حسن', 'حسنة': 'حسن', 'تامة': 'تام', 'كافية': 'كاف',
           'جائزة': 'جائز', 'صالحة': 'صالح'}
# «… كلها حسان»، «كلها وقوف كافية»: one grade for the whole list just given
_COLLECTIVE_RE = re.compile(r'^[\s،]*(?:\(|)?(?:كلها|كلهن)\s+(?:وقوف\s+)?\(?(' +
                            '|'.join(_PLURAL) + r')\)?|^[\s،]*وقوف\s+(' + '|'.join(_PLURAL) + ')')
_PARTICLES = {'ثم', 'ان', 'لا', 'ما', 'او', 'ام', 'بل', 'قد', 'من', 'في', 'الا', 'اذا', 'اذ'}
_ANY_GRADE_RE = re.compile(r'(?<![ء-ي])(' + '|'.join(re.escape(g) for g, _ in rx.GRADES) + r')(?![ء-ي])')
_TOPIC_BREAK = re.compile(r'[.؟]|\bوقال\b|\bقال\b|\bقرأ\b|\bوقرأ\b|\bرسم|\bورسم')


def strip(s):
    return _HARAKAT.sub('', s or '')


def hnorm(tok):
    """rx.norm, blind to hamza seats: the book spells شيئا/ورئيا/مسئول where
    the mushaf writes شَيۡـٔٗا/وَرِءۡيٗا/مَسۡـُٔولٗا."""
    return rx.norm(re.sub('[ئؤٔ]', '', tok or ''))


def verse_words(surah, ayah):
    vk = f'{surah}:{ayah}'
    if vk not in rx.app.qpc_hafs_data_normalized:
        return None
    _, words, _ = rx.app._verse_word_texts(vk)
    return words


def hits_in_ayah(surah, ayah, quote, strict):
    """End-wpos hits of quote in one verse. strict = every tail token equal
    after normalisation; otherwise the builder's prefix/fuzzy tail rules."""
    words = verse_words(surah, ayah)
    if not words:
        return []
    wnorm = [hnorm(w) for w in words]
    for part in rx.quote_parts_for_align(quote):
        qwords = rx.quote_words(part, hnorm)
        if not qwords:
            continue
        # the whole quoted phrase first (3:78 «ويقولون هو من عند الله» vs the
        # later «وما هو من عند الله»), then the builder's 3-word tail
        for full in (True, False):
            hits = set()
            for seq in rx.quote_token_variants(qwords):
                k = len(seq) if full else min(3, len(seq))
                if strict:
                    tail = seq[-k:]
                    hits.update(i + k - 1 for i in range(len(wnorm) - k + 1)
                                if wnorm[i:i + k] == tail)
                else:
                    for level in (1, 2):
                        hits.update(rx._align_seq_hits(wnorm, seq, level, k))
            if hits:
                return sorted(hits)
    return []


_ORDINAL_RE = re.compile(r'^[\s،]*(?:في\s+الموضع\s+)?(الأول|الأولى|الثاني|الثانية|الثالث|الثالثة|الرابع|الرابعة|الأخير|الأخيرة|في الموضعين)(?![ء-ي])')
_ORDINAL = {'الأول': 0, 'الأولى': 0, 'الثاني': 1, 'الثانية': 1,
            'الثالث': 2, 'الثالثة': 2, 'الرابع': 3, 'الرابعة': 3,
            'الأخير': -1, 'الأخيرة': -1, 'في الموضعين': 'both'}


_PAUSE_MARKS = set('\u06D6\u06D7\u06D8\u06D9\u06DA\u06DB')


def pausable(words, w):
    """Verse end, or a word the mushaf marks with a pause sign (ۖ ۗ ۚ ۛ ۘ ۙ)."""
    return w == len(words) - 1 or bool(set(words[w]) & _PAUSE_MARKS)


def find_nth(surah, a0, a1, quote, n):
    """«X» الثاني / الأخيرة: the n-th (or last) occurrence inside the first verse
    of the window that holds more than one; failing that, counted across the
    window's verses («كيف قدر» الثاني). «في الموضعين» → both pause-marked
    occurrences. Returns a list of (ayah, wpos)."""
    for strict in (True, False):
        for a in range(a0, a1 + 1):
            hits = hits_in_ayah(surah, a, quote, strict)
            if len(hits) < 2:
                continue
            if n == 'both':
                words = verse_words(surah, a)
                marked = [h for h in hits if pausable(words, h)]
                return [(a, h) for h in (marked if len(marked) == 2 else hits[-2:])]
            if n == -1 or len(hits) > n:
                return [(a, hits[n])]
    if n == 'both':
        return []
    for strict in (True, False):
        seq = [(a, h) for a in range(a0, a1 + 1) for h in hits_in_ayah(surah, a, quote, strict)]
        if len(seq) > max(n, 1):
            return [seq[n]]
    return []


def find_in_span(surah, a0, w0, a1, quote, later=()):
    """First end-wpos of quote in reading order after (a0, w0), up to verse a1.

    An exact spelling anywhere in the window beats a prefixed/fuzzy one
    (60:10 «لهن» is «يحلون لهن», not «لا هن»). When the phrase repeats inside
    the verse where it is first found, the occurrence the mushaf marks as a
    pause wins (2:85 «ببعض» is «وتكفرون ببعضٖۚ», not «أفتؤمنون ببعض الكتاب»).
    An occurrence that a LATER item of the same chain names (6:144
    «الأنثيين»، و «أرحام الأنثيين») is left for that item.
    Returns (ayah, wpos, ambiguous).
    """
    for strict in (True, False):
        for a in range(a0, a1 + 1):
            hits = [h for h in hits_in_ayah(surah, a, quote, strict) if a > a0 or h > w0]
            if not hits:
                continue
            if len(hits) == 1:
                return a, hits[0], False
            words = verse_words(surah, a)
            claimed = {h for q in later for h in hits_in_ayah(surah, a, q, strict)}
            free = [h for h in hits if h not in claimed] or hits
            marked = [h for h in free if pausable(words, h)]
            if len(free) == 1:
                return a, free[0], False
            return a, (marked[0] if marked else free[0]), len(marked) != 1
    return None, None, False

# Chain items the matcher cannot place — the book's spelling differs from the
# Hafs text (qirāʾa «يقض»، «جدار»، «بظنين»; typos «سراجا» for «سرابا»،
# «فتفكرون» for «فتكفرون»), or the stop lies past the window. Decided by
# reading each line: (surah, head ayah, item) → (ayah, wpos).
PINS = {
    (2, 83, 'الصلاة'): (83, 19), (2, 83, 'الزكاة'): (83, 21),
    (2, 222, 'فاعتزلوا النساء في المحيض حتى يطهرن'): (222, 13),
    (2, 245, 'ويبسط'): (245, 13), (2, 275, 'الربا'): (275, 19),
    (4, 63, 'وعظيم'): (63, 9), (6, 57, 'يقض الحق'): (57, 18), (7, 69, 'بسطة'): (69, 21),
    (9, 55, 'إنهم لمنكم'): (56, 3), (11, 108, 'هؤلاء'): (109, 6), (12, 64, 'حفظا'): (64, 13),
    (13, 20, 'سواء الحساب'): (21, 12), (14, 46, 'وعند الله مكرهم'): (46, 5),
    (18, 57, 'إذن أبدا'): (57, 29), (20, 108, 'للرحمن'): (108, 8),
    (23, 41, 'يستأخرون'): (43, 6), (23, 63, 'يجأرون'): (64, 7), (28, 31, 'ملأه'): (32, 20),
    (28, 77, 'من المفسدين'): (77, 25), (30, 31, 'الصلاة'): (31, 4),
    (34, 52, 'التناوش'): (52, 5), (40, 9, 'فتفكرون'): (10, 14), (40, 74, 'ضلو عنا'): (74, 5),
    (51, 49, 'مبين'): (51, 10), (52, 18, 'تعلمون'): (19, 5), (52, 30, 'من غير شئ'): (35, 4),
    (59, 13, 'جدار'): (14, 10), (77, 42, 'تعلمون'): (43, 5), (78, 18, 'سراجا'): (20, 3),
    (81, 23, 'بظنين'): (24, 4), (83, 30, 'فاكهين'): (31, 5),
}
# «ومثله/و «X»» the parser reads that are remarks, not rulings: «و «ثم» لترتيب
# الأخبار»، «وكذا «إن» نصب بإضمار أعني»، «ومثلها «سوف» … فيبتدأ بها»، rasm
# and verse-count cross-references to other surahs.
NOT_RULINGS = {
    (4, 133, 'ولا الملائكة المقربون'), (23, 41, 'ثم'), (25, 7, 'فمال هؤلاء القوم'),
    (27, 7, 'سوف'), (28, 86, 'فلن أكون ظهيرا للمجرمين'), (29, 58, 'إن'),
    (54, 50, 'فعلوه'), (75, 12, 'ثم'), (48, 26, 'محلقين'), (48, 26, 'مقصرين'),
    (2, 69, 'فاقع لونها'), (6, 91, 'للناس'),
}
# grade differences read and left as stored: 37:12 the book rules {ويسخرون}
# جائز explicitly; 39:51 «كسبوا» تام فيهما; 51:26 «وهو: كاف، ومثله سمين».
MISMATCH_OK = {(37, 12, 2), (39, 51, 3), (51, 26, 5)}


def item_key(surah, head_ayah, item):
    return (surah, head_ayah, strip(item).strip())


def head_seat(surah, ayah, quote):
    """Word a {quote} [n] head rules on: the exact spelling first, then the
    pause-marked occurrence, then the last (the builder's historical choice).
    41:37 {والقمر} is «وَٱلۡقَمَرُۚ», not the later «ولا لِلۡقَمَرِ»."""
    if not rx.quote_words(quote, hnorm):
        return None
    hits = hits_in_ayah(surah, ayah, quote, True) or hits_in_ayah(surah, ayah, quote, False)
    if not hits:
        return None
    words = verse_words(surah, ayah)
    marked = [h for h in hits if pausable(words, h)]
    return marked[0] if marked else hits[-1]


def surah_lines():
    """(surah, line) in book order. Combined Shamela sections (العصر+الهمزة،
    الكافرون+النصر+تبت …) are split on their in-text «سورة X» headings."""
    sections = json.load(open(SECTIONS, encoding='utf-8'))
    seen = set()
    for key in sorted(sections, key=int):
        text = sections[key]['text']
        if text in seen:
            continue
        seen.add(text)
        cur = int(key)
        for ln in text.split('\r'):
            st = strip(ln).strip()
            if re.match(r'^سورة\s', st) and len(st) < 40:
                n = rx.surah_number(st, cur - 1)
                if n:
                    cur = n
            yield cur, ln


def parse_chain(line, start):
    """Items chained after a head ruling that ends at `start`.

    Returns [(quote, own_grade, conditional, trigger, pos)] and the index where
    the chain ended. An item needs an explicit trigger (ومثله/وكذا…) or a bare
    «، و» straight after a previous item; a {…} without either is a new head.
    """
    items, last_end = [], None
    for m in _ITEM_RE.finditer(line, start):
        gap_from = last_end if last_end is not None else start
        gap = line[gap_from:m.start()]
        if last_end is not None and _CONT_RE.match(gap):
            trig = 'و'
        else:
            t = _TRIGGER_RE.search(line[max(gap_from, m.start() - 16):m.start()])
            if not t:
                if m.group(2) is not None:
                    break
                continue          # an inline word quoted inside the علّة
            pre = strip(line[gap_from:m.start() - len(t.group(0))])
            if len(pre) > 90 or _TOPIC_BREAK.search(pre):
                break
            trig = t.group(1)
        q = rx.clean_note(m.group(1) or m.group(2) or '', limit=200)
        tail = strip(line[m.end():m.end() + 50]).lstrip(' ،:؛')
        gm = rx.GRADE_RE.match(tail)
        om = _ORDINAL_RE.match(tail)
        nth = _ORDINAL[om.group(1)] if om else None
        if om:
            tail = tail[om.end():].lstrip(' ،:؛')
            gm = rx.GRADE_RE.match(tail)
        own = dict(rx.GRADES).get(gm.group(1)) if gm else None
        items.append([q, own, bool(_COND_RE.match(tail)), trig, m.start(), m.end(), nth])
        last_end = m.end()
        if m.group(2) is not None:
            break
    # a collective grade right after the list overrides the inherited one
    if items:
        cm = _COLLECTIVE_RE.match(_ORDINAL_RE.sub('', strip(line[items[-1][5]:items[-1][5] + 50]), 1))
        if cm:
            g = _PLURAL[cm.group(1) or cm.group(2)]
            for it in items:
                it[1] = it[1] or g
    return items


def audit(db_rows):
    lines = list(surah_lines())
    heads = []   # (line index, surah, ayah) per line's first plausible marker
    for li, (surah, ln) in enumerate(lines):
        acount = rx.surah_ayah_count(surah)
        m = _HEAD_RE.search(ln)
        heads.append(int(m.group(2)) if m and 1 <= int(m.group(2)) <= acount else None)
    out = []
    for li, (surah, ln) in enumerate(lines):
        acount = rx.surah_ayah_count(surah)
        for hm in _HEAD_RE.finditer(ln):
            ayah = int(hm.group(2))
            if not 1 <= ayah <= acount:
                continue
            gtail = strip(ln[hm.end():hm.end() + 60]).lstrip(' ،:؛')
            gm = rx.GRADE_RE.match(gtail)
            if not gm:
                continue
            grade = dict(rx.GRADES)[gm.group(1)]
            items = parse_chain(ln, hm.end())
            if not items:
                continue
            # alternative grades voiced between the head and its chain
            # («حسن، وقيل: كاف، ومثله …»، «حسن، تام للابتداء بالشرط، ومثله …»)
            alt = {dict(rx.GRADES)[g] for g in
                   _ANY_GRADE_RE.findall(strip(ln[hm.end():items[0][4]]))}
            hq = rx.clean_note(hm.group(1), limit=200)
            hw = head_seat(surah, ayah, hq)
            # search window: up to the verse of the next line that marks a
            # LATER verse; one marked verse further as a flagged fallback.
            later = []
            for j in range(li + 1, len(lines)):
                if lines[j][0] != surah:
                    break
                if heads[j] and heads[j] > ayah and heads[j] not in later:
                    later.append(heads[j])
                    if len(later) == 2:
                        break
            span1 = later[0] if later else acount
            span2 = later[1] if len(later) > 1 else acount
            cur_a, cur_w = ayah, (hw if hw is not None else -1)
            for ii, (q, own, cond, trig, pos, _end, nth) in enumerate(items):
                later = [it[0] for it in items[ii + 1:]]
                g = own or grade
                far = False
                amb = False
                if nth is not None:
                    spots = find_nth(surah, cur_a, span1, q, nth)
                else:
                    a, w, amb = find_in_span(surah, cur_a, cur_w, span1, q, later)
                    if a is None:
                        a, w, amb = find_in_span(surah, max(cur_a, span1),
                                                 -1 if span1 > cur_a else cur_w, span2, q, later)
                        far = a is not None
                    spots = [(a, w)] if a is not None else []
                if len(spots) == 1 and spots[0][1] == 0 and hnorm(q) in _PARTICLES:
                    spots = []    # «و «ثم» لترتيب الأخبار» — a remark, not a stop
                ik = item_key(surah, ayah, q)
                if ik in NOT_RULINGS:
                    continue
                if not spots and ik in PINS:
                    spots = [PINS[ik]]
                base = {'surah': surah, 'head_ayah': ayah, 'head': hq, 'head_grade': grade,
                        'alt_grades': sorted(alt - {grade}), 'trigger': trig, 'item': q,
                        'grade': g, 'own_grade': bool(own), 'conditional': cond, 'ordinal': nth,
                        'ambiguous': amb, 'far': far,
                        'context': strip(ln[max(0, pos - 80):pos + 140])}
                if not spots:
                    out.append(dict(base, status='unaligned'))
                for a, w in spots:
                    rec = dict(base, ayah=a, wpos=w, mushaf_word=verse_words(surah, a)[w])
                    have = db_rows.get((surah, a, w), [])
                    rec['db'] = have
                    grades = {r['grade'] for r in have}
                    if not have:
                        rec['status'] = 'missing'
                    elif g in grades:
                        rec['status'] = 'ok'
                    elif grades & (alt | {grade}) or (surah, a, w) in MISMATCH_OK:
                        rec['status'] = 'ok_alt'
                    else:
                        rec['status'] = 'grade_mismatch'
                    cur_a, cur_w = a, w
                    out.append(rec)
    return out


# ── repeated-word misplacement (any منار row, not only chain items) ───────────
# The extraction aligned short stop phrases with "last occurrence wins", so
# «الله» often landed on the «إِنَّ ٱللَّهَ» right after the real stop
# (5:7 «وَٱتَّقُواْ ٱللَّهَۚ إِنَّ ٱللَّهَ | عَلِيمُۢ»). A row is moved only when
#   * the book rules on no word at its current seat (no {…} [n] head, no chain
#     item resolves there),
#   * its seat is not pause-marked / verse-end, and exactly one OTHER seat in
#     the verse holds the same word, IS ruled on by the book, and is marked,
#   * its note names no ordinal («الثاني»، «في الموضعين» …).
# A row on a ruled seat is also moved when its quote spells exactly one OTHER
# ruled word and its own seat is unmarked (41:37, 48:26 «الحمية» الأولى).
# Everything else that looks misplaced goes to the review queue.
_ORD_NOTE = re.compile(r'الثاني|الثانية|الموضعين|المواضع|كلاهما|كليهما|فيهما|الأخير|الأول|الأولى|الثالث')


def ruled_seats(recs):
    seats = set()
    for r in recs:
        if 'ayah' in r:
            seats.add((r['surah'], r['ayah'], r['wpos']))
    for surah, ln in surah_lines():
        for hm in _HEAD_RE.finditer(ln):
            a = int(hm.group(2))
            if not 1 <= a <= rx.surah_ayah_count(surah):
                continue
            q = rx.clean_note(hm.group(1), limit=200)
            if rx.quote_words(q, hnorm):
                hits = hits_in_ayah(surah, a, q, True) or hits_in_ayah(surah, a, q, False)
            else:
                words = verse_words(surah, a)
                hits = [len(words) - 1] if words else []
            seats.update((surah, a, h) for h in hits)
    return seats


def misplaced_rows(path, recs):
    """([(id, surah, ayah, from_wpos, to_wpos)], [review dicts])."""
    seats = ruled_seats(recs)
    con = sqlite3.connect(path)
    moves, review = [], []
    for rid, s, a, w, q, g, note in con.execute(
            "SELECT id, surah, ayah, wpos, quote, grade, COALESCE(note,'') FROM classical "
            "WHERE source='manar' AND conf=1 AND wpos IS NOT NULL"):
        words = verse_words(s, a)
        if not words or w >= len(words):
            continue
        if (s, a, w) in seats:
            # the quote spells ANOTHER ruled word exactly (41:37 {والقمر} row
            # sitting on «ولا لِلۡقَمَرِ»); move only off an unmarked seat
            strict = hits_in_ayah(s, a, q, True) if rx.quote_words(q, hnorm) else []
            if (len(strict) == 1 and strict[0] != w and (s, a, strict[0]) in seats
                    and not pausable(words, w) and not _ORD_NOTE.search(note)):
                moves.append((rid, s, a, w, strict[0]))
            continue
        last = hnorm(words[w])
        same = [x for x in range(len(words)) if x != w and (s, a, x) in seats
                and rx.match_word(hnorm(words[x]), last, 1)]
        if not same:
            continue
        marked = [x for x in same if pausable(words, x)]
        if (s, a, w) in REVIEWED_OK:
            continue
        if _ORD_NOTE.search(note) or pausable(words, w) or len(marked) != 1:
            review.append({'id': rid, 'surah': s, 'ayah': a, 'wpos': w, 'word': words[w],
                           'candidates': same, 'grade': g, 'quote': q, 'note': note})
        else:
            moves.append((rid, s, a, w, marked[0]))
    con.close()
    return moves, review


# ── curated decisions (each checked by hand against the book, 2026-09-26) ────
# Rows the LLM put on the WRONG occurrence of a repeated word, moved to the
# occurrence the book means: id → (ayah, wpos). E.g. 13:16 «قل الله» تام sat
# on «قُلِ ٱللَّهُ خَٰلِقُ» (mid-sentence) instead of «قُلِ ٱللَّهُۚ»; 22:2
# «سكارى» sat on the second one although its own note says «دون الثاني».
MOVES = {
    47261: (165, 15), 47262: (165, 15), 47522: (230, 23), 47626: (253, 17),
    47770: (282, 21), 47793: (284, 16), 47794: (284, 16), 48026: (55, 7),
    48087: (78, 22), 48543: (12, 33), 48656: (39, 10), 48694: (52, 3),
    49209: (42, 10), 49230: (48, 16), 49242: (51, 7), 49279: (64, 38),
    49827: (136, 20), 50110: (53, 3), 50221: (99, 2), 50489: (13, 4),
    50511: (23, 5), 50575: (48, 32), 50618: (66, 22), 50642: (75, 16),
    51113: (34, 8), 51732: (44, 2), 51957: (16, 6), 51998: (26, 8),
    52080: (11, 24), 52717: (34, 12), 53219: (44, 3), 53773: (2, 14),
    54916: (15, 16), 55011: (50, 16), 55401: (54, 10), 55455: (15, 21),
    56422: (27, 10), 58481: (2, 7), 58610: (20, 5), 58718: (5, 17),
    58733: (10, 9), 58828: (2, 14), 58850: (9, 2), 59502: (7, 3),
    # 7:195 «وكذا «بها» الأخيرة، وفي المواضع الثلاثة لا يجوز الوقف»: the لا
    # belongs to the first three بها, the last one is كاف.
    50435: (195, 3),
    # 2:165 «{كحب الله} حسن … وقال أبو عمرو فيهما: تام» sat on «وَأَنَّ ٱللَّهَ»;
    # two marked «الله» seats compete, so the mechanical rule leaves it.
    47259: (165, 10), 47260: (165, 10),
    # review queue, decided against the book's own {quote} [n] line
    # (2026-09-26): each row sat on a repeated word after the quoted one.
    47022: (101, 14), 47023: (101, 14),      # {أوتوا الكتاب}
    47167: (138, 1),                         # {صبغة الله} حسن ({صبغة} أحسن is w8)
    47367: (194, 16),                        # {واتقوا الله} أحسن
    47372: (196, 1), 47373: (196, 1),        # {وأتموا الحج}
    47389: (197, 18),                        # {من خير} ليس بوقف
    47577: (243, 22),                        # {على الناس}
    47579: (244, 3),                         # {سبيل الله}
    47776: (282, 64),                        # {من الشهداء}
    47784: (282, 121),                       # {واتقوا الله} جائز
    47801: (285, 13), 47802: (285, 13),      # {ورسله}
    47934: (27, 3), 47935: (27, 3),          # {في النهار}
    48027: (55, 11), 48028: (55, 11),        # {ومطهرك من الذين كفروا}
    48214: (119, 7),                         # {بالكتاب كله}
    48381: (174, 4),                         # {وفضل}
    48408: (181, 5),                         # {قول الذين قالوا}
    48484: (98, 6),                          # {بآيات الله}
    48487: (199, 14),                        # {خاشعين لله}
    48585: (23, 2), 48586: (23, 2),          # {أمهاتكم}
    48935: (139, 9),                         # {عندهم العزة}
    49046: (24, 8),                          # {كتاب الله}
    49076: (3, 35),                          # {من دينكم}
    49084: (4, 16), 49086: (4, 26),          # {مما علمكم الله} / {واتقوا الله}
    49238: (49, 5),                          # {بما أنزل الله}
    50299: (143, 5),                         # {وكلمه ربه}
    50687: (19, 18),                         # {لا يستوون عند الله}
    50792: (59, 9),                          # {حسبنا الله}
    50840: (74, 3),                          # {ما قالوا}
    51499: (71, 4), 51500: (71, 4), 51501: (71, 4),   # {فبشرناها بإسحاق}
    51779: (66, 8),                          # {موثقا من الله}
    52498: (76, 21),                         # {هل يستوي هو}
    52874: (108, 2),                         # {سبحان ربنا}
    53001: (46, 7),                          # {خير} ليس بوقف
    53229: (48, 7),                          # {وأدعو ربي}
    53367: (39, 6),                          # {في اليم}
    53855: (36, 5),                          # {من شعائر الله}
    54065: (70, 6), 54068: (71, 11),         # {بالحق} / {بذكرهم}
    54147: (2, 14),                          # {في دين الله}
    54177: (16, 9),                          # {بهذا}
    54197: (25, 4),                          # {دينهم الحق}
    54325: (40, 6),                          # {يغشاه موج}
    54759: (18, 5),                          # {واد النمل}
    55400: (54, 4),                          # {من ضعف}
    55503: (33, 10),                         # {عن ولده}
    55842: (22, 6),                          # {من دون الله}
    56114: (47, 6),                          # {مما رزقكم الله}
    56461: (51, 1),                          # {متكئين فيها}
    57053: (50, 10),                         # {هذا لي}
    57077: (6, 7),                           # {حفيظ عليهم}
    57099: (13, 22), 57100: (13, 28),        # {ولا تتفرقوا فيه} / {ما تدعوهم إليه}
    57726: (38, 11),                         # {ومن يبخل} الثاني
    57811: (26, 6),                          # {الحمية}
    57846: (3, 6),                           # {عند رسول الله}
    57875: (12, 6),                          # {من الظن}
    58075: (18, 3),                          # {بما آتاهم ربهم}
    58407: (10, 6),                          # {في سبيل الله}
    58423: (14, 16),                         # {حتى جاء أمر الله}
    58471: (29, 14),                         # {بيد الله}
    58911: (11, 6),                          # {امرأة فرعون}
    59223: (14, 3),                          # {والجبال} الأول
    50786: (56, 3),                          # ومثله «إنهم لمنكم»
}
# conf=0 rows held back only because the extraction misspelled the quote
# («تُحۡشُورنَ»، «مَسۡظُورٗا»): the ruling is the book's, so cite the mushaf's
# own word and serve it. A value moves the row first (4:17 «عليهمۗ»، 4:46
# «وراعنا» sat on other words); a duplicate of a correct row is dropped.
REPAIR = {
    47223: None, 48564: (17, 15), 48675: (46, 13), 48676: (46, 13), 49348: None,
    49368: None, 49983: None, 51375: None, 51842: None, 51853: None, 52008: None,
    52263: None, 52398: None, 52635: None, 53161: None, 53640: None, 53860: None,
    54007: None, 54043: None, 54196: None, 54847: None, 55310: None, 55352: None,
    55447: None, 55607: None, 55874: None, 56144: None, 57681: None, 58131: None,
    58304: None, 58305: None, 58306: None, 58433: None, 59377: None,
    48477: (20, 13), 49264: (60, 8),      # duplicates of 47914 / 49454
}
# rows no {quote} [n] line of the book supports (3:73 كاف on «وَٱللَّهُ وَٰسِعٌ»،
# 48:10 جائز on «عَٰهَدَ عَلَيۡهُ ٱللَّهَ») or that the author rejects: deleted.
DEMOTE = {48071, 57755,
          46685,      # 2:6 «أم لم تنذرهم» — «وهذا ينبغي أن يرد ولا يلتفت إليه»
          53454,      # 20:95 «يا سامري» — no ruling in the book
          56342}      # 37:165 «الصافون» — the book's ومثله names «المسبحون»
# rows on a repeated word that the book does mean (checked): not suspects
REVIEWED_OK = {(2, 218, 12), (2, 255, 43), (7, 195, 3), (7, 195, 8), (7, 195, 13),
               (11, 119, 3), (13, 31, 28), (39, 51, 11), (59, 18, 11)}
# Grade corrections: id → grade. 39:50 «ومثله «يكسبون»» inherits كاف; the
# «تام فيهما» that follows is about «كسبوا» الأولى والثانية.
REGRADE = {
    56650: 'كاف',
    # traceability queue, read against the book (2026-09-26)
    59559: 'حسن',     # 83:2 {يستوفون} حسن
    58065: 'حسن',     # 52:8 {ما له من دافع} أحسن مما قبله
    46721: 'صالح',    # 2:16 {تجارتهم} أصلح
    59098: 'حسن',     # 70:3 «الوقف الجيد ذي المعارج» (الأخفش)
}
# relayed opinions that were stored as the author's own
REPORTED_FIX = {50554: 'قيل', 59098: 'الأخفش', 46946: 'شيخ الإسلام',
                # «كاف إن جعلت اللام للقسم على قول أبي حاتم» / «كما يقول أبو حاتم»
                55651: 'أبو حاتم', 55982: 'أبو حاتم'}
# grade_mismatch keys where منار's inherited ruling is absent and only another
# (alternate / relayed / conditional) grade was stored: add it.
ADD_GRADE = {
    (6, 75, 5), (7, 195, 18), (15, 22, 7), (18, 102, 13), (18, 103, 4),
    (25, 41, 10), (27, 10, 18), (28, 74, 7), (35, 10, 10), (39, 20, 13),
    (40, 74, 12), (45, 7, 3), (50, 22, 11), (72, 17, 9), (72, 23, 15), (111, 4, 0),
}
# chain items the parser reads that are not rulings («وكذا «محلقين»» is about
# the حال), or whose grade the book states differently than inherited.
SKIP = set()          # superseded by NOT_RULINGS
GRADE_OVERRIDE = {(39, 51, 3): 'تام'}      # «كسبوا» الأولى والثانية تام فيهما
REPORTED = {(25, 41, 10): 'أبو حاتم'}      # «ومثله «رسولا» عند أبي حاتم»
# extra rows the chain implies but the resolver cannot emit on its own
EXTRA = [
    (7, 195, 8, 'بها', 'لا', 'وفي المواضع الثلاثة لا يجوز الوقف؛ لأن «أم» عاطفة'),
    (7, 195, 13, 'بها', 'لا', 'وفي المواضع الثلاثة لا يجوز الوقف؛ لأن «أم» عاطفة'),
    # the book rules on BOTH occurrences; only the second had been stored
    (4, 24, 27, 'فريضة', 'كاف', '{فريضة} كاف، ومثله «من بعد الفريضة»'),
    (4, 102, 11, 'أسلحتهم', 'حسن', '{أسلحتهم} حسن، ومثله «من ورائكم»، وكذا «أسلحتهم» (الثاني)'),
    (12, 51, 7, 'عن نفسه', 'حسن', '{عن نفسه} حسن، ومثله «من سوء»، وكذا «عن نفسه» (الثاني)'),
    (18, 17, 8, 'ذات اليمين', 'حسن', '{ذات اليمين .... ذات الشمال} حسن'),
    (3, 49, 22, 'بإذن الله', 'جائز', '{بإذن الله} جائز في الموضعين'),
]


def source_note(rec):
    """The book's own clause for this item: from its trigger to the end of
    the clause, verbatim (diacritics stripped), e.g. «ومثله «إلا وجهه»،
    والمراد بالوجه: الذات»."""
    ctx, item = rec['context'], strip(rec['item'])
    k = ctx.find('«' + item[:6])
    if k < 0:
        k = ctx.find(item[:6])
    start = max(0, k - 14)
    t = re.search(r'(ومثله|ومثلها|وكذا|وكذلك|ونظيره|ونظيرها|و)\s*:?\s*(?:ب\s*)?$', ctx[start:k])
    if t:
        start += t.start()
    end = len(ctx)
    m = re.search(r'[.]|؛|،\s*(?:و|ومثله|ومثلها|وكذا|وكذلك)\s*:?\s*(?:ب\s*)?«', ctx[k + len(item) + 2:])
    if m:
        end = k + len(item) + 2 + m.start()
    note = ctx[start:end].strip(' ،')
    return rx.clean_note(f'{note} (مثل «{rec["head"]}» {rec["head_grade"]})', limit=300)


def apply(recs, path):
    con = sqlite3.connect(path)
    cur = con.cursor()
    stats = collections.Counter()

    def exists(s, a, w, g):
        return cur.execute("SELECT 1 FROM classical WHERE source='manar' AND surah=? AND ayah=? "
                           "AND wpos=? AND grade=?", (s, a, w, g)).fetchone() is not None

    def seq_near(s, a, w):
        r = cur.execute("SELECT seq FROM classical WHERE source='manar' AND surah=? AND "
                        "(ayah<? OR (ayah=? AND wpos<=?)) ORDER BY ayah DESC, wpos DESC, seq DESC LIMIT 1",
                        (s, a, a, w)).fetchone()
        return r[0] if r else 0

    def dedupe_note(s, a, reported, notes):
        """First candidate that neither repeats nor contains/is contained in
        another explanation of this ayah (the learner view shows them all)."""
        have = [' '.join(n.split()) for (n,) in cur.execute(
            "SELECT note FROM classical WHERE source='manar' AND surah=? AND ayah=? AND "
            "COALESCE(reported_from,'')=? AND COALESCE(note,'')<>''", (s, a, reported or ''))]
        for n in notes:
            n = ' '.join(n.split())
            if not any(n == h or (len(n) >= 30 and n in h) or (len(h) >= 30 and h in n)
                       for h in have):
                return n
        return ''

    def insert(s, a, w, quote, g, notes, reported=None):
        if exists(s, a, w, g):
            return False
        if not rx.pin_matches_wpos(s, a, w, quote):
            # the book's spelling (شيئا، السيئات) — cite the mushaf's words
            n = max(1, len(rx.quote_words(quote)))
            quote = ' '.join(verse_words(s, a)[max(0, w - n + 1):w + 1])
        note = dedupe_note(s, a, reported, notes)
        cur.execute("INSERT INTO classical (source, surah, ayah, wpos, stop_word, quote, grade, "
                    "grade_raw, note, seq, conf, reported_from) VALUES ('manar',?,?,?,?,?,?,?,?,?,1,?)",
                    (s, a, w, verse_words(s, a)[w], quote, g, g, note, seq_near(s, a, w), reported))
        return True

    for rid, (a, w) in MOVES.items():
        row = cur.execute("SELECT surah, ayah, wpos, grade, note FROM classical WHERE id=? AND source='manar'",
                          (rid,)).fetchone()
        if not row or (row[1], row[2]) == (a, w):
            continue
        s = row[0]
        dup = cur.execute("SELECT id, note FROM classical WHERE source='manar' AND surah=? AND ayah=? "
                          "AND wpos=? AND grade=? AND id<>?", (s, a, w, row[3], rid)).fetchone()
        if dup:
            if len(row[4] or '') > len(dup[1] or ''):
                cur.execute("UPDATE classical SET note=? WHERE id=?", (row[4], dup[0]))
            cur.execute("DELETE FROM classical WHERE id=?", (rid,))
            stats['merged_duplicate'] += 1
        else:
            cur.execute("UPDATE classical SET ayah=?, wpos=?, stop_word=? WHERE id=?",
                        (a, w, verse_words(s, a)[w], rid))
            stats['moved'] += 1
    con.commit()
    for rid, s, a, w_from, w_to in misplaced_rows(path, recs)[0]:
        row = cur.execute("SELECT grade, note, reported_from FROM classical WHERE id=?", (rid,)).fetchone()
        dup = cur.execute("SELECT id, note FROM classical WHERE source='manar' AND surah=? AND ayah=? "
                          "AND wpos=? AND grade=? AND COALESCE(reported_from,'')=? AND id<>?",
                          (s, a, w_to, row[0], row[2] or '', rid)).fetchone()
        if dup:
            if len(row[1] or '') > len(dup[1] or ''):
                cur.execute("UPDATE classical SET note=? WHERE id=?", (row[1], dup[0]))
            cur.execute("DELETE FROM classical WHERE id=?", (rid,))
            stats['repeat_merged'] += 1
        else:
            cur.execute("UPDATE classical SET wpos=?, stop_word=? WHERE id=?",
                        (w_to, verse_words(s, a)[w_to], rid))
            stats['repeat_moved'] += 1
    stats['deleted'] += cur.execute(
        f"DELETE FROM classical WHERE source='manar' AND id IN ({','.join(map(str, DEMOTE))})").rowcount
    for rid, seat in REPAIR.items():
        row = cur.execute("SELECT surah, ayah, wpos, grade FROM classical WHERE id=? AND conf=0",
                          (rid,)).fetchone()
        if not row:
            continue
        s_, a, w, g = row
        if seat:
            a, w = seat
        if cur.execute("SELECT 1 FROM classical WHERE source='manar' AND conf=1 AND surah=? AND ayah=? "
                       "AND wpos=? AND grade=? AND id<>?", (s_, a, w, g, rid)).fetchone():
            cur.execute("DELETE FROM classical WHERE id=?", (rid,))
            stats['repair_dropped_duplicate'] += 1
            continue
        word = verse_words(s_, a)[w]
        cur.execute("UPDATE classical SET ayah=?, wpos=?, stop_word=?, quote=?, conf=1 WHERE id=?",
                    (a, w, word, word, rid))
        stats['repaired'] += 1
    for rid, who in REPORTED_FIX.items():
        stats['reattributed'] += cur.execute(
            "UPDATE classical SET reported_from=? WHERE id=? AND COALESCE(reported_from,'')<>?",
            (who, rid, who)).rowcount
    for rid, g in REGRADE.items():
        stats['regraded'] += cur.execute("UPDATE classical SET grade=?, grade_raw=? WHERE id=? AND grade<>?",
                                         (g, g, rid, g)).rowcount
    for r in recs:
        if 'ayah' not in r:
            continue
        key = (r['surah'], r['ayah'], r['wpos'])
        if key in SKIP:
            continue
        if r['status'] == 'missing' or (r['status'] == 'grade_mismatch' and key in ADD_GRADE):
            g = GRADE_OVERRIDE.get(key, r['grade'])
            short = f'مثل «{r["head"]}» ({r["head_grade"]})'
            if insert(*key, r['item'], g, [source_note(r), short], REPORTED.get(key)):
                stats['inserted_' + r['status']] += 1
    for s, a, w, q, g, note in EXTRA:
        stats['inserted_extra'] += insert(s, a, w, q, g, [note])
    con.commit()
    for rid, a, w in explicit_seat_moves(con, recs):
        s_ = cur.execute('SELECT surah FROM classical WHERE id=?', (rid,)).fetchone()[0]
        cur.execute('UPDATE classical SET wpos=?, stop_word=? WHERE id=?',
                    (w, verse_words(s_, a)[w], rid))
        stats['explicit_seat_moved'] += 1
    con.commit()
    stats['own_grade_unlabelled'] = fix_misattributed(con)
    stats['merged_repeats'] = merge_duplicates(con)
    stats['notes_shortened'] = shorten_repeated_notes(con)
    return stats


_OWN_ATTRIB = re.compile(r'^[\s،,؛]*(?:وهو\s+)?(?:عند|على\s+مذهب|على\s+قول|قاله|لـ?\s*)')


def fix_misattributed(con):
    """«{Q} [n] كاف، وقال أبو عمرو: تام» — the كاف is الأشموني's own; the
    name belongs to the NEXT opinion. Rows that carry only a relayed label on
    the book's own grade get the label cleared. «{Q} [n] تام عند أبي حاتم»
    (attribution right after the grade) is left alone."""
    cur = con.cursor()
    fixed = 0
    for surah, ln in surah_lines():
        for hm in _HEAD_RE.finditer(ln):
            a = int(hm.group(2))
            if not 1 <= a <= rx.surah_ayah_count(surah):
                continue
            tail = strip(ln[hm.end():hm.end() + 120]).lstrip(' ،:؛')
            gm = rx.GRADE_RE.match(tail)
            if not gm or _OWN_ATTRIB.match(tail[gm.end():]):
                continue
            w = head_seat(surah, a, rx.clean_note(hm.group(1), limit=200))
            if w is None:
                continue
            g = dict(rx.GRADES)[gm.group(1)]
            rows = cur.execute("SELECT id, reported_from FROM classical WHERE source='manar' AND conf=1 "
                               "AND surah=? AND ayah=? AND wpos=? AND grade=?", (surah, a, w, g)).fetchall()
            if rows and all(r[1] for r in rows) and rows[0][0] not in REPORTED_FIX:
                cur.execute("UPDATE classical SET reported_from=NULL WHERE id=?", (rows[0][0],))
                fixed += 1
    con.commit()
    return fixed


# explicit-seat sweep exceptions (read 2026-09-26): «في الموضعين» (3:49), both
# occurrences pause-marked (4:78, 4:131), or already confirmed where they sit.
SEAT_KEEP = {58606, 57109, 55246, 48009, 48762, 48916, 50427, 55230, 49205}


def explicit_seat_moves(con, recs):
    """[(row id, ayah, to wpos)] for a {Q} [n] GRADE whose word has no row of
    that grade while the same grade sits on another occurrence of that word in
    the verse that the book does not rule on (16:104 «{لا يؤمنون بآيات الله}
    ليس بوقف» sat on «لا يهديهم الله»)."""
    ruled = collections.defaultdict(set)
    for r in recs:
        if 'ayah' in r:
            ruled[(r['surah'], r['ayah'], r['wpos'])].add(r['grade'])
    heads = []
    for surah, ln in surah_lines():
        for hm in _HEAD_RE.finditer(ln):
            a = int(hm.group(2))
            if not 1 <= a <= rx.surah_ayah_count(surah):
                continue
            gm = rx.GRADE_RE.match(strip(ln[hm.end():hm.end() + 40]).lstrip(' ،:؛'))
            if not gm:
                continue
            w = head_seat(surah, a, rx.clean_note(hm.group(1), limit=200))
            if w is None:
                continue
            g = dict(rx.GRADES)[gm.group(1)]
            ruled[(surah, a, w)].add(g)
            heads.append((surah, a, w, g))
    moves = []
    for surah, a, w, g in heads:
        if con.execute("SELECT 1 FROM classical WHERE source='manar' AND surah=? AND ayah=? AND wpos=? "
                       "AND grade=?", (surah, a, w, g)).fetchone():
            continue
        words = verse_words(surah, a)
        key = hnorm(words[w])
        for rid, x in con.execute("SELECT id, wpos FROM classical WHERE source='manar' AND surah=? "
                                  "AND ayah=? AND grade=? AND wpos<>?", (surah, a, g, w)).fetchall():
            if (rid not in SEAT_KEEP and rx.match_word(hnorm(words[x]), key, 1)
                    and g not in ruled[(surah, a, x)]):
                moves.append((rid, a, w))
                break
    return moves


def merge_duplicates(con, sources=('manar', 'muktafa')):
    """Collapse rows that repeat the same ruling on the same word (same grade
    and attribution) when their notes add nothing: one note empty or contained
    in the other. Rows whose notes differ (different conditions, «وقيل»)
    stay separate. Keeps the row with the longest note."""
    cur = con.cursor()
    groups = collections.defaultdict(list)
    q = ','.join('?' * len(sources))
    for row in cur.execute(
            f"SELECT id, source, surah, ayah, wpos, grade, COALESCE(reported_from,''), "
            f"COALESCE(note,'') FROM classical WHERE conf=1 AND source IN ({q})", sources):
        groups[row[1:7]].append((row[0], ' '.join(row[7].split())))
    dropped = 0
    for rows in groups.values():
        if len(rows) < 2:
            continue
        keep = max(rows, key=lambda r: (len(r[1]), -r[0]))
        if all(not n or n in keep[1] for _, n in rows):
            for rid, _ in rows:
                if rid != keep[0]:
                    cur.execute('DELETE FROM classical WHERE id=?', (rid,))
                    dropped += 1
    con.commit()
    return dropped


def shorten_repeated_notes(con):
    """An inserted chain row's note («ومثله «X» … (مثل «H» g)») can end up
    repeating a neighbour's explanation in the same verse; the learner view
    shows both, so keep only its «(مثل …)» reference."""
    cur = con.cursor()
    n = 0
    rows = cur.execute("SELECT id, surah, ayah, COALESCE(reported_from,''), note FROM classical "
                       "WHERE source='manar' AND note LIKE '%(مثل «%' AND note NOT LIKE '«%'").fetchall()
    for rid, s_, a, rep, note in rows:
        m = re.search(r'\((مثل «[^»]*» \S+)\)$', note or '')
        if not m:
            continue
        body = ' '.join(note[:m.start()].split())
        others = [' '.join((o or '').split()) for (o,) in cur.execute(
            "SELECT note FROM classical WHERE source='manar' AND surah=? AND ayah=? AND id<>? "
            "AND COALESCE(reported_from,'')=?", (s_, a, rid, rep))]
        if any(len(o) >= 30 and (body in o or o in note) or (o and o == body) for o in others):
            quote = cur.execute('SELECT quote FROM classical WHERE id=?', (rid,)).fetchone()[0]
            cur.execute('UPDATE classical SET note=? WHERE id=?', (f'«{strip(quote)}» {m.group(1)}', rid))
            n += 1
    con.commit()
    return n


def load_db(path):
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    rows = collections.defaultdict(list)
    for r in con.execute("SELECT id, surah, ayah, wpos, quote, grade, conf FROM classical "
                         "WHERE source='manar' AND wpos IS NOT NULL"):
        rows[(r['surah'], r['ayah'], r['wpos'])].append(
            {'id': r['id'], 'quote': r['quote'], 'grade': r['grade'], 'conf': r['conf']})
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default=os.path.join(ROOT, 'pipeline', 'review', 'manar_mithl.jsonl'))
    ap.add_argument('--db', default=DB)
    ap.add_argument('--apply', action='store_true',
                    help='write the curated moves + missing inherited rulings into --db')
    args = ap.parse_args(argv)
    recs = audit(load_db(args.db))
    if args.apply:
        print('applied:', dict(apply(recs, args.db)))
        recs = audit(load_db(args.db))
    moves, review = misplaced_rows(args.db, recs)
    rq = os.path.join(os.path.dirname(args.out), 'manar_misplaced_review.jsonl')
    with open(rq, 'w', encoding='utf-8') as f:
        for r in review:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')
    print(f'repeated-word misplacements: {len(moves)} mechanical, {len(review)} for review → {rq}')
    with open(args.out, 'w', encoding='utf-8') as f:
        for r in recs:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')
    c = collections.Counter(r['status'] for r in recs)
    print(f'{len(recs)} chained items:', dict(c.most_common()))
    print('conditional:', dict(collections.Counter(r['status'] for r in recs if r['conditional'])))
    print('far-window:', dict(collections.Counter(r['status'] for r in recs if r['far'])))
    print('written', args.out)


if __name__ == '__main__':
    main()
