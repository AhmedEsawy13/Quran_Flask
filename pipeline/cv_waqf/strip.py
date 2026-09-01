"""Above-word strip detector: geometry + OpenCV 5 DNN inference.

Printed Hafs stops sit in the band *above* the word body, near the RTL end —
the same region ``line_gaps`` already searches. Classifying that strip (one
per layout word) keeps letter-body ink and neighboring harakat in context,
instead of feeding an isolated 48×48 connected-component crop to an MLP.

Inference is OpenCV DNN + ONNX. PyTorch is train-only (see train_strip).
"""
from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np

from pipeline.cv_waqf import CLASSES
from pipeline.cv_waqf.config import (
    CROP_SIZE,
    EDITION_STRIP_MODEL_PATHS,
    STRIP_HEIGHT,
    STRIP_WIDTH,
)
from pipeline.cv_waqf.layout_geo import LayoutWord

# Three 3×3 convs + 2×2 pools → spatial /8. Channels stay tiny so a local
# train on ~44 Bahrain pages is not a 100k-parameter net.
STRIP_CONV_CHANNELS: tuple[int, int, int] = (8, 16, 16)
STRIP_CONV_KERNEL = 3
STRIP_POOL = 2
STRIP_POOL_STAGES = 3


def strip_spatial_after_pools(
    height: int = STRIP_HEIGHT,
    width: int = STRIP_WIDTH,
) -> tuple[int, int]:
    """Feature-map size after ``STRIP_POOL_STAGES`` stride-2 pools."""
    h, w = int(height), int(width)
    for _ in range(STRIP_POOL_STAGES):
        h //= STRIP_POOL
        w //= STRIP_POOL
    if h < 1 or w < 1:
        raise ValueError(f'strip {height}×{width} is too small for {STRIP_POOL_STAGES} pools')
    return h, w


def strip_flatten_size(
    height: int = STRIP_HEIGHT,
    width: int = STRIP_WIDTH,
    channels: tuple[int, int, int] = STRIP_CONV_CHANNELS,
) -> int:
    fh, fw = strip_spatial_after_pools(height, width)
    return int(channels[-1]) * fh * fw


def above_word_strip_roi(word: LayoutWord) -> tuple[int, int, int, int]:
    """Pixel box of the band above the RTL end of a layout word.

    Matches ``sample_crops._above_end_roi`` / the search window in
    ``line_gaps._above_roi``: above the letter skeleton, biased to the
    left edge (word end in RTL), not a full-word or mid-body crop.
    """
    return above_word_strip_roi_from_box(
        word.x0, word.y0, word.x1, word.y1, line_y0=word.y0,
    )


def above_word_strip_roi_from_box(
    word_x0: int,
    word_y0: int,
    word_x1: int,
    word_y1: int,
    *,
    line_y0: int | None = None,
) -> tuple[int, int, int, int]:
    """Same band as ``line_gaps``: above the body, near the RTL end."""
    line_h = max(12, int(word_y1) - int(word_y0))
    width = max(8, int(word_x1) - int(word_x0))
    top = int(word_y0) if line_y0 is None else min(int(word_y0), int(line_y0))
    y0 = top - int(0.45 * line_h)
    y1 = int(word_y0) + int(0.20 * line_h)
    end_w = max(14, int(0.42 * width))
    pad_left = max(8, int(0.15 * width))
    x0 = int(word_x0) - pad_left
    x1 = int(word_x0) + end_w
    return x0, y0, x1, y1


def crop_above_word_strip(
    gray: np.ndarray,
    word: LayoutWord,
    *,
    width: int = STRIP_WIDTH,
    height: int = STRIP_HEIGHT,
) -> np.ndarray:
    """Letterbox the above-word band into a fixed ``height×width`` uint8 crop."""
    return crop_strip_roi(
        gray, above_word_strip_roi(word), width=width, height=height,
    )


def crop_strip_roi(
    gray: np.ndarray,
    roi: tuple[int, int, int, int],
    *,
    width: int = STRIP_WIDTH,
    height: int = STRIP_HEIGHT,
) -> np.ndarray:
    """Extract ``roi`` from grayscale and letterbox into ``height×width``."""
    if gray.ndim == 3:
        gray = cv2.cvtColor(gray, cv2.COLOR_BGR2GRAY)
    img_h, img_w = gray.shape[:2]
    x0, y0, x1, y1 = roi
    x0, y0 = max(0, int(x0)), max(0, int(y0))
    x1, y1 = min(img_w, int(x1)), min(img_h, int(y1))
    canvas = np.full((height, width), 255, dtype=np.uint8)
    if x1 <= x0 or y1 <= y0:
        return canvas
    patch = gray[y0:y1, x0:x1]
    if patch.size == 0:
        return canvas
    ph, pw = patch.shape[:2]
    scale = min(width / max(1, pw), height / max(1, ph))
    nw = max(1, int(round(pw * scale)))
    nh = max(1, int(round(ph * scale)))
    nw, nh = min(nw, width), min(nh, height)
    resized = cv2.resize(patch, (nw, nh), interpolation=cv2.INTER_AREA)
    oy = (height - nh) // 2
    ox = (width - nw) // 2
    canvas[oy:oy + nh, ox:ox + nw] = resized
    return canvas


