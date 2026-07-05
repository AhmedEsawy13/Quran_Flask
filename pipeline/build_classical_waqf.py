#!/usr/bin/env python3
"""Align the classical وقف-وابتدا literature to QPC word positions.

Sources (OpenITI machine-readable editions of public-domain classical works,
vendored under pipeline/classical_sources/):

  muktafa — المكتفى في الوقف والابتدا، أبو عمرو الداني (ت 444هـ)
            Shamela 26461 · sequential per-surah entries: {quote} grade علّة.
            Aligned with a forward cursor + back-window (the book flows in
            reading order); comparative citations are flagged conf=0 and never
            advance the cursor (one leap would poison the rest of the surah).

  manar   — منار الهدى في بيان الوقف والابتدا، أحمد الأشموني (ق 11هـ)
            Shamela 6496 · entries carry the verse number: {quote} [n] grade؛
            aligned WITHIN that ayah (±1 for verse-count differences) — no
            cursor needed, so a much larger and safer haul (~9k entries).

Both land in data/classical_waqf.db, table `classical`, with a `source`
column. Unmatched entries are kept (wpos NULL) for coverage audits.

Run:  python3 pipeline/build_classical_waqf.py          # build + stats
      python3 pipeline/build_classical_waqf.py --dry    # stats only
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

SRC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'classical_sources')
OUT_DB = os.path.join(app._BASE_DIR, 'data', 'classical_waqf.db')

SOURCES = {
    'muktafa': 'muktafa_dani_shamela26461.md',
    'manar':   'manar_ashmuni_shamela6496.md',
    'nahhas':  'qatc_nahhas_sham19_20966.md',
    'anbari':  'idah_anbari_sham19_14255.md',
}

# Surah-name aliases the books use that differ from surahs.json names.
ALIASES = {
    'أم القرآن': 1, 'فاتحة الكتاب': 1, 'الفاتحة': 1,
    'بني إسرائيل': 17, 'بنى إسرائيل': 17, 'الإسراء': 17,
    'الملائكة': 35, 'المؤمن': 40, 'حم السجدة': 41, 'المصابيح': 41,
    'محمد صلى الله عليه وسلم': 47, 'القتال': 47,
    'اقتربت': 54, 'قد سمع': 58, 'الممتحنة': 60, 'التغابن': 64,
    'عم يتساءلون': 78, 'النبأ': 78, 'التطفيف': 83, 'المطففين': 83,
    'سبح': 87, 'الأعلى': 87, 'البرية': 98, 'قاف': 50,
    'السجدة': 41,   # المكتفى titles BOTH 32 and فصلت «السجدة»; order picks
    'ألم نشرح': 94, 'الشرح': 94, 'اقرأ': 96, 'العلق': 96,
    'لم يكن': 98, 'البينة': 98, 'الزلزلة': 99, 'إذا زلزلت': 99,
    'ألهاكم': 102, 'التكاثر': 102, 'أرأيت': 107, 'الدين': 107, 'الماعون': 107,
    'تبت': 111, 'المسد': 111, 'الإخلاص': 112, 'قل هو الله أحد': 112,
}

# Grade phrases, longest-first so «أكفى منه» wins over «كاف» etc.
GRADES = [
    ('ليس بوقف منصوص عليه', 'لا'), ('ليس بوقف', 'لا'), ('لا يوقف عليه', 'لا'),
    ('لا وقف', 'لا'), ('ليس بتام ولا كاف', 'لا'),
    ('أكفى منه', 'كاف'), ('أكفى', 'كاف'), ('أتم', 'تام'),
    ('أحسن منه', 'حسن'), ('أحسن', 'حسن'),
    ('تام', 'تام'), ('كاف', 'كاف'), ('حسن', 'حسن'),
    ('جائز', 'جائز'), ('صالح', 'صالح'), ('قبيح', 'قبيح'),
]
GRADE_RE = re.compile(
    r'^[\s:،.؛]*(?:وقف\s+)?(' + '|'.join(re.escape(g) for g, _ in GRADES) + r')\b')

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


def load_book(fname):
    raw = open(os.path.join(SRC_DIR, fname), encoding='utf-8').read()
    body = raw.split('#META#Header#End#', 1)[1]
    body = re.sub(r'PageV\d+P\d+', ' ', body)
    body = re.sub(r'\bms\d+\b', ' ', body)
    # join OpenITI ~~ continuation lines, drop the '# ' paragraph markers
    body = body.replace('\n~~', ' ').replace('\n# ', '\n')
    return body


def surah_number(title, last=0):
    """Resolve a section title to a surah number. The books run in mushaf
    order, so among all plausible candidates take the first one AFTER the
    previously-resolved surah — this disambiguates e.g. المكتفى's two
    sections both titled «سورة السجدة» (32, then فصلت 41)."""
    t = re.sub(r'\[.*?\]|عليها?م? السلام|صلى الله عليه وسلم', '', title).strip()
    tn = norm(t.replace('سورة', ' ').strip())
    if not tn:
        return None
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


# Grammatical prefixes the books drop when quoting the bare stop word — the
# mushaf has «لِّلۡمُتَّقِينَ» where الداني grades «المتقين».
_PREFIXES = ('وال', 'فال', 'بال', 'كال', 'ولل', 'فلل', 'لل', 'ال',
             'وب', 'ول', 'وك', 'فب', 'فل', 'فك', 'و', 'ف', 'ب', 'ل', 'ك')


def _prefix_forms(w):
    yield w
    for p in _PREFIXES:
        if w.startswith(p) and len(w) - len(p) >= 2:
            yield w[len(p):]


def match_word(a, b, level):
    """level 1 = equality modulo ONE grammatical prefix on either side;
    level 2 also allows tight fuzz (Uthmani orthography residue only)."""
    if a == b:
        return True
    forms_a, forms_b = set(_prefix_forms(a)), set(_prefix_forms(b))
    if forms_a & forms_b:
        return True
    if level < 2:
        return False
    # Loose thresholds matched ينفقون onto يظنون — keep this tight.
    if a[:1] == b[:1] and abs(len(a) - len(b)) <= 2 and len(a) >= 4:
        return difflib.SequenceMatcher(None, a, b).ratio() >= 0.8
    return False


def quote_words(quote):
    """Normalised Arabic words of a quote, with footnote/ayah digits dropped."""
    q = re.sub(r'\(\s*\d+\s*\)', ' ', quote)
    return [w for w in (norm(t) for t in re.findall(r'[؀-ۿ]+', q)) if w]


def clean_note(text, limit=500):
    text = re.sub(r'\(\s*\d+\s*\)', '', text)
    text = re.sub(r'\s+', ' ', text).strip(' .،:؛')
    if len(text) <= limit:
        return text
    # Cut on a WORD boundary (never mid-word) and mark the elision, so the
    # displayed علّة never ends on a half-word.
    cut = text[:limit]
    sp = cut.rfind(' ')
    if sp > limit * 0.6:
        cut = cut[:sp]
    return cut.rstrip(' .،:؛') + ' …'


# ─────────────────────────── المكتفى (cursor-based) ───────────────────────────

# No next-brace lookahead: the grade sits at the START of the tail, and a
# lookahead silently dropped every entry whose reasoning ran longer than the
# tail cap before the next quote (e.g. منار's {وعلى سمعهم} [7] تام).
ENTRY_RE = re.compile(r'(?:\{([^{}]{1,120})\}|\(\(([^()]{1,80})\)\))([^{}(]{0,90})', re.S)
_BACK_WINDOW = 40


def parse_muktafa_entries(section_text):
    out = []
    for m in ENTRY_RE.finditer(section_text):
        quote = (m.group(1) or m.group(2) or '').strip()
        tail = m.group(3) or ''
        gm = GRADE_RE.match(tail)
        if not quote:
            continue
        if not gm:
            # «ومثله {X}، ومثله {Y}» chains inherit the previous entry's grade.
            lead = section_text[max(0, m.start() - 14):m.start()]
            if out and re.search(r'(ومثله|وكذلك|ومثلها|ونحوه)\s*[:،]?\s*$', lead):
                prev = out[-1]
                out.append({'quote': quote, 'grade_raw': prev['grade_raw'],
                            'grade': prev['grade'], 'pos': m.start(),
                            'note_from': m.start(3)})
            continue
        raw = gm.group(1)
        out.append({'quote': quote, 'grade_raw': raw, 'grade': dict(GRADES)[raw],
                    'pos': m.start(), 'note_from': m.start(3) + gm.end()})
    for i, e in enumerate(out):
        end = out[i + 1]['pos'] if i + 1 < len(out) else min(len(section_text), e['note_from'] + 600)
        e['note'] = clean_note(section_text[e['note_from']:end])
    return out


_AYAH_COUNT = {}


def surah_ayah_count(surah):
    if surah not in _AYAH_COUNT:
        n = 0
        while f'{surah}:{n + 1}' in app.qpc_hafs_data_normalized:
            n += 1
        _AYAH_COUNT[surah] = n
    return _AYAH_COUNT[surah]


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


def align_cursor(stream, cursor, qwords):
    """Consecutive tail match near/after cursor. Precise (strict+prefix) runs
    position-first everywhere before fuzzy, so a fuzzy near-miss can never
    shadow the true exact position."""
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


def harvest_muktafa(body, rows, seq0):
    seq = seq0
    unmatched = 0
    last_num = 0
    for sec in re.split(r'\n### \| ', body):
        title, _, text = sec.partition('\n')
        if 'سورة' not in title and 'أم القرآن' not in title:
            continue
        num = surah_number(title, last_num)
        if num is None:
            continue
        last_num = num
        stream = build_stream(num)
        cursor = 0
        for e in parse_muktafa_entries(text):
            qwords = quote_words(e['quote'])
            if not qwords:
                continue
            cursor_before = cursor
            hit, cursor = align_cursor(stream, cursor, qwords)
            seq += 1
            if hit is None:
                unmatched += 1
                rows.append(('muktafa', num, None, None, None, e['quote'],
                             e['grade'], e['grade_raw'], e['note'], seq, 0))
                continue
            # Confidence: comparative citations (quotes from elsewhere) show up
            # as jumps; flag them AND keep the cursor put — one leap otherwise
            # strands every later correct match and poisons the whole surah.
            conf = 1
            if '.' in e['quote']:
                conf = 0
            elif cursor_before > 0 and (hit < cursor_before - _BACK_WINDOW
                                        or hit > cursor_before + 300):
                conf = 0
            if conf == 0:
                cursor = cursor_before
            ayah, wpos, _ = stream[hit]
            _, words, _ = app._verse_word_texts(f'{num}:{ayah}')
            rows.append(('muktafa', num, ayah, wpos, words[wpos], e['quote'],
                         e['grade'], e['grade_raw'], e['note'], seq, conf))
    return seq, unmatched


# ─────────────────────── منار الهدى (ayah-anchored) ───────────────────────────
# منار quotes verses in BOTH {…} and «…» (the guillemet form is ~half its
# quotes — mostly the «الوقف على «X» تام» / «ومثله «X»» references that lack
# their own [n] and belong to the ayah currently under discussion).
_MANAR_QUOTE_RE = re.compile(r'\{([^{}]{1,120})\}|«([^«»]{1,80})»')
_MANAR_AYAH_RE = re.compile(r'\[(\d{1,3})\]')
_MITHL_RE = re.compile(r'(ومثله|ومثلها|وكذلك|ونحوه|ونحوها)\s*[:،]?\s*$')


def align_in_ayah(surah, ayah, qwords):
    """Match the quote tail inside ONE ayah (the book gives the verse number).
    Returns wpos or None. If the cleaned quote had no words (pure ayah-end
    marker like {(4)}), the stop is the verse's last word."""
    vk = f'{surah}:{ayah}'
    if vk not in app.qpc_hafs_data_normalized:
        return None
    _, words, _ = app._verse_word_texts(vk)
    wnorm = [norm(w) for w in words]
    if not qwords:
        return len(words) - 1 if words else None
    for level in (1, 2):
        for k in (min(3, len(qwords)), 2, 1):
            if k > len(qwords) or k < 1:
                continue
            tail = qwords[-k:]
            for i in range(len(wnorm) - k, -1, -1):     # prefer the LAST occurrence
                if all(match_word(tail[j], wnorm[i + j], level) for j in range(k)):
                    return i + k - 1
    return None


