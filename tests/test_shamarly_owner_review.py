"""Shamarly word-ownership review: verdicts go to the shared review table (local store here) as JSON."""
from __future__ import annotations

import json

import pytest

from modules import shamarly_owner_review as so

SET = 'shamarly-owner-test'


@pytest.fixture
def review(monkeypatch, tmp_path):
    cards = [{'id': '259-42645', 'run_id': 'batch-rest', 'page': 259, 'line': 3, 'word_index': 42645,
              'text': 'لُّدّٗا', 'prev': 'قَوۡمٗا', 'next': '', 'owners': {'L3:C1': 42645}, 'owners_digest': 'abc'},
             {'id': '391-64436', 'run_id': 'batch-rest', 'page': 391, 'line': 1, 'word_index': 64436,
              'text': 'كَرَّةٗ', 'prev': 'لِي', 'next': 'فَأَكُونَ', 'owners': {}, 'owners_digest': 'def'}]
    (tmp_path / SET / 'cards').mkdir(parents=True)
    (tmp_path / SET / 'cards' / '259-42645.jpg').write_bytes(b'\xff\xd8jpg')
    (tmp_path / SET / 'data.json').write_text(json.dumps({'set': SET, 'cards': cards}), encoding='utf-8')
    monkeypatch.setattr(so, '_root', lambda: tmp_path)
    monkeypatch.setattr(so, '_store', lambda: str(tmp_path / 'store' / 'owner.db'))
    monkeypatch.setattr(so.sb, 'is_configured', lambda: False)
    import modules.editor_auth as auth
    monkeypatch.setattr(auth, 'editor_session_secret_configured', lambda: True)
    monkeypatch.setattr(auth, 'current_editor', lambda: {'id': 'u1', 'name': 'r', 'role': 'editor'})
    monkeypatch.setattr(so, 'current_editor', lambda: {'id': 'u1', 'name': 'r', 'role': 'editor'})
    return tmp_path


def _send(client, method='POST', **body):
    body.setdefault('set', SET)
    return getattr(client, method.lower())('/api/mushaf-editor/shamarly-owner/decision',
                                           data=json.dumps(body), content_type='application/json')


def _cards(client):
    data = client.get(f'/api/mushaf-editor/shamarly-owner?set={SET}').get_json()
    return {c['id']: c for c in data['cards']}


def test_list_hides_owners_and_serves_images(client, review):
    cards = _cards(client)
    assert set(cards) == {'259-42645', '391-64436'}
    assert 'owners' not in cards['259-42645'] and cards['259-42645']['decision'] is None
    assert client.get(f'/api/mushaf-editor/shamarly-owner/card?set={SET}&f=259-42645.jpg').status_code == 200
    assert client.get('/api/mushaf-editor/shamarly-owner/card?set=../x&f=a.jpg').status_code == 404


def test_verdict_round_trip(client, review):
    r = _send(client, id='259-42645', verdict='wrong', reasons=['missing_mark', 'bogus'], note=' shadda ')
    assert r.status_code == 200
    d = _cards(client)['259-42645']['decision']
    assert (d['verdict'], d['reasons'], d['note'], d['stale']) == ('wrong', ['missing_mark'], 'shadda', False)
    [row] = so.load_decisions().values()
    assert (row['edition'], row['page_number'], row['word_id'], row['decision'], row['our_mark']) == \
        (so.EDITION, 259, 42645, 'wrong', 'abc')
    assert json.loads(row['correct_mark'])['set'] == SET and row['updated_by'] == 'u1'

    _send(client, id='391-64436', verdict='prev')
    assert _cards(client)['391-64436']['decision']['reasons'] == []    # reasons belong to «wrong» only
    assert _send(client, id='391-64436', verdict='maybe').status_code == 400
    assert _send(client, id='nope', verdict='right').status_code == 404
    assert _send(client, 'DELETE', id='259-42645').status_code == 200
    assert _cards(client)['259-42645']['decision'] is None


