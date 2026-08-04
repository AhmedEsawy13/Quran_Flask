"""Cross-layout checks for surah-boundary holes and blank ayah lines."""

from __future__ import annotations

import re
import sqlite3

from core.config import (
    AZHAR_LAYOUT_DATABASE,
    BAHRAIN_LAYOUT_DATABASE,
    DIGITAL_KHATT_LAYOUT_DATABASE,
    QPC_V1_LAYOUT_DATABASE,
    QPC_V2_LAYOUT_DATABASE,
    QURAN_SCRIPT_DATABASE,
    SHAMARLY_LAYOUT_DATABASE,
)
from core.datasets import digital_khatt_data
from modules import layout_engine, layouts


def _dk_map():
    layouts._DK_LAYOUT_WORD_MAP = None
    layouts._QPC_HAFS_LAYOUT_WORD_MAP = None
    return layouts._get_dk_layout_word_map()


def _content_gaps(layout_db: str, word_map: dict) -> list[tuple]:
    """Return (first_missing, last_missing, count, next_page_line) gaps."""
    id2 = word_map['id2tok']
    conn = sqlite3.connect(layout_db)
    rows = conn.execute(
        """
        SELECT page_number, line_number, first_word_id, last_word_id
        FROM pages
        WHERE line_type = 'ayah'
          AND first_word_id IS NOT NULL AND CAST(first_word_id AS TEXT) != ''
          AND last_word_id IS NOT NULL AND CAST(last_word_id AS TEXT) != ''
        ORDER BY page_number, line_number
        """
    ).fetchall()
    conn.close()

    gaps = []
    prev = None
    for page_number, line_number, first, last in rows:
        span = layouts._word_ids_in_map_span(word_map, int(first), int(last))
        if prev is not None and span and span[0] > prev + 1:
            missing = [wid for wid in range(prev + 1, span[0]) if wid in id2]
            if missing:
                gaps.append(
                    (missing[0], missing[-1], len(missing), (page_number, line_number))
                )
        if span:
            prev = span[-1]
    return gaps


def _empty_ayah_lines(build, pages: list[int]) -> list[tuple]:
    empty = []
    for page_number in pages:
        payload = build(page_number)
        assert payload is not None
        for line in payload['lines']:
            if line.get('line_type') != 'ayah':
                continue
            if line.get('first_word_id') in (None, ''):
                continue
            if line.get('words'):
                continue
            empty.append(
                (
                    page_number,
                    line.get('line_number'),
                    line.get('first_word_id'),
                    line.get('last_word_id'),
                )
            )
    return empty


def test_madinah_family_has_no_content_gaps_or_empty_ayah_lines():
    word_map = _dk_map()
    for name, db, build in (
        ('digital_khatt', DIGITAL_KHATT_LAYOUT_DATABASE, layouts._build_digital_khatt_page_payload),
        ('qpc_v2', QPC_V2_LAYOUT_DATABASE, layouts._build_qpc_v2_page_payload),
        ('qpc_v1', QPC_V1_LAYOUT_DATABASE, layouts._build_qpc_v1_page_payload),
        ('bahrain', BAHRAIN_LAYOUT_DATABASE, layouts._build_bahrain_page_payload),
    ):
        assert _content_gaps(db, word_map) == [], name
        with sqlite3.connect(db) as conn:
            pages = [
                row[0]
                for row in conn.execute(
                    'SELECT DISTINCT page_number FROM pages ORDER BY page_number'
                )
            ]
        assert _empty_ayah_lines(build, pages) == [], name


def test_madinah_surah_endings_keep_ayah_markers():
    """Every surah whose Digital Khatt text ends with ۝N must render that marker."""
    word_map = _dk_map()
    last_ayah = {}
    for entry in digital_khatt_data.values():
        surah, ayah = map(int, entry['verse_key'].split(':'))
        last_ayah[surah] = max(last_ayah.get(surah, 0), ayah)

    for surah, ayah in sorted(last_ayah.items()):
        source = digital_khatt_data[f'{surah}:{ayah}']['text']
        tokens = [part for part in re.split(r'\s+', source.strip()) if part]
        if not tokens or not layouts._is_ayah_number_token(tokens[-1]):
            continue
        last_id = word_map['last_id'][(surah, ayah)]
        with sqlite3.connect(DIGITAL_KHATT_LAYOUT_DATABASE) as conn:
            page = conn.execute(
                """
                SELECT page_number FROM pages
                WHERE line_type = 'ayah'
                  AND CAST(first_word_id AS INTEGER) <= ?
                  AND CAST(last_word_id AS INTEGER) >= ?
                ORDER BY page_number LIMIT 1
                """,
                (last_id, last_id),
            ).fetchone()
        assert page, (surah, ayah)
        payload = layouts._build_digital_khatt_page_payload(page[0])
        words = [
            word
            for line in payload['lines']
            for word in line['words']
            if word.get('surah') == surah and word.get('ayah') == ayah
        ]
        texts = [word['text'] for word in words]
        assert any(layouts._is_ayah_number_token(text) for text in texts), (
            surah, ayah, texts[-3:]
        )


def test_bahrain_yasin_closing_ayah_is_complete():
    payload = layouts._build_bahrain_page_payload(445)
    y83 = [
        word
        for line in payload['lines']
        for word in line['words']
        if word.get('surah') == 36 and word.get('ayah') == 83
    ]
    joined = ' '.join(word['text'] for word in y83)
    assert 'فَسُبْحَٰنَ' in joined
    assert 'تُرْجَعُونَ' in joined
    assert '۝٨٣' in joined


def test_shamarly_basmala_placeholders_are_not_blank_ayah_lines():
    script_map = layout_engine.script_word_map(QURAN_SCRIPT_DATABASE)
    for page_number in (514, 515):
        payload = layouts._build_shamarly_page_payload(page_number)
        for line in payload['lines']:
            if line.get('line_type') != 'ayah':
                continue
            first = line.get('first_word_id')
            last = line.get('last_word_id')
            if first in (None, '') or last in (None, ''):
                continue
            span = layouts._word_ids_in_map_span(script_map, first, last)
            if span:
                continue
            # Remaining empty expands must not be basmala-shaped ayah rows.
            assert not layouts._looks_like_basmala_text(line.get('raw_text')), (
                page_number, line.get('line_number'), line.get('raw_text')
            )


def test_azhar_has_no_empty_ayah_lines_on_sampled_pages():
    with sqlite3.connect(AZHAR_LAYOUT_DATABASE) as conn:
        pages = [
            row[0]
            for row in conn.execute(
                'SELECT DISTINCT page_number FROM pages ORDER BY page_number'
            )
        ]
    # Full scan is cheap enough for Azhar's 524 pages.
    assert _empty_ayah_lines(layouts._build_azhar_page_payload, pages) == []


def test_shamarly_has_no_empty_ayah_lines():
    with sqlite3.connect(SHAMARLY_LAYOUT_DATABASE) as conn:
        pages = [
            row[0]
            for row in conn.execute(
                'SELECT DISTINCT page_number FROM pages ORDER BY page_number'
            )
        ]
    assert _empty_ayah_lines(layouts._build_shamarly_page_payload, pages) == []