def harvest_manar(body, rows, seq0):
    seq = seq0
    unmatched = 0
    last_num = 0
    current = None
    for sec in re.split(r'\n### \| ', body):
        title, _, text = sec.partition('\n')
        num = surah_number(title, last_num) if 'سورة' in title else None
        if num is not None:
            current, last_num = num, num
        if current is None:
            continue
        # the ayah under discussion at any text offset = the most recent [n].
        # Filter footnote markers: منار's [n] is usually the ayah number but
        # sometimes a footnote (e.g. «لا ريب فيه» [9] in سورة البقرة), so only
        # keep [n] that is a plausible ayah for this surah.
        acount = surah_ayah_count(current)
        markers = [(m.start(), int(m.group(1))) for m in _MANAR_AYAH_RE.finditer(text)
                   if 1 <= int(m.group(1)) <= acount]

        def ayah_at(pos):
            a = None
            for mp, mv in markers:
                if mp <= pos:
                    a = mv
                else:
                    break
            return a

        quotes = list(_MANAR_QUOTE_RE.finditer(text))
        prev = None      # (raw, grade) for ومثله inheritance
        for idx, m in enumerate(quotes):
            quote = (m.group(1) or m.group(2) or '').strip()
            nxt = quotes[idx + 1].start() if idx + 1 < len(quotes) else len(text)
            after = text[m.end():min(nxt, m.end() + 90)]
            own = re.match(r'[\s،:]{0,3}\[(\d{1,3})\]', after)   # the quote's own [n]?
            own_ayah = int(own.group(1)) if own else None
            if own_ayah is not None and not (1 <= own_ayah <= acount):
                own_ayah = None                                  # footnote, not an ayah
            gtail = (after[own.end():] if own else after).lstrip(' ،:؛')
            gm = GRADE_RE.match(gtail)
            before = text[max(0, m.start() - 14):m.start()]
            is_mithl = bool(_MITHL_RE.search(before))
            if gm:
                raw = gm.group(1)
                grade = dict(GRADES)[raw]
            elif is_mithl and prev:
                raw, grade = prev
            else:
                continue
            prev = (raw, grade)
            ayah = own_ayah if own_ayah is not None else ayah_at(m.start())
            if not ayah:
                continue
            qwords = quote_words(quote)
            if not qwords:
                continue
            note = clean_note(text[m.end():min(nxt, m.end() + 600)])
            seq += 1
            wpos, hit_ayah = None, None
            for a in (ayah, ayah + 1, ayah - 1):        # tolerate verse-count drift
                if a < 1:
                    continue
                wpos = align_in_ayah(current, a, qwords)
                if wpos is not None:
                    hit_ayah = a
                    break
            if wpos is None:
                unmatched += 1
                rows.append(('manar', current, None, None, None, quote, grade, raw, note, seq, 0))
                continue
            # High confidence: the entry had its own [n] and matched it, OR a
            # multi-word reference landed in the discussed ayah. Single-word
            # guillemet refs (ambiguous placement) stay conf=0.
            if own_ayah is not None:
                conf = 1 if hit_ayah == own_ayah else 0
            else:
                conf = 1 if (hit_ayah == ayah and len(qwords) >= 2) else 0
            _, words, _ = app._verse_word_texts(f'{current}:{hit_ayah}')
            rows.append(('manar', current, hit_ayah, wpos, words[wpos], quote, grade, raw, note, seq, conf))
    return seq, unmatched


