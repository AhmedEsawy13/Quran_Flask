"""Run a passage round (book → DB) with an OpenAI-compatible model instead of
Claude subagents. The model gets the same two tools the subagents used: the DB
rows for a span (show_rows.py) and a search of the book text.

    python3 pipeline/review/random_check/run_openai.py ROUND_DIR [--model M] [--jobs N]

The key comes from OPENAI_API_KEY (environment or a gitignored .env file);
OPENAI_BASE_URL overrides the endpoint. Each batchN.json in ROUND_DIR gets a
batchN_result.json in the INSTRUCTIONS_PASSAGES.md shape. Existing results are
skipped, so a failed run can be resumed.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).parent
SOURCES = {'muktafa': 'muktafa_dani_shamela26461.md', 'manar': 'manar_ashmuni_shamela6496.md',
           'nahhas': 'qatc_nahhas_sham19_20966.md', 'anbari': 'idah_anbari_sham19_14255.md'}


def env(name):
    if os.environ.get(name):
        return os.environ[name]
    for f in ('.env', '.env.local'):
        if Path(f).exists():
            for line in Path(f).read_text().splitlines():
                k, _, v = line.partition('=')
                if k.strip() == name:
                    return v.strip().strip('"\'')
    return None


KEY = env('OPENAI_API_KEY')
BASE = (env('OPENAI_BASE_URL') or 'https://api.openai.com/v1').rstrip('/')


def api(path, body=None):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode() if body else None,
                                 headers={'Authorization': f'Bearer {KEY}', 'Content-Type': 'application/json'})
    for attempt in range(6):          # dropped connections, rate limits and 5xx are retried
        try:
            with urllib.request.urlopen(req, timeout=600) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code != 429 and e.code < 500 or attempt == 5:
                raise
        except (urllib.error.URLError, ConnectionError, TimeoutError):
            if attempt == 5:
                raise
        time.sleep(5 * 2 ** attempt)


def show_rows(book, surah, first, last):
    last = min(int(last), int(first) + 40)
    out = subprocess.run([sys.executable, str(HERE / 'show_rows.py'), book, str(surah), str(first), str(last)],
                         capture_output=True, text=True, timeout=60)
    return (out.stdout + out.stderr)[:40000]


def search_book(book, pattern):
    lines = Path('pipeline/classical_sources', SOURCES[book]).read_text(encoding='utf-8').splitlines()
    try:
        rx = re.compile(pattern)
    except re.error:
        rx = re.compile(re.escape(pattern))
    hits = [f'{i + 1}: {ln[:600]}' for i, ln in enumerate(lines) if rx.search(ln)]
    return '\n'.join(hits[:25]) + (f'\n… {len(hits) - 25} more' if len(hits) > 25 else '') or 'no match'


TOOLS = [  # Responses API shape
    {'type': 'function', 'name': 'show_rows',
     'description': 'DB rows and 0-based numbered verse words for ayahs FIRST..LAST (max 40).',
     'parameters': {'type': 'object', 'required': ['surah', 'first', 'last'], 'additionalProperties': False,
                    'properties': {'surah': {'type': 'integer'}, 'first': {'type': 'integer'},
                                   'last': {'type': 'integer'}}}},
    {'type': 'function', 'name': 'search_book',
     'description': 'Regex search of this book; returns matching lines with line numbers.',
     'parameters': {'type': 'object', 'required': ['pattern'], 'additionalProperties': False,
                    'properties': {'pattern': {'type': 'string'}}}},
]


def instructions():
    parts = [(HERE / f).read_text(encoding='utf-8') for f in
             ('INSTRUCTIONS.md', 'INSTRUCTIONS_ATTRIBUTION.md', 'INSTRUCTIONS_WIDE.md', 'INSTRUCTIONS_PASSAGES.md')]
    return ('You review a classical waqf database against the book text. The four instruction files follow; '
            'ignore their references to files and scripts — use the tools show_rows and search_book instead. '
            'Return ONLY the JSON object for this one passage: '
            '{"book","surah","ayahs":[first,last],"rulings_in_text","matched","issues":[...]}.\n\n'
            + '\n\n---\n\n'.join(parts))


def review(model, passage, log):
    # /v1/responses: function tools work there with reasoning on (chat completions refuses them)
    items = [{'role': 'user', 'content': json.dumps(passage, ensure_ascii=False)}]
    for _ in range(30):
        r = api('/responses', {'model': model, 'instructions': instructions(), 'input': items,
                               'tools': TOOLS, 'store': False, 'include': ['reasoning.encrypted_content']})
        items += r['output']
        calls = [o for o in r['output'] if o['type'] == 'function_call']
        if not calls:
            text = ''.join(c.get('text', '') for o in r['output'] if o['type'] == 'message'
                           for c in o.get('content', []))
            j = json.loads(text[text.find('{'):text.rfind('}') + 1])
            return j['passages'][0] if 'passages' in j else j   # it sometimes wraps it
        for c in calls:
            a = json.loads(c['arguments'] or '{}')
            if c['name'] == 'show_rows':
                out = show_rows(passage['book'], a.get('surah', passage['surah']), a['first'], a['last'])
            else:
                out = search_book(passage['book'], a['pattern'])
            log.write(f"{c['name']} {a}\n")
            items.append({'type': 'function_call_output', 'call_id': c['call_id'], 'output': out})
    raise RuntimeError('no answer after 30 turns')


def run_batch(model, f):
    out = f.with_name(f.stem + '_result.json')
    if out.exists():
        return f'{f.name}: skipped (result exists)'
    res = []
    with open(f.with_name(f.stem + '_openai.log'), 'w', encoding='utf-8') as log:
        for p in json.loads(f.read_text(encoding='utf-8')):
            try:
                res.append(review(model, p, log))
            except (urllib.error.URLError, ConnectionError, TimeoutError, RuntimeError, ValueError, KeyError) as e:
                body = e.read().decode()[:300] if isinstance(e, urllib.error.HTTPError) else ''
                res.append({'book': p['book'], 'surah': p['surah'], 'error': f'{e} {body}'})
    out.write_text(json.dumps({'passages': res}, ensure_ascii=False, indent=1), encoding='utf-8')
    return f'{f.name}: {sum("error" not in r for r in res)}/{len(res)} passages'


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('round_dir')
    ap.add_argument('--model', default='gpt-6-luna')
    ap.add_argument('--jobs', type=int, default=6)
    ap.add_argument('--check', action='store_true', help='only check the key and that the model exists')
    a = ap.parse_args()
    if not KEY:
        sys.exit('OPENAI_API_KEY is not set (environment or .env)')
    ids = {m['id'] for m in api('/models')['data']}
    if a.model not in ids:
        sys.exit(f'model {a.model!r} not found; similar: {sorted(i for i in ids if "luna" in i or "gpt-6" in i)[:20]}')
    if a.check:
        sys.exit(f'ok: {a.model}')
    batches = sorted(Path(a.round_dir).glob('batch*.json'), key=lambda p: p.name)
    batches = [b for b in batches if re.fullmatch(r'batch\d+\.json', b.name)]
    with ThreadPoolExecutor(a.jobs) as ex:
        for msg in ex.map(lambda b: run_batch(a.model, b), batches):
            print(msg, flush=True)
