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


def test_mushaf_agreement_shape_and_invariants(client):
    """اتفاق القرّاء مع المصاحف: per-reciter, per-mushaf, per-mark agree/total.
    م (لازم) compliance is near-universal; ص (صلى) genuinely varies across reciters."""
    j = client.get("/api/waqf-research/mushaf-agreement").get_json()
    assert j["gap_ms"] == 1
    assert set(j["marks"]) == {"م", "ق", "ص", "لا"}
    assert "المدينة" in j["mushafs"]
    ag = j["agreement"]["المدينة"]
    # Every reciter present with all four mark buckets.
    for r in j["reciters"]:
        cell = ag[r["id"]]
        assert set(cell) == {"م", "ق", "ص", "لا"}
        for m, (a, t) in cell.items():
            assert 0 <= a <= t  # agreements never exceed opportunities

    def rate(rid, m):
        a, t = ag[rid]["م" if m == "م" else m]
        return a / t if t else None

    # م (mandatory) is honoured by essentially everyone.
    lazim_rates = [rate(r["id"], "م") for r in j["reciters"] if ag[r["id"]]["م"][1]]
    assert all(x >= 0.9 for x in lazim_rates)
    # ص (continue-preferred) is the discriminating signal: a real spread exists.
    sila_rates = [rate(r["id"], "ص") for r in j["reciters"] if ag[r["id"]]["ص"][1]]
    assert max(sila_rates) - min(sila_rates) > 0.3


def test_error_responses_are_not_cached(client):
    """A transient API error must never be pinned in the browser/CDN."""
    r = client.get("/api/this-route-does-not-exist")
    assert r.status_code == 404
    assert "no-store" in r.headers.get("Cache-Control", "")


def test_successful_api_response_is_cacheable(client):
    r = client.get("/api/surahs")
    assert r.status_code == 200
    assert "public" in r.headers.get("Cache-Control", "")
