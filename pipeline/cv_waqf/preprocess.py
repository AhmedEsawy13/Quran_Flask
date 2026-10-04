"""OpenCV 5 page preprocessing for waqf candidate search."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pipeline.cv_waqf.config import EditionSpec


@dataclass
class PreparedPage:
    """Preprocessed page ready for candidate extraction.

    ``binary`` / image arrays may be ``None`` for layout-only synthetic pages
    (no OpenCV) — callers that need ink geometry must check first.
    """

    bgr: Any
    gray: Any
    binary: Any
    text_band: Any  # cropped binary of the text region
    band_origin: tuple[int, int]  # (x0, y0) of text_band in full page
    band_box: tuple[int, int, int, int]  # x0,y0,x1,y1


def deskew_gray(gray):
    """Light deskew via min-area rect on ink pixels (no-op if angle tiny)."""
    import cv2

    inv = cv2.bitwise_not(gray)
    coords = cv2.findNonZero(inv)
    if coords is None or len(coords) < 100:
        return gray
    rect = cv2.minAreaRect(coords)
    angle = rect[-1]
    if angle < -45:
        angle = 90 + angle
    if abs(angle) < 0.3 or abs(angle) > 15:
        return gray
    h, w = gray.shape[:2]
    matrix = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    return cv2.warpAffine(
        gray, matrix, (w, h),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_REPLICATE,
    )


def strip_frame(bgr):
    """Whiten the page frame and everything outside its inner rule.

    The frame (and its ornament band) is the connected ink that spans most of
    the page in both directions; text never does. After removing it, the
    background component around the page centre is the area inside the inner
    rule, so everything else (rules, ornaments between rules, headers, page
    numbers, catchwords) goes white. Returns ``bgr`` unchanged when no closed
    frame is found, so a broken scan degrades to the old behaviour.
    """
    import cv2
    import numpy as np

    h, w = bgr.shape[:2]
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    _t, ink = cv2.threshold(gray, 0, 1, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    n, labels, stats, _c = cv2.connectedComponentsWithStats(ink, connectivity=8)
    frame_ids = [
        i for i in range(1, n)
        if stats[i, cv2.CC_STAT_WIDTH] >= 0.4 * w
        and stats[i, cv2.CC_STAT_HEIGHT] >= 0.4 * h
    ]
    if not frame_ids:
        return bgr
    frame = np.isin(labels, frame_ids)
    # The rule's anti-aliased edge is lighter than the Otsu cut, so grow the
    # mask or a grey halo survives and the adaptive threshold reads it as ink.
    frame = cv2.dilate(frame.astype(np.uint8), np.ones((9, 9), np.uint8)).astype(bool)
    free = (~frame).astype(np.uint8)
    m, comp, cstats, _cc = cv2.connectedComponentsWithStats(free, connectivity=4)
    # Inside = every large free region that does not touch the page border
    # (the page outside the frame does; the thin pockets between the rules
    # are tiny). A surah banner that splits the inside in two keeps both.
    inside = []
    for i in range(1, m):
        x, y, bw, bh, area = (int(v) for v in cstats[i])
        touches = x == 0 or y == 0 or x + bw >= w or y + bh >= h
        if not touches and area >= 0.04 * h * w:
            inside.append(i)
    if not inside:
        return bgr
    xs0 = min(int(cstats[i, cv2.CC_STAT_LEFT]) for i in inside)
    xs1 = max(int(cstats[i, cv2.CC_STAT_LEFT] + cstats[i, cv2.CC_STAT_WIDTH]) for i in inside)
    ys0 = min(int(cstats[i, cv2.CC_STAT_TOP]) for i in inside)
    ys1 = max(int(cstats[i, cv2.CC_STAT_TOP] + cstats[i, cv2.CC_STAT_HEIGHT]) for i in inside)
    if xs1 - xs0 < 0.4 * w or ys1 - ys0 < 0.4 * h or xs1 - xs0 > 0.97 * w:
        return bgr  # nothing sensible, or the rule leaked
    out = np.full_like(bgr, 255)
    keep = np.isin(comp, inside)
    out[keep] = bgr[keep]
    return out


def preprocess_page(bgr, spec: EditionSpec, page: int | None = None) -> PreparedPage:
    import cv2

    if bgr is None or bgr.size == 0:
        raise ValueError('empty page image')
    if spec.strip_frame:
        bgr = strip_frame(bgr)
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    gray = deskew_gray(gray)
    gray = cv2.GaussianBlur(gray, (3, 3), 0)
    binary = cv2.adaptiveThreshold(
        gray, 255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV,
        31, 12,
    )
    h, w = binary.shape[:2]
    x0 = int(w * spec.text_left)
    x1 = int(w * spec.text_right)
    top, bottom = spec.band_for_page(page)
    y0 = int(h * top)
    y1 = int(h * bottom)
    band = binary[y0:y1, x0:x1].copy()
    return PreparedPage(
        bgr=bgr,
        gray=gray,
        binary=binary,
        text_band=band,
        band_origin=(x0, y0),
        band_box=(x0, y0, x1, y1),
    )


def synthetic_prepared_page(
    spec: EditionSpec,
    *,
    width: int = 1024,
    height: int = 1536,
    page: int | None = None,
) -> PreparedPage:
    """Band geometry only — used when OpenCV / page images are unavailable."""
    x0 = int(width * spec.text_left)
    x1 = int(width * spec.text_right)
    top, bottom = spec.band_for_page(page)
    y0 = int(height * top)
    y1 = int(height * bottom)
    return PreparedPage(
        bgr=None,
        gray=None,
        binary=None,
        text_band=None,
        band_origin=(x0, y0),
        band_box=(x0, y0, x1, y1),
    )


def load_bgr(path):
    import cv2

    img = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if img is None:
        raise FileNotFoundError(f'cannot read image: {path}')
    return img
