#!/usr/bin/env python3
"""Align المكتفى في الوقف والابتدا (أبو عمرو الداني، ت 444هـ) to QPC word positions.

Source text: OpenITI machine-readable edition (Shamela 0026461, دار عمار 2001,
ed. محيي الدين رمضان) — public-domain classical work, downloaded to
pipeline/classical_sources/muktafa_dani_shamela26461.md.

The book walks each surah in reading order, quoting the stop word/phrase and
grading it — تام / كاف / حسن / صالح / قبيح (or "ليس بوقف") — usually followed
by the grammatical reasoning. This script:

  1. parses every {quote} → grade → reasoning entry per surah,
  2. aligns the quote's LAST word onto the recited-word stream (the same wpos
     space as _verse_word_texts / the مُكْث matrix), using a forward cursor —
     the book is sequential, so each entry matches at-or-after the previous —
     with imlāʾī↔Uthmani folding and a fuzzy fallback,
  3. writes data/classical_waqf.db (table muktafa) incl. unmatched entries
     (wpos NULL) so coverage can be audited.

Run:  python3 pipeline/build_muktafa.py           # writes DB + prints stats
      python3 pipeline/build_muktafa.py --dry     # stats only
"""
import difflib
import os
import re
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('RESEARCH_PRECOMPUTE', '1')   # skip disk caches on import

import app  # noqa: E402
from core.text import _normalize_for_search  # noqa: E402

SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   'classical_sources', 'muktafa_dani_shamela26461.md')
OUT_DB = os.path.join(app._BASE_DIR, 'data', 'classical_waqf.db')

# Surah-name aliases the book uses that differ from surahs.json names.
ALIASES = {
    'أم القرآن': 1, 'فاتحة الكتاب': 1,
    'بني إسرائيل': 17, 'بنى إسرائيل': 17,
    'الملائكة': 35, 'المؤمن': 40, 'حم السجدة': 41, 'المصابيح': 41,
    'محمد صلى الله عليه وسلم': 47, 'القتال': 47,
    'اقتربت': 54, 'قد سمع': 58, 'الممتحنة': 60, 'التغابن': 64,
    'عم يتساءلون': 78, 'التطفيف': 83, 'المطففين': 83,
    'سبح': 87, 'الأعلى': 87, 'البرية': 98, 'قاف': 50,
    'السجدة': 41,   # the book titles BOTH 32 and فصلت as «السجدة»; order picks
    'ألم نشرح': 94, 'الشرح': 94, 'اقرأ': 96, 'العلق': 96,
    'لم يكن': 98, 'البينة': 98, 'الزلزلة': 99, 'إذا زلزلت': 99,
    'ألهاكم': 102, 'التكاثر': 102, 'أرأيت': 107, 'الدين': 107, 'الماعون': 107,
    'تبت': 111, 'المسد': 111, 'الإخلاص': 112, 'قل هو الله أحد': 112,
}

# Grade phrases, longest-first so e.g. «أكفى منه» wins over «كاف».
GRADES = [
    ('ليس بوقف', 'لا'), ('لا يوقف عليه', 'لا'), ('لا وقف', 'لا'),
    ('ليس بتام ولا كاف', 'لا'),
    ('أكفى منه', 'كاف'), ('أكفى', 'كاف'), ('أتم', 'تام'),
    ('تام', 'تام'), ('كاف', 'كاف'), ('حسن', 'حسن'),
    ('صالح', 'صالح'), ('قبيح', 'قبيح'),
]
GRADE_RE = re.compile(
    r'^[\s:،.]*(?:وقف\s+)?(' + '|'.join(re.escape(g) for g, _ in GRADES) + r')\b')

# Uthmani → imlāʾī folds applied AFTER _normalize_for_search stripping, so both
# sides land on the same skeleton (الصلوة/الصلاة، الزكوة، الحيوة، الربوا…).
_POST_FOLDS = [
    ('صلوه', 'صلاه'), ('زكوه', 'زكاه'), ('حيوه', 'حياه'), ('نجوه', 'نجاه'),
    ('غدوه', 'غداه'), ('مشكوه', 'مشكاه'), ('منوه', 'مناه'), ('ربوا', 'ربا'),
]


def norm(tok):
    t = _normalize_for_search(tok)
    for a, b in _POST_FOLDS:
        t = t.replace(a, b)
    return t


def load_book():
    raw = open(SRC, encoding='utf-8').read()
    body = raw.split('#META#Header#End#', 1)[1]
    body = re.sub(r'PageV\d+P\d+', ' ', body)
    body = re.sub(r'\bms\d+\b', ' ', body)
    # join OpenITI ~~ continuation lines, drop the '# ' paragraph markers
    body = body.replace('\n~~', ' ').replace('\n# ', '\n')
    return body


