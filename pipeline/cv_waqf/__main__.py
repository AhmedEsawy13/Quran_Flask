"""CLI entry: python -m pipeline.cv_waqf <command> ..."""
from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ('-h', '--help'):
        print(
            'usage: python -m pipeline.cv_waqf <command> ...\n\n'
            'commands:\n'
            '  cache-pages     download/render page JPEGs\n'
            '  mesaha-boxes    export Mesaha DjVu word boxes\n'
            '  build-crops     weak-label glyph crop dataset\n'
            '  candidate-crops detector-window crops labelled by seat + consensus\n'
            '  splits          fixed train/eval pages for the multi-print recipe\n'
            '  sample-crops    word-anchored crops from trusted DB marks\n'
            '  train           page-split training → models/waqf_glyph.onnx\n'
            '  train-cnn       two-stage CNN glyph classifier (needs torch)\n'
            '  train-strip     above-word strip CNN → models/waqf_strip_bahrain.onnx\n'
            '  run-page        detect marks on one page\n'
            '  audit           CV vs mushaf_waqf.db report\n'
            '  evaluate-hand   exact mark + canonical-word holdout accuracy\n'
            '  evaluate-candidates proposal + word-attachment recall\n'
            '  evaluate-consensus  score a print with no hand labels vs edition consensus\n'
            '  calibrate-geometry  derive an edition\'s nominal text band from pages\n'
            '  ensemble-models average trained MLP glyph models into one ONNX\n'
            '  compare-models  score glyph models on both prints\' held-out pages\n'
            '  review-queue    stratified pages for hand calibration\n'
            '  bootstrap       draft plan.json for an edition\n'
            '  push-hand       upload hand crops + model to Supabase\n'
            '  pull-hand       download hand crops + model from Supabase\n'
            '  status-hand     read-only Supabase hand-label status\n'
        )
        return 0

    cmd, rest = argv[0], argv[1:]
    if cmd == 'cache-pages':
        from pipeline.cv_waqf.pages import cache_page_range
        from pipeline.cv_waqf.config import EDITIONS
        import argparse
        p = argparse.ArgumentParser()
        p.add_argument('--edition', required=True, choices=list(EDITIONS))
        p.add_argument('--pages', required=True)
        args = p.parse_args(rest)
        pages = _parse_pages(args.pages)
        paths = cache_page_range(EDITIONS[args.edition], pages[0], pages[-1])
        print(f'cached {len(paths)} pages')
        return 0
    if cmd == 'mesaha-boxes':
        from pipeline.cv_waqf.mesaha_boxes import main as m
        return m(rest)
    if cmd == 'sample-crops':
        from pipeline.cv_waqf.sample_crops import main as m
        return m(rest)
    if cmd == 'splits':
        from pipeline.cv_waqf.splits import main as m
        return m(rest)
    if cmd == 'candidate-crops':
        from pipeline.cv_waqf.candidate_crops import main as m
        return m(rest)
    if cmd == 'build-crops':
        from pipeline.cv_waqf.build_crops import main as m
        return m(rest)
    if cmd == 'train':
        from pipeline.cv_waqf.train_classifier import main as m
        return m(rest)
    if cmd == 'train-cnn':
        from pipeline.cv_waqf.train_cnn_data import main as m
        return m(rest)
    if cmd == 'train-strip':
        from pipeline.cv_waqf.train_strip import main as m
        return m(rest)
    if cmd == 'run-page':
        from pipeline.cv_waqf.run_page import main as m
        return m(rest)
    if cmd == 'audit':
        from pipeline.cv_waqf.audit_edition import main as m
        return m(rest)
    if cmd == 'evaluate-hand':
        from pipeline.cv_waqf.evaluate_hand import main as m
        return m(rest)
    if cmd == 'calibrate-geometry':
        from pipeline.cv_waqf.calibrate_geometry import main as m
        return m(rest)
    if cmd == 'ensemble-models':
        from pipeline.cv_waqf.ensemble_models import main as m
        return m(rest)
    if cmd == 'compare-models':
        from pipeline.cv_waqf.compare_models import main as m
        return m(rest)
    if cmd == 'evaluate-consensus':
        from pipeline.cv_waqf.evaluate_consensus import main as m
        return m(rest)
    if cmd == 'evaluate-candidates':
        from pipeline.cv_waqf.evaluate_candidates import main as m
        return m(rest)
    if cmd == 'review-queue':
        from pipeline.cv_waqf.review_queue import main as m
        return m(rest)
    if cmd == 'bootstrap':
        from pipeline.cv_waqf.bootstrap_edition import main as m
        return m(rest)
    if cmd == 'push-hand':
        from pipeline.cv_waqf.sync_supabase import main as m
        return m(['push', *rest])
    if cmd == 'pull-hand':
        from pipeline.cv_waqf.sync_supabase import main as m
        return m(['pull', *rest])
    if cmd == 'status-hand':
        from pipeline.cv_waqf.sync_supabase import main as m
        return m(['status', *rest])
    print(f'unknown command: {cmd}', file=sys.stderr)
    return 2


def _parse_pages(spec: str) -> list[int]:
    pages: list[int] = []
    for part in spec.split(','):
        part = part.strip()
        if not part:
            continue
        if '-' in part:
            a, b = part.split('-', 1)
            pages.extend(range(int(a), int(b) + 1))
        else:
            pages.append(int(part))
    return pages


if __name__ == '__main__':
    raise SystemExit(main())
