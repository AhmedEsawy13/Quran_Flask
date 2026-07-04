"""Shared database access helpers.

Uses ``current_app`` (not a module-level ``app``) so any feature blueprint can
open the per-request word_name connection without importing the main app —
this is what lets the blueprints eventually live in their own modules.
"""
import os
import sqlite3
from flask import g, current_app

from core.config import DATABASE


def connect(path, timeout=15.0, row=False):
    """Open a sqlite connection with a generous busy timeout.

    In production the write-capable editor is disabled, so the data DBs are
    read-only and never lock. Locally the editor writes mushaf_waqf.db while
    read endpoints hit it — the timeout lets a reader wait out a brief write
    lock instead of erroring with 'database is locked'.
    """
    conn = sqlite3.connect(path, timeout=timeout)
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
            db = g._database = sqlite3.connect(DATABASE)
            db.row_factory = sqlite3.Row  # To access columns by name
        except sqlite3.Error as e:
            current_app.logger.error(f"Database connection error: {e}")
            return None
    return db


def close_connection(exception):
    """teardown_appcontext handler: close the request word_name connection."""
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()
