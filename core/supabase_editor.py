"""Supabase PostgREST client for mushaf-editor cloud tables.

Uses the service_role key server-side only. When SUPABASE_URL /
SUPABASE_SERVICE_ROLE_KEY are unset, `is_configured()` is False and callers
fall back to local SQLite.
"""
from __future__ import annotations

import hashlib
import logging
import os
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
    return _request('GET', 'editor_marks', params=params) or []


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
            'select': 'edition,surah,ayah,token_index,symbol,word_text',
        }
        out.extend(_request('GET', 'editor_marks', params=params) or [])
    return out


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
    return (rows or [{}])[0]


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


def publish_edition(edition: str, *, actor_id: str | None, actor_name: str | None) -> int:
    """Copy all draft marks for edition → published (upsert). Returns count."""
    drafts = fetch_marks(edition=edition, status='draft')
    count = 0
    for row in drafts:
        symbol = (row.get('symbol') or '').strip()
        if not symbol:
            # Clearing published: delete published row if draft is empty
            delete_mark(
                edition=edition,
                surah=int(row['surah']),
                ayah=int(row['ayah']),
                token_index=int(row['token_index']),
                status='published',
            )
            count += 1
            continue
        upsert_mark(
            edition=edition,
            surah=int(row['surah']),
            ayah=int(row['ayah']),
            token_index=int(row['token_index']),
            status='published',
            symbol=symbol,
            word_text=row.get('word_text'),
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
