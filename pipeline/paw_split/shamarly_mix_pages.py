"""Stage 1 of the layout x glyphs x waqf prototype: an Old Madinah 1405 page (line breaks) as plain data, with each
word's Shamarly key (surah:ayah:position, the key of its glyph in the Shamarly SVGs) and the sign a chosen print's
waqf column puts on it.

    SUPABASE_URL= SUPABASE_SERVICE_ROLE_KEY= FLASK_SKIP_DOTENV=1 .venv/bin/python pipeline/paw_split/shamarly_mix_pages.py \
        --layout qpc-v1 --waqf قطر 3 100 250  ->  artifacts/shamarly-qvp/mix/layout-NNN.json

Stage 2 (shamarly_mix_render.py, ShemrlyMushaf venv) draws the page.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
OUT = ROOT / 'artifacts' / 'shamarly-qvp' / 'mix'


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--layout', default='qpc-v1', choices=['qpc-v1'])
    ap.add_argument('--waqf', default='قطر')
    ap.add_argument('pages', nargs='+', type=int)
    args = ap.parse_args()
    import app as quran_app
    from modules import layouts
    client = quran_app.create_app({'core'}).test_client()
    word_map = layouts._get_dk_layout_word_map()
    script = sqlite3.connect(ROOT / 'data' / 'quran_script.db')
    text_of = {k: t for k, t in script.execute('SELECT word_key, text FROM words')}
    # layout tokens (qpc-layout ids: words + a verse-end token per ayah, the ۞ sign merged into the next word) and
    # script words (quran_script.db: words + the verse number, ۞ as a word of its own) line up one to one inside an
    # ayah once the lone ۞ is dropped; 5 of 6,236 ayahs differ in count and get no Shamarly key.
    layout_ayah, script_ayah = {}, {}
    for wid in word_map['ordered_ids']:
        tok = word_map['id2tok'].get(wid)
        if tok:
            layout_ayah.setdefault((tok['surah'], tok['ayah']), []).append(wid)
    for key, text in script.execute('SELECT word_key, text FROM words'):
        s_, a_, p_ = key.split(':')
        if text.strip() not in ('', '\u06de'):                     # the lone ۞
            script_ayah.setdefault((int(s_), int(a_)), []).append((int(p_), key))
    key_of_id, mismatched = {}, 0
    for ay, ids in layout_ayah.items():
        keys = [k for _p, k in sorted(script_ayah.get(ay, []))]
        if len(keys) == len(ids):
            key_of_id.update(zip(ids, keys))
        else:
            mismatched += 1
    print('ayahs without a one-to-one key:', mismatched)
    OUT.mkdir(parents=True, exist_ok=True)
    for page in args.pages:
        resp = client.get(f'/api/{args.layout}/page/{page}', query_string={'mushaf_version': args.waqf})
        payload = resp.get_json()
        lines = []
        for line in payload['lines']:
            words = []
            for w in line['words']:
                key = key_of_id.get(w['word_index'], '')
                words.append({'key': key, 'layout_text': w['text'], 'text': text_of.get(key, ''),
                              'sign': ((w.get('waqf_symbols') or [{}])[0].get('symbols', '') if isinstance(w.get('waqf_symbols'), list) else (w.get('waqf_symbols') or ''))})
            lines.append({'n': line['line_number'], 'type': line['line_type'], 'centered': bool(line['is_centered']),
                          'words': words})
        (OUT / f'layout-{page:03d}.json').write_text(json.dumps({'page': page, 'waqf': args.waqf, 'lines': lines},
                                                                ensure_ascii=False), encoding='utf-8')
        n = sum(len(l['words']) for l in lines)
        s = sum(1 for l in lines for w in l['words'] if w['sign'])
        miss = sum(1 for l in lines for w in l['words'] if not w['text'])
        print(f'page {page}: {len(lines)} lines, {n} words, {s} signs, {miss} without script text')


if __name__ == '__main__':
    main()
