"""Every graded quote in منار, المكتفى and النحاس has a row, apart from the listed
book slips and other-reading sides (pipeline/review/coverage_check.py)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'pipeline' / 'review'))
import coverage_check  # noqa: E402


def test_every_graded_quote_has_a_row():
    missing = coverage_check.unexplained()
    assert not missing, '\n'.join(f"{m['book']} {m['surah']} «{m['quote']}»" for m in missing[:20])


def test_exceptions_are_still_needed():
    # an exception whose row has since appeared should be removed from the list
    found = {(m['book'], f"{m['surah']}:{m['quote']}") for m in coverage_check.check(books=('manar', 'muktafa', 'nahhas'))}
    stale = [(b, k) for b, items in coverage_check.exceptions().items() for k in items if (b, k) not in found]
    assert not stale, stale
