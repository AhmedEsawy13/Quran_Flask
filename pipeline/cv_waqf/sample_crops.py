"""Sample labeled waqf crops from random pages using known DB marks.

Starts with الشمرلي (full local column), then البحرين. For every DB mark on
the chosen pages we crop the ink in the band *above the word end* (RTL) so
training data is real stops — not harakat weak-labels.

    PYTHONPATH=. .venv/bin/python -m pipeline.cv_waqf sample-crops \\
        --edition الشمرلي --pages 40 --seed 7

Writes:
  data/cv/crops_labeled/<edition_slug>/{m,q,s,j,la,a,sakta,none}/
  data/cv/crops_labeled/<edition_slug>/index.html   (visual QC gallery)
"""
from __future__ import annotations

import argparse
import html
import random
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

import cv2
import numpy as np

from pipeline.cv_waqf.build_crops import _extract_roi, _safe_class_dir
from pipeline.cv_waqf.candidates import Candidate, crop_candidate
from pipeline.cv_waqf.config import (
    CROP_SIZE,
    CV_ROOT,
    EDITIONS,
    EditionSpec,
    TRUSTED_WAQF_EDITIONS,
)
from pipeline.cv_waqf.layout_geo import (
    _ids_between,
    estimate_layout_words,
    load_page_lines,
)
from pipeline.cv_waqf.marks import edition_marks_for_ayahs
from pipeline.cv_waqf.pages import ensure_page_image
from pipeline.cv_waqf.preprocess import load_bgr, preprocess_page
from pipeline.cv_waqf.strip import above_word_strip_roi_from_box

LABELED_ROOT = CV_ROOT / 'crops_labeled'

# Prefer covering every Athar stop class, including rare ones.
TARGET_CLASSES = ('م', 'ق', 'ص', 'ج', 'لا', 'ع', 'س')

# Prints that follow the Madinah layout and marks closely. Where all of them
# agree the label is very likely what is printed; where they differ the print
# is in doubt and the word is excluded rather than guessed.
MADINAH_FAMILY_CONSENSUS = ('قطر', 'المدينة الجديد', 'المدينة القديم')


def consensus_marks(
    editions: tuple[str, ...],
    ayah_keys: list[tuple[int, int]],
    script_db: str,
) -> tuple[dict[tuple[int, int, int], str], set[tuple[int, int, int]]]:
    """``(agreed positives, every word any edition marks)``.

    A positive needs the same symbol from every edition. A word marked by
    some editions but not all, or with different symbols, is *disputed*: it
    is in the second set (so it is never used as a negative) but not the
    first (so it is never used as a positive).
    """
    per_edition = [
        edition_marks_for_ayahs(edition, ayah_keys, script_db)
        for edition in editions
    ]
    marked = set().union(*(set(marks) for marks in per_edition))
    agreed: dict[tuple[int, int, int], str] = {}
    for key in marked:
        symbols = {marks.get(key) for marks in per_edition}
        if len(symbols) == 1 and None not in symbols:
            agreed[key] = symbols.pop()
    return agreed, marked


def _pages_for_edition(spec: EditionSpec) -> list[int]:
    conn = sqlite3.connect(spec.layout_db)
    try:
        rows = conn.execute(
            'SELECT DISTINCT page_number FROM pages '
            'WHERE first_word_id IS NOT NULL ORDER BY page_number'
        ).fetchall()
    finally:
        conn.close()
    pages = [int(r[0]) for r in rows if spec.min_page <= int(r[0]) <= spec.max_page]
    return pages


def _page_word_ids(spec: EditionSpec, page: int) -> list[int]:
    ids: list[int] = []
    for ln in load_page_lines(spec, page):
        if ln.get('first_word_id') is None or ln.get('last_word_id') is None:
            continue
        if (ln.get('line_type') or '') in (
            'surah_name', 'surah_info', 'basmallah', 'basmala',
        ):
            continue
        first_id, last_id = int(ln['first_word_id']), int(ln['last_word_id'])
        ids.extend(_ids_between(spec.script_db, first_id, last_id))
    return ids


