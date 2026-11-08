"""A verse that runs onto the next page keeps each sign on its own word (2:257 spans Shamarly pages 36-37).

The rows were matched against the page's slice of the verse, so the ص of the first «النور» (word 9) landed on
the second «النور» (word 16) of page 37 and the ق of the second «الظلمات» (word 18) on the first one (word 7).
"""


def _signs(client, page):
    data = client.get(f'/api/shamarly/page/{page}?mushaf_version=الشمرلي').get_json()
    out = {}
    for line in data['lines']:
        for w in line['words']:
            marks = [m['symbols'] for m in (w.get('waqf_symbols') or []) if m.get('version') == 'الشمرلي']
            if marks and w.get('word_key', '').startswith('2:257:'):
                out[w['word_key']] = marks[0]
    return out


def test_signs_of_a_split_verse_stay_on_their_words(client):
    assert _signs(client, 36) == {'2:257:9': 'ص'}
    assert _signs(client, 37) == {'2:257:18': 'ق', '2:257:21': 'ص'}
