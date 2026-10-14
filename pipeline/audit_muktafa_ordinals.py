#!/usr/bin/env python3
"""المكتفى: rulings qualified by an ordinal — «{X} الأول كاف»، «الثاني تام»،
«في الموضعين»، «الأول والثاني تام».

The builder's grade regex expects the grade straight after the quote, so an
ordinal in between made الداني's ruling vanish («{مكر الله} الأول كاف»,
«{فإن مع العسر يسرا} الأول كاف … {إن مع العسر يسرا} الثاني تام») or, for a
«ومثله» item, collapsed «الثاني» onto the first occurrence.

المكتفى has no verse numbers, so each ruling is anchored on the nearest
preceding entry that has exactly one confident DB row; occurrences of the
quote are then counted from there (exact spelling only — a lone «كلا» must
not fold onto «ولا»), and a «الثاني» continues from its «الأول» sibling.
Rulings that do not resolve to enough occurrences are only reported.

Run:  python3 pipeline/audit_muktafa_ordinals.py [--apply]
"""
import argparse
import collections
import os
import re
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import audit_manar_mithl as mm  # noqa: E402  (hits_in_ayah, verse_words)
import build_classical_waqf as rx  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, 'data', 'classical_waqf.db')

_ORD_RE = re.compile(r'(?:\{([^{}]{1,80})\}|\(\(([^()]{1,60})\)\))\s*'
                     r'(الأول والثاني|في الموضعين|الأولى|الأول|الثانية|الثاني)([^{(]{0,40})')
_IDX = {'الأول': [0], 'الأولى': [0], 'الثاني': [1], 'الثانية': [1],
        'الأول والثاني': [0, 1], 'في الموضعين': [0, 1]}
_MITHL = re.compile(r'(ومثله|وكذلك|ومثلها|ونحوه)\s*[:،]?\s*$')
_SPAN = 5          # verses searched after the anchor

# Read by hand where the anchor rule cannot count (2026-09-26):
# «وحقت» الثانية (84:5) — no confident entry precedes it in the surah;
# «ويعفو عن كثير» الأول تام (42:30) — the book spells it without the alif
# (the second, 42:34, is تام only for «ويعلمُ» بالرفع, not Hafs).
# «{إلها آخر} كاف … {فسوف يعلمون} تام. وهو تهدد» (15:96) — the builder kept
# only the first «فسوف يعلمون» (15:3).
MANUAL = [(84, 5, 2, 'وحقت', 'تام'), (42, 30, 9, 'ويعفو عن كثير', 'تام'),
          (15, 96, 7, 'فسوف يعلمون', 'تام'), (54, 21, 3, 'ونذر', 'تام'), (54, 39, 2, 'ونذر', 'تام'),
          # «وقال نافع والقتبي والدينوري والأخفش {ولا تقولوا ثلاثة} تمام وهو
          # كاف» (4:171): الداني's own verdict is كاف; the relayed quote was lost
          (4, 171, 30, 'ولا تقولوا ثلاثة', 'كاف',
           'وقال نافع والقتبي والدينوري والأخفش {ولا تقولوا ثلاثة} تمام وهو كاف.'),
          # «تمام القصة / تمام الكلام» — الداني's own تام the parser did not read
          # (2026-10-07 recall check: every «{X} GRADE» in the book has a row)
          (2, 255, 49, 'العلي العظيم', 'تام', '{العلي العظيم} تمام الكلام.'),
          (4, 14, 12, 'مهين', 'تام', '{مهين} تمام القصة.'),
          (22, 24, 8, 'إلى صراط الحميد', 'تام', '{إلى صراط الحميد} تمام القصة.'),
          (37, 10, 6, 'ثاقب', 'تام', '{ثاقب} تمام القصة.'),
          (38, 25, 8, 'وحسن مآب', 'تام', '{وحسن مآب} تمام. ومثله {عن سبيل الله}'),
          (38, 40, 5, 'وحسن مآب', 'تام', '{وحسن مآب} تمام القصة.'),
          (43, 45, 12, 'يعبدون', 'تام', '{ولقومك} تام. {يعبدون} تمام القصة.'),
          (54, 5, 4, 'النذر', 'تام', '{بالغة} كاف على الوجهين. {النذر} تام.'),
          # «وقال الدينوري: … تمام … وليس كذلك، هما كافيان» / «وهما كافيان»
          (6, 163, 2, 'لا شريك له', 'كاف', 'وقال الدينوري: {لا شريك له} تمام. {وبذلك أمرت} تام. وليس كذلك، هما كافيان.'),
          (6, 163, 4, 'وبذلك أمرت', 'كاف', 'وقال الدينوري: {لا شريك له} تمام. {وبذلك أمرت} تام. وليس كذلك، هما كافيان.'),
          (57, 13, 19, 'له باب', 'كاف', 'وقال نافع والدينوري {له باب} تمام، وقالا {قالوا بلى} تمام، وهما كافيان.'),
          (57, 14, 5, 'قالوا بلى', 'كاف', 'وقال نافع والدينوري {له باب} تمام، وقالا {قالوا بلى} تمام، وهما كافيان.')]
