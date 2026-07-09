"""Raw Quranic source datasets, loaded once at import (local-first, CDN
fallback), plus the per-source NORMALISED variants (waqf marks extracted,
combining marks stripped) built on top of them — and the Amiri Quran font's
Azhar-marked variant, baked from QPC Hafs + the mushaf_waqf.db 'الأزهر'
column.
"""
import os
import re
import sqlite3
import logging

from flask import request

from core.loader import load_json_cdn_or_local as _load
from core.config import MUSHAF_WAQF_DATABASE, WAQF_SYMBOL_CHARS
from core.text import normalize_quran_dataset, initialize_waqf_database

logger = logging.getLogger(__name__)

# Local files live under data/quran_text/
digital_khatt_data = _load(
    'Digital_Khatt_Aya_Space.json', 'data/quran_text/Digital_Khatt_Aya_Space.json'
)
qpc_hafs_data = _load(
    'QPC Hafs.json', 'data/quran_text/QPC Hafs.json'
)
indopak_nastaleeq_data = _load(
    'Indopak Nastaleeq_Waqf.json', 'data/quran_text/Indopak Nastaleeq_Waqf.json'
)
indopak_nastaleeq_2_data = _load(
    'indopak-nastaleeq 2.json', 'data/quran_text/indopak-nastaleeq 2.json'
)
transliteration_data = _load(
    'Transliteration.json', 'data/quran_text/Transliteration.json'
)
surahs_data = _load('surahs.json', 'data/quran_text/surahs.json')
if not isinstance(surahs_data, list):
    surahs_data = []


digital_khatt_data_normalized, waqf_rows_digital, digital_stats = normalize_quran_dataset(
    'digital_khatt', digital_khatt_data
)
qpc_hafs_data_normalized, waqf_rows_qpc, qpc_stats = normalize_quran_dataset(
    'qpc_hafs', qpc_hafs_data
)
indopak_nastaleeq_data_normalized, waqf_rows_indopak, indopak_stats = normalize_quran_dataset(
    'indopak_nastaleeq', indopak_nastaleeq_data
)
indopak_nastaleeq_2_data_normalized, _, _ = normalize_quran_dataset(
    'indopak_nastaleeq', indopak_nastaleeq_2_data
)


# QUL waqf code → inline Arabic combining mark, used to bake an Azhar-marked
# variant of QPC Hafs for the Amiri Quran font.
_AZHAR_CODE_TO_MARK = {
    'م':   'ۘ',  # ۘ لازم
    'قلى': 'ۗ',  # ۗ قلى
    'ر':   'ۗ',  # ۗ راجح (rendered like قلى)
    'ج':   'ۚ',  # ۚ جائز
    'ص':   'ۖ',  # ۖ صلى
    'لا':  'ۙ',  # ۙ لا وقف
    'ع':   'ۛ',  # ۛ معانقة
    'س':   'ۜ',  # ۜ سكتة
}


def _encode_azhar_symbol(sym):
    if not sym:
        return ''
    s = sym.strip()
    if s in _AZHAR_CODE_TO_MARK:
        return _AZHAR_CODE_TO_MARK[s]
    # Already encoded as inline marks — pass through.
    if all(ch in WAQF_SYMBOL_CHARS for ch in s):
        return s
    return ''


# Trailing ayah-number suffix (NBSP + Arabic-Indic digits) that QPC Hafs glues
# to the last word. We insert waqf marks BEFORE this suffix so they sit on the
# word, not after the number.
_AYAH_END_SUFFIX_PATTERN = re.compile(r'[ \s][٠-٩۰-۹]+$')


def _insert_mark_before_ayah_end(token, mark):
    match = _AYAH_END_SUFFIX_PATTERN.search(token)
    if match:
        return token[:match.start()] + mark + token[match.start():]
    return token + mark


# Trailing run of Arabic-Indic digits at the very end of a verse — the ayah
# number. Used to prefix it with U+06DD so the Amiri Quran font draws it
# enclosed in the verse-end rosette.
_AYAH_NUMBER_TAIL_PATTERN = re.compile(r'(?<!۝)([٠-٩۰-۹]+)$')


def _wrap_ayah_number_with_end_marker(text):
    match = _AYAH_NUMBER_TAIL_PATTERN.search(text)
    if not match:
        return text
    return text[:match.start()] + '۝' + text[match.start():]


