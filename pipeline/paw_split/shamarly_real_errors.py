"""REAL word-ownership errors with exact answers, to measure a reviewer on (the lesson of the Itqan d/961 update).

Planted errors flatter a judge (a planted error is one piece moved to the nearest word; a real one is often a group of letters
that shifted together). ShemrlyMushaf has exact outline labels for ~197 pages (output/exact-labels, from the Elgharib word
glyphs) and, per page, the votes of its four ownership methods (output/exact-labels/stack/page-NNN.json). The shipped
word-owner model is trained on the labelled pages, so its errors there would be too few; instead this trains the SAME kind of
model (methods A, B, D + geometry + text, word_owner_model.line_features) in 5-fold cross-validation BY PAGE and keeps every
word it gets wrong on a page it never saw. Those are real errors with an exact answer.

    ~/Development/ShemrlyMushaf/.venv/bin/python pipeline/paw_split/shamarly_real_errors.py errors [--out artifacts/shamarly-qvp/real-errors]
        -> errors.json  [{page, line, word_index, wrong, kind, n_missing, n_extra, ...}] for every labelled word, and a printed summary
    ~/Development/ShemrlyMushaf/.venv/bin/python pipeline/paw_split/shamarly_real_errors.py sheets --out <dir>
        -> the fixed test: sheets/ (6 words per picture), truth/truth.json; pages are split into TEST (30%, never used to tune
           reviewer instructions) and DEV; every item shows the ink the system gave the word (red) in the word audit's style, and
           a judge says OK / MISSING / EXTRA / BOTH / UNSURE (score with shamarly_word_audit.py-style scoring: score --out <dir>)
"""
from __future__ import annotations

import argparse
import collections
import json
import random
import sys
from pathlib import Path

import numpy as np

SH = Path.home() / 'Development' / 'ShemrlyMushaf'
sys.path[:0] = [str(SH)]
ROOT = Path(__file__).resolve().parents[2]
LAB = SH / 'output' / 'exact-labels'
METHODS = 'ABD'


def is_mark(b):
    w, h = b[2] - b[0], b[3] - b[1]
    return not (w * h >= 20 and (h >= 12 or w >= 30))


def page_rows(page):
    """(features, label, info) of every (outline, candidate word) pair of a page (as stack_model.page_examples)."""
    from word_owner_model import line_features
    data = json.loads((LAB / 'stack' / f'page-{page:03d}.json').read_text(encoding='utf-8'))
    lines, meta = collections.defaultdict(list), {}
    for r in data:
        (lines[r['line']].append(r) if 'id' in r else meta.__setitem__(r['line'], r))
    X, y, info = [], [], []
    for ln, rs in lines.items():
        feats, keys = line_features(rs, meta[ln]['words'], METHODS)
        gt = {r['id']: r['gt'] for r in rs}
        box = {r['id']: r['bbox'] for r in rs}
        hole = {r['id']: r.get('hole_of') for r in rs}
        for f, (oid, wi) in zip(feats, keys):
            X.append(f)
            y.append(int(gt[oid] == wi) if gt[oid] is not None else -1)
            info.append({'page': page, 'line': ln, 'oid': oid, 'wi': wi, 'gt': gt[oid], 'bbox': box[oid], 'hole_of': hole[oid]})
    return X, y, info