# «ومثله {X} الثاني» items the builder put on the FIRST occurrence:
# (surah, ayah, wpos, quote) → (ayah, wpos).
MOVES = {
    (19, 96, 8, 'لدا'): (97, 9),                    # «لدا» ends 19:97; it sat on «ودا» (19:96)
    (34, 53, 4, 'من قبل'): (54, 9),
    (4, 92, 32, 'وتحرير رقبة مؤمنة'): (92, 46),   # «وتحرير» — the one after «يصدقوا»
    (26, 108, 2, 'وأطيعون'): (110, 2),
    (37, 175, 2, 'فسوف يبصرون'): (179, 2),
    (56, 90, 5, 'أصحاب اليمين'): (91, 4),
    # wrong-word check (seat_check.py): the quote fits a later occurrence in the verse
    (4, 78, 16, 'قل كل من عند الله'): (78, 28),
    (6, 158, 8, 'بعض آيات ربك'): (158, 13),
    (9, 37, 17, 'فيحلوا ما حرم الله'): (37, 21),
    (20, 69, 13, 'كيد ساحر'): (69, 10),
    (15, 25, 5, 'عليم حكيم'): (25, 6),             # Hafs «حكيم عليم»: the stop is the verse end
    # «{ومن فوقهم غواش} {يكسبون} تام. {في سم الخياط}» — 7:39 «تكسبون», not 7:96
    (7, 96, 17, 'يكسبون'): (39, 13),
    (56, 27, 1, 'ما أصحاب اليمين'): (27, 4),      # «وأصحاب اليمين ما أصحاب اليمين»: the second
    # repeated phrases the aligner put on another verse; the book's order
    # (seq) puts each among the verses given here (2026-09-27 order sweep)
    (2, 150, 30, 'تهتدون'): (135, 5),              # «كونوا هودا أو نصارى تهتدوا»
    (9, 54, 18, 'لا ينفقون'): (92, 22),            # «{مع الخوالف} كاف. {لا ينفقون} تام»
    (16, 89, 10, 'أمر بك'): (33, 9),               # «أو يأتي أمر ربك»
    (51, 59, 8, 'به يستعجلون'): (14, 6),           # «هذا الذي كنتم به تستعجلون»
    (6, 31, 21, 'وراء ظهورهم'): (94, 11),          # «{مثل ما أنزل الله} كاف. ومثله {وراء ظهورهم}»
    (7, 145, 19, 'الفاسقين'): (102, 8),            # «وإن وجدنا أكثرهم لفاسقين»
    (15, 8, 4, 'إلا بالحق'): (85, 7),              # «{لآية للمؤمنين} تام … ومثله {إلا بالحق}»
    (15, 25, 6, 'الخلاق العليم'): (86, 4),
    (16, 18, 9, 'لرؤوف رحيم'): (7, 13),            # «{بشق الأنفس} ومثله {لرؤوف رحيم}»
    (38, 45, 7, 'والأبصار'): (63, 5),              # «{ضعفا في النار} تام. ومثله {والأبصار}»
    (46, 14, 2, 'في أصحاب الجنة'): (16, 12),       # «{ووضعته كرها} كاف … ومثله {في أصحاب الجنة}»
    (55, 33, 5, 'وبين حميم آن'): (44, 4),          # «{فلا تنتصران} تام ومثله {وبين حميم آن}»
    # «{يوم عسر} تام ومثله {ونذر} حيث وقع في السورة إذا كان بعده {ولقد يسرنا
    # القرآن للذكر}»: 54:16، 54:21، 54:39 (the other two are in MANUAL)
    (54, 5, 4, 'ونذر'): (16, 3),
    # multi-word quotes seated on a neighbouring verse by their last word
    # alone; the full phrase ends only at the target (2026-09-28 full-quote
    # fit check, confirmed by book order and quranpedia.app's per-ayah text)
    (2, 229, 27, 'أن يقيما حدود الله'): (230, 23),
    (3, 172, 2, 'واتبعوا رضوان الله'): (174, 10),
    (4, 104, 19, 'بما أراك الله'): (105, 10),
    (5, 106, 50, 'لمن الظالمين'): (107, 25),
    (10, 54, 7, 'ما في السماوات والأرض'): (55, 6),
    (13, 38, 20, 'أم الكتاب'): (39, 7),
    (20, 74, 10, 'خالدين فيها'): (76, 7),
    (24, 27, 15, 'فيها متاع لكم'): (29, 10),
    (25, 31, 0, 'جملة واحدة كذلك'): (32, 9),
    (28, 52, 6, 'آمنا به'): (53, 5),
    (30, 8, 6, 'بآيات الله'): (10, 9),
    (31, 26, 6, 'كلمات الله'): (27, 16),
    (48, 18, 4, 'آية للمؤمنين'): (20, 14),
    (69, 2, 1, 'وما أدراك ما الحاقة'): (3, 3),
    (75, 34, 2, 'ثم أولى لك فأولى'): (35, 3),
    (82, 17, 4, 'ثم ما أدراك ما يوم الدين'): (18, 5),
    (101, 2, 1, 'وما أدراك ما القارعة'): (3, 3),
    (6, 57, 18, 'مولاهم الحق'): (62, 5),           # between 6:58 and «ألا له الحكم» (6:62)
    # found against quranpedia.app's per-ayah text (2026-09-28)
    (19, 41, 3, 'عن آلهتي يا إبراهيم'): (46, 5),   # «يا إبراهيم» of 19:46, not 19:41's «إبراهيم»
    (11, 98, 3, 'ويوم القيامة'): (99, 5),          # 11:98 is «يوم القيامة» without و
    (33, 18, 13, 'إلا قليلا'): (20, 22),           # after «أشحة على الخير» (33:19): «ما قاتلوا إلا قليلا»
    (26, 147, 2, 'وجنات وعيون'): (134, 1),        # «{وجنات وعيون} تام. {فأهلكناهم} كاف» (26:139); 147 is «في جنات»
    # book-order sweep (2026-10-07): the book's quote is a slip for the word between its neighbours
    (7, 38, 39, 'تعلمون'): (43, 35),               # «{رسل ربنا بالحق} كاف. {تعلمون} تام. {قالوا نعم}»: 7:43 «تعملون»
    (28, 32, 5, 'بيضاء'): (71, 16),                # «{بيضاء} تام. والآية أتم» between 28:68 and 28:72: «بضياء»
    (39, 45, 8, 'يؤمنون'): (52, 14),               # after «سيئات ما كسبوا» (39:48), before 39:60: «لقوم يؤمنون»
}
# conf=0 rows (the cursor aligner could not pin them confidently), each read
# against its own surah's section (2026-09-26): all are الداني's rulings.
# None = the seat is right; a tuple moves it first.
REPAIR = {
    27: None, 260: None, 391: None, 463: None, 651: None, 1303: None, 2397: None,
    2542: None, 2640: None, 2740: None, 2798: None, 2992: None, 3079: None,
    3225: None, 3267: None, 3303: None, 3765: None, 4044: None, 4105: None,
    4320: None, 4403: None,
    524: (20, 13),        # «أأسلمتم» is «ءَأَسۡلَمۡتُمۡۚ», not «أَسۡلَمۡتُ وَجۡهِيَ»
    2693: (37, 18),       # «والأبصار» ends 24:37, not 24:36
}
REPORTED = {2542: 'الدينوري'}
# rows on a word the book does not rule on: «{الر} حيث وقع و {المر} تام» (يونس's opening)
# was seated on «ضره مر» (10:12); المر is 13:1, which has its own row
VERSE_END_RAW = 'رأس الآية'
# 2437: 20:77 «لا تخف دركا» كاف — the jussive reading («ومن قرأ {لا تخف دركا} بالجزم»); Hafs «لا تخاف»
DROP_IDS = {1736, 2437,
            1979}     # 12:93 «بأهلكم أجمعين» كاف — «ورأس الآية أتم. وكذلك {بأهلكم أجمعين}» is تام (MANUAL)
# «{عليم حكيم} تام. ومثله {ما أنفقوا} {مؤمنون} أتم» is 60:11's «مثل ما أنفقوا»; this تام sat on
# 60:10's second «ما أنفقوا» beside its own كاف (المكتفى is never rebuilt, so ids are stable)
ID_MOVES = {3988: (60, 11, 14),
            1134: (6, 14, 7),
            # «ومثله {سوأة أخيه}» is 5:31's «يواري سوأة أخيه», not 5:30's «قتل أخيه» (unique-ending check)
            1013: (5, 31, 10),
            # cross-book check: the book's order puts these on the next verse —
            # «ومثله {ويقدر له} ومثله {ليقولن الله} ومثله {قل الحمد لله}» (29:63, not 29:61) and
            # «{وأصلح بالهم} تام. {الحق من ربهم} كاف» (47:3, not 47:2; ابن الأنباري marks it [3])
            2973: (29, 63, 14), 3652: (47, 3, 12)}   # «{فاطر السموات والأرض} كاف» is 6:14, not 6:12's «والأرض» (round 25)
