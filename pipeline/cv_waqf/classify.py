"""ONNX glyph classifier via OpenCV 5 DNN (ENGINE_AUTO)."""
from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np

from pipeline.cv_waqf import CLASSES
from pipeline.cv_waqf.candidates import Candidate, crop_candidate
from pipeline.cv_waqf.config import CLASSES_PATH, CROP_SIZE, MODEL_PATH


class GlyphClassifier:
    """Softmax classifier over waqf letter codes + ``none``."""

    def __init__(
        self,
        model_path: Path | None = None,
        classes_path: Path | None = None,
    ):
        self.model_path = Path(model_path or MODEL_PATH)
        self.classes_path = Path(classes_path or CLASSES_PATH)
        self.classes: list[str] = list(CLASSES)
        if self.classes_path.is_file():
            payload = json.loads(self.classes_path.read_text(encoding='utf-8'))
            self.classes = list(payload.get('classes') or CLASSES)
        self.net = None
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
            # Older bindings may not accept engine=; OpenCV 5 should.
            return cv2.dnn.readNet(str(path))

    @property
    def ready(self) -> bool:
        return self.net is not None

    def preprocess_crop(self, gray_crop: np.ndarray) -> np.ndarray:
        img = gray_crop
        if img.shape[0] != CROP_SIZE or img.shape[1] != CROP_SIZE:
            img = cv2.resize(img, (CROP_SIZE, CROP_SIZE), interpolation=cv2.INTER_AREA)
        # Match training: float32 in [0,1], shape NCHW with 1 channel.
        x = img.astype(np.float32) / 255.0
        x = 1.0 - x  # ink-as-positive (pages are dark-on-light)
        return x.reshape(1, 1, CROP_SIZE, CROP_SIZE)

    def predict_crop(self, gray_crop: np.ndarray) -> tuple[str, float]:
        label, conf, _probs = self.predict_probs(gray_crop)
        return label, conf

    def predict_probs(
        self, gray_crop: np.ndarray,
    ) -> tuple[str, float, np.ndarray]:
        if not self.ready:
            zeros = np.zeros(len(self.classes), dtype=np.float32)
            return 'none', 0.0, zeros
        blob = self.preprocess_crop(gray_crop)
        self.net.setInput(blob)
        out = self.net.forward()
        logits = np.asarray(out).reshape(-1).astype(np.float32)
        if logits.size != len(self.classes):
            zeros = np.zeros(len(self.classes), dtype=np.float32)
            if logits.size < len(self.classes):
                return 'none', 0.0, zeros
            logits = logits[: len(self.classes)]
        logits = logits - logits.max()
        probs = np.exp(logits)
        probs = probs / probs.sum()
        idx = int(probs.argmax())
        return self.classes[idx], float(probs[idx]), probs

    def classify_candidates(
        self,
        gray: np.ndarray,
        candidates: list[Candidate],
        *,
        min_conf: float = 0.45,
    ) -> list[tuple[Candidate, str, float]]:
        results: list[tuple[Candidate, str, float]] = []
        for cand in candidates:
            crop = crop_candidate(gray, cand, size=CROP_SIZE)
            label, conf = self.predict_crop(crop)
            if label == 'none' or conf < min_conf:
                continue
            results.append((cand, label, conf))
        return results


def save_classes(path: Path | None = None, classes: list[str] | None = None) -> Path:
    path = Path(path or CLASSES_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {'classes': list(classes or CLASSES), 'crop_size': CROP_SIZE}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    return path
