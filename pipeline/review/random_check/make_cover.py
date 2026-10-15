"""Full-coverage round (book → DB): tile every stretch of a book that no earlier
passage covered, so the passage reviews together read the whole text.

Earlier passages are located exactly (no margin); each gap — however short — is
widened by OVERLAP characters on both sides (a ruling cut at a boundary is read
whole by one of the two passages), nearby gaps are merged, and long windows are
cut at line ends into passages of at most SPAN characters that overlap by OVERLAP.

    python3 pipeline/review/random_check/make_cover.py ROUND anbari,nahhas   # write passagesROUND/
    python3 pipeline/review/random_check/make_cover.py --verify anbari,nahhas  # uncovered chars per book
    python3 pipeline/review/random_check/make_cover.py ROUND nahhas --all       # a fresh full pass of the book
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, '.')
sys.path.insert(0, 'pipeline')
import audit_anbari  # noqa: E402
import build_classical_waqf as rx  # noqa: E402

BASE = Path('artifacts/waqf-random-check')
SPAN = {'manar': 2600, 'nahhas': 2400, 'muktafa': 2200, 'anbari': 2600}
OVERLAP = 150


def sections(book):
    if book == 'nahhas':
        return dict(rx.nahhas_sections(rx.load_book(rx.SOURCES['nahhas'])))
    if book == 'anbari':
        return audit_anbari.sections()
    raise SystemExit(f'{book}: not supported')


def seen(book, exclude=None):
    """(surah) → texts of every passage drawn so far."""
    out = {}
    for d in BASE.glob('passages*'):
        if exclude and d.name == exclude:
            continue
        for f in d.glob('batch*.json'):
            if 'result' in f.name:
                continue
            for p in json.loads(f.read_text(encoding='utf-8')):
                if p['book'] == book:
                    out.setdefault(p['surah'], []).append(p['text'])
    return out


def covered(text, passages):
    """Exact [start, end) intervals of `text` the passages cover (sections may have been
    cleaned since: located by 60-char probes, then the whole passage length)."""
    iv = []
    for x in passages:
        i = text.find(x)
        if i >= 0:
            iv.append((i, i + len(x)))
            continue
        for k in range(0, max(1, len(x) - 60), 120):
            j = text.find(x[k:k + 60])
            if j >= 0:
                iv.append((max(0, j - k), min(len(text), j - k + len(x))))
                break
    iv.sort()
    merged = []
    for a, b in iv:
        if merged and a <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], b))
        else:
            merged.append((a, b))
    return merged


def gaps(text, iv):
    out, pos = [], 0
    for a, b in iv + [(len(text), len(text))]:
        if a > pos and text[pos:a].strip():
            out.append((pos, a))
        pos = max(pos, b)
    return out


def cut(text, lo, hi, span):
    """[lo, hi) into pieces of at most `span`, ending at a line end when one is near."""
    out = []
    while hi - lo > span:
        end = lo + span
        nl = text.rfind('\n', lo + span // 2, end)
        end = nl if nl > 0 else end
        out.append((lo, end))
        lo = max(lo + 1, end - OVERLAP)
    out.append((lo, hi))
    return out


def plan(book, exclude=None, fresh=False):
    secs, prev = sections(book), ({} if fresh else seen(book, exclude))
    out = []
    for s, text in sorted(secs.items()):
        windows = []
        for a, b in gaps(text, covered(text, prev.get(s, []))):
            a, b = max(0, a - OVERLAP), min(len(text), b + OVERLAP)
            if windows and a - windows[-1][1] < 2 * OVERLAP:
                windows[-1] = (windows[-1][0], b)
            else:
                windows.append((a, b))
        for a, b in windows:
            for lo, hi in cut(text, a, b, SPAN[book]):
                out.append({'book': book, 'surah': s, 'surah_ayahs': rx.surah_ayah_count(s),
                            'starts_at_surah_start': lo == 0, 'text': text[lo:hi]})
    return out


def verify(book):
    secs, prev = sections(book), seen(book)
    left = {s: sum(b - a for a, b in gaps(t, covered(t, prev.get(s, [])))) for s, t in secs.items()}
    left = {s: n for s, n in left.items() if n}
    return sum(len(t) for t in secs.values()), left


if __name__ == '__main__':
    if sys.argv[1] == '--verify':
        for book in sys.argv[2].split(','):
            total, left = verify(book)
            print(book, 'chars', total, 'uncovered', sum(left.values()), left)
        sys.exit()
    rnd, books, fresh = sys.argv[1], sys.argv[2].split(','), '--all' in sys.argv
    out_dir = BASE / f'passages{rnd}'
    out_dir.mkdir(parents=True, exist_ok=True)
    passages = [p for b in books for p in plan(b, exclude=out_dir.name, fresh=fresh)]
    # pack small gap passages together: at most 4 passages / ~5000 chars per reviewer call
    batches = [[]]
    for p in passages:
        b = batches[-1]
        if b and (len(b) == 4 or sum(len(x['text']) for x in b) + len(p['text']) > 5000):
            batches.append([p])
        else:
            b.append(p)
    for f in out_dir.glob('batch*.json'):
        f.unlink()
    for i, b in enumerate(batches):
        (out_dir / f'batch{i + 1}.json').write_text(json.dumps(b, ensure_ascii=False, indent=1), encoding='utf-8')
    print(len(batches), 'batches')
    print(len(passages), 'passages', {b: sum(p['book'] == b for p in passages) for b in books},
          'chars', sum(len(p['text']) for p in passages))
