"""Shared setup for the paw_split scripts: repo root on sys.path, and every script runs inside its
gitignored work folder under artifacts/ (pages' JSON, labels and tiles are written there)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# The Qatar mushaf app's bundled assets (pages 1-49 at 600 dpi + verse regions). Only files the app
# ships are read; nothing is fetched from its servers.
QATAR_APP_ASSETS = os.environ.get(
    'QATAR_APP_ASSETS',
    '/Applications/Runner.app/Wrapper/Runner.app/Frameworks/App.framework/flutter_assets/assets',
)


def workdir(name: str) -> Path:
    """cd into artifacts/<name> (created if needed) and return it."""
    path = ROOT / 'artifacts' / name
    path.mkdir(parents=True, exist_ok=True)
    os.chdir(path)
    return path
