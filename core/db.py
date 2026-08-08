"""Shared database access helpers.

Uses ``current_app`` (not a module-level ``app``) so any feature blueprint can
open the per-request word_name connection without importing the main app —
this is what lets the blueprints eventually live in their own modules.
"""
import os
import sqlite3
from pathlib import Path
from flask import g, current_app

from core.config import DATABASE


def connect(path, timeout=15.0, row=False, readonly=False):
    """Open SQLite with consistent timeout, row, and access-mode handling.

    ``readonly=True`` uses SQLite's ``mode=ro`` URI. It therefore cannot create
    a missing database or acquire an accidental write lock. Callers that own a
    deliberate editor/pipeline write use the default read-write mode.
    """
    target = str(path)
    uri = False
    if readonly:
        target = Path(target).resolve().as_uri() + '?mode=ro'
        uri = True
    conn = sqlite3.connect(target, timeout=timeout, uri=uri)
    if row:
        conn.row_factory = sqlite3.Row
    return conn


def get_db():
    """Return the request-scoped word_name.db connection (sqlite3.Row rows)."""
    db = getattr(g, '_database', None)
    if db is None:
        # Check if database file exists
        if not os.path.exists(DATABASE):
            current_app.logger.error(f"Database file not found: {DATABASE}")
            return None

        try:
            db = g._database = connect(DATABASE, row=True, readonly=True)
        except sqlite3.Error as e:
            current_app.logger.error(f"Database connection error: {e}")
            return None
    return db


def close_connection(exception):
    """teardown_appcontext handler: close the request word_name connection."""
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()
