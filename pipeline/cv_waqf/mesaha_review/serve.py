"""Review server for the Mesaha waqf proposals. Every decision is written to disk at once.

    python3 -m pipeline.cv_waqf.mesaha_review.serve        # http://127.0.0.1:5004
"""
import json, os, threading, time
from pathlib import Path
from flask import Flask, jsonify, request, send_from_directory

from pipeline.cv_waqf.mesaha_review.cuts import apply_cuts, cut_key, neighbours, valid_x

HERE = Path(__file__).resolve().parent            # the code
DATA = Path(os.environ.get('MESAHA_REVIEW_DATA') or Path(__file__).resolve().parents[3] / 'artifacts' / 'cv-waqf' / 'mesaha-selflearn')   # data written by a run
DATA.mkdir(parents=True, exist_ok=True)
VERDICTS, DONE, LOG, EXPORT, RELINKS, POSITIONS, CUTS = (DATA / n for n in ('verdicts.json', 'done.json', 'verdicts.log.jsonl', 'reviewed_marks.json', 'relinks.json', 'positions.json', 'cuts.json'))
SYMBOLS = ['ج', 'ق', 'ص', 'م', 'لا', 'س', 'ع']
lock = threading.Lock()
app = Flask(__name__, static_folder=None)

def read(path, default):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except FileNotFoundError:
        return default

def write(path, data):
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding='utf-8')
    os.replace(tmp, path)

def pages():
    return read(DATA / 'pages.json', [])

def cut_pages():
    """The pages with the reviewer's hand-set cuts applied (the boxes the tool shows)."""
    return apply_cuts(pages(), read(CUTS, {}))

def final_marks(done_pages, verdicts):
    """The reviewed marks of the pages the reviewer finished.

    A proposal takes the reviewer's verdict; with none it keeps its default (auto-accepted
    stays a mark, one left for review is NOT a mark). Added marks are verdicts on words that
    were never proposed. '-' is an explicit "not a mark".
    """
    out = {}
    for p in pages():
        if p['page'] not in done_pages:
            continue
        marks = {}
        for pr in p['proposals']:
            v = verdicts.get(f"{p['page']}:{pr['key']}")
            if v is None:
                if pr['default'] == 'accept':
                    marks[pr['key']] = pr['symbol']
            elif v != '-':
                marks[pr['key']] = v
        words = {w['key'] for w in p['words']}
        for k, v in verdicts.items():
            pg, _, key = k.partition(':')
            if pg == str(p['page']) and key in words and v != '-' and key not in marks:
                marks[key] = v
        out[str(p['page'])] = marks
    return out

