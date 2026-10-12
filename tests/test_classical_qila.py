"""منار rows never carry the book's «وقيل» grade in the author's voice
(pipeline/review/qila_check.py). Otherwise the app shows the author grading one
word twice («وجهٌ آخر عنده») where the second grade is someone else's."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'pipeline' / 'review'))
import qila_check  # noqa: E402


def test_no_qila_view_stored_as_the_authors():
    found = qila_check.check()
    assert not found, '\n'.join(map(str, found[:10]))
