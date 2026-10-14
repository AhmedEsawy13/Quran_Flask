"""النحاس: a scholar's view stated right beside a braced quote («{X} عن نافع قال: تم»، «قال الأخفش {X}
هاهنا تم الكلام») has a row credited to him, apart from the listed exceptions
(pipeline/review/nahhas_relayed_check.py)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'pipeline' / 'review'))
import nahhas_relayed_check  # noqa: E402


def test_every_relayed_view_has_a_credited_row():
    missing = nahhas_relayed_check.unexplained()
    assert not missing, '\n'.join(f"{m['surah']} {m['who']} «{m['quote']}»" for m in missing[:20])


def test_exceptions_are_still_needed():
    found = {nahhas_relayed_check.key(m) for m in nahhas_relayed_check.check()}
    stale = [k for k in nahhas_relayed_check.exceptions() if k not in found]
    assert not stale, stale
