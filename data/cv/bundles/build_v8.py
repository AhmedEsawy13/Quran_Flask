"""Build data/cv/bundles/multiprint_crops_v8.npz (2026-10-17).

    PYTHONPATH=. python3 artifacts/cv-waqf/bundle-v8/build_v8.py

v8 = v7 with its Shamarly part rebuilt:
1. every v7 crop from a Shamarly page group is dropped: they were cut with the old word positions
   (a whole line off under surah banners, letter-count word splits) and so carried label noise;
2. Shamarly crops re-sampled with the corrected positions (vector lines, page-font widths, word cuts),
   same 420 training pages (bundle-v6/pages.json), labelled from the corrected column; `none` thinned
   to 12,000, rare signs (لا ع م س) x4 and قلى x2 in training groups only, like v6/v7;
3. hard negatives x4: Shamarly's reviewed v6 false marks (re-cut, they were dropped with the rest), plus
   every v7 false mark confirmed in this round's reviews (maybe/add cards decided «the column is right»)
   on every print except Madinah 1441. Never from a held-out or validation page.
Train with --cap-none 0, one seed at a time (OOM with two on 16 GB).
"""
import collections, json, random, sys
from pathlib import Path
import numpy as np
sys.path.insert(0, '/Users/mac/Quran_Flask')
from pipeline.cv_waqf import CLASSES
from pipeline.cv_waqf.candidates import Candidate, crop_candidate
from pipeline.cv_waqf.config import CROP_SIZE, EDITIONS
from pipeline.cv_waqf.pages import ensure_page_image
from pipeline.cv_waqf.preprocess import load_bgr, preprocess_page
from pipeline.cv_waqf.train_classifier import load_grouped_dataset

A = Path('/Users/mac/Quran_Flask/artifacts/cv-waqf'); B = Path('/Users/mac/Quran_Flask/data/cv/bundles')
NONE = CLASSES.index('none'); Q = CLASSES.index('ق'); RARE = [CLASSES.index(s) for s in ('لا', 'ع', 'م', 'س')]
SEED, HARD_COPIES = 2033, 4

with np.load(B / 'multiprint_crops_v7.npz', allow_pickle=False) as z:
    px, y, g, meta = z['pixels'], z['y'].astype(np.int64), z['groups'].astype(object), json.loads(str(z['meta']))
keep = np.array([not str(v).startswith('shamarly:') for v in g])
print('v7', len(y), 'dropping Shamarly rows', int((~keep).sum()))
px, y, g = px[keep], y[keep], g[keep]
val = {v for v in meta['validation_groups'] if not v.startswith('shamarly:')}

held = collections.defaultdict(set)
for v, key, eid in (('v4', 'bahrain_heldout_all', 'bahrain'), ('v4', 'qatar_holdout_50', 'qatar'),
                    ('v4', 'kuwait_holdout_100', 'kuwait'), ('v5', 'madinah_1405_holdout_100', 'madinah_1405'),
                    ('v6', 'shamarly_holdout_100', 'shamarly')):
    held[eid] |= set(json.loads((A / f'bundle-{v}' / 'pages.json').read_text())[key])

# 2. new Shamarly crops
x, ys, gs = load_grouped_dataset([Path('/Users/mac/Quran_Flask/data/cv/crops_candidates/shamarly_v8')])
ps = np.rint((1.0 - x) * 255.0).astype(np.uint8).reshape(len(x), -1); ys = ys.astype(np.int64); gs = np.asarray([str(v) for v in gs], dtype=object)
leak = {int(str(v).split(':p')[1]) for v in gs.tolist()} & held['shamarly']
assert not leak, f'held-out Shamarly pages leaked: {sorted(leak)[:5]}'
nidx = np.flatnonzero(ys == NONE); kn = set(random.Random(SEED).sample(nidx.tolist(), min(12000, nidx.size)))
sel = np.array([i for i in range(len(ys)) if ys[i] != NONE or i in kn])
ps, ys, gs = ps[sel], ys[sel], gs[sel]
sh_groups = sorted({str(v) for v in gs.tolist()}); sh_val = set(sh_groups[::10]); val |= sh_val
rare = np.array([i for i in range(len(ys)) if ys[i] in RARE and str(gs[i]) not in sh_val], dtype=int)
qq = np.array([i for i in range(len(ys)) if ys[i] == Q and str(gs[i]) not in sh_val], dtype=int)
rep = np.concatenate([np.repeat(rare, 3), qq]) if len(rare) or len(qq) else np.array([], dtype=int)
ps = np.concatenate([ps, ps[rep]]); ys = np.concatenate([ys, ys[rep]]); gs = np.concatenate([gs, gs[rep]])
print('new Shamarly', len(ys), {CLASSES[k]: v for k, v in sorted(collections.Counter(ys.tolist()).items())})

