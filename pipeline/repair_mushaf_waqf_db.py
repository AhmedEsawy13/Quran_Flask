"""
Repair mushaf_waqf.db:
  1. Fix NULL token_index rows by matching word text against QPC Hafs
  2. Merge waqf data from NULL rows into existing indexed rows where duplicate
  3. Delete all-NULL junk rows (no waqf data at all)
  4. Drop السورة.1 column
  5. Add UNIQUE(السورة, الآية, token_index) + index on (السورة, الآية)
"""
import sqlite3, json, re, os, unicodedata

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB   = os.path.join(BASE, 'QUL_data', 'mushaf_waqf.db')
QPC  = os.path.join(BASE, 'QUL_data', 'quran_text', 'QPC Hafs.json')

WAQF_COLS = ['المدينة', 'الشمرلي', 'الأزهر', 'ورش', 'الهندي']

# ── helpers ──────────────────────────────────────────────────────────────────

def strip_arabic(text):
    """Remove diacritics, waqf marks, tatweel, and ayah-number chars."""
    out = []
    for ch in text:
        cp = ord(ch)
        cat = unicodedata.category(ch)
        if cat == 'Mn':                    continue  # combining marks
        if 0x0610 <= cp <= 0x061A:         continue  # extended Arabic marks
        if 0x064B <= cp <= 0x065F:         continue  # harakat
        if 0x06D6 <= cp <= 0x06DC:         continue  # waqf combining marks
        if ch == '\u0640':                 continue  # tatweel
        if 0x0660 <= cp <= 0x0669:         continue  # Arabic-Indic digits (verse numbers)
        if 0x06F0 <= cp <= 0x06F9:         continue  # Extended Arabic-Indic digits
        if ch in '\u00A0\u200C\u200D':     continue  # NBSP, ZWJ, ZWNJ
        out.append(ch)
    return ''.join(out).strip()

def is_verse_number_token(tok):
    """True if the token is only verse-number digits (١٢٣…)."""
    return all(0x0660 <= ord(c) <= 0x0669 or 0x06F0 <= ord(c) <= 0x06F9 for c in tok.strip('\u00A0'))

# ── load QPC Hafs ─────────────────────────────────────────────────────────────

print("Loading QPC Hafs…")
with open(QPC) as f:
    qpc = json.load(f)   # {'1:1': {'text': '…'}, …}

def get_ayah_words(surah, ayah):
    """Return list of (1-based token_index, raw_word) for an ayah."""
    key = f'{surah}:{ayah}'
    if key not in qpc:
        return []
    text = qpc[key]['text']
    tokens = text.split()
    words = [(i + 1, t) for i, t in enumerate(tokens) if not is_verse_number_token(t)]
    return words

def find_position(surah, ayah, db_word):
    """Return (token_index, word_index) or (None, None) if not found."""
    needle = strip_arabic(db_word)
    if not needle:
        return None, None
    words = get_ayah_words(surah, ayah)
    matches = [idx for idx, raw in words if strip_arabic(raw) == needle]
    if len(matches) == 1:
        return matches[0], matches[0]
    # multiple matches → can't disambiguate; return None
    return None, None

# ── main repair ──────────────────────────────────────────────────────────────

con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row
cur = con.cursor()

# ── Step 1: delete pure-junk rows (all waqf cols NULL AND token_index NULL) ──
null_waqf_cond = ' AND '.join(f'"{c}" IS NULL' for c in WAQF_COLS)
cur.execute(f'''
    DELETE FROM waqf
    WHERE token_index IS NULL AND word_index IS NULL
    AND {null_waqf_cond}
''')
deleted_junk = cur.rowcount
print(f"Step 1: deleted {deleted_junk} all-NULL junk rows")

# ── Step 2: fix NULL token_index rows ────────────────────────────────────────
cur.execute('SELECT rowid, * FROM waqf WHERE token_index IS NULL ORDER BY السورة, الآية')
null_rows = cur.fetchall()
print(f"Step 2: {len(null_rows)} rows still have NULL token_index")

fixed = merged = skipped = 0

