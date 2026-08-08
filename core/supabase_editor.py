"""Supabase PostgREST client for mushaf-editor cloud tables.

Uses the service_role key server-side only. When SUPABASE_URL /
SUPABASE_SERVICE_ROLE_KEY are unset, `is_configured()` is False and callers
fall back to local SQLite.
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
import time
from datetime import datetime, timezone
from typing import Any

import requests
from werkzeug.security import check_password_hash, generate_password_hash

logger = logging.getLogger(__name__)

_TIMEOUT = 20
_USERNAME_RE = re.compile(r'^[a-zA-Z0-9._-]{3,32}$')
MIN_PASSWORD_LEN = 8


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
    """SHA-256(code + pepper). Pepper = EDITOR_SESSION_SECRET.

    Legacy helper kept for older rows; new accounts use password_hash.
    """
    raw = (plaintext or '').strip().encode('utf-8')
    pepper = _session_secret().encode('utf-8')
    return hashlib.sha256(pepper + b':' + raw).hexdigest()


def normalize_username(username: str) -> str:
    return (username or '').strip().lower()


def validate_username(username: str) -> str | None:
    """Return normalized username or None if invalid."""
    raw = (username or '').strip()
    if not _USERNAME_RE.fullmatch(raw):
        return None
    return raw.lower()


def validate_password(password: str) -> bool:
    return len((password or '').strip()) >= MIN_PASSWORD_LEN


def hash_password(password: str) -> str:
    return generate_password_hash((password or '').strip())


def verify_password(password_hash: str | None, password: str) -> bool:
    if not password_hash or not password:
        return False
    try:
        return check_password_hash(password_hash, password.strip())
    except (ValueError, TypeError):
        return False


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


class SupabaseResponseError(SupabaseEditorError):
    """A non-success response whose body is retained for internal decisions."""

    def __init__(self, status_code: int, body: str) -> None:
        self.status_code = int(status_code)
        self.body = body
        super().__init__(f'Supabase request returned HTTP {self.status_code}')


class PublishConflict(SupabaseEditorError):
    """The reviewed draft snapshot no longer matches the database."""


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
        logger.error('Supabase request failed: %s', e)
        raise SupabaseEditorError('Supabase request failed') from e
    if resp.status_code >= 400:
        body = (getattr(resp, 'text', '') or '')[:400]
        logger.error('Supabase HTTP %s response: %s', resp.status_code, body)
        raise SupabaseResponseError(resp.status_code, body)
    if resp.status_code == 204 or not resp.content:
        return None
    try:
        payload = resp.json()
    except (ValueError, requests.JSONDecodeError) as exc:
        body = (getattr(resp, 'text', '') or '')[:400]
        logger.error(
            'Supabase successful response was not JSON (HTTP %s): %s',
            resp.status_code,
            body,
        )
        raise SupabaseEditorError(
            'Supabase returned a malformed successful response'
        ) from exc
    # PostgREST table/view endpoints always serialize row sets as arrays.
    # Reject a proxy error object or other valid-but-wrong JSON here instead of
    # letting downstream code interpret it as rows. RPCs define their own shape.
    if not path.lstrip('/').startswith('rpc/') and not isinstance(payload, list):
        logger.error(
            'Supabase successful response had invalid shape for %s: %s',
            path,
            type(payload).__name__,
        )
        raise SupabaseEditorError(
            'Supabase returned a malformed successful response'
        )
    return payload


def find_invite_by_username(username: str) -> dict | None:
    """Lookup active account by username (case-insensitive). Includes password_hash."""
    uname = normalize_username(username)
    if not uname:
        return None
    rows = _request(
        'GET', 'editor_invites',
        params={
            'username': f'eq.{uname}',
            'active': 'eq.true',
            'select': 'id,display_name,role,active,username,password_hash',
            'limit': '1',
        },
    )
    if not rows:
        return None
    return rows[0]


def find_invite_by_code(plaintext: str) -> dict | None:
    """Legacy invite-code lookup (kept for migration / emergency)."""
    code_hash = hash_invite_code(plaintext)
    rows = _request(
        'GET', 'editor_invites',
        params={
            'code_hash': f'eq.{code_hash}',
            'active': 'eq.true',
            'select': 'id,display_name,role,active,username',
            'limit': '1',
        },
    )
    if not rows:
        return None
    return rows[0]


def find_active_invite_by_id(invite_id: str) -> dict | None:
    """Return the current invite state for a signed editor session.

    Session cookies can outlive an invite revocation, so protected requests
    must periodically revalidate the invite instead of trusting the signed
    role/name snapshot for the full cookie lifetime.
    """
    rows = _request(
        'GET', 'editor_invites',
        params={
            'id': f'eq.{invite_id}',
            'active': 'eq.true',
            'select': 'id,display_name,role,active,username',
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


def insert_invite(
    *,
    display_name: str,
    role: str,
    username: str,
    password_hash: str,
    code_hash: str | None = None,
) -> dict:
    body: dict[str, Any] = {
        'display_name': display_name,
        'role': role,
        'username': normalize_username(username),
        'password_hash': password_hash,
        'active': True,
    }
    if code_hash:
        body['code_hash'] = code_hash
    rows = _request(
        'POST', 'editor_invites',
        json_body=body,
        prefer='return=representation',
    )
    return rows[0] if rows else {}


def set_invite_credentials(
    *,
    invite_id: str | None = None,
    display_name: str | None = None,
    username: str | None = None,
    password_hash: str | None = None,
) -> dict | None:
    """Attach/update username and/or password on an existing invite row."""
    body: dict[str, Any] = {}
    if username is not None:
        body['username'] = normalize_username(username)
    if password_hash is not None:
        body['password_hash'] = password_hash
    if not body:
        raise ValueError('username or password_hash required')
    params: dict[str, str] = {
        'select': 'id,display_name,role,active,username',
    }
    if invite_id:
        params['id'] = f'eq.{invite_id}'
    elif display_name:
        params['display_name'] = f'eq.{display_name.strip()}'
    else:
        raise ValueError('invite_id or display_name required')
    rows = _request(
        'PATCH', 'editor_invites',
        params=params,
        json_body=body,
        prefer='return=representation',
    )
    if not rows:
        return None
    return rows[0] if isinstance(rows, list) else rows


def list_invites() -> list[dict]:
    return _request(
        'GET', 'editor_invites',
        params={
            'select': 'id,display_name,role,active,username,created_at,last_used_at',
            'order': 'created_at.desc',
        },
    ) or []


def set_invite_active(invite_id: str, active: bool) -> dict | None:
    rows = _request(
        'PATCH', 'editor_invites',
        params={'id': f'eq.{invite_id}', 'select': 'id,display_name,role,active,username'},
        json_body={'active': active},
        prefer='return=representation',
    )
    if not rows:
        return None
    return rows[0] if isinstance(rows, list) else rows


def fetch_marks(*, edition: str, status: str, surah: int | None = None,
                ayah: int | None = None) -> list[dict]:
    """Fetch marks. Full-edition scans paginate past PostgREST's 1000-row default."""
    # Pending review repeatedly scans drafts; cache the small result briefly.
    if status == 'draft' and surah is None and ayah is None:
        cached = _DRAFT_LIST_CACHE.get(edition)
        if cached and (time.monotonic() - cached[0]) <= _DRAFT_LIST_TTL_SEC:
            return [dict(r) for r in cached[1]]

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
    if status == 'draft':
        _DRAFT_LIST_CACHE[edition] = (time.monotonic(), [dict(r) for r in out])
    return out


