"""Bootstrap draft waqf marks from CV detections (no auto-publish)."""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from pipeline.cv_waqf.config import (
    ARTIFACTS_ROOT,
    EDITIONS,
    resolve_auto_set_min_conf,
    split_marks_by_trust,
)
from pipeline.cv_waqf.marks import within_ayah_token_index
from pipeline.cv_waqf.run_page import detect_page

SCHEMA_VERSION = 1
ALLOWED = frozenset({'م', 'لا', 'ق', 'ص', 'ج', 'س', 'ع'})


def bootstrap_pages(
    edition_key: str,
    pages: list[int],
    *,
    min_conf: float | None = None,
) -> dict:
    spec = EDITIONS[edition_key]
    write_conf = resolve_auto_set_min_conf(edition_key, min_conf)
    detect_conf = min(spec.review_min_conf, write_conf)
    changes: list[dict] = []
    review_candidates: list[dict] = []
    errors: list[str] = []
    seen: set[tuple[int, int, int]] = set()
    review_seen: set[tuple[int, int, int]] = set()

    for page in pages:
        try:
            result = detect_page(edition_key, page, min_conf=detect_conf)
        except Exception as exc:  # noqa: BLE001
            errors.append(f'page {page}: {exc}')
            continue
        # detect_page already dropped Azhar-empty words from marks for البحرين.
        trusted, review = split_marks_by_trust(result['marks'], write_conf)
        for mark in trusted:
            row = _draft_row(spec, edition_key, page, mark, errors)
            if row is None:
                continue
            key = (row['surah'], row['ayah'], row['token_index'])
            if key in seen:
                existing = next(
                    c for c in changes
                    if (c['surah'], c['ayah'], c['token_index']) == key
                )
                if mark['confidence'] <= existing['confidence']:
                    continue
                changes.remove(existing)
            seen.add(key)
            changes.append(row)
        for mark in review:
            row = _draft_row(spec, edition_key, page, mark, errors)
            if row is None:
                continue
            key = (row['surah'], row['ayah'], row['token_index'])
            if key in seen or key in review_seen:
                continue
            review_seen.add(key)
            review_candidates.append({**row, 'op': 'review'})

    changes.sort(key=lambda r: (r['surah'], r['ayah'], r['token_index']))
    review_candidates.sort(key=lambda r: (r['surah'], r['ayah'], r['token_index']))
    plan = {
        'schema_version': SCHEMA_VERSION,
        'source': 'opencv5-cv-waqf',
        'edition': edition_key,
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'pages': pages,
        'min_conf': write_conf,
        'review_min_conf': detect_conf,
        'auto_set_min_conf': spec.auto_set_min_conf,
        'changes': changes,
        'review_candidates': review_candidates,
        'errors': errors,
        'note': (
            'Draft only — review before writing mushaf_waqf.db or publishing '
            'cloud marks. Not an auto-apply published-sync plan. '
            f'changes are auto-set (confidence >= {write_conf:.2f}); '
            'review_candidates are held back for a human.'
        ),
    }
    plan['plan_digest'] = _digest(plan)
    return plan


def _draft_row(
    spec,
    edition_key: str,
    page: int,
    mark: dict,
    errors: list[str],
) -> dict | None:
    if mark['symbol'] not in ALLOWED:
        return None
    loc = within_ayah_token_index(spec.script_db, int(mark['word_id']))
    if loc is None:
        errors.append(
            f"page {page}: unknown word_id {mark['word_id']}"
        )
        return None
    surah, ayah, token_index, text = loc
    return {
        'op': 'set',
        'edition': edition_key,
        'surah': surah,
        'ayah': ayah,
        'token_index': token_index,
        'word_index': mark['word_id'],
        'word_key': mark.get('word_key') or f'{surah}:{ayah}:{token_index + 1}',
        'word_id_space': mark.get('word_id_space') or '',
        'word_text': text or mark.get('text') or '',
        'symbol': mark['symbol'],
        'confidence': round(float(mark['confidence']), 4),
        'page': page,
        'source': 'opencv5-cv-waqf',
    }


def _digest(plan: dict) -> str:
    body = {k: v for k, v in plan.items() if k != 'plan_digest'}
    encoded = json.dumps(
        body, ensure_ascii=False, sort_keys=True, separators=(',', ':'),
    ).encode('utf-8')
    return hashlib.sha256(encoded).hexdigest()


def write_review_markdown(plan: dict, path: Path) -> None:
    lines = [
        f"# CV waqf bootstrap — {plan['edition']}",
        '',
        f"Generated: `{plan['generated_at']}`",
        f"Digest: `{plan['plan_digest']}`",
        f"Pages: {plan['pages']}",
        f"Changes: {len(plan['changes'])}",
        f"Review candidates (not auto-set): {len(plan.get('review_candidates') or [])}",
        '',
        '## Sample changes (first 100)',
        '',
    ]
    for row in plan['changes'][:100]:
        lines.append(
            f"- p{row['page']} {row['surah']}:{row['ayah']} "
            f"tok{row['token_index']} → {row['symbol']} "
            f"({row['confidence']}) {row['word_text']}"
        )
    if plan.get('errors'):
        lines.extend(['', '## Errors', ''])
        for err in plan['errors'][:50]:
            lines.append(f'- {err}')
    path.write_text('\n'.join(lines) + '\n', encoding='utf-8')


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--edition', default='البحرين', choices=list(EDITIONS))
    parser.add_argument('--pages', default='1-5')
    parser.add_argument(
        '--min-conf', type=float, default=None,
        help='override the edition auto-set threshold '
             '(0.85 for البحرين, 0.70 otherwise)',
    )
    parser.add_argument('--out-dir', type=Path, default=None)
    args = parser.parse_args(argv)

    pages = _parse_pages(args.pages)
    plan = bootstrap_pages(args.edition, pages, min_conf=args.min_conf)
    out_dir = args.out_dir or (
        ARTIFACTS_ROOT / f"bootstrap-{EDITIONS[args.edition].id}"
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    plan_path = out_dir / 'plan.json'
    md_path = out_dir / 'review.md'
    plan_path.write_text(
        json.dumps(plan, ensure_ascii=False, indent=2), encoding='utf-8',
    )
    write_review_markdown(plan, md_path)
    print(
        json.dumps({
            'edition': plan['edition'],
            'changes': len(plan['changes']),
            'errors': len(plan['errors']),
            'digest': plan['plan_digest'],
            'plan': str(plan_path),
        }, ensure_ascii=False, indent=2)
    )
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
