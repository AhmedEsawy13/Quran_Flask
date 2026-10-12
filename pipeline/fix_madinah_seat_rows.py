"""Repair four seats in data/mushaf_waqf.db that the QPC 1441 text and the
quran-engine (QVP) page ink both contradict.

* 3:7  — the row at token 16 carries «رَبِّنَا» marks, but word 16 is «فِي»;
         the marks belong on token 41 (رَبِّنَا).
* 3:66 — the row at token 7 is the FIRST «عِلۡمٞ»; the marks belong on the
         second one, token 14 («…لَيۡسَ لَكُم بِهِۦ عِلۡمٞۚ وَٱللَّهُ يَعۡلَمُ»).
* 69:28 — «المدينة الجديد» lacks the sakt on «مَالِيَهۡ» (QPC prints ۜ).
* 36:52 — «مَرۡقَدِنَا» carries both the sakt and قلى (ۜۗ) in both prints; the
         cell held only ق. Stored as «ق,س» — ruling first, since the research
         code reads the first symbol and the UI splits on the comma.

Only locally owned columns move. قطر / الكويت / البحرين are synced from the
published cloud editions (pipeline/sync_published_waqf.py), so they are left
for the editor. Idempotent: a second run changes nothing.
    python3 pipeline/fix_madinah_seat_rows.py
"""
import os
import sqlite3

DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'mushaf_waqf.db')
LOCAL_COLS = ('المدينة الجديد', 'الشمرلي', 'الأزهر', 'ورش')
# (surah, ayah, wrong token, right token, word text for the right row)
MOVES = (
    (3, 7, 16, 41, 'رَبِّنَاۗ'),
    (3, 66, 7, 14, 'عِلۡمٞۚ'),
)
SAKT = ((69, 28, 4, 'المدينة الجديد', 'س'),)
# (surah, ayah, token, columns, current value, value with the sakt added)
DUAL = ((36, 52, 6, ('المدينة الجديد', 'المدينة القديم'), 'ق', 'ق,س'),)


def _row(conn, surah, ayah, token):
    return conn.execute(
        'SELECT rowid FROM waqf WHERE السورة=? AND الآية=? AND token_index=?',
        (surah, ayah, token)).fetchone()


def main():
    conn = sqlite3.connect(DB)
    changed = 0
    for surah, ayah, wrong, right, text in MOVES:
        src, dst = _row(conn, surah, ayah, wrong), _row(conn, surah, ayah, right)
        if not src or not dst:
            raise SystemExit(f'{surah}:{ayah}: expected rows at tokens {wrong} and {right}')
        for col in LOCAL_COLS:
            value = conn.execute(f'SELECT "{col}" FROM waqf WHERE rowid=?', src).fetchone()[0]
            if not value:
                continue
            existing = conn.execute(f'SELECT "{col}" FROM waqf WHERE rowid=?', dst).fetchone()[0]
            if existing and existing != value:
                raise SystemExit(f'{surah}:{ayah} {col}: token {right} already has {existing}')
            conn.execute(f'UPDATE waqf SET "{col}"=? WHERE rowid=?', (value, dst[0]))
            conn.execute(f'UPDATE waqf SET "{col}"=NULL WHERE rowid=?', src)
            changed += 1
            print(f'{surah}:{ayah} {col}: {value} moved token {wrong} → {right}')
        conn.execute("UPDATE waqf SET الكلمة=? WHERE rowid=? AND coalesce(الكلمة,'')=''", (text, dst[0]))
    for surah, ayah, token, col, mark in SAKT:
        cur = conn.execute(
            f'UPDATE waqf SET "{col}"=? WHERE السورة=? AND الآية=? AND token_index=? '
            f'AND coalesce("{col}","")=""', (mark, surah, ayah, token))
        if cur.rowcount:
            changed += 1
            print(f'{surah}:{ayah} {col}: added {mark}')
    for surah, ayah, token, cols, before, after in DUAL:
        for col in cols:
            cur = conn.execute(
                f'UPDATE waqf SET "{col}"=? WHERE السورة=? AND الآية=? AND token_index=? AND "{col}"=?',
                (after, surah, ayah, token, before))
            if cur.rowcount:
                changed += 1
                print(f'{surah}:{ayah} {col}: {before} → {after}')
    conn.commit()
    conn.close()
    print(f'{changed} changes')


if __name__ == '__main__':
    main()
