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
from core.verse_words import verse_word_texts  # noqa: E402

DB = Path(__file__).resolve().parent.parent / 'data' / 'classical_waqf.db'

# (surah, ayah, grade, scholar, quote, note)
EXTRA = [
    # «… {ثم نكسوها لحما} قطع حسن وكذا قال {أعلم أن الله على كل شيء قدير}» (نافع)
    (2, 259, 'حسن', 'نافع', 'أعلم أن الله على كل شيء قدير',
     'وعن نافع {ثم بعثه} تمام، قال {لم يتسنه} تمام {ثم نكسوها لحما} قطع حسن وكذا قال '
     '{أعلم أن الله على كل شيء قدير}'),
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
CURATED_BY = {(2, 'حذر الموت والله محيط بالكافرين', 'تام'): 'الأخفش',
              # «{وتراهم يعرضون عليها خاشعين} تمام عند بعضهم وأكثر أصحاب التمام …»
              (42, 'وتراهم يعرضون عليها خاشعين', 'تام'): 'بعضهم',
              # «وأما قول الأخفش المعنى {وإذ واعدنا موسى} تمام … فمخالف للظاهر»
              (2, 'وإذ واعدنا موسى', 'تام'): 'الأخفش',
              # «قال أبو حاتم {والقرآن الحكيم} {إنك لمن المرسلين} كاف، قال والتمام
              # {على صراط مستقيم}. وغلط في القولين جميعا»
              (36, 'إنك لمن المرسلين', 'كاف'): 'أبو حاتم', (36, 'على صراط مستقيم', 'تام'): 'أبو حاتم',
              # «قال محمد بن يزيد: قال لي المازني {فستبصر ويبصرون} تمام»
              (68, 'فستبصر ويبصرون', 'تام'): 'المازني',
              # «{ويؤت كل ذي فضل فضله} وقف كاف حسن عند أبي حاتم وتمام عند الأخفش»
              (11, 'ويؤت كل ذي فضل فضله', 'كاف'): 'أبو حاتم',
              # «{والمقيمين الصلاة} تمام على مذهب سيبويه» (نصب على المدح)
              (4, 'والمقيمين الصلاة', 'تام'): 'سيبويه',
              # second random check (2026-10-08):
              # «وعن نافع {ثم بعثه} تمام، قال {لم يتسنه} تمام {ثم نكسوها لحما} قطع حسن وكذا قال …»
              (2, 'ثم نكسوها لحما', 'حسن'): 'نافع',
              # «ولا تمام عند الأخفش من {وقالوا الحمد لله} إلى {ولا يمسنا فيها لغوب} هذا التمام عنده»
              (35, 'ولا يمسنا فيها لغوب', 'تام'): 'الأخفش',
              # «وقال بعض أهل التمام … ومن قرأ {عبادنا} فوقفه الكافي {أولى الأيدي والأبصار}»
              (38, 'أولى الأيدي والأبصار', 'كاف'): 'بعضهم'}
# 6:137–139: the text repeats «{فذرهم وما يفترون} افتراء عليه قطع حسن وكذا …»,
# so the «وكذا» chain after it is حسن (of «افتراء عليه»), not the تام before
REGRADE = {(6, 'سيجزيهم بما كانوا يفترون', 'تام'): 'حسن', (6, 'فهم فيه شركاء', 'تام'): 'حسن',
           (6, 'سيجزيهم وصفهم', 'تام'): 'حسن'}
# seats the book's order contradicts (2026-09-27 order sweep): (surah, ayah,
# quote) → (ayah, wpos). «{كذلك يبين الله لكم الآيات} قطع كاف والتمام {والله
# عليكم حكيم}» is 24:58; «وقال محمد بن عيسى {من بعد ما تبين لهم الهدى}» 47:25
MOVES = {(24, 18, 'والله عليكم حكيم'): (58, 48), (47, 32, 'من بعد ما تبين لهم الهدى'): (25, 10),
         # «والتمام {عند} غيره {إن الله عزيز غفور}»: the copy braced «عند»
         (35, 39, 'عند'): (28, 16),
         # «لأن ما بعده نعت للمؤمنين إلى قوله {الذين يرثون الفردوس}… يكون التمام
         # {الذين يرثون الفردوس}»: the verse (23:11) ends the description
         (23, 11, 'الذين يرثون الفردوس'): (11, 5)}
# (surah, ayah, quote as parsed) → (quote, reported_from) the book means
QUOTE_FIX = {(35, 28, 'عند'): ('إن الله عزيز غفور', 'غيره')}
# held rows the builder left unseated (the copy's slips «حلبة»، «خق»، «سأته»،
# «يزيدفي»، «إ الله», or a repeated phrase it could not place), seated by
# fuzzy match inside the book-order window and read one by one (2026-10-08):
# (surah, quote as parsed, grade, reported_from) → (ayah, wpos, reported_from)
SEAT_HELD = {
    (2, 'هل ينظرون إلا أن يأتيهم في ظلل من الغمام', 'تام', None): (210, 9, 'يعقوب'),
    (3, 'أولئك هم المفلحون', 'تام', None): (104, 13, None),
    (4, 'وآتوا النساء صدقاتهن حلة', 'تام', 'نافع'): (4, 3, 'نافع'),
    (4, 'لكن الراسخون في العلم منهم والمؤمنون يؤمنون بما أنزل إليك وما أنزل من قبلك', 'كاف', 'يعقوب'): (162, 13, 'يعقوب'),
    (5, 'على أن لا تعدلوا', 'تام', 'أحمد بن جعفر'): (8, 14, 'أحمد بن جعفر'),
    (5, 'على أن لا تعدلوا', 'كاف', 'غيره'): (8, 14, 'غيره'),
    (5, 'وذلك جزاء الظالمين', 'حسن', None): (29, 12, None),
    (5, 'لأكلوا من فوقهم ومن تحتهم أرجلهم منهم أمة مقتصدة', 'صالح', None): (66, 18, None),
    (5, 'لقد كفر الذين قالوا إن الله هو المسيح بن مريم', 'تام', 'نافع'): (72, 9, 'نافع'),
    (5, 'لقد كفر الذين قالوا إن الله هو المسيح بن مريم', 'صالح', 'غيره'): (72, 9, 'غيره'),
    (5, 'أو لو كان آباؤهم لا يعلمون شيئا ولا يهتدون', 'تام', None): (104, 23, None),
    (7, 'أو لم يتفكروا', 'تام', 'أبو حاتم'): (184, 1, 'أبو حاتم'),
    (9, 'أولئك هم الخاسرون', 'تام', None): (69, 31, None),
    (11, 'وارتقبوا إني معكم قريب', 'تام', None): (93, 18, None),
    (12, 'قال هي راودتني عن نفس', 'حسن', None): (26, 4, None),
    (16, 'تنبوئنهم في الدنيا حسنة', 'كاف', 'أبو حاتم'): (41, 11, 'أبو حاتم'),
    (17, 'وفي آذانهم وقر', 'كاف', None): (46, 8, None),
    (18, 'وهئ لنا من أمرنا رشدا', 'كاف', None): (10, 15, None),
    (19, 'وجعلني مباركا أينما كنت', 'تام', 'أحمد بن موسى'): (31, 4, 'أحمد بن موسى'),
    (20, 'ومنها يخرجكم تارة أخرى', 'تام', None): (55, 7, None),
    (21, 'تنقصها من أطرافها', 'كاف', None): (44, 15, None),
    (21, 'وكنا له حافظين', 'تام', None): (82, 11, None),
    (21, 'أن لا إله إلا الله سبحانك إني كنت من الظالمين', 'كاف', None): (87, 22, None),
    (25, 'أم هو ضلوا السبيل', 'تام', None): (17, 15, None),
    (25, 'إن كان ليضلنا عن آلهتنا لولا أن صبرنا عليها', 'كاف', None): (42, 8, None),
    (27, 'فناظرة بما يرجع المرسلون', 'تام', None): (35, 7, None),
    (28, 'من إله غير يأتيكم بليل تسكنون فيه', 'حسن', None): (72, 18, None),
    (29, 'أو ليس الله بأعلم بما في صدور العالمين', 'تام', 'غيره'): (10, 30, 'غيره'),
    (30, 'اوختلاف ألسنتكم وألوانكم', 'كاف', None): (22, 7, None),
    (31, 'ولئن سألتهم من خق السموات والأرض ليقولن الله', 'تام', None): (25, 7, None),
    (34, 'إلا دابة الأرض تأكل من سأته', 'كاف', None): (14, 12, None),
    (34, 'إلا لمن أذى له', 'تام', 'محمد بن عيسى'): (23, 7, 'محمد بن عيسى'),
    (35, 'يزيدفي الخلق ما يشاء', 'كاف', 'أبو حاتم'): (1, 17, 'أبو حاتم'),
    (35, 'هل من خالق غير الله يرزقكم من السماء والأرض لا إله إلا الله', 'كاف', None): (3, 18, None),
    (35, 'وتستخرجون حلبة تلبسونها', 'صالح', None): (12, 18, None),
    (36, 'فإذا هم جميع دلينا محضرون', 'تام', None): (53, 9, None),
    (37, 'قل هل أنتم مطلعون', 'كاف', None): (54, 3, None),
    (38, 'وأصحاب الأيكة', 'تام', None): (13, 4, None),
    (39, 'هل من ممسكات رحمته', 'تام', 'أبو حاتم'): (38, 29, 'أبو حاتم'),
    (39, 'وجيء بالنبييين والشهداء وقضى بينهم بالحق', 'صالح', None): (69, 11, None),
    (40, 'إذا الأغلال في أعناقهم والسلاسل', 'تام', 'أبو حاتم'): (71, 4, 'أبو حاتم'),
    (44, 'إن كنت موقنين', 'تام', None): (7, 7, None),
    (46, 'من لا يستحب له إلى يوم القيامة', 'تام', 'نافع'): (5, 13, 'نافع'),
    (46, 'ووصينا الإنسان بوالديه حسنا', 'كاف', None): (15, 3, None),
    (47, 'فقط أمعاءهم', 'كاف', None): (15, 43, None),
    (52, 'ماله من دافع', 'تام', 'أبو حاتم'): (8, 3, 'أبو حاتم'),
    (57, 'وهو معكم أينما كنتم', 'تام', 'أبو حاتم'): (4, 31, 'أبو حاتم'),
    (59, 'كيلا يكون دولة بين الأغنياء منكم', 'تام', None): (7, 22, None),
    (59, 'وذلك جزاء الظالمين', 'تام', None): (17, 9, None),
    (64, 'خلق السموات والأرض وصوركم فأحسن صوركم', 'كاف', None): (3, 6, None),
    (69, 'فما منكم م أحد عنه حاجزين', 'كاف', None): (47, 5, None),
    (76, 'إ الله كان عليما حكيما', 'تام', None): (30, 10, None),
    (80, 'ثم أشاء أنشره', 'تام', 'محمد بن عيسى'): (22, 3, 'محمد بن عيسى'),
}
# rulings for a non-Hafs reading: «من قرأ بقراءة ابن عباس {واذكر عبدنا} فوقفه
# الكافي {واذكر عبدنا إبراهيم}» — Hafs reads «عبادنا» (its stop: أولى الأيدي والأبصار)
DROP_NON_HAFS = {(38, 'واذكر عبدنا إبراهيم', 'كاف')}
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
    for (s, a0, q), (a, w) in MOVES.items():
        for (rid,) in con.execute("SELECT id FROM classical WHERE source='nahhas' AND surah=? AND ayah=? "
                                  "AND quote=? AND NOT (ayah=? AND wpos=?)", (s, a0, q, a, w)):
            ops.append(('move', rid, (a, w)))
    for (s, a0, q), fix in QUOTE_FIX.items():
        for (rid,) in con.execute("SELECT id FROM classical WHERE source='nahhas' AND surah=? AND ayah IN (?, ?) "
                                  "AND quote=?", (s, a0, MOVES.get((s, 39, q), (a0,))[0], q)):
            ops.append(('requote', rid, fix))
    for (s, q, g), g2 in REGRADE.items():
        for (rid,) in con.execute("SELECT id FROM classical WHERE source='nahhas' AND surah=? AND quote=? "
                                  "AND grade=?", (s, q, g)):
            ops.append(('regrade', rid, g2))
    for (s, q, g, by), (a, w, who) in SEAT_HELD.items():
        for (rid,) in con.execute("SELECT id FROM classical WHERE source='nahhas' AND surah=? AND quote=? "
                                  "AND grade=? AND COALESCE(reported_from,'')=COALESCE(?,'') AND ayah IS NULL",
                                  (s, q, g, by)):
            ops.append(('seat', rid, (a, w, who)))
    for s, q, g in DROP_NON_HAFS:
        for (rid,) in con.execute("SELECT id FROM classical WHERE source='nahhas' AND surah=? AND quote=? "
                                  "AND grade=?", (s, q, g)):
            ops.append(('delete', rid, None))
    for s, q in DROP_UNSEATED:
        for (rid,) in con.execute("SELECT id FROM classical WHERE source='nahhas' AND surah=? AND quote=? "
                                  "AND ayah IS NULL", (s, q)):
            ops.append(('delete', rid, None))
    for s, a, g, who, q, note in EXTRA:
        w = len(verse_word_texts(f'{s}:{a}')[1]) - 1
        if not con.execute("SELECT 1 FROM classical WHERE source='nahhas' AND surah=? AND ayah=? AND wpos=? "
                           "AND grade=? AND conf=1", (s, a, w, g)).fetchone():
            ops.append(('insert', (s, a, w, g, g, who, q, note), None))
    for s, note in surah_end_rulings():
        a = rx.surah_ayah_count(s)
        w = len(verse_word_texts(f'{s}:{a}')[1]) - 1
        if not con.execute("SELECT 1 FROM classical WHERE source='nahhas' AND surah=? AND ayah=? AND wpos=? "
                           "AND grade='تام' AND reported_from IS NULL", (s, a, w)).fetchone():
            word = verse_word_texts(f'{s}:{a}')[1][w]
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
        elif op == 'move':
            s_ = con.execute('SELECT surah FROM classical WHERE id=?', (x,)).fetchone()[0]
            a, w = who
            con.execute('UPDATE classical SET ayah=?, wpos=?, stop_word=? WHERE id=?',
                        (a, w, verse_word_texts(f'{s_}:{a}')[1][w], x))
        elif op == 'seat':
            s_ = con.execute('SELECT surah FROM classical WHERE id=?', (x,)).fetchone()[0]
            a, w, by = who
            con.execute('UPDATE classical SET ayah=?, wpos=?, stop_word=?, reported_from=?, conf=1 WHERE id=?',
                        (a, w, verse_word_texts(f'{s_}:{a}')[1][w], by, x))
        elif op == 'requote':
            con.execute('UPDATE classical SET quote=?, reported_from=? WHERE id=?', (who[0], who[1], x))
        elif op == 'regrade':
            con.execute('UPDATE classical SET grade=?, grade_raw=? WHERE id=?', (who, who, x))
        elif op == 'delete':
            con.execute('DELETE FROM classical WHERE id=?', (x,))
        else:
            s, a, w, g, raw, who_, q, note = x
            word = verse_word_texts(f'{s}:{a}')[1][w]
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
        st = apply(con)
        # a move can land a row on a twin that the same pass already merged
        # around: repeat until nothing changes (the second pass is a no-op)
        for _ in range(5):
            if not sum(st.values()):
                break
            print('applied:', st)
            st = apply(con)
        else:
            raise SystemExit(f'audit_nahhas does not converge: {st}')
    else:
        ops = plan(con)
        print(len(ops), 'changes:', {k: sum(1 for o in ops if o[0] == k) for k in ('attribute', 'move', 'regrade', 'delete', 'insert')})
    con.close()


if __name__ == '__main__':
    main()
