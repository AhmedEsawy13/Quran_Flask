import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_recitequran_dtw_port_holds_endpoint_and_waqf():
    script = PROJECT_ROOT / "tests/js/test_athar_phoneme_dtw.js"
    result = subprocess.run(
        ["node", str(script)],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "ok" in result.stdout