def choose_pages(
    edition: str,
    spec: EditionSpec,
    *,
    n_pages: int,
    seed: int,
) -> list[int]:
    """Pick random pages, forcing coverage of every mark class when possible."""
    rng = random.Random(seed)
    all_pages = _pages_for_edition(spec)
    if not all_pages:
        raise RuntimeError(f'no layout pages for {edition}')

    # Build class → pages that contain at least one mark of that class.
    # Sample a subset of pages to scan (full 522 mark lookup is fine — SQL).
    class_pages: dict[str, set[int]] = defaultdict(set)
    # Walk pages in shuffled order and record until we have class coverage map
    # from a moderate sample, then refine with targeted queries via word ids.
    # Faster path: for each page, load marks through layout word spans.
    shuffled = list(all_pages)
    rng.shuffle(shuffled)
    # Index up to all pages (shamarly 522 is cheap enough).
    for page in shuffled:
        word_ids = _page_word_ids(spec, page)
        if not word_ids:
            continue
        # Resolve ayah keys from script db for mark lookup.
        conn = sqlite3.connect(spec.script_db)
        try:
            q = ','.join('?' * len(word_ids))
            rows = conn.execute(
                f'SELECT word_index, surah, ayah FROM words '
                f'WHERE word_index IN ({q})',
                word_ids,
            ).fetchall()
        finally:
            conn.close()
        ayah_keys = sorted({(int(s), int(a)) for _wid, s, a in rows})
        marks = edition_marks_for_ayahs(edition, ayah_keys, spec.script_db)
        page_id_set = set(word_ids)
        for (_s, _a, wid), sym in marks.items():
            if wid in page_id_set and sym in TARGET_CLASSES:
                class_pages[sym].add(page)

    chosen: list[int] = []
    used: set[int] = set()
    # 1) Ensure each class appears at least once (prefer rarer classes first).
    for sym in sorted(TARGET_CLASSES, key=lambda s: len(class_pages.get(s, []))):
        options = [p for p in class_pages.get(sym, []) if p not in used]
        if not options:
            continue
        page = rng.choice(options)
        chosen.append(page)
        used.add(page)

    # 2) Fill with random pages that have any marks.
    marked_pages = sorted({p for pages in class_pages.values() for p in pages})
    pool = [p for p in marked_pages if p not in used] or [
        p for p in all_pages if p not in used
    ]
    rng.shuffle(pool)
    for page in pool:
        if len(chosen) >= n_pages:
            break
        chosen.append(page)
        used.add(page)

    chosen.sort()
    return chosen[:n_pages]


def _above_end_roi(
    word_x0: int, word_x1: int, word_y0: int, word_y1: int, line_y0: int,
    convention: str = 'legacy',
) -> tuple[int, int, int, int]:
    return above_word_strip_roi_from_box(
        word_x0, word_y0, word_x1, word_y1, line_y0=line_y0,
        convention=convention,
    )


