#!/usr/bin/env python3
"""Curated fixes for القطع والائتناف (النحاس) after `build_classical_waqf.py
--only nahhas` (which parses the book with pipeline/nahhas_parse.py).

    python3 pipeline/audit_nahhas.py            # dry run: what would change
    python3 pipeline/audit_nahhas.py --apply    # write (idempotent)

What the parser cannot see:
  · الفاتحة is discussed in «باب ذكر السور» with ( … ) quotes, before the
    surah sections: «والتمام (بسم الله الرحمن الرحيم) … وهذا التمام» etc.
  · «ذوات قل» (الإخلاص، الفلق، الناس) is one section: «وقال غيرهما {قل هو
    الله أحد} قطع كاف … وكذا {قل أعوذ برب الفلق} وكذا {قل أعوذ برب الناس}».
  · «والتمام آخر السورة»، «ثم آخر السورة»: the surah's last word is تام.
  · a few citations too indirect for a rule (CURATED_BY).
Identical rulings on one word (same grade and scholar) collapse to one row.
"""
import argparse
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import logging
logging.disable(logging.INFO)
import build_classical_waqf as rx          # noqa: E402

DB = Path(__file__).resolve().parent.parent / 'data' / 'classical_waqf.db'

# (surah, ayah, grade, scholar, quote, note)
EXTRA = [
    (1, 1, 'تام', None, 'بسم الله الرحمن الرحيم',
     'والقطع على (بسم الله) جائز إلا أن الائتناف بما بعده لا ينبغي لأنه نعت، وكذا الوقف على (الرحمن) '
     'والتمام (بسم الله الرحمن الرحيم)'),
    (1, 4, 'تام', None, 'مالك يوم الدين',
     'لأن قوله (رب العالمين الرحمن الرحيم مالك يوم الدين) نعت وهذا التمام'),
    (1, 5, 'تام', None, 'وإياك نستعين',
     'ولا قف على (إياك) لأنه في موضع نصب ب (نعبد) ولا (نعبد) لأن ما بعده معطوف عليه والتمام (نستعين)'),
    (1, 7, 'تام', None, 'ولا الضالين',
     'ولا على (المغضوب) لأن الذي يقوم له مقام الفاعل بعده، والتمام (ولا الضالين)'),
    (113, 1, 'كاف', 'غيره', 'قل أعوذ برب الفلق',
     'وزعم الأخفش وأبو حاتم أنه لا تمام في هذه السورة إلى آخرها وقال غيرهما {قل هو الله أحد} قطع كاف '
     '… وكذا {قل أعوذ برب الفلق}'),
    (114, 1, 'كاف', 'غيره', 'قل أعوذ برب الناس',
     'وزعم الأخفش وأبو حاتم أنه لا تمام في هذه السورة إلى آخرها وقال غيرهما {قل هو الله أحد} قطع كاف '
     '… وكذا {قل أعوذ برب الناس}'),
]
# «قال الأخفش سعيد: وأما قوله جل وعز {مثلهم كمثل الذي استوقد نارا} فالتمام فيه
# عند قوله جل وعز {حذر الموت والله محيط بالكافرين}»
CURATED_BY = {(2, 'حذر الموت والله محيط بالكافرين', 'تام'): 'الأخفش'}
# 6:137–139: the text repeats «{فذرهم وما يفترون} افتراء عليه قطع حسن وكذا …»,
# so the «وكذا» chain after it is حسن (of «افتراء عليه»), not the تام before
REGRADE = {(6, 'سيجزيهم بما كانوا يفترون', 'تام'): 'حسن', (6, 'فهم فيه شركاء', 'تام'): 'حسن',
           (6, 'سيجزيهم وصفهم', 'تام'): 'حسن'}
# «ذوات قل» items the parser seated nowhere (they cite الفلق / الناس)
DROP_UNSEATED = {(112, 'قل أعوذ برب الفلق'), (112, 'قل أعوذ برب الناس')}

_END = re.compile(r'(?:والتمام|ثم|والوقف\s+التام|التمام)\s+آخر\s+السورة')


def surah_end_rulings():
    """[(surah, note)] for sections saying the last تمام is the end of the surah."""
    out = []
    for n, text in rx.nahhas_sections(rx.load_book(rx.SOURCES['nahhas'])):
        m = _END.search(text)
        if m:
            a = max(0, text.rfind('{', 0, m.start()))
            out.append((n, rx.clean_note(text[a:m.end()], limit=300)))
    return out


