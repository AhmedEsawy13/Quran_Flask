"""Run several glyph models over the finished Mesaha pages and store every mark with its confidence.

    PYTHONPATH=. python3 -m pipeline.cv_waqf.mesaha_review.run_models
"""
import json, sys, time
from pathlib import Path
from pipeline.cv_waqf.run_page import detect_page
HERE = Path(__file__).resolve().parent            # the code
DATA = Path(__file__).resolve().parents[3] / 'artifacts' / 'cv-waqf' / 'mesaha-selflearn'   # data written by a run
DATA.mkdir(parents=True, exist_ok=True)
ED = 'المساحة'
def ensure_old_multiprint():
    """The Bahrain+Qatar model that shipped before the 3-print one: a third, independent vote."""
    import subprocess

    if (DATA / 'old_multiprint.onnx').is_file():
        return
    for name, target in (('waqf_glyph_multiprint.onnx', 'old_multiprint.onnx'),
                         ('waqf_glyph_multiprint_gate.onnx', 'old_multiprint_gate.onnx'),
                         ('waqf_glyph_multiprint_gate.json', 'old_multiprint_gate.json'),
                         ('waqf_glyph_multiprint.json', 'old_multiprint.json')):
        blob = subprocess.check_output(['git', 'show', f'7f491c8:models/{name}'])
        if target == 'old_multiprint.json':
            blob = blob.replace(b'waqf_glyph_multiprint_gate.onnx', b'old_multiprint_gate.onnx')
        (DATA / target).write_bytes(blob)


ensure_old_multiprint()
MODELS = {
    'multiprint3': Path('models/waqf_glyph_multiprint.onnx'),   # Bahrain+Qatar+Kuwait (also Kuwait's own)
    'bahrain': Path('models/waqf_glyph_bahrain.onnx'),
    'multiprint2': DATA / 'old_multiprint.onnx',                # the earlier Bahrain+Qatar model
}
PAGES = list(range(4, 135))
out = {}
t0 = time.time()
for name, path in MODELS.items():
    for prior in (False, True):
        key = f'{name}|prior={int(prior)}'
        res = {}
        for page in PAGES:
            r = detect_page(ED, page, min_conf=0.30, model_path=path, azhar_prior=prior)
            res[page] = [{'word_key': m.get('word_key'), 'symbol': m.get('symbol'), 'conf': round(float(m.get('confidence') or 0), 4),
                          'text': m.get('text') or m.get('word_text') or '', 'box': m.get('box')} for m in (r.get('marks') or []) if m.get('word_key')]
        out[key] = res
        print(key, 'marks', sum(len(v) for v in res.values()), f'{time.time()-t0:.0f}s', flush=True)
(DATA / 'model_marks.json').write_text(json.dumps(out, ensure_ascii=False), encoding='utf-8')
