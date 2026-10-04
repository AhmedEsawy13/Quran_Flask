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
    QATAR_LAYOUT_DATABASE,
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

# Fixed-size above-word band fed to the strip CNN (H, W), not a 48×48 CC crop.
STRIP_HEIGHT = 32
STRIP_WIDTH = 64

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
    # After attach, keep a mark only if الأزهر has some waqf on that word.
    # Occupancy only — ignore the Azhar glyph. FP cut, not a classifier.
    # On for البحرين only; other editions stay off.
    azhar_seat_prior: bool = False
    # Which editions' printed stops define the allowed seats when the prior is
    # on. Never the edition's own column (checked in ``__post_init__``).
    seat_prior_editions: tuple[str, ...] = ('الأزهر',)
    # Measure the text rows and word cuts from each page's ink
    # (``geometry.py``) instead of trusting the fixed ``text_*`` fractions and
    # letter-count widths, which are hand-tuned per print. The fractions stay
    # as the fallback when a page gives too little evidence.
    measured_geometry: bool = False
    # Use another edition's model until this print has its own. Explicit and
    # one hop only, so a transfer is visible in the registry and in the detect
    # payload instead of hiding in a path lookup.
    model_fallback: str | None = None
    # Re-seat a prior-rejected mark on an adjacent occupied word of its line
    # (azhar_prior.reattach_rejected_marks). Off unless measured to help.
    prior_reattach: bool = False
    # Recto/verso prints sit at different heights. When set, EVEN pages use
    # this (text_top, text_bottom) and odd pages the plain text_* fields.
    text_band_even: tuple[float, float] | None = None
    # Erase the page frame and everything outside its inner rule before any
    # detection (preprocess.strip_frame). For prints whose frame confuses the
    # text-extent and candidate steps.
    strip_frame: bool = False
    # Re-derive line breaks from the scan's OCR + geometry instead of trusting
    # an unreviewed layout (relayout.py). Falls back to the layout when unsure.
    ocr_relayout: bool = False

    def __post_init__(self) -> None:
        if self.azhar_seat_prior and self.mushaf_version in self.seat_prior_editions:
            raise ValueError(
                f'{self.id}: the seat prior cannot include the edition\'s own '
                f'column ({self.mushaf_version}); it could not find anything '
                'the prior did not already contain'
            )

    @property
    def seat_convention(self) -> str:
        """How a word's stop ROI is placed: ``measured`` follows the ink
        grid convention of ``geometry.py``; ``legacy`` is the older
        above-the-box band the Shamarly crops were sampled with."""
        return 'measured' if self.measured_geometry else 'legacy'

    def band_for_page(self, page: int | None) -> tuple[float, float]:
        """``(text_top, text_bottom)`` for ``page`` (parity-aware)."""
        if self.text_band_even is not None and page is not None and page % 2 == 0:
            return self.text_band_even
        return self.text_top, self.text_bottom

    @property
    def model_path(self) -> Path:
        """Where this edition's own glyph model lives (may not exist yet)."""
        return ROOT / 'models' / f'waqf_glyph_{self.id}.onnx'

    @property
    def strip_model_path(self) -> Path:
        """Where this edition's own above-word strip net lives (may not exist)."""
        return ROOT / 'models' / f'waqf_strip_{self.id}.onnx'


