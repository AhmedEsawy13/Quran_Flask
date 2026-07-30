"""Paths and edition image/layout configuration for CV waqf detection."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from core.config import (
    BAHRAIN_LAYOUT_DATABASE,
    BAHRAIN_REF_CACHE,
    BAHRAIN_REF_PDF,
    BAHRAIN_REF_PDF_OFFSET,
    MESAHA_ARCHIVE_ID,
    MESAHA_LAYOUT_DATABASE,
    MUSHAF_WAQF_DATABASE,
    QURAN_SCRIPT_DATABASE,
    SHAMARLY_LAYOUT_DATABASE,
)

ROOT = Path(__file__).resolve().parents[2]
CV_ROOT = ROOT / 'data' / 'cv'
PAGES_ROOT = CV_ROOT / 'pages'
CROPS_ROOT = CV_ROOT / 'crops'
OVERLAYS_ROOT = CV_ROOT / 'overlays'
MESAHA_BOXES_DB = CV_ROOT / 'word_boxes_mesaha.sqlite'
MESAHA_OCR_DIR = ROOT / 'data' / 'mesaha-ocr'
MODEL_PATH = ROOT / 'models' / 'waqf_glyph.onnx'
CLASSES_PATH = ROOT / 'models' / 'waqf_glyph_classes.json'
ARTIFACTS_ROOT = ROOT / 'artifacts' / 'cv-waqf'

# Default Amiri Quran TTF used to synthesize glyph templates.
DEFAULT_GLYPH_FONT = Path.home() / 'Library' / 'Fonts' / 'amiri-quran.ttf'

IMG_WIDTH = 1024
CROP_SIZE = 48  # square crop fed to the classifier


@dataclass(frozen=True)
class EditionSpec:
    """One printed mushaf the CV pipeline can process."""

    id: str
    mushaf_version: str  # mushaf_waqf.db column
    layout_db: str
    word_space: str  # 'shemrly' | 'qpc'
    script_db: str
    min_page: int
    max_page: int
    # archive | pdf
    image_kind: str
    archive_id: str | None = None
    leaf_offset: int = 0
    pdf_path: str | None = None
    pdf_offset: int = 0  # 0-based PDF index = page + offset
    page_cache_dir: str | None = None
    # Relative text-band crop of the page image (fractions of H/W).
    text_top: float = 0.12
    text_bottom: float = 0.92
    text_left: float = 0.06
    text_right: float = 0.94


EDITIONS: dict[str, EditionSpec] = {
    'الشمرلي': EditionSpec(
        id='shamarly',
        mushaf_version='الشمرلي',
        layout_db=SHAMARLY_LAYOUT_DATABASE,
        word_space='shemrly',
        script_db=QURAN_SCRIPT_DATABASE,
        min_page=2,
        max_page=522,
        image_kind='archive',
        archive_id='shamarlyshamarly',
        leaf_offset=-1,
        page_cache_dir=str(PAGES_ROOT / 'shamarly'),
        text_top=0.11,
        text_bottom=0.90,
    ),
    'البحرين': EditionSpec(
        id='bahrain',
        mushaf_version='البحرين',
        layout_db=BAHRAIN_LAYOUT_DATABASE,
        word_space='qpc',
        script_db=BAHRAIN_LAYOUT_DATABASE,
        min_page=1,
        max_page=604,
        image_kind='pdf',
        pdf_path=BAHRAIN_REF_PDF,
        pdf_offset=BAHRAIN_REF_PDF_OFFSET,
        page_cache_dir=BAHRAIN_REF_CACHE,
        text_top=0.10,
        text_bottom=0.92,
    ),
    'المساحة': EditionSpec(
        id='mesaha',
        mushaf_version='الشمرلي',  # reuse shemrly codes for pilot labels
        layout_db=MESAHA_LAYOUT_DATABASE,
        word_space='shemrly',
        script_db=QURAN_SCRIPT_DATABASE,
        min_page=2,
        max_page=827,
        image_kind='archive',
        archive_id=MESAHA_ARCHIVE_ID,
        leaf_offset=-1,
        page_cache_dir=str(PAGES_ROOT / 'mesaha'),
        text_top=0.14,
        text_bottom=0.88,
    ),
}

WAQF_DB = MUSHAF_WAQF_DATABASE
