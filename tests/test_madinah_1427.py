"""«المدينة ١٤٢٧» (print B) stays consistent with its source: the old print plus
the ملتقى أهل التفسير diff list (pipeline/build_madinah_1427.py)."""
import json
import os
import sqlite3

from pipeline.build_madinah_1427 import B_COL, DB, FORUM, OLD_COL, locate


def _db():
    return sqlite3.connect(DB)


def test_print_b_dropped_every_la():
    with _db() as conn:
        assert conn.execute(f'SELECT count(*) FROM waqf WHERE "{B_COL}" = \'لا\'').fetchone()[0] == 0
        assert conn.execute(f'SELECT count(*) FROM waqf WHERE "{OLD_COL}" = \'لا\'').fetchone()[0] == 68


def test_print_b_carries_every_forum_seat():
    seats = json.load(open(FORUM, encoding='utf-8'))['entries']
    assert len(seats) == 171
    with _db() as conn:
        for seat in seats:
            rowid = locate(conn, seat)
            assert rowid is not None, seat['id']
            old, b = conn.execute(
                f'SELECT coalesce("{OLD_COL}", ""), coalesce("{B_COL}", "") FROM waqf WHERE rowid=?',
                (rowid,)).fetchone()
            assert (old, b) == (seat['old_mark'], seat['new_mark']), seat['id']


def test_print_b_differs_from_old_only_at_listed_seats():
    # 67 «لا» removals + the 171 forum seats (المدثر 31 is both).
    with _db() as conn:
        differ = conn.execute(
            f'SELECT count(*) FROM waqf WHERE coalesce("{OLD_COL}","") <> coalesce("{B_COL}","")'
        ).fetchone()[0]
    assert differ == 238
    assert os.path.exists(FORUM)