def main() -> None:
    from sklearn.ensemble import HistGradientBoostingClassifier
    ap = argparse.ArgumentParser()
    ap.add_argument('cmd', choices=['errors', 'sheets', 'score'])
    ap.add_argument('--out', type=Path, default=ROOT / 'artifacts' / 'shamarly-qvp' / 'real-errors')
    ap.add_argument('--folds', type=int, default=5)
    ap.add_argument('--split', default='test')
    ap.add_argument('--results', default='results')
    ap.add_argument('--seed', type=int, default=20261112)
    a = ap.parse_args()
    if a.cmd == 'sheets':
        sheets(a.out)
        return
    if a.cmd == 'score':
        score(a.out, a.split, a.results)
        return
    pages = sorted(int(p.stem.split('-')[1]) for p in (LAB / 'stack').glob('page-*.json'))
    rows = {p: page_rows(p) for p in pages}
    rng = random.Random(a.seed)
    order = pages[:]
    rng.shuffle(order)
    fold_of = {p: i % a.folds for i, p in enumerate(order)}
    pred = {}                                                     # (page, oid) -> predicted word index
    for f in range(a.folds):
        tr = [p for p in pages if fold_of[p] != f]
        X = np.array([x for p in tr for x in rows[p][0]], float)
        y = np.array([v for p in tr for v in rows[p][1]])
        keep = y >= 0
        clf = HistGradientBoostingClassifier(max_iter=400, learning_rate=0.08, max_leaf_nodes=48, random_state=0)
        clf.fit(X[keep], y[keep])
        for p in (q for q in pages if fold_of[q] == f):
            if not rows[p][0]:
                continue
            prob = clf.predict_proba(np.array(rows[p][0], float))[:, 1]
            best = {}
            for pr, inf in zip(prob, rows[p][2]):
                if inf['oid'] not in best or pr > best[inf['oid']][0]:
                    best[inf['oid']] = (pr, inf['wi'])
            for oid, (_pr, wi) in best.items():
                pred[(p, oid)] = wi
        print(f'fold {f}: trained on {len(tr)} pages, {int(keep.sum())} pairs', flush=True)
    info = {}                                                     # (page, oid) -> info row
    for p in pages:
        for inf in rows[p][2]:
            info[(p, inf['oid'])] = inf
    for (p, oid), inf in info.items():                            # a hole goes with the outline around it
        if inf['hole_of'] and (p, inf['hole_of']) in pred and (p, oid) in pred:
            pred[(p, oid)] = pred[(p, inf['hole_of'])]
    words = collections.defaultdict(lambda: {'gt': [], 'got': [], 'lines': set()})
    for (p, oid), inf in info.items():
        if inf['gt'] is not None:
            w = words[(p, inf['gt'])]
            w['gt'].append((oid, inf['bbox'], pred.get((p, oid))))
            w['lines'].add(inf['line'])
    for (p, oid), wi in pred.items():                            # outlines a word got that the answer gives elsewhere
        inf = info[(p, oid)]
        if inf['gt'] is not None and wi != inf['gt']:
            words[(p, wi)]['got'].append((oid, inf['bbox'], inf['gt']))
    out = []
    for (p, wi), w in words.items():
        missing = [(o, b, got) for o, b, got in w['gt'] if got != wi]
        extra = w['got']
        wrong = bool(missing or extra)
        wrong_boxes = [b for _o, b, _g in missing] + [b for _o, b, _g in extra]
        kinds = sorted({'mark' if is_mark(b) else 'body' for b in wrong_boxes})
        out.append({'page': p, 'word_index': wi, 'line': sorted(w['lines'])[0] if w['lines'] else None, 'wrong': wrong,
                    'n_outlines': len(w['gt']), 'n_missing': len(missing), 'n_extra': len(extra),
                    'kind': '+'.join(kinds) if kinds else '', 'fold': fold_of[p],
                    'wrong_area': round(sum((b[2] - b[0]) * (b[3] - b[1]) for b in wrong_boxes), 1),
                    'to_neighbour': any(abs((got or 0) - wi) == 1 for _o, _b, got in missing),
                    'other_line': False})
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / 'errors.json').write_text(json.dumps(out), encoding='utf-8')
    (a.out / 'pred.json').write_text(json.dumps({f'{p}|{o}': wi for (p, o), wi in pred.items()}), encoding='utf-8')
    n = len(out)
    bad = [r for r in out if r['wrong']]
    print(f'{n} labelled words on {len(pages)} pages; REAL errors (out-of-fold): {len(bad)} = {len(bad) / n:.1%}')
    kinds = collections.Counter(r['kind'] for r in bad)
    print('by kind of wrong piece:', dict(kinds))
    size = collections.Counter('tiny (<8 pt2)' if r['wrong_area'] < 8 else 'small (<40)' if r['wrong_area'] < 40 else 'large' for r in bad)
    print('by size of the wrong ink:', dict(size))
    print('goes to / comes from the neighbouring word:', sum(r['to_neighbour'] for r in bad), 'of', len(bad))
    print('words with 1 wrong outline:', sum(1 for r in bad if r['n_missing'] + r['n_extra'] == 1), '; 2-3:',
          sum(1 for r in bad if 2 <= r['n_missing'] + r['n_extra'] <= 3), '; 4+:', sum(1 for r in bad if r['n_missing'] + r['n_extra'] >= 4))


def page_polys(page):
    """{outline id: [polygon points in page pt]} of every outline of a labelled page (its extraction run's line outlines)."""
    from line_moves import line_outlines
    from pdf_glyph_editor import CONTENT_X0, PDF_TO_FONT, load_page_report
    from pdf_review_store import page_directory
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from shamarly_qvp_svg import _d
    from shamarly_word_audit import flatten
    run = 'stack-train' if (SH / 'output' / 'pdf' / 'stack-train' / f'page-{page:03d}').exists() else 'pipeline-eval'
    page_dir = page_directory(run, page, SH / 'output' / 'pdf')
    report = load_page_report(page_dir)
    out = {}
    for line in report['lines']:
        ln = int(line['line_number'])
        bottom = float(line['bbox'][3])
        for suffix, raw, _p in line_outlines(page_dir, report, ln):
            out[f'L{ln}:{suffix}'] = flatten(_d(raw, PDF_TO_FONT, CONTENT_X0, bottom))
    return out