def test_stale_when_card_rebuilt(client, review):
    _send(client, id='259-42645', verdict='right')
    data = json.loads((review / SET / 'data.json').read_text(encoding='utf-8'))
    data['cards'][0]['owners_digest'] = 'changed'
    (review / SET / 'data.json').write_text(json.dumps(data), encoding='utf-8')
    assert _cards(client)['259-42645']['decision']['stale'] is True


def test_cloud_path_writes_the_shared_table(client, review, monkeypatch):
    calls = []
    monkeypatch.setattr(so.sb, 'is_configured', lambda: True)
    monkeypatch.setattr(so.sb, 'upsert_mark_review_decision', lambda **kw: calls.append(('upsert', kw)))
    monkeypatch.setattr(so.sb, 'append_audit', lambda **kw: calls.append(('audit', kw)))
    monkeypatch.setattr(so.sb, 'list_mark_review_decisions_all', lambda ed: [])
    r = _send(client, id='391-64436', verdict='next', note='n')
    assert r.status_code == 200
    (_, up), (_, audit) = calls
    assert (up['edition'], up['word_id'], up['decision'], up['updated_by']) == (so.EDITION, 64436, 'wrong', 'u1')
    assert json.loads(up['correct_mark']) == {'v': 'next', 'r': [], 'n': 'n', 'set': SET}
    assert audit['action'] == 'mark_review_decision' and audit['new_symbol'] == 'next'


def _line(review):
    line = {'line_number': 1, 'line_height': 100, 'words': [
        {'word_index': 64435, 'token': 'لِي', 'cell': [900, 1000]},
        {'word_index': 64436, 'token': 'كَرَّةٗ', 'cell': [700, 900]}],
        'components': [{'id': 'L1:C1', 'path': 'M0 0', 'font_bbox': [900, 0, 990, 90], 'is_mark': False, 'hole_of': None},
                       {'id': 'L1:C2', 'path': 'M0 0', 'font_bbox': [700, 0, 890, 90], 'is_mark': False, 'hole_of': None},
                       {'id': 'L1:C3', 'path': 'M0 0', 'font_bbox': [800, 95, 830, 120], 'is_mark': True, 'hole_of': None}],
        'owners': {'L1:C1': [64435], 'L1:C2': [64436], 'L1:C3': [64435]}, 'neighbours': {'up': False, 'down': True}}
    (review / SET / 'lines').mkdir()
    (review / SET / 'lines' / '391-64436.json').write_text(json.dumps(line), encoding='utf-8')


def test_line_editor_moves(client, review):
    _line(review)
    assert _cards(client)['391-64436']['has_line'] and not _cards(client)['259-42645']['has_line']
    got = client.get(f'/api/mushaf-editor/shamarly-owner/line?set={SET}&id=391-64436').get_json()
    assert got['word_index'] == 64436 and len(got['components']) == 3
    # a mark given to this word, an unchanged outline (dropped), and one sent to the line above
    r = _send(client, id='391-64436', verdict='right', moves={'L1:C3': 64436, 'L1:C2': 64436})
    assert r.get_json()['decision']['moves'] == {'L1:C3': 64436}
    _send(client, id='391-64436', verdict='unsure')                         # a verdict alone keeps the moves
    assert _cards(client)['391-64436']['decision']['moves'] == {'L1:C3': 64436}
    assert _send(client, id='391-64436', verdict='right', moves={'L1:C9': 64436}).status_code == 400
    assert _send(client, id='391-64436', verdict='right', moves={'L1:C1': 1}).status_code == 400
    assert _send(client, id='391-64436', verdict='right', moves={'L1:C3': 'up'}).status_code == 400   # no line above
    bare = _send(client, id='391-64436', verdict='right', moves={'L1:C1': 'down', 'L1:C3': 'down'})
    assert bare.status_code == 400 and 'no ink' in bare.get_json()['message']
    assert _send(client, id='391-64436', verdict='right', moves={'L1:C3': 'down'}).get_json()['decision']['moves'] == {'L1:C3': 'down'}
    assert _send(client, id='391-64436', verdict='right', moves={}).get_json()['decision']['moves'] == {}