def fetch_marks_for_ayahs(*, edition: str, status: str,
                          ayah_keys: list[tuple[int, int]]) -> list[dict]:
    """Fetch marks for many (surah, ayah) pairs. Batches with OR filter."""
    if not ayah_keys:
        return []

    now = time.monotonic()
    out: list[dict] = []
    missing: list[tuple[int, int]] = []
    for surah, ayah in ayah_keys:
        cached = _MARK_AYAH_CACHE.get((edition, status, surah, ayah))
        if cached and (now - cached[0]) <= _MARK_AYAH_TTL_SEC:
            out.extend(dict(r) for r in cached[1])
        else:
            missing.append((surah, ayah))

    if not missing:
        return out

    # PostgREST or=(and(...),and(...)) — chunk to keep URLs sane.
    chunk_size = 40
    fresh: list[dict] = []
    for i in range(0, len(missing), chunk_size):
        chunk = missing[i:i + chunk_size]
        parts = [f'and(surah.eq.{s},ayah.eq.{a})' for s, a in chunk]
        params = {
            'edition': f'eq.{edition}',
            'status': f'eq.{status}',
            'or': f'({",".join(parts)})',
            'select': 'edition,surah,ayah,token_index,symbol,word_text,status',
        }
        fresh.extend(_request('GET', 'editor_marks', params=params) or [])

    by_ayah: dict[tuple[int, int], list[dict]] = {key: [] for key in missing}
    for row in fresh:
        key = (int(row['surah']), int(row['ayah']))
        if key in by_ayah:
            by_ayah[key].append(row)
    now = time.monotonic()
    for key, rows in by_ayah.items():
        surah, ayah = key
        _MARK_AYAH_CACHE[(edition, status, surah, ayah)] = (now, [dict(r) for r in rows])
        out.extend(dict(r) for r in rows)
    return out


