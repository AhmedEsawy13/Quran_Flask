"""Attach classified mark detections to the nearest layout word (RTL)."""
from __future__ import annotations

from dataclasses import dataclass

from pipeline.cv_waqf.candidates import Candidate
from pipeline.cv_waqf.layout_geo import LayoutWord


@dataclass
class AttachedMark:
    word_id: int
    surah: int
    ayah: int
    text: str
    symbol: str
    confidence: float
    page: int
    line_number: int
    candidate: Candidate


def attach_to_words(
    detections: list[tuple[Candidate, str, float]],
    words: list[LayoutWord],
    *,
    page: int,
    max_dist_frac: float = 0.08,
) -> list[AttachedMark]:
    """Map each (candidate, symbol, conf) to the nearest layout word.

    Prefer the word whose left edge is just to the right of the mark (RTL:
    mark sits at the end of the word).
    """
    if not detections or not words:
        return []
    page_w = max(w.x1 for w in words) - min(w.x0 for w in words)
    max_dist = max(24.0, page_w * max_dist_frac)

    # One mark per word — keep highest confidence.
    best: dict[int, AttachedMark] = {}
    for cand, symbol, conf in detections:
        if symbol == 'none' or conf < 0.35:
            continue
        nearest = _nearest_word(cand, words, max_dist)
        if nearest is None:
            continue
        attached = AttachedMark(
            word_id=nearest.word_id,
            surah=nearest.surah,
            ayah=nearest.ayah,
            text=nearest.text,
            symbol=symbol,
            confidence=float(conf),
            page=page,
            line_number=nearest.line_number,
            candidate=cand,
        )
        prev = best.get(nearest.word_id)
        if prev is None or attached.confidence > prev.confidence:
            best[nearest.word_id] = attached
    return sorted(
        best.values(),
        key=lambda m: (m.line_number, -m.candidate.x, -m.confidence),
    )


def _nearest_word(
    cand: Candidate,
    words: list[LayoutWord],
    max_dist: float,
) -> LayoutWord | None:
    best: LayoutWord | None = None
    best_score = float('inf')
    for word in words:
        if word.surah <= 0 or word.ayah <= 0:
            continue
        # Same line band vertically.
        if cand.cy < word.y0 - 8 or cand.cy > word.y1 + 8:
            continue
        # Prefer marks near the left (end) of the word.
        dx = abs(cand.cx - word.x0)
        dy = abs(cand.cy - (word.y0 + 0.35 * (word.y1 - word.y0)))
        # Soft bonus when mark is left-of-center of the word box.
        left_bias = 0.0 if cand.cx <= word.cx else 12.0
        score = dx + 1.6 * dy + left_bias
        if score < best_score and score <= max_dist * 3:
            best_score = score
            best = word
    if best is None or best_score > max_dist * 3:
        return None
    return best
