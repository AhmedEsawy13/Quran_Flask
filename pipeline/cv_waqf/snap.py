"""Move a detected sign's box from a neighbouring vowel onto the sign itself.

The hybrid proposer centres a fixed window on every small ink component —
fatha, damma, kasra, shadda, dots. A window centred on a vowel right beside a
stop sign still contains most of the sign, so it classifies as that sign with
the same confidence as the sign's own window (9:64: damma 1.00, ج 0.998). The
box then marks the vowel: the review crop shows the wrong thing and the sign
can attach to the neighbouring word. On a Kuwait sample ~1 box in 5 sat on a
vowel this way.

For every classified hit, the nearby components whose own window also reads
as that sign compete. Among those with a sign's amount of ink (at least
INK_SHARE of the largest — a thin fatha slash is not a sign), the HIGHEST
wins: stop signs sit above the vowel layer. A tight crop of each component was
tried as the tie-breaker and rejected: it read a damma as ج (6:72, 0.81) and
the real ج as nothing (9:68, 0.003). The box is then the sign's own outline
plus the small pieces inside it (the dot of ج), never a neighbouring vowel.
Only the box moves: the word that owns the hit is kept as the detector chose it.

Kuwait, 60 random pages: agreement with the DB column unchanged; boxes on a vowel ~5/29 → ~1/29. Enabled per edition by
``EditionSpec.snap_boxes``.
"""
from __future__ import annotations

from dataclasses import replace

from pipeline.cv_waqf.candidates import Candidate, crop_candidate
from pipeline.cv_waqf.config import CROP_SIZE
from pipeline.cv_waqf.line_gaps import _ccs_in_roi

WINDOW = 24            # the proposer's window (find_line_component_candidates)
REACH_X = 30           # how far from the hit a competing component may sit
REACH_UP, REACH_DOWN = 34, 16   # signs sit above vowels: search mostly upward
MIN_AREA = 12          # smaller pieces (dots) are parts, never the sign itself
WINDOW_MIN_P = 0.9     # a competitor's own window must read as the same sign
INK_SHARE = 0.6        # a rival needs this share of the biggest rival's ink
PART_PAD = 2           # px: a small piece whose centre falls inside the sign's
PART_AREA = 0.35       #   outline (+pad) and is under this share of its area is
                       #   part of it (the dot of ج); anything else is a neighbour


def _window(cx: float, cy: float, area: int) -> Candidate:
    half = WINDOW // 2
    return Candidate(x=max(0, int(round(cx)) - half), y=max(0, int(round(cy)) - half),
                     w=WINDOW, h=WINDOW, area=area)


def snap_hits(classified_hits, prepared, clf):
    """Return ``classified_hits`` with each candidate moved onto its sign.

    ``classified_hits`` is ``[(hit, label, conf)]`` as built in ``detect_page``;
    each returned hit keeps its label and confidence. Two hits that snap to the
    same sign for the same word collapse into the more confident one.
    """
    if not classified_hits:
        return classified_hits
    # 1. competing components per hit
    plans = []
    for hit, label, conf in classified_hits:
        cx, cy = hit.candidate.cx, hit.candidate.cy
        comps = [c for c in _ccs_in_roi(prepared.binary, int(cx - REACH_X), int(cy - REACH_UP),
                                         int(cx + REACH_X), int(cy + REACH_DOWN))
                 if max(c[2], c[3]) <= 2 * WINDOW]
        plans.append((hit, label, conf, comps))

    # 2. classify every competitor's own window in one batch
    crops, index = [], []
    for n, (_hit, _label, _conf, comps) in enumerate(plans):
        for c in comps:
            x, y, w, h, area = c
            if area < MIN_AREA:
                continue
            crops.append(crop_candidate(prepared.gray, _window(x + w / 2, y + h / 2, area), size=CROP_SIZE))
            index.append((n, c))
    probs = [p for _lab, _conf, p in clf.predict_many_probs(crops)] if crops else []

    scored: dict[int, list] = {}
    for k, (n, c) in enumerate(index):
        scored.setdefault(n, []).append((c, probs[k]))

    # 3. pick the sign, grow it over its parts, re-seat the hit
    out = {}
    for n, (hit, label, conf, comps) in enumerate(plans):
        li = clf.classes.index(label) if label in clf.classes else None
        rivals = [(c, float(wp[li])) for c, wp in scored.get(n, [])
                  if li is not None and wp[li] >= WINDOW_MIN_P]
        if not rivals:
            out.setdefault(('keep', id(hit)), (hit, label, conf))
            continue
        biggest = max(r[0][4] for r in rivals)
        eligible = [r for r in rivals if r[0][4] >= INK_SHARE * biggest]
        best = min(eligible, key=lambda r: r[0][1] + r[0][3] / 2)   # highest centre
        sign = best[0]
        x0, y0, x1, y1 = sign[0], sign[1], sign[0] + sign[2], sign[1] + sign[3]
        for c in comps:
            ccx, ccy = c[0] + c[2] / 2, c[1] + c[3] / 2
            inside = (sign[0] - PART_PAD <= ccx <= sign[0] + sign[2] + PART_PAD
                      and sign[1] - PART_PAD <= ccy <= sign[1] + sign[3] + PART_PAD)
            if c is not sign and c[4] < PART_AREA * sign[4] and inside:
                x0, y0 = min(x0, c[0]), min(y0, c[1])
                x1, y1 = max(x1, c[0] + c[2]), max(y1, c[1] + c[3])
        cand = Candidate(x=x0, y=y0, w=x1 - x0, h=y1 - y0, area=sign[4], score=hit.candidate.score)
        # The box moves; the word that owns the hit does not. Re-deciding it from
        # the estimated word boxes moved a real ص at 51:25 «سَلَٰمٞ» onto «سَلَٰمٗا».
        moved = replace(hit, candidate=cand)
        layout_word = hit.layout_word
        # Merge only duplicates for the SAME word; hits on one sign but paired
        # with different words stay apart, exactly as before snapping (51:25).
        key = ('sign', sign[:4], layout_word.word_id if layout_word else None)
        if key not in out or conf > out[key][2]:
            out[key] = (moved, label, conf)
    return list(out.values())
