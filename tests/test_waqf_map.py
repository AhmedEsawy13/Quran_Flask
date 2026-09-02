"""GET /api/waqf-map/<surah> — per-surah خلاف / توجيه navigation map."""
from __future__ import annotations

from core.tawjih import verse_words
from test_tawjih import _published_fixture, _write_fixture


def test_waqf_map_invalid_surah_is_400(client):
    assert client.get("/api/waqf-map/0").status_code == 400
    assert client.get("/api/waqf-map/115").status_code == 400
    body = client.get("/api/waqf-map/0").get_json()
    assert body == {"error": "invalid surah"}


def test_waqf_map_surah_2_has_286_ayahs_and_khilaf_at_26(client):
    response = client.get("/api/waqf-map/2")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["surah"] == 2
    assert payload["ayahs"] == 286
    assert isinstance(payload["items"], list)
    by_ayah = {item["ayah"]: item for item in payload["items"]}
    assert 26 in by_ayah, "2:26 should be flagged (Azhar ج vs other mushafs ص on ربهم)"
    item = by_ayah[26]
    assert item["khilaf"] is True
    assert item["solo"] is False
    assert "tawjih" in item
    for row in payload["items"]:
        assert 1 <= row["ayah"] <= 286
        assert row["khilaf"] or row["tawjih"] or row["solo"]


def test_waqf_map_tawjih_at_2_253_from_sqlite_fixture(client, tmp_path, monkeypatch):
    db = tmp_path / "tawjih.db"
    words = verse_words(2, 253)
    _write_fixture(db, [
        _published_fixture(surah=2, ayah=253, wpos=len(words) - 1),
        _published_fixture(
            tweet_id="fixture-lowconf-253",
            surah=2,
            ayah=253,
            wpos=0,
            align_conf=0,
        ),
        _published_fixture(
            tweet_id="fixture-review-2",
            surah=2,
            ayah=2,
            wpos=0,
            status="review",
            align_conf=0,
        ),
    ])
    monkeypatch.setattr("core.tawjih.TAWJIH_DATABASE", str(db))
    payload = client.get("/api/waqf-map/2").get_json()
    by_ayah = {item["ayah"]: item for item in payload["items"]}
    assert by_ayah[253]["tawjih"] is True
    assert 2 not in by_ayah or by_ayah[2]["tawjih"] is False
