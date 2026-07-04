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
    return re.sub(r'\s+', ' ', text).strip(' .،:؛')[:limit]


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

MANAR_ENTRY_RE = re.compile(
    r'\{([^{}]{1,120})\}\s*\[(\d{1,3})\]([^{}]{0,80})', re.S)


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
        entries = list(MANAR_ENTRY_RE.finditer(text))
        for idx, m in enumerate(entries):
            quote, ayah_s, tail = m.group(1).strip(), m.group(2), m.group(3) or ''
            gm = GRADE_RE.match(tail)
            if not gm:
                continue
            ayah = int(ayah_s)
            raw = gm.group(1)
            note_end = entries[idx + 1].start() if idx + 1 < len(entries) else min(len(text), m.end() + 600)
            note = clean_note(text[m.start(3) + gm.end():note_end])
            qwords = quote_words(quote)
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
                rows.append(('manar', current, None, None, None, quote,
                             dict(GRADES)[raw], raw, note, seq, 0))
            else:
                _, words, _ = app._verse_word_texts(f'{current}:{hit_ayah}')
                conf = 1 if hit_ayah == ayah else 0
                rows.append(('manar', current, hit_ayah, wpos, words[wpos], quote,
                             dict(GRADES)[raw], raw, note, seq, conf))
    return seq, unmatched


# ────────────────────────────────── main ─────────────────────────────────────

def main():
    dry = '--dry' in sys.argv
    rows = []
    seq, un_muk = harvest_muktafa(load_book(SOURCES['muktafa']), rows, 0)
    seq, un_man = harvest_manar(load_book(SOURCES['manar']), rows, seq)

    from collections import Counter
    for src, un in (('muktafa', un_muk), ('manar', un_man)):
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
