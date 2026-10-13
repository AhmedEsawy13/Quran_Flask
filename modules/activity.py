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


# ── Per-editor dashboard ─────────────────────────────────────────────

# What a reviewer «did» — logins and progress ticks are counted but not headline work.
_WORK_GROUPS = {
    'marks': ('set_mark', 'clear_mark'),
    'decisions': ('mark_review_decision', 'mark_review_note'),
    'layout': ('layout_save', 'layout_profile', 'layout_undo'),
    'pages': ('review_page', 'mark_review_page', 'progress'),
    'publish': ('publish',),
}
SUMMARY_PERIODS = {7, 30, 90, 0}   # days; 0 = all time


def summarize_activity(rows: list[dict], invites: list[dict], *, days: int, today) -> dict:
    """Per-editor totals for the dashboard. ``today`` is a date (UTC).

    Every active invite gets a card, even with no activity, so a reviewer who
    has not started is visible too. The daily series covers the last
    min(days, 30) days (30 for all time).
    """
    from collections import Counter
    from datetime import timedelta

    span = min(days or 30, 30)
    day_keys = [(today - timedelta(days=i)).isoformat() for i in range(span - 1, -1, -1)]
    people: dict[str, dict] = {}

    def person(pid, name, role=None):
        if pid not in people:
            people[pid] = {'id': pid, 'name': name or 'غير معروف', 'role': role, 'total': 0,
                           'actions': Counter(), 'editions': Counter(), 'pages': set(),
                           'daily': Counter(), 'first_at': None, 'last_at': None}
        return people[pid]

    for inv in invites:
        if inv.get('active', True):
            person(inv.get('id'), inv.get('display_name') or inv.get('username'), inv.get('role'))
    for row in rows:
        pid = row.get('actor_id') or f"name:{row.get('actor_name') or ''}"
        p = person(pid, row.get('actor_name'))
        action = row.get('action') or ''
        at = str(row.get('at') or '')
        p['total'] += 1
        p['actions'][action] += 1
        if row.get('edition'):
            p['editions'][row['edition']] += 1
        if row.get('page_number') and action != 'login':
            p['pages'].add((row.get('edition') or '', row['page_number']))
        if at:
            p['daily'][at[:10]] += 1
            p['last_at'] = max(p['last_at'] or at, at)
            p['first_at'] = min(p['first_at'] or at, at)

    cards = []
    for p in people.values():
        work = {g: sum(p['actions'][a] for a in acts) for g, acts in _WORK_GROUPS.items()}
        cards.append({
            'id': p['id'], 'name': p['name'], 'role': p['role'], 'total': p['total'],
            'work': work, 'logins': p['actions']['login'],
            'actions': [{'id': a, 'label': ACTION_LABELS_AR.get(a, a), 'count': n}
                        for a, n in p['actions'].most_common()],
            'editions': [{'name': e, 'count': n} for e, n in p['editions'].most_common()],
            'pages_touched': len(p['pages']),
            'daily': [p['daily'].get(d, 0) for d in day_keys],
            'first_at': p['first_at'], 'last_at': p['last_at'],
        })
    cards.sort(key=lambda c: (c['total'] - c['logins'], c['last_at'] or ''), reverse=True)   # most work, then most recent
    team = {g: sum(c['work'][g] for c in cards) for g in _WORK_GROUPS}
    return {'days': days, 'day_keys': day_keys, 'people': cards, 'team': team,
            'total': sum(c['total'] for c in cards),
            'active': sum(1 for c in cards if c['total'] - c['logins'] > 0)}


@editor_bp.route('/api/activity/summary', methods=['GET'])
@require_editor
def activity_summary():
    """Per-editor dashboard: what each reviewer did over the last N days."""
    from datetime import datetime, timedelta, timezone

    try:
        days = int(request.args.get('days') or 30)
    except (TypeError, ValueError):
        return jsonify({'error': 'invalid days'}), 400
    if days not in SUMMARY_PERIODS:
        return jsonify({'error': 'invalid days'}), 400
    if not sb.is_configured():
        return jsonify({'cloud': False, 'days': days, 'people': [], 'team': {}, 'total': 0, 'active': 0})
    now = datetime.now(timezone.utc)
    since = (now - timedelta(days=days)).isoformat() if days else None
    try:
        rows = sb.audit_rows_since(since)
        invites = sb.list_invites()
    except sb.SupabaseEditorError as exc:
        logger.error('activity summary failed: %s', exc)
        return jsonify({'error': 'audit unavailable'}), 503
    return jsonify(dict(summarize_activity(rows, invites, days=days, today=now.date()), cloud=True))
