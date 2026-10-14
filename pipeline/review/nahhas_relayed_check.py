"""النحاس: a scholar's view stated next to a braced quote with no row credited to him.

The round-27 review (2026-10-14) found ~20 relayed views the parser skipped —
«{X} قال نافع: تم»، «{X} عن نافع قال: تم»، «قال الأخفش {X} هاهنا تم الكلام». This
lists every braced quote with a scholar and a grade right beside it:

  A  «{X} تم عند فلان»، «{X} وهو كاف على قول فلان»، «{X} عن نافع قال: تم»، «{X} قال أبو حاتم: هو كاف»
  B  «قال الأخفش {X} هاهنا تم الكلام»، «وقال أبو حاتم {X} تام»

and reports those with no row in the surah whose quote ends like X (last two
words, seat_check skeletons) credited to that scholar. Known exceptions —
«قال الأخفش {X} التمام فيه {Y}» (the stop is Y), a name that belongs to the
quote before, other-reading sides — are listed with a reason in
nahhas_relayed_exceptions.json.

Run:  python3 pipeline/review/nahhas_relayed_check.py [--db PATH]
"""
import argparse
import collections
import json
import os
import re
import sqlite3
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path[:0] = [ROOT, os.path.join(ROOT, 'pipeline'), os.path.dirname(os.path.abspath(__file__))]
import build_classical_waqf as rx  # noqa: E402
import seat_check as sc  # noqa: E402

DB = os.path.join(ROOT, 'data', 'classical_waqf.db')
EXCEPTIONS = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'nahhas_relayed_exceptions.json')
# the spellings the book uses → the stored reported_from
NAMES = {'نافع': 'نافع', 'أبو حاتم': 'أبو حاتم', 'أبي حاتم': 'أبو حاتم', 'الأخفش': 'الأخفش',
         'أحمد بن موسى': 'أحمد بن موسى', 'يعقوب': 'يعقوب', 'محمد بن عيسى': 'محمد بن عيسى',
         'أحمد بن جعفر': 'أحمد بن جعفر', 'العباس': 'العباس بن الفضل', 'أبو عبد الله': 'أبو عبد الله',
         'أبي عبد الله': 'أبو عبد الله', 'القتبي': 'القتبي', 'عبد الله بن مسلم': 'القتبي', 'الفراء': 'الفراء',
         'أبو عبيدة': 'أبو عبيدة', 'أبي عبيدة': 'أبو عبيدة', 'نصير': 'نصير', 'الكسائي': 'الكسائي',
         'علي بن سليمان': 'علي بن سليمان', 'ابن شاذان': 'ابن شاذان', 'سيبويه': 'سيبويه',
         'محمد بن يزيد': 'محمد بن يزيد', 'عيسى بن عمر': 'عيسى بن عمر', 'النضر بن شميل': 'النضر بن شميل',
         'أبو إسحاق': 'أبو إسحاق', 'أبي إسحاق': 'أبو إسحاق', 'المازني': 'المازني',
         'أبو عمرو': 'أبو عمرو بن العلاء', 'أبي عمرو': 'أبو عمرو بن العلاء', 'محمد بن جرير': 'محمد بن جرير',
         'أبو عبيد': 'أبو عبيد', 'أبي عبيد': 'أبو عبيد'}
_N = '(' + '|'.join(sorted(map(re.escape, NAMES), key=len, reverse=True)) + r')(?![ء-ي])'
_G = r'(?:قطع\s+|وقف\s+|هو\s+|وهو\s+)?(?:تام|تمام|التمام|تم|كاف|الكافي|حسن|صالح|جيد)(?:\s+الكلام)?'
_PRE = (r'(?:عند|عن|وعن|على\s+قول|في\s+قول|على\s+ما\s+روى?\s+عن|فيما\s+روى?\s+عن|على\s+ما\s+روينا\s+عن)')
_A1 = re.compile(r'\s*[،:.]?\s*' + _G + r'\s+' + _PRE + r'\s+' + _N)
_A2 = re.compile(r'\s*[،:.]?\s*(?:' + _PRE + r'|قال|وقال)\s+' + _N + r'\s*(?:قال)?\s*[:،]?\s*' + _G + r'(?![ء-ي])')
_B_HEAD = re.compile(r'(?:قال|وقال|وزعم|عن|وعن)\s+' + _N + r'\s*[:،]?\s*(?:إن\s+|أن\s+)?$')
_B_TAIL = re.compile(r'\s*[،:.]?\s*(?:هاهنا\s+|ها\s+هنا\s+)?' + _G + r'(?![ء-ي])')


def _words(s):
    return re.sub(r'[^؀-ۿ ]', ' ', s or '').split()


def check(db=DB):
    con = sqlite3.connect(db)
    rows = collections.defaultdict(list)
    for s, q, who in con.execute("SELECT surah, quote, reported_from FROM classical WHERE source='nahhas'"):
        rows[s].append((q, who))
    secs = {}
    for n, text in rx.nahhas_sections(rx.load_book(rx.SOURCES['nahhas'])):
        secs[n] = secs.get(n, '') + text
    out = []
    for s, text in sorted(secs.items()):
        text = re.sub(r'\s+', ' ', text)
        braces = list(re.finditer(r'\{([^{}]{2,80})\}', text))
        for i, m in enumerate(braces):
            lo = max(braces[i - 1].end() if i else 0, m.start() - 80)
            hi = min(braces[i + 1].start() if i + 1 < len(braces) else len(text), m.end() + 120)
            head, tail = text[lo:m.start()], text[m.end():hi]
            names = [NAMES[x.group(1)] for x in (_A1.match(tail), _A2.match(tail)) if x]
            hb = _B_HEAD.search(head)
            if hb and _B_TAIL.match(tail):
                names.append(NAMES[hb.group(1)])
            tail2 = _words(m.group(1))[-2:]
            for who in dict.fromkeys(names):
                if not any(w == who and len(_words(q)) >= len(tail2) and
                           all(sc.score(a, b) for a, b in zip(tail2, _words(q)[-len(tail2):]))
                           for q, w in rows[s]):
                    out.append({'surah': s, 'who': who, 'quote': m.group(1),
                                'context': head[-60:] + '{' + m.group(1) + '}' + tail[:100]})
    return out


def exceptions():
    return json.load(open(EXCEPTIONS, encoding='utf-8'))


def key(m):
    return f"{m['surah']}:{m['who']}:{m['quote']}"


def unexplained(db=DB):
    ex = exceptions()
    return [m for m in check(db) if key(m) not in ex]


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--db', default=DB)
    found = unexplained(ap.parse_args().db)
    print(len(found), 'relayed views with no credited row (beyond nahhas_relayed_exceptions.json)')
    for f in found:
        print(f)
