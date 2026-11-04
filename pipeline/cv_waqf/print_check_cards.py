"""Review cards for the Qatar / Kuwait / Bahrain seats left open by the انفرادات eye review (2026-11-04):
3 seats where the column looks wrong and 9 unsure ones. Each card is a two-line crop of the print's own scan
with the word underlined. Shown in the Mesaha review page (/mushaf-editor/mesaha-waqf, set
mesaha-waqf-prints-check); decisions are saved per print under «<print> · فحص». The card's «model» is the
sign the column has now, so accepting a card keeps the column.

    python3 pipeline/cv_waqf/print_check_cards.py      # reads seats.json, writes data.json + cards/
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from pipeline.cv_waqf.config import EDITIONS  # noqa: E402
from pipeline.cv_waqf.layout_geo import estimate_layout_words  # noqa: E402
from pipeline.cv_waqf.pages import ensure_page_image  # noqa: E402
from pipeline.cv_waqf.preprocess import load_bgr, preprocess_page  # noqa: E402

SET = ROOT / 'data' / 'mesaha-waqf' / 'mesaha-waqf-prints-check'
NOTE = ('مواضع قطر والكويت والبحرين التي بقيت بعد مراجعة الانفرادات: ٣ يبدو فيها العمود خطأ و٩ غير محسومة. '
        '«النموذج» هنا = علامة العمود الآن؛ «اعتماد الكل» يُبقي العمود كما هو. اختر المطبوع على الكلمة المسطّرة.')
norm = lambda t: re.sub(r'[^ء-ي]', '', (t or '').replace('ٱ', 'ا'))


def main() -> int:
    seats = json.loads((SET / 'seats.json').read_text(encoding='utf-8'))
    (SET / 'cards').mkdir(parents=True, exist_ok=True)
    cards = []
    for x in seats:
        spec = EDITIONS[x['print']]
        s, a, n = map(int, x['key'].split(':'))
        page = x['page']
        img_path = ensure_page_image(spec, page)
        words = estimate_layout_words(spec, page, preprocess_page(load_bgr(img_path).copy(), spec, page=page))
        same = [w for w in words if (w.surah, w.ayah) == (s, a)]
        exact = [w for w in same if w.word_key == x['key']]
        w = exact[0] if exact and norm(exact[0].text)[:3] == norm(x['word'])[:3] else \
            min((v for v in same if norm(v.text) == norm(x['word'])), key=lambda v: abs(int(v.word_key.split(':')[2]) - n),
                default=exact[0] if exact else None)
        if w is None:
            print('not located:', x['print'], x['key'])
            continue
        im = Image.open(img_path).convert('RGB')
        h = w.y1 - w.y0
        ImageDraw.Draw(im).line([(w.x0, w.y1 + 3), (w.x1, w.y1 + 3)], fill=(0, 120, 255), width=3)
        crop = im.crop((max(0, int(w.x0 - 3 * h)), max(0, int(w.y0 - 1.9 * h)),
                        min(im.width, int(w.x1 + 3 * h)), min(im.height, int(w.y1 + 0.5 * h))))
        crop = crop.resize((380, max(1, round(crop.height * 380 / crop.width))), Image.LANCZOS)
        wid = s * 1_000_000 + a * 1_000 + n                      # unique per print: the decision's word_id
        cid = f'{page:03d}-{wid}'
        crop.save(SET / 'cards' / f'{cid}.jpg', quality=80)
        hint = {'المصحف': x['print'], 'العمود الآن': x['column'] or '—'}
        if x.get('proposed') is not None:
            hint['اقتراحي'] = x['proposed'] or '—'
        hint.update({f'مصاحف أخرى ({k})': v for k, v in x['others'].items()})
        cards.append({'id': cid, 'page': page, 'word_index': wid, 'key': x['key'], 'text': x['word'],
                      'group': 'B' if x.get('proposed') is not None else 'N', 'model': x['column'] or None,
                      'conf': None, 'hint': hint, 'suggest': x.get('proposed', x['column']) or '',
                      'print': x['print'], 'note': x['note']})
    data = {'pages': sorted({c['page'] for c in cards}), 'note': NOTE, 'cards': cards, 'a_sample': [],
            'decision_edition_by_print': True}
    (SET / 'data.json').write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding='utf-8')
    print(len(cards), 'cards')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