# 3. hard negatives
by_id = {spec.id: name for name, spec in EDITIONS.items()}
want = collections.defaultdict(set)          # (eid, page) -> word keys
src = {}
for c in json.load(open(A / 'agent_review_verdicts.json'))['shamarly']:
    if c['choice'] == 'db' and c['tab'] in ('maybe', 'add') and c.get('cv') != 'س':
        want[('shamarly', c['page'])].add(c['word_key']); src[('shamarly', c['page'], c['word_key'])] = A / 'v6ens_live' / 'shamarly-audit' / 'pages.jsonl'
now = json.load(open(A / 'agent' / 'review_now.json'))
for name, rows in now.items():
    eid = EDITIONS[name].id
    if eid == 'madinah_1441':
        continue
    for r in rows:
        if r['decision'] == 'ok' and r['tab'] in ('maybe', 'add') and r.get('cv') != 'س':
            want[(eid, r['page'])].add(r['word_key']); src[(eid, r['page'], r['word_key'])] = A / f'{eid}-audit' / 'pages.jsonl'
boxes = {}
for path in set(src.values()):
    for line in open(path, encoding='utf-8'):
        rec = json.loads(line)
        for it in rec['items']:
            if it['kind'] == 'not_in_db' and it.get('box'):
                boxes[(str(path), rec['page'], it['word_key'])] = it['box']
hp, hg, skipped = [], [], collections.Counter()
for (eid, page), keys in sorted(want.items()):
    group = f'{eid}:p{page:04d}'
    if page in held[eid]: skipped['held-out'] += len(keys); continue
    if group in val: skipped['validation'] += len(keys); continue
    spec = EDITIONS[by_id[eid]]
    prep = preprocess_page(load_bgr(ensure_page_image(spec, page)), spec, page=page)
    for k in sorted(keys):
        b = boxes.get((str(src[(eid, page, k)]), page, k))
        if b is None: skipped['no box'] += 1; continue
        hp.append(crop_candidate(prep.gray, Candidate(b[0], b[1], b[2] - b[0], b[3] - b[1], 1), size=CROP_SIZE).reshape(-1)); hg.append(group)
print('hard negatives', len(hp), dict(collections.Counter(x.split(':')[0] for x in hg)), 'skipped', dict(skipped))
hp = np.stack(hp).astype(np.uint8); r4 = np.repeat(np.arange(len(hp)), HARD_COPIES)

pixels = np.concatenate([px, ps, hp[r4]]); labels = np.concatenate([y, ys, np.full(len(r4), NONE)])
groups = np.concatenate([g, gs, np.asarray(hg, dtype=object)[r4]])
meta = dict(meta, validation_groups=sorted(val), note=(
    'v8 (2026-10-17): v7 minus its Shamarly rows; Shamarly re-sampled with the corrected word positions '
    '(420 train pages); hard negatives x4 from reviewed v6 Shamarly cards and this round\'s v7 cards on every '
    'print but Madinah 1441. Train with --cap-none 0, one seed at a time.'))
out = B / 'multiprint_crops_v8.npz'
np.savez_compressed(out, pixels=pixels, y=labels.astype(np.int8), groups=np.asarray([str(v) for v in groups], dtype='<U24'),
                    meta=np.asarray(json.dumps(meta, ensure_ascii=False)))
c = collections.Counter(labels.tolist())
print('v8', len(labels), {CLASSES[k]: v for k, v in sorted(c.items())}, 'MB', round(out.stat().st_size / 1e6, 1))
