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


@pytest.fixture(scope="session")
def app():
    return quran_app.create_app()


@pytest.fixture(scope="session")
def client(app):
    return app.test_client()
