"""Split many Mesaha pages, with a Kraken second opinion line by line.

Each page is split twice: without Kraken (the default rules) and with Kraken's stored word spaces as
a cost (KR_PEN=0.5). A line takes the second version only when Kraken read a space INSIDE one of the
first version's words and the second version disagrees with Kraken less. On the 33-page pilot this
fixed 17 of 17 short-word boundary errors (له ذهب, لا ير, كنتم تز, ...) and changed no word of the ten
hand-checked pages; letting Kraken steer every line broke correct words.

    python3 pipeline/paw_split/mesaha_batch.py 5 9 48 ...        # pages
    python3 pipeline/paw_split/mesaha_batch.py --reviewed        # every reviewed plain-text page
Writes artifacts/mesaha-trace/paw-words-NNN.json (+ 'checks', 'kraken_lines') and batch-summary.json.
"""
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from pipeline.paw_split._common import ROOT, workdir  # noqa: E402

SPLIT = str(Path(__file__).with_name('mesaha_split.py'))
KR_PEN = '0.5'


def reviewed_plain_pages() -> list[int]:
    import sqlite3
    from pipeline.cv_waqf.config import EDITIONS
    spec = EDITIONS['المساحة']
    db = sqlite3.connect(ROOT / 'data' / 'mushaf-mesaha-layout.db')
    headers = {r[0] for r in db.execute("SELECT DISTINCT page_number FROM pages WHERE line_type != 'ayah'")}
    return [p for p in range(spec.min_page, spec.max_page + 1) if spec.layout_trusted(p) and p not in headers]


def split_twice(page: int) -> tuple[int, str]:
    env = dict(os.environ, KR_PEN='0', PAW_SUFFIX='')
    a = subprocess.run([sys.executable, SPLIT, str(page)], capture_output=True, text=True, env=env)
    if a.returncode:
        return page, a.stderr.strip().splitlines()[-1] if a.stderr.strip() else 'failed'
    env = dict(os.environ, KR_PEN=KR_PEN, PAW_SUFFIX='.kr')
    b = subprocess.run([sys.executable, SPLIT, str(page)], capture_output=True, text=True, env=env)
    return page, '' if b.returncode == 0 else 'kraken pass failed'


def merge(page: int) -> dict:
    a = json.load(open(f'paw-words-{page:03d}.json', encoding='utf-8'))
    kr_path = Path(f'paw-words-{page:03d}.kr.json')
    if not kr_path.exists():
        return a
    b = json.load(open(kr_path, encoding='utf-8'))
    flags = lambda d, L: sum(len(w.get('doubt', [])) for w in d['words'] if w['line'] == L)
    inside = lambda d, L: any('Kraken space inside' in w.get('doubt', []) for w in d['words'] if w['line'] == L)
    use = sorted(L for L in range(1, len(a['bands']) + 1) if inside(a, L) and flags(b, L) < flags(a, L))
    if use:
        taken = {pid for w in b['words'] if w['line'] in use for pid in w.get('pieces', [])}
        words = []
        for wa, wb in zip(a['words'], b['words']):
            if wa['line'] in use:
                words.append(wb)
            else:
                w = dict(wa); w['pieces'] = [pid for pid in wa.get('pieces', []) if pid not in taken]
                words.append(w)
        a['words'] = words
        a['checks']['words_without_ink'] = [w['text'] for w in words if not w['ring'] and not w.get('pieces')]
        a['checks']['kraken_flags'] = sum(bool(w.get('doubt')) for w in words)
    a['kraken_lines'] = use
    kr_path.unlink()
    with open(f'paw-words-{page:03d}.json', 'w', encoding='utf-8') as f:
        json.dump(a, f, ensure_ascii=False, indent=1)
    return a


def main(argv: list[str]) -> int:
    pages = reviewed_plain_pages() if argv == ['--reviewed'] else [int(x) for x in argv]
    workdir('mesaha-trace')
    with ThreadPoolExecutor(max_workers=max(1, (os.cpu_count() or 4) - 2)) as pool:
        results = list(pool.map(split_twice, pages))
    summary = {'pages': len(pages), 'failed': {}, 'flagged': {}, 'kraken_lines': {}, 'words': 0, 'kraken_flags': 0}
    for page, err in results:
        if err:
            summary['failed'][page] = err
            continue
        d = merge(page)
        c = d['checks']
        summary['words'] += sum(not w['ring'] for w in d['words'])
        summary['kraken_flags'] += c['kraken_flags']
        if d['kraken_lines']:
            summary['kraken_lines'][page] = d['kraken_lines']
        structural = {k: v for k, v in c.items() if v and k != 'kraken_flags'}
        if structural:
            summary['flagged'][page] = structural
    json.dump(summary, open('batch-summary.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(f"pages {summary['pages']} · failed {len(summary['failed'])} · words {summary['words']} · "
          f"structural flags on {len(summary['flagged'])} pages · Kraken retries on "
          f"{sum(len(v) for v in summary['kraken_lines'].values())} lines · Kraken flags {summary['kraken_flags']}")
    for k in ('failed', 'flagged'):
        if summary[k]:
            print(k, summary[k])
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
