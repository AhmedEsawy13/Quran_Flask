"""OpenCV 5 waqf-mark detection — offline pipeline package.

Keep this out of the public Flask reading path. Run via:

    .venv-cv/bin/python -m pipeline.cv_waqf <command> ...
"""
from __future__ import annotations

__all__ = ['CLASSES', 'GLYPH_FOR_CLASS']

# Athar letter codes (match modules.waqf_mark_review._SYMBOL_META) + none.
CLASSES: tuple[str, ...] = ('م', 'ق', 'ص', 'ج', 'لا', 'ع', 'س', 'none')

GLYPH_FOR_CLASS: dict[str, str] = {
    'م': 'ۘ',
    'ق': 'ۗ',
    'ص': 'ۖ',
    'ج': 'ۚ',
    'لا': 'ۙ',
    'ع': 'ۛ',
    'س': 'ۜ',
    'none': '',
}
