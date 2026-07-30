"""Line-by-line waqf detection in the band *above* each word body.

Printed Hafs stops usually sit above a word (often near its RTL end). They are
sometimes near a gap, but not reliably *between* words. Harakat sit on the
letters themselves — lower in the line, inside the word body — so we only
search the upper strip over each segmented word.
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from pipeline.cv_waqf.candidates import Candidate
from pipeline.cv_waqf.layout_geo import LayoutWord
from pipeline.cv_waqf.preprocess import PreparedPage


@dataclass
class WordCluster:
    x0: int
    y0: int
    x1: int
    y1: int
    area: int

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2.0

    @property
    def cy(self) -> float:
        return (self.y0 + self.y1) / 2.0

    @property
    def w(self) -> int:
        return max(1, self.x1 - self.x0)

    @property
    def h(self) -> int:
        return max(1, self.y1 - self.y0)


@dataclass
class AboveWordHit:
    candidate: Candidate
    line_number: int
    layout_word: LayoutWord | None
    cluster_index: int  # 0 = rightmost on the line


def _line_groups(words: list[LayoutWord]) -> dict[int, list[LayoutWord]]:
    groups: dict[int, list[LayoutWord]] = {}
    for w in words:
        groups.setdefault(int(w.line_number), []).append(w)
    for line_no, group in groups.items():
        group.sort(key=lambda w: (w.word_on_line, -w.cx))
        groups[line_no] = group
    return groups


def _ccs_in_roi(binary: np.ndarray, x0: int, y0: int, x1: int, y1: int) -> list[tuple]:
    h, w = binary.shape[:2]
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(w, x1), min(h, y1)
    if x1 <= x0 or y1 <= y0:
        return []
    roi = binary[y0:y1, x0:x1]
    if roi.size == 0:
        return []
    num, _labels, stats, _ = cv2.connectedComponentsWithStats(roi, connectivity=8)
    out = []
    for label in range(1, num):
        rx, ry, rw, rh, area = (int(v) for v in stats[label])
        out.append((x0 + rx, y0 + ry, rw, rh, area))
    return out


def _cluster_word_bodies(
    bodies: list[tuple[int, int, int, int, int]],
    *,
    merge_gap: int,
) -> list[WordCluster]:
    if not bodies:
        return []
    boxes = sorted(bodies, key=lambda b: b[0])
    clusters: list[list[tuple[int, int, int, int, int]]] = [[boxes[0]]]
    for box in boxes[1:]:
        prev = clusters[-1]
        px1 = max(b[0] + b[2] for b in prev)
        if box[0] - px1 <= merge_gap:
            clusters[-1].append(box)
        else:
            clusters.append([box])
    out: list[WordCluster] = []
    for group in clusters:
        out.append(WordCluster(
            x0=min(b[0] for b in group),
            y0=min(b[1] for b in group),
            x1=max(b[0] + b[2] for b in group),
            y1=max(b[1] + b[3] for b in group),
            area=sum(b[4] for b in group),
        ))
    return out


def _match_clusters_to_layout(
    clusters_rtl: list[WordCluster],
    layout_words: list[LayoutWord],
) -> list[LayoutWord | None]:
    if not clusters_rtl:
        return []
    if len(clusters_rtl) == len(layout_words):
        return list(layout_words)
    matched: list[LayoutWord | None] = []
    used: set[int] = set()
    for cl in clusters_rtl:
        best = None
        best_d = float('inf')
        best_i = -1
        for i, lw in enumerate(layout_words):
            if i in used:
                continue
            d = abs(cl.cx - lw.cx)
            if d < best_d:
                best_d = d
                best = lw
                best_i = i
        if best is not None:
            used.add(best_i)
        matched.append(best)
    return matched


def _above_roi(cluster: WordCluster, line_y0: int, line_h: int) -> tuple[int, int, int, int]:
    """Band above the *end* of the word (RTL left side), not the whole word.

    Harakat (فتحة/ضمة) sit on every letter across the word. Stops sit once,
    above the word end — sometimes drifting a little into the left gap.
    """
    y0 = max(line_y0, cluster.y0 - int(0.50 * line_h))
    # Stay above the letter skeleton; do not reach mid-body harakat.
    y1 = min(cluster.y0 + int(0.22 * cluster.h), cluster.y0 + int(0.28 * line_h))

    end_w = max(12, int(0.38 * cluster.w))
    pad_left = max(6, int(0.12 * cluster.w))
    # Left side of the word (= end in RTL) plus a small outward pad.
    x0 = cluster.x0 - pad_left
    x1 = cluster.x0 + end_w
    return x0, y0, x1, y1


def find_above_word_candidates(
    prepared: PreparedPage,
    words: list[LayoutWord],
) -> list[AboveWordHit]:
    """Find waqf-sized ink in the strip above each CV-segmented word, per line."""
    if not words:
        return []
    binary = prepared.binary
    hits: list[AboveWordHit] = []
    seen: set[tuple[int, int, int, int]] = set()

    for line_no, layout_words in sorted(_line_groups(words).items()):
        if not layout_words:
            continue
        y0 = min(w.y0 for w in layout_words) - 4
        y1 = max(w.y1 for w in layout_words) + 4
        x0 = prepared.band_box[0]
        x1 = prepared.band_box[2]
        line_h = max(12, y1 - y0)

        ccs = _ccs_in_roi(binary, x0, y0, x1, y1)
        if not ccs:
            continue

        body_min_h = max(10, int(0.30 * line_h))
        body_min_area = max(36, int(0.010 * line_h * (x1 - x0) / max(1, len(layout_words))))
        bodies = [
            (x, y, w, h, a) for x, y, w, h, a in ccs
            if h >= body_min_h or (a >= body_min_area and h >= int(0.20 * line_h))
        ]
        merge_gap = max(6, int(0.10 * line_h))
        clusters = _cluster_word_bodies(bodies, merge_gap=merge_gap)
        if not clusters:
            continue

        clusters_rtl = sorted(clusters, key=lambda c: -c.cx)
        layout_matched = _match_clusters_to_layout(clusters_rtl, layout_words)

        mark_min = max(8, int(0.12 * line_h))
        mark_max = max(mark_min + 2, int(0.48 * line_h))
        mark_min_area = max(30, mark_min * mark_min // 3)

        for idx, cluster in enumerate(clusters_rtl):
            ax0, ay0, ax1, ay1 = _above_roi(cluster, y0, line_h)
            layout_word = layout_matched[idx] if idx < len(layout_matched) else None

            local: list[Candidate] = []
            for x, y, w, h, a in ccs:
                if not (mark_min <= max(w, h) <= mark_max and a >= mark_min_area):
                    continue
                if max(w, h) / max(1, min(w, h)) > 2.6:
                    continue
                cx = x + w / 2.0
                cy = y + h / 2.0
                if not (ax0 <= cx <= ax1 and ay0 <= cy <= ay1):
                    continue
                # Must sit mostly above the letter top — reject on-body tashkeel.
                if cy > cluster.y0 + int(0.18 * cluster.h):
                    continue
                key = (x, y, w, h)
                if key in seen:
                    continue
                local.append(Candidate(
                    x=x, y=y, w=w, h=h, area=a,
                    score=float(a) / max(1, w * h) + 0.01 * max(w, h),
                ))

            if not local:
                roi = binary[
                    max(0, ay0):max(0, ay1),
                    max(0, ax0):max(0, ax1),
                ]
                if roi.size and int(roi.sum()) >= 255 * 20:
                    ys, xs = np.where(roi > 0)
                    if len(xs) >= 12:
                        tx0 = int(xs.min()) + max(0, ax0)
                        ty0 = int(ys.min()) + max(0, ay0)
                        tx1 = int(xs.max()) + 1 + max(0, ax0)
                        ty1 = int(ys.max()) + 1 + max(0, ay0)
                        tw, th = tx1 - tx0, ty1 - ty0
                        if mark_min <= max(tw, th) <= mark_max and ty1 <= cluster.y0 + 3:
                            local.append(Candidate(
                                x=tx0, y=ty0, w=tw, h=th,
                                area=int(len(xs)), score=0.4,
                            ))

            if not local:
                continue
            # At most one stop per word — keep the strongest blob in the end-band.
            best = max(local, key=lambda c: (c.score, c.area, max(c.w, c.h)))
            key = (best.x, best.y, best.w, best.h)
            if key in seen:
                continue
            seen.add(key)
            hits.append(AboveWordHit(
                candidate=best,
                line_number=line_no,
                layout_word=layout_word,
                cluster_index=idx,
            ))

    hits.sort(key=lambda h: (h.line_number, h.cluster_index, -h.candidate.score))
    return hits


# Back-compat alias while callers migrate.
find_gap_candidates = find_above_word_candidates
GapHit = AboveWordHit
