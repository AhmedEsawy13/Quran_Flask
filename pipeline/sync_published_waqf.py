#!/usr/bin/env python3
"""Synchronize published Qatar/Kuwait cloud marks into mushaf_waqf.db.

The default command is review-only: fetch the complete published snapshot,
validate every token against the canonical QPC word map, and write plan.json
plus review.md. Nothing is changed locally until that exact plan is applied.

    python3 pipeline/sync_published_waqf.py
    python3 pipeline/sync_published_waqf.py --apply artifacts/.../plan.json

Apply verifies both the plan digest and the SQLite SHA-256 recorded during
planning, creates an ignored backup, updates SQLite in one transaction, then
regenerates the baked research caches unless --skip-research is supplied.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import supabase_editor as sb  # noqa: E402
from core.config import CLOUD_EDITOR_EDITIONS, MUSHAF_WAQF_DATABASE  # noqa: E402
from modules.layouts import (  # noqa: E402
    _find_mushaf_row_match_index,
    _get_dk_layout_word_map,
    _normalize_mushaf_word_token,
)

SCHEMA_VERSION = 1
ALLOWED_SYMBOLS = frozenset({'م', 'لا', 'ق', 'ص', 'ج', 'س', 'ع', 'ركوع'})
DEFAULT_ARTIFACT_ROOT = ROOT / 'artifacts' / 'published-waqf-sync'
WordProvider = Callable[[int, int], list[dict]]


class SyncError(RuntimeError):
    """A plan is invalid, stale, or unsafe to apply."""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso_now() -> str:
    return _utc_now().isoformat()


def _quote_identifier(value: str) -> str:
    if value not in CLOUD_EDITOR_EDITIONS:
        raise SyncError(f'unsupported edition: {value!r}')
    return '"' + value.replace('"', '""') + '"'


def database_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _plan_digest(plan: dict) -> str:
    body = {key: value for key, value in plan.items() if key != 'plan_digest'}
    encoded = json.dumps(
        body, ensure_ascii=False, sort_keys=True, separators=(',', ':'),
    ).encode('utf-8')
    return hashlib.sha256(encoded).hexdigest()


def finalize_plan(plan: dict) -> dict:
    plan['plan_digest'] = _plan_digest(plan)
    return plan


def _canonical_words(surah: int, ayah: int) -> list[dict]:
    wmap = _get_dk_layout_word_map()
    first_id = wmap['first_id'].get((surah, ayah))
    last_id = wmap['last_id'].get((surah, ayah))
    if first_id is None or last_id is None:
        return []
    return [
        {'word_id': word_id, 'text': wmap['id2tok'][word_id]['text']}
        for word_id in range(first_id, last_id + 1)
        if word_id in wmap['id2tok']
    ]


def _row_key(row: dict) -> tuple[int, int, int]:
    return int(row['surah']), int(row['ayah']), int(row['token_index'])


def load_local_state(
    database: Path,
    editions: Iterable[str],
    *,
    word_provider: WordProvider = _canonical_words,
) -> dict:
    """Resolve SQLite rows onto canonical zero-based within-ayah token keys."""
    editions = tuple(sorted(set(editions)))
    edition_cols = ', '.join(
        f'{_quote_identifier(edition)} AS "{edition}"' for edition in editions
    )
    conn = sqlite3.connect(database)
    conn.row_factory = sqlite3.Row
    try:
        columns = {row[1] for row in conn.execute('PRAGMA table_info(waqf)')}
        missing = [edition for edition in editions if edition not in columns]
        if missing:
            raise SyncError(f'missing SQLite edition columns: {missing}')
        rows = [dict(row) for row in conn.execute(
            'SELECT rowid, "السورة" AS surah, "الآية" AS ayah, '
            '"الكلمة" AS word, token_index AS db_token_index, word_index, '
            f'{edition_cols} FROM waqf ORDER BY surah, ayah, rowid'
        )]
    finally:
        conn.close()

    grouped: dict[tuple[int, int], list[dict]] = defaultdict(list)
    for row in rows:
        grouped[(int(row['surah']), int(row['ayah']))].append(row)

    row_by_key: dict[tuple[int, int, int], dict] = {}
    marks: dict[str, dict[tuple[int, int, int], dict]] = {
        edition: {} for edition in editions
    }
    errors: list[str] = []
    warnings: list[str] = []

    for (surah, ayah), ayah_rows in grouped.items():
        words = word_provider(surah, ayah)
        search_start = 0
        for row in ayah_rows:
            match_row = {
                'clean_token': row.get('word') or '',
                'word_index': row.get('word_index'),
                # SQLite token_index is not a layout offset.
                'token_index': None,
            }
            matched = _find_mushaf_row_match_index(words, match_row, search_start)
            if matched is None:
                has_selected_mark = any(
                    (row.get(edition) or '').strip() for edition in editions
                )
                message = (
                    f'cannot align SQLite rowid={row["rowid"]} at '
                    f'{surah}:{ayah} word={row.get("word")!r}'
                )
                (errors if has_selected_mark else warnings).append(message)
                continue
            search_start = matched + 1
            key = (surah, ayah, matched)
            if key in row_by_key:
                message = (
                    f'duplicate SQLite mapping at {surah}:{ayah} token {matched}: '
                    f'rowids {row_by_key[key]["rowid"]} and {row["rowid"]}'
                )
                if any((row.get(edition) or '').strip() for edition in editions):
                    errors.append(message)
                else:
                    warnings.append(message)
                continue
            canonical_text = words[matched].get('text') or ''
            mapped = {
                **row,
                'surah': surah,
                'ayah': ayah,
                'token_index': matched,
                'canonical_word': canonical_text,
            }
            row_by_key[key] = mapped
            for edition in editions:
                symbol = (row.get(edition) or '').strip()
                if symbol:
                    marks[edition][key] = {
                        'edition': edition,
                        'surah': surah,
                        'ayah': ayah,
                        'token_index': matched,
                        'symbol': symbol,
                        'word_text': canonical_text,
                        'rowid': int(row['rowid']),
                    }
    return {
        'rows': row_by_key,
        'marks': marks,
        'errors': errors,
        'warnings': warnings,
    }


def validate_cloud_rows(
    rows: Iterable[dict],
    editions: Iterable[str],
    *,
    word_provider: WordProvider = _canonical_words,
) -> dict:
    editions = frozenset(editions)
    marks: dict[str, dict[tuple[int, int, int], dict]] = {
        edition: {} for edition in editions
    }
    errors: list[str] = []
    warnings: list[str] = []

    for offset, source in enumerate(rows):
        row = dict(source)
        edition = (row.get('edition') or '').strip()
        if edition not in editions:
            errors.append(f'cloud row {offset}: unsupported edition {edition!r}')
            continue
        try:
            surah = int(row.get('surah'))
            ayah = int(row.get('ayah'))
            token_index = int(row.get('token_index'))
        except (TypeError, ValueError):
            errors.append(f'cloud row {offset}: invalid location fields')
            continue
        words = word_provider(surah, ayah)
        if not words:
            errors.append(f'cloud row {offset}: unknown ayah {surah}:{ayah}')
            continue
        if not (0 <= token_index < len(words)):
            errors.append(
                f'cloud row {offset}: token {token_index} outside '
                f'{surah}:{ayah} (0..{len(words) - 1})'
            )
            continue
        symbol = (row.get('symbol') or '').strip()
        if symbol not in ALLOWED_SYMBOLS:
            errors.append(
                f'cloud row {offset}: invalid published symbol {symbol!r} '
                f'at {surah}:{ayah}:{token_index}'
            )
            continue
        canonical_word = words[token_index].get('text') or ''
        cloud_word = (row.get('word_text') or '').strip()
        if not cloud_word:
            warnings.append(
                f'cloud row {offset}: missing word_text at '
                f'{surah}:{ayah}:{token_index}; token index was used'
            )
        elif (
            _normalize_mushaf_word_token(cloud_word)
            != _normalize_mushaf_word_token(canonical_word)
        ):
            errors.append(
                f'cloud row {offset}: word mismatch at {surah}:{ayah}:{token_index}: '
                f'{cloud_word!r} != {canonical_word!r}'
            )
            continue
        key = (surah, ayah, token_index)
        if key in marks[edition]:
            errors.append(
                f'duplicate cloud mark for {edition} at '
                f'{surah}:{ayah}:{token_index}'
            )
            continue
        marks[edition][key] = {
            'edition': edition,
            'surah': surah,
            'ayah': ayah,
            'token_index': token_index,
            'symbol': symbol,
            'word_text': canonical_word,
            'updated_at': row.get('updated_at'),
        }
    return {'marks': marks, 'errors': errors, 'warnings': warnings}


def build_plan(
    *,
    database: Path,
    cloud_rows: Iterable[dict],
    editions: Iterable[str],
    source: str,
    min_cloud_coverage: float = 0.80,
    word_provider: WordProvider = _canonical_words,
) -> dict:
    editions = tuple(sorted(set(editions)))
    if not editions or any(edition not in CLOUD_EDITOR_EDITIONS for edition in editions):
        raise SyncError('editions must be a non-empty subset of Qatar/Kuwait')
    if not (0.0 <= min_cloud_coverage <= 1.0):
        raise SyncError('min_cloud_coverage must be between 0 and 1')
    if not database.exists():
        raise SyncError(f'missing database: {database}')

    local = load_local_state(database, editions, word_provider=word_provider)
    cloud = validate_cloud_rows(cloud_rows, editions, word_provider=word_provider)
    errors = list(local['errors']) + list(cloud['errors'])
    warnings = list(local['warnings']) + list(cloud['warnings'])
    changes: list[dict] = []
    summary: dict[str, dict] = {}

    for edition in editions:
        local_marks = local['marks'][edition]
        cloud_marks = cloud['marks'][edition]
        local_count = len(local_marks)
        cloud_count = len(cloud_marks)
        coverage = round(cloud_count / local_count, 4) if local_count else 1.0
        if local_count and coverage < min_cloud_coverage:
            errors.append(
                f'{edition}: cloud snapshot has {cloud_count}/{local_count} marks '
                f'({coverage:.1%}), below the {min_cloud_coverage:.0%} safety floor'
            )
        counts = {'add': 0, 'update': 0, 'delete': 0, 'unchanged': 0}
        for key in sorted(set(local_marks) | set(cloud_marks)):
            old = local_marks.get(key)
            new = cloud_marks.get(key)
            old_symbol = old['symbol'] if old else ''
            new_symbol = new['symbol'] if new else ''
            if old_symbol == new_symbol:
                counts['unchanged'] += 1
                continue
            action = 'add' if not old_symbol else ('delete' if not new_symbol else 'update')
            counts[action] += 1
            source_row = new or old
            changes.append({
                'action': action,
                'edition': edition,
                'surah': key[0],
                'ayah': key[1],
                'token_index': key[2],
                'word_text': source_row.get('word_text') or '',
                'old_symbol': old_symbol,
                'new_symbol': new_symbol,
                'updated_at': (new or {}).get('updated_at'),
            })
        summary[edition] = {
            'local_marks': local_count,
            'cloud_marks': cloud_count,
            'cloud_coverage': coverage,
            **counts,
        }

    changes.sort(key=lambda row: (
        row['edition'], row['surah'], row['ayah'], row['token_index'],
    ))
    plan = {
        'schema_version': SCHEMA_VERSION,
        'generated_at': _iso_now(),
        'source': source,
        'database': str(database.resolve()),
        'database_sha256_before': database_sha256(database),
        'editions': list(editions),
        'min_cloud_coverage': min_cloud_coverage,
        'valid': not errors,
        'summary': summary,
        'validation': {
            'errors': errors,
            'warnings': warnings,
        },
        'changes': changes,
    }
    return finalize_plan(plan)


def _escape_md(value: object) -> str:
    return str(value if value is not None else '').replace('|', '\\|').replace('\n', ' ')


def render_markdown(plan: dict) -> str:
    status = 'PASS — safe to apply' if plan.get('valid') else 'BLOCKED — validation failed'
    lines = [
        '# Published waqf synchronization review',
        '',
        f'- Status: **{status}**',
        f'- Generated: `{plan.get("generated_at", "")}`',
        f'- Source: `{plan.get("source", "")}`',
        f'- Database SHA-256: `{plan.get("database_sha256_before", "")}`',
        f'- Plan digest: `{plan.get("plan_digest", "")}`',
        '',
        '## Summary',
        '',
        '| Edition | Local | Cloud | Coverage | Add | Update | Delete | Unchanged |',
        '|---|---:|---:|---:|---:|---:|---:|---:|',
    ]
    for edition in plan.get('editions', []):
        item = plan.get('summary', {}).get(edition, {})
        lines.append(
            f'| {_escape_md(edition)} | {item.get("local_marks", 0)} | '
            f'{item.get("cloud_marks", 0)} | {item.get("cloud_coverage", 0):.1%} | '
            f'{item.get("add", 0)} | {item.get("update", 0)} | '
            f'{item.get("delete", 0)} | {item.get("unchanged", 0)} |'
        )

    errors = plan.get('validation', {}).get('errors', [])
    warnings = plan.get('validation', {}).get('warnings', [])
    if errors:
        lines.extend(['', '## Blocking errors', ''])
        lines.extend(f'- {_escape_md(message)}' for message in errors)
    if warnings:
        lines.extend(['', '## Warnings', ''])
        lines.extend(f'- {_escape_md(message)}' for message in warnings)

    lines.extend([
        '',
        '## Changes',
        '',
        '| Action | Edition | Verse | Token | Word | Old | New | Updated |',
        '|---|---|---:|---:|---|---:|---:|---|',
    ])
    action_labels = {'add': 'ADD', 'update': 'UPDATE', 'delete': 'DELETE'}
    for row in plan.get('changes', []):
        lines.append(
            f'| {action_labels.get(row.get("action"), row.get("action"))} | '
            f'{_escape_md(row.get("edition"))} | '
            f'{row.get("surah")}:{row.get("ayah")} | '
            f'{int(row.get("token_index", 0)) + 1} | '
            f'{_escape_md(row.get("word_text"))} | '
            f'{_escape_md(row.get("old_symbol") or "∅")} | '
            f'{_escape_md(row.get("new_symbol") or "∅")} | '
            f'{_escape_md(row.get("updated_at") or "")} |'
        )
    if not plan.get('changes'):
        lines.append('| — | — | — | — | No differences | — | — | — |')
    lines.extend([
        '',
        '## Apply',
        '',
        'After scholarly review, apply this exact plan:',
        '',
        '```bash',
        'python3 pipeline/sync_published_waqf.py --apply /absolute/path/to/plan.json',
        '```',
        '',
    ])
    return '\n'.join(lines)


def write_plan_artifacts(plan: dict, output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / 'plan.json'
    markdown_path = output_dir / 'review.md'
    json_path.write_text(
        json.dumps(plan, ensure_ascii=False, indent=2) + '\n', encoding='utf-8',
    )
    markdown_path.write_text(render_markdown(plan), encoding='utf-8')
    return json_path, markdown_path


def _word_index_hint(words: list[dict], token_index: int) -> int:
    return 1 + sum(
        1
        for word in words[:token_index]
        if _normalize_mushaf_word_token(word.get('text') or '')
    )


def verify_plan(plan: dict, database: Path) -> None:
    if plan.get('schema_version') != SCHEMA_VERSION:
        raise SyncError(f'unsupported plan schema: {plan.get("schema_version")!r}')
    expected_digest = plan.get('plan_digest') or ''
    if not expected_digest or _plan_digest(plan) != expected_digest:
        raise SyncError('plan digest mismatch; regenerate the review plan')
    if not plan.get('valid'):
        raise SyncError('plan has blocking validation errors')
    expected_db = plan.get('database_sha256_before') or ''
    actual_db = database_sha256(database)
    if actual_db != expected_db:
        raise SyncError(
            'SQLite changed after planning; regenerate and review a fresh plan '
            f'(expected {expected_db}, got {actual_db})'
        )


def apply_plan(
    plan: dict,
    *,
    database: Path,
    word_provider: WordProvider = _canonical_words,
    backup: bool = True,
) -> dict:
    verify_plan(plan, database)
    editions = tuple(plan.get('editions') or [])
    local = load_local_state(database, editions, word_provider=word_provider)
    if local['errors']:
        raise SyncError('current SQLite alignment failed: ' + '; '.join(local['errors'][:5]))

    backup_path = None
    if backup:
        stamp = _utc_now().strftime('%Y%m%dT%H%M%SZ')
        backup_path = database.with_name(f'{database.stem}.backup_sync_{stamp}{database.suffix}')
        shutil.copy2(database, backup_path)

    conn = sqlite3.connect(database)
    try:
        conn.execute('BEGIN IMMEDIATE')
        used_db_tokens: dict[tuple[int, int], set[int]] = defaultdict(set)
        for row in conn.execute(
            'SELECT "السورة", "الآية", token_index FROM waqf WHERE token_index IS NOT NULL'
        ):
            used_db_tokens[(int(row[0]), int(row[1]))].add(int(row[2]))

        for change in plan.get('changes', []):
            edition = change.get('edition') or ''
            quoted = _quote_identifier(edition)
            key = _row_key(change)
            old_symbol = (change.get('old_symbol') or '').strip()
            new_symbol = (change.get('new_symbol') or '').strip()
            mapped = local['rows'].get(key)
            current = ''
            if mapped:
                current = (mapped.get(edition) or '').strip()
            if current != old_symbol:
                raise SyncError(
                    f'local mark changed at {edition} {key}: '
                    f'expected {old_symbol!r}, got {current!r}'
                )
            if mapped:
                conn.execute(
                    f'UPDATE waqf SET {quoted} = ? WHERE rowid = ?',
                    (new_symbol or None, int(mapped['rowid'])),
                )
                continue
            if not new_symbol:
                raise SyncError(f'cannot delete missing local row at {edition} {key}')

            surah, ayah, token_index = key
            words = word_provider(surah, ayah)
            if not (0 <= token_index < len(words)):
                raise SyncError(f'invalid token while applying {edition} {key}')
            db_token = token_index + 1
            used = used_db_tokens[(surah, ayah)]
            while db_token in used:
                db_token += 1
            used.add(db_token)
            word_text = words[token_index].get('text') or change.get('word_text') or ''
            word_index = _word_index_hint(words, token_index)
            conn.execute(
                f'INSERT INTO waqf '
                f'("السورة","الآية","الكلمة",token_index,word_index,{quoted}) '
                f'VALUES (?, ?, ?, ?, ?, ?)',
                (surah, ayah, word_text, db_token, word_index, new_symbol),
            )

        integrity = conn.execute('PRAGMA integrity_check').fetchone()[0]
        if integrity != 'ok':
            raise SyncError(f'SQLite integrity check failed: {integrity}')
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    post = load_local_state(database, editions, word_provider=word_provider)
    if post['errors']:
        raise SyncError('post-apply alignment failed: ' + '; '.join(post['errors'][:5]))
    for change in plan.get('changes', []):
        key = _row_key(change)
        edition = change['edition']
        actual = (post['marks'][edition].get(key) or {}).get('symbol', '')
        expected = (change.get('new_symbol') or '').strip()
        if actual != expected:
            raise SyncError(
                f'post-apply verification failed at {edition} {key}: '
                f'{actual!r} != {expected!r}'
            )
    return {
        'applied_at': _iso_now(),
        'plan_digest': plan['plan_digest'],
        'database_sha256_after': database_sha256(database),
        'backup': str(backup_path) if backup_path else None,
        'changes_applied': len(plan.get('changes', [])),
    }


def _load_source_json(path: Path) -> list[dict]:
    payload = json.loads(path.read_text(encoding='utf-8'))
    if isinstance(payload, dict):
        payload = payload.get('rows')
    if not isinstance(payload, list):
        raise SyncError('source JSON must be a list or {"rows": [...]}')
    return [dict(row) for row in payload]


def _fetch_published(editions: Iterable[str]) -> list[dict]:
    if not sb.is_configured():
        raise SyncError('set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY first')
    rows: list[dict] = []
    for edition in editions:
        rows.extend(sb.fetch_marks(edition=edition, status='published'))
    return rows


def _default_output_dir() -> Path:
    return DEFAULT_ARTIFACT_ROOT / _utc_now().strftime('%Y%m%dT%H%M%SZ')


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description='Review/apply published Supabase waqf marks into SQLite',
    )
    parser.add_argument('--apply', metavar='PLAN_JSON', type=Path,
                        help='Apply a previously reviewed plan instead of fetching cloud data')
    parser.add_argument('--edition', action='append', dest='editions',
                        choices=sorted(CLOUD_EDITOR_EDITIONS),
                        help='Limit planning to one edition (repeatable)')
    parser.add_argument('--database', type=Path,
                        help='SQLite path (apply defaults to the path recorded in the plan)')
    parser.add_argument('--output-dir', type=Path,
                        help='Plan artifact directory (default: timestamped artifacts folder)')
    parser.add_argument('--source-json', type=Path,
                        help='Offline published-row export instead of Supabase')
    parser.add_argument('--min-cloud-coverage', type=float, default=0.80,
                        help='Block suspiciously incomplete snapshots (default: 0.80)')
    parser.add_argument('--skip-research', action='store_true',
                        help='Do not regenerate data/research_cache after apply')
    parser.add_argument('--no-backup', action='store_true',
                        help='Do not create the ignored SQLite backup before apply')
    return parser.parse_args(argv)


def _load_local_env() -> None:
    """Load the ignored project .env for CLI use when python-dotenv exists."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(ROOT / '.env', override=False)


