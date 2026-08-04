"""Build weakly-labelled glyph crops from edition marks + page images."""
from __future__ import annotations

import argparse
import json
import random
from collections import Counter
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from pipeline.cv_waqf import CLASSES, GLYPH_FOR_CLASS
from pipeline.cv_waqf.config import (
    CROPS_ROOT,
    CROP_SIZE,
    DEFAULT_GLYPH_FONT,
    EDITIONS,
    MESAHA_BOXES_DB,
)
from pipeline.cv_waqf.layout_geo import estimate_layout_words, mark_roi_for_word
from pipeline.cv_waqf.marks import edition_marks_for_ayahs
from pipeline.cv_waqf.mesaha_boxes import lookup_box
from pipeline.cv_waqf.pages import ensure_page_image
from pipeline.cv_waqf.preprocess import load_bgr, preprocess_page


def _safe_class_dir(label: str) -> str:
    # Filesystem-friendly folder names.
    return {
        'م': 'm',
        'ق': 'q',
        'ص': 's',
        'ج': 'j',
        'لا': 'la',
        'ع': 'a',
        'س': 'sakta',
        'none': 'none',
    }.get(label, label)


# Arabic harakat / tashkeel rendered into the ``none`` class so the MLP
# learns to reject ضمة/كسرة/فتحة/شدة/سكون instead of calling them waqf.
_HARAKAT_GLYPHS = (
    'َ', 'ُ', 'ِ', 'ً', 'ٌ', 'ٍ', 'ّ', 'ْ', 'ٰ', 'ٓ', 'ٔ', 'ٕ',
    'ۜ',  # rarely confused; still useful as thin-above mark distractor
)


