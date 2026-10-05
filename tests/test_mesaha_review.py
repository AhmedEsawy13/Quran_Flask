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
                        ('EXPORT', 'reviewed_marks.json'), ('RELINKS', 'relinks.json'),
                        ('POSITIONS', 'positions.json')):
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


def test_ring_position_is_saved_exported_and_follows_a_move(tool):
    client, tmp = tool
    client.post('/api/done', json={'page': 7, 'done': True})
    assert client.post('/api/position', json={'page': 7, 'key': '2:1:1', 'pos': [12.34, 56.78]}).status_code == 200
    assert _marks(tmp)['positions']['7'] == {'2:1:1': [12.3, 56.8]}        # for the marks that survived
    # Dragging the ring over another word moves the mark there and takes the position along.
    client.post('/api/relink', json={'page': 7, 'from': '2:1:1', 'to': '2:1:2', 'symbol': 'ج', 'pos': [30, 40]})
    out = _marks(tmp)
    assert out['marks']['7'] == {'2:1:2': 'ج'} and out['positions']['7'] == {'2:1:2': [30, 40]}
    client.post('/api/relink', json={'page': 7, 'from': '2:1:1', 'to': '2:1:2', 'undo': True})
    assert _marks(tmp)['positions']['7'] == {}                              # undo drops the moved position


def test_position_rejects_bad_input(tool):
    client, _ = tool
    assert client.post('/api/position', json={'page': 7, 'key': '2:1:1', 'pos': [1]}).status_code == 400
    assert client.post('/api/position', json={'page': 7, 'key': '9:9:9', 'pos': [1, 2]}).status_code == 400
    assert client.post('/api/relink', json={'page': 7, 'from': '2:1:1', 'to': '2:1:2', 'symbol': 'ج', 'pos': 'x'}).status_code == 400


@pytest.fixture()
def cut_tool(tmp_path, monkeypatch):
    """A page with one row of four words (right to left) whose cuts sit at x = 300, 200 and 100."""
    def word(i, x0, x1):
        return {'key': f'2:1:{i}', 'text': f't{i}', 'line': 1, 'box': [x0, 10, x1, 50], 'seat': [x0 + 6, 30],
                'doubt': 0.9, 'why': 'x', 'dr': 0.9, 'dl': 0.9, 'dw': 0.0}
    words = [word(1, 300, 400), word(2, 200, 300), word(3, 100, 200), word(4, 0, 100)]
    pages = [{'page': 7, 'w': 400, 'h': 100, 'words': words, 'proposals': [dict(words[1], symbol='ج', default='review')]}]
    (tmp_path / 'pages.json').write_text(json.dumps(pages), encoding='utf-8')
    for name, fname in (('DATA', None), ('VERDICTS', 'verdicts.json'), ('DONE', 'done.json'), ('LOG', 'log.jsonl'),
                        ('EXPORT', 'reviewed_marks.json'), ('RELINKS', 'relinks.json'),
                        ('POSITIONS', 'positions.json'), ('CUTS', 'cuts.json')):
        monkeypatch.setattr(serve, name, tmp_path if fname is None else tmp_path / fname)
    return serve.app.test_client(), tmp_path


def test_a_dragged_cut_moves_both_words_is_saved_and_survives_in_the_export(cut_tool):
    client, tmp = cut_tool
    r = client.post('/api/cut', json={'page': 7, 'right': '2:1:1', 'left': '2:1:2', 'x': 320.4})
    assert r.status_code == 200
    page = r.get_json()['page']
    one, two = page['words'][0], page['words'][1]
    assert one['box'][0] == 320 and two['box'][2] == 320                   # the shared edge moved
    assert two['seat'][0] == 206                                          # nothing of the word on the left moved
    assert one['seat'][0] == 326.4                                        # the seat of the word on the right follows its left edge
    assert one['dl'] == 0 and two['dr'] == 0 and one['cut_fixed'] and two['cut_fixed']   # a person looked at that cut
    assert page['proposals'][0]['box'][2] == 320                          # the proposal carries the new box too
    saved = json.loads((tmp / 'cuts.json').read_text())
    assert saved['7:2:1:1|2:1:2']['x'] == 320.4 and saved['7:2:1:1|2:1:2']['was'] == 300   # the cutter's own cut is kept
    assert saved['7:2:1:1|2:1:2']['doubt'] == 0.9                          # and how unsure it was
    assert client.get('/pages.json').get_json()[0]['words'][0]['box'][0] == 320            # the tool serves it from now on
    client.post('/api/cut', json={'page': 7, 'right': '2:1:1', 'left': '2:1:2', 'x': 330})
    assert json.loads((tmp / 'cuts.json').read_text())['7:2:1:1|2:1:2']['was'] == 300     # still the original
    assert _marks(tmp)['cuts']['7:2:1:1|2:1:2']['x'] == 330


