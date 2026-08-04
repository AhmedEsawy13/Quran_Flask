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


def preprocess_page(bgr, spec: EditionSpec) -> PreparedPage:
    import cv2

    if bgr is None or bgr.size == 0:
        raise ValueError('empty page image')
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
    y0 = int(h * spec.text_top)
    y1 = int(h * spec.text_bottom)
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
) -> PreparedPage:
    """Band geometry only — used when OpenCV / page images are unavailable."""
    x0 = int(width * spec.text_left)
    x1 = int(width * spec.text_right)
    y0 = int(height * spec.text_top)
    y1 = int(height * spec.text_bottom)
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
