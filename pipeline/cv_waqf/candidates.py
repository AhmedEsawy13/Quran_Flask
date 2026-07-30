"""Find small connected-component candidates that may be waqf glyphs."""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from pipeline.cv_waqf.preprocess import PreparedPage


@dataclass
class Candidate:
    """Axis-aligned box in full-page coordinates."""

    x: int
    y: int
    w: int
    h: int
    area: int
    score: float = 1.0

    @property
    def cx(self) -> float:
        return self.x + self.w / 2.0

    @property
    def cy(self) -> float:
        return self.y + self.h / 2.0

    @property
    def box(self) -> tuple[int, int, int, int]:
        return self.x, self.y, self.x + self.w, self.y + self.h


def find_candidates(
    prepared: PreparedPage,
    *,
    min_area: int = 70,
    max_area: int = 700,
    min_side: int = 12,
    max_side: int = 36,
    max_aspect: float = 2.6,
    min_fill: float = 0.18,
) -> list[Candidate]:
    """Contour / CC search for stop-glyph-sized ink blobs in the text band.

    Floors are tuned to reject typical harakat (ضمة/كسرة/فتحة/…) which are
    smaller and thinner than printed waqf stops (ۘۗۖۚۙ…).
    """
    band = prepared.text_band
    ox, oy = prepared.band_origin
    # Stronger open dissolves single-dot / thin harakat before CC.
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    cleaned = cv2.morphologyEx(band, cv2.MORPH_OPEN, kernel, iterations=2)
    num, labels, stats, _ = cv2.connectedComponentsWithStats(cleaned, connectivity=8)
    out: list[Candidate] = []
    for label in range(1, num):
        x, y, w, h, area = (int(v) for v in stats[label])
        if area < min_area or area > max_area:
            continue
        if w < min_side or h < min_side or w > max_side or h > max_side:
            continue
        # Harakat are often wide-thin fathas or tall-thin dammas.
        aspect = max(w, h) / max(1, min(w, h))
        if aspect > max_aspect:
            continue
        fill = area / float(w * h)
        if fill < min_fill:
            continue
        # Tiny "dot-like" residue after open still slips through — drop them.
        if min(w, h) < 8 and area < 100:
            continue
        score = fill * (1.0 / (1.0 + abs(aspect - 1.15)))
        out.append(Candidate(
            x=ox + x, y=oy + y, w=w, h=h, area=area, score=float(score),
        ))
    out.sort(key=lambda c: (-c.score, c.y, -c.x))
    return _nms(out, iou=0.4)


def _nms(cands: list[Candidate], iou: float) -> list[Candidate]:
    kept: list[Candidate] = []
    for cand in cands:
        if any(_iou(cand, other) >= iou for other in kept):
            continue
        kept.append(cand)
    return kept


def _iou(a: Candidate, b: Candidate) -> float:
    ax0, ay0, ax1, ay1 = a.box
    bx0, by0, bx1, by1 = b.box
    ix0, iy0 = max(ax0, bx0), max(ay0, by0)
    ix1, iy1 = min(ax1, bx1), min(ay1, by1)
    iw, ih = max(0, ix1 - ix0), max(0, iy1 - iy0)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    union = a.w * a.h + b.w * b.h - inter
    return inter / union if union else 0.0


def crop_candidate(
    gray_or_bgr: np.ndarray,
    cand: Candidate,
    size: int = 48,
    pad: int = 4,
) -> np.ndarray:
    """Return a square uint8 grayscale crop resized to ``size``."""
    if gray_or_bgr.ndim == 3:
        gray = cv2.cvtColor(gray_or_bgr, cv2.COLOR_BGR2GRAY)
    else:
        gray = gray_or_bgr
    h, w = gray.shape[:2]
    x0 = max(0, cand.x - pad)
    y0 = max(0, cand.y - pad)
    x1 = min(w, cand.x + cand.w + pad)
    y1 = min(h, cand.y + cand.h + pad)
    patch = gray[y0:y1, x0:x1]
    if patch.size == 0:
        return np.zeros((size, size), dtype=np.uint8)
    # Letterbox into square
    ph, pw = patch.shape[:2]
    side = max(ph, pw)
    canvas = np.full((side, side), 255, dtype=np.uint8)
    oy = (side - ph) // 2
    ox = (side - pw) // 2
    canvas[oy:oy + ph, ox:ox + pw] = patch
    return cv2.resize(canvas, (size, size), interpolation=cv2.INTER_AREA)
