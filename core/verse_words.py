"""Recited-word view of a verse, shared by the web modules and the pipelines.

These helpers used to live in ``modules/breathing.py`` and were reached through
``import app`` — which meant every data-build script had to boot the whole
Flask application just to split a verse into words. They have no Flask
dependency, so they live in ``core`` where both sides can import them.
"""
from core.datasets import qpc_hafs_data_normalized
from core.memorization import _has_arabic_letter


def verse_word_texts(verse_key):
    """Per-word text for a verse, aligned to the QUL/reciter word indices
    (words[i] = recited word i+1).

    Uses the qpc_hafs (Uthmanic) text. `text.split()` also yields NON-word
    tokens — the trailing ayah number and ornaments such as the rub‑el‑hizb ۞ —
    which the reciters do NOT count as words, so they must be dropped or the
    reciter stops shift out of alignment with the mushaf marks (e.g. 2:26).

    Returns (text, words, raw_to_wpos) where raw_to_wpos[i] maps a raw split
    index (the basis the printed-mushaf waqf DB token_index uses, which DOES
    count ornaments) to the stripped word index, or None for a dropped token."""
    td = qpc_hafs_data_normalized.get(verse_key)
    text = (td.get('text', '') if isinstance(td, dict) else '') or ''
    words, raw_to_wpos = [], []
    for tok in text.split():
        if _has_arabic_letter(tok):
            raw_to_wpos.append(len(words))
            words.append(tok)
        else:
            raw_to_wpos.append(None)
    return text, words, raw_to_wpos


def mushaf_row_wpos(row, raw_to_wpos, n_words):
    """0-based recited-word index for one printed-mushaf mark row.

    SQLite mushaf_waqf token_index (after get_mushaf_waqf_symbols) is 0-based
    raw split and COUNTS ornaments like ۞; map through raw_to_wpos.
    Cloud editor_marks token_index is already 0-based content/recited wpos
    (index_space ayah-token-0based) and must NOT go through raw_to_wpos or
    verses that start with ۞ (e.g. 2:26) sit one word early.
    """
    if not row or not row.get('symbols'):
        return None
    ti = row.get('token_index')
    if ti is None:
        return None
    try:
        ti = int(ti)
    except (TypeError, ValueError):
        return None
    if row.get('index_space') == 'ayah-token-0based':
        if 0 <= ti < n_words:
            return ti
        return None
    if 0 <= ti < len(raw_to_wpos):
        return raw_to_wpos[ti]
    return None


def mark_word_context(verse_key, token_index, span=2):
    """Map a printed-mushaf 1-based DB token_index to the recited-word position
    and a small surrounding context snippet, the way the per-verse comparison
    view does it.

    The waqf DB's token_index is 1-based and COUNTS ornaments (rub‑el‑hizb, the
    ayah-end marker), whereas `verse_word_texts` drops those — so the index must
    be mapped through raw_to_wpos rather than used directly as a word index, or
    the context lands a word or two past the actual mark. Returns (wpos, context)
    where wpos is the 0-based recited-word index (or None if it can't be mapped).
    """
    _, words, raw_to_wpos = verse_word_texts(verse_key)
    if not words:
        return None, ''
    wpos = None
    if token_index is not None and 0 <= token_index - 1 < len(raw_to_wpos):
        wpos = raw_to_wpos[token_index - 1]
    if wpos is None:
        # Token mapped to a dropped ornament or fell out of range — clamp the
        # raw index into the recited-word range so context is still sensible.
        ti0 = (token_index - 1) if token_index else 0
        wpos = min(max(ti0, 0), len(words) - 1)
    lo, hi = max(0, wpos - span), min(len(words), wpos + span + 1)
    return wpos, ' '.join(words[lo:hi])
