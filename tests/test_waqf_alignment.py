"""Pin the word-alignment logic that has been the source of recurring bugs.

The waqf DB's `token_index` is 1-based AND counts ornament tokens (rub-el-hizb,
ayah-end) that the recited-word list drops, so it must be mapped through
raw_to_wpos rather than used directly as a word index. This invariant has been
violated three separate times; these tests fail loudly if it regresses again.
"""
import app


def test_verse_word_texts_drops_ayah_number():
    """The trailing ayah-number token is not a recited word and must be dropped,
    while raw_to_wpos still maps every raw split index."""
    text, words, raw_to_wpos = app._verse_word_texts("2:26")
    assert words, "2:26 should have words"
    # The last raw token is the ayah number ٢٦ — it maps to None (dropped).
    assert raw_to_wpos[-1] is None
    # Every Arabic word maps to a valid in-range word position.
    for raw_i, wpos in enumerate(raw_to_wpos):
        if wpos is not None:
            assert 0 <= wpos < len(words)


def test_mark_word_context_centers_on_marked_word():
    """2:26's first printed waqf is on فَوۡقَهَا (DB token_index 12, 1-based).
    The context window must be CENTERED on that exact word — the historic bug
    centered two words later (on ٱلَّذِينَ)."""
    wpos, context = app._mark_word_context("2:26", 12)
    _, words, _ = app._verse_word_texts("2:26")
    assert words[wpos] == "فَوۡقَهَاۚ"
    # The marked word must appear inside the returned context snippet.
    assert "فَوۡقَهَا" in context
    # And it must be roughly centred, not at the very edge.
    assert context.split().index("فَوۡقَهَاۚ") in (1, 2)


def test_mark_word_context_matches_word_index_column():
    """token_index mapped through raw_to_wpos must equal the DB's own 1-based
    word_index minus one, across a sample of marks."""
    import sqlite3

    conn = sqlite3.connect(app.MUSHAF_WAQF_DATABASE)
    rows = conn.execute(
        'SELECT "السورة","الآية",token_index,word_index FROM waqf '
        'WHERE token_index IS NOT NULL AND word_index IS NOT NULL LIMIT 200'
    ).fetchall()
    conn.close()
    checked = 0
    for s, a, ti, wi in rows:
        wpos, _ = app._mark_word_context(f"{s}:{a}", ti)
        if wpos is not None:
            assert wpos == wi - 1, f"{s}:{a} ti={ti} mapped {wpos} != word_index-1 {wi - 1}"
            checked += 1
    assert checked > 50, "expected to verify a meaningful sample"