def plan(con):
    ops = []
    for (s, q, g), who in CURATED_BY.items():
        for rid, rf in con.execute("SELECT id, reported_from FROM classical WHERE source='nahhas' AND surah=? "
                                   "AND quote=? AND grade=?", (s, q, g)):
            if rf != who:
                ops.append(('attribute', rid, who))
    for (s, q, g), g2 in REGRADE.items():
        for (rid,) in con.execute("SELECT id FROM classical WHERE source='nahhas' AND surah=? AND quote=? "
                                  "AND grade=?", (s, q, g)):
            ops.append(('regrade', rid, g2))
    for s, q in DROP_UNSEATED:
        for (rid,) in con.execute("SELECT id FROM classical WHERE source='nahhas' AND surah=? AND quote=? "
                                  "AND ayah IS NULL", (s, q)):
            ops.append(('delete', rid, None))
    for s, a, g, who, q, note in EXTRA:
        w = len(rx.app._verse_word_texts(f'{s}:{a}')[1]) - 1
        if not con.execute("SELECT 1 FROM classical WHERE source='nahhas' AND surah=? AND ayah=? AND wpos=? "
                           "AND grade=? AND conf=1", (s, a, w, g)).fetchone():
            ops.append(('insert', (s, a, w, g, g, who, q, note), None))
    for s, note in surah_end_rulings():
        a = rx.surah_ayah_count(s)
        w = len(rx.app._verse_word_texts(f'{s}:{a}')[1]) - 1
        if not con.execute("SELECT 1 FROM classical WHERE source='nahhas' AND surah=? AND ayah=? AND wpos=? "
                           "AND grade='تام' AND reported_from IS NULL", (s, a, w)).fetchone():
            word = rx.app._verse_word_texts(f'{s}:{a}')[1][w]
            ops.append(('insert', (s, a, w, 'تام', 'آخر السورة', None, word, note), None))
    return ops


def merge_duplicates(con):
    """Identical rulings on one word (grade, scholar) keep the first row."""
    gone = 0
    for ids, in con.execute("SELECT group_concat(id) FROM classical WHERE source='nahhas' AND ayah IS NOT NULL "
                            "GROUP BY surah, ayah, wpos, grade, coalesce(reported_from, ''), conf "
                            "HAVING count(*) > 1").fetchall():
        keep, *rest = sorted(int(x) for x in ids.split(','))
        con.executemany('DELETE FROM classical WHERE id=?', [(r,) for r in rest])
        gone += len(rest)
    return gone


def apply(con):
    st = {}
    for op, x, who in plan(con):
        if op == 'attribute':
            con.execute('UPDATE classical SET reported_from=? WHERE id=?', (who, x))
        elif op == 'regrade':
            con.execute('UPDATE classical SET grade=?, grade_raw=? WHERE id=?', (who, who, x))
        elif op == 'delete':
            con.execute('DELETE FROM classical WHERE id=?', (x,))
        else:
            s, a, w, g, raw, who_, q, note = x
            word = rx.app._verse_word_texts(f'{s}:{a}')[1][w]
            seq = (con.execute("SELECT seq FROM classical WHERE source='nahhas' AND surah=? AND "
                               "(ayah<? OR (ayah=? AND wpos<=?)) ORDER BY ayah DESC, wpos DESC LIMIT 1",
                               (s, a, a, w)).fetchone() or (0,))[0]
            con.execute("INSERT INTO classical (source, surah, ayah, wpos, stop_word, quote, grade, grade_raw, "
                        "note, seq, conf, reported_from) VALUES ('nahhas',?,?,?,?,?,?,?,?,?,1,?)",
                        (s, a, w, word, q, g, raw, note, seq, who_))
        st[op] = st.get(op, 0) + 1
    st['merged'] = merge_duplicates(con)
    con.commit()
    return st


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--db', default=str(DB))
    args = ap.parse_args()
    con = sqlite3.connect(args.db)
    if args.apply:
        print('applied:', apply(con))
    else:
        ops = plan(con)
        print(len(ops), 'changes:', {k: sum(1 for o in ops if o[0] == k) for k in ('attribute', 'regrade', 'delete', 'insert')})
    con.close()


if __name__ == '__main__':
    main()
