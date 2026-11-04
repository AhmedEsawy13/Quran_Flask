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


_DK_WORDS = None


def dk_page(pg: int) -> dict:
    """The app's /api/digital-khatt/page/<pg> words (word_index, text, surah, ayah per line), read from
    data/refs/madinah_dk_words.json.gz so a run needs no Flask server (exported from :5001, 2026-11-04)."""
    global _DK_WORDS
    if _DK_WORDS is None:
        import gzip
        import json
        with gzip.open(ROOT / 'data' / 'refs' / 'madinah_dk_words.json.gz', 'rt', encoding='utf-8') as f:
            _DK_WORDS = json.load(f)
    return _DK_WORDS[str(pg)]
