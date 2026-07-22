"""السكتات, الابتداء, and the API cache-control behaviour."""
import sqlite3

import app
from core.config import CLASSICAL_WAQF_DATABASE


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
    """تقارب المصاحف: full meaning/placement matrices + an agglomerative dendrogram."""
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
    # Pairs are sorted strongest-first and the closest pair remains highly similar.
    top = j["pairs"][0]
    assert "المدينة الجديد" in {top["a"], top["b"]}
    assert top["meaning"] >= 0.9
    assert [p["meaning"] for p in j["pairs"]] == sorted((p["meaning"] for p in j["pairs"]), reverse=True)
    # position keys must be verse-unique, not the per-verse token/word index that
    # collapses the whole Quran onto ~155 slots — so totals are the real counts.
    assert j["counts"]["المدينة الجديد"] > 4000


def test_mushaf_similarity_marks_and_profiles(client):
    """Per-mark consensus + per-mushaf 'what makes it special' signatures."""
    j = client.get("/api/waqf-research/mushaf-similarity").get_json()
    mc = {m["sym"]: m for m in j["mark_consensus"]}
    # الأزهر collapses قلى/صلى into ج → zero ق and ص, a large ج.
    assert mc["ق"]["counts"]["الأزهر"] == 0 and mc["ص"]["counts"]["الأزهر"] == 0
    assert mc["ج"]["counts"]["الأزهر"] > mc["ج"]["counts"]["المدينة الجديد"]
    # new Madinah dropped لا; the old print keeps it.
    assert mc["لا"]["counts"]["المدينة الجديد"] == 0
    assert mc["لا"]["counts"]["المدينة القديم"] > 0
    profs = {p["id"]: p for p in j["profiles"]}
    assert profs["ورش"]["system"] == "warsh" and profs["الهندي"]["system"] == "indopak"
    assert profs["المدينة القديم"]["special"]   # has at least one signature line


def test_mushaf_diff_pairwise(client):
    """قارن مصحفين: grouped, verse-tagged differences; bad/equal pairs rejected."""
    import urllib.parse as u
    q = "a=" + u.quote("المدينة الجديد") + "&b=" + u.quote("المدينة القديم")
    j = client.get("/api/waqf-research/mushaf-diff?" + q).get_json()
    assert 0.0 <= j["meaning"] <= 1.0
    assert j["differences"] > 0
    assert j["shown"] == len(j["verses"])
    for v in j["verses"]:
        assert 1 <= v["surah"] <= 114 and v["ayah"] >= 1
        assert v["a_sym"] != v["b_sym"]      # only genuine disagreements listed
    # same mushaf, or an unknown one → 400
    assert client.get("/api/waqf-research/mushaf-diff?a=X&b=Y").status_code == 400
    same = "a=" + u.quote("الكويت") + "&b=" + u.quote("الكويت")
    assert client.get("/api/waqf-research/mushaf-diff?" + same).status_code == 400


def _classical_rows(surah, ayah):
    """Query the classical DB directly, bypassing /api/classical-waqf's
    _ACTIVE_CLASSICAL_SOURCES allowlist — alignment quality across ALL four
    books (منار is the only one currently served in production; the other
    three's pipeline output still needs to hold up while they're finished)."""
    conn = sqlite3.connect(CLASSICAL_WAQF_DATABASE)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute(
            'SELECT source, wpos, grade, note FROM classical '
            'WHERE surah=? AND ayah=? AND conf=1', (surah, ayah))]
    finally:
        conn.close()


def test_classical_waqf_alignment_quality(client):
    """الداني (المكتفى) + الأشموني (منار الهدى) + النحاس (القطع والائتناف) +
    ابن الأنباري (إيضاح الوقف) aligned to recited-word positions: known
    anchors hold and wpos always lands inside the verse. Checked directly
    against the DB since only منار is currently exposed via the API
    (see test_classical_waqf_api_serves_active_sources_only)."""
    rows = _classical_rows(2, 2)
    got = {(r["source"], r["wpos"], r["grade"]) for r in rows}
    # الداني: {لا ريب فيه} كاف on فيه (w4); {هدى للمتقين} تام on للمتقين (w6).
    assert ("muktafa", 4, "كاف") in got and ("muktafa", 6, "تام") in got
    # النحاس: «التمام {ذلك الكتاب}» → تام on الكتاب (w1).
    assert ("nahhas", 1, "تام") in got
    # ابن الأنباري (parenthesised source): سورة مريم «(قال ربك هو على هين) وقف
    # تام» → تام on هين (19:21 w6).
    got19 = {(r["source"], r["wpos"], r["grade"]) for r in _classical_rows(19, 21)}
    assert ("anbari", 6, "تام") in got19
    # علّة notes never end mid-word: truncated ones close on the elision mark.
    assert all(not r["note"] or r["note"] == r["note"].rstrip() for r in rows)
    # 2:7: the two imams genuinely diverge on سمعهم (w5) — الداني كاف،
    # الأشموني تام. Both must be present, at the same word.
    got7 = {(r["source"], r["wpos"], r["grade"]) for r in _classical_rows(2, 7)}
    assert ("muktafa", 5, "كاف") in got7 and ("manar", 5, "تام") in got7
    # آية الكرسي: الداني's five stops at their exact words + الأشموني rows.
    rows255 = _classical_rows(2, 255)
    dani = {r["wpos"] for r in rows255 if r["source"] == "muktafa"}
    assert {11, 18, 25, 31, 39} <= dani        # نوم، الأرض، بإذنه، خلفهم، شاء
    assert any(r["source"] == "manar" for r in rows255)
    _, words, _ = app._verse_word_texts("2:255")
    for r in rows255:
        assert 0 <= r["wpos"] < len(words)
        assert r["grade"] in ("تام", "كاف", "حسن", "جائز", "صالح", "قبيح", "لا")


