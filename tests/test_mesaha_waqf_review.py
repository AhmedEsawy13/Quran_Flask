"""Mesaha waqf review: decisions go to the shared review table (local store here), bulk accept included."""
from __future__ import annotations

import json

import pytest

from modules import mesaha_waqf_review as mw
from modules import waqf_mark_review as wmr

SET = 'mesaha-waqf-test'


def _card(cid, group, model, page=5, word=264, key='2:19:16'):
    return {'id': cid, 'page': page, 'line': 9, 'word_index': word, 'key': key, 'text': 'w', 'group': group,
            'model': model, 'conf': 1.0 if model else None, 'hint': {}, 'suggest': model or ''}


@pytest.fixture
def review(monkeypatch, tmp_path):
    cards = [_card('005-264', 'A', 'ج'), _card('005-270', 'A', 'صلى', word=270),
             _card('006-300', 'B', 'ق', page=6, word=300), _card('006-310', 'N', None, page=6, word=310)]
    cards[1]['model'] = 'ص'
    (tmp_path / SET / 'cards').mkdir(parents=True)
    (tmp_path / SET / 'data.json').write_text(json.dumps({'pages': [5, 6], 'cards': cards, 'a_sample': ['005-264']}))
    monkeypatch.setattr(mw, '_sets_root', lambda: tmp_path)
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


def _decisions(client):
    data = client.get(f'/api/mushaf-editor/mesaha-waqf?set={SET}').get_json()
    return {c['id']: c['decision'] for c in data['cards']}


def test_decision_round_trip(client, review):
    assert _send(client, 'decision', id='006-300', mark='ج').status_code == 200
    assert _decisions(client)['006-300']['mark'] == 'ج'
    [row] = mw.load_decisions().values()
    assert (row['decision'], row['our_mark'], row['correct_mark']) == ('wrong', 'ق', 'ج')
    assert _send(client, 'decision', id='006-300', mark='x').status_code == 400
    assert _send(client, 'decision', 'DELETE', id='006-300').status_code == 200
    assert _decisions(client)['006-300'] is None


def test_accept_group_keeps_earlier_decisions(client, review):
    _send(client, 'decision', id='005-270', mark='')            # reviewed by hand: no sign
    r = _send(client, 'accept', group='A')
    assert r.get_json()['accepted'] == 1
    d = _decisions(client)
    assert d['005-264']['mark'] == 'ج' and d['005-270']['mark'] == '' and d['006-300'] is None
    assert _send(client, 'accept', group='Z').status_code == 400


def test_import_old_export(client, review):
    r = _send(client, 'import', decisions={'006-300': 'ق', '006-310': '', 'nope': 'ج', '005-264': 'zz'})
    assert r.get_json() == {'ok': True, 'imported': 2, 'skipped': 2}
    assert mw.load_decisions()[(6, 300)]['decision'] == 'ok'


def test_card_image_name_is_checked(client, review):
    assert client.get(f'/api/mushaf-editor/mesaha-waqf/card?set={SET}&f=../data.json').status_code == 404
    assert client.get('/api/mushaf-editor/mesaha-waqf/card?set=other&f=005-264.jpg').status_code == 404


def test_complete_mesaha_column_is_offered_to_readers(client):
    import sqlite3
    from core.config import MUSHAF_WAQF_DATABASE
    from core.mushaf_waqf import PARTIAL_WAQF_COLUMNS
    versions = client.get('/api/mushaf-versions').get_json()
    assert 'المساحة' not in PARTIAL_WAQF_COLUMNS
    assert 'المساحة' in versions and 'البحرين' in versions
    with sqlite3.connect(MUSHAF_WAQF_DATABASE) as conn:      # every page but the cover is covered
        pages = {r[0] for r in conn.execute("SELECT page_number FROM waqf_column_pages WHERE edition = 'المساحة'")}
    assert pages == set(range(2, 828))


def test_mesaha_column_matches_resolved_cards():
    pytest.importorskip('cv2')     # the column builder reads the script DB through the cv_waqf pipeline
    from pipeline.add_mesaha_waqf_column import resolve
    cards = [_card('005-264', 'A', 'ج'), _card('006-300', 'B', 'ق', page=6, word=300, key='2:19:17')]
    marks, problems = resolve(cards, {(6, 300): 'ص'})
    assert problems == [] and set(marks.values()) == {'ج', 'ص'}
    _, problems = resolve([_card('006-310', 'N', None, page=6, word=310)], {})
    assert problems == ['006-310 (N) has no decision']
