"""المتشابهات relevance: real look-alikes are found, generic-formula noise is not.

The tool must surface verses that share a DISTINCTIVE run (or are near-duplicates)
and must NOT surface verses that merely share a ubiquitous formula like
«يَٰأَيُّهَا ٱلَّذِينَ ءَامَنُوا».
"""


def _matches(client, s, a, **params):
    qs = "&".join(f"{k}={v}" for k, v in params.items())
    j = client.get(f"/api/mutashabihat/{s}/{a}?{qs}").get_json()
    return {f"{m['surah']}:{m['ayah']}": m for m in j["matches"]}


def test_classic_pair_2_58_finds_7_161(client):
    m = _matches(client, 2, 58)
    assert "7:161" in m, "the 2:58 / 7:161 قصة pair must be found"


def test_near_duplicate_refrain_kept(client):
    """al-Rahman's فبأي آلاء refrain repeats verbatim — every repeat is a match
    and is flagged near_duplicate even though the run is common."""
    m = _matches(client, 55, 13)
    assert "55:16" in m
    assert m["55:16"]["near_duplicate"] is True


def test_short_refrain_found(client):
    """The 3-word ويل يومئذ للمكذبين (repeated in al-Mursalat) must be found."""
    m = _matches(client, 77, 15)
    assert "77:19" in m


def test_generic_opener_noise_rejected(client):
    """2:183 shares only «يَٰأَيُّهَا ٱلَّذِينَ ءَامَنُوا» with these — that formula
    appears in ~90 verses, so they are NOT متشابهات and must be filtered out,
    while the genuinely similar 2:178 («...كُتِبَ عَلَيۡكُمُ») is kept."""
    m = _matches(client, 2, 183, limit=60)
    assert "2:178" in m, "the real متشابه (2:178) must survive the filter"
    for noise in ("9:123", "5:57", "24:27"):
        assert noise not in m, f"{noise} shares only a generic opener and must be filtered"


def test_unique_verse_has_no_matches(client):
    """قُلۡ هُوَ ٱللَّهُ أَحَدٌ shares no distinctive run with any verse."""
    j = client.get("/api/mutashabihat/112/1").get_json()
    assert j["count"] == 0


def test_response_shape(client):
    j = client.get("/api/mutashabihat/2/58").get_json()
    assert {"surah", "ayah", "words", "matches", "count"} <= set(j)
    m = j["matches"][0]
    assert {"surah", "ayah", "words", "opcodes", "longest_run", "shared", "coverage"} <= set(m)