# Short-lived ayah mark cache — spread navigation re-hits the same verses.
_MARK_AYAH_CACHE: dict[tuple[str, str, int, int], tuple[float, list[dict]]] = {}
_MARK_AYAH_TTL_SEC = 45.0
# Draft lists are small; cache whole-edition draft scans for the pending panel.
_DRAFT_LIST_CACHE: dict[str, tuple[float, list[dict]]] = {}
_DRAFT_LIST_TTL_SEC = 20.0
# Corrected Layout Studio pages are small (15 rows each). Cache the complete
# edition briefly so page navigation does not make one Supabase request per
# click while still letting another editor's changes appear quickly.
_LAYOUT_PAGE_CACHE: dict[str, tuple[float, list[dict]]] = {}
_LAYOUT_PAGE_TTL_SEC = 5.0
_LAYOUT_INDEX_CACHE: dict[str, tuple[float, list[dict]]] = {}
_LAYOUT_PROFILE_CACHE: dict[str, tuple[float, dict | None]] = {}


def invalidate_mark_cache(*, edition: str | None = None, surah: int | None = None,
                          ayah: int | None = None) -> None:
    if edition is None and surah is None and ayah is None:
        _MARK_AYAH_CACHE.clear()
        _DRAFT_LIST_CACHE.clear()
        return
    if edition is not None and surah is None and ayah is None:
        _DRAFT_LIST_CACHE.pop(edition, None)
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
    if edition is not None:
        _DRAFT_LIST_CACHE.pop(edition, None)


def fetch_layout_pages(*, edition: str, force: bool = False) -> list[dict]:
    """Return all cloud overrides for one Layout Studio edition."""
    cached = _LAYOUT_PAGE_CACHE.get(edition)
    if (
        not force
        and cached
        and (time.monotonic() - cached[0]) <= _LAYOUT_PAGE_TTL_SEC
    ):
        return [dict(row) for row in cached[1]]

    rows = _request(
        'GET', 'editor_layout_pages',
        params={
            'edition': f'eq.{edition}',
            'select': 'edition,page_number,lines,updated_at,updated_by',
            'order': 'page_number',
        },
    ) or []
    _LAYOUT_PAGE_CACHE[edition] = (
        time.monotonic(), [dict(row) for row in rows],
    )
    return [dict(row) for row in rows]


def fetch_layout_page_index(*, edition: str, force: bool = False) -> list[dict]:
    """Fetch lightweight page revision metadata for cloud change detection."""
    cached = _LAYOUT_INDEX_CACHE.get(edition)
    if (
        not force
        and cached
        and (time.monotonic() - cached[0]) <= _LAYOUT_PAGE_TTL_SEC
    ):
        return [dict(row) for row in cached[1]]
    rows = _request(
        'GET', 'editor_layout_pages',
        params={
            'edition': f'eq.{edition}',
            'select': 'page_number,updated_at',
            'order': 'page_number',
        },
    ) or []
    _LAYOUT_INDEX_CACHE[edition] = (
        time.monotonic(), [dict(row) for row in rows],
    )
    return [dict(row) for row in rows]


