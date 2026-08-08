"""Username/password auth for /mushaf-editor (HttpOnly signed cookie)."""
from __future__ import annotations

import functools
import logging
import os
import secrets
import threading
import time
from typing import Callable

from flask import g, jsonify, request
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from core.blueprints import editor_bp
from core import supabase_editor as sb

logger = logging.getLogger(__name__)

COOKIE_NAME = 'ed_session'
SESSION_MAX_AGE = 7 * 24 * 3600  # 7 days
MIN_SESSION_SECRET_LENGTH = 32
_LOCAL_DEV_SECRET = 'dev-editor-secret'
_INVITE_CACHE_TTL = 15.0
_invite_cache: dict[str, tuple[float, dict | None]] = {}
_invite_cache_lock = threading.RLock()


def invalidate_editor_session_cache(invite_id: str | None = None) -> None:
    """Drop cached invite state after revocation/reactivation or in tests."""
    with _invite_cache_lock:
        if invite_id is None:
            _invite_cache.clear()
        else:
            _invite_cache.pop(invite_id, None)


def _active_invite(invite_id: str) -> dict | None:
    now = time.monotonic()
    with _invite_cache_lock:
        cached = _invite_cache.get(invite_id)
        if cached and (now - cached[0]) <= _INVITE_CACHE_TTL:
            return dict(cached[1]) if cached[1] else None
    invite = sb.find_active_invite_by_id(invite_id)
    with _invite_cache_lock:
        _invite_cache[invite_id] = (now, dict(invite) if invite else None)
    return invite


def editor_session_secret_configured() -> bool:
    """Cloud sessions require a dedicated, non-default signing secret."""
    if not sb.is_configured():
        return True
    secret = (os.environ.get('EDITOR_SESSION_SECRET') or '').strip()
    return len(secret) >= MIN_SESSION_SECRET_LENGTH and secret != _LOCAL_DEV_SECRET


def _serializer() -> URLSafeTimedSerializer:
    if sb.is_configured():
        secret = (os.environ.get('EDITOR_SESSION_SECRET') or '').strip()
        if not editor_session_secret_configured():
            raise RuntimeError('cloud editor session secret is not configured')
    else:
        secret = (
            os.environ.get('EDITOR_SESSION_SECRET')
            or os.environ.get('SECRET_KEY')
            or _LOCAL_DEV_SECRET
        ).strip()
    return URLSafeTimedSerializer(secret, salt='athar-mushaf-editor')


def issue_session_cookie(response, invite: dict):
    token = _serializer().dumps({
        'id': invite['id'],
        'name': invite['display_name'],
        'role': invite['role'],
    })
    secure = request.is_secure or os.environ.get('FLASK_ENV') == 'production'
    response.set_cookie(
        COOKIE_NAME, token,
        max_age=SESSION_MAX_AGE,
        httponly=True,
        samesite='Lax',
        secure=secure,
        path='/',
    )
    return response


def clear_session_cookie(response):
    response.delete_cookie(COOKIE_NAME, path='/')
    return response


def current_editor() -> dict | None:
    if hasattr(g, '_editor_user'):
        return g._editor_user
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        g._editor_user = None
        return None
    try:
        data = _serializer().loads(token, max_age=SESSION_MAX_AGE)
    except RuntimeError:
        logger.error('cloud editor auth disabled: EDITOR_SESSION_SECRET is missing or weak')
        g._editor_auth_unavailable = True
        g._editor_user = None
        return None
    except (BadSignature, SignatureExpired):
        g._editor_user = None
        return None
    if not isinstance(data, dict) or not data.get('id'):
        g._editor_user = None
        return None
    if sb.is_configured():
        try:
            invite = _active_invite(str(data['id']))
        except sb.SupabaseEditorError as e:
            logger.error('session invite validation failed: %s', e)
            g._editor_auth_unavailable = True
            g._editor_user = None
            return None
        if not invite:
            g._editor_user = None
            return None
        data = {
            'id': invite['id'],
            'name': invite.get('display_name') or '',
            'role': invite.get('role') or 'editor',
        }
    g._editor_user = {
        'id': data['id'],
        'name': data.get('name') or '',
        'role': data.get('role') or 'editor',
    }
    return g._editor_user