# الشعراء's refrain: «{إن في ذلك لآية} كاف. {مؤمنين} تام. {العزيز الرحيم} أتم منه.
# وكذلك جميع ما في السورة من ذلك» (26:8–9) — the seven repeats got the general
# «ورؤوس الآي بعد كافية» instead. (ayah of «مؤمنين», wpos of «لآية»)
_REFRAIN_26 = '{إن في ذلك لآية} كاف. {مؤمنين} تام. {العزيز الرحيم} أتم منه. وكذلك جميع ما في السورة من ذلك'
for _a, _w in ((67, 3), (103, 3), (121, 3), (139, 5), (158, 5), (174, 3), (190, 3)):
    MANUAL += [(26, _a, _w, 'إن في ذلك لآية', 'كاف', _REFRAIN_26),
               (26, _a, _w + 4, 'مؤمنين', 'تام', _REFRAIN_26),
               (26, _a + 1, 4, 'العزيز الرحيم', 'تام', _REFRAIN_26)]
# other «حيث وقع / جميع ما في السورة» statements that reached only the occurrence
# they stand at (sweep after the الشعراء refrain, 2026-10-08)
MANUAL += [
    (2, 1, 0, 'الم', 'تام', 'الوقف على: {الم} حيث وقع تام إذا جعل اسما للسورة. والتقدير: اقرأ الم. '
                            'أو جعل على تأويل: أنا الله أعلم. وذلك الاختيار. قال أبو حاتم هو كاف.'),
    (10, 1, 0, 'الر', 'تام', '{الر} حيث وقع و {المر} تام على قول ابن عباس، لأن معنى ((الر)) عنده: أنا الله '
                             'أرى. وقيل: الوقف عليهما كاف.'),
]
_ILAH_27 = '{شجرها} كاف. ومثله {أإله مع الله} حيث وقع، وهو استفهام توبيخ'
MANUAL += [(27, _a, _w, 'أإله مع الله', 'كاف', _ILAH_27) for _a, _w in ((61, 16), (62, 12), (63, 15), (64, 12))]
# «ومثله {ونذر} حيث وقع في السورة إذا كان بعده {ولقد يسرنا …} وكذلك ما فيها ((من مدكر))»
_MUDDAKIR_54 = '{يوم عسر} تام ومثله {ونذر} حيث وقع في السورة إذا كان بعده {ولقد يسرنا القرآن للذكر فهل من مدكر} وكذلك ما فيها ((من مدكر))'
MANUAL += [(54, _a, len(mm.verse_words(54, _a)) - 1, 'فهل من مدكر', 'تام', _MUDDAKIR_54)
           for _a in (15, 17, 22, 32, 40, 51)]
# «{للمكذبين} تام، جميع ما في السورة. وكذلك ما قبل {ويل يومئذ للمكذبين} فيها»
_WAYL_77 = '{للمكذبين} تام، جميع ما في السورة. وكذلك ما قبل {ويل يومئذ للمكذبين} فيها.'
# (the verse before each is a general «ما قبل …» rule: audit_muktafa_blanket.MANUAL_VERSES)
MANUAL += [(77, _a, 2, 'ويل يومئذ للمكذبين', 'تام', _WAYL_77) for _a in (15, 19, 24, 28, 34, 37, 40, 45, 47, 49)]
_NAJM_53 = ('والوقف {وما ينطق عن الهوى} وهو كاف. ومثله {يوحى} ومثله {بالأفق الأعلى} ومثله {ما أوحى} '
            'ومثله {ما رأى} ومثله {من آيات ربه الكبرى} ومثله {تلك إذا قسمة ضيزى}')
# sixth and seventh passage checks (2026-10-11): rulings the parser missed — an editor's
# restoration in brackets (9:30), «[ومثله]» (74:31), «{كلا} أيضا» (74:53) and
# «جواب القسم {X} وهو تام» (89:14); round 7: «[ومثله]» in 7, «والتمام {X}», «وهو عندي»
# round 25: verse ends the book rules by name, over a blanket «رؤوس الآي» row (an explicit
# ruling wins), and the Hafs side of 3:79 («ومن قرأ ذلك بالنصب لم يقف على ((تدرسون))»)
MANUAL += [(6, 3, 11, 'تَكۡسِبُونَ', 'تام', 'والتمام عندي آخر الآية، لأن المعنى على التقديم والتأخير'),
           (2, 141, 14, 'يَعۡمَلُونَ', 'تام', '{عما كانوا يعملون} تام، وكذلك [الذي] عند رأس الجزء.'),
           (12, 92, 10, 'ٱلرَّٰحِمِينَ', 'تام', 'ورأس الآية أتم. وكذلك {بأهلكم أجمعين}'),
           (12, 93, 11, 'بأهلكم أجمعين', 'تام', 'ورأس الآية أتم. وكذلك {بأهلكم أجمعين}'),
           (3, 79, 27, 'تَدۡرُسُونَ', 'لا', 'ومن قرأ ذلك بالنصب لم يقف على ((تدرسون))'),
           # whole-book check for named verse ends (2026-10-14): «وآخر الآية أكفى» with no row,
           # and «ورأس الآية أكفى / أتم منه» whose general-rule row had the other grade
           (24, 9, 8, 'من الصادقين', 'تام', '{من الكاذبين} تام. مثله {من الصادقين}'),   # round 26
           (2, 181, 13, 'عَلِيمٞ', 'كاف', '{وعلى الذين يبدلونه} كاف، وآخر الآية أكفى'),
           (4, 1, 27, 'رَقِيبٗا', 'كاف', '{تساءلون به والأرحام} كاف، وآخر الآية أكفى منه'),
           (3, 75, 35, 'يَعۡلَمُونَ', 'كاف', 'ومثله {في الأميين سبيل} ورأس الآية أكفى منه'),
           (10, 92, 13, 'لَغَٰفِلُونَ', 'تام', '{لمن خلفك آية} [تام] ورأس الآية أتم منه')]
