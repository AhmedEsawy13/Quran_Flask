"""The Mesaha waqf review tool: moving a mark to another word is atomic, reversible and recorded."""
from __future__ import annotations

import json

import pytest

from pipeline.cv_waqf.mesaha_review import serve


@pytest.fixture()
def tool(tmp_path, monkeypatch):
    words = [{'key': f'2:1:{i}', 'text': f't{i}', 'line': 1, 'box': [0, 0, 1, 1], 'seat': [0, 0]} for i in range(1, 5)]
    pages = [{'page': 7, 'w': 100, 'h': 100, 'words': words, 'proposals': [
        {'key': '2:1:1', 'symbol': 'ج', 'default': 'accept', 'text': 't1', 'line': 1, 'box': [0, 0, 1, 1], 'seat': [0, 0]},
        {'key': '2:1:3', 'symbol': 'ص', 'default': 'review', 'text': 't3', 'line': 1, 'box': [0, 0, 1, 1], 'seat': [0, 0]},
    ]}]
    (tmp_path / 'pages.json').write_text(json.dumps(pages), encoding='utf-8')
    for name, fname in (('DATA', None), ('VERDICTS', 'verdicts.json'), ('DONE', 'done.json'), ('LOG', 'log.jsonl'),
                        ('EXPORT', 'reviewed_marks.json'), ('RELINKS', 'relinks.json')):
        monkeypatch.setattr(serve, name, tmp_path if fname is None else tmp_path / fname)
    return serve.app.test_client(), tmp_path


def _marks(tmp_path):
    return json.loads((tmp_path / 'reviewed_marks.json').read_text(encoding='utf-8'))


def test_relink_moves_the_mark_and_records_it(tool):
    client, tmp = tool
    client.post('/api/done', json={'page': 7, 'done': True})
    assert _marks(tmp)['marks']['7'] == {'2:1:1': 'ج'}                      # the auto-accepted mark
    r = client.post('/api/relink', json={'page': 7, 'from': '2:1:1', 'to': '2:1:2', 'symbol': 'ج'})
    assert r.status_code == 200
    out = _marks(tmp)
    assert out['marks']['7'] == {'2:1:2': 'ج'}                              # on the right word, not the wrong one
    assert out['relinks']['7:2:1:2'] == {'from': '2:1:1', 'symbol': 'ج', 't': out['relinks']['7:2:1:2']['t']}


def test_relink_undo_restores_both_words(tool):
    client, tmp = tool
    client.post('/api/done', json={'page': 7, 'done': True})
    client.post('/api/relink', json={'page': 7, 'from': '2:1:1', 'to': '2:1:2', 'symbol': 'ج'})
    client.post('/api/relink', json={'page': 7, 'from': '2:1:1', 'to': '2:1:2', 'undo': True})
    assert _marks(tmp)['marks']['7'] == {'2:1:1': 'ج'}
    assert json.loads((tmp / 'relinks.json').read_text()) == {}
    assert json.loads((tmp / 'verdicts.json').read_text()) == {}


def test_relink_onto_a_proposal_replaces_its_symbol_and_rejects_bad_requests(tool):
    client, tmp = tool
    client.post('/api/done', json={'page': 7, 'done': True})
    client.post('/api/relink', json={'page': 7, 'from': '2:1:1', 'to': '2:1:3', 'symbol': 'ق'})
    assert _marks(tmp)['marks']['7'] == {'2:1:3': 'ق'}                      # t3 was a proposal for 'ص'; the move decides
    assert client.post('/api/relink', json={'page': 7, 'from': '2:1:1', 'to': '2:1:1', 'symbol': 'ج'}).status_code == 400
    assert client.post('/api/relink', json={'page': 7, 'from': '2:1:1', 'to': '9:9:9', 'symbol': 'ج'}).status_code == 400
    assert client.post('/api/relink', json={'page': 7, 'from': '2:1:1', 'to': '2:1:2', 'symbol': 'x'}).status_code == 400
