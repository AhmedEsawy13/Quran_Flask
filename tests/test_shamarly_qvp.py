"""Beta الشمرلي QVP pages: the page list follows the folder, missing pages and servers without it answer cleanly."""
import core.config


def test_qvp_pages_follow_the_folder(client, tmp_path, monkeypatch):
    (tmp_path / '042.qvp').write_bytes(b'QVP1-test')
    (tmp_path / '404.qvp').write_bytes(b'QVP1-test')
    (tmp_path / '042.words.json').write_text('[]')
    (tmp_path / 'notes.txt').write_text('x')
    monkeypatch.setattr(core.config, 'SHAMARLY_QVP_DIR', str(tmp_path))

    assert client.get('/api/shamarly/qvp-pages').get_json() == {'pages': [42, 404]}
    page = client.get('/api/shamarly/qvp/42.qvp')
    assert page.status_code == 200
    assert page.data == b'QVP1-test'
    assert client.get('/api/shamarly/qvp/43.qvp').status_code == 404


def test_no_folder_means_no_beta_pages(client, tmp_path, monkeypatch):
    monkeypatch.setattr(core.config, 'SHAMARLY_QVP_DIR', str(tmp_path / 'absent'))
    assert client.get('/api/shamarly/qvp-pages').get_json() == {'pages': []}
    assert client.get('/api/shamarly/qvp/42.qvp').status_code == 404


def test_tajweed_sidecar_is_served_per_page(client, tmp_path, monkeypatch):
    (tmp_path / '042.tajweed.json').write_text('{"2:285:1": ["madda_normal"]}')
    monkeypatch.setattr(core.config, 'SHAMARLY_QVP_DIR', str(tmp_path))
    ok = client.get('/api/shamarly/qvp-tajweed/42.json')
    assert ok.status_code == 200 and ok.get_json() == {'2:285:1': ['madda_normal']}
    assert client.get('/api/shamarly/qvp-tajweed/43.json').status_code == 404