MANUAL += [(7, 74, 16, 'وتنحتون الجبال بيوتا', 'كاف', '{عذاب أليم} . [ومثله] {وتنحتون الجبال بيوتا}'),
           (7, 176, 19, 'أو تتركه يلهث', 'كاف', '{واتبع هواه} كاف. [ومثله] {أو تتركه يلهث}'),
           # a bare quote between two «ومثله» items: «ومثله {جاثمين} . {كأن لم يغنوا فيها} . ومثله {الخاسرين}»
           (7, 92, 6, 'كأن لم يغنوا فيها', 'تام', '{خير الفاتحين} تام. ومثله {جاثمين} . {كأن لم يغنوا فيها} .'),
           # «وقال نافع والدينوري: {لا يؤمنون به} هنا وفي الشعراء تام. وهو عندي كاف»
           (15, 13, 2, 'لا يؤمنون به', 'كاف', 'وقال نافع والدينوري: {لا يؤمنون به} هنا وفي الشعراء تام. وهو عندي كاف'),
           (26, 201, 2, 'لا يؤمنون به', 'كاف', 'وقال نافع والدينوري: {لا يؤمنون به} هنا وفي الشعراء تام. وهو عندي كاف'),
           # «وقال ابن الأنباري: هو حسن. وكذلك هو عندي» (60:1, beside نافع's تام)
           (60, 1, 19, 'والرسول وإياكم', 'حسن', 'وقال ابن الأنباري: هو حسن. وكذلك هو عندي، وليس بتام ولا كاف'),
           (60, 4, 44, 'وما أملك لك من الله من شيء', 'تام', 'والتمام {وما أملك لك من الله من شيء}'),
           (9, 30, 9, 'وقالت النصارى المسيح ابن الله', 'كاف', '[وقالت النصارى المسيح ابن الله. كاف]'),
           (74, 31, 45, 'ويهدي من يشاء', 'كاف', '{تسعة عشر} كاف. ومثله {بهذا مثلا} [ومثله] {ويهدي من يشاء}'),
           (74, 53, 0, 'كلا', 'تام', '{منشرة} تام. {كلا} أيضا تام. أي: لا يؤتاها.'),
           (89, 14, 2, 'إن ربك لبالمرصاد', 'تام', 'جواب القسم {إن ربك لبالمرصاد} وهو تام.'),
           # round 8: «جواب القسم: {إن إلهكم لواحد} وهو وقف كاف. {ورب المشارق} التمام.»
           (37, 4, 2, 'إن إلهكم لواحد', 'كاف', 'جواب القسم: {إن إلهكم لواحد} وهو وقف كاف.'),
           (37, 5, 6, 'ورب المشارق', 'تام', '{ورب المشارق} التمام.'),
           # round 9: «{هو أزكى لكم} شبيه بالتام ورأس الآية أتم» (24:28), «{ما يشاء} أتم منه وآخر
           # الآية أتم منهما» (24:45)
           (24, 28, 17, 'هو أزكى لكم', 'كاف', '{هو أزكى لكم} شبيه بالتام ورأس الآية أتم.'),
           (24, 28, 21, 'عَلِيمٞ', 'تام', '{هو أزكى لكم} شبيه بالتام ورأس الآية أتم.'),
           (24, 45, 30, 'قَدِيرٞ', 'تام', '{ما يشاء} أتم منه وآخر الآية أتم منهما.'),
           # round 10: «والآية أتم» / «ورأس الآية أتم» on a verse end a blanket كاف had filled
           (3, 122, 11, 'ٱلۡمُؤۡمِنُونَ', 'تام', '{والله وليهما} تام، والآية أتم.'),
           (25, 16, 9, 'مَّسۡـُٔولٗا', 'تام', '{ما يشاءون خالدين} تام والآية أتم.'),
           (25, 20, 19, 'بَصِيرٗا', 'تام', '{أتصبرون} تام، والآية أتم.'),
           (28, 35, 14, 'ٱلۡغَٰلِبُونَ', 'تام', 'ومثله {إليكما بآياتنا} ورأس الآية أتم.'),
           (60, 3, 12, 'بَصِيرٞ', 'تام', 'ومثله {يفصل بينكم} والآية أتم.'),
           # «جواب {إذا} {علمت نفس ما أحضرت} ولا تمام دونه، وهو تام» / «جواب القسم {…} وهو تمام»
           (81, 14, 3, 'علمت نفس ما أحضرت', 'تام', 'جواب {إذا} {علمت نفس ما أحضرت} ولا تمام دونه، وهو تام.'),
           (77, 7, 2, 'إنما توعدون لواقع', 'تام', 'جواب القسم {إنما توعدون لواقع} وهو تمام.'),
           # round 11
           (25, 21, 11, 'أو نرى ربنا', 'تام', 'وهو عندي تام لانقضاء كلامهم.'),
           (12, 52, 11, 'ٱلۡخَآئِنِينَ', 'تام', '{ذلك ليعلم أني لم أخنه بالغيب وأن الله لا يهدي كيد الخائنين} تمام الكلام.'),
           (27, 43, 11, 'كَٰفِرِينَ', 'تام', '{من دون الله} كاف. وقيل: تام، ورأس الآية أتم.'),
           # round 12: «والوقف {وما ينطق عن الهوى} وهو كاف. ومثله {يوحى} ومثله …» (53)
           (53, 3, 3, 'وما ينطق عن الهوى', 'كاف', _NAJM_53),
           (53, 4, 4, 'يوحى', 'كاف', _NAJM_53),
           (53, 7, 2, 'بالأفق الأعلى', 'كاف', _NAJM_53),
           (53, 10, 4, 'ما أوحى', 'كاف', _NAJM_53),
           (53, 11, 4, 'ما رأى', 'كاف', _NAJM_53),
           (53, 18, 5, 'من آيات ربه الكبرى', 'كاف', _NAJM_53),
           (53, 22, 3, 'تلك إذا قسمة ضيزى', 'كاف', _NAJM_53),
           (50, 42, 3, 'الصيحة بالحق', 'كاف', 'وقال نافع {الصيحة بالحق} تام، وهو كاف.'),
           (83, 28, 3, 'المقربون', 'تام', '{تكذبون} تام. ومثله {يشهده المقربون} الأول، و {المقربون} الثاني'),
           # «جواب القسم {X} فلا وقف دونه»: the oath verses before the answer (no quote of their own)
           (53, 1, 2, 'هَوَىٰ', 'لا', 'جواب القسم {ما ضل صاحبكم وما غوى} فلا وقف دونه.'),
           # round 13
           (22, 27, 13, 'من كل فج عميق', 'صالح', '{من كل فج عميق} أي بعيد صالح غير تام ولا كاف'),
           (3, 34, 6, 'سميع عليم', 'تام', 'وقيل: تام، [ {سميع عليم} ] . تام.'),
           (33, 33, 24, 'تطهيرا', 'تام', 'يكون الوقف قبله كافيا، والتمام ((تطهيرا))'),
           (22, 41, 16, 'ٱلۡأُمُورِ', 'تام', '{ونهوا عن المنكر} تام. ورأس الآية أتم.'),
           (11, 109, 19, 'مَنقُوصٖ', 'تام', '{آباؤهم من قبل} والآية تمام.'),
           # round 14
           (7, 30, 5, 'عليهم الضلالة', 'كاف', '((فريقا هدى وفريقا حق عليهم الضلالة)) [عليهم الضلالة] كاف على'),
           (3, 156, 35, 'بَصِيرٞ', 'تام', '{في قلوبهم} كاف. ومثله {والله يحيي ويميت} والتمام آخر الآية'),
           (4, 157, 8, 'رسول الله', 'كاف', 'والوقف عندي على ((رسول الله)) وهو كاف.'),
           # round 15
           (4, 8, 12, 'مَّعۡرُوفٗا', 'كاف', '{فارزقوهم منه} كاف. وآخر الآية أكفى.'),
           (4, 24, 41, 'عليما حكيما', 'تام', '{عليما حكيما} تمام القصة.'),
           (4, 30, 12, 'يسيرا', 'تام', '[يسيرا] تام.'),
           (5, 25, 7, 'وأخي', 'كاف', 'والوجه أن يكون الوقف على ((وأخي)) وهو كاف.'),
           (7, 190, 7, 'جعلا له شركاء فيما آتاهما', 'تام', 'كاف عند أصحاب الوقف، وهو عندي تام'),
           # coverage sweep (2026-10-12): «جواب القسم {X} وهو GRADE» and the «ومثله» items after it —
           # «وهو» before the grade left these heads (and their chains) without rows
           (82, 5, 4, 'ما قدمت وأخرت', 'تام', 'جواب {إذا} {ما قدمت وأخرت} وهو تام. ومثله {ما شاء ربك} ومثله {ما تفعلون} ومثله. {بغائبين} .'),
           (82, 8, 5, 'ما شاء ربك', 'تام', 'جواب {إذا} {ما قدمت وأخرت} وهو تام. ومثله {ما شاء ربك} ومثله {ما تفعلون} ومثله. {بغائبين} .'),          # the book's slip for «ركبك»
           (82, 12, 2, 'ما تفعلون', 'تام', 'جواب {إذا} {ما قدمت وأخرت} وهو تام. ومثله {ما شاء ربك} ومثله {ما تفعلون} ومثله. {بغائبين} .'),
           (82, 16, 3, 'بغائبين', 'تام', 'جواب {إذا} {ما قدمت وأخرت} وهو تام. ومثله {ما شاء ربك} ومثله {ما تفعلون} ومثله. {بغائبين} .'),
           (86, 4, 5, 'إن كل نفس لما عليها حافظ', 'تام', 'جواب {والسماء والطارق} {إن كل نفس لما عليها حافظ} وهو تام، وقيل: كاف.'),
           (90, 4, 4, 'لقد خلقنا الإنسان في كبد', 'كاف', '{لا أقسم بهذا البلد} قسم وجوابه {لقد خلقنا الإنسان في كبد} وهو كاف، وقيل: تام.'),
           (92, 4, 2, 'إن سعيكم لشتى', 'تام', 'جواب القسم {إن سعيكم لشتى} وهو تام.'),
           (93, 3, 4, 'ما ودعك ربك وما قلى', 'تام', 'جواب القسم {ما ودعك ربك وما قلى} وهو تام. ومثله {من الأولى}'),
           (93, 4, 4, 'من الأولى', 'تام', 'جواب القسم {ما ودعك ربك وما قلى} وهو تام. ومثله {من الأولى}'),
           (95, 4, 5, 'لقد خلقنا الإنسان في أحسن تقويم', 'كاف', 'جواب القسم {لقد خلقنا الإنسان في أحسن تقويم} وهو كاف. ومثله {وعملوا الصالحات} .'),
           (95, 6, 4, 'وعملوا الصالحات', 'كاف', 'جواب القسم {لقد خلقنا الإنسان في أحسن تقويم} وهو كاف. ومثله {وعملوا الصالحات} .'),
           # «… وهو تام على القراءتين / في كلا الوجهين / كاف على القراءتين»
           (14, 2, 8, 'ما في الأرض', 'تام', 'ومن قرأ بالخفض على البدل لم يقف على ((ما في الأرض)) . وهو تام على القراءتين.'),
           (28, 68, 8, 'الخيرة', 'تام', 'فالوقف على {الخيرة} ، وهو تام في كلا الوجهين.'),
           (29, 66, 3, 'وليتمتعوا', 'كاف', 'ووقف على ((وليتمتعوا)) وهو كاف على القراءتين.')]
