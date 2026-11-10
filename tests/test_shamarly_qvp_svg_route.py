"""The reader's «رسم الملف» verse view cuts words out of the page SVG the QVP was built from."""
import pytest


@pytest.fixture
def svg_dir(tmp_path, monkeypatch):
    qvp = tmp_path / 'qvp'
    svg = tmp_path / 'svg'
    qvp.mkdir()
    svg.mkdir()
    (svg / '004.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg"><g class="word"/></svg>', encoding='utf-8')
    monkeypatch.setattr('core.config.SHAMARLY_QVP_DIR', str(qvp))
    return svg


def test_svg_route_serves_built_page(client, svg_dir):
    response = client.get('/api/shamarly/qvp-svg/004.svg')
    assert response.status_code == 200
    assert response.mimetype == 'image/svg+xml'
    assert b'class="word"' in response.data


def test_svg_route_missing_page_is_404(client, svg_dir):
    assert client.get('/api/shamarly/qvp-svg/005.svg').status_code == 404
    assert client.get('/api/shamarly/qvp-svg/0.svg').status_code == 404
