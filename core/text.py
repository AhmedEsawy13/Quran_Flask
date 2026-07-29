"""Quranic text normalisation and waqf-mark extraction.

Pure functions over the raw source texts (QPC / Digital Khatt / IndoPak):
search folding, token alignment, waqf-symbol extraction, and persistence of
the extracted rows. No Flask dependency — importable by every feature module.
"""
import logging
import sqlite3

from core.config import (
    WAQF_DATABASE,
    WAQF_SYMBOL_CHARS,
    INDOPAK_EXTRA_WAQF_SYMBOL_CHARS,
    NON_WAQF_SPECIFIC_CHARS,
    ARABIC_INDIC_DIGIT_PATTERN,
    _SEARCH_STRIP_PATTERN,
    _SEARCH_LETTER_FOLD,
)

logger = logging.getLogger(__name__)


def _normalize_for_search(text):
    """Fold vocalisation and common Arabic letter variants so exact-match
    search behaves the way a reader typing on a keyboard expects."""
    if not text:
        return ''
    cleaned = _SEARCH_STRIP_PATTERN.sub('', text)
    # Fold common letter variants (hamza forms, alif maqsura, taa marbuta).
    return ''.join(_SEARCH_LETTER_FOLD.get(ch, ch) for ch in cleaned)


def _search_normalization_variants(text):
    """Return search forms with Quranic dagger alif omitted and restored.

    The same Uthmani mark represents a written alif in words such as
    ``ٱلصَّدَقَٰتِ`` but is omitted in modern spelling of words such as
    ``هَٰذَا``. Keeping both deterministic forms makes basic Arabic search
    correct even when the optional imlaey transcription package is absent.
    """
    if not text:
        return {''}
    return {
        _normalize_for_search(text),
        _normalize_for_search(text.replace('\u0670', 'ا')),
    }


def is_waqf_like_char(char, source_name):
    if char in NON_WAQF_SPECIFIC_CHARS:
        return False
        
    if char in WAQF_SYMBOL_CHARS:
        return True

    if source_name == 'indopak_nastaleeq':
        # IndoPak source stores extra waqf/marker glyphs in this range.
        if char in INDOPAK_EXTRA_WAQF_SYMBOL_CHARS:
            return True
        # Specific patterns for IndoPak waqf symbols that might be composite or standalone
        # 0xE000-0xF8FF: Private Use Area often used for ligatures and markers in IndoPak fonts
        if 0xE000 <= ord(char) <= 0xF8FF:
            return True
        # Check for standard small markers often used in IndoPak
        if char in ['ؐ', 'ؑ', 'ؒ', 'ؓ', 'ؔ', 'ؕ', 'ؖ', 'ؗ', 'ؘ', 'ؙ', 'ؚ', 'ٛ', 'ٜ', 'ٝ', '٘', 'ٙ']:
            return True

    return False


def build_aligned_text(raw_text, source_name):
    """
    Keep original tokens except standalone waqf marker tokens in the middle of a verse.
    For IndoPak, this preserves end marker tokens while removing noisy in-verse marker-only tokens.
    """
    tokens = [token for token in (raw_text or '').split(' ') if token]
    if source_name != 'indopak_nastaleeq':
        return ' '.join(tokens)

    aligned_tokens = []
    last_index = len(tokens) - 1

    for idx, token in enumerate(tokens):
        stripped = ''.join(
            char for char in token if not is_waqf_like_char(char, source_name)
        ).strip()

        if stripped:
            aligned_tokens.append(token)
        elif idx == last_index:
            # Keep ayah-end marker token because segment indices often include it.
            aligned_tokens.append(token)

    return ' '.join(aligned_tokens)


def normalize_text_and_extract_waqf(raw_text, source_name):
    """
    Split verse text into alignment-safe tokens and extract waqf symbols.
    Returns cleaned words and per-token waqf symbol metadata.
    """
    tokens = [token for token in (raw_text or '').split(' ') if token]
    cleaned_words = []
    waqf_entries = []

    changed = False

    for original_index, token in enumerate(tokens):
        cleaned_chars = []
        symbols = []

        for char in token:
            if is_waqf_like_char(char, source_name):
                symbols.append(char)
            else:
                cleaned_chars.append(char)

        cleaned_token = ''.join(cleaned_chars).strip()
        digits_only = bool(cleaned_token) and ARABIC_INDIC_DIGIT_PATTERN.match(cleaned_token)
        current_word_index = None

        if cleaned_token and not digits_only:
            current_word_index = len(cleaned_words) + 1
        elif cleaned_words:
            current_word_index = len(cleaned_words)

        if symbols:
            changed = True
            waqf_entries.append({
                'token_index': original_index,
                'word_index': current_word_index,
                'symbols': ''.join(symbols),
                'original_token': token,
                'clean_token': cleaned_token
            })

        # Ayah-number tokens (e.g., ۝٤) should never be included in word alignment.
        if digits_only:
            changed = True
            continue

        if cleaned_token:
            if cleaned_token != token:
                changed = True
            cleaned_words.append(cleaned_token)

    return cleaned_words, waqf_entries, changed