MANUAL += [(51, _a, 1, mm.verse_words(51, _a)[1], 'لا', 'جواب القسم {إنما توعدون لصادق} فلا وقف دونه.')
           for _a in (1, 2, 3, 4)]
MANUAL += [(52, _a, len(mm.verse_words(52, _a)) - 1, mm.verse_words(52, _a)[-1], 'لا',
            'جواب القسم {إن عذاب ربك لواقع} فلا وقف دونه.') for _a in (1, 2, 3, 4, 5, 6)]
# relayed views with no row at all (RELAYED_BY only relabels): inserted credited
# (surah, ayah, wpos, quote, grade, reported_from, note)
RELAYED_ADD = [
    # round 26: «قال أبو حاتم هو كاف» (2:1 «الم»), «وقال نافع: لا ريب فيه، تام»
    (2, 1, 0, 'الم', 'كاف', 'أبو حاتم', 'قال أبو حاتم هو كاف. وقال غيره: ليس بتام ولا كاف'),
    (2, 2, 4, 'لا ريب فيه', 'تام', 'نافع', 'وقال نافع: لا ريب فيه، تام'),
    # quranpedia cross-check (2026-10-14): «وقال القتبي: {كذلك} التمام والكاف في موضع نصب …»
    (10, 103, 5, 'كذلك', 'تام', 'القتبي', 'وقال القتبي: {كذلك} التمام'),
    # round 25: «وقال أبو جعفر النحاس، وهو قول يعقوب: ((كمثل آدم)) تمام الكلام … وقال غيرهما: ليس ذلك بتام»
    (3, 59, 6, 'كمثل آدم', 'تام', 'أبو جعفر النحاس', 'وقال أبو جعفر النحاس، وهو قول يعقوب: ((كمثل آدم)) تمام الكلام'),
    (38, 25, 1, 'فغفرنا له', 'تام', 'يعقوب والدينوري',
     'وقال يعقوب والدينوري: التمام ((فغفرنا له)) ثم يبتدأ ((ذلك)) أي الأمر ذلك'),
    (68, 6, 1, 'بأيكم المفتون', 'تام', 'غيره', 'وقال غيره {بأيكم المفتون} التمام. ومثله {بالمهتدين} ومثله {فيدهنون}'),
    (18, 22, 11, 'ويقولون سبعة', 'تام', 'أبو إسحاق الزجاج', 'وقال أبو إسحاق الزجاج ((ويقولون سبعة)) تمام'),
    # «{وما كان منتصرا. هنالك} تمام … ويكون العامل [فيه] منتصرا»: the stop is «هنالك»
    (18, 44, 0, 'وما كان منتصرا. هنالك', 'تام', 'الدينوري', 'وقال الدينوري: {وما كان منتصرا. هنالك} تمام'),
    (48, 29, 30, 'ومثلهم في الإنجيل', 'تام', 'مجاهد', 'والتمام على قول مجاهد: {ومثلهم في الإنجيل}'),
    (59, 15, 4, 'كمثل الذين من قبلهم قريبا', 'تام', 'الأخفش', 'وقال الأخفش {كمثل الذين من قبلهم قريبا} تمام الكلام'),
    (7, 172, 15, 'قالوا بلى', 'تام', 'نافع ومحمد بن عيسى والقتبي والدينوري',
     'وقال نافع ومحمد بن عيسى والقتبي والدينوري: التمام ((قالوا بلى))'),
    (72, 5, 9, 'على الله كذبا', 'تام', 'بعض العلماء', 'قال بعض العلماء: … والوقف على رأس كل آية كاف. ويتم على قوله {على الله كذبا} و {لجهنم حطبا} … وكذلك قوله {أن لن يبعث الله أحدا}'),
    (72, 7, 8, 'أن لن يبعث الله أحدا', 'تام', 'بعض العلماء', 'قال بعض العلماء: … والوقف على رأس كل آية كاف. ويتم على قوله {على الله كذبا} و {لجهنم حطبا} … وكذلك قوله {أن لن يبعث الله أحدا}'),
    (72, 15, 4, 'لجهنم حطبا', 'تام', 'بعض العلماء', 'قال بعض العلماء: … والوقف على رأس كل آية كاف. ويتم على قوله {على الله كذبا} و {لجهنم حطبا} … وكذلك قوله {أن لن يبعث الله أحدا}'),
    (81, 21, 1, 'مطاع ثم', 'تام', 'نافع', 'وقال نافع: {مطاع ثم} تم. وليس بتام ولا كاف لأن ((أمين)) نعت ل ((مطاع))'),
]
# the Hafs side of a reading split whose other side is the stored row: inserted
# beside it (MANUAL would regrade a lone row with the same quote instead)
HAFS_SIDE = [
    # round 10: «ولا يوقف على {العالمين} لأن {لمن يشاء} بدل منه» (81:27); «لم يوقف على قوله
    # ((تمشي)) ولا يبتدأ ب ((على استحياء))» (28:25)
    (81, 27, 4, 'العالمين', 'لا', 'ولا يوقف على {العالمين} لأن {لمن يشاء} بدل منه'),
    (28, 25, 2, 'تمشي', 'لا', 'لم يوقف على قوله ((تمشي)) ولا يبتدأ ب ((على استحياء))'),
    # «{بالحق} كاف لمن قرأ {والذين تدعون} بالتاء. ومن قرأ بالياء فهو راجع إلى ما قبله … فلا يقطع»
    (40, 20, 2, 'بالحق', 'لا', 'ومن قرأ بالياء [«يدعون»، قراءة حفص] فهو راجع إلى ما قبله من الخبر فلا يقطع'),
    # a stop the book rules out where a blanket «والفواصل بين ذلك كافية» put كاف:
    # «قوله {إلا المصلين} استثناء من الإنسان … فلا يكفي الوقف قبله» (70:21 «منوعا»)
    (70, 21, 3, 'إلا المصلين', 'لا', 'قوله {إلا المصلين} استثناء من الإنسان وهو بمعنى الناس، فلا يكفي '
                                     'الوقف قبله'),
    # «{فسواها} … ومن قرأ ((ولا يخاف)) بالواو لم يبتدئ بذلك لأن الكلام متعلق بما قبله»
    (91, 14, 6, 'فسواها', 'لا', 'ومن قرأ ((ولا يخاف)) بالواو [قراءة حفص] لم يبتدئ بذلك لأن الكلام متعلق بما '
                                  'قبله، وذلك أن الواو في موضع الحال'),
]
# «{سيقولون لله} كاف في الثلاثة» (23:85، 87، 89); «{من هلك عن بينة} تام [ابن عبد الرزاق].
# وليس كذلك لأن: {ويحيى من حي عن بينة} نسق على ذلك وهو التمام» (8:42)
MANUAL += [(23, 87, 1, 'سيقولون لله', 'كاف', '{سيقولون لله} كاف في الثلاثة'),
           (23, 89, 1, 'سيقولون لله', 'كاف', '{سيقولون لله} كاف في الثلاثة'),
           (8, 42, 30, 'ويحيى من حي عن بينة', 'تام',
            '{من هلك عن بينة} تام. وليس كذلك لأن: {ويحيى من حي عن بينة} نسق على ذلك وهو التمام')]