def research_subprocess_env() -> dict[str, str]:
    """Force cache regeneration to read the synchronized local SQLite data."""
    env = dict(os.environ)
    env.pop('SUPABASE_URL', None)
    env.pop('SUPABASE_SERVICE_ROLE_KEY', None)
    return env


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    _load_local_env()
    try:
        if args.apply:
            plan_path = args.apply.resolve()
            plan = json.loads(plan_path.read_text(encoding='utf-8'))
            database = (
                args.database
                or Path(plan.get('database') or MUSHAF_WAQF_DATABASE)
            ).resolve()
            result = apply_plan(
                plan, database=database, backup=not args.no_backup,
            )
            if not args.skip_research:
                subprocess.run(
                    [sys.executable, str(ROOT / 'pipeline' / 'precompute_research.py')],
                    cwd=ROOT,
                    env=research_subprocess_env(),
                    check=True,
                )
                result['research_caches_regenerated'] = True
            else:
                result['research_caches_regenerated'] = False
            result_path = plan_path.with_name('apply-result.json')
            result_path.write_text(
                json.dumps(result, ensure_ascii=False, indent=2) + '\n',
                encoding='utf-8',
            )
            print(f'Applied {result["changes_applied"]} changes atomically.')
            print(f'Backup: {result.get("backup") or "disabled"}')
            print(f'Result: {result_path}')
            return 0

        editions = tuple(sorted(set(args.editions or CLOUD_EDITOR_EDITIONS)))
        database = (args.database or Path(MUSHAF_WAQF_DATABASE)).resolve()
        if args.source_json:
            cloud_rows = [
                row for row in _load_source_json(args.source_json)
                if (
                    (row.get('edition') or '').strip() in editions
                    or (row.get('edition') or '').strip() not in CLOUD_EDITOR_EDITIONS
                )
            ]
            source = str(args.source_json.resolve())
        else:
            cloud_rows = _fetch_published(editions)
            source = sb._base()
        plan = build_plan(
            database=database,
            cloud_rows=cloud_rows,
            editions=editions,
            source=source,
            min_cloud_coverage=args.min_cloud_coverage,
        )
        output_dir = (args.output_dir or _default_output_dir()).resolve()
        json_path, markdown_path = write_plan_artifacts(plan, output_dir)
        print(f'Plan: {json_path}')
        print(f'Review: {markdown_path}')
        print(f'Changes: {len(plan["changes"])}')
        if not plan['valid']:
            print('BLOCKED: validation errors must be resolved before apply.', file=sys.stderr)
            return 2
        print('PASS: review the Markdown report before applying the plan.')
        return 0
    except (OSError, ValueError, json.JSONDecodeError, sb.SupabaseEditorError, SyncError) as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as exc:
        print(f'ERROR: research cache regeneration failed ({exc.returncode})', file=sys.stderr)
        return exc.returncode or 1


if __name__ == '__main__':
    raise SystemExit(main())