# ─────────────────────── النحاس (discursive, cursor-based) ────────────────────
# القطع والائتناف is prose, not a stop list. His signature is the grade-BEFORE
# form «التمام {X}» / «الكافي {X}» (definite article = "THE perfect stop IS X"),
# plus a grade-after «{X} تمام / كاف / ليس بوقف». Two precision guards:
#  · grade-before is taken ONLY with the definite article — bare «تمام {X}» is
#    almost always a NEGATION («غير تمام», «ليس بتمام»).
#  · grade-after is checked FIRST (it grades THIS quote); a definite grade-before
#    is the fallback. So «غير تمام {X} كاف» → كاف (after), not تام.
_NAHHAS_AFTER = [('ليس بموضع قطع', 'لا'), ('ليس بوقف', 'لا'), ('لا يوقف عليه', 'لا'),
                 ('تمام', 'تام'), ('تام', 'تام'), ('كافٍ', 'كاف'), ('كاف', 'كاف'),
                 ('حسن', 'حسن'), ('صالح', 'صالح')]
_NAHHAS_BEFORE = [('والتمام', 'تام'), ('التمام', 'تام'), ('فالتمام', 'تام'),
                  ('والتام', 'تام'), ('التام', 'تام'),
                  ('والكافي', 'كاف'), ('الكافي', 'كاف'), ('فالكافي', 'كاف'),
                  ('والحسن', 'حسن'), ('الحسن', 'حسن')]