# «{A} GRADE. مثله {B}» (no «و») and «{B} مثل {A}» — chain items the parser skipped
MANUAL += [(6, 25, 12, 'وفي آذانهم وقرا', 'كاف', '{أو كذب بآياته} كاف. مثله {وفي آذانهم وقرا}'),
           (45, 10, 15, 'من دون الله أولياء', 'كاف', '{كأن لم يسمعها} كاف. مثله {من دون الله أولياء}'),
           (98, 4, 10, 'البينة', 'تام', '{كتب قيمة} تام. مثله {البينة}'),
           (111, 2, 5, 'وما كسب', 'كاف', '{وما كسب} مثل {وتب}'),
           # عاصم «حمالةَ» (Hafs): «فعلى هذا يكفي الوقف على قوله {وامرأته}»
           (111, 4, 0, 'وامرأته', 'كاف', 'وقرأ عاصم {حمالة الحطب} بالنصب … أن يجعل قوله ((وامرأته)) معطوف على '
                                          'الضمير الذي في ((سيصلى)) … فعلى هذا يكفي الوقف على قوله {وامرأته}')]
# a ruling the book relays and then corrects: (surah, ayah, wpos, quote, grade) → scholar
RELAYED_BY = {(6, 163, 4, 'وبذلك أمرت', 'تام'): 'الدينوري',   # «… وليس كذلك، هما كافيان»
              # round 26: «وقال إبراهيم بن عبد الرزاق: {مائة عام} تام و {آية للناس} تام»
              (2, 259, 47, 'آية للناس', 'تام'): 'إبراهيم بن عبد الرزاق',
              # «قال نصير بن يوسف ومحمد بن عيسى: الوقف على قوله: {أولياء} [كاف]»
              (60, 1, 7, 'أولياء', 'كاف'): 'نصير بن يوسف ومحمد بن عيسى',
              # «وقال المازني: {ويبصرون} تام … وقال غيره {بأيكم المفتون} التمام. ومثله {بالمهتدين}
              # ومثله {فيدهنون}» — the chain continues غيره's view
              # «{أو نرى ربنا} كاف عند أبي حاتم وابن الأنباري وابن عبد الرزاق وهو عندي تام»
              (25, 21, 11, 'أو نرى ربنا', 'كاف'): 'أبو حاتم وابن الأنباري وابن عبد الرزاق',
              # «{متقابلين. كذلك} تام على قول الحسن لأن المعنى عنده: كذلك حكم الله …»
              (44, 53, 4, 'متقابلين. كذلك', 'تام'): 'الحسن',
              # «وقال أحمد بن جعفر الدينوري وأحمد بن محمد النحاس: ((مثلا ما)) وقف حسن … وليس كما قالوا»
              (2, 26, 7, 'مثلا ما', 'حسن'): 'أحمد بن جعفر الدينوري وأحمد بن محمد النحاس',
              # «وقال ابن الأنباري: الوقف ((لتركبوها)) وتبتدئ: ((وزينة)) … وقال: ((وزينة)) تام»
              (16, 8, 4, 'وزينة', 'تام'): 'ابن الأنباري',
              # «قال نافع: {ممن خلق} تام. قال: {وجعلكم ملوكا} تام»; «كاف عند أصحاب الوقف، وهو عندي تام»
              (5, 20, 14, 'وجعلكم ملوكا', 'تام'): 'نافع',
              (7, 190, 7, 'جعلا له شركاء فيما آتاهما', 'كاف'): 'أصحاب الوقف',
              (68, 5, 1, 'ويبصرون', 'تام'): 'المازني',
              # «وقال بعض أهل التأويل: وهو قول عيسى بن عمر، ويروى عن الحسن: {واتخذ سبيله في البحر عجبا} تام»
              (18, 63, 19, 'واتخذ سبيله في البحر عجبا', 'تام'): 'بعض أهل التأويل',
              (68, 7, 10, 'بالمهتدين', 'تام'): 'غيره',
              (68, 9, 3, 'فيدهنون', 'تام'): 'غيره',
              # «{أجر العاملين} تام عند ابن الأنباري. وليس كذلك من حيث لم يأت ل {الذين صبروا} خبر بعد»
              (29, 58, 16, 'أجر العاملين', 'تام'): 'ابن الأنباري',
              # «{ولا أماني أهل الكتاب} كاف عند أصحاب التمام … وهو عندي تام» (his تام is its own row)
              (4, 123, 5, 'ولا أماني أهل الكتاب', 'كاف'): 'أصحاب التمام',
              # «وقال بعض المفسرين، وهو أحمد بن موسى، {يسبحون الليل} تام … وليس يصح ما قالوه»
              (21, 20, 1, 'يسبحون الليل', 'تام'): 'أحمد بن موسى',
              # «{قل إن كان للرحمن ولد} تام إذا جعلت ((إن)) بمعنى ((ما)) … وهو قول الحسن وقتادة»
              (43, 81, 4, 'قل إن كان للرحمن ولد', 'تام'): 'الحسن وقتادة',
              # «وقال ابن الأنباري: ومثله {ومن دونهما جنتان}»
              (55, 62, 2, 'ومن دونهما جنتان', 'تام'): 'ابن الأنباري'}
