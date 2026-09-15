import json
import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FRONTEND = PROJECT_ROOT / "frontend"
PIN_PATH = PROJECT_ROOT / "data/qvp_upstream.json"


def test_madinah_qvp_is_a_registered_reader_edition():
    mushaf = (FRONTEND / "lib/mushaf.ts").read_text(encoding="utf-8")
    assert "madinah_qvp:" in mushaf
    assert 'renderer: "qvp"' in mushaf
    assert 'apiBase: "digital-khatt"' in mushaf
    assert "isQvpEdition" in mushaf


def test_qvp_canvas_is_wired_into_the_mushaf_renderer():
    renderer = (FRONTEND / "components/mushaf-renderer.tsx").read_text(encoding="utf-8")
    assert "QvpPageCanvas" in renderer
    assert "isQvpEdition" in renderer


def test_qvp_decoder_still_expects_qvp1_pages():
    decoder = (FRONTEND / "lib/qvp-lite.ts").read_text(encoding="utf-8")
    assert "0x31505651" in decoder
    assert "export class QvpLitePage" in decoder
    assert "hitTest" in decoder
    assert "QVP_FAMILY_WAQF = 4" in decoder
    assert "hideWaqf" in decoder


def test_qvp_pin_matches_frontend_release():
    pin = json.loads(PIN_PATH.read_text(encoding="utf-8"))
    mushaf = (FRONTEND / "lib/qvp.ts").read_text(encoding="utf-8")
    assert f'export const QVP_RELEASE = "{pin["pages"]["release"]}"' in mushaf
    assert f'export const QVP_CDN_HOST = "{pin["pages"]["cdn"]}"' in mushaf
    assert pin["pages"]["format"] == 1
    assert pin["engine"]["consumed"] == "lite-fork"
    result = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "scripts/check_qvp_upstream.py"), "--offline"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_qvp_upstream_has_not_drifted():
    env = os.environ.copy()
    env.setdefault("QVP_UPSTREAM_STRICT", "1")
    result = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "scripts/check_qvp_upstream.py")],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    if result.returncode != 0 and "upstream lookup failed" in (result.stdout + result.stderr):
        import pytest
        pytest.skip(result.stderr.strip() or result.stdout.strip())
    assert result.returncode == 0, result.stdout + result.stderr
