"""Invite-code auth for /mushaf-editor (HttpOnly signed cookie)."""
from __future__ import annotations

import functools
import logging
import os
from typing import Callable

from flask import g, jsonify, request
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from core.blueprints import editor_bp
from core import supabase_editor as sb

logger = logging.getLogger(__name__)

COOKIE_NAME = 'ed_session'
SESSION_MAX_AGE = 7 * 24 * 3600  # 7 days


def _serializer() -> URLSafeTimedSerializer:
    secret = (
        os.environ.get('EDITOR_SESSION_SECRET')
        or os.environ.get('SECRET_KEY')
        or 'dev-editor-secret'
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
    except (BadSignature, SignatureExpired):
        g._editor_user = None
        return None
    if not isinstance(data, dict) or not data.get('id'):
        g._editor_user = None
        return None
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
        user = current_editor()
        if not user:
            return jsonify({'error': 'login required', 'login_required': True}), 401
        return view(*args, **kwargs)
    return wrapped


def require_admin(view: Callable):
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if not sb.is_configured():
            return jsonify({'error': 'cloud editor not configured'}), 503
        user = current_editor()
        if not user:
            return jsonify({'error': 'login required', 'login_required': True}), 401
        if user.get('role') != 'admin':
            return jsonify({'error': 'admin required'}), 403
        return view(*args, **kwargs)
    return wrapped


@editor_bp.route('/api/mushaf-editor/auth/status', methods=['GET'])
def editor_auth_status():
    configured = sb.is_configured()
    user = current_editor() if configured else None
    return jsonify({
        'cloud': configured,
        'authenticated': bool(user) or not configured,
        'user': user,
        'login_required': configured and not user,
    })


@editor_bp.route('/api/mushaf-editor/login', methods=['POST'])
def editor_login():
    if not sb.is_configured():
        return jsonify({'error': 'cloud editor not configured'}), 503
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({'error': 'JSON object required'}), 400
    code = (data.get('code') or '').strip()
    if not code:
        return jsonify({'error': 'code required'}), 400
    try:
        invite = sb.find_invite_by_code(code)
    except sb.SupabaseEditorError as e:
        logger.error('login lookup failed: %s', e)
        return jsonify({'error': 'auth service unavailable'}), 503
    if not invite:
        return jsonify({'error': 'invalid code'}), 401
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
