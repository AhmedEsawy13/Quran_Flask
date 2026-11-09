"""The Shamarly build validator catches each bug that has broken a page (pipeline/paw_split/shamarly_validate.py)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'pipeline' / 'paw_split'))
import shamarly_validate as V  # noqa: E402

SQUARE = 'M 10 10 L 20 10 L 20 20 L 10 20 Z'
HOLE = 'M 13 13 L 13 17 L 17 17 L 17 13 Z'          # wound the other way round
OTHER = 'M 30 10 L 40 10 L 40 20 L 30 20 Z'


def page(words='', rings=''):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 441 600" data-page="1"><g class="line" data-line="1">'
            f'<g class="ayah-fragment" data-ayah-key="1:1">{words}</g></g>{rings}</svg>')


def word(key, *paths):
    return f'<g class="word" data-word-key="{key}" data-rasm-uthmani="x">' + ''.join(paths) + '</g>'


def body(d):
    return f'<path data-kind="body" d="{d}"/>'


def test_clean_page_passes():
    svg = page(word('1:1:1', body(SQUARE + ' ' + HOLE), body(OTHER)))
    assert V.check_page(svg) == {}


def test_empty_and_duplicate_paths():
    mark = '<path data-kind="mark" data-mark="" data-mark-family="diacritic" d=""/>'
    found = V.check_page(page(word('1:1:1', body(SQUARE), mark) + word('1:1:2', body(OTHER), mark)))
    assert 'empty_path' in found
    twice = V.check_page(page(word('1:1:1', body(SQUARE)) + word('1:1:2', body(SQUARE))))
    assert 'duplicate_d' in twice


def test_zero_width_path_and_empty_groups():
    flat = 'M 10 10 L 10 10.4 L 10 10.4 Z'
    assert 'thin_path' in V.check_page(page(word('1:1:1', body(SQUARE), body(flat))))
    found = V.check_page(page(word('1:1:1') + word('1:1:2', body(SQUARE)),
                              '<g class="ayah-mark" id="r" data-ayah-key="1:1"></g>'))
    assert len(found['empty_group']) == 2


def test_a_hole_alone_in_its_path_is_flagged():
    assert 'orphan_hole' in V.check_page(page(word('1:1:1', body(SQUARE), body(HOLE))))
    assert 'orphan_hole' not in V.check_page(page(word('1:1:1', body(SQUARE + ' ' + HOLE))))


def test_tajweed_lists_must_match_the_diacritic_paths():
    mark = '<path data-kind="mark" data-mark="" data-mark-family="diacritic" d="M 50 10 L 55 10 L 55 15 L 50 15 Z"/>'
    svg = page(word('1:1:1', body(SQUARE), mark))
    assert V.check_page(svg, {'marks': {'1:1:1': ['ghunnah']}, 'letters': {}}) == {}
    assert 'tajweed_marks' in V.check_page(svg, {'marks': {'1:1:1': ['ghunnah', 'qalaqah']}, 'letters': {}})
    assert 'tajweed_span' in V.check_page(svg, {'marks': {}, 'letters': {'1:1:1': [[731.3, 747.1, 'madda_normal']]}})


def test_builder_leftovers_are_reported():
    svg = page(word('1:1:1', body(SQUARE)))
    assert 'unowned_left' in V.check_page(svg, None, {'unowned_left': [['L1:C1', [0, 0, 1, 1]]]})
