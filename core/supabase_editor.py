"""Supabase PostgREST client for mushaf-editor cloud tables.

Uses the service_role key server-side only. When SUPABASE_URL /
SUPABASE_SERVICE_ROLE_KEY are unset, `is_configured()` is False and callers
fall back to local SQLite.
"""
from __future__ import annotations

import hashlib
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any

import requests

logger = logging.getLogger(__name__)

_TIMEOUT = 20


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def is_configured() -> bool:
    return bool(
        (os.environ.get('SUPABASE_URL') or '').strip()
        and (os.environ.get('SUPABASE_SERVICE_ROLE_KEY') or '').strip()
    )


def _base() -> str:
    return (os.environ.get('SUPABASE_URL') or '').strip().rstrip('/')


def _key() -> str:
    return (os.environ.get('SUPABASE_SERVICE_ROLE_KEY') or '').strip()


def _session_secret() -> str:
    return (os.environ.get('EDITOR_SESSION_SECRET') or os.environ.get('SECRET_KEY') or 'dev-editor-secret').strip()


def hash_invite_code(plaintext: str) -> str:
    """SHA-256(code + pepper). Pepper = EDITOR_SESSION_SECRET."""
    raw = (plaintext or '').strip().encode('utf-8')
    pepper = _session_secret().encode('utf-8')
    return hashlib.sha256(pepper + b':' + raw).hexdigest()


def _headers(prefer: str | None = None) -> dict[str, str]:
    h = {
        'apikey': _key(),
        'Authorization': f'Bearer {_key()}',
        'Content-Type': 'application/json',
    }
    if prefer:
        h['Prefer'] = prefer
    return h


class SupabaseEditorError(RuntimeError):
    pass


def _request(method: str, path: str, *, params: dict | None = None,
             json_body: Any = None, prefer: str | None = None) -> Any:
    if not is_configured():
        raise SupabaseEditorError('Supabase editor is not configured')
    url = f'{_base()}/rest/v1/{path.lstrip("/")}'
    try:
        resp = requests.request(
            method, url, params=params, json=json_body,
            headers=_headers(prefer), timeout=_TIMEOUT,
        )
    except requests.RequestException as e:
        raise SupabaseEditorError(f'Supabase request failed: {e}') from e
    if resp.status_code >= 400:
        raise SupabaseEditorError(f'Supabase {resp.status_code}: {resp.text[:400]}')
    if resp.status_code == 204 or not resp.content:
        return None
    return resp.json()


def find_invite_by_code(plaintext: str) -> dict | None:
    code_hash = hash_invite_code(plaintext)
    rows = _request(
        'GET', 'editor_invites',
        params={
            'code_hash': f'eq.{code_hash}',
            'active': 'eq.true',
            'select': 'id,display_name,role,active',
            'limit': '1',
        },
    )
    if not rows:
        return None
    return rows[0]


def touch_invite(invite_id: str) -> None:
    _request(
        'PATCH', 'editor_invites',
        params={'id': f'eq.{invite_id}'},
        json_body={'last_used_at': _now_iso()},
    )


def insert_invite(*, display_name: str, role: str, code_hash: str) -> dict:
    rows = _request(
        'POST', 'editor_invites',
        json_body={
            'display_name': display_name,
            'role': role,
            'code_hash': code_hash,
            'active': True,
        },
        prefer='return=representation',
    )
    return rows[0] if rows else {}


def list_invites() -> list[dict]:
    return _request(
        'GET', 'editor_invites',
        params={
            'select': 'id,display_name,role,active,created_at,last_used_at',
            'order': 'created_at.desc',
        },
    ) or []


def set_invite_active(invite_id: str, active: bool) -> dict | None:
    rows = _request(
        'PATCH', 'editor_invites',
        params={'id': f'eq.{invite_id}', 'select': 'id,display_name,role,active'},
        json_body={'active': active},
        prefer='return=representation',
    )
    if not rows:
        return None
    return rows[0] if isinstance(rows, list) else rows


