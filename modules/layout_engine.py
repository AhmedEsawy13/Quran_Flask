"""Shared mushaf layout engine — range-based line break / cascade / undo.

Used by the Azhar layout studio (Shemrly word space). Future editions plug in
their own DB path, word-id universe, and closed-page rules.
"""
from __future__ import annotations

import bisect
import json
import sqlite3
from typing import Iterable

from core.db import connect as _sqlite_connect

_UNDO_LIMIT = 40
_SCRIPT_WORD_IDS: dict[str, list[int]] = {}
_SCRIPT_WORD_RECORDS: dict[str, tuple[list[int], dict[int, dict]]] = {}


def all_script_word_ids(script_db: str) -> list[int]:
    """Sorted word_index list from quran_script (process-cached)."""
    cache_key = str(script_db)
    if cache_key in _SCRIPT_WORD_IDS:
        return _SCRIPT_WORD_IDS[cache_key]
    conn = _sqlite_connect(script_db)
    try:
        cur = conn.cursor()
        cur.execute('SELECT word_index FROM words ORDER BY word_index ASC')
        _SCRIPT_WORD_IDS[cache_key] = [int(r[0]) for r in cur.fetchall()]
    finally:
        conn.close()
    return _SCRIPT_WORD_IDS[cache_key]


def clear_script_word_id_cache() -> None:
    _SCRIPT_WORD_IDS.clear()
    _SCRIPT_WORD_RECORDS.clear()


def existing_word_ids_between(first, last, universe: list[int] | None = None, script_db: str | None = None):
    """Real word_index values in [first, last] (skips reserved gaps)."""
    if first is None or last is None:
        return []
    first, last = int(first), int(last)
    if last < first:
        return []
    ids = universe
    if ids is None:
        if not script_db:
            return []
        ids = all_script_word_ids(script_db)
    lo = bisect.bisect_left(ids, first)
    hi = bisect.bisect_right(ids, last)
    return ids[lo:hi]


def expand_ayah_words(line, universe=None, script_db=None):
    return existing_word_ids_between(
        line.get('first_word_id'), line.get('last_word_id'),
        universe=universe, script_db=script_db,
    )


def word_texts(script_db: str, word_ids: Iterable[int]) -> dict[int, str]:
    ids = list(word_ids)
    if not ids:
        return {}
    conn = _sqlite_connect(script_db)
    try:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        out: dict[int, str] = {}
        for i in range(0, len(ids), 400):
            chunk = ids[i:i + 400]
            placeholders = ','.join('?' * len(chunk))
            cur.execute(
                f'SELECT word_index, text FROM words WHERE word_index IN ({placeholders})',
                chunk,
            )
            for row in cur.fetchall():
                out[int(row['word_index'])] = row['text'] or ''
        return out
    finally:
        conn.close()


def assign_words_to_line(line, word_ids, text_map):
    if not word_ids:
        line['first_word_id'] = None
        line['last_word_id'] = None
        line['line_text'] = ''
        return
    line['first_word_id'] = int(word_ids[0])
    line['last_word_id'] = int(word_ids[-1])
    line['line_text'] = ' '.join(
        text_map.get(w, '') for w in word_ids if text_map.get(w)
    ).strip()


def persist_line(cur, line):
    cur.execute(
        '''
        UPDATE pages
        SET first_word_id = ?, last_word_id = ?, line_text = ?
        WHERE id = ?
        ''',
        (line['first_word_id'], line['last_word_id'], line.get('line_text') or '', line['id']),
    )


def load_all_lines(cur):
    cur.execute(
        '''
        SELECT id, page_number, line_number, line_type, is_centered,
               first_word_id, last_word_id, surah_number, line_text
        FROM pages
        ORDER BY page_number ASC, line_number ASC
        '''
    )
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


# Header rows that reserve page slots (not ayah word stream).
SURAH_HEADER_TYPES = frozenset({'surah_name', 'surah_info', 'basmallah'})

# Egyptian / Azhar-print classification (مدنية). All others treated as مكية.
_MEDINAN_SURAHS = frozenset({
    2, 3, 4, 5, 8, 9, 13, 22, 24, 33, 47, 48, 49, 55, 57, 58, 59, 60, 61, 62,
    63, 64, 65, 66, 76, 98, 99, 110,
})
_ARABIC_INDIC = str.maketrans('0123456789', '٠١٢٣٤٥٦٧٨٩')


def is_surah_separator(line) -> bool:
    """surah_name / surah_info / basmallah fence ayah word streams."""
    return (line or {}).get('line_type') in SURAH_HEADER_TYPES


def to_arabic_indic(n: int) -> str:
    return str(int(n)).translate(_ARABIC_INDIC)


def surah_ayah_count(script_db: str, surah_number: int) -> int:
    conn = _sqlite_connect(script_db)
    try:
        row = conn.execute(
            'SELECT MAX(ayah) FROM words WHERE surah = ?',
            (int(surah_number),),
        ).fetchone()
        return int(row[0] or 0)
    finally:
        conn.close()


def surah_info_text(surah_number: int, *, script_db: str) -> str:
    """Second header line under the surah name: مكية/مدنية · آياتها N."""
    place = 'مدنية' if int(surah_number) in _MEDINAN_SURAHS else 'مكية'
    count = surah_ayah_count(script_db, int(surah_number))
    if count <= 0:
        return place
    return f'{place} · آياتها {to_arabic_indic(count)}'


