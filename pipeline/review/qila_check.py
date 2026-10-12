"""منار: «وقيل» views stored in the author's voice.

The book often gives its own grade and then a relayed one: «{حذر الموت} [19]
حسن، وقيل: كاف». When both are rows, the «وقيل» row must carry reported_from
«قيل»; otherwise the reader sees the author grade one word twice. This finds
own-voice rows on one word with different grades whose book entry reads
«{…} [n] G1 …، وقيل: G2» (found 37 on 2026-10-12, now credited by
audit_manar_mithl.REPORTED_FIX).

Run:  python3 pipeline/review/qila_check.py [--db PATH]
"""
import argparse
import collections
import os
import re
import sqlite3
import sys
import unicodedata

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path[:0] = [ROOT, os.path.join(ROOT, 'pipeline')]
import audit_manar_mithl as mm  # noqa: E402
import build_classical_waqf as rx  # noqa: E402

DB = os.path.join(ROOT, 'data', 'classical_waqf.db')
GRADES = {'تام': 'تام', 'كاف': 'كاف', 'كافٍ': 'كاف', 'حسن': 'حسن', 'جائز': 'جائز', 'صالح': 'صالح',
          'ليس بوقف': 'لا', 'لا يوقف': 'لا', 'أحسن': 'حسن', 'أكفى': 'كاف', 'أتم': 'تام', 'مفهوم': 'مفهوم'}
_G = '(' + '|'.join(sorted(map(re.escape, GRADES), key=len, reverse=True)) + ')'


def plain(s):
    s = ''.join(c for c in unicodedata.normalize('NFKD', s or '') if not unicodedata.combining(c))
    s = re.sub('[ۖ-ۭـ]', '', s)
    return re.sub('[ٱأإآ]', 'ا', s)


def check(db=DB):
    book = re.sub(r'\s+', ' ', plain(rx.load_book(rx.SOURCES['manar'])))
    con = sqlite3.connect(db)
    seats = collections.defaultdict(list)
    for rid, s, a, w, g in con.execute("SELECT id, surah, ayah, wpos, grade FROM classical WHERE source='manar' "
                                       "AND conf=1 AND reported_from IS NULL AND ayah IS NOT NULL"):
        seats[(s, a, w)].append((rid, g))
    out = []
    for (s, a, w), rows in sorted(seats.items()):
        if len({g for _, g in rows}) < 2:
            continue
        words = mm.verse_words(s, a)
        word = plain(words[w]) if words and w < len(words) else ''
        if not word:
            continue
        stem = re.sub(r'^(وال|فال|بال|لل|ال|و|ف)', '', word)[:4]
        # a short word must close the quote; a longer one is matched by its stem
        head = (r'\{[^{}]*\s' + re.escape(word) + r'(?:\s*\(\d+\))?\}') if len(stem) < 3 else \
            (r'\{[^{}]*' + re.escape(stem) + r'[^{}]*\}')
        pat = (head + r'\s*\[(?:[\d ]*[،,] *)?' + str(a) + r'(?: *[،,][\d، ,]*)?\]\s*' + _G +
               r'[^.{}]{0,60}?[،,]?\s*و?قيل:?\s*(?:هو\s+)?' + _G)
        for m in re.finditer(pat, book):
            if re.search(r'ومثله|وكذا|وكذلك', m.group(0)):
                continue          # the «وقيل» may belong to the chain item
            g1, g2 = GRADES[m.group(1)], GRADES[m.group(2)]
            qila = [rid for rid, g in rows if g == g2]
            if g1 != g2 and qila and any(g == g1 for _, g in rows):
                out.append({'seat': (s, a, w), 'own': g1, 'qila': g2, 'ids': qila, 'text': m.group(0)[:120]})
                break
    return out


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--db', default=DB)
    found = check(ap.parse_args().db)
    print(len(found), 'منار «وقيل» rows stored in the author\'s voice')
    for f in found:
        print(f)