def normalize_quran_dataset(source_name, source_data):
    """Extract waqf records and attach cleaned text without mutating original verse text."""
    if not isinstance(source_data, dict):
        return source_data, [], {'source': source_name, 'normalized': 0, 'mismatches': 0}

    normalized = {}
    waqf_rows = []
    normalized_count = 0
    for verse_key, verse_data in source_data.items():
        if not isinstance(verse_data, dict):
            normalized[verse_key] = verse_data
            continue

        verse_copy = dict(verse_data)
        original_text = verse_copy.get('text', '')
        cleaned_words, waqf_entries, changed = normalize_text_and_extract_waqf(original_text, source_name)
        aligned_text = build_aligned_text(original_text, source_name)

        if changed:
            normalized_text = ' '.join(cleaned_words)
            normalized_count += 1
            verse_copy['clean_text'] = normalized_text

        if source_name == 'indopak_nastaleeq' and aligned_text != original_text:
            verse_copy['raw_text'] = original_text
            verse_copy['text'] = aligned_text

        normalized[verse_key] = verse_copy

        if waqf_entries:
            try:
                surah_number, ayah_number = verse_key.split(':')
                surah_number = int(surah_number)
                ayah_number = int(ayah_number)
            except (ValueError, TypeError):
                continue

            for entry in waqf_entries:
                waqf_rows.append({
                    'source': source_name,
                    'verse_key': verse_key,
                    'surah_number': surah_number,
                    'ayah_number': ayah_number,
                    'token_index': entry['token_index'],
                    'word_index': entry.get('word_index'),
                    'symbols': entry['symbols'],
                    'original_token': entry['original_token'],
                    'clean_token': entry['clean_token']
                })

    stats = {
        'source': source_name,
        'normalized': normalized_count
    }
    return normalized, waqf_rows, stats


def initialize_waqf_database(waqf_rows):
    """Persist extracted waqf symbols in a dedicated SQLite database.

    Skips the full rebuild when the existing row count already matches, so
    repeated cold starts on serverless don't pay the write cost every time.
    """
    try:
        conn = sqlite3.connect(WAQF_DATABASE)
        cursor = conn.cursor()

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS waqf_symbols (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                verse_key TEXT NOT NULL,
                surah_number INTEGER NOT NULL,
                ayah_number INTEGER NOT NULL,
                token_index INTEGER NOT NULL,
                word_index INTEGER,
                symbols TEXT NOT NULL,
                original_token TEXT,
                clean_token TEXT
            )
        ''')
        existing_columns = {row[1] for row in cursor.execute('PRAGMA table_info(waqf_symbols)').fetchall()}
        if 'word_index' not in existing_columns:
            cursor.execute('ALTER TABLE waqf_symbols ADD COLUMN word_index INTEGER')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_waqf_lookup ON waqf_symbols(source, surah_number, ayah_number)')
        conn.commit()

        # Skip expensive rebuild if data is already current.
        cursor.execute('SELECT COUNT(*) FROM waqf_symbols')
        if cursor.fetchone()[0] == len(waqf_rows):
            conn.close()
            return

        # Rebuild inside a single transaction for crash safety.
        cursor.execute('BEGIN')
        cursor.execute('DELETE FROM waqf_symbols')
        if waqf_rows:
            cursor.executemany(
                '''
                INSERT INTO waqf_symbols (
                    source, verse_key, surah_number, ayah_number, token_index,
                    word_index, symbols, original_token, clean_token
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''',
                [(
                    row['source'], row['verse_key'], row['surah_number'], row['ayah_number'],
                    row['token_index'], row.get('word_index'), row['symbols'], row['original_token'], row['clean_token']
                ) for row in waqf_rows]
            )
        cursor.execute('COMMIT')
        conn.close()
    except sqlite3.Error as e:
        logger.error(f"Failed to initialize waqf database: {e}")