def ensure_surah_info_schema(cur) -> bool:
    """Widen pages.line_type CHECK to allow surah_info. Returns True if rebuilt."""
    row = cur.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='pages'"
    ).fetchone()
    if not row or not row[0]:
        return False
    sql = row[0]
    if 'surah_info' in sql:
        return False
    cur.execute(
        '''
        CREATE TABLE pages__surah_info (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            page_number INTEGER NOT NULL,
            line_number INTEGER NOT NULL,
            line_type TEXT NOT NULL
                CHECK(line_type IN ('ayah', 'surah_name', 'surah_info', 'basmallah')),
            is_centered INTEGER NOT NULL,
            first_word_id INTEGER,
            last_word_id INTEGER,
            surah_number INTEGER,
            line_text TEXT NOT NULL DEFAULT ''
        )
        '''
    )
    cur.execute(
        '''
        INSERT INTO pages__surah_info (
            id, page_number, line_number, line_type, is_centered,
            first_word_id, last_word_id, surah_number, line_text
        )
        SELECT id, page_number, line_number, line_type, is_centered,
               first_word_id, last_word_id, surah_number, line_text
        FROM pages
        '''
    )
    cur.execute('DROP TABLE pages')
    cur.execute('ALTER TABLE pages__surah_info RENAME TO pages')
    cur.execute(
        'CREATE INDEX IF NOT EXISTS idx_azhar_page_line ON pages (page_number, line_number)'
    )
    cur.execute(
        'CREATE INDEX IF NOT EXISTS idx_azhar_surah_number ON pages (surah_number)'
    )
    return True


def ayah_segment_slots(lines, start_idx, *, page_scope=None) -> list[int]:
    """Ayah line indices from start_idx until the next surah separator (or page end).

    Open-page cascade used to treat the whole mushaf as one stream, which pushed
    leftover words of سورة آل عمران onto سورة النساء lines after a mid-page
    surah header. Separators fence the stream; page_scope (closed Fatiha) still
    limits to one page.
    """
    if start_idx < 0 or start_idx >= len(lines):
        return []
    # If start sits on/after a separator before the next ayah, begin at that ayah.
    i = start_idx
    slots: list[int] = []
    while i < len(lines):
        line = lines[i]
        if page_scope is not None and int(line['page_number']) != int(page_scope):
            break
        if is_surah_separator(line):
            # A separator after we've already collected ayahs ends the segment.
            if slots:
                break
            # Leading separators (page starts with surah_name) are skipped.
            i += 1
            continue
        if line['line_type'] == 'ayah':
            # Crossing into a separator-bounded new surah: stop before it.
            # (Handled above when we *see* the separator.)
            slots.append(i)
        i += 1
    return slots


def separator_between(lines, left_idx: int, right_idx: int) -> bool:
    """True if a surah_name/basmallah sits strictly between two line indices."""
    if left_idx is None or right_idx is None:
        return False
    lo, hi = sorted((int(left_idx), int(right_idx)))
    for i in range(lo + 1, hi):
        if is_surah_separator(lines[i]):
            return True
    return False


def cascade_from(lines, start_idx, head_words, text_map, *, universe=None, page_scope=None,
                 closed_stream=None):
    """Rewrite ayah lines from start_idx onward (capacity-preserving).

    When `page_scope` is set with `closed_stream` (canonical word ids for that
    page), spilled words are pulled back and cannot leave the page.

    Open mode fences at the next surah_name/basmallah so words never spill into
    the following surah's ayah lines.
    """
    ayah_slots = ayah_segment_slots(lines, start_idx, page_scope=page_scope)
    if not ayah_slots or not head_words:
        return False

    head = list(head_words)
    closed = page_scope is not None and closed_stream is not None

    if closed:
        page_ayah = [
            i for i, line in enumerate(lines)
            if line['line_type'] == 'ayah' and int(line['page_number']) == int(page_scope)
        ]
        prefix = []
        for i in page_ayah:
            if i < start_idx:
                prefix.extend(expand_ayah_words(lines[i], universe=universe))
            else:
                break
        canonical = list(closed_stream)
        start = prefix + head
        if canonical[:len(start)] != start:
            return False
        stream_from_start = canonical[len(prefix):]
    else:
        stream_from_start = []
        for line_i in ayah_slots:
            stream_from_start.extend(expand_ayah_words(lines[line_i], universe=universe))

    capacities = []
    for slot_i, line_i in enumerate(ayah_slots):
        words = expand_ayah_words(lines[line_i], universe=universe)
        capacities.append(max(1, len(head) if slot_i == 0 else len(words) or 1))

    if stream_from_start[:len(head)] != head:
        return False
    rest = stream_from_start[len(head):]

    # Single slot with leftover words would drop them (nowhere to spill inside
    # the surah fence). Caller should reject rather than delete scripture.
    if len(ayah_slots) == 1 and rest:
        return False

    assignments = [head]
    cursor = 0
    for slot_i in range(1, len(ayah_slots)):
        is_last = slot_i == len(ayah_slots) - 1
        if is_last:
            chunk = rest[cursor:]
        else:
            n = capacities[slot_i]
            chunk = rest[cursor:cursor + n]
            cursor += len(chunk)
        assignments.append(chunk)

    if len(ayah_slots) > 1:
        used = sum(len(a) for a in assignments[1:-1])
        assignments[-1] = rest[used:]

    for slot_i, line_i in enumerate(ayah_slots):
        assign_words_to_line(lines[line_i], assignments[slot_i], text_map)
    return True


def segment_page_bounds(lines, start_idx, *, page_scope=None) -> tuple[int, int]:
    """(page_from, page_to) covering ayah slots rewritten by a cascade."""
    slots = ayah_segment_slots(lines, start_idx, page_scope=page_scope)
    if not slots:
        page = int(lines[start_idx]['page_number'])
        return page, page
    pages = [int(lines[i]['page_number']) for i in slots]
    return min(pages), max(pages)


