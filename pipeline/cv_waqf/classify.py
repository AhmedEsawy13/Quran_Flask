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
    """One-stage or binary-gated waqf glyph classifier."""

    def __init__(
        self,
        model_path: Path | None = None,
        classes_path: Path | None = None,
    ):
        self.model_path = Path(model_path or MODEL_PATH)
        self.classes_path = Path(classes_path or CLASSES_PATH)
        self.classes: list[str] = list(CLASSES)
        self.symbol_classes: list[str] = list(CLASSES)
        self.pipeline = 'single-stage'
        self.gate_net = None
        self.gate_classes = ['none', 'mark']
        self.gate_mode = 'probability'
        self.gate_min_conf = 0.5
        payload: dict = {}
        model_meta = self.model_path.with_suffix('.json')
        if model_meta.is_file():
            payload = json.loads(model_meta.read_text(encoding='utf-8'))
        elif self.classes_path.is_file():
            payload = json.loads(self.classes_path.read_text(encoding='utf-8'))

        if payload.get('pipeline') == 'two-stage':
            self.pipeline = 'two-stage'
            self.classes = list(payload.get('full_classes') or CLASSES)
            self.symbol_classes = list(
                payload.get('classes')
                or [label for label in self.classes if label != 'none']
            )
            self.gate_classes = list(
                payload.get('gate_classes') or ['none', 'mark']
            )
            self.gate_mode = str(payload.get('gate_mode') or 'probability')
            self.gate_min_conf = float(payload.get('gate_min_conf') or 0.5)
            gate_name = payload.get('gate_model')
            if gate_name:
                gate_path = self.model_path.parent / str(gate_name)
                if gate_path.is_file():
                    self.gate_net = self._load_net(gate_path)
        else:
            self.classes = list(payload.get('classes') or CLASSES)
            self.symbol_classes = list(self.classes)
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
        return self.net is not None and (
            self.pipeline != 'two-stage' or self.gate_net is not None
        )

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
        return self.predict_many_probs([gray_crop])[0]

    @staticmethod
    def _softmax_rows(logits: np.ndarray) -> np.ndarray:
        shifted = logits - logits.max(axis=1, keepdims=True)
        probs = np.exp(shifted)
        return probs / probs.sum(axis=1, keepdims=True)

    def predict_many_probs(
        self, gray_crops: list[np.ndarray],
    ) -> list[tuple[str, float, np.ndarray]]:
        """Classify a page's proposals in one OpenCV DNN batch."""
        if not gray_crops:
            return []
        if not self.ready:
            zeros = np.zeros(len(self.classes), dtype=np.float32)
            return [('none', 0.0, zeros.copy()) for _ in gray_crops]
        blob = np.concatenate(
            [self.preprocess_crop(crop) for crop in gray_crops], axis=0,
        )
        self.net.setInput(blob)
        logits = np.asarray(self.net.forward(), dtype=np.float32)
        logits = logits.reshape(len(gray_crops), -1)
        if self.pipeline == 'two-stage':
            return self._predict_many_two_stage(blob, logits)
        results: list[tuple[str, float, np.ndarray]] = []
        for row in logits:
            if row.size != len(self.classes):
                zeros = np.zeros(len(self.classes), dtype=np.float32)
                results.append(('none', 0.0, zeros))
                continue
            probs = self._softmax_rows(row.reshape(1, -1))[0]
            idx = int(probs.argmax())
            results.append((self.classes[idx], float(probs[idx]), probs))
        return results

    def _predict_many_two_stage(
        self,
        blob: np.ndarray,
        symbol_logits: np.ndarray,
    ) -> list[tuple[str, float, np.ndarray]]:
        count = len(blob)
        if (
            self.gate_net is None
            or symbol_logits.shape[1] != len(self.symbol_classes)
        ):
            zeros = np.zeros(len(self.classes), dtype=np.float32)
            return [('none', 0.0, zeros.copy()) for _ in range(count)]
        self.gate_net.setInput(blob)
        gate_logits = np.asarray(self.gate_net.forward(), dtype=np.float32)
        gate_logits = gate_logits.reshape(count, -1)
        if gate_logits.shape[1] != len(self.gate_classes):
            zeros = np.zeros(len(self.classes), dtype=np.float32)
            return [('none', 0.0, zeros.copy()) for _ in range(count)]

        symbol_probs = self._softmax_rows(symbol_logits)
        gate_probs = self._softmax_rows(gate_logits)
        none_gate_idx = self.gate_classes.index('none')
        mark_gate_idx = self.gate_classes.index('mark')
        none_idx = self.classes.index('none')
        results: list[tuple[str, float, np.ndarray]] = []
        for gate_row, symbol_row in zip(gate_probs, symbol_probs):
            combined = np.zeros(len(self.classes), dtype=np.float32)
            none_probability = float(gate_row[none_gate_idx])
            mark_probability = float(gate_row[mark_gate_idx])
            # When the second stage is an existing classifier that already
            # has a `none` output, the gate is a strict veto: both models must
            # agree that the crop is a mark. This prevents the gate from
            # turning an old `none` prediction into a confidently wrong mark.
            if 'none' in self.symbol_classes:
                symbol_none_idx = self.symbol_classes.index('none')
                if self.gate_mode == 'veto':
                    symbol_idx = int(symbol_row.argmax())
                    symbol = self.symbol_classes[symbol_idx]
                    if (
                        symbol != 'none'
                        and mark_probability >= self.gate_min_conf
                    ):
                        results.append(
                            (symbol, float(symbol_row[symbol_idx]), symbol_row)
                        )
                    else:
                        rejected = np.zeros(
                            len(self.classes), dtype=np.float32,
                        )
                        rejected[none_idx] = 1.0
                        results.append(('none', 1.0, rejected))
                    continue
                combined[none_idx] = (
                    none_probability
                    + mark_probability * float(symbol_row[symbol_none_idx])
                )
                for symbol, probability in zip(
                    self.symbol_classes, symbol_row,
                ):
                    if symbol in self.classes and symbol != 'none':
                        combined[self.classes.index(symbol)] = (
                            mark_probability * float(probability)
                        )
                idx = int(combined.argmax())
                results.append(
                    (self.classes[idx], float(combined[idx]), combined)
                )
                continue

            combined[none_idx] = none_probability
            mark_total = sum(
                float(probability)
                for symbol, probability in zip(
                    self.symbol_classes, symbol_row,
                )
                if symbol != 'none'
            )
            if mark_total <= 0.0:
                results.append(('none', float(combined[none_idx]), combined))
                continue
            for symbol, probability in zip(self.symbol_classes, symbol_row):
                if symbol in self.classes and symbol != 'none':
                    combined[self.classes.index(symbol)] = (
                        mark_probability * float(probability) / mark_total
                    )
            idx = int(combined.argmax())
            results.append(
                (self.classes[idx], float(combined[idx]), combined)
            )
        return results

    def classify_candidates(
        self,
        gray: np.ndarray,
        candidates: list[Candidate],
        *,
        min_conf: float = 0.45,
    ) -> list[tuple[Candidate, str, float]]:
        crops = [
            crop_candidate(gray, cand, size=CROP_SIZE) for cand in candidates
        ]
        results: list[tuple[Candidate, str, float]] = []
        for cand, (label, conf, _probs) in zip(
            candidates, self.predict_many_probs(crops),
        ):
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
