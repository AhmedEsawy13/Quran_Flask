"""OpenCV 5 waqf-mark detection — offline pipeline package.

Keep this out of the public Flask reading path. Run via:

    .venv-cv/bin/python -m pipeline.cv_waqf <command> ...
"""
from __future__ import annotations

__all__ = ['CLASSES', 'GLYPH_FOR_CLASS']

from core.waqf_glyphs import CV_CLASSES as CLASSES, GLYPH_FOR_CLASS
