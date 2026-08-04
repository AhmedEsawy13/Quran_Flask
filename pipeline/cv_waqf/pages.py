"""Page-image fetch/cache for Archive leaves and Bahrain PDF."""
from __future__ import annotations

import logging
import os
import tempfile
import urllib.request
from contextlib import contextmanager
from pathlib import Path

from pipeline.cv_waqf.config import IMG_WIDTH, EditionSpec

logger = logging.getLogger(__name__)

_UA = (
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
    'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
)


@contextmanager
def _atomic_output(out: Path):
    """Yield a unique sibling temp path and atomically publish it.

    Multiple local reviewer requests can render the same uncached page at
    once. A fixed ``.tmp`` name lets one request move the other request's file,
    causing a spurious FileNotFoundError. Unique files make concurrent writers
    harmless; the final complete JPEG wins.
    """
    out.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        dir=out.parent,
        prefix=f'.{out.name}.',
        suffix='.tmp',
        delete=False,
    )
    tmp = Path(handle.name)
    handle.close()
    try:
        yield tmp
        os.replace(tmp, out)
    finally:
        tmp.unlink(missing_ok=True)


def page_image_path(spec: EditionSpec, page: int, width: int = IMG_WIDTH) -> Path:
    cache = Path(spec.page_cache_dir or '.')
    cache.mkdir(parents=True, exist_ok=True)
    if spec.image_kind == 'pdf':
        # Match modules.editor._bahrain_ref_jpeg naming.
        return cache / f'p{page:03d}_w{width}.jpg'
    return cache / f'p{page:03d}_w{width}.jpg'


def ensure_page_image(spec: EditionSpec, page: int, width: int = IMG_WIDTH) -> Path:
    """Return a local JPEG for ``page``, downloading/rendering if needed."""
    if not (spec.min_page <= page <= spec.max_page):
        raise ValueError(f'page {page} outside {spec.min_page}..{spec.max_page}')
    out = page_image_path(spec, page, width)
    if out.is_file() and out.stat().st_size > 0:
        return out

    if spec.image_kind == 'pdf':
        return _render_pdf_page(spec, page, width, out)
    if spec.image_kind == 'archive':
        return _download_archive_leaf(spec, page, width, out)
    if spec.image_kind == 'cache':
        raise FileNotFoundError(
            f'{spec.id}: verified printed page is not cached at {out}. '
            'Cache the matching edition scan before generating trusted crops.'
        )
    raise ValueError(f'unsupported image_kind={spec.image_kind!r}')


def _download_archive_leaf(
    spec: EditionSpec, page: int, width: int, out: Path,
) -> Path:
    if not spec.archive_id:
        raise RuntimeError(f'{spec.id}: missing archive_id')
    leaf = page + int(spec.leaf_offset)
    url = (
        f'https://archive.org/download/{spec.archive_id}/'
        f'page/leaf{leaf}_w{width}.jpg'
    )
    req = urllib.request.Request(url, headers={'User-Agent': _UA})
    logger.info('Downloading %s → %s', url, out)
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = resp.read()
    if len(data) < 1000 or data[:2] != b'\xff\xd8':
        raise RuntimeError(f'bad JPEG from {url} ({len(data)} bytes)')
    with _atomic_output(out) as tmp:
        tmp.write_bytes(data)
    return out


def _render_pdf_page(
    spec: EditionSpec, page: int, width: int, out: Path,
) -> Path:
    pdf = spec.pdf_path
    if not pdf or not os.path.isfile(pdf):
        raise FileNotFoundError(
            f'{spec.id}: PDF missing at {pdf!r}. '
            'Run pipeline/fetch_bahrain_ref_pdf.py first.'
        )
    try:
        import fitz  # PyMuPDF
    except ImportError as exc:
        raise RuntimeError(
            'pymupdf is required to render Bahrain pages '
            '(pip install -r requirements-cv.txt)'
        ) from exc

    out.parent.mkdir(parents=True, exist_ok=True)
    pdf_index = page + int(spec.pdf_offset)
    doc = fitz.open(pdf)
    try:
        if pdf_index < 0 or pdf_index >= doc.page_count:
            raise ValueError(
                f'PDF index {pdf_index} out of range for page {page}'
            )
        pg = doc.load_page(pdf_index)
        zoom = width / float(pg.rect.width)
        pix = pg.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        with _atomic_output(out) as tmp:
            pix.save(str(tmp), output='jpeg', jpg_quality=82)
    finally:
        doc.close()
    return out


def cache_page_range(
    spec: EditionSpec,
    start: int,
    end: int,
    width: int = IMG_WIDTH,
) -> list[Path]:
    paths: list[Path] = []
    for page in range(start, end + 1):
        paths.append(ensure_page_image(spec, page, width=width))
    return paths