# «{…} كاف عند أصحاب التمام … وهو عندي تام» (4:123): الداني's own verdict is تام
REGRADE = {877: 'تام',
           2011: 'تام',
           429: 'تام'}    # 2:262 «والتمام آخر الآية وكذلك {يحزنون}» (round 26)   # 13:11 «ومثله {فلا مرد له} وهو أتم منه» (quranpedia cross-check, 2026-10-14)     # «وقال الدينوري: ((ذلك هو الضلال البعيد يدعو)) تام»


def occurrences(surah, after, quote):
    """Exact-spelling end seats of quote after (ayah, wpos), reading order."""
    a0, w0 = after
    out = []
    for a in range(a0, min(a0 + _SPAN, rx.surah_ayah_count(surah)) + 1):
        out += [(a, h) for h in mm.hits_in_ayah(surah, a, quote, True) if a > a0 or h > w0]
    return out


def resolve(con):
    body = rx.normalize_muktafa_headings(rx.load_book(rx.SOURCES['muktafa']))
    found, unresolved = [], []
    last = 0
    for sec in re.split(r'\n### \| ', body):
        title, _, text = sec.partition('\n')
        if 'سورة' not in title and 'أم القرآن' not in title:
            continue
        surah = rx.surah_number(title, last)
        if surah is None:
            continue
        last = surah
        entries = rx.parse_muktafa_entries(text)
        sibling = {}
        for m in _ORD_RE.finditer(text):
            quote = rx.clean_note(m.group(1) or m.group(2), limit=200)
            ordinal = m.group(3)
            tail = mm.strip(m.group(4)).lstrip(' ،.[')
            gm = rx.GRADE_RE.match(tail)
            grade = dict(rx.GRADES)[gm.group(1)] if gm else None
            prev = [e for e in entries if e['pos'] < m.start()]
            if grade is None and prev and _MITHL.search(mm.strip(text[max(0, m.start() - 14):m.start()])):
                grade = prev[-1]['grade']
            if grade is None:
                continue
            key = rx.norm(' '.join(rx.quote_words(quote)[-2:]))
            if key in sibling and _IDX[ordinal] == [1]:
                seats = occurrences(surah, sibling[key], quote)[:1]
            else:
                anchor = None
                for e in reversed(prev):
                    rows = con.execute("SELECT ayah, wpos FROM classical WHERE source='muktafa' "
                                       "AND conf=1 AND grade_raw<>'رؤوس الآي' AND surah=? AND quote=?", (surah, e['quote'])).fetchall()
                    if len(rows) == 1:
                        anchor = rows[0]
                        break
                cands = occurrences(surah, anchor, quote) if anchor else []
                idx = _IDX[ordinal]
                seats = [cands[i] for i in idx] if len(cands) > max(idx) else []
            rec = {'surah': surah, 'quote': quote, 'ordinal': ordinal, 'grade': grade,
                   'note': rx.clean_note(text[m.end(3):m.end(3) + 300])}
            if not seats:
                unresolved.append(rec)
                continue
            sibling[key] = seats[-1]
            for a, w in seats:
                found.append(dict(rec, ayah=a, wpos=w))
    return found, unresolved


# «وقال نافع {بل أحياء} تام» — no colon, so the builder's reported_scholar()
# (which needs «وقال فلان:») missed it and the row reads as الداني's own.
_RELAYED = re.compile(r'(?:^|[\s.،])و?قال(?:ت)?\s+([^{}:.،()]{2,45}?)\s*:?\s*'
                      r'(?:\{([^{}]{1,80})\}|\(\(([^()]{1,60})\)\))\s*(تام|كاف|حسن|أتم|أكفى|قبيح)')
RELAYED_SEAT = {(4, 'غفورا رحيما'): 23}     # the passage is on 4:23, not 4:152


def relayed_rows(con):
    """[(row id, scholar)] for المكتفى rows that are someone else's ruling."""
    body = rx.normalize_muktafa_headings(rx.load_book(rx.SOURCES['muktafa']))
    out, last = [], 0
    for sec in re.split(r'\n### \| ', body):
        title, _, text = sec.partition('\n')
        if 'سورة' not in title and 'أم القرآن' not in title:
            continue
        surah = rx.surah_number(title, last)
        if not surah:
            continue
        last = surah
        for m in _RELAYED.finditer(mm.strip(text)):
            name = re.sub(r'\s+', ' ', m.group(1)).strip()
            if name in ('أبو عمرو', 'الداني', 'أبو عمرو الداني'):      # الداني himself
                continue
            quote = (m.group(2) or m.group(3)).strip()
            rows = con.execute("SELECT id, ayah FROM classical WHERE source='muktafa' AND surah=? "
                               "AND quote=? AND grade_raw<>'رؤوس الآي'", (surah, quote)).fetchall()
            want = RELAYED_SEAT.get((surah, quote))
            rows = [r for r in rows if want is None or r[1] == want]
            if len(rows) == 1:
                out.append((rows[0][0], name))
    return out


