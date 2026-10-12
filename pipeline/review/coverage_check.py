"""Coverage check: every graded quote in منار and المكتفى has a row.

A sweep of the whole book text (2026-10-12) found rulings the parser had
skipped — المكتفى's «جواب القسم {X} وهو تام» and its «ومثله» chain, منار's
relayed «{X (n) كلا} [n، n+1] G عند …» — which random passage checks only meet
by chance. This lists every quote followed by a grade word with no row whose
quote ends on the same word (consonant skeleton, as seat_check) in its surah
(منار: at the verse its «[n]» names). Known exceptions — book slips whose row
sits at the right seat, other-reading sides, cross-references — are listed
with a reason in coverage_exceptions.json.

Run:  python3 pipeline/review/coverage_check.py [--db PATH]
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
EXCEPTIONS = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'coverage_exceptions.json')
_G = r'(تام|كاف|حسن|صالح|جائز|ليس بوقف|أتم|أكفى|أحسن|مفهوم|قبيح)'


def _sections(book):
    body = rx.load_book(rx.SOURCES[book])
    if book == 'muktafa':
        body = rx.normalize_muktafa_headings(body)
    secs, last = {}, 0
    for sec in re.split(r'\n### \| ', body):
        title, _, text = sec.partition('\n')
        if 'سورة' not in title and 'أم القرآن' not in title:
            continue
        n = rx.surah_number(title, last)
        if n:
            secs[n] = secs.get(n, '') + text
            last = n
    return secs


def _words(s):
    return re.sub(r'[^؀-ۿ ]', ' ', re.sub(r'\(\d+\)', ' ', s or '')).split()


def check(db=DB, books=('manar', 'muktafa')):
    con = sqlite3.connect(db)
    out = []
    for book in books:
        rows = collections.defaultdict(list)
        for s, a, q in con.execute('SELECT surah, ayah, quote FROM classical WHERE source=?', (book,)):
            rows[s].append((a, q))
        if book == 'manar':
            pat = r'\{([^{}]{2,80})\}\s*\[([\d،, ]{1,12})\]\s*[.،]?\s*' + _G + r'(?![ء-ي])'
        else:
            pat = r'(?:\{([^{}]{2,80})\}|\(\(([^()]{2,60})\)\))\s*[.،]?\s*(?:وهو\s+)?' + _G + r'(?![ء-ي])'
        for s, text in sorted(_sections(book).items()):
            text = re.sub(r'\s+', ' ', text)
            for m in re.finditer(pat, text):
                if re.search(r'(?:غير|ليس)\s*$', text[max(0, m.start() - 8):m.start()]):
                    continue
                quote = m.group(1) if book == 'manar' else (m.group(1) or m.group(2))
                # «منزلين. بلى»: either side of the period may carry the stop
                ends = [w[-1] for w in (_words(part) for part in quote.split('.')) if w]
                if not ends:
                    continue
                if book == 'manar':
                    marks = {int(x) for x in re.findall(r'\d+', m.group(2))} | \
                            {int(x) for x in re.findall(r'\((\d+)\)', quote)}
                    cands = [q for a, q in rows[s] if a in marks]
                else:
                    cands = [q for _, q in rows[s]]
                if any(sc.score(e, (_words(q) or [''])[-1]) for e in ends for q in cands):
                    continue
                out.append({'book': book, 'surah': s, 'quote': re.sub(r'\(\d+\)', '', quote).strip(),
                            'context': text[max(0, m.start() - 50):m.end() + 50]})
    return out


def exceptions():
    return json.load(open(EXCEPTIONS, encoding='utf-8'))


def unexplained(db=DB):
    ex = exceptions()
    return [m for m in check(db) if f"{m['surah']}:{m['quote']}" not in ex.get(m['book'], {})]


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--db', default=DB)
    found = unexplained(ap.parse_args().db)
    print(len(found), 'graded quotes with no row (beyond coverage_exceptions.json)')
    for f in found:
        print(f)
