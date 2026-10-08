"""Second-round review packets aimed at attribution and reading-conditional
rulings: per book, rows credited to a scholar plus own-voice rows whose note
mentions another scholar or a reading (قال، عند، عن، روي، وقيل، غيره، قرأ…).

Run from the repo root:  python3 pipeline/review/random_check/make_attribution_packets.py
"""
import json
import random
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, '.')
sys.path.insert(0, str(Path(__file__).parent))
import make_packets as mp  # noqa: E402  (book texts, excerpt finder)

OUT = Path('artifacts/waqf-random-check/attribution')
OUT.mkdir(parents=True, exist_ok=True)
random.seed(20261009)
PER_BOOK, CREDITED = 40, 20
RISKY = ("(note LIKE '%قال%' OR note LIKE '%عند %' OR note LIKE '%عن %' OR note LIKE '%روي%' "
         "OR note LIKE '%وقيل%' OR note LIKE '%غيره%' OR note LIKE '%قرأ%' OR note LIKE '%قراءة%')")
seen = set()
for f in Path('artifacts/waqf-random-check').glob('batch*.json'):
    if 'result' not in f.name:
        seen |= {p['id'] for p in json.loads(f.read_text(encoding='utf-8'))}

con = sqlite3.connect('data/classical_waqf.db')
con.row_factory = sqlite3.Row
packets = []
for src in ['muktafa', 'manar', 'anbari', 'nahhas']:
    base = f"SELECT * FROM classical WHERE source=? AND conf=1 AND wpos IS NOT NULL AND "
    cred = [r for r in con.execute(base + "COALESCE(reported_from,'')<>''", (src,)) if r['id'] not in seen]
    own = [r for r in con.execute(base + "COALESCE(reported_from,'')='' AND " + RISKY, (src,)) if r['id'] not in seen]
    random.shuffle(cred), random.shuffle(own)
    pick = cred[:CREDITED]
    pick += own[:PER_BOOK - len(pick)]
    for r in pick:
        words = mp.verse_word_texts(f"{r['surah']}:{r['ayah']}")[1]
        ex, nhits = mp.excerpts(src, r['quote'] or r['stop_word'], span=900) or ([], 0)
        packets.append({
            'id': r['id'], 'book': src, 'surah': r['surah'], 'ayah': r['ayah'], 'wpos': r['wpos'],
            'seated_word': words[r['wpos']] if 0 <= r['wpos'] < len(words) else '?',
            'verse_numbered': ' '.join(f'{i}:{w}' for i, w in enumerate(words)),
            'quote': r['quote'], 'grade': r['grade'], 'grade_raw': r['grade_raw'],
            'reported_from': r['reported_from'], 'note': r['note'], 'illa': r['illa'],
            'book_file': str(mp.SRC / mp.FILES[src]), 'quote_hits_in_book': nhits, 'excerpts': ex,
        })
random.shuffle(packets)
for b in range(8):
    (OUT / f'batch{b + 1}.json').write_text(json.dumps(packets[b::8], ensure_ascii=False, indent=1),
                                            encoding='utf-8')
print(len(packets), {s: sum(p['book'] == s for p in packets) for s in mp.FILES},
      'credited:', sum(bool(p['reported_from']) for p in packets))
