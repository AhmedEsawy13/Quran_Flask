"""Audit CV detections against mushaf_waqf.db for an edition."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from pipeline.cv_waqf.config import ARTIFACTS_ROOT, EDITIONS
from pipeline.cv_waqf.layout_geo import estimate_layout_words
from pipeline.cv_waqf.marks import edition_marks_for_ayahs
from pipeline.cv_waqf.pages import ensure_page_image
from pipeline.cv_waqf.preprocess import load_bgr, preprocess_page
from pipeline.cv_waqf.run_page import detect_page


def audit_pages(
    edition_key: str,
    pages: list[int],
    *,
    min_conf: float = 0.60,
) -> dict:
    spec = EDITIONS[edition_key]
    diffs: list[dict] = []
    summary = {
        'pages': 0,
        'db_marks': 0,
        'cv_marks': 0,
        'match': 0,
        'wrong': 0,
        'missing': 0,
        'extra': 0,
    }

    for page in pages:
        try:
            ensure_page_image(spec, page)
        except Exception as exc:  # noqa: BLE001
            diffs.append({
                'page': page, 'kind': 'error', 'detail': str(exc),
            })
            continue
        result = detect_page(edition_key, page, min_conf=min_conf)
        bgr = load_bgr(result['image'])
        prepared = preprocess_page(bgr, spec)
        words = estimate_layout_words(spec, page, prepared)
        ayah_keys = sorted({(w.surah, w.ayah) for w in words if w.surah and w.ayah})
        db_marks = edition_marks_for_ayahs(edition_key, ayah_keys, spec.script_db)
        # Restrict DB marks to words actually on this page.
        page_word_ids = {w.word_id for w in words}
        db_on_page = {
            k: v for k, v in db_marks.items() if k[2] in page_word_ids
        }
        cv_map = {
            (m['surah'], m['ayah'], m['word_id']): m
            for m in result['marks']
            if m.get('surah') and m.get('ayah')
        }

        summary['pages'] += 1
        summary['db_marks'] += len(db_on_page)
        summary['cv_marks'] += len(cv_map)

        for key, db_sym in db_on_page.items():
            surah, ayah, word_id = key
            cv = cv_map.get(key)
            if cv is None:
                summary['missing'] += 1
                diffs.append({
                    'page': page,
                    'kind': 'missing',
                    'surah': surah,
                    'ayah': ayah,
                    'word_id': word_id,
                    'db': db_sym,
                    'cv': None,
                })
            elif cv['symbol'] == db_sym:
                summary['match'] += 1
            else:
                summary['wrong'] += 1
                diffs.append({
                    'page': page,
                    'kind': 'wrong',
                    'surah': surah,
                    'ayah': ayah,
                    'word_id': word_id,
                    'db': db_sym,
                    'cv': cv['symbol'],
                    'confidence': cv['confidence'],
                    'text': cv.get('text'),
                })

        for key, cv in cv_map.items():
            if key not in db_on_page:
                summary['extra'] += 1
                diffs.append({
                    'page': page,
                    'kind': 'extra',
                    'surah': key[0],
                    'ayah': key[1],
                    'word_id': key[2],
                    'db': None,
                    'cv': cv['symbol'],
                    'confidence': cv['confidence'],
                    'text': cv.get('text'),
                })

    exact_precision = summary['match'] / max(1, summary['cv_marks'])
    exact_recall = summary['match'] / max(1, summary['db_marks'])
    anchored = summary['match'] + summary['wrong']
    summary['exact_precision'] = round(exact_precision, 4)
    summary['exact_recall'] = round(exact_recall, 4)
    summary['word_attachment_precision'] = round(
        anchored / max(1, summary['cv_marks']), 4,
    )
    summary['word_attachment_recall'] = round(
        anchored / max(1, summary['db_marks']), 4,
    )
    return {
        'edition': edition_key,
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'pages': pages,
        'min_conf': min_conf,
        'summary': summary,
        'diffs': diffs,
    }


def write_review_markdown(report: dict, path: Path) -> None:
    s = report['summary']
    lines = [
        f"# CV waqf audit — {report['edition']}",
        '',
        f"Generated: `{report['generated_at']}`",
        '',
        '## Summary',
        '',
        f"- pages: {s['pages']}",
        f"- DB marks: {s['db_marks']}",
        f"- CV marks: {s['cv_marks']}",
        f"- match: {s['match']}",
        f"- wrong: {s['wrong']}",
        f"- missing (DB only): {s['missing']}",
        f"- extra (CV only): {s['extra']}",
        '',
        '## Diffs (first 200)',
        '',
    ]
    for row in report['diffs'][:200]:
        lines.append(
            f"- p{row.get('page')} {row['kind']} "
            f"{row.get('surah')}:{row.get('ayah')} w{row.get('word_id')} "
            f"db={row.get('db')!r} cv={row.get('cv')!r}"
        )
    path.write_text('\n'.join(lines) + '\n', encoding='utf-8')


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--edition', default='الشمرلي', choices=list(EDITIONS))
    parser.add_argument('--pages', default='2',
                        help='range a-b or comma list')
    parser.add_argument('--min-conf', type=float, default=0.60)
    parser.add_argument(
        '--out-dir', type=Path,
        default=None,
        help='defaults to artifacts/cv-waqf/audit-<edition>/',
    )
    args = parser.parse_args(argv)

    pages = _parse_pages(args.pages)
    report = audit_pages(args.edition, pages, min_conf=args.min_conf)
    out_dir = args.out_dir or (
        ARTIFACTS_ROOT / f"audit-{EDITIONS[args.edition].id}"
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / 'report.json'
    md_path = out_dir / 'review.md'
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8',
    )
    write_review_markdown(report, md_path)
    print(json.dumps(report['summary'], ensure_ascii=False, indent=2))
    print(f'wrote {json_path}')
    print(f'wrote {md_path}')
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