def sheets(out: Path, n_test=(90, 70, 80), n_clean_test=160, n_dev=(40, 40, 40), n_clean_dev=80, seed=20261113) -> None:
    import sqlite3
    import cv2
    from PIL import Image
    import shamarly_word_audit as W
    texts = dict(sqlite3.connect(ROOT / 'data' / 'quran_script.db').execute('SELECT word_index, text FROM words').fetchall())
    digits = set('٠١٢٣٤٥٦٧٨٩۝')
    rows = [r for r in json.loads((out / 'errors.json').read_text(encoding='utf-8'))
            if texts.get(r['word_index'], '') and not set(texts[r['word_index']]) <= digits]      # a verse ring + its number is no word: the
    pred = {tuple(k.split('|')): v for k, v in json.loads((out / 'pred.json').read_text(encoding='utf-8')).items()}  # labels split it differently
    pages = sorted({r['page'] for r in rows})
    rng = random.Random(seed)
    shuffled = pages[:]
    rng.shuffle(shuffled)
    test_pages = set(shuffled[:round(0.3 * len(pages))])

    def pick(pool, counts, split_pages):
        chosen = []
        for kind, k in zip(('mark', 'body+mark', 'body'), counts):
            cand = [r for r in pool if r['wrong'] and r['kind'] == kind and r['page'] in split_pages]
            rng.shuffle(cand)
            chosen += cand[:k]
        return chosen

    def pick_clean(pool, k, split_pages, like):
        cand = [r for r in pool if not r['wrong'] and r['page'] in split_pages and r['n_outlines'] >= 1]
        rng.shuffle(cand)
        want = collections.Counter(min(r['n_outlines'], 8) for r in like)         # clean words with the same outline-count profile
        got, taken = [], collections.Counter()
        for r in cand:
            b = min(r['n_outlines'], 8)
            if taken[b] < max(1, round(want[b] / max(1, len(like)) * k)):
                got.append(r)
                taken[b] += 1
            if len(got) == k:
                break
        return got
    dev_pages = set(pages) - test_pages
    items = []
    for split, spages, cnt, nclean in (('test', test_pages, n_test, n_clean_test), ('dev', dev_pages, n_dev, n_clean_dev)):
        bad = pick(rows, cnt, spages)
        items += [{**r, 'split': split} for r in bad + pick_clean(rows, nclean, spages, bad)]
    rng.shuffle(items)
    for sub in ('sheets', 'truth'):
        (out / sub).mkdir(parents=True, exist_ok=True)
    cache, cells, truth = {}, [], {}
    for number, it in enumerate(items):
        p = it['page']
        if p not in cache:
            cache[p] = page_polys(p)
        polys = cache[p]
        mine_ids = [o for (pg, o), wi in pred.items() if pg == str(p) and wi == it['word_index']]
        boxes = []
        for o in mine_ids:
            for sub in polys.get(o, []):
                boxes.append(W._box(sub))
        gt_ids = [o for o in polys if False]
        if not boxes:
            continue
        x0, y0 = min(b[0] for b in boxes) - 9, min(b[1] for b in boxes) - 10
        x1, y1 = max(b[2] for b in boxes) + 9, max(b[3] for b in boxes) + 9
        region = (x0, y0, x1, y1)
        mine = [s for o in mine_ids for s in polys.get(o, [])]
        others = [s for o, subs in polys.items() if o not in set(mine_ids) for s in subs]
        plain = W._render(region, [(W.COL['ink'], mine + others)])
        coloured = W._render(region, [(W.COL['other'], others), (W.COL['mine'], mine)])
        img = np.hstack([plain, np.full((plain.shape[0], 8, 3), 120, np.uint8), coloured])
        if img.shape[1] > 1500:
            k = 1500 / img.shape[1]
            img = cv2.resize(img, (1500, max(1, int(img.shape[0] * k))), interpolation=cv2.INTER_AREA)
        iid = f'r{number:04d}'
        header = np.full((18, img.shape[1], 3), 235, np.uint8)
        cv2.putText(header, iid, (4, 13), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)
        cells.append((np.vstack([header, img]), {'id': iid, 'text': texts.get(it['word_index'], '')}))
        truth[iid] = {k: it[k] for k in ('page', 'word_index', 'wrong', 'kind', 'wrong_area', 'n_missing', 'n_extra', 'n_outlines', 'split')}
    for split in ('dev', 'test'):                                   # sheets never mix the two: judges for tuning only ever see dev
        mine_cells = [(c, m) for c, m in cells if truth[m['id']]['split'] == split]
        for s in range(0, len(mine_cells), 6):
            chunk = mine_cells[s:s + 6]
            width = max(c.shape[1] for c, _ in chunk)
            canvas = np.full((sum(c.shape[0] + 6 for c, _ in chunk), width, 3), 255, np.uint8)
            y = 0
            for c, _ in chunk:
                canvas[y:y + c.shape[0], :c.shape[1]] = c
                y += c.shape[0] + 6
            name = f'{split}_sheet_{s // 6:03d}'
            Image.fromarray(canvas[:, :, ::-1]).save(out / 'sheets' / f'{name}.png')
            (out / 'sheets' / f'{name}.json').write_text(json.dumps([m for _, m in chunk], ensure_ascii=False), encoding='utf-8')
    (out / 'truth' / 'truth.json').write_text(json.dumps({'seed': seed, 'test_pages': sorted(test_pages), 'items': truth}, ensure_ascii=False), encoding='utf-8')
    by = collections.Counter((t['split'], t['wrong']) for t in truth.values())
    print(f'{len(truth)} items on {len(cells) // 6 + 1} sheets;', dict(by))


