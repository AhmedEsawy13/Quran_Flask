"""Pilot comparison: «الكويت (الحداد)» signs read on pages 4-30 vs every waqf column (run from the repo root)."""
import json, sqlite3, sys
from collections import Counter
sys.path.insert(0, '.')
from pipeline.paw_split.haddad_waqf import layout_keys, load_columns, HAFS
key_of = layout_keys(); cols = load_columns()
norm = lambda v: {'قلى': 'ق', 'صلى': 'ص'}.get(v, v)
pages = range(int(sys.argv[1]) if len(sys.argv) > 1 else 4, (int(sys.argv[2]) if len(sys.argv) > 2 else 30) + 1)
sign, words = {}, set()
for p in pages:
    d = json.load(open(f'artifacts/haddad-trace/paw-words-{p:03d}.json'))
    for w in d['words']:
        if not w['ring']: words.add(key_of[w['word_index']])
    for r in json.load(open(f'artifacts/haddad-trace/waqf-{p:03d}.json'))['signs']:
        sign[key_of[r['word_index']]] = (r['sign'], r['conf'], p)
print('words', len(words), 'signs read', len(sign), Counter(v[0] for v in sign.values()))
for c in HAFS:
    same = pos = 0; extra = miss = 0
    for k in words:
        a = norm(sign.get(k, ('',))[0]); b = norm((cols.get(k) or {}).get(c, ''))
        if a and b: pos += 1; same += a == b
        elif a and not b: extra += 1
        elif b and not a: miss += 1
    print(f'{c:14s} both {pos:4d} same {same:4d}  haddad-only {extra:3d}  column-only {miss:3d}')
print()
extra = [(k, v) for k, v in sign.items() if not (cols.get(k) or {}).get('الكويت')]
any_col = [(k, v) for k, v in extra if any((cols.get(k) or {}).get(c) for c in HAFS)]
print('haddad-only vs الكويت', len(extra), '· of them some other print marks', len(any_col))
import numpy as np
print('conf of extras (pct 10/50/90)', np.percentile([v[1] for _, v in extra], [10, 50, 90]).round(3))
print('conf of matches', np.percentile([v[1] for k, v in sign.items() if (cols.get(k) or {}).get('الكويت')], [10, 50, 90]).round(3))
print('extras with conf>=0.99:', sum(v[1] >= 0.99 for _, v in extra), [ (k, v) for k, v in extra if v[1] >= 0.99][:12])
miss = [k for k in words if (cols.get(k) or {}).get('الكويت') and k not in sign]
print('column-only', [(k, cols[k]['الكويت']) for k in sorted(miss)])
diff = [(k, sign[k][0], cols[k]['الكويت']) for k in sign if (cols.get(k) or {}).get('الكويت') and norm(sign[k][0]) != norm(cols[k]['الكويت'])]
print('different symbol', diff)
print()
dis = [k for k in sorted(words) if norm((cols.get(k) or {}).get('الكويت','')) != norm((cols.get(k) or {}).get('المساحة',''))]
print('pilot words where الكويت ≠ المساحة:', len(dis))
for k in dis:
    c = cols.get(k) or {}
    print(k, 'kuwait', c.get('الكويت') or '-', '| mesaha', c.get('المساحة') or '-', '| 1371', c.get('المساحة ١٣٧١') or '-', '| haddad read', sign.get(k, ('-',))[0])
