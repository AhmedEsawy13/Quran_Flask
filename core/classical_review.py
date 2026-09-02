"""Deterministic accuracy metrics and local scholarly-review persistence."""
from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
from functools import lru_cache
from pathlib import Path

from core.config import CLASSICAL_REVIEW_DATABASE, CLASSICAL_WAQF_DATABASE, _BASE_DIR

MUKTAFA_SOURCE = Path(_BASE_DIR) / 'pipeline' / 'classical_sources' / 'muktafa_dani_shamela26461.md'
MANAR_REVIEW_QUEUE = Path(_BASE_DIR) / 'pipeline' / 'review' / 'manar_traceability.jsonl'
VALID_DECISIONS = {'approve', 'reject', 'pending'}
VALID_BOOK_DECISIONS = {'add', 'reject', 'pending'}
REVIEW_GRADE_LABELS = {
    'تام': 'تام',
    'كاف': 'كاف',
    'حسن': 'حسن',
    'جائز': 'جائز',
    'صالح': 'صالح',
    'قبيح': 'قبيح',
    'لا': 'ليس بوقف',
}
REVIEW_GRADE_OPTIONS = tuple(
    {'value': value, 'label': label}
    for value, label in REVIEW_GRADE_LABELS.items()
)


def _review_path(path=None):
    return path or CLASSICAL_REVIEW_DATABASE