def test_classical_waqf_api_serves_active_sources_only(client):
    """Production only exposes منار (الأشموني) — see modules/breathing.py's
    _ACTIVE_CLASSICAL_SOURCES: it's the only source with full 114/114-surah
    coverage and zero low-confidence rows. The other three (الداني، النحاس،
    ابن الأنباري) stay aligned in the DB (previous test) but are withheld
    from both the citation card and تدريب's grader until reviewed."""
    j = client.get("/api/classical-waqf/2/255").get_json()
    assert set(j["sources"].keys()) == {"manar"}
    assert j["sources"]["manar"]["title"].startswith("منار الهدى")
    assert j["entries"], "منار should still have entries for آية الكرسي"
    assert all(e["source"] == "manar" for e in j["entries"])
    # bounds validation
    assert client.get("/api/classical-waqf/115/1").status_code == 400


def test_waqf_practice_grading(client):
    """تدريب الوقف grades chosen stops against mushaf marks only (for now)."""
    p = client.get("/api/waqf-practice/passage/2/1/3").get_json()
    assert [v["ayah"] for v in p["verses"]] == [1, 2, 3]
    assert all(v["words"] for v in p["verses"])

    def grade(stops, mushaf="المدينة الجديد", s=2, f=1, t=5):
        return client.post("/api/waqf-practice/grade", json={
            "surah": s, "from_ayah": f, "to_ayah": t, "mushaf": mushaf, "stops": stops
        }).get_json()

    # 2:2 w3/w4 carry معانقة (ع); verse-end 2:5 has no mark → رأس آية / good.
    r = grade([{"ayah": 2, "wpos": 3}, {"ayah": 5, "wpos": 7}])
    by = {(x["ayah"], x["wpos"]): x for x in r["stops"]}
    assert by[(2, 3)]["has_mark"] is True and by[(2, 3)]["mark"] == "ع"
    assert by[(2, 3)]["verdict"] == "good"
    assert by[(5, 7)]["has_mark"] is False and by[(5, 7)]["verdict"] == "good"
    assert r["score"] == 100 and r["summary"]["errors"] == 0

    # 2:5 w4 carries صلى (ص) → ok (الوصل أولى).
    r = grade([{"ayah": 5, "wpos": 4}], s=2, f=5, t=5)
    assert r["stops"][0]["has_mark"] is True
    assert r["stops"][0]["mark"] == "ص"
    assert r["stops"][0]["verdict"] == "ok"

    # mid-phrase with no mushaf mark → unmarked note, not an error.
    r = grade([{"ayah": 3, "wpos": 1}], s=2, f=3, t=3)
    assert r["stops"][0]["has_mark"] is False
    assert r["stops"][0]["mark"] == ""
    assert r["stops"][0]["verdict"] == "unmarked"
    assert r["summary"]["errors"] == 0

    # bounds + range guards.
    assert client.post("/api/waqf-practice/grade",
                       json={"surah": 2, "from_ayah": 5, "to_ayah": 1}).status_code == 400
    assert client.get("/api/waqf-practice/passage/2/1/99").status_code == 400


def test_research_disk_cache_is_served_verbatim(client):
    """The baked research caches (pipeline/precompute_research.py) exist and the
    endpoint serves exactly that payload — no silent drift between the baked
    file and a live compute."""
    import json as _json
    import os as _os
    path = _os.path.join(app._RESEARCH_CACHE_DIR, "mushaf_similarity.json")
    assert _os.path.exists(path), "run pipeline/precompute_research.py"
    with open(path, encoding="utf-8") as f:
        baked = _json.load(f)
    assert client.get("/api/waqf-research/mushaf-similarity").get_json() == baked


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