def _best_ink_in_roi(
    binary: np.ndarray,
    roi: tuple[int, int, int, int],
    *,
    expected: tuple[float, float] | None = None,
    line_h: int | None = None,
) -> Candidate | None:
    """The ink blob in ``roi`` most likely to be the stop.

    With ``expected`` (measured geometry) the winner is the stop-sized blob
    nearest the known seat, not the biggest one: the biggest blob in a seat
    ROI is usually a neighbouring letter body or frame ornament.
    """
    h, w = binary.shape[:2]
    x0, y0, x1, y1 = roi
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(w, x1), min(h, y1)
    if x1 <= x0 or y1 <= y0:
        return None
    patch = binary[y0:y1, x0:x1]
    if patch.size == 0 or int(patch.sum()) < 255 * 10:
        return None
    num, lab, stats, _ = cv2.connectedComponentsWithStats(patch, connectivity=8)
    best = None
    best_score = -1.0
    rh, rw = y1 - y0, x1 - x0
    min_side = max(6, int(0.10 * max(rh, rw)))
    max_side = max(min_side + 2, int(0.85 * max(rh, rw)))
    if expected is not None and line_h:
        # Stop-sized only: 0.15h..0.55h, and not a long thin stroke.
        min_side = max(6, int(0.15 * line_h))
        max_side = max(min_side + 2, int(0.55 * line_h))
    for label in range(1, num):
        bx, by, bw, bh, area = (int(v) for v in stats[label])
        if area < 18:
            continue
        if not (min_side <= max(bw, bh) <= max_side):
            continue
        if expected is not None and line_h:
            # Stops are compact (hand-drawn Bahrain boxes are ~1:1). A long
            # diagonal is a fatha, and a blob cut by the ROI edge is frame
            # ornament or a neighbouring letter, never the stop.
            if max(bw, bh) / max(1, min(bw, bh)) > 2.0:
                continue
            if bx <= 0 or by <= 0 or bx + bw >= x1 - x0 or by + bh >= y1 - y0:
                continue
            # A diagonal fatha has a squarish bounding box but a long thin
            # rotated one, so test elongation on the pixels themselves.
            points = np.column_stack(np.where(lab[by:by + bh, bx:bx + bw] == label))
            if len(points) >= 5:
                (_c, (rw_, rh_), _a) = cv2.minAreaRect(points.astype(np.float32))
                if max(rw_, rh_) / max(1.0, min(rw_, rh_)) > 2.0:
                    continue
            cx = x0 + bx + bw / 2.0
            cy = y0 + by + bh / 2.0
            distance = ((cx - expected[0]) ** 2 + (cy - expected[1]) ** 2) ** 0.5
            if distance > 0.30 * line_h:
                continue
            score = 1000.0 - distance + 0.05 * area
            if score > best_score:
                best_score = score
                best = Candidate(x=x0 + bx, y=y0 + by, w=bw, h=bh, area=area, score=score)
            continue
        score = area + 2.0 * max(bw, bh)
        if score > best_score:
            best_score = score
            best = Candidate(x=x0 + bx, y=y0 + by, w=bw, h=bh, area=area, score=score)
    if best is not None:
        return best
    if expected is not None:
        return None  # measured seat: no stop-sized ink means no stop
    # Fallback: tight ink bbox of whole ROI.
    ys, xs = np.where(patch > 0)
    if len(xs) < 8:
        return None
    return Candidate(
        x=int(xs.min()) + x0,
        y=int(ys.min()) + y0,
        w=int(xs.max()) - int(xs.min()) + 1,
        h=int(ys.max()) - int(ys.min()) + 1,
        area=int(len(xs)),
        score=0.5,
    )


def _seat_kwargs(word, measured: bool) -> dict:
    if not measured:
        return {}
    from pipeline.cv_waqf import geometry

    return {
        'expected': geometry.mark_seat_centre(word.x0, word.y0, word.y1),
        'line_h': word.y1 - word.y0,
    }


