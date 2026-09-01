"""Canonical waqf mark letter codes → Uthmanic Hafs combining glyphs.

Single source of truth for Python; keep ``data/waqf_glyphs.json`` in sync for JS.
All standard Hafs stop marks render in ``static/fonts/uthmanic_hafs_v20.woff2``.
"""
from __future__ import annotations

# Letter / alias codes stored in mushaf_waqf.db → printed stop glyphs (Hafs).
WAQF_GLYPH_MAP: dict[str, str] = {
    'م': 'ۘ', 'قلى': 'ۗ', 'قلي': 'ۗ', 'ق': 'ۗ',
    'صلى': 'ۖ', 'صلي': 'ۖ', 'ص': 'ۖ', 'ج': 'ۚ',
    'لا': 'ۙ', 'س': 'ۜ', 'ع': 'ۛ',
    # Already-encoded combining forms (idempotent).
    'ۘ': 'ۘ', 'ۗ': 'ۗ', 'ۖ': 'ۖ', 'ۚ': 'ۚ', 'ۙ': 'ۙ', 'ۛ': 'ۛ', 'ۜ': 'ۜ',
    # IndoPak small-high marks — present in Uthmanic Hafs v20; pass through.
    'ؕ': 'ؕ', 'ؗ': 'ؗ', 'ؔ': 'ؔ', '۪': '۪', '۫': '۫', '۬': '۬',
}

# Primary symbols for legends, CV classes, and print packs.
SYMBOL_META: tuple[tuple[str, str, str], ...] = (
    ('م', 'ۘ', 'لازم'),
    ('لا', 'ۙ', 'لا وقف'),
    ('ق', 'ۗ', 'الوقف أولى'),
    ('ص', 'ۖ', 'الوصل أولى'),
    ('ج', 'ۚ', 'جائز'),
    ('س', 'ۜ', 'سكتة'),
    ('ع', 'ۛ', 'معانقة'),
)

# How reviewers write marks on paper (صلى / قلى / ج …).
MARK_WRITE_FORM: dict[str, str] = {
    'ص': 'صلى', 'صلي': 'صلى', 'صلى': 'صلى',
    'ق': 'قلى', 'قلي': 'قلى', 'قلى': 'قلى',
    'م': 'م', 'ج': 'ج', 'لا': 'لا', 'س': 'س', 'ع': 'ع',
}

# Short Arabic labels next to the printed pause glyph in review UIs.
SHORT_NAME: dict[str, str] = {
    'م': 'لازم',
    'لا': 'لا وقف',
    'ق': 'قلى',
    'ص': 'صلى',
    'ج': 'جائز',
    'س': 'سكتة',
    'ع': 'معانقة',
}

SYMBOL_CHOICES: tuple[str, ...] = tuple(code for code, _glyph, _name in SYMBOL_META)

# CV / ONNX classifier classes (includes none).
CV_CLASSES: tuple[str, ...] = (*SYMBOL_CHOICES, 'none')

GLYPH_FOR_CLASS: dict[str, str] = {
    **{code: glyph for code, glyph, _name in SYMBOL_META},
    'none': '',
}


def waqf_glyph(symbol: str) -> str:
    """Map DB mark code(s) to Uthmanic combining glyph string."""
    raw = (symbol or '').strip()
    if not raw or raw == 'ركوع':
        return raw
    parts: list[str] = []
    for token in raw.replace('،', ',').split(','):
        token = token.replace(' ', '').strip()
        if token:
            parts.append(WAQF_GLYPH_MAP.get(token, token))
    return ''.join(parts)


def waqf_write_form(symbol: str) -> str:
    """Human-written mark label for print legend (صلى / قلى / ج …)."""
    raw = (symbol or '').strip()
    if not raw or raw == 'ركوع':
        return raw
    parts: list[str] = []
    for token in raw.replace('،', ',').split(','):
        token = token.replace(' ', '').strip()
        if not token:
            continue
        parts.append(MARK_WRITE_FORM.get(token, token))
    return '،'.join(parts)
