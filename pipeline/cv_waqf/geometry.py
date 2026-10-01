"""Measured page geometry: text rows and word cuts read from the page ink.

``layout_geo`` places words from the layout DB alone, using per-edition text
band fractions and letter-count widths. That is only as good as the constants,
and the ornamental frame of a print leaks into the estimate. This module
measures instead, so the same code works on any print whose layout DB says
which words are on which line:

* ``text_ink_mask`` keeps black, unsaturated ink and drops coloured frames and
  full-width/full-height rules.
* ``fit_line_grid`` fits the text block's top and line pitch to the measured
  rows (robust to header rows and missing lines).
* ``segment_line_words`` cuts a line into its words by choosing, among the
  measured inter-word gaps, the ones that best agree with the expected widths.

Everything here is pure numpy/OpenCV and edition-agnostic; the only tuned
constant is ``LINE_CENTER_BIAS`` (see its comment).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

# Black text: dark and unsaturated. Frames are red/gold/brown (saturated).
INK_V_MAX = 110
INK_S_MAX = 90

# Where a line's measured ink centre sits relative to the slot the rest of the
# pipeline uses, as a fraction of the pitch. The slot convention (word boxes
# reach above the letter body so the mark band is inside them) was tuned on
# Bahrain; expressing it as a bias keeps the tuning relative to the ink, not
# to one print's page margins. Set by ``calibrate_line_center_bias``.
LINE_CENTER_BIAS = 0.56

# How far (in line pitches) the fitted text top may move from the nominal one.
DEFAULT_REACH = 0.5


def text_ink_mask(bgr: np.ndarray) -> np.ndarray:
    """uint8 {0,1} mask of text ink with frame rules removed."""
    import cv2

    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    mask = ((hsv[..., 2] < INK_V_MAX) & (hsv[..., 1] < INK_S_MAX)).astype(np.uint8)
    h, w = mask.shape
    # Thin frame rules run the whole width / height; text lines never do.
    central = mask[:, int(w * 0.22):int(w * 0.78)]
    mask[central.mean(axis=1) > 0.88, :] = 0
    zone = mask[int(h * 0.12):int(h * 0.90), :]
    cols = np.flatnonzero(zone.mean(axis=0) > 0.5)
    for col in cols:
        mask[:, max(0, col - 1):col + 2] = 0
    return mask


def text_x_bounds(bgr: np.ndarray, y0: int, y1: int) -> tuple[int, int]:
    """Horizontal extent of the text block, from the frame's inner edge.

    Prints box the text inside a frame. Scanning outward from the page centre
    over the text rows, the first column that is non-paper for (nearly) the
    whole height is that frame's inner edge; text columns never are, since
    interline gaps break them. A vertical closing bridges dotted rules and
    scan noise without ever closing across a line gap. Ornament outside the
    edge then cannot chain into a line. Falls back to the full width when no
    edge is found on both sides.
    """
    import cv2

    h, w = bgr.shape[:2]
    y0, y1 = max(0, int(y0)), min(h, int(y1))
    full = (0, w)
    if y1 - y0 < 100:
        return full
    gray = cv2.cvtColor(bgr[y0:y1], cv2.COLOR_BGR2GRAY)
    paper = float(np.percentile(gray[:, int(w * 0.3):int(w * 0.7)], 90))
    nonpaper = (gray < paper - 45).astype(np.uint8)
    closed = cv2.morphologyEx(
        nonpaper, cv2.MORPH_CLOSE, np.ones((13, 1), np.uint8),
    )
    edge = closed.mean(axis=0) > 0.85
    centre = w // 2
    left = np.flatnonzero(edge[:centre])
    right = np.flatnonzero(edge[centre:])
    if left.size == 0 or right.size == 0:
        return full
    lo, hi = int(left.max()) + 2, int(right.min()) + centre - 1
    if hi - lo < 0.4 * w:
        return full
    return lo, hi


@dataclass(frozen=True)
class LineGrid:
    """Text block rows: slot ``k`` spans ``top + k*pitch`` .. ``+ pitch``."""

    top: float
    pitch: float
    support: float  # share of expected lines that found a measured row
    fitted: bool    # False → nominal values returned unchanged

    def slot(self, k: int) -> tuple[int, int]:
        return int(round(self.top + k * self.pitch)), int(
            round(self.top + (k + 1) * self.pitch)
        )


def measured_line_centres(mask: np.ndarray) -> list[float]:
    """Baseline row of each ink row band, from the central columns.

    The Arabic baseline is the densest row band of a line and does not move
    with the marks above or the descenders below, so it is a steadier anchor
    than the band's centre of mass.
    """
    h, w = mask.shape
    profile = mask[:, int(w * 0.22):int(w * 0.78)].sum(axis=1).astype(float)
    smooth = np.convolve(profile, np.ones(5) / 5.0, mode='same')
    if smooth.max() <= 0:
        return []
    on = smooth > smooth.max() * 0.10
    centres: list[float] = []
    start = None
    for y, flag in enumerate(np.append(on, False)):
        if flag and start is None:
            start = y
        elif not flag and start is not None:
            if y - start > 20:
                seg = smooth[start:y]
                # Centre of the near-peak plateau, not the first peak row:
                # ties are common and would bias the baseline upward.
                near = np.flatnonzero(seg >= 0.92 * seg.max())
                centres.append(float(start + (near[0] + near[-1]) / 2.0))
            start = None
    return centres


def fit_line_grid(
    mask: np.ndarray,
    slots: list[int],
    *,
    nominal_top: float,
    nominal_pitch: float,
    center_bias: float | None = None,
    min_support: float = 0.6,
    reach: float = DEFAULT_REACH,
) -> LineGrid:
    """Fit ``(top, pitch)`` so expected line slots land on measured rows.

    ``slots`` are zero-based physical row indexes of the lines that carry
    words. Extra measured rows (surah banners, page furniture) are ignored,
    and expected lines with no row simply do not vote, so short and heading
    pages fit as well as full ones. Falls back to the nominal grid when too
    few lines have evidence.

    ``reach`` is how far (in pitches) the top may move from ``nominal_top``.
    Keep it at or under 0.5: text lines are periodic, so a wider window admits
    the grid shifted by one whole line as an equally good fit, and the fit
    then picks between the two almost at random. That makes ``nominal_top``
    matter: it must follow the slot-box convention (see ``LINE_CENTER_BIAS``),
    not the ink extent; ``calibrate-geometry`` derives it from sample pages.
    """
    bias = LINE_CENTER_BIAS if center_bias is None else center_bias
    nominal = LineGrid(nominal_top, nominal_pitch, 0.0, False)
    centres = np.asarray(measured_line_centres(mask))
    if not slots or centres.size < 3:
        return nominal
    k = np.asarray(slots, dtype=float)
    reach_px = reach * nominal_pitch
    best: tuple[float, float, float] | None = None
    for pitch in nominal_pitch * np.linspace(0.90, 1.10, 41):
        for top in np.arange(
            nominal_top - reach_px, nominal_top + reach_px + 1.0, 1.0,
        ):
            predicted = top + (k + 0.5 + bias) * pitch
            dist = np.abs(predicted[:, None] - centres[None, :]).min(axis=1)
            cap = 0.5 * pitch
            cost = float(np.minimum(dist, cap).sum())
            if best is None or cost < best[0]:
                best = (cost, float(top), float(pitch))
    assert best is not None
    _cost, top, pitch = best
    predicted = top + (k + 0.5 + bias) * pitch
    dist = np.abs(predicted[:, None] - centres[None, :]).min(axis=1)
    support = float((dist < 0.35 * pitch).mean())
    if support < min_support:
        return LineGrid(nominal_top, nominal_pitch, support, False)
    return LineGrid(top, pitch, support, True)


def _ink_extent(
    occupied: np.ndarray, max_gap: int,
) -> tuple[int, int] | None:
    """Left/right of the heaviest chain of ink columns.

    Columns closer than ``max_gap`` chain together (word spaces, kashida);
    the specks a frame leaves outside the text are further away than that and
    form their own light chains.
    """
    cols = np.flatnonzero(occupied)
    if cols.size == 0:
        return None
    breaks = np.flatnonzero(np.diff(cols) > max_gap)
    starts = np.concatenate(([0], breaks + 1))
    ends = np.concatenate((breaks + 1, [cols.size]))
    best = max(range(starts.size), key=lambda i: ends[i] - starts[i])
    chain = cols[starts[best]:ends[best]]
    return int(chain[0]), int(chain[-1])


def segment_line_words(
    mask: np.ndarray,
    *,
    baseline: float,
    pitch: float,
    weights: list[float],
    x_range: tuple[int, int],
    position_sigma: float = 0.06,
    virtual_penalty: float = 1.5,
    gap_reward: float = 1.0,
) -> list[tuple[int, int]] | None:
    """Cut one printed line into ``len(weights)`` word spans, RTL order.

    Candidate cuts are the measured empty column runs inside the line's ink
    extent. A monotone DP picks the ``N-1`` cuts that best match the expected
    cumulative widths, preferring wide gaps (real word spaces are wider than
    the breaks after non-joining letters). If the line has fewer gaps than
    needed, virtual cuts at the expected positions fill in, at a penalty, so
    the result always has one span per word. Returns ``None`` when the line
    has no measurable ink.
    """
    n = len(weights)
    if n == 0:
        return None
    h, _w = mask.shape
    y0 = max(0, int(baseline - 0.50 * pitch))
    y1 = min(h, int(baseline + 0.22 * pitch))
    lo, hi = max(0, x_range[0]), min(mask.shape[1], x_range[1])
    if y1 <= y0 or hi <= lo:
        return None
    occupied = mask[y0:y1, lo:hi].any(axis=0)
    extent = _ink_extent(occupied, max_gap=max(8, int(0.45 * pitch)))
    if extent is None:
        return None
    left, right = extent[0] + lo, extent[1] + lo + 1
    span = right - left
    if span < 4 * n:
        return None
    if n == 1:
        return [(left, right)]

    # Measured gaps strictly inside the extent.
    inner = occupied[extent[0]:extent[1] + 1]
    padded = np.concatenate(([True], inner, [True]))
    edges = np.flatnonzero(np.diff(padded.astype(np.int8)))
    gaps: list[tuple[float, float]] = []  # (centre x, width)
    for start, end in zip(edges[0::2], edges[1::2]):
        width = end - start
        if width >= 2 and start > 0 and end < inner.size + 1:
            gaps.append((left + (start + end) / 2.0 - 0.5, float(width)))

    total = float(sum(weights))
    cum = np.cumsum(weights)[:-1]
    expected = right - span * cum / total  # decreasing x for j = 0..N-2
    unit = max(1.0, 0.30 * pitch)

    cands = [(x, gw, True) for x, gw in gaps]
    cands += [(float(x), 0.0, False) for x in expected]
    cands.sort(key=lambda c: -c[0])  # RTL: rightmost first
    m = len(cands)
    inf = float('inf')
    sigma = max(1.0, position_sigma * span)

    def cost(j: int, i: int) -> float:
        x, gw, real = cands[i]
        value = ((x - expected[j]) / sigma) ** 2
        if real:
            value -= gap_reward * min(gw / unit, 1.0)
        else:
            value += virtual_penalty
        return value

    dp = np.full((n - 1, m), inf)
    back = np.full((n - 1, m), -1, dtype=int)
    for i in range(m):
        dp[0, i] = cost(0, i)
    for j in range(1, n - 1):
        for i in range(m):
            best_prev, best_val = -1, inf
            for k in range(i):
                if cands[k][0] - cands[i][0] < 1.0:
                    continue
                if dp[j - 1, k] < best_val:
                    best_prev, best_val = k, dp[j - 1, k]
            if best_prev >= 0:
                dp[j, i] = best_val + cost(j, i)
                back[j, i] = best_prev
    last = int(np.argmin(dp[n - 2]))
    if not np.isfinite(dp[n - 2, last]):
        return None
    chosen = [last]
    for j in range(n - 2, 0, -1):
        chosen.append(int(back[j, chosen[-1]]))
    cuts = [cands[i][0] for i in reversed(chosen)]  # x for cut after word j
    bounds = [float(right), *cuts, float(left)]
    return [
        (int(round(bounds[i + 1])), int(round(bounds[i])))
        for i in range(n)
    ]


# Where a printed stop sits inside a word's slot box under measured geometry,
# in units of the box height ``h`` from the word's left (RTL end) edge / top.
# Read off 513 hand-drawn Bahrain marks: the box is 0.32h wide and 0.32h tall,
# centred at (+0.15h, +0.51h). The ROI below spans roughly the 10th-90th
# percentile of those boxes so it survives a mis-cut word edge.
MARK_SEAT_CENTRE = (0.15, 0.51)
MARK_SEAT_ROI = (-0.20, 0.22, 0.55, 0.80)  # x0, y0, x1, y1 offsets


def mark_seat_roi_from_box(
    word_x0: int, word_y0: int, word_x1: int, word_y1: int,
) -> tuple[int, int, int, int]:
    """Pixel ROI of a word's stop under measured geometry."""
    h = max(12, int(word_y1) - int(word_y0))
    ox0, oy0, ox1, oy1 = MARK_SEAT_ROI
    return (
        int(round(word_x0 + ox0 * h)), int(round(word_y0 + oy0 * h)),
        int(round(word_x0 + ox1 * h)), int(round(word_y0 + oy1 * h)),
    )


def mark_seat_centre(
    word_x0: int, word_y0: int, word_y1: int,
) -> tuple[float, float]:
    """Expected pixel centre of a word's stop under measured geometry."""
    h = max(12, int(word_y1) - int(word_y0))
    return word_x0 + MARK_SEAT_CENTRE[0] * h, word_y0 + MARK_SEAT_CENTRE[1] * h