def preprocess_strip(
    gray_strip: np.ndarray,
    *,
    height: int = STRIP_HEIGHT,
    width: int = STRIP_WIDTH,
) -> np.ndarray:
    """float32 NCHW in [0, 1] with ink-as-positive (pages are dark-on-light)."""
    img = gray_strip
    if img.ndim == 3:
        img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    if img.shape[0] != height or img.shape[1] != width:
        img = cv2.resize(img, (width, height), interpolation=cv2.INTER_AREA)
    x = img.astype(np.float32) / 255.0
    x = 1.0 - x
    return x.reshape(1, 1, height, width)


def is_strip_model(path: Path | str) -> bool:
    """True when the sidecar (or filename) says this ONNX is a strip net."""
    model_path = Path(path)
    meta_path = model_path.with_suffix('.json')
    if meta_path.is_file():
        try:
            payload = json.loads(meta_path.read_text(encoding='utf-8'))
        except json.JSONDecodeError:
            payload = {}
        pipeline = str(payload.get('pipeline') or '')
        detector = str(payload.get('detector') or '')
        if pipeline == 'strip' or detector == 'strip':
            return True
        if pipeline in {'two-stage', 'single-stage', 'binary-gate'}:
            return False
        if (
            int(payload.get('crop_size') or 0) == CROP_SIZE
            and payload.get('strip_width') is None
        ):
            return False
    return 'strip' in model_path.stem.lower()


def strip_model_path_for_edition(
    edition_key: str,
    *,
    model_path: Path | str | None = None,
    strip_model_path: Path | str | None = None,
) -> Path | None:
    """ONNX to use for the strip detector, or None to keep the CC-crop MLP.

    An explicit ``--model`` pointing at the gated MLP (or any non-strip net)
    disables auto strip even if ``waqf_strip_bahrain.onnx`` exists, so
    evaluate-hand A/B stays possible.
    """
    if strip_model_path is not None:
        return Path(strip_model_path)
    if model_path is not None:
        path = Path(model_path)
        if is_strip_model(path):
            return path
        return None
    auto = EDITION_STRIP_MODEL_PATHS.get(edition_key)
    if auto is not None and auto.is_file():
        return auto
    return None


class StripClassifier:
    """Small conv net over a fixed above-word strip (OpenCV 5 DNN)."""

    def __init__(self, model_path: Path | None = None):
        self.model_path = Path(
            model_path
            or EDITION_STRIP_MODEL_PATHS['البحرين']
        )
        self.classes: list[str] = list(CLASSES)
        self.pipeline = 'strip'
        self.height = STRIP_HEIGHT
        self.width = STRIP_WIDTH
        self.net = None
        payload: dict = {}
        meta_path = self.model_path.with_suffix('.json')
        if meta_path.is_file():
            payload = json.loads(meta_path.read_text(encoding='utf-8'))
            self.classes = list(payload.get('classes') or CLASSES)
            self.height = int(payload.get('strip_height') or STRIP_HEIGHT)
            self.width = int(payload.get('strip_width') or STRIP_WIDTH)
        if self.model_path.is_file():
            self.net = self._load_net(self.model_path)

    @staticmethod
    def _load_net(path: Path):
        kwargs = {}
        if hasattr(cv2.dnn, 'ENGINE_AUTO'):
            kwargs['engine'] = cv2.dnn.ENGINE_AUTO
        try:
            return cv2.dnn.readNet(str(path), **kwargs)
        except TypeError:
            return cv2.dnn.readNet(str(path))

    @property
    def ready(self) -> bool:
        return self.net is not None

    @staticmethod
    def _softmax_rows(logits: np.ndarray) -> np.ndarray:
        shifted = logits - logits.max(axis=1, keepdims=True)
        probs = np.exp(shifted)
        return probs / probs.sum(axis=1, keepdims=True)

    def predict_many_probs(
        self, gray_strips: list[np.ndarray],
    ) -> list[tuple[str, float, np.ndarray]]:
        if not gray_strips:
            return []
        zeros = np.zeros(len(self.classes), dtype=np.float32)
        if not self.ready:
            return [('none', 0.0, zeros.copy()) for _ in gray_strips]
        blob = np.concatenate(
            [
                preprocess_strip(strip, height=self.height, width=self.width)
                for strip in gray_strips
            ],
            axis=0,
        )
        self.net.setInput(blob)
        logits = np.asarray(self.net.forward(), dtype=np.float32)
        logits = logits.reshape(len(gray_strips), -1)
        results: list[tuple[str, float, np.ndarray]] = []
        for row in logits:
            if row.size != len(self.classes):
                results.append(('none', 0.0, zeros.copy()))
                continue
            probs = self._softmax_rows(row.reshape(1, -1))[0]
            idx = int(probs.argmax())
            results.append((self.classes[idx], float(probs[idx]), probs))
        return results

    def predict_probs(
        self, gray_strip: np.ndarray,
    ) -> tuple[str, float, np.ndarray]:
        return self.predict_many_probs([gray_strip])[0]

    def predict_crop(self, gray_strip: np.ndarray) -> tuple[str, float]:
        label, conf, _probs = self.predict_probs(gray_strip)
        return label, conf