def apply(con, found):
    cur = con.cursor()
    stats = collections.Counter()
    for (s, a0, w0, q), (a, w) in MOVES.items():
        stats['moved'] += cur.execute(
            "UPDATE classical SET ayah=?, wpos=?, stop_word=? WHERE source='muktafa' AND surah=? "
            "AND ayah=? AND wpos=? AND quote=? AND grade_raw<>'رؤوس الآي'",
            (a, w, mm.verse_words(s, a)[w], s, a0, w0, q)).rowcount
    for rid, (s, a, w) in ID_MOVES.items():
        stats['moved'] += cur.execute("UPDATE classical SET ayah=?, wpos=?, stop_word=? WHERE id=? AND "
                                      "source='muktafa' AND surah=? AND (ayah<>? OR wpos<>?)",
                                      (a, w, mm.verse_words(s, a)[w], rid, s, a, w)).rowcount
    stats['dropped'] += cur.execute(f"DELETE FROM classical WHERE source='muktafa' AND id IN "
                                    f"({','.join(map(str, DROP_IDS))})").rowcount
    for rid, seat in REPAIR.items():
        row = cur.execute("SELECT surah, ayah, wpos FROM classical WHERE id=? AND conf=0", (rid,)).fetchone()
        if not row:
            continue
        s, a, w = row
        if seat:
            a, w = seat
        cur.execute("UPDATE classical SET ayah=?, wpos=?, stop_word=?, conf=1, reported_from=? WHERE id=?",
                    (a, w, mm.verse_words(s, a)[w], REPORTED.get(rid), rid))
        stats['repaired'] += 1
    for rid, name in relayed_rows(con):
        stats['relayed_labelled'] += cur.execute(
            "UPDATE classical SET reported_from=? WHERE id=? AND COALESCE(reported_from,'')<>?",
            (name, rid, name)).rowcount
    for (s, a, w, q, g), name in RELAYED_BY.items():
        stats['relayed_labelled'] += cur.execute(
            "UPDATE classical SET reported_from=? WHERE source='muktafa' AND surah=? AND ayah=? AND wpos=? "
            "AND quote=? AND grade=? AND COALESCE(reported_from,'')<>?", (name, s, a, w, q, g, name)).rowcount
    for rid, g in REGRADE.items():
        stats['regraded_own'] += cur.execute(
            "UPDATE classical SET grade=?, grade_raw=? WHERE id=? AND grade<>?", (g, g, rid, g)).rowcount
    for s, a, w, q, g, note in HAFS_SIDE:
        if not cur.execute("SELECT 1 FROM classical WHERE source='muktafa' AND surah=? AND ayah=? AND wpos=? "
                           "AND grade=?", (s, a, w, g)).fetchone():
            cur.execute("INSERT INTO classical (source, surah, ayah, wpos, stop_word, quote, grade, grade_raw, "
                        "note, seq, conf, reported_from) VALUES ('muktafa',?,?,?,?,?,?,?,?,?,1,NULL)",
                        (s, a, w, mm.verse_words(s, a)[w], q, g, 'ليس بوقف', note,
                         # the seq of the row it sits beside, else of the nearest earlier row
                         (cur.execute("SELECT seq FROM classical WHERE source='muktafa' AND surah=? AND ayah=? "
                                      "AND wpos=?", (s, a, w)).fetchone()
                          or cur.execute("SELECT seq FROM classical WHERE source='muktafa' AND surah=? AND "
                                         "(ayah<? OR (ayah=? AND wpos<=?)) ORDER BY ayah DESC, wpos DESC LIMIT 1",
                                         (s, a, a, w)).fetchone() or (0,))[0]))
            stats['hafs_side'] += 1
    for s, a, w, q, g, by, note in RELAYED_ADD:
        if not cur.execute("SELECT 1 FROM classical WHERE source='muktafa' AND surah=? AND ayah=? AND wpos=? "
                           "AND grade=? AND reported_from=?", (s, a, w, g, by)).fetchone():
            seq = (cur.execute("SELECT seq FROM classical WHERE source='muktafa' AND surah=? AND "
                               "(ayah<? OR (ayah=? AND wpos<=?)) ORDER BY ayah DESC, wpos DESC LIMIT 1",
                               (s, a, a, w)).fetchone() or (0,))[0]
            cur.execute("INSERT INTO classical (source, surah, ayah, wpos, stop_word, quote, grade, grade_raw, "
                        "note, seq, conf, reported_from) VALUES ('muktafa',?,?,?,?,?,?,?,?,?,1,?)",
                        (s, a, w, mm.verse_words(s, a)[w], q, g, g, note, seq, by))
            stats['relayed_added'] += 1
    rows = [(r['surah'], r['ayah'], r['wpos'], r['quote'], r['grade'], r['note']) for r in found]
    stats['verse_end_raw'] += sum(cur.execute(
        "UPDATE classical SET grade_raw=? WHERE source='muktafa' AND surah=? AND ayah=? AND wpos=? AND quote=? "
        "AND grade_raw=grade", (VERSE_END_RAW, s, a, w, q)).rowcount
        for s, a, w, q, g, *_ in MANUAL if re.search('[\u064b-\u0652]', q))
    rows += [(s, a, w, q, g, rest[0] if rest else f'{q} {g}') for s, a, w, q, g, *rest in MANUAL]
    for s, a, w, q, g, note in rows:
        have = cur.execute("SELECT id, grade FROM classical WHERE source='muktafa' AND surah=? "
                           "AND ayah=? AND wpos=? AND reported_from IS NULL AND grade_raw<>'رؤوس الآي'",
                           (s, a, w)).fetchall()
        if any(h[1] == g for h in have):
            continue
        if len(have) == 1 and q == cur.execute("SELECT quote FROM classical WHERE id=?",
                                               (have[0][0],)).fetchone()[0]:
            # the «ومثله» item inherited the head's grade; the book grades it here
            cur.execute("UPDATE classical SET grade=?, grade_raw=? WHERE id=?", (g, g, have[0][0]))
            stats['regraded'] += 1
            continue
        seq = (cur.execute("SELECT seq FROM classical WHERE source='muktafa' AND surah=? AND "
                           "(ayah<? OR (ayah=? AND wpos<=?)) ORDER BY ayah DESC, wpos DESC LIMIT 1",
                           (s, a, a, w)).fetchone() or (0,))[0]
        # a verse end the book names only as «ورأس الآية أتم» / «والآية أتم» has no quote of
        # its own: the row carries the mushaf word and grade_raw «رأس الآية» (traced by its note)
        raw = VERSE_END_RAW if re.search('[\u064b-\u0652]', q) else g
        cur.execute("INSERT INTO classical (source, surah, ayah, wpos, stop_word, quote, grade, "
                    "grade_raw, note, seq, conf, reported_from) VALUES ('muktafa',?,?,?,?,?,?,?,?,?,1,NULL)",
                    (s, a, w, mm.verse_words(s, a)[w], q, g, raw, note, seq))
        stats['inserted'] += 1
    con.commit()
    return stats


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--db', default=DB)
    ap.add_argument('--apply', action='store_true')
    args = ap.parse_args(argv)
    con = sqlite3.connect(args.db)
    found, unresolved = resolve(con)
    for r in found:
        w = mm.verse_words(r['surah'], r['ayah'])
        print(f"{r['surah']}:{r['ayah']}:{r['wpos']} «{r['quote']}» {r['ordinal']} {r['grade']} "
              f"[{' '.join(w[max(0, r['wpos'] - 2):r['wpos'] + 1])}]")
    print(f'{len(found)} resolved seats; unresolved: '
          + '، '.join(f"{r['surah']} «{r['quote']}» {r['ordinal']}" for r in unresolved))
    if args.apply:
        print('applied:', dict(apply(con, found)))
    con.close()


if __name__ == '__main__':
    main()
