"""In-editor review of a book audit: decisions write cloud drafts and are recorded."""
from __future__ import annotations

import json

import pytest

from modules import audit_review as ar

ED = 'البحرين'


def _item(tab, key, db=None, cv=None, **kw):
    return dict(tab=tab, word_key=key, db=db, cv=cv, page=4, text='w', crop='c.jpg', **kw)


def test_targets_per_tab():
    assert ar.targets(_item('add', '2:5:3', cv='ج'), 'image') == {'2:5:3': 'ج'}
    assert ar.targets(_item('add', '2:5:3', cv='ج'), 'db') == {'2:5:3': ''}
    assert ar.targets(_item('differs', '2:5:3', db='ص', cv='ج'), 'image') == {'2:5:3': 'ج'}
    assert ar.targets(_item('differs', '2:5:3', db='ص', cv='ج'), 'db') == {'2:5:3': 'ص'}
    assert ar.targets(_item('missed', '2:5:3', db='ق'), 'image') == {'2:5:3': ''}
    assert ar.targets(_item('missed', '2:5:3', db='ق'), 'db') == {'2:5:3': 'ق'}
    shift = _item('shift', '2:5:4', db='ج', cv='ج', from_key='2:5:3')
    assert ar.targets(shift, 'image') == {'2:5:3': '', '2:5:4': 'ج'}
    assert ar.targets(shift, 'db') == {'2:5:3': 'ج', '2:5:4': ''}
    assert ar.targets(_item('differs', '2:5:3', db='ص', cv='ج'), 'set', 'م') == {'2:5:3': 'م'}


@pytest.fixture
def cloud(monkeypatch, tmp_path):
    """A fake Supabase: marks keyed by word_key (published = the DB), decisions by (page, word_id)."""
    queue = {'edition': ED, 'built': 'x', 'summary': {}, 'tabs': [{'id': 'differs', 'title': 't', 'note': ''}],
             'items': [_item('differs', '2:5:3', db='ص', cv='ج'),
                       _item('shift', '2:5:5', db='ج', cv='ج', from_key='2:5:4')]}
    (tmp_path / 'queue.json').write_text(json.dumps(queue, ensure_ascii=False))
    published = {'2:5:3': 'ص', '2:5:4': 'ج'}
    state = {'draft': {}, 'decisions': {}, 'writes': []}
    first = 1000                                  # layout id of 2:5:1

    def marks(edition, keys):
        return {k: state['draft'].get(k, published.get(k, '')) for k in keys}

    def write(word_id, edition, symbol, user):
        key = f'2:5:{word_id - first + 1}'
        state['draft'][key] = symbol
        state['writes'].append((key, symbol))

    monkeypatch.setattr(ar, '_audit_dir', lambda e: tmp_path)
    monkeypatch.setattr(ar, '_layout_word_id', lambda k: first + int(k.split(':')[2]) - 1)
    monkeypatch.setattr(ar, '_cloud_marks', marks)
    monkeypatch.setattr(ar, '_get_or_set_word_waqf_cloud', write)
    monkeypatch.setattr(ar.sb, 'is_configured', lambda: True)
    monkeypatch.setattr(ar.sb, 'list_mark_review_decisions',
                        lambda e: [dict(v, page_number=p, word_id=w) for (p, w), v in state['decisions'].items()])
    monkeypatch.setattr(ar.sb, 'upsert_mark_review_decision',
                        lambda **kw: state['decisions'].__setitem__((kw['page_number'], kw['word_id']), kw))
    monkeypatch.setattr(ar.sb, 'delete_mark_review_decision',
                        lambda **kw: state['decisions'].pop((kw['page_number'], kw['word_id']), None))
    import modules.editor_auth as auth
    monkeypatch.setattr(auth, 'editor_session_secret_configured', lambda: True)
    monkeypatch.setattr(auth, 'current_editor', lambda: {'id': 'u1', 'name': 'r', 'role': 'editor'})
    monkeypatch.setattr(ar, 'current_editor', lambda: {'id': 'u1', 'name': 'r', 'role': 'editor'})
    return state


def _post(client, method='POST', **body):
    return getattr(client, method.lower())('/api/mushaf-editor/book-audit/decision',
                                           data=json.dumps(dict(edition=ED, **body)), content_type='application/json')


def test_image_decision_writes_the_draft_and_records_it(client, cloud):
    r = _post(client, tab='differs', word_key='2:5:3', choice='image')
    assert r.status_code == 200, r.get_json()
    assert cloud['writes'] == [('2:5:3', 'ج')]
    [d] = cloud['decisions'].values()
    assert (d['decision'], d['our_mark'], d['correct_mark']) == ('wrong', 'ص', 'ج')
    q = client.get(f'/api/mushaf-editor/book-audit?edition={ED}').get_json()
    assert q['items'][0]['decision'] == {'decision': 'wrong', 'mark': 'ج', 'at': None}
    assert q['items'][0]['cloud'] == 'ج'


def test_db_is_right_writes_nothing(client, cloud):
    assert _post(client, tab='differs', word_key='2:5:3', choice='db').status_code == 200
    assert cloud['writes'] == []
    assert [d['decision'] for d in cloud['decisions'].values()] == ['ok']


def test_undo_restores_the_db_and_forgets_the_decision(client, cloud):
    _post(client, tab='shift', word_key='2:5:5', choice='image')
    assert cloud['draft'] == {'2:5:4': '', '2:5:5': 'ج'}
    assert _post(client, 'DELETE', tab='shift', word_key='2:5:5').status_code == 200
    assert cloud['draft'] == {'2:5:4': 'ج', '2:5:5': ''}
    assert cloud['decisions'] == {}


def test_unknown_card_and_bad_symbol_are_refused(client, cloud):
    assert _post(client, tab='differs', word_key='9:9:9', choice='image').status_code == 404
    assert _post(client, tab='differs', word_key='2:5:3', choice='set', symbol='x').status_code == 400
    assert cloud['writes'] == []


def test_refused_without_the_cloud(client, cloud, monkeypatch):
    monkeypatch.setattr(ar.sb, 'is_configured', lambda: False)
    r = _post(client, tab='differs', word_key='2:5:3', choice='image')
    assert r.status_code == 409 and r.get_json()['error'] == 'cloud_not_configured'


def test_crop_names_cannot_escape_the_audit_dir(client, cloud):
    assert client.get(f'/api/mushaf-editor/book-audit/crop?edition={ED}&f=../queue.json').status_code == 404


def test_clearing_an_add_card_counts_as_the_db_being_right(client, cloud):
    cloud['draft']['2:5:3'] = ''                  # pretend the queue card is an «add» on an empty word
    import json as _j
    q = _j.loads((ar._audit_dir(ED) / 'queue.json').read_text())
    q['items'][0].update(tab='add', db=None)
    (ar._audit_dir(ED) / 'queue.json').write_text(_j.dumps(q, ensure_ascii=False))
    assert _post(client, tab='add', word_key='2:5:3', choice='set', symbol='').status_code == 200
    assert [d['decision'] for d in cloud['decisions'].values()] == ['ok']