def surah_number(title, last=0):
    """Resolve a section title to a surah number. The book runs in mushaf
    order, so among all plausible candidates we take the first one AFTER the
    previously-resolved surah — this is what disambiguates the two sections
    both titled «سورة السجدة» (32, then فصلت 41)."""
    t = re.sub(r'\[.*?\]|عليها?م? السلام|صلى الله عليه وسلم', '', title).strip()
    tn = norm(t.replace('سورة', ' ').strip())
    cands = set()
    for name, num in ALIASES.items():
        if norm(name) in tn:
            cands.add(num)
    for s in app.surahs_data:
        n = norm(s.get('name', ''))
        if not n:
            continue
        if n == tn or norm('ال') + n == tn or n == norm('ال') + tn:
            cands.add(int(s['number']))
        # containment fallback (e.g. «يونس عليه السلام») — require a real word,
        # not a 1-2 letter name like «ق» hiding inside «القرآن».
        elif len(n) >= 3 and n in tn:
            cands.add(int(s['number']))
    if not cands:
        return None
    ahead = sorted(c for c in cands if c > last)
    return ahead[0] if ahead else max(cands)


# entry = quote in {...} or ((...)) immediately followed by a grade phrase
ENTRY_RE = re.compile(r'(?:\{([^{}]{1,120})\}|\(\(([^()]{1,80})\)\))([^{}(]{0,90}?)'
                      r'(?=\{|\(\(|$)', re.S)


def parse_entries(section_text):
    """Yield (quote, grade_raw, grade, note_start_offset, end_offset)."""
    out = []
    for m in ENTRY_RE.finditer(section_text):
        quote = (m.group(1) or m.group(2) or '').strip()
        tail = m.group(3) or ''
        gm = GRADE_RE.match(tail)
        if not quote:
            continue
        if not gm:
            # «ومثله {X}، ومثله {Y}» chains: a grade-less quote right after
            # ومثله/وكذلك inherits the previous entry's grade.
            lead = section_text[max(0, m.start() - 14):m.start()]
            if out and re.search(r'(ومثله|وكذلك|ومثلها|ونحوه)\s*[:،]?\s*$', lead):
                prev = out[-1]
                out.append({'quote': quote, 'grade_raw': prev['grade_raw'],
                            'grade': prev['grade'], 'pos': m.start(),
                            'note_from': m.start(3), 'inherited': True})
            continue
        raw = gm.group(1)
        canon = dict(GRADES)[raw]
        out.append({'quote': quote, 'grade_raw': raw, 'grade': canon,
                    'pos': m.start(), 'note_from': m.start(3) + gm.end()})
    # note = text until the next entry's quote (the reasoning that follows)
    for i, e in enumerate(out):
        end = out[i + 1]['pos'] if i + 1 < len(out) else min(len(section_text), e['note_from'] + 600)
        note = section_text[e['note_from']:end]
        note = re.sub(r'\s+', ' ', note).strip(' .،:؛')
        e['note'] = note[:500]
    return out


def build_stream(surah):
    """[(ayah, wpos, norm_word)] for the whole surah in reading order."""
    stream = []
    ayah = 1
    while True:
        vk = f'{surah}:{ayah}'
        if vk not in app.qpc_hafs_data_normalized:
            break
        _, words, _ = app._verse_word_texts(vk)
        for w, tok in enumerate(words):
            n = norm(tok)
            if n:
                stream.append((ayah, w, n))
        ayah += 1
    return stream


# Grammatical prefixes the book drops when quoting the bare stop word — the
# mushaf has «لِّلۡمُتَّقِينَ» where the book grades «المتقين».
_PREFIXES = ('وال', 'فال', 'بال', 'كال', 'ولل', 'فلل', 'لل', 'ال',
             'وب', 'ول', 'وك', 'فب', 'فل', 'فك', 'و', 'ف', 'ب', 'ل', 'ك')


def _prefix_forms(w):
    yield w
    for p in _PREFIXES:
        if w.startswith(p) and len(w) - len(p) >= 2:
            yield w[len(p):]


def match_word(a, b, level):
    """level 0 = strict equality; 1 = equality modulo ONE grammatical prefix
    on either side; 2 = tight fuzzy (Uthmani orthography residue only)."""
    if a == b:
        return True
    if level == 0:
        return False
    forms_a, forms_b = set(_prefix_forms(a)), set(_prefix_forms(b))
    if forms_a & forms_b:
        return True
    if level < 2:
        return False
    # Loose thresholds matched ينفقون onto يظنون — keep this tight.
    if a[:1] == b[:1] and abs(len(a) - len(b)) <= 2 and len(a) >= 4:
        return difflib.SequenceMatcher(None, a, b).ratio() >= 0.8
    return False


# The book often re-grades the SAME stop in the following discussion; allow the
# scan to start a little behind the cursor so those re-references don't get
# pushed onto the next occurrence of the word.
_BACK_WINDOW = 40