_NAHHAS_AFTER_RE = re.compile(
    r'\{([^{}]{1,90})\}[\s،]{0,3}(' + '|'.join(re.escape(g) for g, _ in _NAHHAS_AFTER) + r')(?=[\s،.]|$)')
_NAHHAS_BEFORE_RE = re.compile(
    r'(?:^|[\s،.])(' + '|'.join(re.escape(g) for g, _ in _NAHHAS_BEFORE) + r')\s{0,2}\{([^{}]{1,90})\}')
_AFTER_MAP = dict(_NAHHAS_AFTER)
_BEFORE_MAP = dict(_NAHHAS_BEFORE)


def harvest_nahhas(body, rows, seq0):
    seq = seq0
    unmatched = 0
    last_num = 0
    for sec in re.split(r'\n### \|+ ?', body):
        title, _, text = sec.partition('\n')
        title = re.sub(r'^(AUTO|CHECK)\s*', '', title.strip())
        if 'سورة' not in title:
            continue
        num = surah_number(title, last_num)
        if num is None:
            continue
        last_num = num
        stream = build_stream(num)
        cursor = 0
        # collect entries (quote, grade) by position, after-grade wins over before.
        entries = {}   # start-offset → (quote, grade)
        for m in _NAHHAS_AFTER_RE.finditer(text):
            entries[m.start(1)] = (m.group(1), _AFTER_MAP[m.group(2)], m.end())
        for m in _NAHHAS_BEFORE_RE.finditer(text):
            entries.setdefault(m.start(2), (m.group(2), _BEFORE_MAP[m.group(1)], m.end()))
        for pos in sorted(entries):
            quote, grade, note_from = entries[pos]
            qwords = quote_words(quote)
            if not qwords:
                continue
            cursor_before = cursor
            hit, cursor = align_cursor(stream, cursor, qwords)
            seq += 1
            note = clean_note(text[note_from:note_from + 400])
            if hit is None:
                unmatched += 1
                rows.append(('nahhas', num, None, None, None, quote, grade, grade, note, seq, 0))
                continue
            conf = 1
            if cursor_before > 0 and (hit < cursor_before - _BACK_WINDOW or hit > cursor_before + 300):
                conf = 0
                cursor = cursor_before
            ayah, wpos, _ = stream[hit]
            _, words, _ = app._verse_word_texts(f'{num}:{ayah}')
            rows.append(('nahhas', num, ayah, wpos, words[wpos], quote, grade, grade, note, seq, conf))
    return seq, unmatched


