"""Shamarly missed-sign review: the Mesaha review module serves a second card family with its own groups."""
from __future__ import annotations

import json

import pytest

from modules import mesaha_waqf_review as mw
from modules import waqf_mark_review as wmr

SET = 'shamarly-waqf-test'


def _card(cid, group, model, page=11, word=1282, key='2:74:32'):
    return {'id': cid, 'page': page, 'line': 14, 'word_index': word, 'key': key, 'text': 'w', 'group': group,
            'model': model, 'conf': None if group == 'A' else 0.97, 'hint': {}, 'suggest': ''}


@pytest.fixture
def review(monkeypatch, tmp_path):
    shamarly, mesaha = tmp_path / 'shamarly', tmp_path / 'mesaha'
    (shamarly / SET / 'cards').mkdir(parents=True)
    (mesaha / 'mesaha-waqf-x').mkdir(parents=True)
    (mesaha / 'mesaha-waqf-x' / 'data.json').write_text(json.dumps({'cards': []}))
    (shamarly / SET / 'cards' / '011-a1282.jpg').write_bytes(b'\xff\xd8jpeg')
    data = {'title': 'علامات الشمرلي الناقصة', 'decision_edition': 'الشمرلي · فحص', 'no_accept': True, 'pages': [11],
            'groups': {'A': {'name': 'أ', 'note': 'n'}, 'B': {'name': 'ب', 'note': 'n'}},
            'cards': [_card('011-a1282', 'A', 'ق'), _card('011-b1290-1', 'B', 'ج', word=1290, key='2:74:40')]}
    (shamarly / SET / 'data.json').write_text(json.dumps(data))
    monkeypatch.setattr(mw, 'SHAMARLY_WAQF_CARDS_DIR', str(shamarly))
    monkeypatch.setattr(mw, '_sets_root', lambda: mesaha)
    monkeypatch.setattr(mw.sb, 'is_configured', lambda: False)
    monkeypatch.setattr(wmr, 'MARK_REVIEW_STORE_DATABASE', str(tmp_path / 'store.db'))
    import modules.editor_auth as auth
    monkeypatch.setattr(auth, 'editor_session_secret_configured', lambda: True)
    monkeypatch.setattr(auth, 'current_editor', lambda: {'id': 'u1', 'name': 'r', 'role': 'editor'})
    monkeypatch.setattr(mw, 'current_editor', lambda: {'id': 'u1', 'name': 'r', 'role': 'editor'})
    return tmp_path


def _send(client, path, method='POST', **body):
    body.setdefault('set', SET)
    return getattr(client, method.lower())(f'/api/mushaf-editor/mesaha-waqf/{path}',
                                           data=json.dumps(body), content_type='application/json')


def test_families_list_their_own_sets(review):
    assert mw.available_sets('shamarly') == [SET]
    assert mw.available_sets() == ['mesaha-waqf-x']


def test_shamarly_set_carries_its_groups_and_saves_under_its_own_edition(client, review):
    data = client.get(f'/api/mushaf-editor/mesaha-waqf?set={SET}').get_json()
    assert data['title'] == 'علامات الشمرلي الناقصة' and set(data['groups']) == {'A', 'B'}
    assert [c['id'] for c in data['cards']] == ['011-a1282', '011-b1290-1']
    assert _send(client, 'decision', id='011-a1282', mark='ق').status_code == 200
    assert _send(client, 'decision', id='011-b1290-1', mark='').status_code == 200
    assert mw.load_decisions('الشمرلي · فحص')[(11, 1282)]['decision'] == 'ok'
    assert mw.load_decisions() == {}                        # nothing leaked into the Mesaha store
    assert _send(client, 'decision', id='011-a1282', mark='x').status_code == 400


def test_default_listing_by_family(client, review):
    data = client.get('/api/mushaf-editor/mesaha-waqf?family=shamarly').get_json()
    assert data['set'] == SET and data['sets'] == [SET]
    assert client.get('/api/mushaf-editor/mesaha-waqf').get_json()['set'] == 'mesaha-waqf-x'


def test_bulk_accept_is_off_for_shamarly(client, review):
    assert _send(client, 'accept', group='B').status_code == 400


def test_card_images_come_from_the_shamarly_folder(client, review):
    ok = client.get(f'/api/mushaf-editor/mesaha-waqf/card?set={SET}&f=011-a1282.jpg')
    assert ok.status_code == 200 and ok.data.startswith(b'\xff\xd8')
    assert client.get(f'/api/mushaf-editor/mesaha-waqf/card?set={SET}&f=..%2Fdata.json').status_code == 404
    assert client.get(f'/api/mushaf-editor/mesaha-waqf/card?set={SET}&f=data.json').status_code == 404


def test_both_pages_render(client, review):
    mes = client.get('/mushaf-editor/mesaha-waqf')
    sha = client.get('/mushaf-editor/shamarly-waqf')
    assert mes.status_code == sha.status_code == 200
    assert 'data-family="shamarly"' in sha.get_data(as_text=True) and 'data-family="mesaha"' in mes.get_data(as_text=True)


