import json, collections, cv2
from pathlib import Path
from pipeline.cv_waqf.config import EDITIONS
from pipeline.cv_waqf.marks import edition_marks_for_ayahs
from pipeline.cv_waqf.pages import ensure_page_image
from pipeline.cv_waqf.preprocess import preprocess_page
from pipeline.cv_waqf import layout_geo
from pipeline.cv_waqf.mesaha_review.cuts import use_hand_cuts
HERE = Path(__file__).resolve().parent            # the code
DATA = Path(__file__).resolve().parents[3] / 'artifacts' / 'cv-waqf' / 'mesaha-selflearn'   # data written by a run
DATA.mkdir(parents=True, exist_ok=True)
M = json.loads((DATA / 'model_marks.json').read_text())
spec = EDITIONS['المساحة']
use_hand_cuts(DATA)
ref = {}      # page -> {word_key: symbol}  (Shemrly column, restricted to the page)
for page in range(4, 135):
    prep = preprocess_page(cv2.imread(str(ensure_page_image(spec, page))), spec, page)
    ws = layout_geo.estimate_layout_words(spec, page, prep)
    ayahs = sorted({(w.surah, w.ayah) for w in ws if w.surah and w.ayah})
    db = edition_marks_for_ayahs('المساحة', ayahs, spec.script_db)
    byid = {w.word_id: w.word_key for w in ws}
    ref[page] = {byid[k[2]]: v for k, v in db.items() if k[2] in byid and v != 'ركوع'}
(DATA / 'reference_column.json').write_text(json.dumps(ref, ensure_ascii=False))
print('reference marks on pages 4-134:', sum(len(v) for v in ref.values()))
cfgs = ['multiprint3|prior=0', 'bahrain|prior=0', 'multiprint2|prior=0']
rows = {}   # (page, key) -> {cfg: (sym, conf)}
for cfg in cfgs + ['multiprint3|prior=1']:
    for page, marks in M[cfg].items():
        for m in marks:
            rows.setdefault((int(page), m['word_key']), {})[cfg] = (m['symbol'], m['conf'])
tiers = collections.defaultdict(lambda: [0, 0, 0])   # tier -> [n, ref has a mark here, ref same symbol]
for (page, key), d in rows.items():
    syms = [d[c][0] for c in cfgs if c in d]
    top, votes = collections.Counter(syms).most_common(1)[0]
    agree = [d[c][1] for c in cfgs if c in d and d[c][0] == top]
    minc = min(agree); prior = 'multiprint3|prior=1' in d
    if votes == 3 and minc >= 0.9: t = 'A: all 3 models agree, each >=0.90'
    elif votes == 3: t = 'B: all 3 agree, some <0.90'
    elif votes == 2 and min(agree) >= 0.9: t = 'C: 2 of 3 agree, both >=0.90'
    elif votes == 2: t = 'D: 2 of 3 agree, weaker'
    else: t = 'E: a single model'
    r = ref[page].get(key)
    x = tiers[(t, prior)]; x[0] += 1; x[1] += r is not None; x[2] += (r == top)
tot = sum(v[0] for v in tiers.values())
print('candidate marks (word,symbol) across the 3 no-prior models:', tot, '| per page', round(tot / 131, 1))
for (t, prior), (n, h, s) in sorted(tiers.items()):
    print(f'{t:44s} prior-pass={str(prior):5s} n={n:5d}  column has a mark {100*h/n:5.1f}%  same symbol {100*s/n:5.1f}%')
refn = sum(len(v) for v in ref.values())
cov = sum(1 for page, d in ref.items() for k in d if (page, k) in rows)
print('column marks seen by at least one model:', cov, '/', refn)