def split_words_evenly(word_ids: list[int], n_slots: int) -> list[list[int]]:
    """Distribute word ids across n_slots as evenly as possible (all non-empty if possible)."""
    ids = list(word_ids)
    if n_slots <= 0:
        return []
    if not ids:
        return [[] for _ in range(n_slots)]
    n = min(int(n_slots), len(ids))
    base, rem = divmod(len(ids), n)
    out: list[list[int]] = []
    i = 0
    for k in range(n):
        take = base + (1 if k < rem else 0)
        out.append(ids[i:i + take])
        i += take
    while len(out) < n_slots:
        out.append([])
    return out


def reshape_page_line_count(
    cur,
    page_number: int,
    target_lines: int,
    *,
    script_db: str,
    universe: list[int] | None = None,
) -> dict:
    """Collapse/expand a page to `target_lines` keeping headers + redistributing ayah words.

    Expects the page to start with surah_name / basmallah (optional) then ayah
    lines. Headers are preserved in order; remaining slots become ayah lines.
    """
    cur.execute(
        '''
        SELECT id, page_number, line_number, line_type, is_centered,
               first_word_id, last_word_id, surah_number, line_text
        FROM pages
        WHERE page_number = ?
        ORDER BY line_number ASC
        ''',
        (int(page_number),),
    )
    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    if not rows:
        raise ValueError(f'page {page_number} has no lines')

    headers = [r for r in rows if r['line_type'] in SURAH_HEADER_TYPES]
    ayah_rows = [r for r in rows if r['line_type'] == 'ayah']
    header_count = len(headers)
    ayah_slots = int(target_lines) - header_count
    if ayah_slots < 1:
        raise ValueError(
            f'page {page_number}: target_lines={target_lines} leaves no room for ayah '
            f'after {header_count} header line(s)'
        )

    word_ids: list[int] = []
    for line in ayah_rows:
        word_ids.extend(expand_ayah_words(line, universe=universe, script_db=script_db))
    chunks = split_words_evenly(word_ids, ayah_slots)
    text_map = word_texts(script_db, word_ids)

    surah_number = None
    for line in rows:
        if line.get('surah_number') is not None:
            surah_number = line['surah_number']
            break

    cur.execute('DELETE FROM pages WHERE page_number = ?', (int(page_number),))
    line_no = 1
    for header in headers:
        cur.execute(
            '''
            INSERT INTO pages (
                page_number, line_number, line_type, is_centered,
                first_word_id, last_word_id, surah_number, line_text
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''',
            (
                int(page_number),
                line_no,
                header['line_type'],
                1 if header.get('is_centered') else 0,
                header.get('first_word_id'),
                header.get('last_word_id'),
                header.get('surah_number'),
                header.get('line_text') or '',
            ),
        )
        line_no += 1

    for chunk in chunks:
        line = {
            'first_word_id': None,
            'last_word_id': None,
            'line_text': '',
        }
        assign_words_to_line(line, chunk, text_map)
        cur.execute(
            '''
            INSERT INTO pages (
                page_number, line_number, line_type, is_centered,
                first_word_id, last_word_id, surah_number, line_text
            ) VALUES (?, ?, 'ayah', 0, ?, ?, ?, ?)
            ''',
            (
                int(page_number),
                line_no,
                line['first_word_id'],
                line['last_word_id'],
                surah_number,
                line['line_text'] or '',
            ),
        )
        line_no += 1

    return {
        'page_number': int(page_number),
        'target_lines': int(target_lines),
        'header_lines': header_count,
        'ayah_lines': ayah_slots,
        'word_count': len(word_ids),
    }


def _replace_page_rows(cur, page_number: int, rows: list[dict]) -> None:
    """Rewrite one page's lines from an ordered row list (1-based line_number)."""
    cur.execute('DELETE FROM pages WHERE page_number = ?', (int(page_number),))
    for i, row in enumerate(rows, start=1):
        cur.execute(
            '''
            INSERT INTO pages (
                page_number, line_number, line_type, is_centered,
                first_word_id, last_word_id, surah_number, line_text
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''',
            (
                int(page_number),
                i,
                row['line_type'],
                1 if row.get('is_centered') else 0,
                row.get('first_word_id'),
                row.get('last_word_id'),
                row.get('surah_number'),
                row.get('line_text') or '',
            ),
        )


def _page_rows(cur, page_number: int) -> list[dict]:
    cur.execute(
        '''
        SELECT id, page_number, line_number, line_type, is_centered,
               first_word_id, last_word_id, surah_number, line_text
        FROM pages
        WHERE page_number = ?
        ORDER BY line_number ASC
        ''',
        (int(page_number),),
    )
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def _make_surah_info_row(surah_number: int, *, script_db: str) -> dict:
    return {
        'line_type': 'surah_info',
        'is_centered': 1,
        'first_word_id': None,
        'last_word_id': None,
        'surah_number': int(surah_number) if surah_number is not None else None,
        'line_text': surah_info_text(int(surah_number), script_db=script_db)
        if surah_number is not None else '',
    }


def _make_basmallah_row(surah_number: int) -> dict:
    return {
        'line_type': 'basmallah',
        'is_centered': 1,
        'first_word_id': None,
        'last_word_id': None,
        'surah_number': int(surah_number),
        'line_text': 'بِسْمِ اللَّهِ الرَّحْمَنِ الرَّحِيمِ',
    }


