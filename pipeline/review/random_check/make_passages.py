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
SEEN = {}          # (book, surah) → passage texts already drawn
for d in Path('artifacts/waqf-random-check').glob('passages*'):
    if d != OUT:
        for f in d.glob('batch*.json'):
            if 'result' not in f.name:
                for p in json.loads(f.read_text(encoding='utf-8')):
                    DONE.setdefault(p['book'], set()).add(p['surah'])
                    SEEN.setdefault((p['book'], p['surah']), []).append(p['text'])
PLAN = {'manar': 8, 'nahhas': 6, 'muktafa': 6, 'anbari': 4}   # passages per book
if len(sys.argv) > 2:                                          # e.g. «nahhas:8,anbari:8»
    PLAN = {b: int(n) for b, n in (x.split(':') for x in sys.argv[2].split(','))}
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


def unseen_runs(book, s, text, span):
    """[(start, end)] stretches of a section no earlier passage covered, at least a span long."""
    covered = []
    for x in SEEN.get((book, s), []):
        # the section text may have been cleaned since (scan slips): find it by short probes
        for k in range(0, max(1, len(x) - 60), 120):
            i = text.find(x[k:k + 60])
            if i >= 0:
                covered.append((max(0, i - k - 200), i - k + len(x) + 200))
                break
    covered.sort()
    runs, pos = [], 0
    for a, b in covered + [(len(text), len(text))]:
        if a - pos >= span:
            runs.append((pos, a))
        pos = max(pos, b)
    return runs


passages = []
for book, n in PLAN.items():
    allsecs = {s: t for s, t in sections(book).items() if s > 1 and len(t) > 400}
    fresh = sorted(s for s in allsecs if s not in DONE.get(book, ()))
    picks = [(s, None) for s in random.sample(fresh, min(n, len(fresh)))]
    if len(picks) < n:
        # every surah drawn once: an unread stretch of a long section instead
        # short books (ابن الأنباري) run out of full-span stretches: accept shorter ones
        span, pool = SPAN[book], []
        while span >= 800:
            pool = [(s, r) for s in sorted(allsecs) if s not in fresh for r in unseen_runs(book, s, allsecs[s], span)]
            if len(pool) >= n - len(picks):
                break
            span //= 2
        picks += random.sample(pool, min(n - len(picks), len(pool)))
    for s, run in picks:
        t = allsecs[s]
        span = SPAN[book]
        lo, hi = run if run else (0, len(t))
        start = lo if hi - lo <= span else random.randrange(lo, hi - span)
        if start:
            nl = t.find('\n', start)
            start = nl + 1 if 0 <= nl < start + 300 else start
        end = min(hi, start + span)
        nl = t.rfind('\n', start, end)
        end = nl if nl > start + span // 2 else end
        passages.append({'book': book, 'surah': s, 'surah_ayahs': rx.surah_ayah_count(s),
                         'starts_at_surah_start': start == 0, 'text': t[start:end]})
random.shuffle(passages)
for b in range(len(passages) // 2):
    (OUT / f'batch{b + 1}.json').write_text(json.dumps(passages[b::len(passages) // 2], ensure_ascii=False, indent=1),
                                            encoding='utf-8')
print(len(passages), [(p['book'], p['surah']) for p in passages])