def test_a_cut_can_be_undone_and_bad_cuts_are_refused(cut_tool):
    client, tmp = cut_tool
    client.post('/api/cut', json={'page': 7, 'right': '2:1:2', 'left': '2:1:3', 'x': 230})
    r = client.post('/api/cut', json={'page': 7, 'right': '2:1:2', 'left': '2:1:3', 'undo': True})
    assert r.status_code == 200 and json.loads((tmp / 'cuts.json').read_text()) == {}
    assert r.get_json()['page']['words'][1]['box'][0] == 200                # back to the cutter's own
    assert client.post('/api/cut', json={'page': 7, 'right': '2:1:2', 'left': '2:1:3', 'x': 'a'}).status_code == 400
    assert client.post('/api/cut', json={'page': 7, 'right': '2:1:1', 'left': '2:1:3', 'x': 250}).status_code == 400   # not neighbours
    assert client.post('/api/cut', json={'page': 7, 'right': '2:1:2', 'left': '2:1:1', 'x': 250}).status_code == 400   # wrong order
    assert client.post('/api/cut', json={'page': 7, 'right': '2:1:1', 'left': '2:1:2', 'x': 401}).status_code == 400   # past the word
    assert client.post('/api/cut', json={'page': 7, 'right': '2:1:1', 'left': '2:1:2', 'x': 203}).status_code == 400   # leaves the word too narrow
    assert client.post('/api/cut', json={'page': 9, 'right': '2:1:1', 'left': '2:1:2', 'x': 250}).status_code == 400


def test_hand_cuts_are_handed_to_the_cutter_by_word_keys():
    from pipeline.cv_waqf.mesaha_review.cuts import pinned_cuts

    assert pinned_cuts({'7:2:1:1|2:1:2': {'x': 320.4, 'was': 300}}) == {('2:1:1', '2:1:2'): 320.4}


def test_alternative_splits_keep_only_what_differs_and_validate_a_row():
    from pipeline.cv_waqf.mesaha_review import resplit

    current = [300.0, 200.0, 100.0]
    options = [{'id': 'a', 'cuts': [300.0, 201.0, 100.0]},                     # the same cuts
               {'id': 'b', 'cuts': [320.0, 200.0, 100.0]},
               {'id': 'c', 'cuts': [321.0, 200.0, 100.0]},                     # the same as b
               {'id': 'd', 'cuts': [300.0, 150.0, 80.0]}]
    kept = resplit.distinct(current, options, pitch=100)
    assert [o['id'] for o in kept] == ['b', 'd'] and [o['moved'] for o in kept] == [1, 2]
    assert resplit.valid_row([310, 205, 95], 400, 0, 6)
    assert not resplit.valid_row([310, 315, 95], 400, 0, 6) and not resplit.valid_row([399, 205, 95], 400, 0, 6)


def test_a_row_the_reviewer_calls_wrong_gets_alternatives_and_the_chosen_one_is_saved(cut_tool, monkeypatch):
    from pipeline.cv_waqf.mesaha_review import resplit

    client, tmp = cut_tool
    seen = {}

    def fake(page, row, pins):
        seen.update(page=page, words=[w['key'] for w in row], pins=pins)
        return [{'id': 'reader', 'label': 'x', 'cuts': [310.0, 205.0, 95.0], 'moved': 3}]
    monkeypatch.setattr(resplit, 'compute', fake)
    client.post('/api/cut', json={'page': 7, 'right': '2:1:3', 'left': '2:1:4', 'x': 104})          # a hand-set cut stays pinned
    out = client.post('/api/resplit/options', json={'page': 7, 'line': 1}).get_json()
    assert out['options'][0]['id'] == 'reader' and seen['page'] == 7 and seen['words'] == ['2:1:1', '2:1:2', '2:1:3', '2:1:4']
    assert seen['pins'] == {('2:1:3', '2:1:4'): 104.0}
    r = client.post('/api/resplit', json={'page': 7, 'line': 1, 'cuts': [310, 205, 104], 'via': 'reader'})
    assert r.status_code == 200
    saved = json.loads((tmp / 'cuts.json').read_text())
    assert saved['7:2:1:1|2:1:2']['x'] == 310 and saved['7:2:1:1|2:1:2']['via'] == 'resplit:reader' and saved['7:2:1:1|2:1:2']['was'] == 300
    assert '7:2:1:3|2:1:4' in saved and 'via' not in saved['7:2:1:3|2:1:4']               # the hand-set one is untouched (it did not move)
    boxes = [w['box'][0] for w in r.get_json()['page']['words']]
    assert boxes == [310, 205, 104, 0]
    # undo gives back the adopted borders only
    client.post('/api/resplit', json={'page': 7, 'line': 1, 'undo': True})
    left = json.loads((tmp / 'cuts.json').read_text())
    assert list(left) == ['7:2:1:3|2:1:4']


def test_resplit_refuses_bad_input(cut_tool):
    client, _ = cut_tool
    assert client.post('/api/resplit', json={'page': 7, 'line': 1, 'cuts': [310, 205]}).status_code == 400            # wrong count
    assert client.post('/api/resplit', json={'page': 7, 'line': 1, 'cuts': [310, 315, 95]}).status_code == 400        # out of order
    assert client.post('/api/resplit', json={'page': 7, 'line': 1, 'cuts': ['a', 205, 95]}).status_code == 400
    assert client.post('/api/resplit', json={'page': 7, 'line': 9, 'cuts': [1, 2, 3]}).status_code == 400             # no such row
    assert client.post('/api/resplit/options', json={'page': 7, 'line': 9}).status_code == 400