def _normalize_surah_banners(rows: list[dict], *, script_db: str) -> list[dict]:
    """Make each surah banner complete and ordered.

    Azhar uses name + info + basmala. At-Tawbah intentionally has no basmala,
    but still receives its information row. A few inferred Shemrly pages omit
    the basmala entirely, so a display-only row is synthesized for them.
    """
    out: list[dict] = []
    i = 0
    while i < len(rows):
        row = rows[i]
        if row['line_type'] != 'surah_name':
            out.append(row)
            i += 1
            continue

        surah_number = row.get('surah_number')
        out.append(row)
        i += 1

        if i < len(rows) and rows[i]['line_type'] == 'surah_info':
            info = dict(rows[i])
            info['surah_number'] = surah_number
            info['line_text'] = (
                info.get('line_text')
                or surah_info_text(int(surah_number), script_db=script_db)
            )
            out.append(info)
            i += 1
        else:
            out.append(_make_surah_info_row(surah_number, script_db=script_db))

        if int(surah_number or 0) == 9:
            continue
        if i < len(rows) and rows[i]['line_type'] == 'basmallah':
            basmala = dict(rows[i])
            basmala['surah_number'] = surah_number
            out.append(basmala)
            i += 1
        else:
            out.append(_make_basmallah_row(int(surah_number)))
    return out


def _leading_header_count(rows: list[dict]) -> int:
    n = 0
    for row in rows:
        if row['line_type'] in SURAH_HEADER_TYPES:
            n += 1
            continue
        break
    return n


def _script_words_in_numeric_range(
    script_db: str,
    first_word_id,
    last_word_id,
) -> list[dict]:
    """Read source-layout ranges before they are normalized.

    The inferred Shemrly source has three displaced numeric blocks. Reading the
    raw numeric interval is intentional here; the page repair then restores
    canonical (surah, ayah, word) order.
    """
    if first_word_id is None or last_word_id is None:
        return []
    first, last = int(first_word_id), int(last_word_id)
    if last < first:
        first, last = last, first
    cache_key = str(script_db)
    if cache_key not in _SCRIPT_WORD_RECORDS:
        conn = _sqlite_connect(script_db)
        try:
            rows = conn.execute(
                '''
                SELECT word_index, word_key, surah, ayah, text
                FROM words
                ORDER BY word_index
                '''
            ).fetchall()
        finally:
            conn.close()
        records = {
            int(row[0]): {
                'word_index': int(row[0]),
                'word_key': row[1] or '',
                'surah': int(row[2]),
                'ayah': int(row[3]),
                'text': row[4] or '',
            }
            for row in rows
        }
        _SCRIPT_WORD_RECORDS[cache_key] = (sorted(records), records)
    ids, records = _SCRIPT_WORD_RECORDS[cache_key]
    lo = bisect.bisect_left(ids, first)
    hi = bisect.bisect_right(ids, last)
    return [records[word_id] for word_id in ids[lo:hi]]


def _canonical_word_key(word: dict) -> tuple[int, int, int]:
    try:
        position = int(str(word.get('word_key') or '').rsplit(':', 1)[-1])
    except (TypeError, ValueError):
        position = int(word['word_index'])
    return int(word['surah']), int(word['ayah']), position


def _allocate_group_slots(groups: list[list[dict]], total_slots: int) -> list[int]:
    """Allocate at least one line to each non-empty surah group."""
    if not groups:
        return []
    if total_slots < len(groups):
        raise ValueError('page has more surah word groups than available ayah slots')
    sizes = [len(group) for group in groups]
    total_words = sum(sizes)
    allocations = [1] * len(groups)
    remaining = int(total_slots) - len(groups)
    if remaining <= 0 or total_words <= 0:
        return allocations
    raw = [remaining * size / total_words for size in sizes]
    floors = [int(value) for value in raw]
    allocations = [base + extra for base, extra in zip(allocations, floors)]
    left = remaining - sum(floors)
    order = sorted(
        range(len(groups)),
        key=lambda idx: (raw[idx] - floors[idx], sizes[idx]),
        reverse=True,
    )
    for idx in order[:left]:
        allocations[idx] += 1
    return allocations


def _repair_displaced_boundary_page(
    cur,
    page_number: int,
    *,
    script_db: str,
    default_lines: int,
) -> None:
    """Repair a page whose inferred numeric ranges place a later surah first."""
    rows = _page_rows(cur, page_number)
    names = {
        int(row['surah_number']): dict(row)
        for row in rows
        if row['line_type'] == 'surah_name' and row.get('surah_number') is not None
    }
    infos = {
        int(row['surah_number']): dict(row)
        for row in rows
        if row['line_type'] == 'surah_info' and row.get('surah_number') is not None
    }
    basmalas = [
        dict(row) for row in rows if row['line_type'] == 'basmallah'
    ]

    by_surah: dict[int, dict[int, dict]] = {}
    encounter_order: list[int] = []
    for row in rows:
        if row['line_type'] != 'ayah':
            continue
        for word in _script_words_in_numeric_range(
            script_db, row.get('first_word_id'), row.get('last_word_id'),
        ):
            surah = int(word['surah'])
            if surah not in by_surah:
                by_surah[surah] = {}
                encounter_order.append(surah)
            by_surah[surah][int(word['word_index'])] = word

    ordered_surahs = sorted(by_surah)
    if encounter_order == ordered_surahs:
        return

    banner_rows: dict[int, list[dict]] = {}
    for surah, name in names.items():
        info = infos.get(surah) or _make_surah_info_row(surah, script_db=script_db)
        banner = [name, info]
        if surah != 9:
            basmala = next(
                (row for row in basmalas if int(row.get('surah_number') or 0) == surah),
                None,
            )
            if basmala is None and len(names) == 1 and len(basmalas) == 1:
                basmala = dict(basmalas[0])
                basmala['surah_number'] = surah
            banner.append(basmala or _make_basmallah_row(surah))
        banner_rows[surah] = banner

    header_count = sum(len(banner_rows.get(surah, ())) for surah in ordered_surahs)
    ayah_slots = int(default_lines) - header_count
    word_groups = [
        sorted(by_surah[surah].values(), key=_canonical_word_key)
        for surah in ordered_surahs
    ]
    allocations = _allocate_group_slots(word_groups, ayah_slots)

    rebuilt: list[dict] = []
    for surah, words, slots in zip(ordered_surahs, word_groups, allocations):
        rebuilt.extend(banner_rows.get(surah, ()))
        rebuilt.extend(
            _ayah_rows_from_words(
                [int(word['word_index']) for word in words],
                slots,
                surah_number=surah,
                script_db=script_db,
            )
        )
    if len(rebuilt) != int(default_lines):
        raise ValueError(
            f'page {page_number}: displaced-boundary repair produced '
            f'{len(rebuilt)} lines, expected {default_lines}'
        )
    _replace_page_rows(cur, page_number, rebuilt)