def write_export():
    done, verdicts = set(read(DONE, [])), read(VERDICTS, {})
    marks = final_marks(done, verdicts)
    # Where the reviewer put the ring (the printed mark's true position), for the marks that survived.
    pos = read(POSITIONS, {})
    positions = {pg: {k: pos[f'{pg}:{k}'] for k in ms if f'{pg}:{k}' in pos} for pg, ms in marks.items()}
    write(EXPORT, {'pages': sorted(done), 'marks': marks, 'positions': positions, 'relinks': read(RELINKS, {}),
                   'cuts': read(CUTS, {}),
                   'updated_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())})
    return marks

@app.get('/')
def index():
    return send_from_directory(HERE, 'index.html')

@app.get('/pages.json')
def pages_json():
    return jsonify(cut_pages())

@app.get('/img/<path:name>')
def img(name):
    return send_from_directory(DATA / 'img', name)

@app.get('/api/state')
def state():
    return jsonify({'verdicts': read(VERDICTS, {}), 'done': read(DONE, []), 'symbols': SYMBOLS,
                    'relinks': read(RELINKS, {}), 'positions': read(POSITIONS, {}), 'cuts': read(CUTS, {})})

@app.post('/api/verdict')
def verdict():
    b = request.get_json(force=True) or {}
    try:
        page, key, sym = int(b['page']), str(b['key']), b.get('symbol')
    except (KeyError, TypeError, ValueError):
        return jsonify({'error': 'bad request'}), 400
    if sym not in SYMBOLS + ['-', None]:
        return jsonify({'error': 'bad symbol'}), 400
    with lock:
        v = read(VERDICTS, {})
        if sym is None:
            v.pop(f'{page}:{key}', None)
        else:
            v[f'{page}:{key}'] = sym
        write(VERDICTS, v)
        with LOG.open('a', encoding='utf-8') as f:
            f.write(json.dumps({'t': time.time(), 'page': page, 'key': key, 'symbol': sym}, ensure_ascii=False) + '\n')
        write_export()
    return jsonify({'ok': True, 'total': len(v)})

@app.post('/api/relink')
def relink():
    """Move a mark to another word: the mark is right, the word it was linked to is not.

    One atomic write: the old word becomes "not a mark", the new word carries the symbol, and the
    move is recorded (``relinks.json``: how often, and from which word, the attachment was off).
    ``undo`` puts both words back to undecided.
    """
    b = request.get_json(force=True) or {}
    try:
        page, src, dst = int(b['page']), str(b['from']), str(b['to'])
    except (KeyError, TypeError, ValueError):
        return jsonify({'error': 'bad request'}), 400
    sym = b.get('symbol')
    undo = bool(b.get('undo'))
    if not undo and sym not in SYMBOLS:
        return jsonify({'error': 'bad symbol'}), 400
    if src == dst:
        return jsonify({'error': 'same word'}), 400
    words = {w['key'] for p in pages() if p['page'] == page for w in p['words']}
    if src not in words or dst not in words:
        return jsonify({'error': 'unknown word'}), 400
    pos = b.get('pos')
    if pos is not None and not (isinstance(pos, list) and len(pos) == 2 and all(isinstance(n, (int, float)) for n in pos)):
        return jsonify({'error': 'bad position'}), 400
    with lock:
        v, r, ps = read(VERDICTS, {}), read(RELINKS, {}), read(POSITIONS, {})
        if undo:
            v.pop(f'{page}:{src}', None)
            v.pop(f'{page}:{dst}', None)
            r.pop(f'{page}:{dst}', None)
            ps.pop(f'{page}:{dst}', None)
        else:
            v[f'{page}:{src}'] = '-'
            v[f'{page}:{dst}'] = sym
            if pos is not None:
                ps[f'{page}:{dst}'] = [round(pos[0], 1), round(pos[1], 1)]
            ps.pop(f'{page}:{src}', None)
            r[f'{page}:{dst}'] = {'from': src, 'symbol': sym, 't': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}
        write(VERDICTS, v)
        write(RELINKS, r)
        write(POSITIONS, ps)
        with LOG.open('a', encoding='utf-8') as f:
            f.write(json.dumps({'t': time.time(), 'page': page, 'relink': {'from': src, 'to': dst, 'symbol': sym, 'undo': undo}},
                               ensure_ascii=False) + '\n')
        write_export()
    return jsonify({'ok': True, 'verdicts': v, 'relinks': r, 'positions': ps})


@app.post('/api/position')
def position():
    """Where the reviewer put the ring: the printed mark's true position (``pos`` null clears it)."""
    b = request.get_json(force=True) or {}
    try:
        page, key = int(b['page']), str(b['key'])
    except (KeyError, TypeError, ValueError):
        return jsonify({'error': 'bad request'}), 400
    pos = b.get('pos')
    if pos is not None and not (isinstance(pos, list) and len(pos) == 2 and all(isinstance(n, (int, float)) for n in pos)):
        return jsonify({'error': 'bad position'}), 400
    if not any(key == w['key'] for p in pages() if p['page'] == page for w in p['words']):
        return jsonify({'error': 'unknown word'}), 400
    with lock:
        ps = read(POSITIONS, {})
        if pos is None:
            ps.pop(f'{page}:{key}', None)
        else:
            ps[f'{page}:{key}'] = [round(pos[0], 1), round(pos[1], 1)]
        write(POSITIONS, ps)
        write_export()
    return jsonify({'ok': True, 'positions': ps})


@app.post('/api/cut')
def cut():
    """Put the cut between two neighbouring words of a row at ``x`` (page pixels); ``undo`` gives it back.

    Stored in ``cuts.json`` with the x the cutter had chosen (``was``), so the labels also measure the cutter.
    The reply is the page with the cut applied.
    """
    b = request.get_json(force=True) or {}
    try:
        page, right_key, left_key = int(b['page']), str(b['right']), str(b['left'])
    except (KeyError, TypeError, ValueError):
        return jsonify({'error': 'bad request'}), 400
    undo = bool(b.get('undo'))
    x = b.get('x')
    if not undo and not isinstance(x, (int, float)):
        return jsonify({'error': 'bad position'}), 400
    raw = next((p for p in pages() if p['page'] == page), None)
    if raw is None or neighbours(raw['words'], right_key, left_key) is None:
        return jsonify({'error': 'unknown cut'}), 400
    key = cut_key(page, right_key, left_key)
    with lock:
        cuts = read(CUTS, {})
        if undo:
            cuts.pop(key, None)
        else:
            current = apply_cuts([raw], {k: v for k, v in cuts.items() if k != key})[0]
            right, left = neighbours(current['words'], right_key, left_key)
            if not valid_x(right, left, float(x)):
                return jsonify({'error': 'cut outside the two words'}), 400
            first = cuts.get(key, {})
            was = first.get('was', raw_cut(raw, right_key, left_key))
            # how doubtful the cutter was about this cut when it was first corrected (kept through later edits)
            doubt = first.get('doubt', round(max(float(right.get('dl', 0)), float(left.get('dr', 0))), 2))
            cuts[key] = {'x': round(float(x), 1), 'was': was, 'doubt': doubt,
                         't': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}
        write(CUTS, cuts)
        with LOG.open('a', encoding='utf-8') as f:
            f.write(json.dumps({'t': time.time(), 'page': page, 'cut': {'right': right_key, 'left': left_key, 'x': x, 'undo': undo}},
                               ensure_ascii=False) + '\n')
        write_export()
    return jsonify({'ok': True, 'cuts': cuts, 'page': apply_cuts([raw], cuts)[0]})


def raw_cut(page: dict, right_key: str, left_key: str) -> float:
    """Where the cutter put the cut (the left edge of the word on the right)."""
    right, _left = neighbours(page['words'], right_key, left_key)
    return right['box'][0]


@app.post('/api/done')
def done():
    b = request.get_json(force=True) or {}
    try:
        page = int(b['page'])
    except (KeyError, TypeError, ValueError):
        return jsonify({'error': 'bad request'}), 400
    with lock:
        d = set(read(DONE, []))
        d.add(page) if b.get('done') else d.discard(page)
        write(DONE, sorted(d))
        marks = write_export()
    return jsonify({'ok': True, 'done': sorted(d), 'marks_on_done_pages': sum(len(m) for m in marks.values())})

if __name__ == '__main__':
    app.run(port=int(os.environ.get('MESAHA_REVIEW_PORT') or 5004), debug=False, use_reloader=False)