def fetch_marks(*, edition: str, status: str, surah: int | None = None,
                ayah: int | None = None) -> list[dict]:
    """Fetch marks. Full-edition scans paginate past PostgREST's 1000-row default."""
    params: dict[str, str] = {
        'edition': f'eq.{edition}',
        'status': f'eq.{status}',
        'select': 'edition,surah,ayah,token_index,symbol,word_text,updated_at,updated_by',
        'order': 'surah,ayah,token_index',
    }
    if surah is not None:
        params['surah'] = f'eq.{surah}'
    if ayah is not None:
        params['ayah'] = f'eq.{ayah}'
    # Narrow ayah filters stay under the default page size.
    if surah is not None or ayah is not None:
        return _request('GET', 'editor_marks', params=params) or []

    out: list[dict] = []
    page_size = 1000
    offset = 0
    while True:
        page_params = dict(params)
        page_params['limit'] = str(page_size)
        page_params['offset'] = str(offset)
        chunk = _request('GET', 'editor_marks', params=page_params) or []
        out.extend(chunk)
        if len(chunk) < page_size:
            break
        offset += page_size
    return out


def fetch_marks_for_ayahs(*, edition: str, status: str,
                          ayah_keys: list[tuple[int, int]]) -> list[dict]:
    """Fetch marks for many (surah, ayah) pairs. Batches with OR filter."""
    if not ayah_keys:
        return []
    # PostgREST or=(and(...),and(...)) — chunk to keep URLs sane.
    out: list[dict] = []
    chunk_size = 40
    for i in range(0, len(ayah_keys), chunk_size):
        chunk = ayah_keys[i:i + chunk_size]
        parts = [f'and(surah.eq.{s},ayah.eq.{a})' for s, a in chunk]
        params = {
            'edition': f'eq.{edition}',
            'status': f'eq.{status}',
            'or': f'({",".join(parts)})',
            'select': 'edition,surah,ayah,token_index,symbol,word_text,status',
        }
        out.extend(_request('GET', 'editor_marks', params=params) or [])
    return out


# Short-lived ayah mark cache — spread navigation re-hits the same verses.
_MARK_AYAH_CACHE: dict[tuple[str, str, int, int], tuple[float, list[dict]]] = {}
_MARK_AYAH_TTL_SEC = 45.0


def invalidate_mark_cache(*, edition: str | None = None, surah: int | None = None,
                          ayah: int | None = None) -> None:
    if edition is None and surah is None and ayah is None:
        _MARK_AYAH_CACHE.clear()
        return
    drop = []
    for key in _MARK_AYAH_CACHE:
        ed, _status, s, a = key
        if edition is not None and ed != edition:
            continue
        if surah is not None and s != surah:
            continue
        if ayah is not None and a != ayah:
            continue
        drop.append(key)
    for key in drop:
        _MARK_AYAH_CACHE.pop(key, None)