def require_editor(view: Callable):
    """Require invite session when Supabase is configured; otherwise allow (local SQLite)."""
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if not sb.is_configured():
            return view(*args, **kwargs)
        if not editor_session_secret_configured():
            return jsonify({'error': 'auth service unavailable'}), 503
        user = current_editor()
        if getattr(g, '_editor_auth_unavailable', False):
            return jsonify({'error': 'auth service unavailable'}), 503
        if not user:
            return jsonify({'error': 'login required', 'login_required': True}), 401
        return view(*args, **kwargs)
    wrapped._athar_auth_policy = 'editor'  # type: ignore[attr-defined]
    return wrapped


def require_admin(view: Callable):
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if not sb.is_configured():
            return jsonify({'error': 'cloud editor not configured'}), 503
        if not editor_session_secret_configured():
            return jsonify({'error': 'auth service unavailable'}), 503
        user = current_editor()
        if getattr(g, '_editor_auth_unavailable', False):
            return jsonify({'error': 'auth service unavailable'}), 503
        if not user:
            return jsonify({'error': 'login required', 'login_required': True}), 401
        if user.get('role') != 'admin':
            return jsonify({'error': 'admin required'}), 403
        return view(*args, **kwargs)
    wrapped._athar_auth_policy = 'admin'  # type: ignore[attr-defined]
    return wrapped


@editor_bp.route('/api/mushaf-editor/auth/status', methods=['GET'])
def editor_auth_status():
    configured = sb.is_configured()
    auth_available = editor_session_secret_configured()
    if configured and not auth_available:
        return jsonify({
            'cloud': True,
            'authenticated': False,
            'user': None,
            'login_required': True,
            'auth_available': False,
            'error': 'auth service unavailable',
        }), 503
    user = current_editor() if configured else None
    return jsonify({
        'cloud': configured,
        'authenticated': bool(user) or not configured,
        'user': user,
        'login_required': configured and not user,
        'auth_available': auth_available,
    })


@editor_bp.route('/api/mushaf-editor/login', methods=['POST'])
def editor_login():
    if not sb.is_configured():
        return jsonify({'error': 'cloud editor not configured'}), 503
    if not editor_session_secret_configured():
        logger.error('cloud editor login disabled: EDITOR_SESSION_SECRET is missing or weak')
        return jsonify({'error': 'auth service unavailable'}), 503
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({'error': 'JSON object required'}), 400
    username = (data.get('username') or '').strip()
    password = data.get('password') or ''
    if not username or not password:
        return jsonify({'error': 'username and password required'}), 400
    try:
        invite = sb.find_invite_by_username(username)
    except sb.SupabaseEditorError as e:
        logger.error('login lookup failed: %s', e)
        return jsonify({'error': 'auth service unavailable'}), 503
    if not invite or not sb.verify_password(invite.get('password_hash'), password):
        return jsonify({'error': 'invalid credentials'}), 401
    try:
        sb.touch_invite(invite['id'])
        sb.append_audit(
            actor_id=invite['id'],
            actor_name=invite['display_name'],
            action='login',
        )
    except sb.SupabaseEditorError as e:
        logger.warning('post-login bookkeeping failed: %s', e)
    resp = jsonify({
        'ok': True,
        'user': {
            'id': invite['id'],
            'name': invite['display_name'],
            'role': invite['role'],
        },
    })
    return issue_session_cookie(resp, invite)


@editor_bp.route('/api/mushaf-editor/logout', methods=['POST'])
def editor_logout():
    resp = jsonify({'ok': True})
    return clear_session_cookie(resp)


