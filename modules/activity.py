"""Editor activity log — browse who changed what across cloud tools."""
from __future__ import annotations

import logging

from flask import jsonify, render_template, request

from core.blueprints import editor_bp
from core.loader import IS_SERVERLESS as _IS_SERVERLESS
from core import supabase_editor as sb
from modules.editor_auth import current_editor, require_editor

logger = logging.getLogger(__name__)

ACTION_LABELS_AR = {
    'set_mark': 'تعيين علامة',
    'clear_mark': 'مسح علامة',
    'review_page': 'مراجعة صفحة',
    'publish': 'اعتماد ونشر',
    'login': 'دخول',
    'invite_create': 'إنشاء حساب',
    'invite_revoke': 'إلغاء حساب',
    'layout_save': 'حفظ تخطيط',
    'layout_profile': 'إعدادات تخطيط',
    'layout_undo': 'تراجع تخطيط',
    'mark_review_decision': 'قرار مراجعة علامة',
    'mark_review_note': 'ملاحظة ناقص',
    'mark_review_page': 'إنهاء صفحة مراجعة',
    'progress': 'تقدّم مراجعة',
}


@editor_bp.route('/activity')
def activity_page():
    return render_template(
        'activity.html',
        enable_vercel_analytics=_IS_SERVERLESS,
        actions=[
            {'id': key, 'label': label}
            for key, label in ACTION_LABELS_AR.items()
        ],
        cloud=sb.is_configured(),
    )


@editor_bp.route('/api/activity', methods=['GET'])
@require_editor
def activity_feed():
    """Paginated cloud audit feed for the activity page."""
    if not sb.is_configured():
        return jsonify({
            'items': [],
            'cloud': False,
            'next_cursor': None,
            'actions': ACTION_LABELS_AR,
        })

    edition = (request.args.get('edition') or '').strip() or None
    actor_id = (request.args.get('actor_id') or '').strip() or None
    action = (request.args.get('action') or '').strip() or None
    since = (request.args.get('since') or '').strip() or None
    until = (request.args.get('until') or '').strip() or None
    q = (request.args.get('q') or '').strip() or None
    before_at = (request.args.get('before_at') or '').strip() or None
    before_id_raw = request.args.get('before_id')
    try:
        limit = int(request.args.get('limit') or 50)
    except (TypeError, ValueError):
        return jsonify({'error': 'invalid limit'}), 400
    before_id = None
    if before_id_raw not in (None, ''):
        try:
            before_id = int(before_id_raw)
        except (TypeError, ValueError):
            return jsonify({'error': 'invalid before_id'}), 400
    if (before_at is None) != (before_id is None):
        return jsonify({'error': 'incomplete cursor'}), 400
    if action and action not in sb.AUDIT_ACTIONS:
        return jsonify({'error': 'invalid action'}), 400

    try:
        items, next_cursor = sb.list_audit_page(
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
    except sb.SupabaseEditorError as exc:
        logger.error('activity feed failed: %s', exc)
        return jsonify({'error': 'audit unavailable'}), 503

    user = current_editor()
    actors = []
    try:
        for inv in sb.list_invites():
            if not inv.get('active', True):
                continue
            actors.append({
                'id': inv.get('id'),
                'name': inv.get('display_name') or inv.get('username') or inv.get('id'),
            })
    except sb.SupabaseEditorError as exc:
        logger.warning('activity actors list failed: %s', exc)

    return jsonify({
        'items': items,
        'cloud': True,
        'next_cursor': next_cursor,
        'actions': ACTION_LABELS_AR,
        'actors': actors,
        'user': user,
    })
