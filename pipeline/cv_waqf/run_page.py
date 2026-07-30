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

from pipeline.cv_waqf.attach import AttachedMark, attach_to_words
from pipeline.cv_waqf.candidates import Candidate, crop_candidate
from pipeline.cv_waqf.classify import GlyphClassifier
from pipeline.cv_waqf.config import CROP_SIZE, EDITIONS, OVERLAYS_ROOT
from pipeline.cv_waqf.layout_geo import estimate_layout_words
from pipeline.cv_waqf.line_gaps import find_above_word_candidates
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


def _attach_from_hits(
    classified_hits: list[tuple[object, str, float]],
    page: int,
    fallback_words,
) -> list[AttachedMark]:
    """Prefer the layout word already paired to the above-word hit."""
    best: dict[int, AttachedMark] = {}
    orphan: list[tuple[Candidate, str, float]] = []

    for hit, symbol, conf in classified_hits:
        cand = hit.candidate
        lw = hit.layout_word
        if lw is None or lw.surah <= 0 or lw.ayah <= 0:
            orphan.append((cand, symbol, conf))
            continue
        attached = AttachedMark(
            word_id=lw.word_id,
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


def detect_page(
    edition_key: str,
    page: int,
    *,
    min_conf: float = 0.55,
    overlay_path: Path | None = None,
    seat_prior: bool = True,  # kept for CLI compat; above-word path is always used
) -> dict:
    del seat_prior  # unused — geometry is above-word, not old seat prior
    spec = EDITIONS[edition_key]
    img_path = ensure_page_image(spec, page)
    bgr = load_bgr(img_path)
    prepared = preprocess_page(bgr, spec)
    words = estimate_layout_words(spec, page, prepared)

    hits = find_above_word_candidates(prepared, words)
    clf = GlyphClassifier()
    if not clf.ready:
        raise RuntimeError(
            f'missing ONNX model at {clf.model_path}. '
            'Run: python -m pipeline.cv_waqf train'
        )

    classified_hits: list[tuple[object, str, float]] = []
    raw_classified: list[tuple[Candidate, str, float]] = []
    for hit in hits:
        crop = crop_candidate(prepared.gray, hit.candidate, size=CROP_SIZE)
        label, conf = clf.predict_crop(crop)
        if label == 'none' or conf < min_conf:
            continue
        classified_hits.append((hit, label, conf))
        raw_classified.append((hit.candidate, label, conf))

    raw_classified = _reject_ambiguous(clf, prepared.gray, raw_classified, min_conf)
    keep_cands = {id(c) for c, _l, _p in raw_classified}
    classified_hits = [
        (hit, label, conf)
        for hit, label, conf in classified_hits
        if id(hit.candidate) in keep_cands
        or any(
            c.x == hit.candidate.x and c.y == hit.candidate.y
            and c.w == hit.candidate.w and c.h == hit.candidate.h
            for c, _l, _p in raw_classified
        )
    ]
    # Re-filter hits against ambiguous-rejected set by box identity.
    kept_boxes = {(c.x, c.y, c.w, c.h) for c, _l, _p in raw_classified}
    classified_hits = [
        (hit, label, conf) for hit, label, conf in classified_hits
        if (hit.candidate.x, hit.candidate.y, hit.candidate.w, hit.candidate.h)
        in kept_boxes
    ]

    attached = _attach_from_hits(classified_hits, page, words)

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
        for mark in attached:
            cv2.circle(
                vis,
                (int(mark.candidate.cx), int(mark.candidate.cy)),
                4, (0, 200, 0), -1,
            )
        cv2.imwrite(str(overlay_path), vis)

    return {
        'edition': edition_key,
        'page': page,
        'image': str(img_path),
        'candidates': len(hits),
        'classified': len(raw_classified),
        'strategy': 'above-word-per-line',
        'marks': [
            {
                'word_id': m.word_id,
                'surah': m.surah,
                'ayah': m.ayah,
                'text': m.text,
                'symbol': m.symbol,
                'confidence': round(m.confidence, 4),
                'line': m.line_number,
                'box': list(m.candidate.box),
            }
            for m in attached
        ],
        'model_ready': clf.ready,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--edition', default='الشمرلي', choices=list(EDITIONS))
    parser.add_argument('--page', type=int, required=True)
    parser.add_argument('--min-conf', type=float, default=0.55)
    parser.add_argument('--overlay', action='store_true')
    parser.add_argument('--json-out', type=Path, default=None)
    args = parser.parse_args(argv)

    overlay = None
    if args.overlay:
        overlay = OVERLAYS_ROOT / EDITIONS[args.edition].id / f'p{args.page:03d}.jpg'
    result = detect_page(
        args.edition, args.page,
        min_conf=args.min_conf,
        overlay_path=overlay,
    )
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(text, encoding='utf-8')
    print(text)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
