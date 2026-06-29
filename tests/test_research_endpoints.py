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
    # المدينة follows the Hafs marks (+ ج as a stop-rate column); ورش has only صه.
    assert {m["sym"] for m in j["mark_config"]["المدينة الجديد"]} == {"م", "ق", "ص", "لا", "ج"}
    assert [m["sym"] for m in j["mark_config"]["ورش"]] == ["ص"]
    assert j["mark_config"]["ورش"][0]["dir"] == "stop"      # صه = قف, opposite of حفص صلى
    assert {m["sym"] for m in j["mark_config"]["الأزهر"]} == {"م", "لا", "ج"}
    # ج is a "choice" column (stop-rate), not pass/fail.
    assert next(m["dir"] for m in j["mark_config"]["المدينة الجديد"] if m["sym"] == "ج") == "choice"
    assert "ورش" in j["mushafs"]
    # المدينة القديم (old Madinah) keeps the لا sign the new print dropped.
    assert "المدينة القديم" in j["mushafs"]
    old_la = sum(j["agreement"]["المدينة القديم"][r["id"]]["لا"][1] for r in j["reciters"][:1])
    new_la = sum(j["agreement"]["المدينة الجديد"][r["id"]]["لا"][1] for r in j["reciters"][:1])
    assert old_la > 0 and new_la == 0
    ag = j["agreement"]["المدينة الجديد"]
    for r in j["reciters"]:
        for m, (a, t) in ag[r["id"]].items():
            assert 0 <= a <= t  # agreements never exceed opportunities

    def rate(rid, m):
        a, t = ag[rid][m]
        return a / t if t else None

    # م (mandatory) is honoured by essentially everyone.
    lazim_rates = [rate(r["id"], "م") for r in j["reciters"] if ag[r["id"]]["م"][1]]
    assert all(x >= 0.9 for x in lazim_rates)
    # ص (continue-preferred) is the discriminating signal: a real spread exists.
    sila_rates = [rate(r["id"], "ص") for r in j["reciters"] if ag[r["id"]]["ص"][1]]
    assert max(sila_rates) - min(sila_rates) > 0.3


def test_mushaf_agreement_cases_drilldown(client):
    """Drill-down lists the verses where a reciter went against a mark."""
    j = client.get("/api/waqf-research/mushaf-agreement/cases"
                   "?mushaf=الشمرلي&reciter=ahmed_amer&mark=لا").get_json()
    assert j["directive"] == "nostop"
    assert j["disagreed"] >= 0
    assert j["shown"] == len(j["verses"])
    for v in j["verses"]:
        assert 1 <= v["surah"] <= 114 and v["ayah"] >= 1
    # bad params → 400
    assert client.get("/api/waqf-research/mushaf-agreement/cases"
                      "?mushaf=X&reciter=Y&mark=Z").status_code == 400


def test_clustering_matrix_shape(client):
    """تشابه القرّاء returns an ordered full similarity matrix + clusters."""
    j = client.get("/api/waqf-research/clustering").get_json()
    order = [o["id"] for o in j["order"]]
    assert len(order) >= 2
    # symmetric matrix, self-similarity = 1.
    for a in order:
        assert j["matrix"][a][a] == 1.0
        for b in order:
            assert j["matrix"][a][b] == j["matrix"][b][a]
    assert j["range"]["min"] <= j["range"]["max"]
    assert sum(c["size"] for c in j["clusters"]) == len(order)  # every reciter placed


def test_mushaf_similarity_tree_and_pairs(client):
    """تقارب المصاحف: full meaning/placement matrices + an agglomerative dendrogram.
    المدينة الجديد and الكويت are effectively the same print (top pair, ~100%);
    ورش/الهندي are the outliers that join last."""
    j = client.get("/api/waqf-research/mushaf-similarity").get_json()
    ms = j["mushafs"]
    assert {"المدينة الجديد", "الكويت", "ورش", "الهندي"} <= set(ms)
    # symmetric meaning matrix, self-similarity = 1.
    for a in ms:
        assert j["meaning_matrix"][a][a] == 1.0
        for b in ms:
            assert j["meaning_matrix"][a][b] == j["meaning_matrix"][b][a]
    # every leaf appears once in the dendrogram.
    leaves = []
    def walk(n):
        if n["type"] == "leaf":
            leaves.append(n["id"])
        else:
            assert 0.0 <= n["similarity"] <= 1.0
            for c in n["children"]:
                walk(c)
    walk(j["tree"])
    assert sorted(leaves) == sorted(ms)
    # closest pair is the Madinah/Kuwait twin; pairs are sorted strongest-first.
    top = j["pairs"][0]
    assert {top["a"], top["b"]} == {"المدينة الجديد", "الكويت"}
    assert top["meaning"] >= 0.99
    assert [p["meaning"] for p in j["pairs"]] == sorted((p["meaning"] for p in j["pairs"]), reverse=True)


def test_research_endpoints_not_browser_cached(client):
    """Heavy Quran-wide analyses are server-cached, so don't pin them in the browser."""
    r = client.get("/api/waqf-research/clustering")
    assert "no-store" in r.headers.get("Cache-Control", "")


def test_error_responses_are_not_cached(client):
    """A transient API error must never be pinned in the browser/CDN."""
    r = client.get("/api/this-route-does-not-exist")
    assert r.status_code == 404
    assert "no-store" in r.headers.get("Cache-Control", "")


def test_successful_api_response_is_cacheable(client):
    r = client.get("/api/surahs")
    assert r.status_code == 200
    assert "public" in r.headers.get("Cache-Control", "")