def align(stream, cursor, qwords):
    """Find qwords (tail of the quote) as consecutive stream words near/after
    cursor. Exact matching is tried EVERYWHERE before any fuzzy matching, so a
    fuzzy near-miss can never shadow the true exact position. Returns (index
    of the LAST matched stream slot, new cursor) or (None, cursor)."""
    # Levels 0+1 are both high-precision (strict / prefix-stripped equality),
    # so they run as ONE position-first pass — otherwise a strict match far
    # ahead (المتقين at 2:180) outranks the true prefixed word nearby
    # (لِّلۡمُتَّقِينَ at 2:2). Fuzzy stays a separate last resort.
    for level in (1, 2):
        for k in (min(3, len(qwords)), 2, 1):
            if k > len(qwords) or k < 1:
                continue
            tail = qwords[-k:]
            for start in (max(0, cursor - _BACK_WINDOW), 0):
                i = start
                while i <= len(stream) - k:
                    if all(match_word(tail[j], stream[i + j][2], level) for j in range(k)):
                        end = i + k - 1
                        return end, max(cursor, end + 1)
                    i += 1
                if start == 0:
                    break
    return None, cursor


def main():
    dry = '--dry' in sys.argv
    body = load_book()
    sections = re.split(r'\n### \| ', body)
    rows, unmatched, no_surah = [], 0, []
    seq = 0
    last_num = 0
    for sec in sections:
        title, _, text = sec.partition('\n')
        if 'سورة' not in title and 'أم القرآن' not in title:
            continue
        num = surah_number(title, last_num)
        if num is None:
            no_surah.append(title.strip())
            continue
        last_num = num
        stream = build_stream(num)
        cursor = 0
        for e in parse_entries(text):
            qwords = [norm(w) for w in re.findall(r'[؀-ۿ]+', e['quote'])]
            qwords = [w for w in qwords if w]
            if not qwords:
                continue
            cursor_before = cursor
            hit, cursor = align(stream, cursor, qwords)
            seq += 1
            if hit is None:
                unmatched += 1
                rows.append((num, None, None, None, e['quote'], e['grade'],
                             e['grade_raw'], e['note'], seq, 0))
            else:
                # Confidence: the book flows forward. A match far behind the
                # cursor or leaping far ahead is usually a COMPARATIVE citation
                # (a verse quoted from elsewhere as an analogy), not the surah's
                # own next stop — keep it, but flagged, so the UI can filter.
                conf = 1
                if '.' in e['quote']:
                    conf = 0            # multi-fragment quote {X. Y} = citation
                elif cursor_before > 0 and (hit < cursor_before - _BACK_WINDOW
                                            or hit > cursor_before + 300):
                    conf = 0
                if conf == 0:
                    # A citation/leap must NOT drag the cursor with it — one bad
                    # leap would strand every later (correct) match behind the
                    # cursor and poison the rest of the surah to conf=0.
                    cursor = cursor_before
                ayah, wpos, _ = stream[hit]
                _, words, _ = app._verse_word_texts(f'{num}:{ayah}')
                rows.append((num, ayah, wpos, words[wpos], e['quote'], e['grade'],
                             e['grade_raw'], e['note'], seq, conf))

    total = len(rows)
    matched = total - unmatched
    confident = sum(1 for r in rows if r[9])
    print(f'entries: {total}  matched: {matched} ({matched / total * 100:.1f}%)  '
          f'unmatched: {unmatched}  confident: {confident} ({confident / total * 100:.1f}%)')
    if no_surah:
        print('unmapped surah titles:', no_surah)
    from collections import Counter
    print('grades:', dict(Counter(r[5] for r in rows).most_common()))

    if dry:
        return
    os.makedirs(os.path.dirname(OUT_DB), exist_ok=True)
    conn = sqlite3.connect(OUT_DB)
    conn.execute('DROP TABLE IF EXISTS muktafa')
    conn.execute('''CREATE TABLE muktafa (
        id INTEGER PRIMARY KEY, surah INTEGER NOT NULL, ayah INTEGER,
        wpos INTEGER, stop_word TEXT, quote TEXT NOT NULL,
        grade TEXT NOT NULL, grade_raw TEXT NOT NULL, note TEXT, seq INTEGER,
        conf INTEGER NOT NULL DEFAULT 1)''')
    conn.execute('CREATE INDEX idx_muktafa_verse ON muktafa(surah, ayah)')
    conn.executemany(
        'INSERT INTO muktafa (surah, ayah, wpos, stop_word, quote, grade, grade_raw, note, seq, conf)'
        ' VALUES (?,?,?,?,?,?,?,?,?,?)', rows)
    conn.commit()
    conn.close()
    print(f'wrote {OUT_DB}')


if __name__ == '__main__':
    main()