def sample_crops(
    edition: str,
    *,
    n_pages: int = 40,
    seed: int = 7,
    out_root: Path | None = None,
    clear: bool = False,
    include_none: bool = True,
    none_per_page: int = 4,
    pages: list[int] | None = None,
    consensus: tuple[str, ...] | None = None,
) -> dict:
    """Write labelled crops for ``pages`` (or ``n_pages`` chosen at random).

    ``consensus`` replaces the edition's own column as the source of labels
    with the marks all listed editions agree on (see ``consensus_marks``).
    """
    spec = EDITIONS[edition]
    slug = spec.id
    out = Path(out_root or (LABELED_ROOT / slug))
    if clear and out.exists():
        import shutil
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)

    if pages is None:
        pages = choose_pages(edition, spec, n_pages=n_pages, seed=seed)
    print(f'{edition}: sampling {len(pages)} pages → {pages}')

    counts: Counter = Counter()
    gallery: list[dict] = []

    for page in pages:
        try:
            img_path = ensure_page_image(spec, page)
        except Exception as exc:  # noqa: BLE001
            print(f'  page {page}: image skip ({exc})')
            continue
        prepared = preprocess_page(load_bgr(img_path), spec)
        words = estimate_layout_words(spec, page, prepared)
        if not words:
            continue
        ayah_keys = sorted({(w.surah, w.ayah) for w in words if w.surah and w.ayah})
        if consensus:
            marks, marked_any = consensus_marks(
                consensus, ayah_keys, spec.script_db,
            )
            disputed_ids = {wid for (_s, _a, wid) in marked_any - set(marks)}
        else:
            marks = edition_marks_for_ayahs(edition, ayah_keys, spec.script_db)
            disputed_ids = set()
        by_id = {w.word_id: w for w in words}
        page_marks = {
            wid: sym for (s, a, wid), sym in marks.items()
            if wid in by_id and sym in TARGET_CLASSES
        }
        saved = 0
        measured = spec.seat_convention == 'measured'
        for wid, sym in sorted(page_marks.items()):
            word = by_id[wid]
            roi = _above_end_roi(
                word.x0, word.x1, word.y0, word.y1, word.y0,
                spec.seat_convention,
            )
            cand = _best_ink_in_roi(
                prepared.binary, roi,
                **_seat_kwargs(word, measured),
            )
            if cand is None and measured:
                # A positive with no stop-sized ink at its seat is a geometry
                # miss or a print difference; a whole-ROI crop would poison
                # the class, so leave it out.
                counts['skipped_no_ink'] += 1
                continue
            if cand is None:
                crop = _extract_roi(prepared.gray, roi, CROP_SIZE)
            else:
                crop = crop_candidate(prepared.gray, cand, size=CROP_SIZE, pad=3)
            folder = out / _safe_class_dir(sym)
            folder.mkdir(parents=True, exist_ok=True)
            name = f'p{page:03d}_s{word.surah}a{word.ayah}_w{wid}_{sym}.png'
            dest = folder / name
            cv2.imwrite(str(dest), crop)
            counts[sym] += 1
            saved += 1
            gallery.append({
                'page': page,
                'surah': word.surah,
                'ayah': word.ayah,
                'word_id': wid,
                'word_key': word.word_key,
                'word_id_space': word.word_id_space,
                'text': word.text,
                'symbol': sym,
                'rel': f'{_safe_class_dir(sym)}/{name}',
            })

        if include_none:
            unmarked = [
                w for w in words
                if w.word_id not in page_marks and w.word_id not in disputed_ids
            ]
            random.Random(seed + page).shuffle(unmarked)
            for word in unmarked[:none_per_page]:
                # Use the same above-word seat as positive inference. This
                # teaches the classifier real empty/haraka/debris contexts,
                # not an easier and distribution-shifted mid-word crop.
                roi = _above_end_roi(
                    word.x0, word.x1, word.y0, word.y1, word.y0,
                    spec.seat_convention,
                )
                cand = _best_ink_in_roi(
                    prepared.binary, roi,
                    **_seat_kwargs(word, measured),
                )
                crop = (
                    crop_candidate(prepared.gray, cand, size=CROP_SIZE, pad=3)
                    if cand is not None
                    else _extract_roi(prepared.gray, roi, CROP_SIZE)
                )
                folder = out / 'none'
                folder.mkdir(parents=True, exist_ok=True)
                name = f'p{page:03d}_w{word.word_id}_none.png'
                dest = folder / name
                cv2.imwrite(str(dest), crop)
                counts['none'] += 1
                gallery.append({
                    'page': page,
                    'surah': word.surah,
                    'ayah': word.ayah,
                    'word_id': word.word_id,
                    'word_key': word.word_key,
                    'word_id_space': word.word_id_space,
                    'text': word.text,
                    'symbol': 'none',
                    'rel': f'none/{name}',
                })

        print(f'  page {page}: {saved} mark crops (+ none)')

    index = _write_gallery(out, edition, pages, counts, gallery)
    manifest = {
        'edition': edition,
        'slug': slug,
        'pages': pages,
        'seed': seed,
        'counts': dict(counts),
        'out': str(out),
        'gallery': str(index),
    }
    (out / 'manifest.json').write_text(
        __import__('json').dumps(manifest, ensure_ascii=False, indent=2),
        encoding='utf-8',
    )
    return manifest