def fetch_draft_and_published_for_ayahs(*, edition: str,
                                        ayah_keys: list[tuple[int, int]]) -> tuple[list[dict], list[dict]]:
    """One PostgREST round-trip for draft+published marks on the given ayahs.

    Falls back to cached per-ayah rows when still fresh.
    """
    if not ayah_keys:
        return [], []

    now = time.monotonic()
    drafts: list[dict] = []
    published: list[dict] = []
    missing: list[tuple[int, int]] = []

    for surah, ayah in ayah_keys:
        have = True
        for status in ('draft', 'published'):
            cached = _MARK_AYAH_CACHE.get((edition, status, surah, ayah))
            if not cached or (now - cached[0]) > _MARK_AYAH_TTL_SEC:
                have = False
                break
        if not have:
            missing.append((surah, ayah))
            continue
        for status, bucket in (('draft', drafts), ('published', published)):
            cached = _MARK_AYAH_CACHE.get((edition, status, surah, ayah))
            if cached:
                bucket.extend(dict(r) for r in cached[1])

    if not missing:
        return drafts, published

    # Fetch both statuses in one request per chunk.
    chunk_size = 40
    fresh_rows: list[dict] = []
    for i in range(0, len(missing), chunk_size):
        chunk = missing[i:i + chunk_size]
        parts = [f'and(surah.eq.{s},ayah.eq.{a})' for s, a in chunk]
        params = {
            'edition': f'eq.{edition}',
            'status': 'in.(draft,published)',
            'or': f'({",".join(parts)})',
            'select': 'edition,surah,ayah,token_index,symbol,word_text,status',
        }
        fresh_rows.extend(_request('GET', 'editor_marks', params=params) or [])

    by_ayah_status: dict[tuple[int, int, str], list[dict]] = {}
    for row in fresh_rows:
        key = (int(row['surah']), int(row['ayah']), (row.get('status') or '').strip())
        by_ayah_status.setdefault(key, []).append(row)

    now = time.monotonic()
    for surah, ayah in missing:
        for status in ('draft', 'published'):
            rows = by_ayah_status.get((surah, ayah, status), [])
            _MARK_AYAH_CACHE[(edition, status, surah, ayah)] = (now, [dict(r) for r in rows])
            if status == 'draft':
                drafts.extend(dict(r) for r in rows)
            else:
                published.extend(dict(r) for r in rows)

    return drafts, published


def upsert_mark(*, edition: str, surah: int, ayah: int, token_index: int,
                status: str, symbol: str, word_text: str | None,
                updated_by: str | None) -> dict:
    payload = {
        'edition': edition,
        'surah': surah,
        'ayah': ayah,
        'token_index': token_index,
        'status': status,
        'symbol': symbol or '',
        'word_text': word_text,
        'updated_by': updated_by,
        'updated_at': _now_iso(),
    }
    rows = _request(
        'POST', 'editor_marks',
        params={'on_conflict': 'edition,surah,ayah,token_index,status'},
        json_body=payload,
        prefer='resolution=merge-duplicates,return=representation',
    )
    invalidate_mark_cache(edition=edition, surah=surah, ayah=ayah)
    return (rows or [{}])[0]


def upsert_marks_batch(rows: list[dict]) -> int:
    """Bulk upsert editor_marks. Each row needs edition/surah/ayah/token_index/status/symbol."""
    if not rows:
        return 0
    now = _now_iso()
    payload = []
    editions: set[str] = set()
    for r in rows:
        editions.add(r['edition'])
        payload.append({
            'edition': r['edition'],
            'surah': int(r['surah']),
            'ayah': int(r['ayah']),
            'token_index': int(r['token_index']),
            'status': r['status'],
            'symbol': (r.get('symbol') or ''),
            'word_text': r.get('word_text'),
            'updated_by': r.get('updated_by'),
            'updated_at': now,
        })
    # PostgREST accepts a JSON array for multi-row insert/upsert.
    chunk = 200
    done = 0
    for i in range(0, len(payload), chunk):
        part = payload[i:i + chunk]
        _request(
            'POST', 'editor_marks',
            params={'on_conflict': 'edition,surah,ayah,token_index,status'},
            json_body=part,
            prefer='resolution=merge-duplicates,return=minimal',
        )
        done += len(part)
    for edition in editions:
        invalidate_mark_cache(edition=edition)
    return done


def delete_mark(*, edition: str, surah: int, ayah: int, token_index: int,
                status: str) -> None:
    _request(
        'DELETE', 'editor_marks',
        params={
            'edition': f'eq.{edition}',
            'surah': f'eq.{surah}',
            'ayah': f'eq.{ayah}',
            'token_index': f'eq.{token_index}',
            'status': f'eq.{status}',
        },
    )
    invalidate_mark_cache(edition=edition, surah=surah, ayah=ayah)


def get_mark(*, edition: str, surah: int, ayah: int, token_index: int,
             status: str) -> dict | None:
    rows = _request(
        'GET', 'editor_marks',
        params={
            'edition': f'eq.{edition}',
            'surah': f'eq.{surah}',
            'ayah': f'eq.{ayah}',
            'token_index': f'eq.{token_index}',
            'status': f'eq.{status}',
            'select': 'symbol,word_text,updated_at',
            'limit': '1',
        },
    )
    return rows[0] if rows else None