def _repair_ayah_surah_metadata(cur, *, script_db: str) -> int:
    """Make line-level surah metadata agree with the actual words."""
    fixed = 0
    for page in [
        int(row[0]) for row in cur.execute(
            'SELECT DISTINCT page_number FROM pages ORDER BY page_number'
        ).fetchall()
    ]:
        rows = _page_rows(cur, page)
        changed = False
        for row in rows:
            if row['line_type'] != 'ayah':
                continue
            actual = {
                int(word['surah'])
                for word in _script_words_in_numeric_range(
                    script_db, row.get('first_word_id'), row.get('last_word_id'),
                )
            }
            if len(actual) == 1 and row.get('surah_number') != next(iter(actual)):
                row['surah_number'] = next(iter(actual))
                fixed += 1
                changed = True
        if changed:
            _replace_page_rows(cur, page, rows)
    return fixed


def normalize_surah_header_pages(
    cur,
    *,
    script_db: str,
    universe: list[int] | None = None,
    default_lines: int = 15,
    skip_pages: Iterable[int] | None = None,
) -> dict:
    """Azhar geometry: every page stays at ``default_lines`` (usually 15).

    Matches Madinah/QPC page budget: headers consume slots inside the 15, they
    do not grow the page.

    1. Promote trailing ``surah_name`` onto the next page when that page starts
       with ``basmallah`` (Shemrly split-header pattern, e.g. 494→495).
    2. Insert ``surah_info`` between every ``surah_name`` → ``basmallah`` banner
       (leading or mid-page) so the banner is always 3 slots.
    3. On pages that *lead* with that banner, keep only
       ``default_lines - header_count`` ayah rows in the opening block.
    4. Clamp any page still over ``default_lines`` by spilling trailing ayah
       words onto the next page of the same surah (e.g. mid-page banner on 498).
    5. Expand any underfull page back to ``default_lines``.
    """
    ensure_surah_info_schema(cur)
    skip = {int(p) for p in (skip_pages or ())}
    universe = universe if universe is not None else all_script_word_ids(script_db)

    page_numbers = [
        int(r[0]) for r in cur.execute(
            'SELECT DISTINCT page_number FROM pages ORDER BY page_number'
        ).fetchall()
    ]
    promoted = 0
    for page in list(page_numbers):
        rows = _page_rows(cur, page)
        if not rows or rows[-1]['line_type'] != 'surah_name':
            continue
        nxt_page = page + 1
        nxt = _page_rows(cur, nxt_page)
        if not nxt or nxt[0]['line_type'] != 'basmallah':
            continue
        name_row = rows[-1]
        _replace_page_rows(cur, page, rows[:-1])
        _replace_page_rows(cur, nxt_page, [name_row] + nxt)
        promoted += 1

    displaced_pages: list[int] = []
    for page in page_numbers:
        if page in skip:
            continue
        encountered: list[int] = []
        for row in _page_rows(cur, page):
            if row['line_type'] != 'ayah':
                continue
            for word in _script_words_in_numeric_range(
                script_db, row.get('first_word_id'), row.get('last_word_id'),
            ):
                surah = int(word['surah'])
                if not encountered or encountered[-1] != surah:
                    encountered.append(surah)
        if any(right < left for left, right in zip(encountered, encountered[1:])):
            _repair_displaced_boundary_page(
                cur,
                page,
                script_db=script_db,
                default_lines=int(default_lines),
            )
            displaced_pages.append(page)

    info_inserted_pages = 0
    page_numbers = [
        int(r[0]) for r in cur.execute(
            'SELECT DISTINCT page_number FROM pages ORDER BY page_number'
        ).fetchall()
    ]
    for page in page_numbers:
        if page in skip:
            continue
        rows = _page_rows(cur, page)
        if not any(r['line_type'] == 'surah_name' for r in rows):
            continue
        updated = _normalize_surah_banners(rows, script_db=script_db)
        if updated != rows:
            _replace_page_rows(cur, page, updated)
            info_inserted_pages += 1

    spilled_pages = 0
    page_numbers = [
        int(r[0]) for r in cur.execute(
            'SELECT DISTINCT page_number FROM pages ORDER BY page_number'
        ).fetchall()
    ]
    for page in page_numbers:
        if page in skip:
            continue
        rows = _page_rows(cur, page)
        header_n = _leading_header_count(rows)
        if header_n < 2:
            continue
        # Only pages that open with a surah banner (name … basmala …).
        if rows[0]['line_type'] != 'surah_name':
            continue
        ayah_rows = []
        cursor = header_n
        while cursor < len(rows) and rows[cursor]['line_type'] == 'ayah':
            ayah_rows.append(rows[cursor])
            cursor += 1
        trailing = rows[cursor:]
        ayah_budget = int(default_lines) - header_n - len(trailing)
        if ayah_budget < 1:
            continue
        if len(ayah_rows) <= ayah_budget:
            continue
        keep = ayah_rows[:ayah_budget]
        excess_rows = ayah_rows[ayah_budget:]
        # When trailing mid-page content forces a cut, pack leading ayah denser
        # instead of dropping lines that still belong on this page's surah.
        if trailing and excess_rows:
            packed_words: list[int] = []
            for line in ayah_rows:
                packed_words.extend(
                    expand_ayah_words(line, universe=universe, script_db=script_db)
                )
            text_map = word_texts(script_db, packed_words)
            chunks = split_words_evenly(packed_words, ayah_budget)
            keep = []
            for chunk in chunks:
                line = {
                    'line_type': 'ayah',
                    'is_centered': 0,
                    'surah_number': ayah_rows[0].get('surah_number'),
                    'first_word_id': None,
                    'last_word_id': None,
                    'line_text': '',
                }
                assign_words_to_line(line, chunk, text_map)
                keep.append(line)
            _replace_page_rows(cur, page, rows[:header_n] + keep + trailing)
            spilled_pages += 1
            continue

        excess_words: list[int] = []
        for line in excess_rows:
            excess_words.extend(
                expand_ayah_words(line, universe=universe, script_db=script_db)
            )
        _replace_page_rows(cur, page, rows[:header_n] + keep + trailing)

        if not excess_words:
            spilled_pages += 1
            continue

        lines = load_all_lines(cur)
        start_idx = next(
            (
                i for i, line in enumerate(lines)
                if int(line['page_number']) > page and line['line_type'] == 'ayah'
            ),
            None,
        )
        if start_idx is None:
            if keep:
                last = dict(keep[-1])
                merged = (
                    expand_ayah_words(last, universe=universe, script_db=script_db)
                    + excess_words
                )
                text_map = word_texts(script_db, merged)
                assign_words_to_line(last, merged, text_map)
                keep[-1] = last
                _replace_page_rows(cur, page, rows[:header_n] + keep + trailing)
            spilled_pages += 1
            continue

        slots = ayah_segment_slots(lines, start_idx)
        if not slots:
            spilled_pages += 1
            continue
        slot_words = [
            expand_ayah_words(lines[i], universe=universe, script_db=script_db)
            for i in slots
        ]
        full_stream = excess_words + [w for sw in slot_words for w in sw]
        text_map = word_texts(script_db, full_stream)
        capacities = [max(1, len(sw)) for sw in slot_words]
        capacities[0] = capacities[0] + len(excess_words)
        cursor = 0
        for slot_i, line_i in enumerate(slots):
            if slot_i == len(slots) - 1:
                chunk = full_stream[cursor:]
            else:
                n = capacities[slot_i]
                chunk = full_stream[cursor:cursor + n]
                cursor += len(chunk)
            assign_words_to_line(lines[line_i], chunk, text_map)
            persist_line(cur, lines[line_i])
        spilled_pages += 1

    clamped_pages = _clamp_pages_to_line_count(
        cur,
        script_db=script_db,
        universe=universe,
        default_lines=int(default_lines),
        skip_pages=skip,
    )

    promoted_orphan_banners = _promote_orphan_trailing_banners(
        cur,
        skip_pages=skip,
    )
    if promoted_orphan_banners:
        clamped_pages += _clamp_pages_to_line_count(
            cur,
            script_db=script_db,
            universe=universe,
            default_lines=int(default_lines),
            skip_pages=skip,
        )

    filled_pages = _fill_pages_to_line_count(
        cur,
        script_db=script_db,
        universe=universe,
        default_lines=int(default_lines),
        skip_pages=skip,
    )

    metadata_fixed = _repair_ayah_surah_metadata(cur, script_db=script_db)

    return {
        'promoted_split_headers': promoted,
        'repaired_boundary_pages': displaced_pages,
        'info_pages': info_inserted_pages,
        'spilled_pages': spilled_pages,
        'clamped_pages': clamped_pages,
        'promoted_orphan_banners': promoted_orphan_banners,
        'filled_pages': filled_pages,
        'metadata_fixed': metadata_fixed,
    }


