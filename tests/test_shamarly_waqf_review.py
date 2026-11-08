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
