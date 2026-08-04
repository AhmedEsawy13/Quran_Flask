"""Build deterministic, layout-aware page queues for CV hand review."""
from __future__ import annotations

import argparse
import json
import math
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from pipeline.cv_waqf.config import ARTIFACTS_ROOT, EDITIONS
from pipeline.cv_waqf.pages import ensure_page_image

SCHEMA_VERSION = 1
DEFAULT_SIZE = 30
DEFAULT_BANDS = 6

# Reviewer-directed calibration batches.  These are added to (not substituted
# for) the broad stratified sample so rare symbols are easy to find in the UI.
PRIORITY_PAGES: dict[str, tuple[int, ...]] = {
    'البحرين': (
        17, 18, 33, 42, 74, 106, 143, 216, 253, 382, 437, 459, 528,
    ),
}


def load_page_stats(layout_db: str) -> list[dict]:
    """Return stable page-level features derived only from the edition layout."""
    conn = sqlite3.connect(layout_db)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT
                page_number,
                COUNT(*) AS line_count,
                SUM(CASE WHEN line_type = 'surah_name' THEN 1 ELSE 0 END)
                    AS surah_headers,
                SUM(CASE WHEN line_type = 'basmallah' THEN 1 ELSE 0 END)
                    AS basmallah_lines,
                SUM(CASE WHEN line_type = 'ayah' AND is_centered = 1 THEN 1 ELSE 0 END)
                    AS centered_ayah_lines,
                SUM(
                    CASE
                        WHEN line_type = 'ayah'
                         AND first_word_id IS NOT NULL
                         AND last_word_id IS NOT NULL
                        THEN MAX(0, last_word_id - first_word_id + 1)
                        ELSE 0
                    END
                ) AS word_count
                ,SUM(LENGTH(line_text) - LENGTH(REPLACE(line_text, 'ۗ', '')))
                    AS q_seats
                ,SUM(LENGTH(line_text) - LENGTH(REPLACE(line_text, 'ۘ', '')))
                    AS m_seats
            FROM pages
            GROUP BY page_number
            ORDER BY page_number
            """
        ).fetchall()
    finally:
        conn.close()
    return [
        {
            'page': int(row['page_number']),
            'line_count': int(row['line_count'] or 0),
            'surah_headers': int(row['surah_headers'] or 0),
            'basmallah_lines': int(row['basmallah_lines'] or 0),
            'centered_ayah_lines': int(row['centered_ayah_lines'] or 0),
            'word_count': int(row['word_count'] or 0),
            'q_seats': int(row['q_seats'] or 0),
            'm_seats': int(row['m_seats'] or 0),
        }
        for row in rows
    ]


def _closest(candidates: list[dict], target: float) -> dict:
    return min(candidates, key=lambda row: (abs(row['page'] - target), row['page']))


def _take(
    selected: list[dict], candidates: list[dict], *, target: float,
    predicate=None, reverse_score=None,
) -> None:
    unused = [row for row in candidates if row not in selected]
    if predicate is not None:
        preferred = [row for row in unused if predicate(row)]
        if preferred:
            unused = preferred
    if not unused:
        return
    if reverse_score is not None:
        best_score = max(reverse_score(row) for row in unused)
        unused = [row for row in unused if reverse_score(row) == best_score]
    selected.append(_closest(unused, target))


def select_stratified_pages(
    stats: list[dict], *, size: int = DEFAULT_SIZE, bands: int = DEFAULT_BANDS,
) -> list[dict]:
    """Select broad page coverage without relying on an untrusted CV model.

    Every geographic band contributes surah-opening, dense, sparse, and
    ordinary pages. Selection is deterministic so reviewers on two machines
    receive the same queue.
    """
    if not stats or size < 1:
        return []
    stats = sorted(stats, key=lambda row: row['page'])
    bands = max(1, min(int(bands), size, len(stats)))
    min_page, max_page = stats[0]['page'], stats[-1]['page']
    span = max_page - min_page + 1
    quota_base, quota_extra = divmod(size, bands)
    selected: list[dict] = []

    for band in range(bands):
        lo = min_page + math.floor(span * band / bands)
        hi = min_page + math.floor(span * (band + 1) / bands) - 1
        if band == bands - 1:
            hi = max_page
        candidates = [row for row in stats if lo <= row['page'] <= hi]
        if not candidates:
            continue
        quota = quota_base + (1 if band < quota_extra else 0)
        band_selected: list[dict] = []
        targets = [
            lo,
            lo + (hi - lo) * 0.25,
            lo + (hi - lo) * 0.50,
            lo + (hi - lo) * 0.75,
            hi,
        ]

        # Boundary pages expose special first/last-page typography.
        if band == 0:
            _take(band_selected, candidates, target=lo)
        elif band == bands - 1:
            _take(band_selected, candidates, target=hi)

        _take(
            band_selected, candidates, target=targets[1],
            predicate=lambda row: row['surah_headers'] > 0,
            reverse_score=lambda row: (
                row['surah_headers'] * 3 + row['basmallah_lines']
            ),
        )
        _take(
            band_selected, candidates, target=targets[2],
            reverse_score=lambda row: row['word_count'],
        )
        _take(
            band_selected, candidates, target=targets[3],
            reverse_score=lambda row: -row['word_count'],
        )
        for target in targets:
            if len(band_selected) >= quota:
                break
            _take(band_selected, candidates, target=target)
        selected.extend(band_selected[:quota])

    # Fill rare empty-band/rounding gaps with pages farthest from those chosen.
    while len(selected) < min(size, len(stats)):
        unused = [row for row in stats if row not in selected]
        if not unused:
            break
        selected_pages = [row['page'] for row in selected]
        row = max(
            unused,
            key=lambda item: (
                min(abs(item['page'] - page) for page in selected_pages),
                item['surah_headers'] > 0,
                item['page'],
            ),
        )
        selected.append(row)

    return sorted(selected[:size], key=lambda row: row['page'])


def _tags(row: dict, dense_cutoff: int, sparse_cutoff: int) -> list[str]:
    tags: list[str] = []
    if row['surah_headers'] >= 2:
        tags.append('multi-surah')
    elif row['surah_headers']:
        tags.append('surah-opening')
    if row['centered_ayah_lines']:
        tags.append('centered-ayah')
    if row['word_count'] >= dense_cutoff:
        tags.append('dense')
    elif row['word_count'] <= sparse_cutoff:
        tags.append('sparse')
    if not tags:
        tags.append('regular')
    if row.get('q_seats'):
        tags.append('rare-q')
    if row.get('m_seats'):
        tags.append('rare-m')
    return tags


def build_review_queue(
    edition: str, *, size: int = DEFAULT_SIZE, bands: int = DEFAULT_BANDS,
) -> dict:
    spec = EDITIONS[edition]
    stats = load_page_stats(spec.layout_db)
    chosen = select_stratified_pages(stats, size=size, bands=bands)
    by_page = {row['page']: row for row in stats}
    priority_numbers = [
        page for page in PRIORITY_PAGES.get(edition, ()) if page in by_page
    ]
    priority_set = set(priority_numbers)
    # Put the requested batch first in its explicit reviewer order.  Keep the
    # original stratified pages afterwards, without duplicates.
    chosen = [by_page[page] for page in priority_numbers] + [
        row for row in chosen if row['page'] not in priority_set
    ]
    word_counts = sorted(row['word_count'] for row in stats)
    sparse_cutoff = word_counts[max(0, len(word_counts) // 4 - 1)]
    dense_cutoff = word_counts[min(len(word_counts) - 1, len(word_counts) * 3 // 4)]
    span = max(1, spec.max_page - spec.min_page + 1)
    pages = []
    for row in chosen:
        item = dict(row)
        item['band'] = min(
            bands,
            max(1, math.ceil((row['page'] - spec.min_page + 1) * bands / span)),
        )
        item['tags'] = _tags(row, dense_cutoff, sparse_cutoff)
        item['priority'] = row['page'] in priority_set
        if item['priority']:
            item['tags'].insert(0, 'targeted')
            item['target_symbols'] = [
                symbol for symbol, count in (
                    ('ق', item.get('q_seats', 0)),
                    ('م', item.get('m_seats', 0)),
                ) if count
            ]
        pages.append(item)
    return {
        'schema_version': SCHEMA_VERSION,
        'edition': edition,
        'slug': spec.id,
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'strategy': 'layout-stratified-plus-targeted-v2',
        'requested_size': int(size),
        'targeted_size': len(priority_numbers),
        'bands': int(bands),
        'pages': pages,
        'instructions': {
            'positive': 'Label every visible waqf mark and confirm its Quran word.',
            'negative': 'Also label at least two mark-like hard negatives as none per page.',
            'training_gate': 'Do not train until every class and none have adequate coverage.',
        },
    }


def write_review_queue(queue: dict) -> tuple[Path, Path]:
    out_dir = ARTIFACTS_ROOT / 'review-queues'
    out_dir.mkdir(parents=True, exist_ok=True)
    slug = queue['slug']
    json_path = out_dir / f'{slug}.json'
    md_path = out_dir / f'{slug}.md'
    json_path.write_text(
        json.dumps(queue, ensure_ascii=False, indent=2) + '\n', encoding='utf-8',
    )
    rows = [
        f"# CV review queue · {queue['edition']}",
        '',
        f"{len(queue['pages'])} pages · {queue['strategy']}",
        '',
        'For each page: label every mark, confirm its word, and add at least two `none` hard negatives.',
        '',
    ]
    for index, item in enumerate(queue['pages'], 1):
        tags = ', '.join(item['tags'])
        rows.append(
            f"- [ ] {index:02d}. [page {item['page']}]"
            f"(/cv-waqf?edition={queue['edition']}&page={item['page']}&mode=label)"
            f" — band {item['band']} · {tags} · {item['word_count']} words"
        )
    md_path.write_text('\n'.join(rows) + '\n', encoding='utf-8')
    return json_path, md_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Build a stratified hand-review page queue')
    parser.add_argument('--edition', required=True, choices=list(EDITIONS))
    parser.add_argument('--size', type=int, default=DEFAULT_SIZE)
    parser.add_argument('--bands', type=int, default=DEFAULT_BANDS)
    parser.add_argument(
        '--cache', action='store_true',
        help='also cache/render every selected page image',
    )
    args = parser.parse_args(argv)
    queue = build_review_queue(args.edition, size=args.size, bands=args.bands)
    json_path, md_path = write_review_queue(queue)
    if args.cache:
        spec = EDITIONS[args.edition]
        for item in queue['pages']:
            ensure_page_image(spec, item['page'])
    page_list = ','.join(str(item['page']) for item in queue['pages'])
    print(f"queue={len(queue['pages'])} pages={page_list}")
    print(f'json={json_path}')
    print(f'review={md_path}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