# ─────────────────── ابن الأنباري (parenthesised, ayah-anchored) ──────────────
# إيضاح الوقف والابتداء quotes verses in ( … ) and grades DENSELY, often several
# stops per verse in prose: «الوقف على (بسم) قبيح … والوقف على (الرحيم) تام».
# So we must capture قبيح (his commonest ruling!) and أحسن/أتم — and his [n]
# markers are frequent enough that a single-word stop in the current ayah is
# trustworthy. «غير تام»/«لا يتم» are NOT extracted (ambiguous: "not COMPLETE"
# ≠ forbidden; may still be كاف).
_ANBARI_ENTRY_RE = re.compile(r'\(([^()]{2,120})\)\s*(?:\[(\d{1,3})\])?([^()]{0,60})')
_ANBARI_GRADE_RE = re.compile(
    r'^[\s،:؛]*(?:وقف\s+)?(لا يحسن الوقف|ليس بوقف|لا يوقف|التمام|التام|أتم|تمام|تام'
    r'|كافٍ|كاف|أحسن|حسن|صالح|قبيح)(?=[\s،.]|$)')
_ANBARI_MAP = {'التمام': 'تام', 'التام': 'تام', 'أتم': 'تام', 'تمام': 'تام', 'تام': 'تام',
               'كافٍ': 'كاف', 'كاف': 'كاف', 'أحسن': 'حسن', 'حسن': 'حسن', 'صالح': 'صالح',
               'قبيح': 'قبيح', 'لا يحسن الوقف': 'قبيح', 'ليس بوقف': 'لا', 'لا يوقف': 'لا'}