def _prepend_words_to_following_ayah(
    cur,
    after_page: int,
    excess_words: list[int],
    *,
    script_db: str,
    universe: list[int] | None,
) -> bool:
    """Prepend words onto the next same-surah ayah stream after ``after_page``."""
    if not excess_words:
        return True
    lines = load_all_lines(cur)
    start_idx = next(
        (
            i for i, line in enumerate(lines)
            if int(line['page_number']) > int(after_page) and line['line_type'] == 'ayah'
        ),
        None,
    )
    if start_idx is None:
        return False
    # Refuse to cross a surah separator between this page and the target ayah.
    page_last = max(
        (i for i, line in enumerate(lines) if int(line['page_number']) == int(after_page)),
        default=None,
    )
    if page_last is not None and separator_between(lines, page_last, start_idx):
        return False
    slots = ayah_segment_slots(lines, start_idx)
    if not slots:
        return False
    slot_words = [
        expand_ayah_words(lines[i], universe=universe, script_db=script_db)
        for i in slots
    ]
    full_stream = list(excess_words) + [w for sw in slot_words for w in sw]
    text_map = word_texts(script_db, full_stream)
    capacities = [max(1, len(sw)) for sw in slot_words]
    capacities[0] = capacities[0] + len(excess_words)
    cursor = 0
    for slot_i, line_i in enumerate(slots):
        if slot_i == len(slots) - 1:
            chunk = full_stream[cursor:]
        else:
            n = capacities[slot_i]
            chunk = full_stream[cursor:cursor + n]
            cursor += len(chunk)
        assign_words_to_line(lines[line_i], chunk, text_map)
        persist_line(cur, lines[line_i])
    return True


