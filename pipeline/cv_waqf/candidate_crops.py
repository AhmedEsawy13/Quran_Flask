"""Training crops cut exactly like inference cuts them, labelled by seat.

The hybrid detector classifies a fixed window centred on every small ink
component (``line_gaps.find_line_component_candidates``). Crops sampled any
other way (a tight box around a chosen blob, a human-drawn box) fill the
48×48 input differently, so a model trained on them mislabels the windows it
actually sees. This sampler runs the *same* candidate generator and crop
function, then labels each window from where it sits:

* it belongs to the word whose measured stop seat is nearest;
* on a word with an agreed mark, the largest component at the seat takes that
  mark's symbol and windows clearly away from it are ``none`` (harakat,
  letter parts — the hard negatives the detector really produces);
* on an agreed-empty word every window is ``none``;
* disputed words and the ambiguous ring in between are left out.

Labels come from ``sample_crops.consensus_marks`` (any set of editions, one
edition included), so the same sampler serves every print.
"""
from __future__ import annotations

import argparse
import random
from collections import Counter
from pathlib import Path

import cv2

from pipeline.cv_waqf import geometry
from pipeline.cv_waqf.candidates import crop_candidate
from pipeline.cv_waqf.config import CROP_SIZE, CV_ROOT, EDITIONS
from pipeline.cv_waqf.layout_geo import estimate_layout_words
from pipeline.cv_waqf.line_gaps import find_line_component_candidates
from pipeline.cv_waqf.pages import ensure_page_image
from pipeline.cv_waqf.preprocess import load_bgr, preprocess_page
from pipeline.cv_waqf.sample_crops import (
    MADINAH_FAMILY_CONSENSUS,
    TARGET_CLASSES,
    _safe_class_dir,
    consensus_marks,
)

CANDIDATE_ROOT = CV_ROOT / 'crops_candidates'

# Seat distance, in units of the word's slot height h.
POSITIVE_RADIUS = 0.20   # window centre this close to the seat → the mark
NEGATIVE_RADIUS = 0.34   # ...this far or more from it → not the mark
OWNER_RADIUS = 0.70      # farther than this from every seat → background


def label_windows(
    hits,
    words,
    positives: dict[int, str],
    disputed: set[int],
    *,
    rng: random.Random,
    background_keep: float,
    empty_keep: float,
):
    """Yield ``(hit, label, word)`` for each usable candidate window."""
    seats = [
        (
            word,
            geometry.mark_seat_centre(word.x0, word.y0, word.y1),
            max(12, word.y1 - word.y0),
        )
        for word in words if word.is_content_word
    ]
    owned: list[tuple[object, float, object]] = []
    for hit in hits:
        cx, cy = hit.candidate.cx, hit.candidate.cy
        best = None
        for word, (sx, sy), h in seats:
            if not (word.y0 - 0.3 * h <= cy <= word.y1 + 0.3 * h):
                continue
            distance = ((cx - sx) ** 2 + (cy - sy) ** 2) ** 0.5 / h
            if best is None or distance < best[0]:
                best = (distance, word)
        if best is None or best[0] > OWNER_RADIUS:
            if rng.random() < background_keep:
                yield hit, 'none', None
            continue
        owned.append((hit, best[0], best[1]))

    # The stop is the largest component near an agreed seat; a fatha or a
    # letter part in the same neighbourhood is neither a clean positive nor a
    # clean negative, so it is left out rather than guessed.
    strongest: dict[int, object] = {}
    for hit, distance, word in owned:
        if word.word_id in positives and distance <= POSITIVE_RADIUS:
            current = strongest.get(word.word_id)
            if current is None or hit.candidate.area > current.candidate.area:
                strongest[word.word_id] = hit
    for hit, distance, word in owned:
        wid = word.word_id
        if wid in disputed:
            continue
        symbol = positives.get(wid)
        if symbol is not None:
            if strongest.get(wid) is hit:
                yield hit, symbol, word
            elif distance >= NEGATIVE_RADIUS:
                yield hit, 'none', word
        elif rng.random() < empty_keep:
            yield hit, 'none', word


def sample_candidate_crops(
    edition: str,
    pages: list[int],
    *,
    consensus: tuple[str, ...],
    out_root: Path | None = None,
    seed: int = 7,
    clear: bool = False,
    background_keep: float = 0.02,
    empty_keep: float = 0.10,
) -> dict:
    spec = EDITIONS[edition]
    if not spec.measured_geometry:
        raise ValueError(
            f'{edition}: candidate crops need measured geometry '
            '(the stop seat is defined relative to it)'
        )
    out = Path(out_root or (CANDIDATE_ROOT / spec.id))
    if clear and out.exists():
        import shutil
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)
    counts: Counter = Counter()
    for page in pages:
        try:
            image = ensure_page_image(spec, page)
        except Exception as exc:  # noqa: BLE001
            print(f'  page {page}: image skip ({exc})')
            continue
        prepared = preprocess_page(load_bgr(image), spec)
        words = estimate_layout_words(spec, page, prepared)
        if not words:
            continue
        ayah_keys = sorted({(w.surah, w.ayah) for w in words if w.surah and w.ayah})
        agreed, marked_any = consensus_marks(
            consensus, ayah_keys, spec.script_db,
        )
        on_page = {w.word_id for w in words}
        positives = {
            wid: sym for (_s, _a, wid), sym in agreed.items()
            if wid in on_page and sym in TARGET_CLASSES
        }
        disputed = {
            wid for (_s, _a, wid) in marked_any
            if wid in on_page and wid not in positives
        }
        hits = find_line_component_candidates(prepared, words)
        rng = random.Random(seed * 100_003 + page)
        for index, (hit, label, word) in enumerate(label_windows(
            hits, words, positives, disputed, rng=rng,
            background_keep=background_keep, empty_keep=empty_keep,
        )):
            crop = crop_candidate(prepared.gray, hit.candidate, size=CROP_SIZE)
            folder = out / _safe_class_dir(label)
            folder.mkdir(parents=True, exist_ok=True)
            wid = word.word_id if word is not None else 0
            cv2.imwrite(
                str(folder / f'p{page:03d}_w{wid}_{index:04d}_{label}.png'),
                crop,
            )
            counts[label] += 1
    return {'edition': edition, 'pages': len(pages), 'counts': dict(counts), 'out': str(out)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--edition', required=True, choices=list(EDITIONS))
    parser.add_argument('--page-list', required=True, help='e.g. 12,40-45')
    parser.add_argument(
        '--consensus', default='self',
        help="'self' (the edition's own column), 'madinah', or a "
             'comma-separated edition list',
    )
    parser.add_argument('--out', type=Path, default=None)
    parser.add_argument('--seed', type=int, default=7)
    parser.add_argument('--clear', action='store_true')
    args = parser.parse_args(argv)
    from pipeline.cv_waqf.evaluate_hand import _parse_pages
    if args.consensus == 'self':
        consensus = (args.edition,)
    elif args.consensus == 'madinah':
        consensus = MADINAH_FAMILY_CONSENSUS
    else:
        consensus = tuple(part.strip() for part in args.consensus.split(','))
    result = sample_candidate_crops(
        args.edition, _parse_pages(args.page_list), consensus=consensus,
        out_root=args.out, seed=args.seed, clear=args.clear,
    )
    print(result)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
