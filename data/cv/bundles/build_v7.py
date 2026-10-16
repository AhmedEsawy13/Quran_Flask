"""Build data/cv/bundles/multiprint_crops_v7.npz (2026-10-16).

    PYTHONPATH=. python3 artifacts/cv-waqf/bundle-v7/build_v7.py

v7 = v6 (v5 + Shamarly part) with three changes, all aimed at v6's two weaknesses (false marks on diacritics
and wasl, and قلى read as ج):
1. hard negatives: the detector windows of every reviewed card where v6 reported a mark that is not printed
   (book-audit tabs «maybe»/«add», verdict "column right": artifacts/cv-waqf/agent_review_verdicts.json), cut
   from the page exactly as the detector cuts them, labelled none, x4. Never from a held-out page, never from
   Madinah 1441 (the permanent unseen test print).
2. every قلى crop in a training group repeated once more (x2).
3. ordinary none thinned to NONE_KEEP so the bundle carries its own none:positive ratio; train with --cap-none 0
   so no hard negative is thrown away at training time.
"""
import collections
import json
import random
from pathlib import Path

import cv2
import numpy as np

from pipeline.cv_waqf import CLASSES
from pipeline.cv_waqf.candidates import Candidate, crop_candidate
from pipeline.cv_waqf.config import CROP_SIZE, EDITIONS
from pipeline.cv_waqf.pages import ensure_page_image
from pipeline.cv_waqf.preprocess import load_bgr, preprocess_page

ROOT = Path('.')
B = ROOT / 'data/cv/bundles'
A = ROOT / 'artifacts/cv-waqf'
SEED = 2032
NONE = CLASSES.index('none'); Q = CLASSES.index('ق')
NONE_KEEP = 40000
HARD_COPIES = 4


def read(path):
    with np.load(path, allow_pickle=False) as z:
        return z['pixels'], z['y'].astype(np.int64), z['groups'].astype(object), json.loads(str(z['meta']))


p5, y5, g5, m5 = read(B / 'multiprint_crops_v5.npz')
ps, ys, gs, ms = read(B / 'multiprint_crops_v6_shamarly_part.npz')
pixels, y, groups = np.concatenate([p5, ps]), np.concatenate([y5, ys]), np.concatenate([g5, gs])
assert len(y) == ms['expected_total']
val = set(m5['validation_groups']) | set(ms['validation_groups'])
print('v6', len(y), dict(collections.Counter(y.tolist())))

# --- held-out pages, per edition id
held = collections.defaultdict(set)
for v, key, eid in (('v4', 'bahrain_heldout_all', 'bahrain'), ('v4', 'qatar_holdout_50', 'qatar'),
                    ('v4', 'kuwait_holdout_100', 'kuwait'), ('v5', 'madinah_1405_holdout_100', 'madinah_1405'),
                    ('v6', 'shamarly_holdout_100', 'shamarly')):
    held[eid] |= set(json.loads((A / f'bundle-{v}' / 'pages.json').read_text())[key])

# --- 1. hard negatives from the reviewed cards
verdicts = json.loads((A / 'agent_review_verdicts.json').read_text())
by_id = {spec.id: name for name, spec in EDITIONS.items()}
hard_p, hard_g, skipped = [], [], collections.Counter()
for eid, cards in verdicts.items():
    if eid == 'madinah_1441':
        continue
    edition = by_id[eid]; spec = EDITIONS[edition]
    want = collections.defaultdict(list)
    for c in cards:
        if c['choice'] != 'db' or c['tab'] not in ('maybe', 'add'):
            continue
        if c.get('cv') == 'س':     # the small س reading note looks exactly like a sakta: keep the rare class safe
            skipped['س look-alike'] += 1; continue
        if c['page'] in held[eid]:
            skipped['held-out page'] += 1; continue
        if f'{eid}:p{c["page"]:04d}' in val:
            skipped['validation page'] += 1; continue
        want[c['page']].append(c['word_key'])
    boxes = {}
    for line in open(A / f'{eid}-audit' / 'pages.jsonl', encoding='utf-8'):
        r = json.loads(line)
        for it in r['items']:
            if it['kind'] == 'not_in_db' and it['word_key'] in want.get(r['page'], ()):
                boxes[(r['page'], it['word_key'])] = it['box']
    for page in sorted(want):
        prep = preprocess_page(load_bgr(ensure_page_image(spec, page)), spec, page=page)
        for key in want[page]:
            box = boxes.get((page, key))
            if box is None:
                skipped['no box'] += 1; continue
            x0, y0, x1, y1 = box
            crop = crop_candidate(prep.gray, Candidate(x0, y0, x1 - x0, y1 - y0, (x1 - x0) * (y1 - y0)), size=CROP_SIZE)
            hard_p.append(crop); hard_g.append(f'{eid}:p{page:04d}')
    print(eid, 'hard negatives', sum(1 for g in hard_g if g.startswith(eid + ':')))
print('skipped', dict(skipped))
# bundle pixels are the crop itself (white background), flattened: rint((1 - x) * 255) with x = 1 - img / 255
hard_px = np.stack(hard_p).astype(np.uint8).reshape(len(hard_p), -1)
assert hard_px.shape[1:] == pixels.shape[1:], (hard_px.shape, pixels.shape)

# --- 3. thin ordinary none (before adding hard negatives, so none of those is thinned)
rng = random.Random(SEED)
none_idx = np.flatnonzero(y == NONE).tolist()
keep_none = set(rng.sample(none_idx, NONE_KEEP))
sel = np.asarray([i for i in range(len(y)) if y[i] != NONE or i in keep_none])
pixels, y, groups = pixels[sel], y[sel], groups[sel]

# --- 2. قلى once more, training groups only
q_rows = np.asarray([i for i in np.flatnonzero(y == Q) if str(groups[i]) not in val])
pixels = np.concatenate([pixels, pixels[q_rows]]); y = np.concatenate([y, y[q_rows]]); groups = np.concatenate([groups, groups[q_rows]])

rep = np.repeat(np.arange(len(hard_px)), HARD_COPIES)
pixels = np.concatenate([pixels, hard_px[rep]]); y = np.concatenate([y, np.full(len(rep), NONE)])
groups = np.concatenate([groups, np.asarray(hard_g, dtype=object)[rep]])

meta = dict(m5, validation_groups=sorted(val), note=(
    'v7 (2026-10-16): v6 + hard negatives (reviewed v6 false marks, x4, never held-out pages or Madinah 1441) '
    '+ قلى x2 in training groups; ordinary none thinned to 40000. Train with --cap-none 0.'))
meta.pop('expected_total', None)
out = B / 'multiprint_crops_v7.npz'
np.savez_compressed(out, pixels=pixels, y=y.astype(np.int8), groups=np.asarray([str(v) for v in groups], dtype='<U24'),
                    meta=np.asarray(json.dumps(meta, ensure_ascii=False)))
c = collections.Counter(y.tolist())
print('v7', len(y), {CLASSES[k]: v for k, v in sorted(c.items())}, 'positives', len(y) - c[NONE],
      'MB', round(out.stat().st_size / 1e6, 1))
