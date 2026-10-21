"""Run the shipped waqf detector (pipeline.cv_waqf.run_page.detect_page, edition قطر) on a page
range and keep its kept + Azhar-rejected marks for qatar_attach_eval.py -> shipped.json.

    python3 pipeline/paw_split/qatar_detect_shipped.py 3 49
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from pipeline.paw_split._common import workdir  # noqa: E402
from pipeline.cv_waqf.run_page import detect_page  # noqa: E402

first, last = int(sys.argv[1]), int(sys.argv[2])
out = {}
for page in range(first, last + 1):
    r = detect_page('قطر', page)
    out[page] = {'marks': r['marks'], 'rejected': r['azhar_rejected']}
workdir('qatar-attach')
json.dump(out, open('shipped.json', 'w'), ensure_ascii=False)
print('pages', len(out), 'kept', sum(len(v['marks']) for v in out.values()),
      'rejected', sum(len(v['rejected']) for v in out.values()))