@editor_bp.route('/api/mushaf-editor/invites', methods=['GET', 'POST'])
@require_admin
def editor_invites():
    """List accounts or create one (admin only). Password returned once on create."""
    user = current_editor()
    if request.method == 'GET':
        try:
            rows = sb.list_invites()
        except sb.SupabaseEditorError as e:
            logger.error('list invites failed: %s', e)
            return jsonify({'error': 'invites unavailable'}), 503
        return jsonify({
            'invites': [
                {
                    'id': r.get('id'),
                    'name': r.get('display_name'),
                    'username': r.get('username') or '',
                    'role': r.get('role'),
                    'active': bool(r.get('active')),
                    'created_at': r.get('created_at'),
                    'last_used_at': r.get('last_used_at'),
                }
                for r in rows
            ],
        })

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({'error': 'JSON object required'}), 400
    name = (data.get('name') or data.get('display_name') or '').strip()
    if not name:
        return jsonify({'error': 'name required'}), 400
    role = (data.get('role') or 'editor').strip()
    if role not in ('editor', 'admin'):
        return jsonify({'error': 'invalid role'}), 400
    username = sb.validate_username(data.get('username') or '')
    if not username:
        return jsonify({
            'error': 'invalid username',
            'hint': '3–32 chars: letters, digits, . _ -',
        }), 400
    password = (data.get('password') or '').strip() or secrets.token_urlsafe(10)
    if not sb.validate_password(password):
        return jsonify({
            'error': 'password too short',
            'hint': f'min {sb.MIN_PASSWORD_LEN} chars',
        }), 400
    try:
        row = sb.insert_invite(
            display_name=name,
            role=role,
            username=username,
            password_hash=sb.hash_password(password),
        )
        sb.append_audit(
            actor_id=user['id'] if user else None,
            actor_name=user['name'] if user else None,
            action='invite_create',
            meta={
                'invite_id': row.get('id'),
                'name': name,
                'username': username,
                'role': role,
            },
        )
    except sb.SupabaseEditorError as e:
        logger.error('create invite failed: %s', e)
        msg = e.body if isinstance(e, sb.SupabaseResponseError) else str(e)
        if '23505' in msg or 'duplicate' in msg.lower():
            return jsonify({'error': 'username already used'}), 409
        return jsonify({'error': 'create invite failed'}), 503
    return jsonify({
        'ok': True,
        'invite': {
            'id': row.get('id'),
            'name': row.get('display_name') or name,
            'username': row.get('username') or username,
            'role': row.get('role') or role,
            'active': True,
        },
        'username': username,
        'password': password,  # plaintext once — store/share now
    }), 201


@editor_bp.route('/api/mushaf-editor/invites/<invite_id>', methods=['PATCH'])
@require_admin
def editor_invite_patch(invite_id):
    """Revoke, re-activate, or reset password for an account (admin only)."""
    user = current_editor()
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({'error': 'JSON object required'}), 400
    invite_id = (invite_id or '').strip()
    if not invite_id:
        return jsonify({'error': 'invalid id'}), 400

    has_active = 'active' in data
    password = (data.get('password') or '').strip() if 'password' in data else ''
    username_raw = (data.get('username') or '').strip() if 'username' in data else ''
    if not has_active and not password and not username_raw:
        return jsonify({'error': 'active, username, or password required'}), 400

    row = None
    try:
        if has_active:
            row = sb.set_invite_active(invite_id, bool(data.get('active')))
            if not row:
                return jsonify({'error': 'not found'}), 404
            invalidate_editor_session_cache(invite_id)
            sb.append_audit(
                actor_id=user['id'] if user else None,
                actor_name=user['name'] if user else None,
                action='invite_revoke' if not data.get('active') else 'invite_create',
                meta={
                    'invite_id': invite_id,
                    'active': bool(data.get('active')),
                    'name': row.get('display_name'),
                },
            )

        if password or username_raw:
            uname = None
            if username_raw:
                uname = sb.validate_username(username_raw)
                if not uname:
                    return jsonify({'error': 'invalid username'}), 400
            pwd_hash = None
            if password:
                if not sb.validate_password(password):
                    return jsonify({
                        'error': 'password too short',
                        'hint': f'min {sb.MIN_PASSWORD_LEN} chars',
                    }), 400
                pwd_hash = sb.hash_password(password)
            row = sb.set_invite_credentials(
                invite_id=invite_id,
                username=uname,
                password_hash=pwd_hash,
            )
            if not row:
                return jsonify({'error': 'not found'}), 404
            sb.append_audit(
                actor_id=user['id'] if user else None,
                actor_name=user['name'] if user else None,
                action='invite_create',
                meta={
                    'invite_id': invite_id,
                    'credentials_updated': True,
                    'username': uname,
                },
            )
    except sb.SupabaseEditorError as e:
        logger.error('patch invite failed: %s', e)
        msg = e.body if isinstance(e, sb.SupabaseResponseError) else str(e)
        if '23505' in msg or 'duplicate' in msg.lower():
            return jsonify({'error': 'username already used'}), 409
        return jsonify({'error': 'update failed'}), 503

    if not row:
        return jsonify({'error': 'not found'}), 404
    out = {
        'ok': True,
        'invite': {
            'id': row.get('id'),
            'name': row.get('display_name'),
            'username': row.get('username') or '',
            'role': row.get('role'),
            'active': bool(row.get('active')),
        },
    }
    if password:
        out['password'] = password
    return jsonify(out)
