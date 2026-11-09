"""Where may a Shamarly word's ink be wrong? A per-word risk score learned from the 1,000 judged words of the audit.

Ownership of an outline by a word is ~92% exact (blind pages) and the audit judged 7.9% of sampled words wrong at least
(the judge misses small missing pieces). Nobody can review 49,000 words, so this ranks them. Features come from the book
itself: the outline counts the text predicts (text_check), how the word compares with the other printed copies of the
same text (outline count, ink area), its fit with its neighbours, and what the builder had to do to it (adopted an
unowned outline). The score is trained on the audit's verdicts and cross-validated on them.

    ~/Development/ShemrlyMushaf/.venv/bin/python pipeline/paw_split/shamarly_word_risk.py [--audit DIR] [--out DIR]
        -> artifacts/shamarly-qvp/risk/words.json  {word key: {page, risk, why}}  and  pages.json  (per page)
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path.home() / 'Development' / 'ShemrlyMushaf'))
import shamarly_mix_render as R  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
SVG = ROOT / 'artifacts' / 'shamarly-qvp' / 'svg'
FEATURES = ['count_ok', 'dT', 'dS', 'abs_dT', 'abs_dS', 'n_out', 'n_big', 'n_small', 'area', 'width', 'height', 'has_copies',
            'd_out', 'area_ratio', 'big_diff', 'small_diff', 'adopted', 'edge_first', 'edge_last', 'gap_r', 'gap_l',
            'text_len', 'text_marks', 'line_words', 'dag_alif', 'wasla']


def outline_stats(paths):
    subs = [sp for _a, d in paths for sp in R._subpaths(d)]
    big = small = 0
    area = 0.0
    for sp in subs:
        xs, ys = [q[0] for q in sp['pts']], [q[1] for q in sp['pts']]
        if sp['area'] > 0:
            if R._small((min(xs), min(ys), max(xs), max(ys))):
                small += 1
            else:
                big += 1
        area += sp['area']
    return big + small, big, small, area


def build_rows():
    """One row per word copy of the 318 built pages: features + identity."""
    import text_check
    model = json.loads(text_check.MODEL_PATH.read_text(encoding='utf-8'))
    words, _marks, _g, _p, _s = R.build_library()
    rows = []
    stats_of = {}
    for rec in (r for v in words.values() for r in v):
        n_out, n_big, n_small, area = outline_stats(rec['paths'])
        rec['_n'] = (n_out, n_big, n_small, area)
    by_text = defaultdict(list)
    for rec in (r for v in words.values() for r in v):
        by_text[rec['text']].append(rec)
    line_words = defaultdict(list)
    for rec in (r for v in words.values() for r in v):
        line_words[(rec['page'], rec['line'])].append(rec)
    for lw in line_words.values():
        lw.sort(key=lambda r: -r['bx'][1])
    for page in sorted({r['page'] for r in (x for v in words.values() for x in v)}):
        stats_of[page] = json.loads((SVG / f'{page:03d}.json').read_text(encoding='utf-8'))
    keys_by_index = {}
    import sqlite3
    for i, k in sqlite3.connect(ROOT / 'data' / 'quran_script.db').execute('SELECT word_index, word_key FROM words'):
        keys_by_index[i] = k
    adopted = defaultdict(int)
    for page, st in stats_of.items():
        for _oid, owner, _b in st.get('adopted', []):
            try:
                adopted[keys_by_index[int(owner.split(':')[1])]] += 1
            except (KeyError, ValueError):
                pass
    for lw in line_words.values():
        for i, rec in enumerate(lw):
            T, S = text_check.predict(model, rec['text'])
            n_out, n_big, n_small, area = rec['_n']
            others = [o for o in by_text[rec['text']] if o is not rec]
            has = len(others) >= 3
            med = lambda f: statistics.median(f(o['_n']) for o in others)
            gap_r = (lw[i - 1]['bx'][0] - rec['bx'][1]) if i > 0 else 20.0
            gap_l = (rec['bx'][0] - lw[i + 1]['bx'][1]) if i + 1 < len(lw) else 20.0
            t = rec['text']
            row = {
                'page': rec['page'], 'line': rec['line'], 'key': rec['key'], 'text': t,
                'count_ok': float(rec['ok']), 'dT': n_out - T, 'dS': n_small - S, 'abs_dT': abs(n_out - T), 'abs_dS': abs(n_small - S),
                'n_out': n_out, 'n_big': n_big, 'n_small': n_small, 'area': area, 'width': rec['bx'][1] - rec['bx'][0],
                'height': rec['box'][3] - rec['box'][1], 'has_copies': float(has),
                'd_out': n_out - med(lambda n: n[0]) if has else 0.0,
                'area_ratio': (area / max(1.0, med(lambda n: n[3]))) if has else 1.0,
                'big_diff': n_big - med(lambda n: n[1]) if has else 0.0,
                'small_diff': n_small - med(lambda n: n[2]) if has else 0.0,
                'adopted': float(adopted.get(rec['key'], 0)), 'edge_first': float(i == 0), 'edge_last': float(i == len(lw) - 1),
                'gap_r': gap_r, 'gap_l': gap_l, 'text_len': len(t), 'text_marks': sum(1 for c in t if 'ً' <= c <= 'ٟ' or c in 'ٰۖۡ'),
                'line_words': len(lw), 'dag_alif': float('ٰ' in t), 'wasla': float('ٱ' in t),
            }
            rows.append(row)
    return rows, text_check


def matrix(rows):
    return np.array([[r[f] for f in FEATURES] for r in rows], dtype=float)


def main():
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import roc_auc_score
    from sklearn.model_selection import StratifiedKFold, cross_val_predict
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    ap = argparse.ArgumentParser()
    ap.add_argument('--audit', type=Path, default=ROOT / 'artifacts' / 'shamarly-qvp' / 'word-audit')
    ap.add_argument('--out', type=Path, default=ROOT / 'artifacts' / 'shamarly-qvp' / 'risk')
    a = ap.parse_args()
    rows, _tc = build_rows()
    index = {(r['page'], r['key']): i for i, r in enumerate(rows)}
    truth = json.loads((a.audit / 'truth' / 'truth.json').read_text(encoding='utf-8'))['items']
    verdict = {}
    for f in (a.audit / 'results').glob('*.jsonl'):
        for line in f.read_text(encoding='utf-8').splitlines():
            if line.strip():
                v = json.loads(line)
                verdict[v['id']] = v['verdict']
    lab = [(index[(t['page'], t['key'])], 1 if verdict[i] in ('MISSING', 'EXTRA', 'BOTH') else 0)
           for i, t in truth.items() if t['planted'] is None and i in verdict and verdict[i] != 'UNSURE' and (t['page'], t['key']) in index]
    X_all = matrix(rows)
    idx = np.array([i for i, _ in lab])
    y = np.array([v for _, v in lab])
    X = X_all[idx]
    print(f'{len(rows)} word copies; {len(y)} judged real words, {int(y.sum())} flagged ({y.mean():.1%})')
    base = 1 - X[:, FEATURES.index('count_ok')]
    print(f'baseline "count check failed": AUC {roc_auc_score(y, base):.3f}, flags {base.mean():.0%} of words, catches {(base * y).sum() / y.sum():.0%} of errors')
    models = {'gbm': HistGradientBoostingClassifier(max_depth=3, learning_rate=0.05, max_iter=150, l2_regularization=1.0),
              'logreg': make_pipeline(StandardScaler(), LogisticRegression(C=0.3, max_iter=2000))}
    best_name, best_auc, best_pred = None, 0, None
    for name, m in models.items():
        aucs, pred = [], np.zeros(len(y))
        for seed in range(5):
            p = cross_val_predict(m, X, y, cv=StratifiedKFold(5, shuffle=True, random_state=seed), method='predict_proba')[:, 1]
            aucs.append(roc_auc_score(y, p))
            pred += p / 5
        print(f'{name}: 5x5-fold CV AUC {np.mean(aucs):.3f} (+-{np.std(aucs):.3f})')
        if np.mean(aucs) > best_auc:
            best_name, best_auc, best_pred = name, np.mean(aucs), pred
    order = np.argsort(-best_pred)
    for frac in (0.1, 0.2, 0.3, 0.4, 0.6):
        k = int(frac * len(y))
        print(f'  review the riskiest {frac:.0%} of words: catches {y[order[:k]].sum() / y.sum():.0%} of the flagged errors (precision {y[order[:k]].mean():.0%})')
    model = models[best_name].fit(X, y)
    risk = model.predict_proba(X_all)[:, 1]
    # why: the features that move this word furthest from the typical word
    mu, sd = X_all.mean(0), X_all.std(0) + 1e-9
    a.out.mkdir(parents=True, exist_ok=True)
    out = {}
    for r, p, x in zip(rows, risk, X_all):
        z = (x - mu) / sd
        top = np.argsort(-np.abs(z))[:2]
        out[r['key']] = {'page': r['page'], 'line': r['line'], 'risk': round(float(p), 4), 'text': r['text'],
                         'why': [f'{FEATURES[j]}={x[j]:.1f}' for j in top]}
    (a.out / 'words.json').write_text(json.dumps(out, ensure_ascii=False), encoding='utf-8')
    import csv
    with open(a.out / 'queue.csv', 'w', encoding='utf-8', newline='') as fh:           # riskiest first: page, line, word
        w = csv.writer(fh)
        w.writerow(['risk', 'page', 'line', 'word_key', 'text', 'why'])
        for k, v in sorted(out.items(), key=lambda kv: -kv[1]['risk']):
            w.writerow([v['risk'], v['page'], v['line'], k, v['text'], ' '.join(v['why'])])
    pages = defaultdict(list)
    for k, v in out.items():
        pages[v['page']].append(v['risk'])
    summary = {str(p): {'words': len(v), 'mean_risk': round(float(np.mean(v)), 4), 'expected_wrong': round(float(np.sum(v)), 1)} for p, v in pages.items()}
    (a.out / 'pages.json').write_text(json.dumps(summary), encoding='utf-8')
    print(f'model {best_name}; mean risk over all words {risk.mean():.1%} (the audit found >= 7.9% wrong); wrote {a.out}')


if __name__ == '__main__':
    main()
