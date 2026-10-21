"""mesaha_debug_pieces.py PAGE w1 w2 ... : pieces of those words (1-based, rings excluded) with box, mark flag, baseline offset"""
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))
from pipeline.paw_split._common import ROOT, QATAR_APP_ASSETS, workdir  # noqa: E402
workdir('mesaha-trace')

import runpy, sys, io, contextlib
P = sys.argv[1]; nums = [int(x) for x in sys.argv[2:]]
sys.argv = ['mesaha_split.py', P]
with contextlib.redirect_stdout(io.StringIO()):
    g = runpy.run_path(str(_Path(__file__).with_name('mesaha_split.py')))
by = {p['id']: p for p in g['pieces']}; lh = g['line_h']
ws = [w for w in g['words_out'] if not w['ring']]
for i in nums:
    w = ws[i - 1]; base = g['baselines'][w['line'] - 1]
    print(i, w['text'], 'line', w['line'])
    for pid in sorted(w['pieces'], key=lambda k: -by[k]['x1']):
        p = by[pid]
        print(f"   {pid:5d} x{p['x0']}-{p['x1']} h{(p['y1']-p['y0'])/lh:.2f} w{(p['x1']-p['x0'])/lh:.2f} top{(p['y0']-base)/lh:+.2f} bot{(p['y1']-base)/lh:+.2f} a{p['area']} {'M' if p['mark'] else 'B'}")
print('line_h', round(lh, 1))
