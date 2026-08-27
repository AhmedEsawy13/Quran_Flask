"""Run detection on one mushaf page → JSON (+ optional overlay).

Primary strategy: line-by-line search in the band *above* each word body
(see ``line_gaps.find_above_word_candidates``). Harakat on letters are ignored
because they sit lower, inside the word skeleton.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2

from pipeline.cv_waqf.attach import AttachedMark, _nearest_word, attach_to_words
from pipeline.cv_waqf.azhar_prior import (
    AZHAR_REJECT_REASON,
    partition_marks_by_azhar_occupancy,
)
from pipeline.cv_waqf.candidates import Candidate, crop_candidate
from pipeline.cv_waqf.classify import GlyphClassifier
from pipeline.cv_waqf.config import (
    CROP_SIZE,
    EDITION_MODEL_PATHS,
    EDITIONS,
    OVERLAYS_ROOT,
    PROPOSAL_MODES,
    resolve_azhar_seat_prior,
    resolve_proposal_mode,
)
from pipeline.cv_waqf.layout_geo import estimate_layout_words
from pipeline.cv_waqf.line_gaps import (
    find_above_word_candidates,
    find_line_component_candidates,
)
from pipeline.cv_waqf.pages import ensure_page_image
from pipeline.cv_waqf.preprocess import load_bgr, preprocess_page


def _reject_ambiguous(
    clf: GlyphClassifier,
    gray,
    classified: list[tuple[Candidate, str, float]],
    min_conf: float,
    *,
    margin: float = 0.12,
) -> list[tuple[Candidate, str, float]]:
    kept: list[tuple[Candidate, str, float]] = []
    none_idx = clf.classes.index('none') if 'none' in clf.classes else None
    for cand, label, conf in classified:
        crop = crop_candidate(gray, cand, size=CROP_SIZE)
        top, top_p, probs = clf.predict_probs(crop)
        if top != label or top_p < min_conf:
            continue
        ranked = sorted(enumerate(probs.tolist()), key=lambda t: -t[1])
        second_p = ranked[1][1] if len(ranked) > 1 else 0.0
        none_p = float(probs[none_idx]) if none_idx is not None else 0.0
        if (top_p - second_p) < margin:
            continue
        if none_p > 0.25 and (top_p - none_p) < 0.28:
            continue
        kept.append((cand, label, float(top_p)))
    return kept


def _prediction_is_clear(
    clf: GlyphClassifier,
    label: str,
    confidence: float,
    probs,
    min_conf: float,
    *,
    margin: float = 0.12,
) -> bool:
    if label == 'none' or confidence < min_conf:
        return False
    ranked = sorted((float(value) for value in probs), reverse=True)
    second = ranked[1] if len(ranked) > 1 else 0.0
    none_idx = clf.classes.index('none') if 'none' in clf.classes else None
    none_p = float(probs[none_idx]) if none_idx is not None else 0.0
    if confidence - second < margin:
        return False
    if none_p > 0.25 and confidence - none_p < 0.28:
        return False
    return True


def _attach_from_hits(
    classified_hits: list[tuple[object, str, float]],
    page: int,
    fallback_words,
) -> list[AttachedMark]:
    """Prefer the layout word already paired to the above-word hit."""
    best: dict[int, AttachedMark] = {}
    orphan: list[tuple[Candidate, str, float]] = []
    page_width = max(
        1,
        max(word.x1 for word in fallback_words)
        - min(word.x0 for word in fallback_words),
    ) if fallback_words else 1
    max_dist = max(24.0, page_width * 0.08)

    for hit, symbol, conf in classified_hits:
        cand = hit.candidate
        lw = hit.layout_word
        # Exact cluster counts can still assign an above-word component to the
        # adjacent word. Reconcile an unmarked owner with the trusted script
        # seat before accepting that direct cluster match.
        if lw is not None and not lw.has_waqf_seat:
            line_words = [
                word for word in fallback_words
                if word.line_number == hit.line_number
            ]
            prior_owner = _nearest_word(cand, line_words, max_dist)
            if prior_owner is not None and prior_owner.has_waqf_seat:
                lw = prior_owner
        if (
            lw is None or lw.surah <= 0 or lw.ayah <= 0
            or not lw.is_content_word
        ):
            orphan.append((cand, symbol, conf))
            continue
        attached = AttachedMark(
            word_id=lw.word_id,
            word_key=lw.word_key,
            word_id_space=lw.word_id_space,
            surah=lw.surah,
            ayah=lw.ayah,
            text=lw.text,
            symbol=symbol,
            confidence=float(conf),
            page=page,
            line_number=hit.line_number,
            candidate=cand,
        )
        prev = best.get(lw.word_id)
        if prev is None or attached.confidence > prev.confidence:
            best[lw.word_id] = attached

    if orphan:
        for m in attach_to_words(orphan, fallback_words, page=page):
            prev = best.get(m.word_id)
            if prev is None or m.confidence > prev.confidence:
                best[m.word_id] = m

    return sorted(
        best.values(),
        key=lambda m: (m.line_number, -m.candidate.x, -m.confidence),
    )


def _mark_dict(mark: AttachedMark, *, reject_reason: str | None = None) -> dict:
    row = {
        'word_id': mark.word_id,
        'word_key': mark.word_key,
        'word_id_space': mark.word_id_space,
        'surah': mark.surah,
        'ayah': mark.ayah,
        'text': mark.text,
        'symbol': mark.symbol,
        'confidence': round(mark.confidence, 4),
        'line': mark.line_number,
        'box': list(mark.candidate.box),
    }
    if reject_reason:
        row['reject_reason'] = reject_reason
    return row


def detect_page(
    edition_key: str,
    page: int,
    *,
    min_conf: float = 0.55,
    overlay_path: Path | None = None,
    model_path: Path | None = None,
    proposal_mode: str | None = None,
    seat_prior: bool = True,  # kept for CLI compat; above-word path is always used
    azhar_prior: bool | None = None,
) -> dict:
    del seat_prior  # unused — geometry is above-word, not old seat prior
    proposal_mode = resolve_proposal_mode(edition_key, proposal_mode)
    use_azhar_prior = resolve_azhar_seat_prior(edition_key, azhar_prior)
    spec = EDITIONS[edition_key]
    img_path = ensure_page_image(spec, page)
    bgr = load_bgr(img_path)
    prepared = preprocess_page(bgr, spec)
    words = estimate_layout_words(spec, page, prepared)

    narrow_hits = find_above_word_candidates(prepared, words)
    broad_hits = (
        find_line_component_candidates(prepared, words)
        if proposal_mode == 'hybrid' else []
    )
    # Keep alternate crop scales because the glyph can be a single component
    # or several nearby components.  Suppress only exact duplicate boxes.
    hits = []
    seen_boxes: set[tuple[int, int, int, int]] = set()
    for hit in [*narrow_hits, *broad_hits]:
        box = (
            hit.candidate.x, hit.candidate.y,
            hit.candidate.w, hit.candidate.h,
        )
        if box in seen_boxes:
            continue
        seen_boxes.add(box)
        hits.append(hit)
    resolved_model = model_path
    if resolved_model is None:
        edition_model = EDITION_MODEL_PATHS.get(edition_key)
        if edition_model is not None and edition_model.is_file():
            resolved_model = edition_model
    clf = GlyphClassifier(model_path=resolved_model)
    if not clf.ready:
        raise RuntimeError(
            f'missing ONNX model at {clf.model_path}. '
            'Run: python -m pipeline.cv_waqf train'
        )

    crops = [
        crop_candidate(prepared.gray, hit.candidate, size=CROP_SIZE)
        for hit in hits
    ]
    classified_hits: list[tuple[object, str, float]] = []
    raw_classified: list[tuple[Candidate, str, float]] = []
    for hit, (label, conf, probs) in zip(
        hits, clf.predict_many_probs(crops),
    ):
        if not _prediction_is_clear(
            clf, label, conf, probs, min_conf,
        ):
            continue
        classified_hits.append((hit, label, conf))
        raw_classified.append((hit.candidate, label, conf))

    attached = _attach_from_hits(classified_hits, page, words)
    kept = attached
    rejected: list[AttachedMark] = []
    if use_azhar_prior:
        kept, rejected = partition_marks_by_azhar_occupancy(attached)

    if overlay_path is not None:
        overlay_path.parent.mkdir(parents=True, exist_ok=True)
        vis = bgr.copy()
        for hit in hits:
            c = hit.candidate
            cv2.rectangle(vis, (c.x, c.y), (c.x + c.w, c.y + c.h), (180, 180, 80), 1)
        for cand, label, conf in raw_classified:
            cv2.rectangle(
                vis, (cand.x, cand.y), (cand.x + cand.w, cand.y + cand.h),
                (0, 140, 255), 2,
            )
            cv2.putText(
                vis, f'{label}:{conf:.2f}',
                (cand.x, max(12, cand.y - 2)),
                cv2.FONT_HERSHEY_SIMPLEX, 0.35, (0, 140, 255), 1, cv2.LINE_AA,
            )
        for mark in kept:
            cv2.circle(
                vis,
                (int(mark.candidate.cx), int(mark.candidate.cy)),
                4, (0, 200, 0), -1,
            )
        for mark in rejected:
            cv2.circle(
                vis,
                (int(mark.candidate.cx), int(mark.candidate.cy)),
                4, (0, 0, 220), -1,
            )
            cv2.circle(
                vis,
                (int(mark.candidate.cx), int(mark.candidate.cy)),
                8, (0, 0, 220), 1,
            )
        cv2.imwrite(str(overlay_path), vis)

    return {
        'edition': edition_key,
        'page': page,
        'image': str(img_path),
        'candidates': len(hits),
        'classified': len(raw_classified),
        'strategy': (
            'hybrid-line-components'
            if proposal_mode == 'hybrid' else 'above-word-per-line'
        ),
        'proposal_mode': proposal_mode,
        'azhar_prior': use_azhar_prior,
        'narrow_candidates': len(narrow_hits),
        'component_candidates': len(broad_hits),
        'marks': [_mark_dict(m) for m in kept],
        'azhar_rejected': [
            _mark_dict(m, reject_reason=AZHAR_REJECT_REASON) for m in rejected
        ],
        'azhar_kept': len(kept),
        'azhar_rejected_count': len(rejected),
        'model_ready': clf.ready,
        'model': str(clf.model_path),
        'model_pipeline': clf.pipeline,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--edition', default='الشمرلي', choices=list(EDITIONS))
    parser.add_argument('--page', type=int, required=True)
    parser.add_argument('--min-conf', type=float, default=0.55)
    parser.add_argument('--overlay', action='store_true')
    parser.add_argument('--json-out', type=Path, default=None)
    parser.add_argument('--model', type=Path, default=None)
    parser.add_argument(
        '--proposal-mode',
        choices=sorted(PROPOSAL_MODES),
        default=None,
        help='override the edition default (hybrid for البحرين, narrow otherwise)',
    )
    parser.add_argument(
        '--azhar-prior',
        action=argparse.BooleanOptionalAction,
        default=None,
        help='override edition Azhar occupancy prior (on for البحرين; '
             'use --no-azhar-prior to disable)',
    )
    args = parser.parse_args(argv)

    overlay = None
    if args.overlay:
        overlay = OVERLAYS_ROOT / EDITIONS[args.edition].id / f'p{args.page:03d}.jpg'
    result = detect_page(
        args.edition, args.page,
        min_conf=args.min_conf,
        overlay_path=overlay,
        model_path=args.model,
        proposal_mode=args.proposal_mode,
        azhar_prior=args.azhar_prior,
    )
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(text, encoding='utf-8')
    print(text)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
