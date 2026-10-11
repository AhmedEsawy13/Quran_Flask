"""Fourth round (book → DB): random continuous passages of each book. The
reviewer lists every ruling the passage states and reconciles it with the DB
rows for those verses: missing rulings, unsupported rows, wrong ones.

Run from the repo root:  python3 pipeline/review/random_check/make_passages.py [ROUND]
"""
import json
import random
import re
import sys
from pathlib import Path

sys.path.insert(0, '.')
sys.path.insert(0, 'pipeline')
import audit_anbari  # noqa: E402
import build_classical_waqf as rx  # noqa: E402

ROUND = sys.argv[1] if len(sys.argv) > 1 else ''          # e.g. «2»: a fresh draw
OUT = Path('artifacts/waqf-random-check/passages' + ROUND)
OUT.mkdir(parents=True, exist_ok=True)
random.seed(20261011 + (int(ROUND) if ROUND else 0))
# surahs already drawn in earlier rounds are skipped per book
DONE = {}
for d in Path('artifacts/waqf-random-check').glob('passages*'):
    if d != OUT:
        for f in d.glob('batch*.json'):
            if 'result' not in f.name:
                for p in json.loads(f.read_text(encoding='utf-8')):
                    DONE.setdefault(p['book'], set()).add(p['surah'])
PLAN = {'manar': 8, 'nahhas': 6, 'muktafa': 6, 'anbari': 4}   # passages per book
SPAN = {'manar': 2600, 'nahhas': 2400, 'muktafa': 2200, 'anbari': 2600}


def muktafa_sections():
    body = rx.normalize_muktafa_headings(rx.load_book(rx.SOURCES['muktafa']))
    out, last = {}, 0
    for sec in re.split(r'\n### \| ', body):
        title, _, text = sec.partition('\n')
        if 'سورة' not in title and 'أم القرآن' not in title:
            continue
        n = rx.surah_number(title, last)
        if n:
            out[n], last = text, n
    return out


def sections(book):
    if book == 'muktafa':
        return muktafa_sections()
    if book == 'nahhas':
        return dict(rx.nahhas_sections(rx.load_book(rx.SOURCES['nahhas'])))
    if book == 'anbari':
        return audit_anbari.sections()
    d = json.load(open('pipeline/classical_sources/manar_shamela_sections.json', encoding='utf-8'))
    return {int(k): (v['text'] if isinstance(v, dict) else v) for k, v in d.items()}


passages = []
for book, n in PLAN.items():
    secs = {s: t for s, t in sections(book).items() if s > 1 and len(t) > 400 and s not in DONE.get(book, ())}
    surahs = random.sample(sorted(secs), n)
    for s in surahs:
        t = secs[s]
        span = SPAN[book]
        start = 0 if len(t) <= span else random.randrange(0, len(t) - span)
        if start:
            nl = t.find('\n', start)
            start = nl + 1 if 0 <= nl < start + 300 else start
        end = min(len(t), start + span)
        nl = t.rfind('\n', start, end)
        end = nl if nl > start + span // 2 else end
        passages.append({'book': book, 'surah': s, 'surah_ayahs': rx.surah_ayah_count(s),
                         'starts_at_surah_start': start == 0, 'text': t[start:end]})
random.shuffle(passages)
for b in range(12):
    (OUT / f'batch{b + 1}.json').write_text(json.dumps(passages[b::12], ensure_ascii=False, indent=1),
                                            encoding='utf-8')
print(len(passages), [(p['book'], p['surah']) for p in passages])
