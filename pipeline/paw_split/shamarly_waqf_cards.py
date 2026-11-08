"""Review cards for the waqf signs the Shamarly vector builder could not hide (data/shamarly-waqf/<set>/).

The builder (shamarly_qvp_svg.py, run with SIGN_AUDIT=1) tags the signs of the «الشمرلي» column and the
detector's marks so the reader can hide them. Two kinds of sign it can miss, and each becomes a card:

  A  a column sign whose outlines it did not find (the card shows the word, with room above it);
  B  a sign-sized group of outlines the classifier reads as a sign (p >= 0.9) although neither the column nor
     the detector has it, and no tagged sign is within 8 pt (most are letter pieces: the card says so).

Decisions are made in the app (/mushaf-editor/shamarly-waqf, modules/mesaha_waqf_review.py) and saved like the
Mesaha ones, under «الشمرلي · فحص»: the sign actually printed on the word ('' = none). Run with the
ShemrlyMushaf venv (pymupdf + PIL):

    SIGN_AUDIT=1 SHAMARLY_SVG_OUT=<dir> .../shamarly_qvp_svg.py <pages>      # SVGs + artifacts/shamarly-qvp/audit
    .../python pipeline/paw_split/shamarly_waqf_cards.py --svg-dir <dir> --pages-file pages.txt
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import sqlite3
from html import unescape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SHEMRLY = Path(os.environ.get('SHEMRLY_ROOT', Path.home() / 'Development' / 'ShemrlyMushaf'))
PDF = SHEMRLY / 'BOOK_27111_1.pdf'
AUDIT = ROOT / 'artifacts' / 'shamarly-qvp' / 'audit'
WAQF = ROOT / 'artifacts' / 'shamarly-qvp' / 'waqf'
OUT_ROOT = ROOT / 'data' / 'shamarly-waqf'
SET_NAME = 'shamarly-waqf-missed'
HINT_COLUMNS = ('المدينة الجديد', 'المدينة القديم', 'الأزهر', 'الشمرلي')
MIN_P = 0.9          # a B card's classifier probability
FAR_PT = 8.0         # a B card sits at least this far from every tagged sign
SCALE, MARGIN, MAX_W = 7, 16, 560

_WORD = re.compile(r'<g class="word" data-word-key="([^"]+)"[^>]*data-rasm-uthmani="([^"]*)"[^>]*>(.*?)</g>', re.S)
_LINE = re.compile(r'<g class="line" data-line="(\d+)">')
_PATH = re.compile(r'<path ([^>]*?) d="([^"]+)"')
_NUM = re.compile(r'-?\d+\.?\d*')


def _bbox(d: str):
    nums = [float(v) for v in _NUM.findall(d)]
    xs, ys = nums[0::2], nums[1::2]
    return min(xs), min(ys), max(xs), max(ys)


def words_of(svg: str) -> dict[str, dict]:
    """{word key: {text, line, box, signed}} from a built page SVG (control points bound the outline)."""
    out, lines = {}, [(m.start(), int(m.group(1))) for m in _LINE.finditer(svg)]
    for m in _WORD.finditer(svg):
        boxes, signed = [], False
        for p in _PATH.finditer(m.group(3)):
            signed = signed or 'data-mark-family="waqf"' in p.group(1)
            boxes.append(_bbox(p.group(2)))
        if not boxes:
            continue
        line = max((n for pos, n in lines if pos < m.start()), default=0)
        out[m.group(1)] = {'text': unescape(m.group(2)), 'line': line, 'signed': signed,
                           'box': (min(b[0] for b in boxes), min(b[1] for b in boxes),
                                   max(b[2] for b in boxes), max(b[3] for b in boxes))}
    return out


def gap(a, b) -> float:
    dx = max(a[0] - b[2], b[0] - a[2], 0)
    dy = max(a[1] - b[3], b[1] - a[3], 0)
    return (dx * dx + dy * dy) ** 0.5


def crop_jpeg(page, box, color, extra=()) -> bytes:
    import fitz
    from PIL import Image, ImageDraw
    r = fitz.Rect(box[0] - MARGIN - 8, box[1] - MARGIN, box[2] + MARGIN + 8, box[3] + MARGIN)
    pix = page.get_pixmap(matrix=fitz.Matrix(SCALE, SCALE), clip=r)
    im = Image.frombytes('RGB', (pix.width, pix.height), pix.samples)
    d = ImageDraw.Draw(im)
    for b, c in [(box, color)] + list(extra):
        d.rectangle([(b[0] - r.x0) * SCALE, (b[1] - r.y0) * SCALE, (b[2] - r.x0) * SCALE, (b[3] - r.y0) * SCALE],
                    outline=c, width=3)
    if im.width > MAX_W:
        im = im.resize((MAX_W, round(im.height * MAX_W / im.width)), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, 'JPEG', quality=78, optimize=True)
    return buf.getvalue()


def main() -> None:
    import fitz
    ap = argparse.ArgumentParser()
    ap.add_argument('--svg-dir', required=True, type=Path)
    ap.add_argument('--pages-file', required=True, type=Path)
    args = ap.parse_args()
    pages = sorted(int(p) for p in args.pages_file.read_text().split())

    sdb = sqlite3.connect(ROOT / 'data' / 'quran_script.db')
    index = {k: i for i, k in sdb.execute('SELECT word_index, word_key FROM words')}
    wdb = sqlite3.connect(ROOT / 'data' / 'mushaf_waqf.db')
    cols = ', '.join(f'"{c}"' for c in HINT_COLUMNS)

    def hint(key: str) -> dict:
        s, a, w = key.split(':')
        row = wdb.execute(f'SELECT {cols} FROM waqf WHERE السورة=? AND الآية=? AND word_index=?',
                          (int(s), int(a), int(w))).fetchone()
        return {c: v for c, v in zip(HINT_COLUMNS, row or ()) if v}

    doc = fitz.open(PDF)
    svgs: dict[int, dict] = {}

    def page_words(n: int) -> dict:
        if n not in svgs:
            p = args.svg_dir / f'{n:03d}.svg'
            svgs[n] = words_of(p.read_text(encoding='utf-8')) if p.exists() else {}
        return svgs[n]

    out = OUT_ROOT / SET_NAME
    (out / 'cards').mkdir(parents=True, exist_ok=True)
    for old in (out / 'cards').glob('*.jpg'):
        old.unlink()
    cards, used, dropped = [], set(), {'collision': 0, 'no_word': 0}

    def add(card: dict, jpg: bytes) -> None:
        (out / 'cards' / f"{card['id']}.jpg").write_bytes(jpg)
        cards.append(card)

    a_cards = []
    for n in pages:
        col = json.loads((WAQF / f'{n:03d}.column.json').read_text(encoding='utf-8'))
        here = page_words(n)
        for key, sym in col.items():
            if key in here and here[key]['signed']:
                continue
            host = next(((m, page_words(m)[key]) for m in (n, n - 1, n + 1) if key in page_words(m)), None)
            if host is None or key not in index:
                dropped['no_word'] += 1
                continue
            a_cards.append((host[0], key, sym, host[1]))
    for page, key, sym, w in sorted(a_cards, key=lambda t: (t[0], index[t[1]])):
        b = w['box']
        card = {'id': f'{page:03d}-a{index[key]}', 'page': page, 'line': w['line'], 'word_index': index[key],
                'key': key, 'text': w['text'], 'group': 'A', 'model': sym, 'conf': None, 'hint': hint(key),
                'suggest': sym}
        used.add((page, index[key]))
        add(card, crop_jpeg(doc[page - 1], (b[0], b[1] - 22, b[2], b[3]), (220, 30, 30)))

    for n in pages:
        audit = json.loads((AUDIT / f'{n:03d}.json').read_text(encoding='utf-8'))
        here, seen = page_words(n), []
        for x in sorted(audit['unclaimed'], key=lambda t: -t['p']):
            if x['p'] < MIN_P or any(abs(x['box'][0] - s[0]) < 6 and abs(x['box'][1] - s[1]) < 6 for s in seen):
                continue
            seen.append(x['box'])
            if min((gap(x['box'], t['box']) for t in audit['tagged']), default=99) <= FAR_PT:
                continue
            key = x['word']
            if key not in index:
                dropped['no_word'] += 1
                continue
            if (n, index[key]) in used:
                dropped['collision'] += 1
                continue
            used.add((n, index[key]))
            card = {'id': f'{n:03d}-b{index[key]}-{len(cards)}', 'page': n, 'line': x['line'],
                    'word_index': index[key], 'key': key, 'text': here.get(key, {}).get('text', ''),
                    'group': 'B', 'model': x['sym'], 'conf': x['p'], 'hint': hint(key), 'suggest': ''}
            tagged = [(t['box'], (30, 170, 60)) for t in audit['tagged']]
            add(card, crop_jpeg(doc[n - 1], x['box'], (220, 30, 30), tagged))

    n_a = sum(1 for c in cards if c['group'] == 'A')
    data = {
        'title': 'علامات الشمرلي الناقصة',
        'decision_edition': 'الشمرلي · فحص',
        'no_accept': True,      # a candidate's reading is the classifier's, not a sign: no "accept all"
        'pages': sorted({c['page'] for c in cards}),
        'groups': {
            'A': {'name': '(أ) علامات العمود غير الموجودة',
                  'note': 'علامة في عمود الشمرلي لم يجد المُنشئ حبرها. المربع الأحمر حول الكلمة: اختر العلامة المطبوعة فوقها فعلًا، أو «لا شيء».'},
            'B': {'name': '(ب) مرشّحون ليسوا في العمود',
                  'note': 'مجموعة حبر يقرؤها المصنِّف علامة وليست في العمود ولا عند الكاشف. المربع الأحمر هو المرشّح، والأخضر علامات مُعلَّمة. '
                          'الأغلب حروف أو شدّات: اختر «لا شيء» لها. الكلمة المذكورة أقرب كلمة إلى الحبر وقد تكون جارتها.'},
        },
        'note': f'بطاقات (ب) التي وقعت على كلمة بطاقة أخرى أُسقطت ({dropped["collision"]}).',
        'cards': cards,
    }
    (out / 'data.json').write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    print(f'{n_a} A + {len(cards) - n_a} B cards, dropped {dropped}')


if __name__ == '__main__':
    main()
