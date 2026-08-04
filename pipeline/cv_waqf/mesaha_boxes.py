"""Export Mesaha DjVu WORD boxes aligned to layout word_index spans."""
from __future__ import annotations

import argparse
import sqlite3
import xml.etree.ElementTree as ET
from pathlib import Path

from pipeline.cv_waqf.config import (
    EDITIONS,
    MESAHA_BOXES_DB,
    MESAHA_OCR_DIR,
    EditionSpec,
)
from pipeline.cv_waqf.layout_geo import _ids_between


def _word_box(node) -> tuple[int, int, int, int] | None:
    raw = node.get('coords') or ''
    try:
        a, b, c, d = (int(part) for part in raw.split(','))
    except (TypeError, ValueError):
        return None
    return min(a, c), min(b, d), max(a, c), max(b, d)


def load_ocr_page_word_boxes(xml_path: Path, leaf_index: int) -> list[list[tuple[int, int, int, int]]]:
    """Return per-LINE lists of WORD boxes for one OBJECT (0-based leaf)."""
    root = ET.parse(xml_path).getroot()
    objects = root.findall('.//OBJECT')
    if leaf_index < 0 or leaf_index >= len(objects):
        return []
    obj = objects[leaf_index]
    lines: list[list[tuple[int, int, int, int]]] = []
    for line in obj.findall('.//LINE'):
        boxes = [box for box in (_word_box(w) for w in line.findall('WORD')) if box]
        if boxes:
            lines.append(boxes)
    return lines


def _layout_ayah_spans(spec: EditionSpec, page: int) -> list[list[int]]:
    conn = sqlite3.connect(spec.layout_db)
    try:
        rows = conn.execute(
            '''
            SELECT first_word_id, last_word_id, line_type
            FROM pages
            WHERE page_number = ?
            ORDER BY line_number ASC
            ''',
            (page,),
        ).fetchall()
    finally:
        conn.close()
    spans: list[list[int]] = []
    for first_id, last_id, line_type in rows:
        if first_id is None or last_id is None:
            continue
        if (line_type or '') in ('surah_name', 'surah_info', 'basmallah', 'basmala'):
            continue
        first_id, last_id = int(first_id), int(last_id)
        ids = _ids_between(spec.script_db, first_id, last_id)
        if ids:
            spans.append(ids)
    return spans


def build_mesaha_boxes(
    *,
    xml_path: Path,
    out_db: Path = MESAHA_BOXES_DB,
    page_start: int | None = None,
    page_end: int | None = None,
) -> dict:
    spec = EDITIONS['المساحة']
    if not Path(spec.layout_db).is_file():
        raise FileNotFoundError(f'mesaha layout missing: {spec.layout_db}')
    if not xml_path.is_file():
        raise FileNotFoundError(xml_path)

    page_start = page_start or spec.min_page
    page_end = page_end or spec.max_page
    out_db.parent.mkdir(parents=True, exist_ok=True)
    if out_db.exists():
        out_db.unlink()
    conn = sqlite3.connect(out_db)
    conn.execute(
        '''
        CREATE TABLE word_boxes (
            page INTEGER NOT NULL,
            word_index INTEGER NOT NULL,
            x0 INTEGER NOT NULL,
            y0 INTEGER NOT NULL,
            x1 INTEGER NOT NULL,
            y1 INTEGER NOT NULL,
            PRIMARY KEY (page, word_index)
        )
        '''
    )
    inserted = 0
    pages_done = 0
    for page in range(page_start, page_end + 1):
        leaf = page + int(spec.leaf_offset)
        ocr_lines = load_ocr_page_word_boxes(xml_path, leaf)
        spans = _layout_ayah_spans(spec, page)
        if not ocr_lines or not spans:
            continue
        # Pair by order: take min(len) ayah-like OCR lines (skip short headers).
        ocr_body = [ln for ln in ocr_lines if len(ln) >= 2]
        n = min(len(ocr_body), len(spans))
        for i in range(n):
            boxes = ocr_body[i]
            ids = spans[i]
            # OCR boxes are LTR in file order; Arabic line is RTL visually.
            # Sort by x descending so index 0 ≈ rightmost ≈ first mushaf word.
            ordered = sorted(boxes, key=lambda b: -((b[0] + b[2]) / 2))
            m = min(len(ordered), len(ids))
            for j in range(m):
                x0, y0, x1, y1 = ordered[j]
                conn.execute(
                    'INSERT OR REPLACE INTO word_boxes '
                    '(page, word_index, x0, y0, x1, y1) VALUES (?,?,?,?,?,?)',
                    (page, ids[j], x0, y0, x1, y1),
                )
                inserted += 1
        pages_done += 1
        if pages_done % 50 == 0:
            conn.commit()
    conn.commit()
    conn.close()
    return {
        'db': str(out_db),
        'pages': pages_done,
        'boxes': inserted,
        'xml': str(xml_path),
    }


def lookup_box(db: Path, page: int, word_index: int) -> tuple[int, int, int, int] | None:
    if not db.is_file():
        return None
    conn = sqlite3.connect(db)
    try:
        row = conn.execute(
            'SELECT x0,y0,x1,y1 FROM word_boxes WHERE page=? AND word_index=?',
            (page, word_index),
        ).fetchone()
        return tuple(row) if row else None
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--ocr-xml',
        type=Path,
        default=MESAHA_OCR_DIR / 'mushafElMesaha_djvu.xml',
    )
    parser.add_argument('--out', type=Path, default=MESAHA_BOXES_DB)
    parser.add_argument('--page-start', type=int, default=None)
    parser.add_argument('--page-end', type=int, default=None)
    args = parser.parse_args(argv)
    result = build_mesaha_boxes(
        xml_path=args.ocr_xml,
        out_db=args.out,
        page_start=args.page_start,
        page_end=args.page_end,
    )
    print(result)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
