"""Wrong-word check: a row whose quote does not end on the word it is seated on.

A planted-error test (2026-10-11) showed that neither the reviewer model nor the
catalog gate notices a row moved a word or two off its stop. This compares the
quote's closing words with the verse words by consonant skeleton (the book
writes «الصالحين» / «الزكاة» where the mushaf has «ٱلصَّٰلِحِينَ» / «ٱلزَّكَوٰةَ»):

  flagged  the seated word does not match the quote's last word, or another
           word of the verse matches the quote's closing words better (the
           right occurrence of a repeated word: «وأصحاب اليمين ما أصحاب اليمين»)

Blanket rows (quote = the verse-end word) and book slips pinned in
hand_pinned_seats.json are skipped.

Run:  python3 pipeline/review/seat_check.py [--db PATH] [--show N]
"""
import argparse
import json
import os
import re
import sqlite3
import sys
import unicodedata

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
from core.verse_words import verse_word_texts  # noqa: E402

DB = os.path.join(ROOT, 'data', 'classical_waqf.db')
PINS = os.path.join(ROOT, 'pipeline', 'review', 'hand_pinned_seats.json')
BOOKS = ('manar', 'muktafa', 'anbari', 'nahhas')


def skel(word):
    """Consonant skeletons of a word: with and without an article or و/ف/ب/ل/ك prefix,
    long vowels and hamza seats dropped («الليل» vs «ٱلَّيۡلِ», «الصالحين» vs «ٱلصَّٰلِحِينَ»)."""
    s = ''.join(c for c in unicodedata.normalize('NFKD', word or '') if not unicodedata.combining(c))
    s = s.replace('ٱ', 'ا').replace('ـ', '').replace('ة', 'ه')
    s = re.sub(r'[^ء-ي]', '', s)
    out = set()
    for v in (s, re.sub(r'^(?:[وف]?(?:ب|ل|ك)?ال|[وف]?لل|[وف]?(?:ب|ل|ك)|[وف])(?=..)', '', s),
              re.sub(r'^[وف]?(?:ب|ل|ك)?ا?ل', '', s)):
        out.add(re.sub(r'[اأإآءؤئوىي]', '', v) or v)     # «وإياي»: all long vowels
    return out


def near(a, b):
    """One edit apart (substitution, insertion, deletion or swap) — the book's typos and
    reading variants («أنفنسا»، «يعملون»، «تعتدون» for Hafs «يعتدون»)."""
    if abs(len(a) - len(b)) > 1 or min(len(a), len(b)) < 3:
        return False
    if len(a) == len(b):
        diff = [i for i in range(len(a)) if a[i] != b[i]]
        return len(diff) == 1 or (len(diff) == 2 and diff[1] == diff[0] + 1
                                  and a[diff[0]] == b[diff[1]] and a[diff[1]] == b[diff[0]])
    s, l = sorted((a, b), key=len)
    return any(l[:i] + l[i + 1:] == s for i in range(len(l)))


def score(q, w):
    best = 0
    for a in skel(q):
        for b in skel(w):
            if a == b:
                return 2
            if len(a) >= 2 and len(b) >= 2 and (a.startswith(b) or b.startswith(a)) or near(a, b):
                best = 1
    return best


def fit(qwords, words, i):
    """How well the quote's closing words fit a stop on words[i]: last word first, then the run before it."""
    s = score(qwords[-1], words[i])
    if not s:
        return (0, 0)
    run = 0
    for k in range(1, min(len(qwords), i + 1)):
        if score(qwords[-1 - k], words[i - k]):
            run += 1
        else:
            break
    return (s, run)


def pinned():
    d = json.load(open(PINS, encoding='utf-8'))
    out = set()
    for book, items in d.items():
        if isinstance(items, dict):
            out |= {(book, k) for k in items}
    return out


def check(db=DB, books=BOOKS):
    con = sqlite3.connect(db)
    pins = pinned()
    words_of, bad = {}, []
    for rid, book, s, a, w, q in con.execute(
            "SELECT id, source, surah, ayah, wpos, quote FROM classical WHERE ayah IS NOT NULL AND wpos IS NOT NULL "
            f"AND source IN ({','.join('?' * len(books))}) AND grade_raw<>'رؤوس الآي' AND COALESCE(quote,'')<>''",
            books):
        if (book, str(rid)) in pins or (book, f'{s}:{a}:{w}:{q}') in pins:
            continue
        if (s, a) not in words_of:
            words_of[(s, a)] = verse_word_texts(f'{s}:{a}')[1]
        words = words_of[(s, a)]
        # «X. Y»: المكتفى stops on X («منزلين. بلى»), ابن الأنباري on Y («غدا. إلا أن يشاء الله»)
        variants = [re.sub(r'[^؀-ۿ ]', ' ', v).split() for v in {q.split('.')[0], q}]
        qwords = max(variants, key=lambda v: fit(v, words, w) if v and w < len(words) else (-1, 0))
        if not qwords or w >= len(words):
            bad.append((rid, book, s, a, w, q, None, 'no word'))
            continue
        here = fit(qwords, words, w)
        best = max(range(len(words)), key=lambda i: (fit(qwords, words, i), -abs(i - w)))
        if here[0] == 0:
            bad.append((rid, book, s, a, w, q, words[w], f'no match; best {best} {words[best]}'))
        elif fit(qwords, words, best) > here and fit(qwords, words, best)[1] > here[1]:
            bad.append((rid, book, s, a, w, q, words[w], f'better at {best} {words[best]}'))
    return bad


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--db', default=DB)
    ap.add_argument('--show', type=int, default=40)
    a = ap.parse_args()
    bad = check(a.db)
    print(len(bad), 'rows whose quote does not end on their word')
    for b in bad[:a.show]:
        print(b)
