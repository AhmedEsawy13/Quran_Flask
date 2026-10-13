"""Per-editor dashboard on /activity: who did what, from the audit log."""
from __future__ import annotations

from datetime import date

from modules import activity

TODAY = date(2026, 10, 13)
INVITES = [
    {'id': 'u1', 'display_name': 'أحمد', 'role': 'admin', 'active': True},
    {'id': 'u2', 'display_name': 'سارة', 'role': 'editor', 'active': True},
    {'id': 'u3', 'display_name': 'قديم', 'role': 'editor', 'active': False},
]


def _row(actor, action, at='2026-10-12T10:00:00+00:00', edition='البحرين', page=12, name=None):
    return {'actor_id': actor, 'actor_name': name or actor, 'action': action, 'at': at,
            'edition': edition, 'page_number': page}


def test_summary_counts_work_per_editor():
    rows = [_row('u1', 'set_mark'), _row('u1', 'clear_mark', page=13), _row('u1', 'login', page=None),
            _row('u1', 'mark_review_decision', edition='قطر', at='2026-10-13T08:00:00+00:00'),
            _row('u1', 'publish', page=None)]
    out = activity.summarize_activity(rows, INVITES, days=30, today=TODAY)
    ahmad = next(p for p in out['people'] if p['id'] == 'u1')
    assert ahmad['total'] == 5 and ahmad['logins'] == 1
    assert ahmad['work'] == {'marks': 2, 'decisions': 1, 'layout': 0, 'pages': 0, 'publish': 1}
    assert ahmad['pages_touched'] == 3          # (البحرين,12) (البحرين,13) (قطر,12); logins/publish carry no page
    assert ahmad['last_at'].startswith('2026-10-13')
    assert ahmad['daily'][-1] == 1 and ahmad['daily'][-2] == 4 and len(ahmad['daily']) == 30
    assert [e['name'] for e in ahmad['editions']] == ['البحرين', 'قطر']


def test_idle_invites_are_listed_and_inactive_ones_are_not():
    out = activity.summarize_activity([_row('u1', 'set_mark')], INVITES, days=7, today=TODAY)
    ids = [p['id'] for p in out['people']]
    assert ids == ['u1', 'u2']                   # most work first; u3 is deactivated
    assert out['active'] == 1 and len(out['people'][1]['daily']) == 7


def test_rows_without_an_invite_still_count():
    out = activity.summarize_activity([_row(None, 'layout_save', name='ضيف')], [], days=0, today=TODAY)
    [p] = out['people']
    assert (p['name'], p['work']['layout'], len(p['daily'])) == ('ضيف', 1, 30)


def test_summary_api(client, monkeypatch):
    import modules.editor_auth as auth
    monkeypatch.setattr(activity.sb, 'is_configured', lambda: True)
    monkeypatch.setattr(auth, 'editor_session_secret_configured', lambda: True)
    monkeypatch.setattr(auth, 'current_editor', lambda: {'id': 'u1', 'name': 'أحمد', 'role': 'admin'})
    seen = []
    monkeypatch.setattr(activity.sb, 'audit_rows_since', lambda since: seen.append(since) or [_row('u1', 'set_mark')])
    monkeypatch.setattr(activity.sb, 'list_invites', lambda: INVITES)
    r = client.get('/api/activity/summary?days=7')
    assert r.status_code == 200
    body = r.get_json()
    assert body['cloud'] is True and body['people'][0]['name'] == 'أحمد'
    assert client.get('/api/activity/summary?days=5').status_code == 400
    assert client.get('/api/activity/summary?days=0').status_code == 200
    assert seen[0] is not None                                                  # 7 days: a lower bound
    assert seen[-1] is None                                                     # «الكل»: no lower bound


def test_summary_needs_sign_in(client, monkeypatch):
    import modules.editor_auth as auth
    monkeypatch.setattr(activity.sb, 'is_configured', lambda: True)
    monkeypatch.setattr(auth, 'editor_session_secret_configured', lambda: True)
    monkeypatch.setattr(auth, 'current_editor', lambda: None)
    assert client.get('/api/activity/summary').status_code == 401