def upsert_layout_pages(
    *,
    edition: str,
    pages: list[dict],
    updated_by: str | None,
) -> list[dict]:
    """Atomically persist every page touched by one layout operation."""
    if not pages:
        return []
    now = _now_iso()
    payload = [
        {
            'edition': edition,
            'page_number': int(page['page_number']),
            'lines': list(page.get('lines') or []),
            'updated_by': updated_by,
            'updated_at': now,
        }
        for page in pages
    ]
    rows = _request(
        'POST', 'editor_layout_pages',
        params={'on_conflict': 'edition,page_number'},
        json_body=payload,
        prefer='resolution=merge-duplicates,return=representation',
    ) or payload

    # Keep the local read-through cache coherent. Otherwise the response page
    # builder could immediately reapply the five-second-old cloud snapshot and
    # visually undo the edit that was just saved.
    existing = {
        int(row['page_number']): dict(row)
        for row in (_LAYOUT_PAGE_CACHE.get(edition) or (0, []))[1]
    }
    for row in rows:
        existing[int(row['page_number'])] = dict(row)
    _LAYOUT_PAGE_CACHE[edition] = (
        time.monotonic(),
        [existing[key] for key in sorted(existing)],
    )
    index = {
        int(row['page_number']): {
            'page_number': int(row['page_number']),
            'updated_at': row.get('updated_at') or now,
        }
        for row in (_LAYOUT_INDEX_CACHE.get(edition) or (0, []))[1]
    }
    for row in rows:
        page_number = int(row['page_number'])
        index[page_number] = {
            'page_number': page_number,
            'updated_at': row.get('updated_at') or now,
        }
    _LAYOUT_INDEX_CACHE[edition] = (
        time.monotonic(),
        [index[key] for key in sorted(index)],
    )
    return [dict(row) for row in rows]


def fetch_layout_profile(*, edition: str, force: bool = False) -> dict | None:
    cached = _LAYOUT_PROFILE_CACHE.get(edition)
    if (
        not force
        and cached
        and (time.monotonic() - cached[0]) <= _LAYOUT_PAGE_TTL_SEC
    ):
        return dict(cached[1]) if cached[1] else None
    rows = _request(
        'GET', 'editor_layout_profiles',
        params={
            'edition': f'eq.{edition}',
            'select': 'edition,profile,updated_at,updated_by',
            'limit': '1',
        },
    ) or []
    row = dict(rows[0]) if rows else None
    _LAYOUT_PROFILE_CACHE[edition] = (
        time.monotonic(), dict(row) if row else None,
    )
    return row


def upsert_layout_profile(
    *,
    edition: str,
    profile: dict,
    updated_by: str | None,
) -> dict:
    payload = {
        'edition': edition,
        'profile': dict(profile),
        'updated_by': updated_by,
        'updated_at': _now_iso(),
    }
    rows = _request(
        'POST', 'editor_layout_profiles',
        params={'on_conflict': 'edition'},
        json_body=payload,
        prefer='resolution=merge-duplicates,return=representation',
    )
    row = dict((rows or [payload])[0])
    _LAYOUT_PROFILE_CACHE[edition] = (time.monotonic(), dict(row))
    return row


def invalidate_layout_cache(edition: str | None = None) -> None:
    if edition is None:
        _LAYOUT_PAGE_CACHE.clear()
        _LAYOUT_INDEX_CACHE.clear()
        _LAYOUT_PROFILE_CACHE.clear()
        return
    _LAYOUT_PAGE_CACHE.pop(edition, None)
    _LAYOUT_INDEX_CACHE.pop(edition, None)
    _LAYOUT_PROFILE_CACHE.pop(edition, None)


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


def list_mark_review_decisions(edition: str) -> list[dict]:
    rows = _request(
        'GET', 'waqf_mark_review_decisions',
        params={
            'edition': f'eq.{edition}',
            'select': 'edition,page_number,word_id,decision,our_mark,correct_mark,surah,ayah,word_text,updated_at',
            'order': 'page_number,word_id',
        },
    ) or []
    return rows