def list_reviewed_pages(edition: str) -> list[int]:
    rows = _request(
        'GET', 'editor_progress',
        params={
            'edition': f'eq.{edition}',
            'reviewed': 'eq.true',
            'select': 'page_number',
            'order': 'page_number',
        },
    ) or []
    return [int(r['page_number']) for r in rows]


def upsert_progress(*, edition: str, page_number: int, reviewed: bool,
                    updated_by: str | None) -> None:
    _request(
        'POST', 'editor_progress',
        params={'on_conflict': 'edition,page_number'},
        json_body={
            'edition': edition,
            'page_number': page_number,
            'reviewed': reviewed,
            'updated_by': updated_by,
            'updated_at': _now_iso(),
        },
        prefer='resolution=merge-duplicates,return=minimal',
    )


def append_audit(**fields: Any) -> None:
    body = {k: v for k, v in fields.items() if v is not None}
    try:
        _request('POST', 'editor_audit', json_body=body, prefer='return=minimal')
    except SupabaseEditorError as e:
        logger.warning('editor_audit write failed: %s', e)


def recent_audit(*, edition: str | None = None, limit: int = 30) -> list[dict]:
    params: dict[str, str] = {
        'select': 'at,actor_name,action,edition,surah,ayah,token_index,word_id,page_number,old_symbol,new_symbol',
        'order': 'at.desc',
        'limit': str(limit),
    }
    if edition:
        params['edition'] = f'eq.{edition}'
    return _request('GET', 'editor_audit', params=params) or []


def pending_publish_diff(edition: str) -> list[dict]:
    """Draft marks that differ from published (what اعتماد will push live).

    Published rows are loaded only for ayahs that have drafts (avoids the
    PostgREST 1000-row default truncating mid-mushaf and showing ∅ for old).
    """
    drafts = fetch_marks(edition=edition, status='draft')
    ayah_keys = sorted({(int(r['surah']), int(r['ayah'])) for r in drafts})
    published = {
        (int(r['surah']), int(r['ayah']), int(r['token_index'])): (r.get('symbol') or '').strip()
        for r in fetch_marks_for_ayahs(
            edition=edition, status='published', ayah_keys=ayah_keys,
        )
    }
    changes: list[dict] = []
    for row in drafts:
        surah = int(row['surah'])
        ayah = int(row['ayah'])
        ti = int(row['token_index'])
        new_symbol = (row.get('symbol') or '').strip()
        old_symbol = published.get((surah, ayah, ti), '')
        if new_symbol == old_symbol:
            continue
        changes.append({
            'surah': surah,
            'ayah': ayah,
            'token_index': ti,
            'word_text': row.get('word_text') or '',
            'old_symbol': old_symbol,
            'new_symbol': new_symbol,
            'updated_at': row.get('updated_at'),
        })
    changes.sort(key=lambda c: (c['surah'], c['ayah'], c['token_index']))
    return changes


def publish_edition(edition: str, *, actor_id: str | None, actor_name: str | None) -> int:
    """Promote draft marks that differ from published. Returns change count."""
    changes = pending_publish_diff(edition)
    count = 0
    for ch in changes:
        surah = int(ch['surah'])
        ayah = int(ch['ayah'])
        ti = int(ch['token_index'])
        symbol = (ch.get('new_symbol') or '').strip()
        if not symbol:
            delete_mark(
                edition=edition,
                surah=surah,
                ayah=ayah,
                token_index=ti,
                status='published',
            )
        else:
            upsert_mark(
                edition=edition,
                surah=surah,
                ayah=ayah,
                token_index=ti,
                status='published',
                symbol=symbol,
                word_text=ch.get('word_text'),
                updated_by=actor_id,
            )
        count += 1
    append_audit(
        actor_id=actor_id,
        actor_name=actor_name,
        action='publish',
        edition=edition,
        meta={'count': count},
    )
    return count
