"""Words whose pieces differ from the hand-checked paw-words-NNN.truth.json.

    python3 pipeline/paw_split/regress.py mesaha-trace 015 021 041
"""
import json, sys
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))
from pipeline.paw_split._common import workdir  # noqa: E402
workdir(sys.argv[1])
for P in sys.argv[2:]:
    a = [w for w in json.load(open(f'paw-words-{P}.truth.json'))['words'] if not w['ring']]
    b = [w for w in json.load(open(f'paw-words-{P}.json'))['words'] if not w['ring']]
    print(P, 'changed vs truth:', [x['text'] for x, y in zip(a, b) if sorted(x.get('pieces', [])) != sorted(y.get('pieces', []))])
