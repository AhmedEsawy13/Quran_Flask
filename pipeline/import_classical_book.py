#!/usr/bin/env python3
"""Validate and import a classical waqf book without an LLM.

A book-specific parser produces JSONL candidates.  This command owns the
shared, strict part of the pipeline:

* closed grade lexicon;
* exact ayah and Qur'an-word alignment;
* ambiguity rejection (never silently choose one repeated word);
* transactional replacement of one source only;
* source checksum and per-row provenance;
* machine-readable review queue for anything that cannot be proved.

Candidate JSONL fields:

    {"surah": 2, "ayah": 255, "quote": "السماوات والأرض",
     "grade": "كاف", "grade_raw": "كاف", "note": "...",
     "reported_from": null, "locator": "PageV01P123:paragraph-4",
     "expected_wpos": 43}

``expected_wpos`` is optional when the quote has exactly one exact/prefix
match in the ayah.  It is required to disambiguate repeated phrases.  The
book parser must copy evidence from the source; this importer performs no
semantic inference and makes no network/API calls.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'pipeline'))
os.environ.setdefault('RESEARCH_PRECOMPUTE', '1')

import app  # noqa: E402
import build_classical_waqf as classical  # noqa: E402

CANONICAL_GRADES = {canonical for _, canonical in classical.GRADES}


@dataclass(frozen=True)
class Candidate:
    surah: int
    ayah: int
    quote: str
    grade: str
    grade_raw: str
    note: str = ''
    reported_from: str | None = None
    locator: str = ''
    expected_wpos: int | None = None


@dataclass(frozen=True)
class Accepted:
    candidate: Candidate
    wpos: int
    stop_word: str


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def exact_alignment_candidates(surah: int, ayah: int, quote: str) -> list[int]:
    """Return every exact/prefix-aligned end position; fuzzy matches excluded."""
    key = f'{surah}:{ayah}'
    if key not in app.qpc_hafs_data_normalized:
        return []
    _, words, _ = app._verse_word_texts(key)
    verse = [classical.norm(word) for word in words]
    quoted = classical.quote_words(quote)
    if not quoted:
        return []

    # Prefer the longest available suffix, matching the established aligner.
    for length in dict.fromkeys((min(3, len(quoted)), 2, 1)):
        if length < 1 or length > len(quoted):
            continue
        tail = quoted[-length:]
        hits = []
        for start in range(0, len(verse) - length + 1):
            if all(classical.match_word(tail[i], verse[start + i], level=1)
                   for i in range(length)):
                hits.append(start + length - 1)
        if hits:
            return hits
    return []


def candidate_from_dict(raw: dict) -> Candidate:
    required = ('surah', 'ayah', 'quote', 'grade')
    missing = [key for key in required if key not in raw]
    if missing:
        raise ValueError(f'missing fields: {", ".join(missing)}')
    grade = str(raw['grade']).strip()
    return Candidate(
        surah=int(raw['surah']), ayah=int(raw['ayah']),
        quote=str(raw['quote']).strip(), grade=grade,
        grade_raw=str(raw.get('grade_raw') or grade).strip(),
        note=str(raw.get('note') or '').strip(),
        reported_from=(str(raw['reported_from']).strip()
                       if raw.get('reported_from') else None),
        locator=str(raw.get('locator') or '').strip(),
        expected_wpos=(int(raw['expected_wpos'])
                       if raw.get('expected_wpos') is not None else None),
    )


def validate(candidate: Candidate) -> tuple[Accepted | None, str | None]:
    if candidate.grade not in CANONICAL_GRADES:
        return None, 'unknown_grade'
    if not 1 <= candidate.surah <= 114:
        return None, 'invalid_surah'
    if not 1 <= candidate.ayah <= classical.surah_ayah_count(candidate.surah):
        return None, 'invalid_ayah'
    if not candidate.quote or not classical.quote_words(candidate.quote):
        return None, 'empty_quote'
    if not candidate.locator:
        return None, 'missing_source_locator'

    hits = exact_alignment_candidates(candidate.surah, candidate.ayah, candidate.quote)
    if not hits:
        return None, 'unaligned_quote'
    if candidate.expected_wpos is not None:
        if candidate.expected_wpos not in hits:
            return None, 'expected_wpos_mismatch'
        wpos = candidate.expected_wpos
    elif len(hits) == 1:
        wpos = hits[0]
    else:
        return None, 'ambiguous_repeated_phrase'

    _, words, _ = app._verse_word_texts(f'{candidate.surah}:{candidate.ayah}')
    return Accepted(candidate, wpos, words[wpos]), None


def read_candidates(path: Path) -> tuple[list[Accepted], list[dict]]:
    accepted, rejected = [], []
    with path.open(encoding='utf-8') as fh:
        for line_number, line in enumerate(fh, 1):
            if not line.strip():
                continue
            try:
                raw = json.loads(line)
                candidate = candidate_from_dict(raw)
                row, reason = validate(candidate)
            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                rejected.append({'line': line_number, 'reason': 'invalid_json_or_schema',
                                 'detail': str(exc), 'raw': line.rstrip()})
                continue
            if row is None:
                rejected.append({'line': line_number, 'reason': reason,
                                 'candidate': asdict(candidate)})
            else:
                accepted.append(row)
    return accepted, rejected


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute('''CREATE TABLE IF NOT EXISTS classical_editions (
        source TEXT PRIMARY KEY, title_ar TEXT NOT NULL, author_ar TEXT NOT NULL,
        source_file TEXT NOT NULL, source_sha256 TEXT NOT NULL,
        parser TEXT NOT NULL, imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS classical_provenance (
        classical_id INTEGER PRIMARY KEY REFERENCES classical(id) ON DELETE CASCADE,
        source_locator TEXT NOT NULL, source_sha256 TEXT NOT NULL,
        parser TEXT NOT NULL, evidence TEXT NOT NULL)''')


def replace_source(db: Path, source_key: str, title_ar: str, author_ar: str,
                   parser: str, source_file: Path, rows: list[Accepted]) -> None:
    checksum = sha256_file(source_file)
    conn = sqlite3.connect(db)
    try:
        conn.execute('PRAGMA foreign_keys=ON')
        ensure_schema(conn)
        conn.execute('BEGIN IMMEDIATE')
        old_ids = [r[0] for r in conn.execute(
            'SELECT id FROM classical WHERE source=?', (source_key,))]
        if old_ids:
            conn.executemany('DELETE FROM classical_provenance WHERE classical_id=?',
                             ((row_id,) for row_id in old_ids))
        conn.execute('DELETE FROM classical WHERE source=?', (source_key,))
        conn.execute('DELETE FROM classical_editions WHERE source=?', (source_key,))
        conn.execute(
            'INSERT INTO classical_editions '
            '(source,title_ar,author_ar,source_file,source_sha256,parser) '
            'VALUES (?,?,?,?,?,?)',
            (source_key, title_ar, author_ar, str(source_file.relative_to(ROOT)),
             checksum, parser))
        for seq, accepted in enumerate(rows, 1):
            c = accepted.candidate
            cur = conn.execute(
                'INSERT INTO classical '
                '(source,surah,ayah,wpos,stop_word,quote,grade,grade_raw,note,seq,conf,reported_from) '
                'VALUES (?,?,?,?,?,?,?,?,?,?,1,?)',
                (source_key, c.surah, c.ayah, accepted.wpos, accepted.stop_word,
                 c.quote, c.grade, c.grade_raw, c.note, seq, c.reported_from))
            conn.execute(
                'INSERT INTO classical_provenance '
                '(classical_id,source_locator,source_sha256,parser,evidence) '
                'VALUES (?,?,?,?,?)',
                (cur.lastrowid, c.locator, checksum, parser, c.quote))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def write_review_queue(path: Path, rejected: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8') as fh:
        for item in rejected:
            fh.write(json.dumps(item, ensure_ascii=False, sort_keys=True) + '\n')


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--source-key', required=True)
    ap.add_argument('--title-ar', required=True)
    ap.add_argument('--author-ar', required=True)
    ap.add_argument('--parser', required=True)
    ap.add_argument('--source-file', type=Path, required=True)
    ap.add_argument('--candidates', type=Path, required=True)
    ap.add_argument('--db', type=Path, default=ROOT / 'data' / 'classical_waqf.db')
    ap.add_argument('--review-out', type=Path,
                    default=ROOT / 'pipeline' / 'classical_review_queue.jsonl')
    ap.add_argument('--write', action='store_true', help='replace this source in the DB')
    args = ap.parse_args(argv)

    source_file = args.source_file.resolve()
    if not source_file.is_file():
        ap.error(f'source file does not exist: {source_file}')
    accepted, rejected = read_candidates(args.candidates)
    write_review_queue(args.review_out, rejected)
    print(f'accepted={len(accepted)} rejected={len(rejected)} review={args.review_out}')
    if rejected:
        counts: dict[str, int] = {}
        for row in rejected:
            counts[row['reason']] = counts.get(row['reason'], 0) + 1
        print(f'rejection reasons: {counts}')
    if args.write:
        if not accepted:
            raise SystemExit('refusing to replace a source with zero accepted rows')
        replace_source(args.db, args.source_key, args.title_ar, args.author_ar,
                       args.parser, source_file, accepted)
        print(f'wrote source={args.source_key} rows={len(accepted)} db={args.db}')
    return 0 if not rejected else 2


if __name__ == '__main__':
    raise SystemExit(main())
