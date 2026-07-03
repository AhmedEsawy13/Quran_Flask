#!/usr/bin/env python3
"""Bake the Quran-wide research analyses to data/research_cache/*.json.

The مُكْث research endpoints (تشابه القرّاء، تقارب المصاحف، اتفاق القرّاء،
الابتداء) each walk all 114 surahs across every installed reciter on first
request — seconds of CPU that the first visitor pays. Running this script at
build time (or after reciter/waqf data changes) writes the finished payloads
to disk; the app then serves them instantly and only recomputes if a file is
missing or unreadable.

    python3 pipeline/precompute_research.py

Re-run after: syncing reciter timestamps (import_qul_reciters.py --sync),
editing mushaf_waqf.db, or adding/removing reciters.
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ['RESEARCH_PRECOMPUTE'] = '1'   # force builders to compute, not read disk

import app  # noqa: E402

BUILDERS = {
    'clustering':        app._build_reciter_clustering,
    'mushaf_similarity': app._build_mushaf_similarity,
    'mushaf_agreement':  app._build_mushaf_agreement_index,
    'ibtidaa':           app._build_ibtidaa_index,
}


def main():
    out_dir = app._RESEARCH_CACHE_DIR
    os.makedirs(out_dir, exist_ok=True)
    for name, build in BUILDERS.items():
        t0 = time.time()
        payload = build()
        path = os.path.join(out_dir, f'{name}.json')
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False, separators=(',', ':'))
        kb = os.path.getsize(path) // 1024
        print(f'  {name}: {time.time() - t0:5.1f}s → {path} ({kb} KB)')
    print('done — commit data/research_cache/ so deployments ship the baked files.')


if __name__ == '__main__':
    main()
