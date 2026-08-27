"""Paths and edition image/layout configuration for CV waqf detection."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from core.config import (
    AZHAR_LAYOUT_DATABASE,
    AZHAR_LAYOUT_MAX_PAGE,
    AZHAR_LAYOUT_MIN_PAGE,
    BAHRAIN_LAYOUT_DATABASE,
    BAHRAIN_REF_CACHE,
    BAHRAIN_REF_PDF,
    BAHRAIN_REF_PDF_OFFSET,
    MESAHA_ARCHIVE_ID,
    MESAHA_LAYOUT_DATABASE,
    MUSHAF_WAQF_DATABASE,
    DIGITAL_KHATT_LAYOUT_DATABASE,
    QPC_V1_LAYOUT_DATABASE,
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

# Target-print models are optional and fall back to the shared classifier when
# absent. Keeping them separate prevents Bahrain-specific hard negatives from
# degrading trusted Shamarly/Madinah/Azhar behavior.
EDITION_MODEL_PATHS: dict[str, Path] = {
    'البحرين': ROOT / 'models' / 'waqf_glyph_bahrain.onnx',
}

# Default Amiri Quran TTF used to synthesize glyph templates.
DEFAULT_GLYPH_FONT = Path.home() / 'Library' / 'Fonts' / 'amiri-quran.ttf'

IMG_WIDTH = 1024
CROP_SIZE = 48  # square crop fed to the classifier

PROPOSAL_MODES = frozenset({'narrow', 'hybrid'})


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
    # Candidate geometry. ``hybrid`` adds line-component proposals on top of
    # the above-word band. Keep ``narrow`` unless an edition model has beaten
    # production on unseen reviewer labels with the broader search.
    default_proposal_mode: str = 'narrow'
    # Detect floor for /cv-waqf and other human-review paths.
    review_min_conf: float = 0.55
    # Draft/auto-set writes (bootstrap). Higher than review_min_conf when a
    # confidence cutoff cuts false positives without collapsing recall.
    auto_set_min_conf: float = 0.70


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
        # The 15 Quran rows occupy this band in the 1024px Bahrain scans.
        # A wider 10%..92% band drifts by almost a full row at both edges.
        text_top=0.14,
        text_bottom=0.88,
        # Gated Bahrain ONNX + hybrid proposals: 217/238 correct on 44
        # labeled pages at min_conf 0.55, vs 11/238 for gated + narrow.
        default_proposal_mode='hybrid',
        # 0.85 keeps almost the same recall (214/238) while cutting FP 31 → 14.
        # Remaining FPs are 0.97+ fatha-sized glyphs; a cutoff cannot reach 0 FP.
        auto_set_min_conf=0.85,
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
    # Trusted annotation sources. Their page-image caches are intentionally
    # cache-only: do not silently train on a different print merely because it
    # shares the same Quran text or line layout. Put verified page JPEGs under
    # the configured directory before sampling crops.
    'المدينة الجديد': EditionSpec(
        id='madinah_1441',
        mushaf_version='المدينة الجديد',
        layout_db=DIGITAL_KHATT_LAYOUT_DATABASE,
        word_space='qpc',
        script_db=BAHRAIN_LAYOUT_DATABASE,
        min_page=1,
        max_page=604,
        image_kind='cache',
        page_cache_dir=str(PAGES_ROOT / 'madinah_1441'),
        text_top=0.10,
        text_bottom=0.92,
    ),
    'المدينة القديم': EditionSpec(
        id='madinah_1405',
        mushaf_version='المدينة القديم',
        layout_db=QPC_V1_LAYOUT_DATABASE,
        word_space='qpc',
        script_db=BAHRAIN_LAYOUT_DATABASE,
        min_page=1,
        max_page=604,
        image_kind='cache',
        page_cache_dir=str(PAGES_ROOT / 'madinah_1405'),
        text_top=0.10,
        text_bottom=0.92,
    ),
    'الأزهر': EditionSpec(
        id='azhar',
        mushaf_version='الأزهر',
        layout_db=AZHAR_LAYOUT_DATABASE,
        word_space='shemrly',
        script_db=QURAN_SCRIPT_DATABASE,
        min_page=AZHAR_LAYOUT_MIN_PAGE,
        max_page=AZHAR_LAYOUT_MAX_PAGE,
        image_kind='cache',
        page_cache_dir=str(PAGES_ROOT / 'azhar'),
        text_top=0.11,
        text_bottom=0.90,
    ),
}

TRUSTED_WAQF_EDITIONS: tuple[str, ...] = (
    'الشمرلي', 'المدينة الجديد', 'المدينة القديم', 'الأزهر',
)
TARGET_WAQF_EDITIONS: tuple[str, ...] = ('البحرين', 'المساحة')

WAQF_DB = MUSHAF_WAQF_DATABASE


def resolve_proposal_mode(
    edition_key: str,
    proposal_mode: str | None = None,
) -> str:
    """Return an explicit override, or the edition's default proposal mode."""
    resolved = proposal_mode or EDITIONS[edition_key].default_proposal_mode
    if resolved not in PROPOSAL_MODES:
        raise ValueError("proposal_mode must be 'narrow' or 'hybrid'")
    return resolved


def resolve_auto_set_min_conf(
    edition_key: str,
    min_conf: float | None = None,
) -> float:
    """Return an explicit override, or the edition's draft-write threshold."""
    if min_conf is not None:
        return float(min_conf)
    return float(EDITIONS[edition_key].auto_set_min_conf)


def classify_mark_trust(confidence: float, auto_set_min_conf: float) -> str:
    """``auto-set`` is trusted enough to draft; ``review`` needs a human."""
    if float(confidence) >= float(auto_set_min_conf):
        return 'auto-set'
    return 'review'


def split_marks_by_trust(
    marks: list[dict],
    auto_set_min_conf: float,
) -> tuple[list[dict], list[dict]]:
    """Partition detections into trusted draft writes vs review candidates."""
    trusted: list[dict] = []
    review: list[dict] = []
    for mark in marks:
        if classify_mark_trust(mark.get('confidence') or 0.0, auto_set_min_conf) == 'auto-set':
            trusted.append(mark)
        else:
            review.append(mark)
    return trusted, review
