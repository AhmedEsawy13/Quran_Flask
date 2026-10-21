"""Words whose pieces differ from the hand-checked split of a page.

The truth files live in tests/fixtures/paw_split/<edition>/paw-words-NNN.truth.json (checked by eye,
tile by tile); the run being checked is artifacts/<work>/paw-words-NNN.json.

    python3 pipeline/paw_split/regress.py mesaha-trace 015 021 041
    python3 pipeline/paw_split/regress.py mesaha-trace            # every page that has a truth file
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from pipeline.paw_split._common import ROOT, workdir  # noqa: E402

TRUTH_DIRS = {'mesaha-trace': ROOT / 'tests' / 'fixtures' / 'paw_split' / 'mesaha'}


def changed_words(truth: dict, run: dict) -> list[str]:
    """Texts of the words (verse rings left out) whose ink pieces differ."""
    a = [w for w in truth['words'] if not w['ring']]
    b = [w for w in run['words'] if not w['ring']]
    if [w['text'] for w in a] != [w['text'] for w in b]:
        return ['<word list differs>']
    return [x['text'] for x, y in zip(a, b) if sorted(x.get('pieces', [])) != sorted(y.get('pieces', []))]


def main(argv: list[str]) -> int:
    work = argv[0]
    truth_dir = TRUTH_DIRS[work]
    pages = argv[1:] or sorted(p.name[10:13] for p in truth_dir.glob('paw-words-*.truth.json'))
    workdir(work)
    bad = 0
    for page in pages:
        truth = json.load(open(truth_dir / f'paw-words-{page}.truth.json', encoding='utf-8'))
        run = json.load(open(f'paw-words-{page}.json', encoding='utf-8'))
        diff = changed_words(truth, run)
        bad += bool(diff)
        print(page, 'changed vs truth:', diff)
    return 1 if bad else 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
