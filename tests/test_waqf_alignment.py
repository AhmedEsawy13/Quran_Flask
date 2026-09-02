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


def test_qpc_2_26_words_drop_rub_el_hizb():
    """QPC recited words for 2:26 do not include the leading ۞ ornament.
    words[10] is فَوۡقَهَا — the first printed waqf seat."""
    _, words, raw_to_wpos = app._verse_word_texts("2:26")
    assert words, "2:26 should have words"
    assert not words[0].startswith("۞")
    assert "۞" not in words[0]
    assert "فَوۡقَهَا" in words[10]
    # ۞ is the first raw split token and is dropped from recited words.
    assert raw_to_wpos[0] is None


def test_mushaf_row_wpos_cloud_content_index_skips_raw_map():
    """Cloud editor_marks token_index is already 0-based content/recited wpos.
    Mapping it through raw_to_wpos on a ۞ verse (2:26) would land one early."""
    _, words, raw_to_wpos = app._verse_word_texts("2:26")
    n_words = len(words)
    cloud = {"token_index": 10, "symbols": "ج", "index_space": "ayah-token-0based"}
    sqlite = {"token_index": 11, "symbols": "ج"}  # 0-based raw; ۞ is raw 0

    assert app._mushaf_row_wpos(cloud, raw_to_wpos, n_words) == 10
    assert app._mushaf_row_wpos(sqlite, raw_to_wpos, n_words) == 10
    # Old bug: treating cloud 10 as a raw-split index hits فما (wpos 9).
    assert raw_to_wpos[10] == 9
    assert app._mushaf_row_wpos(cloud, raw_to_wpos, n_words) != 9
    assert "فَوۡقَهَا" in words[10]


def test_cloud_qatar_mark_on_hizb_verse_stays_on_content_word(monkeypatch):
    """قطر cloud row token_index 10 on 2:26 must surface as mushafs[].marks wpos 10."""
    import modules.breathing as breathing

    def fake_get(surah, ayah, ver):
        if ver == "قطر":
            return [{
                "token_index": 10,
                "symbols": "ج",
                "index_space": "ayah-token-0based",
                "clean_token": "فَوْقَهَاۚ",
            }]
        return []

    monkeypatch.setattr(breathing, "get_mushaf_waqf_symbols", fake_get)
    monkeypatch.setattr(breathing, "_memo_reciter_installed", lambda rid: False)
    breathing._verse_waqf_cache.clear()
    data = breathing._build_verse_waqf_detail(2, 26)
    qatar = next(m for m in data["mushafs"] if m["id"] == "قطر")
    assert qatar["marks"][0]["wpos"] == 10
    assert data["words"][10].find("فَوۡقَهَا") >= 0