for row in null_rows:
    rid    = row['rowid']
    surah  = row['السورة']
    ayah   = row['الآية']
    word   = row['الكلمة'] or ''
    waqf   = {c: row[c] for c in WAQF_COLS}
    has_data = any(v for v in waqf.values())

    # 2a. Check if an indexed row already exists for same (surah, ayah, word)
    cur.execute(
        'SELECT rowid, * FROM waqf WHERE السورة=? AND الآية=? AND الكلمة=? AND token_index IS NOT NULL',
        (surah, ayah, word)
    )
    existing = cur.fetchone()

    if existing:
        if has_data:
            # Merge: fill in any NULL waqf columns in the existing row
            sets = []
            vals = []
            for c in WAQF_COLS:
                if existing[c] is None and waqf[c] is not None:
                    sets.append(f'"{c}"=?')
                    vals.append(waqf[c])
            if sets:
                vals.append(existing['rowid'])
                cur.execute(f'UPDATE waqf SET {", ".join(sets)} WHERE rowid=?', vals)
                print(f"  Merged {surah}:{ayah} '{word}' → token {existing['token_index']} ({', '.join(sets)})")
        cur.execute('DELETE FROM waqf WHERE rowid=?', (rid,))
        merged += 1
        continue

    # 2b. Try to find position from QPC Hafs text
    if word:
        ti, wi = find_position(surah, ayah, word)
        if ti is not None:
            cur.execute('UPDATE waqf SET token_index=?, word_index=? WHERE rowid=?', (ti, wi, rid))
            print(f"  Fixed {surah}:{ayah} '{word}' → token {ti}")
            fixed += 1
        else:
            print(f"  SKIP (ambiguous/not found): {surah}:{ayah} '{word}'")
            skipped += 1
    else:
        print(f"  SKIP (empty word): {surah}:{ayah} token_index=NULL")
        skipped += 1

print(f"  fixed={fixed}, merged={merged}, skipped={skipped}")

# ── Step 3: delete remaining NULL rows that still have no waqf data ──────────
cur.execute(f'''
    DELETE FROM waqf
    WHERE token_index IS NULL AND word_index IS NULL
    AND {null_waqf_cond}
''')
print(f"Step 3: deleted {cur.rowcount} additional junk rows")

# ── Step 4: rebuild table without السورة.1, with UNIQUE constraint ────────────
print("Step 4: rebuilding table schema…")
cur.execute('''
    CREATE TABLE waqf_new (
        السورة      INTEGER NOT NULL,
        الآية       INTEGER NOT NULL,
        الكلمة      TEXT,
        token_index INTEGER,
        word_index  INTEGER,
        المدينة     TEXT,
        الشمرلي     TEXT,
        الأزهر      TEXT,
        ورش         TEXT,
        الهندي      TEXT,
        UNIQUE(السورة, الآية, token_index)
    )
''')
cur.execute('''
    INSERT OR IGNORE INTO waqf_new
        (السورة, الآية, الكلمة, token_index, word_index, المدينة, الشمرلي, الأزهر, ورش, الهندي)
    SELECT
        السورة, الآية, الكلمة, token_index, word_index, المدينة, الشمرلي, الأزهر, ورش, الهندي
    FROM waqf
''')
cur.execute('DROP TABLE waqf')
cur.execute('ALTER TABLE waqf_new RENAME TO waqf')

# ── Step 5: drop old indexes, add new ones ────────────────────────────────────
print("Step 5: rebuilding indexes…")
for idx in ['idx_waqf_surah_ayah_token_index', 'idx_waqf_surah_ayah_word_index']:
    cur.execute(f'DROP INDEX IF EXISTS {idx}')

cur.execute('CREATE INDEX idx_waqf_surah_ayah ON waqf(السورة, الآية)')
cur.execute('CREATE INDEX idx_waqf_surah_ayah_token ON waqf(السورة, الآية, token_index)')
cur.execute('CREATE INDEX idx_waqf_surah_ayah_word  ON waqf(السورة, الآية, word_index)')

con.commit()

# ── Final stats ───────────────────────────────────────────────────────────────
cur.execute('SELECT COUNT(*) FROM waqf')
total = cur.fetchone()[0]
cur.execute('SELECT COUNT(*) FROM waqf WHERE token_index IS NULL')
still_null = cur.fetchone()[0]
cur.execute("SELECT name FROM sqlite_master WHERE type='index'")
indexes = [r[0] for r in cur.fetchall()]
cur.execute("PRAGMA table_info(waqf)")
cols = [r[1] for r in cur.fetchall()]

print(f"\n=== Done ===")
print(f"Total rows : {total}")
print(f"NULL token_index remaining : {still_null}")
print(f"Columns    : {cols}")
print(f"Indexes    : {indexes}")

con.close()