def _clamp_pages_to_line_count(
    cur,
    *,
    script_db: str,
    universe: list[int] | None,
    default_lines: int,
    skip_pages: set[int],
) -> int:
    """Spill trailing ayah off pages that exceed ``default_lines`` after banners.

    Mid-page ``name + info + basmala`` banners add a third header slot (e.g.
    page 498). Madinah/QPC keep a hard 15-line page; we do the same by moving
    the last ayah line's words onto the next page of the same surah. If that
    would cross a surah fence, densify into the previous ayah of the same block.
    """
    clamped = 0
    page_numbers = [
        int(r[0]) for r in cur.execute(
            'SELECT DISTINCT page_number FROM pages ORDER BY page_number'
        ).fetchall()
    ]
    for page in page_numbers:
        if page in skip_pages:
            continue
        guard = 0
        while guard < 20:
            guard += 1
            rows = _page_rows(cur, page)
            if not rows or len(rows) <= int(default_lines):
                break
            last_i = next(
                (i for i in range(len(rows) - 1, -1, -1) if rows[i]['line_type'] == 'ayah'),
                None,
            )
            if last_i is None:
                break
            excess = expand_ayah_words(
                rows[last_i], universe=universe, script_db=script_db,
            )
            fenced_on_page = any(
                is_surah_separator(row) for row in rows[last_i + 1:]
            )
            kept = rows[:last_i] + rows[last_i + 1:]
            _replace_page_rows(cur, page, kept)
            if not excess:
                clamped += 1
                continue
            if not fenced_on_page and _prepend_words_to_following_ayah(
                cur, page, excess, script_db=script_db, universe=universe,
            ):
                clamped += 1
                continue
            # Fenced: merge into the previous ayah of this same trailing block.
            rows2 = _page_rows(cur, page)
            prev_i = None
            search_from = min(last_i - 1, len(rows2) - 1)
            for i in range(search_from, -1, -1):
                if is_surah_separator(rows2[i]):
                    break
                if rows2[i]['line_type'] == 'ayah':
                    prev_i = i
                    break
            if prev_i is None:
                # Nowhere to put the words — put the line back and stop.
                _replace_page_rows(cur, page, rows)
                break
            merged = (
                expand_ayah_words(rows2[prev_i], universe=universe, script_db=script_db)
                + excess
            )
            text_map = word_texts(script_db, merged)
            prev = dict(rows2[prev_i])
            assign_words_to_line(prev, merged, text_map)
            _replace_page_rows(
                cur, page, rows2[:prev_i] + [prev] + rows2[prev_i + 1:],
            )
            clamped += 1
    return clamped


def _promote_orphan_trailing_banners(
    cur,
    *,
    skip_pages: set[int],
) -> int:
    """Move a trailing banner to the next page when it has no ayah beneath it."""
    promoted = 0
    page_numbers = [
        int(r[0]) for r in cur.execute(
            'SELECT DISTINCT page_number FROM pages ORDER BY page_number'
        ).fetchall()
    ]
    available = set(page_numbers)
    for page in page_numbers:
        if page in skip_pages or page + 1 not in available:
            continue
        rows = _page_rows(cur, page)
        name_indices = [
            i for i, row in enumerate(rows) if row['line_type'] == 'surah_name'
        ]
        if not name_indices:
            continue
        start = name_indices[-1]
        suffix = rows[start:]
        if not suffix or any(row['line_type'] == 'ayah' for row in suffix):
            continue
        if not all(row['line_type'] in SURAH_HEADER_TYPES for row in suffix):
            continue
        nxt = _page_rows(cur, page + 1)
        _replace_page_rows(cur, page, rows[:start])
        _replace_page_rows(cur, page + 1, suffix + nxt)
        promoted += 1
    return promoted


def _first_ayah_block(rows: list[dict]) -> tuple[int, list[dict], list[dict]]:
    """Return (block_start_index, ayah_rows, trailing_rows) for the first ayah run."""
    i = 0
    while i < len(rows) and rows[i]['line_type'] in SURAH_HEADER_TYPES:
        i += 1
    start = i
    ayah_rows: list[dict] = []
    while i < len(rows) and rows[i]['line_type'] == 'ayah':
        ayah_rows.append(rows[i])
        i += 1
    return start, ayah_rows, rows[i:]


def _ayah_rows_from_words(
    word_ids: list[int],
    n_slots: int,
    *,
    surah_number,
    script_db: str,
) -> list[dict]:
    ids = list(word_ids)
    if not ids:
        return []
    slots = max(1, min(int(n_slots), len(ids)))
    chunks = split_words_evenly(ids, slots)
    text_map = word_texts(script_db, ids)
    out: list[dict] = []
    for chunk in chunks:
        if not chunk:
            continue
        line = {
            'line_type': 'ayah',
            'is_centered': 0,
            'surah_number': surah_number,
            'first_word_id': None,
            'last_word_id': None,
            'line_text': '',
        }
        assign_words_to_line(line, chunk, text_map)
        out.append(line)
    return out


