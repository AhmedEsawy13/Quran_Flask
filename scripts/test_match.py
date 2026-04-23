import sqlite3
import re
from collections import defaultdict
import os

MUSHAF_WAQF_DATABASE = 'QUL_data/mushaf_waqf.db'
ARABIC_DIACRITICS_STRIP_PATTERN = re.compile(
        r'[\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06DC\u06DF-\u06E8\u06EA-\u06ED]'
    )

def _normalize_mushaf_word_token(value):
    text = (value or '').strip()
    if not text:
        return ''
    text = ARABIC_DIACRITICS_STRIP_PATTERN.sub('', text)
    return ''.join(ch for ch in text if not ch.isspace())

def get_mushaf_waqf_symbols(surah_number, ayah_number, mushaf_version):
    conn = sqlite3.connect(MUSHAF_WAQF_DATABASE)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    query = f'''
        SELECT "الكلمة" as word, "{mushaf_version}" as symbol, NULL as token_index 
        FROM waqf 
        WHERE "السورة" = ? AND "الآية" = ? 
        AND "{mushaf_version}" IS NOT NULL AND "{mushaf_version}" != ''
        ORDER BY rowid ASC
    '''
    cursor.execute(query, (surah_number, ayah_number))
    rows = cursor.fetchall()
    return [{'clean_token': row['word'], 'symbols': row['symbol']} for row in rows]

conn = sqlite3.connect('QUL_data/quran_script.db')
conn.row_factory = sqlite3.Row
words = [dict(row) for row in conn.execute("SELECT * FROM words WHERE surah = 58 AND ayah = 11 ORDER BY word_index ASC").fetchall()]

waqf_symbols = []
mushaf_version = 'المدينة'
mushaf_waqf_rows = get_mushaf_waqf_symbols(58, 11, mushaf_version)

search_start = 0
for row in mushaf_waqf_rows:
    target_word = _normalize_mushaf_word_token(row.get('clean_token') or '')
    print(f"Target: {target_word} (from {row.get('clean_token')})")
    
    matched_index = None
    for i in range(search_start, len(words)):
        candidate = _normalize_mushaf_word_token(words[i].get('text_original') or words[i].get('text') or '')
        if candidate == target_word:
            matched_index = i
            break
    
    if matched_index is None:
        for i in range(0, len(words)):
            candidate = _normalize_mushaf_word_token(words[i].get('text_original') or words[i].get('text') or '')
            if candidate == target_word:
                matched_index = i
                break
                
    if matched_index is not None:
        print(f"Matched {target_word} at {matched_index} ({words[matched_index]['text']})")
        waqf_symbols.append({"word_index": words[matched_index]['word_index'], "symbol": row['symbols']})
        search_start = matched_index + 1
    else:
        print(f"FAILED to match {target_word}")

print(waqf_symbols)
