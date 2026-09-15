from core.memorization import normalize_qul_word_timestamps


def test_qul_v3_rows_become_verse_keys():
    raw = {
        '_meta': {'schema_version': 3, 'tier': 'word'},
        'rows': [
            ['1:1', 100, 200, True, 40, [[1, 110, 140], [2, 140, 190]]],
            ['1:2', 240, 400, True, 0, [[1, 250, 390]]],
        ],
    }
    out = normalize_qul_word_timestamps(raw)
    assert out['1:1'][0] == [100, 200]
    assert out['1:1'][1] == [[1, 110, 140], [2, 140, 190]]
    assert out['1:2'][1][0][0] == 1


def test_qul_v3_repeat_rows_stay_in_audio_order():
    raw = {
        '_meta': {'schema_version': 3},
        'rows': [
            ['1:1', 100, 180, True, 20, [[1, 100, 180]]],
            ['1:1', 200, 280, False, 0, [[1, 200, 280]]],
        ],
    }
    words = normalize_qul_word_timestamps(raw)['1:1'][1]
    assert words == [[1, 100, 180], [1, 200, 280]]


def test_qul_v2_passthrough():
    raw = {
        '_meta': {'schema_version': 1},
        '1:1': [[10, 50], [[1, 10, 50]]],
    }
    assert normalize_qul_word_timestamps(raw) is raw