def _build_amiri_quran_data(base_data):
    """Bake الأزهر waqf marks into the QPC Hafs text so the Amiri Quran font
    shows them inline in 'original only' mode, matching how other mushaf fonts
    carry their tradition's marks in the text itself."""
    if not isinstance(base_data, dict):
        return base_data
    if not os.path.exists(MUSHAF_WAQF_DATABASE):
        # Without the source DB we can't transform — fall back to qpc_hafs as-is.
        return {k: dict(v) if isinstance(v, dict) else v for k, v in base_data.items()}

    try:
        conn = sqlite3.connect(MUSHAF_WAQF_DATABASE)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            'SELECT "السورة" AS surah, "الآية" AS ayah, '
            '"token_index" AS tidx, "الأزهر" AS sym '
            'FROM waqf '
            'WHERE "الأزهر" IS NOT NULL AND "الأزهر" != "" '
            'ORDER BY "السورة", "الآية", "token_index"'
        )
        rows = cur.fetchall()
        conn.close()
    except sqlite3.Error as exc:
        logger.warning(f'Could not read Azhar waqf for Amiri Quran build: {exc}')
        return {k: dict(v) if isinstance(v, dict) else v for k, v in base_data.items()}

    marks_by_verse = {}
    for r in rows:
        try:
            verse_key = f"{int(r['surah'])}:{int(r['ayah'])}"
            tidx = int(r['tidx'])
        except (TypeError, ValueError):
            continue
        mark = _encode_azhar_symbol(r['sym'])
        if not mark:
            continue
        marks_by_verse.setdefault(verse_key, []).append((tidx, mark))

    out = {}
    for verse_key, verse_data in base_data.items():
        if not isinstance(verse_data, dict):
            out[verse_key] = verse_data
            continue
        verse_copy = dict(verse_data)
        text = verse_copy.get('text', '') or ''
        # Strip the existing inline waqf marks so Azhar's are the only ones shown.
        stripped = ''.join(ch for ch in text if ch not in WAQF_SYMBOL_CHARS)
        # Split on every whitespace run (NBSP included) while preserving the
        # separators, so verses that start with ۞ joined to the next word by
        # NBSP still tokenise the way the mushaf_waqf DB expects.
        parts = re.split(r'(\s+)', stripped)
        token_part_indices = [i for i, p in enumerate(parts) if p and not p.isspace()]
        for tidx, mark in marks_by_verse.get(verse_key, []):
            i = tidx - 1
            if 0 <= i < len(token_part_indices):
                pi = token_part_indices[i]
                parts[pi] = _insert_mark_before_ayah_end(parts[pi], mark)
        verse_copy['text'] = _wrap_ayah_number_with_end_marker(''.join(parts))
        out[verse_key] = verse_copy
    return out


amiri_quran_data = _build_amiri_quran_data(qpc_hafs_data)
amiri_quran_data_normalized, _, amiri_stats = normalize_quran_dataset(
    'amiri_quran', amiri_quran_data
)

initialize_waqf_database(waqf_rows_digital + waqf_rows_qpc + waqf_rows_indopak)
logger.info(
    f"Waqf normalization summary: {digital_stats}, {qpc_stats}, {indopak_stats}, {amiri_stats}"
)


def normalize_source(source):
    valid_sources = [
        'digital_khatt', 'digital_khatt_2', 'old_madina',
        'indopak_nastaleeq', 'indopak_nastaleeq_2', 'qpc_hafs', 'shamarly',
        'amiri_quran'
    ]
    if source not in valid_sources:
        return 'qpc_hafs'
    if source in ('digital_khatt_2', 'old_madina'):
        return 'digital_khatt'
    return source


def get_quran_text_data_by_source(source):
    if source == 'digital_khatt':
        return digital_khatt_data_normalized
    if source == 'indopak_nastaleeq':
        return indopak_nastaleeq_data_normalized
    if source == 'indopak_nastaleeq_2':
        return indopak_nastaleeq_2_data_normalized
    if source == 'shamarly':
        return qpc_hafs_data_normalized
    if source == 'amiri_quran':
        return amiri_quran_data_normalized
    return qpc_hafs_data_normalized


def get_quran_text_data():
    source = normalize_source(request.args.get('source', 'qpc_hafs'))
    return get_quran_text_data_by_source(source)
