#!/usr/bin/env python3
"""
build_indopak_waqf.py
----------------------
Extracts all waqf/pause symbols from the IndoPak Nastaleeq Quran text
(QUL_data/indopak-nastaleeq 2.json) and writes them as a new column
"الهندي" in QUL_data/mushaf_waqf.db — making IndoPak waqf available
in the mushaf version selector alongside المدينة / الأزهر / الشمرلي / ورش.

IndoPak waqf symbol inventory
──────────────────────────────
Standalone (space-separated) tokens found between words.
Traditional IndoPak letter names ↔ Unicode marks stored in DB:

  ؕ  U+0615  ARABIC SMALL HIGH TAH        → ط  مطلق   (absolute stop; IndoPak-only)
  ؗ  U+0617  ARABIC SMALL HIGH ZAIN       → ز  مجوَّز  (permitted for a reason)
  ۘ  U+06D8  ARABIC SMALL HIGH MEEM       → م  لازم   (mandatory)
  ۚ  U+06DA  ARABIC SMALL HIGH JEEM       → ج         (permitted stop)
  ۙ  U+06D9  ARABIC SMALL HIGH LAM ALEF   → لا        (no-stop)
  ۖ  U+06D6  ...SAD WITH LAM              → ص  مرخّص  (licensed for necessity)
  ۗ  U+06D7  ...QAF WITH LAM              → قلى       (prefer stop)
  ۛ  U+06DB  ARABIC SMALL HIGH THREE DOTS → ع         (muʿānaqah)

  ۟  U+06DF  ROUNDED ZERO                 = verse-end marker (not a waqf stop — SKIPPED)
  ۠  U+06E0  RECTANGULAR ZERO             = sajda/ruku marker (SKIPPED)
  Private Use Area U+F500–U+F6FF          = font ligatures for verse numbers (SKIPPED)

Placement: the IndoPak text does not always split a verse into the same words as
quran_script.db (27:20 «مَا لِيَ», 72:16, 73:20 …), so each verse's IndoPak words are
ALIGNED to its quran_script words by their letters (difflib on a consonant skeleton),
not counted. Counting put 12 marks on the wrong word; 32 marks in 14 verses were never
written (found 2026-10-15). `--check` compares the column with the source and exits 1
on any difference.

Usage:
  python pipeline/build_indopak_waqf.py --check
  python pipeline/build_indopak_waqf.py --reset      # rebuild the column from the source
"""

import argparse
import collections
import difflib
import json
import re
import sqlite3
import sys
import unicodedata
from pathlib import Path

BASE            = Path(__file__).parent.parent
INDOPAK_JSON    = BASE / "data/quran_text/Indopak Nastaleeq_Waqf.json"
MUSHAF_WAQF_DB  = BASE / "data/mushaf_waqf.db"
QURAN_SCRIPT_DB = BASE / "data/quran_script.db"
SURAHS_JSON     = BASE / "data/quran_text/surahs.json"

INDOPAK_COL = "الهندي"

# ── Codepoint sets ────────────────────────────────────────────────────────────

# Standard waqf range + IndoPak-specific marks
WAQF_CPS = set(range(0x06D6, 0x06EE))   # U+06D6–U+06ED
WAQF_CPS |= {
    0x0615,  # ؕ  ط مطلق (absolute stop)
    0x0617,  # ؗ  ز مجوَّز
    0x0614,  # ؔ  takhallus / قف mark
    0x06EA,  # ۪  empty centre low stop
    0x06EB,  # ۫  empty centre high stop
    0x06EC,  # ۬  rounded high stop
}

# These appear in standalone tokens but are NOT waqf stop marks — skip them
SKIP_CPS = {
    0x06DF,  # ۟  rounded zero  = verse-end marker
    0x06E0,  # ۠  rectangular zero = sajda/ruku marker
}
SKIP_CPS |= set(range(0xF500, 0xF700))  # private-use font ligatures
SKIP_CPS |= {0xF61E, 0xF68F}

