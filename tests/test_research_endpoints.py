"""السكتات, الابتداء, and the API cache-control behaviour."""
import app


def test_saktat_dataset_integrity(client):
    """Four obligatory + one optional sakta; each on_word actually carries the
    sakta mark (ۜ, U+06DC) at its position in the QPC text."""
    j = client.get("/api/waqf-research/saktat").get_json()
    assert j["count"] == 5
    assert j["obligatory"] == 4
    SAKTA = "ۜ"
    for sk in j["saktat"]:
        _, words, _ = app._verse_word_texts(f"{sk['surah']}:{sk['ayah']}")
        word = words[sk["wpos"]]
        assert SAKTA in word, f"{sk['surah']}:{sk['ayah']} word {word!r} lacks the sakta mark"
        # on_word matches the verse word once diacritics/sakta/waqf marks are folded.
        assert app._normalize_for_search(word) == app._normalize_for_search(sk["on_word"])
        assert sk["reason"]


def test_ibtidaa_back_ups_are_well_formed(client):
    """Every harvested back-up resumes at or before the stop word (never forward),
    has a positive reciter count, and names both words."""
    j = client.get("/api/waqf-research/ibtidaa").get_json()
    assert j["count"] > 0
    assert 0 < j["multi_reciter"] <= j["count"]
    for it in j["items"][:50]:
        assert it["count"] >= 1
        assert it["back_distance"] >= 0
        assert it["stop_word"] and it["resume_word"]
    # Items are sorted strongest-first (most reciters).
    counts = [it["count"] for it in j["items"]]
    assert counts == sorted(counts, reverse=True)


def test_error_responses_are_not_cached(client):
    """A transient API error must never be pinned in the browser/CDN."""
    r = client.get("/api/this-route-does-not-exist")
    assert r.status_code == 404
    assert "no-store" in r.headers.get("Cache-Control", "")


def test_successful_api_response_is_cacheable(client):
    r = client.get("/api/surahs")
    assert r.status_code == 200
    assert "public" in r.headers.get("Cache-Control", "")