def upsert_mark_review_decision(*, edition: str, page_number: int, word_id: int,
                                decision: str, our_mark: str | None = None,
                                correct_mark: str | None = None,
                                surah: int | None = None, ayah: int | None = None,
                                word_text: str | None = None,
                                updated_by: str | None = None) -> None:
    _request(
        'POST', 'waqf_mark_review_decisions',
        params={'on_conflict': 'edition,page_number,word_id'},
        json_body={
            'edition': edition,
            'page_number': page_number,
            'word_id': word_id,
            'decision': decision,
            'our_mark': our_mark or '',
            'correct_mark': correct_mark if correct_mark is not None else '',
            'surah': surah,
            'ayah': ayah,
            'word_text': word_text or '',
            'updated_by': updated_by,
            'updated_at': _now_iso(),
        },
        prefer='resolution=merge-duplicates,return=minimal',
    )


def delete_mark_review_decision(*, edition: str, page_number: int, word_id: int) -> None:
    _request(
        'DELETE', 'waqf_mark_review_decisions',
        params={
            'edition': f'eq.{edition}',
            'page_number': f'eq.{page_number}',
            'word_id': f'eq.{word_id}',
        },
        prefer='return=minimal',
    )


def list_mark_review_notes(edition: str) -> list[dict]:
    rows = _request(
        'GET', 'waqf_mark_review_notes',
        params={
            'edition': f'eq.{edition}',
            'select': 'id,edition,page_number,note,updated_at',
            'order': 'page_number,updated_at',
        },
    ) or []
    return rows


def add_mark_review_note(*, edition: str, page_number: int, note: str,
                         updated_by: str | None = None) -> dict:
    rows = _request(
        'POST', 'waqf_mark_review_notes',
        json_body={
            'edition': edition,
            'page_number': page_number,
            'note': note,
            'updated_by': updated_by,
            'updated_at': _now_iso(),
        },
        prefer='return=representation',
    )
    if isinstance(rows, list) and rows:
        return rows[0]
    return rows or {}


def append_audit(**fields: Any) -> None:
    body = {k: v for k, v in fields.items() if v is not None}
    try:
        _request('POST', 'editor_audit', json_body=body, prefer='return=minimal')
    except SupabaseEditorError as e:
        logger.warning('editor_audit write failed: %s', e)


AUDIT_ACTIONS = frozenset({
    'set_mark', 'clear_mark', 'review_page', 'publish', 'login',
    'invite_create', 'invite_revoke',
    'layout_save', 'layout_profile', 'layout_undo',
    'mark_review_decision', 'mark_review_note', 'mark_review_page',
    'progress',
})

_AUDIT_SELECT = (
    'id,at,actor_id,actor_name,action,edition,surah,ayah,token_index,'
    'word_id,page_number,old_symbol,new_symbol,meta'
)


def recent_audit(*, edition: str | None = None, limit: int = 30) -> list[dict]:
    return list_audit(edition=edition, limit=limit)