# Arabic base letters (including Urdu/Persian extensions)
ARABIC_BASE = (
    set(range(0x0621, 0x063B)) |
    set(range(0x0641, 0x064B)) |
    {0x06CC, 0x06A9, 0x06AF, 0x06BA, 0x06BE, 0x06C1, 0x06C3}
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def is_content_word(token: str) -> bool:
    """True if the token contains at least one Arabic base letter."""
    return any(ord(c) in ARABIC_BASE for c in token)


def extract_waqf_symbol(token: str) -> str | None:
    """Strip verse-end / private-use chars from a standalone waqf token.

    Returns the cleaned symbol string, or None if nothing remains after stripping.
    """
    cleaned = "".join(c for c in token if ord(c) not in SKIP_CPS)
    return cleaned.strip() or None


def load_sura_names(surahs_path: Path) -> dict[int, str]:
    with open(surahs_path, encoding="utf-8") as f:
        return {s["number"]: s["name"] for s in json.load(f)}


def ensure_column(conn: sqlite3.Connection, reset: bool) -> None:
    existing = [c[1] for c in conn.execute("PRAGMA table_info(waqf)").fetchall()]
    if INDOPAK_COL not in existing:
        conn.execute(f'ALTER TABLE waqf ADD COLUMN "{INDOPAK_COL}" TEXT')
        conn.commit()
        print(f"  Added column '{INDOPAK_COL}'")
    elif reset:
        conn.execute(f'UPDATE waqf SET "{INDOPAK_COL}" = NULL')
        conn.commit()
        print(f"  Reset existing '{INDOPAK_COL}' values")
    else:
        print(f"  Column '{INDOPAK_COL}' already exists — appending (use --reset to rebuild)")


def get_word_text(qs_cur: sqlite3.Cursor, sura: int, aya: int, pos: int) -> str:
    row = qs_cur.execute(
        "SELECT text FROM words WHERE word_key=?",
        (f"{sura}:{aya}:{pos}",)
    ).fetchone()
    return row[0] if row else ""


def _unused_place_symbol(
    waqf_cur: sqlite3.Cursor,
    qs_cur: sqlite3.Cursor,
    sura_names: dict,
    sura: int, aya: int, word_pos: int,
    symbol: str,
) -> None:
    """Insert/update a symbol at content word ``word_pos`` in mushaf_waqf.db.

    quran_script.db and token_index count a leading ۞ as a word; word_pos
    does not. Look rows up by token_index (word_pos + that offset) — rows
    disagree on word_index in ۞ verses, which once put these marks one word
    early (fixed by pipeline/fix_hizb_verse_rows.py).
    """
    first = get_word_text(qs_cur, sura, aya, 1).strip()
    token = word_pos + (1 if first == '۞' else 0)
    row = waqf_cur.execute(
        f'SELECT rowid, "{INDOPAK_COL}" FROM waqf WHERE "السورة"=? AND "الآية"=? AND token_index=?',
        (sura, aya, token),
    ).fetchone()

    if row:
        rowid, existing = row
        new_val = (existing + symbol) if (existing and existing != symbol) else symbol
        waqf_cur.execute(
            f'UPDATE waqf SET "{INDOPAK_COL}"=? WHERE rowid=?',
            (new_val, rowid),
        )
    else:
        word_text = get_word_text(qs_cur, sura, aya, token)
        waqf_cur.execute(
            f"""INSERT INTO waqf
                ("السورة", "السورة.1", "الآية", "الكلمة", "{INDOPAK_COL}", word_index, token_index)
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (sura, sura_names.get(sura, ""), aya, word_text, symbol, word_pos, token),
        )


# ── Alignment ────────────────────────────────────────────────────────────────

_FOLD = str.maketrans({'ی': 'ي', 'ى': 'ي', 'ئ': 'ي', 'ک': 'ك', 'ہ': 'ه', 'ۃ': 'ة', 'ة': 'ه',
                       'أ': 'ا', 'إ': 'ا', 'آ': 'ا', 'ٱ': 'ا', 'ؤ': 'و'})
# IndoPak font ligatures that stand for whole words
_PUA_WORDS = {'\uf664': 'انثي', '\uf668': 'وفي'}
_VERSE_NUMBER = re.compile(r'[\u06dd٠-٩0-9 ]+')


def _skeleton(word: str) -> str:
    """Consonant skeleton for matching an IndoPak word to its Uthmani spelling."""
    for k, v in _PUA_WORDS.items():
        word = word.replace(k, v)
    word = ''.join(c for c in word if not ('\ue000' <= c <= '\uf8ff'))
    word = ''.join(c for c in unicodedata.normalize('NFKD', word) if unicodedata.category(c) != 'Mn')
    word = re.sub(r'[^ء-ي]', '', word.translate(_FOLD).replace('ـ', ''))
    return re.sub('[اويء]', '', word)


# Stop signs as they end a word; 15 in the source are typed with no space before them
# (2:219 «الْعَفْوَؕ», 3:2 «هُوَۙ» …) and quranwbw's IndoPak text has them on those words.
# Not ؔ: attached to a word (76:15-16 «قَوَارِیْرَاۡؔ») it marks an unread alif, not a stop.
_STOP_SIGNS = set('۪ؕؗۖۗۘۙۚۛ۫۬')


def _attached_marks(word: str) -> str:
    tail = ''
    for ch in reversed(word):
        if ch in _STOP_SIGNS:
            tail = ch + tail
        elif '\ue000' <= ch <= '\uf8ff':      # font glyphs between the word and its sign
            continue
        else:
            break
    return tail


# Where the source disagrees with two independent copies of the same IndoPak text —
# quranwbw.com (Qalam Hanafi edition, words-data/arabic/6.json) and quran.com
# (api/v4 quran/verses/indopak) — and both say the same thing (checked 2026-10-15).
# Key: (surah, ayah, IndoPak word position) -> the sign that word carries.
SOURCE_CORRECTIONS = {
    (3, 4, 18): 'ؕ',     # «انتقام» verse end: ط missing in the source
    (11, 94, 10): 'ۚ',   # «منّا»: ج missing in the source
    (41, 24, 5): 'ؕ',    # «لهم»: source ج, both copies ط
    (58, 4, 10): 'ؕ',    # «يتماسّا»: source ج, both copies ط
}


def derive_marks(indopak: dict, qs_conn: sqlite3.Connection) -> tuple[dict, list]:
    """{(surah, ayah, token_index): symbols} from the IndoPak text, placed by alignment.

    token_index counts a leading ۞ like the waqf table does. Returns the marks and the
    list of marks that could not be aligned (should be empty)."""
    words = collections.defaultdict(list)
    for key, text in qs_conn.execute('SELECT word_key, text FROM words'):
        s, a, w = map(int, key.split(':'))
        words[(s, a)].append((w, text))
    marks, unplaced = {}, []
    for vk, entry in indopak.items():
        s, a = map(int, vk.split(':'))
        verse = sorted(words[(s, a)])
        hizb = 1 if verse and verse[0][1].strip() == '۞' else 0
        db = [t for w, t in verse if t.strip() != '۞' and not _VERSE_NUMBER.fullmatch(t.strip())]
        ip, found = [], []
        for tok in entry.get('text', '').split():
            if is_content_word(tok):
                ip.append(tok)
                if (tail := _attached_marks(tok)):          # a sign typed without its space
                    found.append((len(ip) - 1, tail))
            elif (sym := extract_waqf_symbol(tok)) and ip:
                found.append((len(ip) - 1, sym))
        corrected = {(s, a, i + 1) for i, _ in found} & set(SOURCE_CORRECTIONS)
        found = [(i, SOURCE_CORRECTIONS.get((s, a, i + 1), sym)) for i, sym in found]
        found += [(p - 1, sym) for (cs, ca, p), sym in SOURCE_CORRECTIONS.items()
                  if (cs, ca) == (s, a) and (cs, ca, p) not in corrected]
        to_db = {}
        matcher = difflib.SequenceMatcher(None, [_skeleton(t) for t in ip], [_skeleton(t) for t in db], autojunk=False)
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == 'equal' or (tag == 'replace' and i2 - i1 == j2 - j1):
                for k in range(i2 - i1):
                    to_db[i1 + k] = j1 + k
            elif tag == 'replace':          # n IndoPak words <-> m words: a mark after the block goes on its last word
                to_db[i2 - 1] = j2 - 1
        for i, sym in found:
            if i not in to_db:
                unplaced.append((vk, i + 1, ip[i], sym))
                continue
            key = (s, a, to_db[i] + 1 + hizb)
            marks[key] = marks.get(key, '') + sym
    return marks, unplaced


def stored_marks(conn: sqlite3.Connection) -> dict:
    return {(s, a, t): v for s, a, t, v in conn.execute(
        f'SELECT "السورة", "الآية", token_index, "{INDOPAK_COL}" FROM waqf '
        f'WHERE "{INDOPAK_COL}" IS NOT NULL AND "{INDOPAK_COL}" != ""')}


# ── Main ─────────────────────────────────────────────────────────────────────

def build(check: bool = False, reset: bool = False) -> int:
    with open(INDOPAK_JSON, encoding="utf-8") as f:
        indopak = json.load(f)
    qs_conn = sqlite3.connect(QURAN_SCRIPT_DB)
    waqf_conn = sqlite3.connect(MUSHAF_WAQF_DB)
    marks, unplaced = derive_marks(indopak, qs_conn)
    have = stored_marks(waqf_conn)
    add = {k: v for k, v in marks.items() if k not in have}
    drop = {k: v for k, v in have.items() if k not in marks}
    change = {k: (have[k], v) for k, v in marks.items() if k in have and have[k] != v}
    print(f"{len(indopak):,} verses, {len(marks):,} marks in the source, {len(have):,} in the column; "
          f"unaligned {len(unplaced)}")
    print(f"missing {len(add)}, extra/misplaced {len(drop)}, symbol differs {len(change)}")
    for name, rows in (('missing', add), ('extra', drop), ('differs', change)):
        for k, v in list(rows.items())[:15]:
            print(f"  {name:8s} {k[0]}:{k[1]} token {k[2]}  {v!r}")
    if check:
        return 1 if (add or drop or change or unplaced) else 0
    if unplaced:
        print('refusing to write: some marks could not be aligned'); return 1

    ensure_column(waqf_conn, reset)
    cur, qs_cur = waqf_conn.cursor(), qs_conn.cursor()
    if not reset:   # targeted: clear only the rows that are wrong
        marks_cols = [c[1] for c in cur.execute('PRAGMA table_info(waqf)')
                      if c[1] not in ('السورة', 'الآية', 'الكلمة', 'token_index', 'word_index')]
        nothing_left = ' AND '.join(f'("{c}" IS NULL OR "{c}" = \'\')' for c in marks_cols)
        for (s, a, t) in drop:
            cur.execute(f'UPDATE waqf SET "{INDOPAK_COL}"=NULL WHERE "السورة"=? AND "الآية"=? AND token_index=?', (s, a, t))
            # a row that only held this misplaced mark goes with it
            cur.execute(f'DELETE FROM waqf WHERE "السورة"=? AND "الآية"=? AND token_index=? AND {nothing_left}', (s, a, t))
    targets = marks if reset else {**add, **{k: v for k, (_, v) in change.items()}}
    for (s, a, t), sym in targets.items():
        row = cur.execute('SELECT rowid FROM waqf WHERE "السورة"=? AND "الآية"=? AND token_index=?', (s, a, t)).fetchone()
        if row:
            cur.execute(f'UPDATE waqf SET "{INDOPAK_COL}"=? WHERE rowid=?', (sym, row[0]))
        else:
            first = get_word_text(qs_cur, s, a, 1).strip()
            cur.execute(f'''INSERT INTO waqf ("السورة", "الآية", "الكلمة", "{INDOPAK_COL}", word_index, token_index)
                            VALUES (?, ?, ?, ?, ?, ?)''',
                        (s, a, get_word_text(qs_cur, s, a, t), sym, t - (1 if first == '۞' else 0), t))
    waqf_conn.commit()
    left = stored_marks(waqf_conn)
    print(f"wrote; column now {len(left):,} marks, equal to the source: {left == marks}")
    return 0 if left == marks else 1


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Build الهندي waqf column from IndoPak JSON")
    p.add_argument("--check", action="store_true", help="Compare the column with the source; write nothing")
    p.add_argument("--reset", action="store_true", help="Clear the column and rebuild it entirely")
    args = p.parse_args()
    sys.exit(build(check=args.check, reset=args.reset))
