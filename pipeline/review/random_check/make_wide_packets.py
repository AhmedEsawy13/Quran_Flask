"""Third round: a wider random check weighted toward منار. 150 منار rows in four
strata (plain heads, «ومثله» chain rows, reading/i'rab-conditional rows,
rulings on a word its verse repeats) + ~33 rows from each other book, none
checked before. 10 mixed batches of 25.

Run from the repo root:  python3 pipeline/review/random_check/make_wide_packets.py
"""
import json
import random
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, '.')
sys.path.insert(0, str(Path(__file__).parent))
import make_packets as mp  # noqa: E402
from pipeline.build_classical_waqf import norm  # noqa: E402

ROOT = Path('artifacts/waqf-random-check')
OUT = ROOT / 'wide'
OUT.mkdir(parents=True, exist_ok=True)
random.seed(20261010)
COND = re.compile(r'قرأ|قراءة|لمن |إن جعل|إن جعلت|على أن|إن نصب|إن رفع|عند من')
seen = set()
for f in ROOT.rglob('batch*.json'):
    if 'result' not in f.name:
        seen |= {p['id'] for p in json.loads(f.read_text(encoding='utf-8'))}

con = sqlite3.connect('data/classical_waqf.db')
con.row_factory = sqlite3.Row
words_cache = {}


def words(s, a):
    if (s, a) not in words_cache:
        words_cache[(s, a)] = mp.verse_word_texts(f'{s}:{a}')[1]
    return words_cache[(s, a)]


def repeated(r):
    w = words(r['surah'], r['ayah'])
    return 0 <= r['wpos'] < len(w) and sum(norm(x) == norm(w[r['wpos']]) for x in w) > 1


def pool(src):
    return [r for r in con.execute("SELECT * FROM classical WHERE source=? AND conf=1 AND wpos IS NOT NULL",
                                   (src,)) if r['id'] not in seen]


manar = pool('manar')
random.shuffle(manar)
strata = {
    'chain': [r for r in manar if r['follows'] or (r['note'] or '').startswith(('ومثله', 'مثل «'))],
    'conditional': [r for r in manar if COND.search(r['note'] or '')],
    'repeated_word': [r for r in manar if repeated(r)],
}
pick, used = [], set()
for name, n in (('chain', 40), ('conditional', 40), ('repeated_word', 30)):
    got = [r for r in strata[name] if r['id'] not in used][:n]
    used |= {r['id'] for r in got}
    pick += [(r, name) for r in got]
plain = [r for r in manar if r['id'] not in used][:150 - len(pick)]
pick += [(r, 'plain') for r in plain]
for src, n in (('muktafa', 34), ('anbari', 33), ('nahhas', 33)):
    rows = pool(src)
    random.shuffle(rows)
    pick += [(r, 'plain') for r in rows[:n]]

packets = []
for r, stratum in pick:
    src = r['source']
    w = words(r['surah'], r['ayah'])
    ex, nhits = mp.excerpts(src, r['quote'] or r['stop_word'], span=900) or ([], 0)
    packets.append({
        'id': r['id'], 'book': src, 'stratum': stratum, 'surah': r['surah'], 'ayah': r['ayah'],
        'wpos': r['wpos'], 'seated_word': w[r['wpos']] if 0 <= r['wpos'] < len(w) else '?',
        'verse_numbered': ' '.join(f'{i}:{x}' for i, x in enumerate(w)),
        'quote': r['quote'], 'grade': r['grade'], 'grade_raw': r['grade_raw'],
        'reported_from': r['reported_from'], 'note': r['note'], 'illa': r['illa'], 'follows': r['follows'],
        'book_file': str(mp.SRC / mp.FILES[src]), 'quote_hits_in_book': nhits, 'excerpts': ex,
    })
random.shuffle(packets)
for b in range(10):
    (OUT / f'batch{b + 1}.json').write_text(json.dumps(packets[b::10], ensure_ascii=False, indent=1),
                                            encoding='utf-8')
print(len(packets), {s: sum(p['book'] == s for p in packets) for s in mp.FILES},
      {k: sum(p['stratum'] == k for p in packets if p['book'] == 'manar')
       for k in ('plain', 'chain', 'conditional', 'repeated_word')})
