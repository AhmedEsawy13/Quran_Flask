"""Build the review data: per finished Mesaha page, the models' proposed waqf marks + page words.

    PYTHONPATH=. python3 -m pipeline.cv_waqf.mesaha_review.build_review
Inputs: model_marks.json (run_models.py), reference_column.json (tiers.py).
"""
import collections, json
from pathlib import Path
import cv2
from pipeline.cv_waqf.config import EDITIONS
from pipeline.cv_waqf.pages import ensure_page_image
from pipeline.cv_waqf.preprocess import preprocess_page
from pipeline.cv_waqf.splits import mesaha_blind_pages
from pipeline.cv_waqf import layout_geo, geometry

HERE = Path(__file__).resolve().parent            # the code
DATA = Path(__file__).resolve().parents[3] / 'artifacts' / 'cv-waqf' / 'mesaha-selflearn'   # data written by a run
DATA.mkdir(parents=True, exist_ok=True)
M = json.loads((DATA / 'model_marks.json').read_text())
REF = json.loads((DATA / 'reference_column.json').read_text())
spec = EDITIONS['المساحة']
CFGS = ['multiprint3|prior=0', 'bahrain|prior=0', 'multiprint2|prior=0']
PRIOR = 'multiprint3|prior=1'
blind = set(mesaha_blind_pages())              # these stay unseen: they are labelled from scratch
(DATA / 'img').mkdir(exist_ok=True)

pages_out = []
for page in range(4, 135):
    if page in blind:
        continue
    prep = preprocess_page(cv2.imread(str(ensure_page_image(spec, page))), spec, page)
    ws = layout_geo.estimate_layout_words(spec, page, prep)
    cv2.imwrite(str(DATA / 'img' / f'p{page}.jpg'), prep.bgr, [cv2.IMWRITE_JPEG_QUALITY, 82])
    byid = {}
    for w in ws:
        h = max(12, w.y1 - w.y0)
        sx, sy = geometry.mark_seat_centre(w.x0, w.y0, w.y1)
        byid[w.word_key] = {'key': w.word_key, 'text': w.text, 'line': w.line_number,
                            'box': [int(w.x0), int(w.y0 + 0.45 * h), int(w.x1), int(w.y0 + 1.3 * h)],
                            'seat': [round(sx), round(sy)]}
    cands = collections.defaultdict(dict)
    for cfg in CFGS + [PRIOR]:
        for m in M[cfg].get(str(page), []):
            cands[m['word_key']][cfg] = (m['symbol'], m['conf'], m.get('box'))
    ref = REF.get(str(page), {})
    props = []
    for key in set(cands) | set(ref):
        if key not in byid:
            continue
        d = cands.get(key, {})
        syms = [d[c][0] for c in CFGS if c in d]
        top, votes = (collections.Counter(syms).most_common(1)[0] if syms else (None, 0))
        prior_pass = PRIOR in d
        col = ref.get(key)
        if votes < 2 and not prior_pass and col is None:
            continue                                   # a single model with nothing else behind it: noise
        symbol = top or (d[PRIOR][0] if prior_pass else col)
        agree = [d[c][1] for c in CFGS if c in d and d[c][0] == symbol]
        boxes = [d[c][2] for c in CFGS + [PRIOR] if c in d and d[c][0] == symbol and d[c][2]]
        mbox = boxes[0] if boxes else None             # where the printed mark was actually found
        accept = prior_pass and votes >= 2 and col == symbol
        why = ('3 نماذج' if votes == 3 else '2 من 3' if votes == 2 else '1 من 3' if votes == 1 else 'لا نموذج')
        props.append({**byid[key], 'symbol': symbol, 'conf': round(sum(agree) / len(agree), 3) if agree else 0.0,
                      'votes': votes, 'why': why, 'prior': prior_pass, 'column': col,
                      'default': 'accept' if accept else 'review',
                      'mbox': mbox,
                      'models': {c.split('|')[0]: d[c][:2] for c in CFGS if c in d}})
    props.sort(key=lambda p: (p['line'], -p['seat'][0]))
    pages_out.append({'page': page, 'w': int(prep.bgr.shape[1]), 'h': int(prep.bgr.shape[0]),
                      'words': sorted(byid.values(), key=lambda w: (w['line'], -w['box'][2])), 'proposals': props})
    print(page, 'proposals', len(props), 'auto-accept', sum(p['default'] == 'accept' for p in props), flush=True)
(DATA / 'pages.json').write_text(json.dumps(pages_out, ensure_ascii=False), encoding='utf-8')
tot = sum(len(p['proposals']) for p in pages_out)
acc = sum(sum(q['default'] == 'accept' for q in p['proposals']) for p in pages_out)
print('pages', len(pages_out), 'proposals', tot, 'auto-accepted', acc, 'to review', tot - acc, f'({(tot-acc)/len(pages_out):.1f}/page)')