def _fill_pages_to_line_count(
    cur,
    *,
    script_db: str,
    universe: list[int] | None,
    default_lines: int,
    skip_pages: set[int],
) -> int:
    """Expand underfull pages to ``default_lines``.

    Azhar pages are always 15 lines. A leading surah banner (name + info +
    basmala) occupies 3 of those slots so 12 ayah lines remain; continuation
    pages with no banner still get 15 ayah lines (never left short after a
    promote/spill that removed a trailing surah_name).
    """
    filled = 0
    page_numbers = [
        int(r[0]) for r in cur.execute(
            'SELECT DISTINCT page_number FROM pages ORDER BY page_number'
        ).fetchall()
    ]
    for page in page_numbers:
        if page in skip_pages:
            continue
        rows = _page_rows(cur, page)
        if not rows or len(rows) >= int(default_lines):
            continue
        deficit = int(default_lines) - len(rows)
        block_start, ayah_rows, trailing = _first_ayah_block(rows)
        if not ayah_rows:
            continue
        prefix = rows[:block_start]
        target_ayah = len(ayah_rows) + deficit
        words: list[int] = []
        for line in ayah_rows:
            words.extend(expand_ayah_words(line, universe=universe, script_db=script_db))
        if not words:
            continue
        new_ayah = _ayah_rows_from_words(
            words,
            target_ayah,
            surah_number=ayah_rows[0].get('surah_number'),
            script_db=script_db,
        )
        new_rows = prefix + new_ayah + trailing
        if len(new_rows) <= len(rows):
            continue
        _replace_page_rows(cur, page, new_rows)
        filled += 1
    return filled


def _safe_table(name: str) -> str:
    """Allow only simple SQL identifiers for undo table names."""
    if not name or not all(c.isalnum() or c == '_' for c in name):
        raise ValueError(f'invalid undo table name: {name!r}')
    return name


def ensure_undo_table(cur, undo_table: str = 'azhar_layout_undo'):
    table = _safe_table(undo_table)
    cur.execute(
        f'''
        CREATE TABLE IF NOT EXISTS {table} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            label TEXT,
            page_number INTEGER,
            snapshot TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        '''
    )


def snapshot_page_range(cur, page_from: int, page_to: int | None = None) -> dict:
    """Snapshot only the page range a cascade can touch (not the whole DB)."""
    if page_to is None:
        cur.execute(
            '''
            SELECT id, page_number, first_word_id, last_word_id, line_text
            FROM pages
            WHERE page_number >= ?
            ORDER BY id ASC
            ''',
            (int(page_from),),
        )
    else:
        cur.execute(
            '''
            SELECT id, page_number, first_word_id, last_word_id, line_text
            FROM pages
            WHERE page_number >= ? AND page_number <= ?
            ORDER BY id ASC
            ''',
            (int(page_from), int(page_to)),
        )
    rows = [
        {
            'id': int(r[0]),
            'page_number': int(r[1]),
            'first_word_id': r[2],
            'last_word_id': r[3],
            'line_text': r[4] or '',
        }
        for r in cur.fetchall()
    ]
    return {
        'page_from': int(page_from),
        'page_to': int(page_to) if page_to is not None else None,
        'rows': rows,
    }


def push_undo(
    cur, label: str, page_number: int, page_from: int, page_to: int | None = None,
    *, undo_table: str = 'azhar_layout_undo',
):
    table = _safe_table(undo_table)
    ensure_undo_table(cur, table)
    payload = snapshot_page_range(cur, page_from=page_from, page_to=page_to)
    cur.execute(
        f'INSERT INTO {table} (label, page_number, snapshot) VALUES (?, ?, ?)',
        (label, page_number, json.dumps(payload, ensure_ascii=False)),
    )
    cur.execute(
        f'''
        DELETE FROM {table}
        WHERE id NOT IN (
            SELECT id FROM {table} ORDER BY id DESC LIMIT ?
        )
        ''',
        (_UNDO_LIMIT,),
    )


def undo_available(
    cur, page_number: int | None = None, *, undo_table: str = 'azhar_layout_undo',
) -> int:
    table = _safe_table(undo_table)
    ensure_undo_table(cur, table)
    if page_number is None:
        row = cur.execute(f'SELECT COUNT(*) FROM {table}').fetchone()
        return int(row[0] or 0)
    row = cur.execute(
        f'SELECT COUNT(*) FROM {table} WHERE page_number = ?',
        (int(page_number),),
    ).fetchone()
    return int(row[0] or 0)


def restore_snapshot(cur, snapshot) -> dict | None:
    """Restore a page-scoped (or legacy full-list) snapshot. Returns meta."""
    data = json.loads(snapshot) if isinstance(snapshot, str) else snapshot
    if isinstance(data, list):
        rows = data
        meta = {'page_from': None, 'page_to': None}
    else:
        rows = data.get('rows') or []
        meta = {
            'page_from': data.get('page_from'),
            'page_to': data.get('page_to'),
        }
    for row in rows:
        cur.execute(
            '''
            UPDATE pages
            SET first_word_id = ?, last_word_id = ?, line_text = ?
            WHERE id = ?
            ''',
            (row.get('first_word_id'), row.get('last_word_id'), row.get('line_text') or '', row['id']),
        )
    return meta


def pop_undo(
    cur, page_number: int | None = None, *, undo_table: str = 'azhar_layout_undo',
):
    """Pop the latest undo entry (optionally for one initiation page)."""
    table = _safe_table(undo_table)
    ensure_undo_table(cur, table)
    if page_number:
        row = cur.execute(
            f'''
            SELECT id, label, page_number, snapshot
            FROM {table}
            WHERE page_number = ?
            ORDER BY id DESC LIMIT 1
            ''',
            (int(page_number),),
        ).fetchone()
    else:
        row = cur.execute(
            f'''
            SELECT id, label, page_number, snapshot
            FROM {table}
            ORDER BY id DESC LIMIT 1
            '''
        ).fetchone()
    if not row:
        return None
    restore_snapshot(cur, row['snapshot'] if isinstance(row, sqlite3.Row) else row[3])
    undo_id = row['id'] if isinstance(row, sqlite3.Row) else row[0]
    label = row['label'] if isinstance(row, sqlite3.Row) else row[1]
    initiated = row['page_number'] if isinstance(row, sqlite3.Row) else row[2]
    cur.execute(f'DELETE FROM {table} WHERE id = ?', (undo_id,))
    return {'label': label, 'page_number': initiated}