def render_synthetic_crops(
    out_root: Path,
    *,
    per_class: int = 40,
    harakat_per: int = 80,
    font_path: Path | None = None,
) -> Counter:
    font_path = Path(font_path or DEFAULT_GLYPH_FONT)
    counts: Counter = Counter()
    if not font_path.is_file():
        print(f'warning: glyph font missing at {font_path}; skipping synthetics')
        return counts
    try:
        font = ImageFont.truetype(str(font_path), 36)
        font_small = ImageFont.truetype(str(font_path), 22)
    except OSError as exc:
        print(f'warning: cannot load font: {exc}')
        return counts

    rng = random.Random(42)
    for label in CLASSES:
        folder = out_root / _safe_class_dir(label)
        folder.mkdir(parents=True, exist_ok=True)
        glyph = GLYPH_FOR_CLASS.get(label) or ('·' if label == 'none' else label)
        for i in range(per_class):
            img = Image.new('L', (CROP_SIZE, CROP_SIZE), color=255)
            draw = ImageDraw.Draw(img)
            # jitter
            ox = rng.randint(-4, 4)
            oy = rng.randint(-4, 4)
            draw.text(
                (CROP_SIZE // 2 + ox, CROP_SIZE // 2 + oy),
                glyph if label != 'none' else '',
                font=font,
                fill=0,
                anchor='mm',
            )
            arr = np.array(img)
            if rng.random() < 0.5:
                arr = cv2.GaussianBlur(arr, (3, 3), 0)
            noise = rng.randint(0, 12)
            if noise:
                speck = np.random.randint(0, noise, arr.shape, dtype=np.uint8)
                arr = cv2.subtract(arr, speck)
            path = folder / f'synth_{i:04d}.png'
            cv2.imwrite(str(path), arr)
            counts[label] += 1

    # Hard negatives: real harakat shapes labeled ``none``.
    none_folder = out_root / 'none'
    none_folder.mkdir(parents=True, exist_ok=True)
    for i in range(harakat_per):
        glyph = _HARAKAT_GLYPHS[i % len(_HARAKAT_GLYPHS)]
        img = Image.new('L', (CROP_SIZE, CROP_SIZE), color=255)
        draw = ImageDraw.Draw(img)
        ox = rng.randint(-6, 6)
        oy = rng.randint(-6, 6)
        use = font_small if rng.random() < 0.7 else font
        draw.text(
            (CROP_SIZE // 2 + ox, CROP_SIZE // 2 + oy),
            glyph, font=use, fill=0, anchor='mm',
        )
        arr = np.array(img)
        if rng.random() < 0.6:
            arr = cv2.GaussianBlur(arr, (3, 3), 0)
        path = none_folder / f'haraka_{i:04d}.png'
        cv2.imwrite(str(path), arr)
        counts['none'] += 1
    return counts


def mine_harakat_negatives(
    edition_key: str,
    pages: list[int],
    out_root: Path,
    *,
    max_per_page: int = 40,
) -> Counter:
    """Save small ink blobs away from known mark seats as ``none`` crops."""
    from pipeline.cv_waqf.candidates import crop_candidate, find_candidates

    spec = EDITIONS[edition_key]
    counts: Counter = Counter()
    folder = out_root / 'none'
    folder.mkdir(parents=True, exist_ok=True)
    for page in pages:
        try:
            img_path = ensure_page_image(spec, page)
        except Exception as exc:  # noqa: BLE001
            print(f'page {page}: skip ({exc})')
            continue
        prepared = preprocess_page(load_bgr(img_path), spec)
        words = estimate_layout_words(spec, page, prepared)
        ayah_keys = sorted({(w.surah, w.ayah) for w in words if w.surah and w.ayah})
        marks = edition_marks_for_ayahs(edition_key, ayah_keys, spec.script_db)
        mark_ids = {wid for (_s, _a, wid) in marks}
        avoid = [
            mark_roi_for_word(w, pad_x=8, pad_y=8)
            for w in words if w.word_id in mark_ids
        ]
        cands = find_candidates(
            prepared,
            min_area=12,
            max_area=120,
            min_side=3,
            max_side=14,
            max_aspect=4.0,
            min_fill=0.10,
        )
        saved = 0
        for i, cand in enumerate(cands):
            if saved >= max_per_page:
                break
            if any(
                ax0 <= cand.cx <= ax1 and ay0 <= cand.cy <= ay1
                for ax0, ay0, ax1, ay1 in avoid
            ):
                continue
            crop = crop_candidate(prepared.gray, cand, size=CROP_SIZE)
            dest = folder / f'haraka_cc_{spec.id}_p{page:03d}_{i:03d}.png'
            cv2.imwrite(str(dest), crop)
            counts['none'] += 1
            saved += 1
        print(f'page {page}: mined {saved} harakat negatives')
    return counts


def mine_component_negatives(
    edition_key: str,
    pages: list[int],
    out_root: Path,
    *,
    max_per_page: int = 60,
) -> Counter:
    """Mine safe word-body negatives using the production proposal window.

    Only lower-row components are selected.  Confirmed Bahrain stop marks sit
    above this zone, so unreviewed true marks are not silently labelled none.
    """
    from pipeline.cv_waqf.candidates import crop_candidate
    from pipeline.cv_waqf.line_gaps import find_line_component_candidates

    spec = EDITIONS[edition_key]
    counts: Counter = Counter()
    folder = out_root / 'none'
    folder.mkdir(parents=True, exist_ok=True)
    for page in pages:
        try:
            prepared = preprocess_page(
                load_bgr(ensure_page_image(spec, page)), spec,
            )
        except Exception as exc:  # noqa: BLE001
            print(f'page {page}: skip ({exc})')
            continue
        words = estimate_layout_words(spec, page, prepared)
        by_line: dict[int, list] = {}
        for word in words:
            by_line.setdefault(word.line_number, []).append(word)
        candidates = []
        for hit in find_line_component_candidates(prepared, words):
            line_words = by_line.get(hit.line_number) or []
            if not line_words:
                continue
            line_y0 = min(word.y0 for word in line_words)
            line_y1 = max(word.y1 for word in line_words)
            line_h = max(1, line_y1 - line_y0)
            relative_y = (hit.candidate.cy - line_y0) / line_h
            if relative_y < 0.78:
                continue
            candidates.append(hit.candidate)
        # Spread examples over the page instead of taking one dense corner.
        candidates.sort(key=lambda cand: (cand.y, -cand.x))
        if len(candidates) > max_per_page:
            step = len(candidates) / max_per_page
            candidates = [
                candidates[min(len(candidates) - 1, int(index * step))]
                for index in range(max_per_page)
            ]
        for index, cand in enumerate(candidates):
            crop = crop_candidate(prepared.gray, cand, size=CROP_SIZE)
            dest = folder / (
                f'component_none_{spec.id}_p{page:03d}_{index:03d}.png'
            )
            cv2.imwrite(str(dest), crop)
            counts['none'] += 1
        print(f'page {page}: mined {len(candidates)} component negatives')
    return counts


def build_hand_proposal_crops(
    edition_key: str,
    labels_path: Path,
    pages: list[int],
    out_root: Path,
    *,
    max_per_label: int = 2,
) -> Counter:
    """Re-crop hand labels through the same component windows used at runtime."""
    from pipeline.cv_waqf.candidates import Candidate, crop_candidate
    from pipeline.cv_waqf.line_gaps import find_line_component_candidates

    wanted = {int(page) for page in pages}
    rows = []
    for raw in Path(labels_path).read_text(encoding='utf-8').splitlines():
        try:
            row = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if int(row.get('page') or 0) in wanted and row.get('symbol') in CLASSES:
            rows.append(row)
    by_page: dict[int, list[dict]] = {}
    for row in rows:
        by_page.setdefault(int(row['page']), []).append(row)

    spec = EDITIONS[edition_key]
    counts: Counter = Counter()
    for page, page_rows in sorted(by_page.items()):
        prepared = preprocess_page(
            load_bgr(ensure_page_image(spec, page)), spec,
        )
        words = estimate_layout_words(spec, page, prepared)
        hits = find_line_component_candidates(prepared, words)
        for label_index, row in enumerate(page_rows):
            bx0, by0, bx1, by1 = (int(value) for value in row['box'])

            def overlap(candidate: Candidate) -> float:
                ax0, ay0, ax1, ay1 = candidate.box
                ix0, iy0 = max(ax0, bx0), max(ay0, by0)
                ix1, iy1 = min(ax1, bx1), min(ay1, by1)
                intersection = max(0, ix1 - ix0) * max(0, iy1 - iy0)
                if not intersection:
                    return 0.0
                union = (
                    candidate.w * candidate.h
                    + (bx1 - bx0) * (by1 - by0)
                    - intersection
                )
                return intersection / union if union else 0.0

            ranked = sorted(
                (
                    (overlap(hit.candidate), hit.candidate)
                    for hit in hits
                ),
                key=lambda item: -item[0],
            )
            selected = [
                candidate for score, candidate in ranked
                if score >= 0.10
            ][:max_per_label]
            if not selected:
                # Every confirmed box still contributes one runtime-sized
                # example if thresholding split its ink unusually.
                cx, cy = (bx0 + bx1) // 2, (by0 + by1) // 2
                selected = [Candidate(
                    x=max(0, cx - 12), y=max(0, cy - 12),
                    w=24, h=24, area=max(1, (bx1 - bx0) * (by1 - by0)),
                )]
            symbol = str(row['symbol'])
            folder = out_root / _safe_class_dir(symbol)
            folder.mkdir(parents=True, exist_ok=True)
            for proposal_index, candidate in enumerate(selected):
                crop = crop_candidate(
                    prepared.gray, candidate, size=CROP_SIZE,
                )
                dest = folder / (
                    f'proposal_{spec.id}_p{page:03d}_{label_index:03d}_'
                    f'{proposal_index}_{_safe_class_dir(symbol)}.png'
                )
                cv2.imwrite(str(dest), crop)
                counts[symbol] += 1
        print(f'page {page}: proposal-aligned {len(page_rows)} labels')
    return counts


def build_page_crops(
    edition_key: str,
    pages: list[int],
    out_root: Path,
    *,
    max_per_page: int = 80,
    include_negatives: bool = True,
) -> Counter:
    spec = EDITIONS[edition_key]
    counts: Counter = Counter()
    for page in pages:
        try:
            img_path = ensure_page_image(spec, page)
        except Exception as exc:  # noqa: BLE001 — keep batch going
            print(f'page {page}: skip image ({exc})')
            continue
        bgr = load_bgr(img_path)
        prepared = preprocess_page(bgr, spec)
        words = estimate_layout_words(spec, page, prepared)
        if not words:
            continue
        ayah_keys = sorted({(w.surah, w.ayah) for w in words if w.surah and w.ayah})
        marks = edition_marks_for_ayahs(edition_key, ayah_keys, spec.script_db)
        gray = prepared.gray
        saved = 0
        for word in words:
            key = (word.surah, word.ayah, word.word_id)
            label = marks.get(key)
            if label and label in CLASSES and label != 'none':
                box = None
                if edition_key == 'المساحة':
                    box = lookup_box(MESAHA_BOXES_DB, page, word.word_id)
                if box:
                    x0, y0, x1, y1 = box
                    # Mark seat: left of word box.
                    roi = (max(0, x0 - 20), max(0, y0 - 12), x0 + 8, y1)
                else:
                    roi = mark_roi_for_word(word)
                crop = _extract_roi(gray, roi, CROP_SIZE)
                folder = out_root / _safe_class_dir(label)
                folder.mkdir(parents=True, exist_ok=True)
                dest = folder / f'{spec.id}_p{page:03d}_w{word.word_id}_{label}.png'
                cv2.imwrite(str(dest), crop)
                counts[label] += 1
                saved += 1
            elif include_negatives and random.random() < 0.08:
                roi = mark_roi_for_word(word)
                crop = _extract_roi(gray, roi, CROP_SIZE)
                folder = out_root / 'none'
                folder.mkdir(parents=True, exist_ok=True)
                dest = folder / f'{spec.id}_p{page:03d}_w{word.word_id}_none.png'
                cv2.imwrite(str(dest), crop)
                counts['none'] += 1
                saved += 1
            if saved >= max_per_page:
                break
        print(f'page {page}: saved {saved} crops')
    return counts


def _extract_roi(gray: np.ndarray, roi: tuple[int, int, int, int], size: int) -> np.ndarray:
    h, w = gray.shape[:2]
    x0, y0, x1, y1 = roi
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(w, x1), min(h, y1)
    if x1 <= x0 or y1 <= y0:
        return np.full((size, size), 255, dtype=np.uint8)
    patch = gray[y0:y1, x0:x1]
    ph, pw = patch.shape[:2]
    side = max(ph, pw, 1)
    canvas = np.full((side, side), 255, dtype=np.uint8)
    oy = (side - ph) // 2
    ox = (side - pw) // 2
    canvas[oy:oy + ph, ox:ox + pw] = patch
    return cv2.resize(canvas, (size, size), interpolation=cv2.INTER_AREA)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--edition', default='البحرين',
        choices=list(EDITIONS.keys()),
    )
    parser.add_argument('--pages', default='1-20',
                        help='page range a-b or comma list')
    parser.add_argument('--out', type=Path, default=CROPS_ROOT)
    parser.add_argument('--synthetic', type=int, default=40,
                        help='synthetic crops per class (0 to skip)')
    parser.add_argument('--mine-harakat', action='store_true',
                        help='also mine small page blobs as none (harakat)')
    parser.add_argument('--mine-components', action='store_true',
                        help='mine lower word-body proposal windows as none')
    parser.add_argument('--no-negatives', action='store_true')
    args = parser.parse_args(argv)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    totals: Counter = Counter()
    if args.synthetic > 0:
        totals += render_synthetic_crops(out, per_class=args.synthetic)

    pages = _parse_pages(args.pages)
    totals += build_page_crops(
        args.edition,
        pages,
        out,
        include_negatives=not args.no_negatives,
    )
    if args.mine_harakat:
        totals += mine_harakat_negatives(args.edition, pages, out)
    if args.mine_components:
        totals += mine_component_negatives(args.edition, pages, out)
    print('totals:', dict(totals))
    return 0


def _parse_pages(spec: str) -> list[int]:
    pages: list[int] = []
    for part in spec.split(','):
        part = part.strip()
        if not part:
            continue
        if '-' in part:
            a, b = part.split('-', 1)
            pages.extend(range(int(a), int(b) + 1))
        else:
            pages.append(int(part))
    return pages


if __name__ == '__main__':
    raise SystemExit(main())