def _write_gallery(
    out: Path,
    edition: str,
    pages: list[int],
    counts: Counter,
    gallery: list[dict],
) -> Path:
    parts = [
        '<!DOCTYPE html><html lang="ar" dir="rtl"><head><meta charset="utf-8">',
        f'<title>Crops · {html.escape(edition)}</title>',
        '<style>',
        'body{font-family:system-ui,sans-serif;background:#f3ebe0;color:#1c1915;margin:16px}',
        'h1{font-size:1.3rem} .meta{color:#6b6358;font-size:.9rem}',
        '.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(140px,1fr));gap:10px}',
        '.card{background:#fff;border:1px solid #ddd;border-radius:8px;padding:8px;text-align:center}',
        '.card img{width:96px;height:96px;object-fit:contain;background:#eee;image-rendering:pixelated}',
        '.sym{font-size:1.4rem;font-family:serif} .tag{font-size:.75rem;color:#6b6358}',
        '</style></head><body>',
        f'<h1>عيّنة قصّ علامات · {html.escape(edition)}</h1>',
        f'<p class="meta">صفحات: {html.escape(", ".join(str(p) for p in pages))}</p>',
        f'<p class="meta">العدد: {html.escape(str(dict(counts)))}</p>',
        '<div class="grid">',
    ]
    # Show marks first, then a sample of none.
    marks = [g for g in gallery if g['symbol'] != 'none']
    nones = [g for g in gallery if g['symbol'] == 'none'][:60]
    for g in marks + nones:
        parts.append(
            '<div class="card">'
            f'<div class="sym">{html.escape(g["symbol"])}</div>'
            f'<img src="{html.escape(g["rel"])}" alt="">'
            f'<div class="tag">p{g["page"]} · {g["surah"]}:{g["ayah"]}<br>'
            f'{html.escape(g.get("text") or "")}</div>'
            '</div>'
        )
    parts.append('</div></body></html>')
    index = out / 'index.html'
    index.write_text('\n'.join(parts), encoding='utf-8')
    return index


def _parse_page_list(spec: str) -> list[int]:
    pages: list[int] = []
    for part in spec.split(','):
        part = part.strip()
        if not part:
            continue
        if '-' in part:
            start, end = part.split('-', 1)
            pages.extend(range(int(start), int(end) + 1))
        else:
            pages.append(int(part))
    return pages


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--edition', default='الشمرلي', choices=list(EDITIONS))
    parser.add_argument(
        '--trusted-all', action='store_true',
        help='sample every trusted edition into per-edition subdirectories',
    )
    parser.add_argument('--pages', type=int, default=40,
                        help='how many random pages to sample')
    parser.add_argument('--seed', type=int, default=7)
    parser.add_argument('--out', type=Path, default=None)
    parser.add_argument('--clear', action='store_true',
                        help='wipe previous labeled crops for this edition')
    parser.add_argument('--no-none', action='store_true')
    parser.add_argument(
        '--page-list', default=None,
        help='explicit pages (comma/range, e.g. 12,40-45) instead of random',
    )
    parser.add_argument(
        '--consensus', default=None,
        help="comma-separated editions whose agreed marks are the labels, "
             "or 'madinah' for the Madinah-family default",
    )
    args = parser.parse_args(argv)
    page_list = _parse_page_list(args.page_list) if args.page_list else None
    consensus = None
    if args.consensus:
        consensus = (
            MADINAH_FAMILY_CONSENSUS if args.consensus == 'madinah'
            else tuple(part.strip() for part in args.consensus.split(','))
        )

    editions = TRUSTED_WAQF_EDITIONS if args.trusted_all else (args.edition,)
    for edition in editions:
        out = args.out
        if args.trusted_all and out is not None:
            out = out / EDITIONS[edition].id
        manifest = sample_crops(
            edition,
            n_pages=args.pages,
            seed=args.seed,
            out_root=out,
            clear=args.clear,
            include_none=not args.no_none,
            pages=page_list,
            consensus=consensus,
        )
        print(manifest)
        print(f'Open gallery: {manifest["gallery"]}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
