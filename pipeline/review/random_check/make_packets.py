"""Draw a random sample from the four classical books and write review packets
(60 rows per book, 8 mixed batches) for reviewers following INSTRUCTIONS.md.

Run from the repo root:  python3 pipeline/review/random_check/make_packets.py
"""
import json, random, re, sqlite3, sys
from pathlib import Path
sys.path.insert(0, '.')
from core.verse_words import verse_word_texts
from pipeline.build_classical_waqf import norm

SRC = Path('pipeline/classical_sources')
FILES = {'muktafa': 'muktafa_dani_shamela26461.md', 'anbari': 'idah_anbari_sham19_14255.md',
         'nahhas': 'qatc_nahhas_sham19_20966.md', 'manar': 'manar_ashmuni_shamela6496.md'}
OUT = Path('artifacts/waqf-random-check')   # gitignored; one batchN.json per reviewer
OUT.mkdir(parents=True, exist_ok=True)
random.seed(20261008)

def fold(s):
    s = re.sub(r'[ً-ٰٟۖ-ۭـ]', '', s or '')
    s = re.sub('[أإآٱ]', 'ا', s).replace('ى', 'ي').replace('ة', 'ه').replace('ؤ', 'و').replace('ئ', 'ي')
    return s

texts = {k: (SRC / f).read_text(encoding='utf-8') for k, f in FILES.items()}
folded = {}
for k, t in texts.items():
    # map folded index -> raw index
    out, idx = [], []
    for i, ch in enumerate(t):
        f = fold(ch)
        for c in f:
            out.append(c); idx.append(i)
    folded[k] = (''.join(out), idx)

def excerpts(src, quote, n=4, span=700):
    ft, idx = folded[src]
    q = fold(re.sub(r'[{}«»()\[\]]', '', quote)).strip()
    q = re.sub(r'\s+', ' ', q)
    if len(q) < 2:
        return []
    hits, start = [], 0
    while len(hits) < 12:
        j = ft.find(q, start)
        if j < 0: break
        hits.append(j); start = j + 1
    out = []
    for j in hits[:n]:
        a = idx[max(0, j - span)]; b = idx[min(len(idx) - 1, j + len(q) + span)]
        line = texts[src].count('\n', 0, idx[j]) + 1
        out.append({'line': line, 'text': texts[src][a:b]})
    return out, len(hits)

def main():
    con = sqlite3.connect('data/classical_waqf.db'); con.row_factory = sqlite3.Row
    packets = []
    for src in ['muktafa', 'manar', 'anbari', 'nahhas']:
        rows = con.execute("select * from classical where source=? order by random()", (src,)).fetchall()
        random.shuffle(rows := list(rows))
        for r in rows[:60]:
            words = verse_word_texts(f"{r['surah']}:{r['ayah']}")[1]
            ex, nhits = excerpts(src, r['quote'] or r['stop_word']) or ([], 0)
            packets.append({
                'id': r['id'], 'book': src, 'surah': r['surah'], 'ayah': r['ayah'], 'wpos': r['wpos'],
                'seated_word': words[r['wpos']] if r['wpos'] is not None and 0 <= r['wpos'] < len(words) else '(no word seat)' if r['wpos'] is None else '?',
                'verse_numbered': ' '.join(f'{i}:{w}' for i, w in enumerate(words)),
                'quote': r['quote'], 'grade': r['grade'], 'grade_raw': r['grade_raw'],
                'reported_from': r['reported_from'], 'note': r['note'], 'illa': r['illa'],
                'follows': r['follows'], 'conf': r['conf'],
                'book_file': str(SRC / FILES[src]), 'quote_hits_in_book': nhits, 'excerpts': ex,
            })
    random.shuffle(packets)
    # 8 batches, each mixing books
    for b in range(8):
        (OUT / f'batch{b+1}.json').write_text(json.dumps(packets[b::8], ensure_ascii=False, indent=1), encoding='utf-8')
    print(len(packets), {s: sum(p['book'] == s for p in packets) for s in FILES},
          'no excerpt:', sum(not p['excerpts'] for p in packets))


if __name__ == '__main__':
    main()
