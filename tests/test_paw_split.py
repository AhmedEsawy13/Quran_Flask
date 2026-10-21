"""pipeline/paw_split: the Mesaha word split must keep reproducing the hand-checked pages.

The truth files (tests/fixtures/paw_split/mesaha) were checked by eye, word by word. The page scans
(data/cv/pages/mesaha, gitignored) exist only on the machine that downloaded them, so the split
itself is skipped elsewhere; the fixtures are still checked for shape. One page runs by default
(~15 s); all ten with PAW_SPLIT_ALL=1 (~2.5 min).
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / 'tests' / 'fixtures' / 'paw_split' / 'mesaha'
TRUTH = sorted(FIXTURES.glob('paw-words-*.truth.json'))
RUN = TRUTH if os.environ.get('PAW_SPLIT_ALL') == '1' else TRUTH[:1]

sys.path.insert(0, str(ROOT))
from pipeline.paw_split.regress import changed_words  # noqa: E402


def _page(path: Path) -> int:
    return int(path.name[10:13])


def test_fixtures_are_whole_pages():
    assert len(TRUTH) == 10
    for path in TRUTH:
        d = json.loads(path.read_text(encoding='utf-8'))
        assert d['page'] == _page(path)
        words = [w for w in d['words'] if not w['ring']]
        assert len(words) >= 90 and all(w['pieces'] for w in words)


def test_changed_words_reports_moved_piece():
    truth = {'words': [{'text': 'أ', 'ring': False, 'pieces': [1, 2]}, {'text': 'ب', 'ring': False, 'pieces': [3]}]}
    run = {'words': [{'text': 'أ', 'ring': False, 'pieces': [1]}, {'text': 'ب', 'ring': False, 'pieces': [2, 3]}]}
    assert changed_words(truth, truth) == []
    assert changed_words(truth, run) == ['أ', 'ب']


@pytest.mark.parametrize('truth_path', RUN, ids=lambda p: f'p{_page(p):03d}')
def test_mesaha_split_matches_hand_checked_page(truth_path):
    pytest.importorskip('cv2')
    page = _page(truth_path)
    if not (ROOT / 'data' / 'cv' / 'pages' / 'mesaha' / f'p{page:03d}_w1600.jpg').is_file():
        pytest.skip('Mesaha page scans are not on this machine')
    done = subprocess.run([sys.executable, str(ROOT / 'pipeline' / 'paw_split' / 'mesaha_split.py'), str(page)],
                          capture_output=True, text=True, timeout=300)
    assert done.returncode == 0, done.stderr[-2000:]
    run = json.loads((ROOT / 'artifacts' / 'mesaha-trace' / f'paw-words-{page:03d}.json').read_text(encoding='utf-8'))
    truth = json.loads(truth_path.read_text(encoding='utf-8'))
    assert changed_words(truth, run) == []
