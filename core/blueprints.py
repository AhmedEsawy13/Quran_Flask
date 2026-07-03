"""Feature blueprints. Defined here — not in app.py — so feature modules can
attach their routes without importing the application object (no circular
imports). app.py registers whichever of these the FEATURES env enables.

  core      — shared Quran text, search, and mushaf page-rendering (read-only)
  reading   — main mushaf reading page + tafseer/tajweed/eerab aids
  memorize  — repeat-verses player
  breathing — reciter-validated waqf stops (دليل التنفس / مُكْث)
  editor    — /mushaf-editor click-to-edit waqf tool (the ONLY writer)
"""
from flask import Blueprint

core_bp = Blueprint('core', __name__)
reading_bp = Blueprint('reading', __name__)
memorize_bp = Blueprint('memorize', __name__)
breathing_bp = Blueprint('breathing', __name__)
editor_bp = Blueprint('editor', __name__)
