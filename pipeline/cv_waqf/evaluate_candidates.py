"""Audit proposal recall and RTL word attachment independently of the model."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from pipeline.cv_waqf.attach import _nearest_word
from pipeline.cv_waqf.candidates import Candidate
from pipeline.cv_waqf.config import ARTIFACTS_ROOT, EDITIONS
from pipeline.cv_waqf.evaluate_hand import load_anchored_labels, _parse_pages
from pipeline.cv_waqf.layout_geo import estimate_layout_words
from pipeline.cv_waqf.line_gaps import find_line_component_candidates
from pipeline.cv_waqf.pages import ensure_page_image
from pipeline.cv_waqf.preprocess import load_bgr, preprocess_page


def _iou_box(candidate: Candidate, raw_box: list[int]) -> float:
    ax0, ay0, ax1, ay1 = candidate.box
    bx0, by0, bx1, by1 = (int(value) for value in raw_box)
    ix0, iy0 = max(ax0, bx0), max(ay0, by0)
    ix1, iy1 = min(ax1, bx1), min(ay1, by1)
    intersection = max(0, ix1 - ix0) * max(0, iy1 - iy0)
    if not intersection:
        return 0.0
    union = (ax1 - ax0) * (ay1 - ay0) + (bx1 - bx0) * (by1 - by0) - intersection
    return intersection / union if union else 0.0


def evaluate_candidate_labels(
    edition: str,
    labels: list[dict],
    *,
    min_iou: float = 0.10,
) -> dict:
    """Measure proposal coverage and word ownership on positive hand labels."""
    spec = EDITIONS[edition]
    positives = [row for row in labels if row.get('symbol') != 'none']
    by_page: dict[int, list[dict]] = {}
    for row in positives:
        by_page.setdefault(int(row['page']), []).append(row)

    details: list[dict] = []
    proposal_count = 0
    covered = attached = manual_attached = 0
    for page, page_labels in sorted(by_page.items()):
        prepared = preprocess_page(
            load_bgr(ensure_page_image(spec, page)), spec,
        )
        words = estimate_layout_words(spec, page, prepared)
        hits = find_line_component_candidates(prepared, words)
        proposal_count += len(hits)
        page_width = max(1, prepared.band_box[2] - prepared.band_box[0])
        for expected in page_labels:
            overlaps = [
                hit for hit in hits
                if _iou_box(hit.candidate, expected['box']) >= min_iou
            ]
            has_proposal = bool(overlaps)
            has_attachment = any(
                hit.layout_word is not None
                and hit.layout_word.word_key == expected['word_key']
                for hit in overlaps
            )
            x0, y0, x1, y1 = (int(value) for value in expected['box'])
            manual = Candidate(
                x=x0, y=y0, w=x1 - x0, h=y1 - y0,
                area=max(1, (x1 - x0) * (y1 - y0)),
            )
            owner = _nearest_word(
                manual, words, max(24.0, page_width * 0.08),
            )
            manual_ok = owner is not None and owner.word_key == expected['word_key']
            covered += int(has_proposal)
            attached += int(has_attachment)
            manual_attached += int(manual_ok)
            details.append({
                'page': page,
                'word_key': expected['word_key'],
                'symbol': expected.get('symbol'),
                'proposal': has_proposal,
                'proposal_attached_to_expected_word': has_attachment,
                'manual_box_attached_to_expected_word': manual_ok,
                'overlapping_proposals': len(overlaps),
            })

    total = len(positives)
    denominator = max(1, total)
    return {
        'edition': edition,
        'min_iou': min_iou,
        'summary': {
            'pages': len(by_page),
            'positive_labels': total,
            'proposals': proposal_count,
            'proposal_recall': round(covered / denominator, 4),
            'proposal_attachment_recall': round(attached / denominator, 4),
            'manual_box_attachment_accuracy': round(manual_attached / denominator, 4),
            'covered': covered,
            'attached': attached,
            'manual_attached': manual_attached,
        },
        'details': details,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--edition', required=True, choices=list(EDITIONS))
    parser.add_argument('--pages', default=None)
    parser.add_argument('--min-iou', type=float, default=0.10)
    parser.add_argument('--out', type=Path, default=None)
    args = parser.parse_args(argv)
    spec = EDITIONS[args.edition]
    labels = load_anchored_labels(spec.id)
    if args.pages:
        wanted = set(_parse_pages(args.pages))
        labels = [row for row in labels if int(row['page']) in wanted]
    if not labels:
        raise SystemExit(f'no anchored labels for {args.edition}')
    report = evaluate_candidate_labels(
        args.edition, labels, min_iou=args.min_iou,
    )
    out = args.out or ARTIFACTS_ROOT / f'evaluate-candidates-{spec.id}.json'
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report['summary'], ensure_ascii=False, indent=2))
    print(f'wrote {out}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