# Seat prior for prints that follow the Madinah layout: Azhar (the widest
# printed-stop set) plus both Madinah editions. Whole-book, against each
# print's own column, this recovers all 12 of Bahrain's Azhar-empty stops and
# 24 of Qatar's for +9 / +7 false marks (allowed seats 4870 → 4922). Adding
# الشمرلي gains 2 more on Qatar; الكويت grows the set by 379 for almost nothing.
SEAT_PRIOR_AZHAR_MADINAH: tuple[str, ...] = (
    'الأزهر', 'المدينة الجديد', 'المدينة القديم',
)

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
        # Word-level Azhar occupancy (word_index, not token_index):
        # 31→6 FP / 217→213 correct on the 44-page hand set.
        # 12 known Bahrain-only DB seats will be missed.
        azhar_seat_prior=True,
        seat_prior_editions=SEAT_PRIOR_AZHAR_MADINAH,
        # 213 hand-labelled pages, gated MLP + hybrid, min_conf 0.55:
        #   with the Azhar prior   429→430 correct, FP 15→13
        #   without the prior      434→435 correct, FP 40→31
        # mark box → owning word 95.9%→96.7% (evaluate-candidates).
        measured_geometry=True,
    ),
    # Same 15-line QPC layout as Madinah/Bahrain, different frame and margins.
    # Scans are cached at 2000px; ensure_page_image derives the 1024px copy.
    # No Qatar-only model: it resolves to the multi-print model, which was
    # trained on detector-window crops labelled by Madinah-family consensus.
    # 50 unseen pages vs that consensus: 85.7% exact, 91% precision.
    'قطر': EditionSpec(
        id='qatar',
        mushaf_version='قطر',
        layout_db=QATAR_LAYOUT_DATABASE,
        word_space='qpc',
        script_db=BAHRAIN_LAYOUT_DATABASE,
        min_page=1,
        max_page=604,
        image_kind='cache',
        page_cache_dir=str(PAGES_ROOT / 'qatar'),
        # Slot-box convention (what ``geometry.fit_line_grid`` expects), from
        # ``calibrate-geometry``: the ink block is 0.155..0.865, but the slot
        # box sits ~0.56 line higher. Using the ink extent here put the true
        # alignment at the edge of the search window and let 10% of pages
        # lock onto the neighbouring line.
        text_top=0.1284,
        text_bottom=0.8526,
        default_proposal_mode='hybrid',
        auto_set_min_conf=0.85,
        # Without the prior the detector alone fires on ~12% of empty words
        # (758 false positives on 6.2k); with it, 2. Same trade-off as
        # Bahrain: a real Qatar-only stop on an Azhar-empty word is dropped.
        azhar_seat_prior=True,
        seat_prior_editions=SEAT_PRIOR_AZHAR_MADINAH,
        measured_geometry=True,
    ),
    # Kuwait (الكويت الحديث): 15-line QPC v1 layout, 604 pages, same scan the
    # editor shows (Archive item kweat--h4794794946945969, page N = leaf N+3).
    # Geometry measured with ``calibrate-geometry`` (30 pages across the book:
    # 0.0637/0.8406, stray 0, p5-p95 spread -0.11..+0.12 line; an independent
    # 36-page sample of p3-108 gave 0.0633/0.8423). Leaf offset verified by
    # the printed folios (p5, p50, p300, p604) and Fatiha/Baqara at p1/p2.
    # Hybrid + the Azhar+Madinah seat prior (see README "The seat prior"):
    # 40 unseen pages, 86.7% exact vs the Kuwait DB column, 7 extras that are
    # all real stops the DB lacks. Narrow finds 8/89; without the prior ~15
    # false marks per page. The prior covers 99.66% of Kuwait's waqf seats
    # (the 363 ركوع rows are section markers, not waqf).
    'الكويت': EditionSpec(
        id='kuwait',
        mushaf_version='الكويت',
        layout_db=QPC_V1_LAYOUT_DATABASE,
        word_space='qpc',
        script_db=BAHRAIN_LAYOUT_DATABASE,
        min_page=1,
        max_page=604,
        image_kind='archive',
        archive_id='kweat--h4794794946945969',
        leaf_offset=3,
        page_cache_dir=str(PAGES_ROOT / 'kuwait'),
        text_top=0.0637,
        text_bottom=0.8406,
        # Inner frame rule sits at ~0.138 / 0.867 (geometry.text_x_bounds);
        # the default 0.06 / 0.94 let hybrid proposals fire on the ornamented
        # border. 40 pages: wrong 24 -> 20, match 228 -> 230.
        text_left=0.135,
        text_right=0.868,
        default_proposal_mode='hybrid',
        auto_set_min_conf=0.85,
        azhar_seat_prior=True,
        seat_prior_editions=SEAT_PRIOR_AZHAR_MADINAH,
        # Own model: round-2 kuwait_s1 (models/cloud2, installed as
        # models/waqf_glyph_kuwait*). 100 held-out pages: 97.7% exact on the
        # corrected column / 95.8% on the pre-review one (3-seed mean 96.4 / 94.6).
        # 60 pages vs the synced column: missing 17 -> 11, +3 extra.
        prior_reattach=True,
        measured_geometry=True,
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
        # Recto/verso differ by ~half a line; calibrate-geometry per parity on
        # FRAME-STRIPPED pages (15 pages each, 12 lines, spread +-0.13 line):
        # odd 0.1771/0.7902, even 0.1487/0.7648. The first calibration ran on
        # raw pages, where the header line above the frame counted as a text
        # row, so every word box sat one line too high (hand labels: marks
        # 1.5 line-heights below their word's box top instead of 0.51).
        text_top=0.1771,
        text_bottom=0.7902,
        text_band_even=(0.1487, 0.7648),
        strip_frame=True,
        ocr_relayout=True,
        # WIP: vertical band only. Horizontal frame bounds are not parity-clean
        # yet and Mesaha word positions use the Shemrly word space, so marks
        # cannot be compared with or filtered by the QPC-indexed columns.
        default_proposal_mode='hybrid',
        measured_geometry=True,
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

# Per-edition model locations follow ``EditionSpec.model_path`` /
# ``strip_model_path``; nothing is hand-listed, so adding an edition to
# EDITIONS is enough. Files are optional and checked at use time.
EDITION_MODEL_PATHS: dict[str, Path] = {
    key: spec.model_path for key, spec in EDITIONS.items()
}
EDITION_STRIP_MODEL_PATHS: dict[str, Path] = {
    key: spec.strip_model_path for key, spec in EDITIONS.items()
}


# Trained on detector-window crops from several prints (see
# ``candidate_crops``), so a print without its own model can use it directly.
# Optional; when absent the legacy ``waqf_glyph.onnx`` path is unchanged.
SHARED_MULTIPRINT_MODEL_PATH = ROOT / 'models' / 'waqf_glyph_multiprint.onnx'


def resolve_edition_model(edition_key: str) -> tuple[Path | None, str | None]:
    """Best model for an edition, and where it came from.

    Order: the edition's own model → the explicit ``model_fallback`` edition's
    → the multi-print model → ``(None, None)`` (legacy shared
    ``waqf_glyph.onnx``). The label is ``own``, ``transfer:<edition>`` or
    ``multiprint`` so a detect payload can say whether a transfer happened.
    """
    spec = EDITIONS[edition_key]
    if spec.model_path.is_file():
        return spec.model_path, 'own'
    fallback = spec.model_fallback
    if fallback and EDITIONS[fallback].model_path.is_file():
        return EDITIONS[fallback].model_path, f'transfer:{fallback}'
    if SHARED_MULTIPRINT_MODEL_PATH.is_file():
        return SHARED_MULTIPRINT_MODEL_PATH, 'multiprint'
    return None, None


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


def resolve_azhar_seat_prior(
    edition_key: str,
    azhar_prior: bool | None = None,
) -> bool:
    """Return an explicit override, or the edition's Azhar occupancy flag."""
    if azhar_prior is not None:
        return bool(azhar_prior)
    return bool(EDITIONS[edition_key].azhar_seat_prior)


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