def score(out: Path, split: str, results: str = 'results') -> None:
    """Judge results (<out>/results/*.jsonl {id, verdict, note}) against the real errors: recall by kind and size, false alarms."""
    truth = json.loads((out / 'truth' / 'truth.json').read_text(encoding='utf-8'))['items']
    verdict = {}
    for f in sorted((out / results).glob('*.jsonl')):
        for line in f.read_text(encoding='utf-8').splitlines():
            if line.strip():
                r = json.loads(line)
                verdict[r['id']] = r['verdict']
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from shamarly_word_audit import clopper_pearson_upper
    flagged = lambda i: verdict[i] in ('MISSING', 'EXTRA', 'BOTH')
    items = {i: t for i, t in truth.items() if t['split'] == split and i in verdict}
    label_wrong = set()                                    # errors of the KEY, found by looking (adjudicate/results_*.jsonl OURS_RIGHT)
    for f in sorted((out / 'adjudicate').glob('results_*.jsonl')) if (out / 'adjudicate').exists() else []:
        for line in f.read_text(encoding='utf-8').splitlines():
            if line.strip() and json.loads(line)['verdict'] == 'OURS_RIGHT':
                label_wrong.add(json.loads(line)['id'])
    if label_wrong:
        print(f'{len([i for i in label_wrong if i in items])} items the answer key got wrong (adjudicated by looking) are dropped from the errors')
        items = {i: t for i, t in items.items() if i not in label_wrong}
    wrong = [i for i, t in items.items() if t['wrong']]
    clean = [i for i, t in items.items() if not t['wrong']]
    unsure = [i for i in items if verdict[i] == 'UNSURE']
    caught = [i for i in wrong if flagged(i)]
    fa = [i for i in clean if flagged(i)]
    print(f'split {split}: judged {len(items)} (real errors {len(wrong)}, clean {len(clean)}, unsure {len(unsure)})')
    if wrong:
        print(f'recall on real errors: {len(caught)}/{len(wrong)} = {len(caught) / len(wrong):.1%}')
    if clean:
        print(f'false alarms on clean words: {len(fa)}/{len(clean)} = {len(fa) / len(clean):.1%} (95% upper {clean and clopper_pearson_upper(len(fa), len(clean)):.1%})')
    for name, sel in (('mark only', lambda t: t['kind'] == 'mark'), ('body + mark', lambda t: t['kind'] == 'body+mark'), ('body only', lambda t: t['kind'] == 'body'),
                      ('tiny wrong ink (<8 pt2)', lambda t: t['wrong_area'] < 8), ('small (8-40)', lambda t: 8 <= t['wrong_area'] < 40),
                      ('large (40+)', lambda t: t['wrong_area'] >= 40), ('1 wrong outline', lambda t: t['n_missing'] + t['n_extra'] == 1),
                      ('2-3 wrong outlines', lambda t: 2 <= t['n_missing'] + t['n_extra'] <= 3), ('4+ wrong outlines', lambda t: t['n_missing'] + t['n_extra'] >= 4)):
        ids = [i for i in wrong if sel(truth[i])]
        if ids:
            print(f'  {name:26s} caught {sum(1 for i in ids if flagged(i))}/{len(ids)}')
    miss = [i for i in wrong if not flagged(i)]
    (out / f'missed_{results}.json').write_text(json.dumps([{'id': i, **truth[i]} for i in miss], ensure_ascii=False, indent=1), encoding='utf-8')


if __name__ == '__main__':
    main()
