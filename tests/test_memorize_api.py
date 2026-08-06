"""memorize_bp (modules/memorize.py): the تثبيت audio-timing/phrase-
segmentation API, plus a direct unit test of the mushaf-waqf phrase-snapping
algorithm (_waqf_aligned_phrases) — the one piece of real, synthesizable
logic in this module, worth pinning independent of any specific reciter's
real timing data.
"""
from core.memorization import (
    _audio_timing_entry,
    _gd_audio_offset_ms,
    _gd_audio_url,
)
from modules.memorize import _waqf_aligned_phrases


def test_memorization_verse_count_and_word_monotonic_timing(client):
    j = client.get('/api/memorization/1').get_json()
    assert j['reciter_id'] == 'husary'
    assert j['mode'] == 'acoustic'
    assert len(j['verses']) == 7  # al-Fatiha
    v = j['verses'][0]
    assert v['ayah'] == 1 and v['verse_key'] == '1:1'
    assert v['start'] <= v['end']
    # word timings are 0-based and non-decreasing.
    prev_end = -1
    for wpos, start, end in v['words']:
        assert wpos >= 0
        assert start <= end
        assert start >= prev_end
        prev_end = end
    # every phrase falls within the verse's own [start, end] window.
    for p in v['phrases']:
        assert v['start'] - 0.001 <= p['start'] <= p['end'] <= v['end'] + 0.001


def test_memorization_bounds_and_missing_surah(client):
    assert client.get('/api/memorization/0').status_code == 400
    assert client.get('/api/memorization/115').status_code == 400


def test_memorization_gap_param_clamped_not_rejected(client):
    j = client.get('/api/memorization/1?gap=-5').get_json()
    assert j['gap_ms'] == 250  # negative → default, not an error
    j = client.get('/api/memorization/1?gap=99999').get_json()
    assert j['gap_ms'] == 250  # above the 5000ms ceiling → default


def test_memorization_mode_param_clamped(client):
    j = client.get('/api/memorization/1?mode=bogus').get_json()
    assert j['mode'] == 'acoustic'
    j = client.get('/api/memorization/1?mode=waqf').get_json()
    assert j['mode'] == 'waqf'


def test_memorization_unknown_reciter_falls_back_to_default(client):
    j = client.get('/api/memorization/1?reciter=not-a-real-reciter').get_json()
    assert j['reciter_id'] == 'husary'


def test_memorization_reciters_lists_husary(client):
    """husary's timestamp data ships in the repo (not a QUL-synced optional
    reciter), so it must always be present regardless of what else is installed."""
    out = client.get('/api/memorization-reciters').get_json()
    ids = {r['id'] for r in out}
    assert 'husary' in ids
    husary = next(r for r in out if r['id'] == 'husary')
    assert husary['name_en'] == 'Mahmoud Khalil al-Husary'


def test_memorization_breathing_shape(client):
    j = client.get('/api/memorization/1/breathing').get_json()
    assert j['surah_number'] == 1
    assert len(j['reciters']) >= 1
    assert set(j['verses']) == {'1', '2', '3', '4', '5', '6', '7'}
    for v in j['verses'].values():
        assert v['reciters_total'] >= 1
        for stop in v['stops']:
            assert 0 <= stop['reciters'] <= v['reciters_total']
            assert stop['solo'] == (stop['reciters'] == 1)


def test_memorization_breathing_bounds(client):
    assert client.get('/api/memorization/0/breathing').status_code == 400


def test_drive_reciter_uses_native_range_download_url():
    url = _gd_audio_url('ayyub', 2)
    assert url == (
        'https://drive.usercontent.google.com/download'
        '?id=1rl6qU2TnCacbR_VjK5V-wFm97Zn-cHSg&export=download&confirm=t'
    )
    assert 'mp3quran' not in url


def test_drive_chapter_offsets_shift_qul_timing_without_mutating_cache():
    entry = [[100, 300], [[0, 100, 200], [1, 220, 300]]]
    shifted = _audio_timing_entry('ayyub', 2, entry)

    assert _gd_audio_offset_ms('ayyub', 2) == 59055
    assert shifted == [[59155, 59355], [[0, 59155, 59255], [1, 59275, 59355]]]
    assert entry == [[100, 300], [[0, 100, 200], [1, 220, 300]]]


# ── _waqf_aligned_phrases: pure-function snapping algorithm ────────────────

def _w(idx, start, end):
    return (idx, start, end)


def test_waqf_aligned_phrases_snaps_to_nearby_silence():
    """A boundary at word 2 with no real pause there, but a clear 300ms gap
    one word later (word 3) within the snap window, must snap forward to 3."""
    words = [_w(0, 0, 100), _w(1, 100, 200), _w(2, 200, 300),
             _w(3, 600, 700), _w(4, 700, 800)]
    phrases = _waqf_aligned_phrases(words, boundaries=[2], snap_floor=250, snap_window=3)
    cut_points = sorted(p['first_word'] for p in phrases)
    # word 3's start(600) - word 2's end(300) = 300ms >= snap_floor(250) —
    # the ONLY real silence in this sequence — so the cut lands on word 3, not 2.
    assert cut_points == [0, 3]


def test_waqf_aligned_phrases_keeps_boundary_when_no_nearby_pause():
    """No gap anywhere near the boundary >= snap_floor: honour the waqf mark
    itself rather than silently dropping the phrase break."""
    words = [_w(i, i * 100, i * 100 + 90) for i in range(6)]  # uniform 10ms gaps
    phrases = _waqf_aligned_phrases(words, boundaries=[3], snap_floor=250, snap_window=2)
    cut_points = sorted(p['first_word'] for p in phrases)
    assert cut_points == [0, 3]


def test_waqf_aligned_phrases_ignores_out_of_range_boundaries():
    words = [_w(i, i * 100, i * 100 + 90) for i in range(4)]
    phrases = _waqf_aligned_phrases(words, boundaries=[0, 4, 99], snap_floor=250)
    assert len(phrases) == 1  # every boundary was <=0 or >=n, so no real cut


def test_waqf_aligned_phrases_empty_words():
    assert _waqf_aligned_phrases([], boundaries=[1], snap_floor=250) == []
