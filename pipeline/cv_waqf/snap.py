"""Move a detected sign's box from a neighbouring vowel onto the sign itself.

The hybrid proposer centres a fixed window on every small ink component —
fatha, damma, kasra, shadda, dots. A window centred on a vowel right beside a
stop sign still contains most of the sign, so it scores as a sign as
confidently as the sign's own window (9:64: damma 1.00, ج 0.998). The box then
marks the vowel, and often the label is wrong too (2:197: a fatha read ج under
a printed قلى). On a Kuwait sample about 1 box in 5 sat on a vowel.

For every classified hit, the nearby components whose own window reads as a
stop sign compete:
- a component reading the hit's own sign may sit up to REACH_UP above it; one
  reading a DIFFERENT sign must sit above the hit, within OTHER_DX sideways,
  and carry at least the ink of the hit's own best piece (a real sign is
  bigger than the vowel it replaces; a stray kasra is smaller than the صلى
  the box already holds, 2:279);
- letters are never rivals: anything over SIGN_MAX_SIDE, or within TEXT_GAP
  of a letter-sized stroke (6:157), is text;
- among rivals with a sign's amount of ink (INK_SHARE of the largest), the
  HIGHEST wins, since stop signs sit above the vowel layer.
The box becomes the sign's outline plus the small pieces inside it (the dot of
ج); the label becomes what that sign reads. Only the box and label change: the
word that owns the hit stays as the detector chose it (re-deciding it from the
estimated word boxes moved a real ص at 51:25).

Tried and rejected: a tight crop of each component as the tie-breaker (read a
damma as ج at 6:72 and the real ج as nothing at 9:68); Kraken line OCR (no
stop signs in its alphabet, and it reports positions along the line only, so
it cannot tell a vowel from the sign above it).

Kuwait: 60 random pages unchanged (487 match / 1 wrong / 2 extra); on the 55
pages behind the review's sign-differs cards 58 → 41 wrong, no page worse.
Enabled per edition by ``EditionSpec.snap_boxes``.
"""
from __future__ import annotations

from dataclasses import replace

from pipeline.cv_waqf.candidates import Candidate, crop_candidate
from pipeline.cv_waqf.config import CROP_SIZE
from pipeline.cv_waqf.line_gaps import _ccs_in_roi

WINDOW = 24            # the proposer's window (find_line_component_candidates)
REACH_X = 30           # how far from the hit a competing component may sit
REACH_UP, REACH_DOWN = 34, 16
OTHER_REACH_UP = 44    # a rival reading a DIFFERENT sign may sit this far above
OTHER_DX = 20          # ...and at most this far sideways
SIGN_MAX_SIDE = 24     # px: a rival bigger than this is a letter, not a stop sign
TEXT_GAP = 2           # px: a rival this close to a letter-sized stroke is text (6:157)
ANY_LABEL = True       # let a piece reading a different sign win (guards above)   # signs sit above vowels: search mostly upward
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


def _gap(a, b) -> int:
    dx = max(0, max(a[0], b[0]) - min(a[0] + a[2], b[0] + b[2]))
    dy = max(0, max(a[1], b[1]) - min(a[1] + a[3], b[1] + b[3]))
    return max(dx, dy)


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
        roi = _ccs_in_roi(prepared.binary, int(cx - REACH_X) - TEXT_GAP, int(cy - max(REACH_UP, OTHER_REACH_UP)) - TEXT_GAP,
                          int(cx + REACH_X) + TEXT_GAP, int(cy + REACH_DOWN) + TEXT_GAP)
        comps = [c for c in roi if max(c[2], c[3]) <= 2 * WINDOW]
        strokes = [c for c in roi if max(c[2], c[3]) > SIGN_MAX_SIDE]   # letters / words
        plans.append((hit, label, conf, comps, strokes))

    # 2. classify every competitor's own window in one batch
    crops, index = [], []
    for n, (_hit, _label, _conf, comps, _strokes) in enumerate(plans):
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
    signs = [i for i, name in enumerate(clf.classes) if name != 'none']
    for n, (hit, label, conf, comps, strokes) in enumerate(plans):
        # A rival is any piece whose own window reads as SOME stop sign: a box
        # on a vowel often carries the wrong label too (2:197 fatha read ج
        # under a printed قلى), so the real sign may read differently.
        rivals = []
        cx, cy = hit.candidate.cx, hit.candidate.cy
        for c, wp in scored.get(n, []):
            if max(c[2], c[3]) > SIGN_MAX_SIDE or any(_gap(c, t) <= TEXT_GAP for t in strokes):
                continue                 # a letter, or a piece touching a word: text
            ccx, ccy = c[0] + c[2] / 2, c[1] + c[3] / 2
            if label in clf.classes and wp[clf.classes.index(label)] >= WINDOW_MIN_P:
                if ccy >= cy - REACH_UP:
                    rivals.append((c, label, float(wp[clf.classes.index(label)])))
                continue
            if not ANY_LABEL or not signs:
                continue
            best_i = max(signs, key=lambda i: wp[i])
            if (wp[best_i] >= WINDOW_MIN_P and ccy < cy - 4 and abs(ccx - cx) <= OTHER_DX):
                rivals.append((c, clf.classes[best_i], float(wp[best_i])))
        # A piece reading a DIFFERENT sign replaces the hit only if it carries at
        # least the ink of the hit's own best piece: a real sign above a vowel is
        # bigger than the vowel (2:197 قلى over a fatha), whereas a kasra of the
        # line above is smaller than the صلى the box already sits on (2:279).
        own_ink = max((r[0][4] for r in rivals if r[1] == label), default=0)
        rivals = [r for r in rivals if r[1] == label or r[0][4] >= own_ink]
        if not rivals:
            out.setdefault(('keep', id(hit)), (hit, label, conf))
            continue
        biggest = max(r[0][4] for r in rivals)
        eligible = [r for r in rivals if r[0][4] >= INK_SHARE * biggest]
        best = min(eligible, key=lambda r: r[0][1] + r[0][3] / 2)   # highest centre
        sign, sign_label, sign_conf = best
        if sign_label != label:          # the sign itself reads differently: trust it
            label, conf = sign_label, sign_conf
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
