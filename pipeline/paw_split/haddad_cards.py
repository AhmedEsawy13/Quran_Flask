"""Review cards for «الكويت (الحداد)»: the seats where the sign read off the al-Haddad scan and the «الكويت»
column (which this print follows on 98.9% of shared signs) disagree, minus signs merely credited to the
neighbouring word. Shown in /mushaf-editor/mesaha-waqf (set mesaha-waqf-haddad); decisions are saved under
«الكويت (الحداد) · فحص». Groups: D = both mark, symbols differ; M = only the column marks (the reader saw
nothing); X = only the print (read with confidence >= 0.99). «النموذج» = the best guess: the column's sign for
D and M (the sample: the reader misses / misreads visible signs, e.g. 2:40:7, 2:87:8, 2:143:12), the read sign
for X (mixed: 2:130:13 real, 2:49:16 noise).

    python3 pipeline/paw_split/haddad_cards.py      # reads artifacts/haddad/cands.json (haddad_compare step)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from pipeline.paw_split.haddad_waqf import layout_keys, load_columns  # noqa: E402

SET = ROOT / 'data' / 'mesaha-waqf' / 'mesaha-waqf-haddad'     # the review page lists sets named mesaha-waqf-*
PRINT = 'الكويت (الحداد)'
S = 2208 / 2608
NOTE = ('مواضع الخلاف بين المطبوع في مصحف الكويت بخط الحداد (١٤٢١) وعمود «الكويت». D: العلامتان مختلفتان، '
        'M: العمود فيه علامة لم يقرأها البرنامج، X: علامة قرأها البرنامج ولا علامة في العمود. «النموذج» تخمين؛ '
        'اختر المطبوع فوق الكلمة المسطّرة.')
norm = lambda v: {'قلى': 'ق', 'صلى': 'ص'}.get(v, v)


def main() -> int:
    c = json.load(open(ROOT / 'artifacts' / 'haddad' / 'cands.json'))
    key_of = layout_keys(); cols = load_columns()
    wid_of = {v: k for k, v in key_of.items()}
    (SET / 'cards').mkdir(parents=True, exist_ok=True)
    seats = [(tuple(k), 'D') for k in c['diff']] + [(tuple(k), 'M') for k in c['miss']] + [(tuple(k), 'X') for k in c['extra']]
    seats.sort(key=lambda t: (t[0][0], t[0][1], t[0][2]))
    cards, pages, cache = [], set(), {}
    for k, group in seats:
        ks = ':'.join(map(str, k))
        page = c['page'][ks]
        d = cache.get(page) or json.load(open(ROOT / 'artifacts' / 'haddad-trace' / f'paw-words-{page:03d}.json'))
        cache = {page: d}
        w = next(x for x in d['words'] if x['word_index'] == wid_of[k])
        a, b = d['bands'][w['line'] - 1]
        im = cv2.imread(str(ROOT / 'artifacts' / 'haddad' / 'pages' / f'p{page:03d}.jpg'))
        im = cv2.resize(im, None, fx=S, fy=S, interpolation=cv2.INTER_AREA)
        cv2.line(im, (int(w['x0']), int(b) + 4), (int(w['x1']), int(b) + 4), (255, 120, 0), 3)
        x0, x1 = max(0, int(w['x0'] - 260)), min(im.shape[1], int(w['x1'] + 260))
        y0, y1 = max(0, int(a - 150)), min(im.shape[0], int(b + 30))
        crop = im[y0:y1, x0:x1]
        crop = cv2.resize(crop, (380, max(1, round(crop.shape[0] * 380 / crop.shape[1]))), interpolation=cv2.INTER_AREA)
        cid = f"{page:03d}-{k[0] * 1_000_000 + k[1] * 1_000 + k[2]}"
        cv2.imwrite(str(SET / 'cards' / f'{cid}.jpg'), crop, [cv2.IMWRITE_JPEG_QUALITY, 80])
        col = cols.get(k) or {}
        kw = norm(col.get('الكويت') or '')
        read = c['sign'].get(ks, [None, None])
        if group == 'X':
            model = read[0]
        else:
            model = col.get('الكويت')
        cards.append({'id': cid, 'page': page, 'line': w['line'], 'word_index': k[0] * 1_000_000 + k[1] * 1_000 + k[2], 'key': ks,
                      'text': w['text'], 'group': group, 'model': model or None,
                      'conf': read[1], 'print': PRINT, 'suggest': '',
                      'hint': {'المطبوع قرأه البرنامج': read[0] or '—', 'الكويت': col.get('الكويت') or '—',
                               'المساحة': col.get('المساحة') or '—', 'المساحة ١٣٧١': col.get('المساحة ١٣٧١') or '—',
                               'المدينة القديم': col.get('المدينة القديم') or '—'}})
        pages.add(page)
    groups = {"D": {"name": "(د) العلامتان مختلفتان", "note": "قرأ البرنامج علامة غير علامة عمود «الكويت». «النموذج» = علامة العمود (أغلب هذه أخطاء قراءة). اختر المطبوع فوق الكلمة."}, "M": {"name": "(م) في العمود ولم تُقرأ", "note": "في عمود «الكويت» علامة لم يقرأها البرنامج. «النموذج» = علامة العمود (أغلبها مطبوعة فعلًا). اختر «لا شيء» إن لم تكن مطبوعة."}, "X": {"name": "(ز) قُرئت وليست في العمود", "note": "قرأ البرنامج علامة (ثقة ≥ ٠٫٩٩) ولا علامة في عمود «الكويت». بعضها حقيقي وبعضها تشويش. اختر المطبوع أو «لا شيء»."}}
    json.dump({'pages': sorted(pages), 'note': NOTE, 'a_sample': [], 'decision_edition_by_print': True,
               'groups': groups, 'cards': cards},
              open(SET / 'data.json', 'w'), ensure_ascii=False, indent=1)
    from collections import Counter
    print(len(cards), 'cards', Counter(x['group'] for x in cards), 'on', len(pages), 'pages')
    return 0


if __name__ == '__main__':
    sys.exit(main())