def list_audit_page(
    *,
    edition: str | None = None,
    actor_id: str | None = None,
    action: str | None = None,
    since: str | None = None,
    until: str | None = None,
    q: str | None = None,
    before_at: str | None = None,
    before_id: int | None = None,
    limit: int = 50,
) -> tuple[list[dict], dict[str, Any] | None]:
    """Filtered activity feed (newest first). Cursor = (before_at, before_id)."""
    limit = max(1, min(int(limit), 100))
    needle = (q or '').strip().lower()
    # Text search is intentionally local because useful fields are spread
    # across columns and JSON metadata. Scan a bounded window and return a
    # cursor even when that window has no matches, so older rows stay reachable.
    scan_limit = 200 if needle else limit
    params: dict[str, str] = {
        'select': _AUDIT_SELECT,
        'order': 'at.desc,id.desc',
        'limit': str(scan_limit + 1),
    }
    if edition:
        params['edition'] = f'eq.{edition}'
    if actor_id:
        params['actor_id'] = f'eq.{actor_id}'
    if action:
        params['action'] = f'eq.{action}'
    if since and until:
        params['and'] = f'(at.gte.{since},at.lte.{until})'
    elif since:
        params['at'] = f'gte.{since}'
    elif until:
        params['at'] = f'lte.{until}'
    if before_at is not None and before_id is not None:
        bid = int(before_id)
        params['or'] = (
            f'(at.lt.{before_at},'
            f'and(at.eq.{before_at},id.lt.{bid}))'
        )

    rows = _request('GET', 'editor_audit', params=params) or []
    has_extra = len(rows) > scan_limit
    scanned = rows[:scan_limit]
    out: list[dict] = []
    next_row = None
    for index, row in enumerate(scanned):
        if needle:
            meta = row.get('meta')
            meta_blob = ''
            if isinstance(meta, dict):
                meta_blob = ' '.join(
                    str(meta.get(k) or '')
                    for k in (
                        'change_summary', 'op', 'decision', 'word_text', 'note',
                        'first_key', 'last_key',
                    )
                )
            elif meta is not None:
                meta_blob = str(meta)
            blob = ' '.join([
                str(row.get('actor_name') or ''),
                str(row.get('edition') or ''),
                str(row.get('action') or ''),
                str(row.get('page_number') or ''),
                f"{row.get('surah') or ''}:{row.get('ayah') or ''}",
                str(row.get('old_symbol') or ''),
                str(row.get('new_symbol') or ''),
                meta_blob,
            ]).lower()
            if needle not in blob:
                continue
        out.append(row)
        if len(out) >= limit:
            if index < len(scanned) - 1 or has_extra:
                next_row = row
            break
    else:
        if has_extra and scanned:
            next_row = scanned[-1]

    next_cursor = None
    if next_row and next_row.get('at') is not None and next_row.get('id') is not None:
        next_cursor = {
            'before_at': next_row['at'],
            'before_id': next_row['id'],
        }
    return out, next_cursor


def list_audit(
    *,
    edition: str | None = None,
    actor_id: str | None = None,
    action: str | None = None,
    since: str | None = None,
    until: str | None = None,
    q: str | None = None,
    before_at: str | None = None,
    before_id: int | None = None,
    limit: int = 50,
) -> list[dict]:
    items, _cursor = list_audit_page(
        edition=edition,
        actor_id=actor_id,
        action=action,
        since=since,
        until=until,
        q=q,
        before_at=before_at,
        before_id=before_id,
        limit=limit,
    )
    return items


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


def canonical_publish_snapshot(changes: list[dict]) -> list[dict]:
    """Return the stable, reviewer-visible fields checked by the publish RPC."""
    snapshot = []
    for change in changes:
        snapshot.append({
            'surah': int(change['surah']),
            'ayah': int(change['ayah']),
            'token_index': int(change['token_index']),
            'old_symbol': (change.get('old_symbol') or '').strip(),
            'new_symbol': (change.get('new_symbol') or '').strip(),
        })
    snapshot.sort(key=lambda c: (c['surah'], c['ayah'], c['token_index']))
    return snapshot


def publish_edition(
    edition: str,
    *,
    actor_id: str | None,
    actor_name: str | None,
    expected_changes: list[dict],
) -> int:
    """Atomically publish exactly the draft diff reviewed by an admin."""
    expected = canonical_publish_snapshot(expected_changes)
    try:
        result = _request(
            'POST',
            'rpc/publish_editor_edition',
            json_body={
                'p_edition': edition,
                'p_actor_id': actor_id,
                'p_actor_name': actor_name,
                'p_expected_changes': expected,
            },
        )
    except SupabaseEditorError as e:
        body = e.body if isinstance(e, SupabaseResponseError) else ''
        if 'publish snapshot changed' in body or '40001' in body:
            raise PublishConflict(
                'Drafts changed after review; refresh the pending list.'
            ) from e
        raise

    if not isinstance(result, dict) or 'published' not in result:
        raise SupabaseEditorError('Supabase publish RPC returned an invalid response')
    invalidate_mark_cache(edition=edition)
    return int(result['published'])
