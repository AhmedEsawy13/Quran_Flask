"""Shared pytest fixtures.

The app builds its Flask blueprints at import time and loads all Quran data
from local files, so a single module-scoped app/client is enough for the suite.
"""
import os
import sys

import pytest

# Make the project root importable (app.py lives there, one level up).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app as quran_app  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_cloud_environment(monkeypatch):
    """Tests are local/offline unless their own fixture opts into fake cloud."""
    monkeypatch.delenv('SUPABASE_URL', raising=False)
    monkeypatch.delenv('SUPABASE_SERVICE_ROLE_KEY', raising=False)
    monkeypatch.delenv('EDITOR_SESSION_SECRET', raising=False)


@pytest.fixture(scope="session")
def app():
    # Mount every feature (incl. the write-capable editor) so the suite can
    # exercise all modules. register_blueprints is idempotent; blueprints must
    # be added before the first request, which is why this happens once here.
    return quran_app.create_app({'core', 'reading', 'memorize', 'breathing', 'editor'})


@pytest.fixture(scope="session")
def client(app):
    return app.test_client()