# --- applying the reviewed (أ) cards to the «الشمرلي» column ---

WORDS = ['كتب', 'قال', 'ربك', 'يوم', 'قوم', 'حمد']


@pytest.fixture
def column(monkeypatch, review):
    import sqlite3
    from pipeline import apply_shamarly_review as asr
    db = review / 'waqf.db'
    conn = sqlite3.connect(db)
    conn.execute('CREATE TABLE waqf ("السورة" INTEGER, "الآية" INTEGER, "الكلمة" TEXT, token_index INTEGER, '
                 'word_index INTEGER, "الشمرلي" TEXT, UNIQUE("السورة","الآية",token_index))')
    conn.executemany('INSERT INTO waqf VALUES (2, 74, ?, ?, ?, ?)', [('ربك', 3, 3, 'ج'), ('قوم', 5, 5, 'ص')])
    conn.commit(); conn.close()
    monkeypatch.setattr(mw, 'MUSHAF_WAQF_DATABASE', str(db))
    monkeypatch.setattr(asr, 'WORD_PROVIDER', lambda s, a: [{'word_id': i, 'text': t} for i, t in enumerate(WORDS)])
    cards = [_card('011-a3', 'A', 'ج', word=3, key='2:74:3'), _card('011-a5', 'A', 'ص', word=5, key='2:74:5'),
             _card('011-a6', 'A', 'ق', word=6, key='2:74:6'), _card('011-a2', 'A', 'م', word=2, key='2:74:2'),
             _card('011-b4', 'B', 'ج', word=4, key='2:74:4')]
    for c, w in zip(cards, ['ربك', 'قوم', 'حمد', 'قال', 'يوم']):
        c['text'] = w
    data = json.loads((review / 'shamarly' / SET / 'data.json').read_text())
    data['cards'] = cards
    (review / 'shamarly' / SET / 'data.json').write_text(json.dumps(data))
    return db


def _apply(client, **body):
    body.setdefault('set', SET)
    return client.post('/api/mushaf-editor/shamarly-waqf/apply', data=json.dumps(body), content_type='application/json')


def _decide(client, cid, mark):
    assert _send(client, 'decision', id=cid, mark=mark).status_code == 200


def _marks(db):
    import sqlite3
    return dict(sqlite3.connect(db).execute('SELECT token_index, "الشمرلي" FROM waqf').fetchall())


def test_plan_lists_only_real_column_changes(client, column):
    for cid, mark in (('011-a3', 'ج'), ('011-a5', ''), ('011-a6', 'ق'), ('011-b4', 'ص')):
        _decide(client, cid, mark)
    r = client.get(f'/api/mushaf-editor/shamarly-waqf/apply-plan?set={SET}').get_json()
    assert r['can_apply'] and r['plan']['valid']
    got = [(c['token_index'], c['old_symbol'], c['new_symbol']) for c in r['plan']['changes']]
    assert got == [(4, 'ص', ''), (5, '', 'ق')]                 # token = word position - 1; ج was confirmed as is
    s = r['plan']['summary']['الشمرلي']
    assert (s['decided_a'], s['unchanged'], s['undecided_a'], s['b_verdicts']) == (3, 1, 1, 1)


def test_apply_changes_the_column_once_and_refuses_a_stale_plan(client, column):
    for cid, mark in (('011-a5', ''), ('011-a6', 'ق')):
        _decide(client, cid, mark)
    plan = client.get(f'/api/mushaf-editor/shamarly-waqf/apply-plan?set={SET}').get_json()['plan']
    assert _apply(client, plan_digest='nope').status_code == 409
    assert _marks(column) == {3: 'ج', 5: 'ص'}
    ok = _apply(client, plan_digest=plan['plan_digest'])
    assert ok.status_code == 200, ok.get_json()
    assert ok.get_json()['applied'] == 2 and ok.get_json()['backup']
    assert _marks(column)[3] == 'ج' and _marks(column)[5] is None and _marks(column)[6] == 'ق'
    again = client.get(f'/api/mushaf-editor/shamarly-waqf/apply-plan?set={SET}').get_json()['plan']
    assert again['changes'] == []


def test_apply_needs_a_writable_column_and_an_admin_when_cloud(client, column, monkeypatch):
    import os
    monkeypatch.setattr(os, 'access', lambda *a, **k: False)
    r = client.get(f'/api/mushaf-editor/shamarly-waqf/apply-plan?set={SET}').get_json()
    assert r['can_apply'] is False and 'read-only' in r['reason']
    assert _apply(client, plan_digest=r['plan']['plan_digest']).status_code == 403
    monkeypatch.undo()
    monkeypatch.setattr(mw.sb, 'is_configured', lambda: True)
    monkeypatch.setattr(mw, 'current_editor', lambda: {'id': 'u1', 'name': 'r', 'role': 'editor'})
    assert mw._apply_gate({'set': SET}) == (False, 'admin required')
