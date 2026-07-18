#!/usr/bin/env python3
"""Report the measurable accuracy/coverage gates for المكتفى."""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.classical_review import muktafa_accuracy  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--json', action='store_true')
    ap.add_argument('--strict', action='store_true',
                    help='fail unless every confident row is source-traceable and aligned')
    args = ap.parse_args(argv)
    result = muktafa_accuracy()
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f'Extracted rulings: {result["total_extracted"]}')
        print(f'Qur’an-location match: {result["matched"]}/{result["total_extracted"]} '
              f'({result["matched_rate"]:.2f}%)')
        print(f'High-confidence: {result["confident"]}/{result["total_extracted"]} '
              f'({result["confident_rate"]:.2f}%)')
        print(f'Confident source traceability: {result["source_traceable"]}/{result["confident"]} '
              f'({result["source_traceable_rate"]:.2f}%)')
        print(f'Confident Qur’an alignment: {result["quran_aligned"]}/{result["confident"]} '
              f'({result["quran_aligned_rate"]:.2f}%)')
        print(f'Alignment modes: exact/prefix={result["exact_or_prefix"]}, '
              f'orthographic-fuzzy={result["orthographic_fuzzy"]}')
        print(f'Review queue: {result["review"]}')
        print(result['claim_limit'])
    if args.strict and (result['source_traceable'] != result['confident']
                        or result['quran_aligned'] != result['confident']):
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
