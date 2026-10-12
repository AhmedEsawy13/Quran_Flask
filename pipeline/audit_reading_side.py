#!/usr/bin/env python3
"""Mark classical rows whose ruling holds only under a reading other than Hafs's.

منار and المكتفى keep both sides of a reading split («كاف لمن قرأ "تعلمون"
بالتاء، وليس بوقف لمن قرأ بالياء»), each with its condition in the note. The
app follows Hafs, so a row for the other side must be visibly marked, or a
reader who skips the note takes it as Hafs's ruling. The curated list lives in
pipeline/review/reading_side.json (every verdict read against the Hafs text);
this writes classical.reading = 'other' for those ids and NULL elsewhere.

Run after the other audits (idempotent):  python3 pipeline/audit_reading_side.py [--apply]
"""
import argparse
import json
import os
import sqlite3

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, 'data', 'classical_waqf.db')
LIST = os.path.join(ROOT, 'pipeline', 'review', 'reading_side.json')


def other_ids():
    data = json.load(open(LIST, encoding='utf-8'))
    return {(src, int(i)) for src, ids in data['other'].items() for i in ids}


def apply(con):
    cur = con.cursor()
    if 'reading' not in {c[1] for c in cur.execute('PRAGMA table_info(classical)')}:
        cur.execute('ALTER TABLE classical ADD COLUMN reading TEXT')
    want = other_ids()
    have = {(s, i) for s, i in cur.execute("SELECT source, id FROM classical WHERE reading='other'")}
    missing = [k for k in want if not cur.execute('SELECT 1 FROM classical WHERE source=? AND id=?', k).fetchone()]
    cur.execute("UPDATE classical SET reading=NULL WHERE reading IS NOT NULL")
    for src, rid in want:
        cur.execute("UPDATE classical SET reading='other' WHERE source=? AND id=?", (src, rid))
    con.commit()
    return {'marked': len(want) - len(missing), 'added': len(want - have), 'cleared': len(have - want),
            'missing_ids': sorted(missing)}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--db', default=DB)
    ap.add_argument('--apply', action='store_true')
    a = ap.parse_args(argv)
    con = sqlite3.connect(a.db)
    if not a.apply:
        print(len(other_ids()), 'rows listed as another reading (dry run; --apply to write)')
        return
    print('applied:', apply(con))


if __name__ == '__main__':
    main()