def harvest_anbari(body, rows, seq0):
    seq = seq0
    unmatched = 0
    last_num = 0
    for sec in re.split(r'\n### \|+ ?', body):
        title, _, text = sec.partition('\n')
        title = re.sub(r'^(AUTO|CHECK)\s*', '', title.strip())
        # ابن الأنباري titles surahs three ways: «سورة X» (مريم onward),
        # «السورة التي تذكر فيها X» (early surahs), and «فاتحة الكتاب» for
        # الفاتحة — which lacks «سورة» and was being skipped entirely.
        if 'سورة' not in title and 'فاتحة' not in title:
            continue
        num = surah_number(title, last_num)
        if num is None:
            continue
        last_num = num
        acount = surah_ayah_count(num)
        cur_ayah = 1                       # ayah context for entries lacking [n]
        prev = None                        # (raw, grade) for ومثله inheritance
        entries = list(_ANBARI_ENTRY_RE.finditer(text))
        for idx, m in enumerate(entries):
            quote = m.group(1).strip()
            own = int(m.group(2)) if m.group(2) and 1 <= int(m.group(2)) <= acount else None
            gm = _ANBARI_GRADE_RE.match(m.group(3) or '')
            before = text[max(0, m.start() - 14):m.start()]
            is_mithl = bool(_MITHL_RE.search(before))
            if gm:
                raw = gm.group(1)
                grade = _ANBARI_MAP[raw]
            elif is_mithl and prev:
                raw, grade = prev
            else:
                if own is not None:
                    cur_ayah = own
                continue
            prev = (raw, grade)
            ayah = own if own is not None else cur_ayah
            cur_ayah = ayah
            qwords = quote_words(quote)
            if not qwords:
                continue
            nxt = entries[idx + 1].start() if idx + 1 < len(entries) else len(text)
            note = clean_note(text[m.end():min(nxt, m.end() + 600)])
            seq += 1
            wpos, hit_ayah = None, None
            for a in (ayah, ayah + 1, ayah - 1):
                if a < 1:
                    continue
                wpos = align_in_ayah(num, a, qwords)
                if wpos is not None:
                    hit_ayah = a
                    break
            if wpos is None:
                unmatched += 1
                rows.append(('anbari', num, None, None, None, quote, grade, grade, note, seq, 0))
                continue
            # ابن الأنباري anchors densely ([n] most verses) and grades stop by
            # stop, so a hit in the intended ayah is trustworthy even for a
            # single word (align_in_ayah takes the last occurrence = the stop).
            if own is not None:
                conf = 1 if hit_ayah == own else 0
            else:
                conf = 1 if hit_ayah == ayah else 0
            _, words, _ = app._verse_word_texts(f'{num}:{hit_ayah}')
            rows.append(('anbari', num, hit_ayah, wpos, words[wpos], quote, grade, grade, note, seq, conf))
    return seq, unmatched


# ────────────────────────────────── main ─────────────────────────────────────

def main():
    dry = '--dry' in sys.argv
    rows = []
    seq, un_muk = harvest_muktafa(load_book(SOURCES['muktafa']), rows, 0)
    seq, un_man = harvest_manar(load_book(SOURCES['manar']), rows, seq)
    seq, un_nah = harvest_nahhas(load_book(SOURCES['nahhas']), rows, seq)
    seq, un_anb = harvest_anbari(load_book(SOURCES['anbari']), rows, seq)

    from collections import Counter
    for src, un in (('muktafa', un_muk), ('manar', un_man), ('nahhas', un_nah), ('anbari', un_anb)):
        sub = [r for r in rows if r[0] == src]
        conf = sum(1 for r in sub if r[10])
        print(f'{src:8} entries: {len(sub):5}  matched: {len(sub) - un} '
              f'({(len(sub) - un) / len(sub) * 100:.1f}%)  confident: {conf} '
              f'({conf / len(sub) * 100:.1f}%)  grades: '
              f'{dict(Counter(r[6] for r in sub).most_common(6))}')

    if dry:
        return
    conn = sqlite3.connect(OUT_DB)
    conn.execute('DROP TABLE IF EXISTS classical')
    conn.execute('DROP TABLE IF EXISTS muktafa')       # superseded schema
    conn.execute('''CREATE TABLE classical (
        id INTEGER PRIMARY KEY, source TEXT NOT NULL, surah INTEGER NOT NULL,
        ayah INTEGER, wpos INTEGER, stop_word TEXT, quote TEXT NOT NULL,
        grade TEXT NOT NULL, grade_raw TEXT NOT NULL, note TEXT, seq INTEGER,
        conf INTEGER NOT NULL DEFAULT 1)''')
    conn.execute('CREATE INDEX idx_classical_verse ON classical(surah, ayah)')
    conn.executemany(
        'INSERT INTO classical (source, surah, ayah, wpos, stop_word, quote, '
        'grade, grade_raw, note, seq, conf) VALUES (?,?,?,?,?,?,?,?,?,?,?)', rows)
    conn.commit()
    conn.close()
    print(f'wrote {OUT_DB}')


if __name__ == '__main__':
    main()