def _connect_review(path=None):
    path = _review_path(path)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute('''CREATE TABLE IF NOT EXISTS classical_review_decisions (
        source TEXT NOT NULL, classical_id INTEGER NOT NULL,
        decision TEXT NOT NULL CHECK(decision IN ('approve','reject','pending')),
        reviewer_note TEXT NOT NULL DEFAULT '', corrected_surah INTEGER,
        corrected_ayah INTEGER, corrected_wpos INTEGER,
        corrected_grade TEXT,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY(source, classical_id))''')
    columns = {
        row['name'] for row in conn.execute(
            'PRAGMA table_info(classical_review_decisions)'
        ).fetchall()
    }
    if 'corrected_grade' not in columns:
        conn.execute(
            'ALTER TABLE classical_review_decisions ADD COLUMN corrected_grade TEXT'
        )
    conn.execute('''CREATE TABLE IF NOT EXISTS classical_review_books (
        source TEXT PRIMARY KEY,
        decision TEXT NOT NULL CHECK(decision IN ('add','reject','pending')),
        reviewer_note TEXT NOT NULL DEFAULT '',
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
    conn.commit()
    return conn


def decisions(source='muktafa', review_db=None):
    review_db = _review_path(review_db)
    if not os.path.exists(review_db):
        return {}
    conn = _connect_review(review_db)
    try:
        return {row['classical_id']: dict(row) for row in conn.execute(
            'SELECT * FROM classical_review_decisions WHERE source=?', (source,))}
    finally:
        conn.close()


def save_decision(classical_id, decision, note='', corrected=None,
                  source='muktafa', review_db=None, corrected_grade=None):
    if decision not in VALID_DECISIONS:
        raise ValueError('invalid decision')
    if corrected_grade not in (None, '') and corrected_grade not in REVIEW_GRADE_LABELS:
        raise ValueError('invalid corrected grade')
    corrected = corrected or (None, None, None)
    conn = _connect_review(review_db)
    try:
        if decision == 'pending':
            conn.execute('DELETE FROM classical_review_decisions WHERE source=? AND classical_id=?',
                         (source, classical_id))
        else:
            conn.execute('''INSERT INTO classical_review_decisions
                (source,classical_id,decision,reviewer_note,corrected_surah,corrected_ayah,corrected_wpos,corrected_grade,updated_at)
                VALUES (?,?,?,?,?,?,?, ?,CURRENT_TIMESTAMP)
                ON CONFLICT(source,classical_id) DO UPDATE SET
                  decision=excluded.decision, reviewer_note=excluded.reviewer_note,
                  corrected_surah=excluded.corrected_surah,
                  corrected_ayah=excluded.corrected_ayah,
                  corrected_wpos=excluded.corrected_wpos,
                  corrected_grade=excluded.corrected_grade,
                  updated_at=CURRENT_TIMESTAMP''',
                (source, classical_id, decision, note, *corrected,
                 corrected_grade or None))
        conn.commit()
    finally:
        conn.close()


def book_decision(source='muktafa', review_db=None):
    review_db = _review_path(review_db)
    if not os.path.exists(review_db):
        return {'decision': 'pending', 'reviewer_note': '', 'updated_at': None}
    conn = _connect_review(review_db)
    try:
        row = conn.execute('SELECT * FROM classical_review_books WHERE source=?', (source,)).fetchone()
        return dict(row) if row else {'decision': 'pending', 'reviewer_note': '', 'updated_at': None}
    finally:
        conn.close()


def save_book_decision(decision, note='', source='muktafa',
                       review_db=None):
    if decision not in VALID_BOOK_DECISIONS:
        raise ValueError('invalid book decision')
    conn = _connect_review(review_db)
    try:
        conn.execute('''INSERT INTO classical_review_books(source,decision,reviewer_note,updated_at)
            VALUES (?,?,?,CURRENT_TIMESTAMP)
            ON CONFLICT(source) DO UPDATE SET decision=excluded.decision,
              reviewer_note=excluded.reviewer_note, updated_at=CURRENT_TIMESTAMP''',
            (source, decision, note))
        conn.commit()
    finally:
        conn.close()


def _builder():
    pipeline = str(Path(_BASE_DIR) / 'pipeline')
    if pipeline not in sys.path:
        sys.path.insert(0, pipeline)
    import build_classical_waqf
    return build_classical_waqf


def _quote_hits_wpos(builder, verse, quoted, wpos):
    """True if some tokenisation of `quoted` has its tail ending at wpos."""
    if not quoted:
        return False
    variants = builder.quote_token_variants(quoted) if hasattr(builder, 'quote_token_variants') else [quoted]
    for seq in variants:
        for level in (1, 2):
            for length in dict.fromkeys((min(3, len(seq)), 2, 1)):
                if length < 1 or length > len(seq):
                    continue
                start = wpos - length + 1
                if start < 0:
                    continue
                ok = True
                for i in range(length):
                    q, w = seq[-length + i], verse[start + i]
                    if i == length - 1 and level == 1 and hasattr(builder, 'match_stop_word'):
                        if not builder.match_stop_word(q, w, level):
                            ok = False
                            break
                    elif not builder.match_word(q, w, level):
                        ok = False
                        break
                if ok:
                    return True
    return False


def quote_matches_position(surah, ayah, wpos, quote):
    """Verify the quote tail ends at exactly this Qur'an word position.

    Period quotes (`منزلين. بلى`) try the part before the period (ayah-end
    pin) and the part after (e.g. ذق). Tokenisation variants and last-token
    ت/ي/ن · ا/ه folds match pipeline/build_classical_waqf.align_in_ayah."""
    b = _builder()
    key = f'{surah}:{ayah}'
    if key not in b.app.qpc_hafs_data_normalized:
        return False
    _, words, _ = b.app._verse_word_texts(key)
    if not 0 <= wpos < len(words):
        return False
    verse = [b.norm(word) for word in words]
    parts = [quote]
    if '.' in (quote or ''):
        before, after = quote.split('.', 1)
        parts.extend((before, after))
    for part in parts:
        quoted = b.quote_words(part)
        if _quote_hits_wpos(b, verse, quoted, wpos):
            return True
        # Frozen formula whose last token isn't in the mushaf (فليتوكل
        # المتوكلون vs فليتوكل المؤمنون): the preceding tokens uniquely
        # sit immediately before the recited stop.
        if len(quoted) >= 2 and wpos >= 1 and _quote_hits_wpos(b, verse, quoted[:-1], wpos - 1):
            return True
    return False


@lru_cache(maxsize=1)
def _muktafa_sections():
    """Raw source sections keyed by surah, retaining OpenITI page markers."""
    b = _builder()
    raw = MUKTAFA_SOURCE.read_text(encoding='utf-8').split('#META#Header#End#', 1)[1]
    raw = b.normalize_muktafa_headings(raw)
    sections, last = {}, 0
    for part in re.split(r'(?=\n### \| )', raw):
        first = part.lstrip('\n').split('\n', 1)[0]
        title = re.sub(r'^### \|\s*', '', first)
        if 'سورة' not in title and 'أم القرآن' not in title:
            continue
        number = b.surah_number(title, last)
        if number is not None:
            sections[number] = (title, part)
            last = number
    return sections


def _normalized_find(text, quote):
    b = _builder()
    tokens = [(m.start(), b.norm(m.group(0))) for m in re.finditer(r'[؀-ۿ]+', text)]
    needle = b.quote_words(quote)
    if not needle:
        return -1
    values = [token for _, token in tokens]
    for start in range(0, len(values) - len(needle) + 1):
        if values[start:start + len(needle)] == needle:
            return tokens[start][0]
    return -1


def muktafa_source_context(row, radius=460):
    section = _muktafa_sections().get(int(row['surah']))
    if not section:
        return {'locator': f'سورة {row["surah"]}', 'context': ''}
    title, text = section
    quote = row['quote'] or ''
    positions, pos = [], 0
    while quote:
        pos = text.find(quote, pos)
        if pos < 0:
            break
        positions.append(pos)
        pos += max(1, len(quote))
    if positions:
        # Prefer the occurrence whose following prose overlaps the stored note.
        note_words = [w for w in re.findall(r'[؀-ۿ]+', row['note'] or '')[:8] if len(w) > 2]
        pos = max(positions, key=lambda p: sum(w in text[p:p + 900] for w in note_words))
    else:
        pos = _normalized_find(text, quote)
    if pos < 0:
        pos = 0
    page_matches = list(re.finditer(r'PageV(\d+)P(\d+)', text[:pos]))
    page = f'V{page_matches[-1].group(1)}P{page_matches[-1].group(2)}' if page_matches else 'بلا رقم صفحة'
    excerpt = text[max(0, pos - radius):min(len(text), pos + len(quote) + radius)]
    excerpt = re.sub(r'PageV\d+P\d+|\bms\d+\b', ' ', excerpt)
    excerpt = excerpt.replace('\n~~', ' ').replace('\n# ', '\n')
    excerpt = re.sub(r'[ \t]+', ' ', excerpt).strip()
    return {'locator': f'{title} · {page}', 'context': excerpt}


@lru_cache(maxsize=1)
def manar_review_queue():
    if not MANAR_REVIEW_QUEUE.exists():
        return {}
    items = {}
    with MANAR_REVIEW_QUEUE.open(encoding='utf-8') as fh:
        for line in fh:
            if line.strip():
                item = json.loads(line)
                items[int(item['id'])] = item
    return items


@lru_cache(maxsize=1)
def manar_explicit_keys():
    """Return explicit ruling keys from both committed Manar source copies."""
    from pipeline import build_classical_llm as builder

    expected = set()
    for sections in (
        builder.load_shamela_sections(),
        builder._openiti_manar_crosscheck_sections(),
    ):
        for surah in range(1, 115):
            expected.update(
                (surah, row[1], row[2], row[5])
                for row in builder.explicit_manar_rows(
                    surah, sections[str(surah)]['text']
                )
            )
    return expected


def review_row_ids(source, db_path=CLASSICAL_WAQF_DATABASE):
    if source == 'manar':
        return set(manar_review_queue())
    if source != 'muktafa':
        return set()
    conn = sqlite3.connect(db_path)
    try:
        return {row[0] for row in conn.execute(
            "SELECT id FROM classical WHERE source='muktafa' AND conf=0")}
    finally:
        conn.close()


def _decision_counts(source, row_ids, review_db=None):
    saved = decisions(source, review_db)
    counts = {'approved': 0, 'rejected': 0, 'pending': 0}
    for row_id in row_ids:
        decision = saved.get(row_id, {}).get('decision')
        counts['approved' if decision == 'approve' else 'rejected' if decision == 'reject' else 'pending'] += 1
    return counts


def muktafa_accuracy(db_path=CLASSICAL_WAQF_DATABASE, review_db=None):
    review_db = _review_path(review_db)
    b = _builder()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute("SELECT * FROM classical WHERE source='muktafa'").fetchall()
    finally:
        conn.close()
    confident = [row for row in rows if row['conf'] == 1]
    matched = [row for row in rows if row['ayah'] is not None and row['wpos'] is not None]

    raw = b.load_book(b.SOURCES['muktafa'])
    source_words = ' ' + ' '.join(
        token for token in (b.norm(t) for t in re.findall(r'[؀-ۿ]+', raw)) if token) + ' '
    source_traceable = 0
    aligned = exact = fuzzy = 0
    for row in confident:
        qwords = b.quote_words(row['quote'])
        if qwords and (' ' + ' '.join(qwords) + ' ') in source_words:
            source_traceable += 1
        if quote_matches_position(row['surah'], row['ayah'], row['wpos'], row['quote']):
            aligned += 1
            # Level-1 exact/prefix vs tight fuzzy orthographic fallback.
            _, words, _ = b.app._verse_word_texts(f'{row["surah"]}:{row["ayah"]}')
            verse = [b.norm(word) for word in words]
            is_exact = False
            for length in dict.fromkeys((min(3, len(qwords)), 2, 1)):
                start = row['wpos'] - length + 1
                if length >= 1 and length <= len(qwords) and start >= 0 and all(
                        b.match_word(qwords[-length + i], verse[start + i], 1) for i in range(length)):
                    is_exact = True
                    break
            exact += int(is_exact)
            fuzzy += int(not is_exact)

    uncertain_ids = {row['id'] for row in rows if row['conf'] == 0}
    counts = _decision_counts('muktafa', uncertain_ids, review_db)
    total = len(rows)
    return {
        'total_extracted': total, 'matched': len(matched), 'unmatched': total - len(matched),
        'confident': len(confident), 'uncertain': total - len(confident),
        'matched_rate': round(100 * len(matched) / total, 2),
        'confident_rate': round(100 * len(confident) / total, 2),
        'source_traceable': source_traceable,
        'source_traceable_rate': round(100 * source_traceable / max(1, len(confident)), 2),
        'quran_aligned': aligned,
        'quran_aligned_rate': round(100 * aligned / max(1, len(confident)), 2),
        'exact_or_prefix': exact, 'orthographic_fuzzy': fuzzy,
        'review': counts, 'book_decision': book_decision('muktafa', review_db),
        'claim_limit': 'لا توجد نسبة اكتمال للكتاب كله بلا معيار ذهبي ومراجعة بشرية للنثر الاستطرادي.',
        'source': 'muktafa', 'title_ar': 'المكتفى لأبي عمرو الداني',
        'currently_active': book_decision('muktafa', review_db).get('decision') == 'add',
    }


def manar_accuracy(db_path=CLASSICAL_WAQF_DATABASE, review_db=None):
    review_db = _review_path(review_db)
    queue = manar_review_queue()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT id,conf,surah,ayah,wpos,grade FROM classical WHERE source='manar'"
        ).fetchall()
    finally:
        conn.close()
    ids = {row['id'] for row in rows}
    queue_ids = set(queue)
    stale = queue_ids - ids
    total = len(rows)
    grounded = total - len(queue_ids & ids)
    live_keys = {
        (row['surah'], row['ayah'], row['wpos'], row['grade'])
        for row in rows
    }
    explicit_keys = manar_explicit_keys()
    counts = _decision_counts('manar', queue_ids & ids, review_db)
    decision = book_decision('manar', review_db)
    return {
        'source': 'manar', 'title_ar': 'منار الهدى للأشموني',
        'total_extracted': total, 'matched': total, 'unmatched': 0,
        'confident': total, 'uncertain': len(queue_ids & ids),
        'matched_rate': 100.0, 'confident_rate': 100.0,
        'source_traceable': grounded,
        'source_traceable_rate': round(100 * grounded / max(1, total), 2),
        'quran_aligned': total, 'quran_aligned_rate': 100.0,
        'explicit_expected': len(explicit_keys),
        'explicit_missing': len(explicit_keys - live_keys),
        'review': counts, 'book_decision': decision,
        'currently_active': decision.get('decision') != 'reject',
        'stale_review_ids': len(stale),
        'claim_limit': 'هذه قائمة فحص احترازية: غياب الدليل القريب لا يعني أن الحكم خاطئ، بل يحتاج قراءة بشرية في سياقه.',
    }


def source_accuracy(source, db_path=CLASSICAL_WAQF_DATABASE, review_db=None):
    if source == 'muktafa':
        return muktafa_accuracy(db_path, review_db)
    if source == 'manar':
        return manar_accuracy(db_path, review_db)
    raise ValueError('unsupported review source')


def export_decisions(path, source='muktafa', review_db=None):
    data = {
        'source': source,
        'book': book_decision(source, review_db),
        'rows': sorted(decisions(source, review_db).values(), key=lambda row: row['classical_id']),
    }
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    return data
