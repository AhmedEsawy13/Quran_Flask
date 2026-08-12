"""Layout Studio edition registry.

Milestone C: one registered edition (azhar). Future mushafs add another
LayoutEdition entry; routes under /layout-studio/<id> stay the same.

Azhar short-page specials (physical print, not Shemrly 8-line seed):
  • سورة الفاتحة (page 2): 6 lines including البسملة
  • أول البقرة (page 3): 5 lines
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Iterable

from core.config import (
    AZHAR_LAYOUT_DATABASE,
    AZHAR_LAYOUT_MAX_PAGE,
    AZHAR_LAYOUT_MIN_PAGE,
    BAHRAIN_LAYOUT_DATABASE,
    BAHRAIN_REF_PDF_URL,
    MESAHA_ARCHIVE_ID,
    MESAHA_LAYOUT_DATABASE,
    MESAHA_LAYOUT_MAX_PAGE,
    MESAHA_LAYOUT_MIN_PAGE,
    QPC_V2_LAYOUT_DATABASE,
    QURAN_SCRIPT_DATABASE,
    SHAMARLY_LAYOUT_DATABASE,
)


@dataclass(frozen=True)
class ClosedPageRule:
    """Words that must stay on one short page (cannot cascade into the next)."""
    page: int
    ayah_first: int
    ayah_last: int
    # First word of the following page after a seal/restore.
    next_page_first_word: int
    next_page: int
    target_lines: int  # total lines on the page (headers + ayah)


@dataclass(frozen=True)
class LayoutProfile:
    """Geometry rules shared by every layout-studio edition.

    ``page_end_mode='ayah'`` keeps the existing Quran word range of each page
    fixed while line breaks are edited. This matches Madinah/Qatar layouts:
    pages normally end at an ayah, while unavoidable long-ayah splits already
    present in the source remain intact. ``continuous`` lets edits move the
    page boundary inside the same surah, as Shemrly/Azhar layouts do.

    Header values are physical page slots reserved by one logical row. A value
    of zero hides that optional row; values above one let a future print give a
    banner more vertical space without duplicating its text.
    """

    lines_per_page: int
    page_end_mode: str
    surah_name_lines: int = 1
    surah_info_lines: int = 0
    basmallah_lines: int = 1

    @property
    def full_banner_lines(self) -> int:
        return (
            int(self.surah_name_lines)
            + int(self.surah_info_lines)
            + int(self.basmallah_lines)
        )

    def as_client_dict(self) -> dict:
        payload = asdict(self)
        payload['full_banner_lines'] = self.full_banner_lines
        return payload


@dataclass(frozen=True)
class LayoutEdition:
    id: str
    name_ar: str
    subtitle_ar: str
    mushaf_version: str          # waqf overlay key, e.g. الأزهر
    layout_db: str
    seed_source_db: str | None
    word_space: str              # shemrly | qpc
    script_db: str
    min_page: int
    max_page: int
    profile: LayoutProfile
    font_name: str
    undo_table: str
    progress_table: str
    payload_kind: str            # how to build page JSON (azhar for now)
    ref_archive_id: str | None
    ref_label_ar: str
    ref_leaf_offset: int         # archive leaf = page + offset (Azhar: -1)
    ref_image_template: str | None
    ref_open_template: str | None
    ref_pdf_url: str | None = None
    # 1-based PDF page = mushaf_page + offset (Bahrain islamhouse: +5).
    ref_pdf_page_offset: int = 0
    # Some working editions outgrow their temporary printed reference.
    ref_max_page: int | None = None
    closed_pages: tuple[ClosedPageRule, ...] = ()
    line_count_overrides: tuple[tuple[int, int], ...] = ()
    storage_key: str = ''        # localStorage prefix
    cloud_enabled: bool = False
    line_page_transfer: bool = False
    header_down_cascade: bool = False
    protected_trailing_lines: tuple[tuple[int, int], ...] = ()

    def __post_init__(self):
        if self.word_space not in {'shemrly', 'qpc'}:
            raise ValueError(f'unsupported word ID space: {self.word_space}')
        if not self.storage_key:
            object.__setattr__(self, 'storage_key', f'layout_studio_{self.id}_page')

    @property
    def word_id_space(self) -> str:
        """Stable namespace label; IDs are never interchangeable across labels."""
        return (
            'qpc-layout-global-v1'
            if self.word_space == 'qpc'
            else 'quran-script-stable-v1'
        )

    @property
    def page_count(self) -> int:
        return self.max_page - self.min_page + 1

    @property
    def lines_per_page(self) -> int:
        """Compatibility alias for callers that predate layout profiles."""
        return int(self.profile.lines_per_page)

    @property
    def closed_page(self) -> ClosedPageRule | None:
        """First closed-page rule (compat for Fatiha-centric callers)."""
        return self.closed_pages[0] if self.closed_pages else None

    def closed_rule_for(self, page_number: int) -> ClosedPageRule | None:
        page = int(page_number)
        for rule in self.closed_pages:
            if int(rule.page) == page:
                return rule
        return None

    def line_count_for(self, page_number: int) -> int:
        rule = self.closed_rule_for(page_number)
        if rule:
            return int(rule.target_lines)
        page = int(page_number)
        for configured_page, lines in self.line_count_overrides:
            if int(configured_page) == page:
                return int(lines)
        return int(self.profile.lines_per_page)

    def protected_trailing_count_for(self, page_number: int) -> int:
        page = int(page_number)
        for configured_page, count in self.protected_trailing_lines:
            if int(configured_page) == page:
                return max(0, int(count))
        return 0

    def client_config(self, profile: LayoutProfile | None = None) -> dict:
        """JSON-safe config injected into the studio page."""
        effective = profile or self.profile
        return {
            'id': self.id,
            'nameAr': self.name_ar,
            'subtitleAr': self.subtitle_ar,
            'mushafVersion': self.mushaf_version,
            'wordSpace': self.word_space,
            'wordIdSpace': self.word_id_space,
            'minPage': self.min_page,
            'maxPage': self.max_page,
            'linesPerPage': effective.lines_per_page,
            'profile': effective.as_client_dict(),
            'profilePresets': public_profile_presets(),
            'fontName': self.font_name,
            'apiBase': f'/api/layout-studio/{self.id}',
            'pageByAyahBase': (
                f'/api/layout-studio/{self.id}/page-by-ayah'
            ),
            'storageKey': self.storage_key,
            'metaLabel': (
                f'{self.mushaf_version} · {effective.lines_per_page} سطراً · '
                f'كلمة {_word_space_ar(self.word_space)} · {self.font_name}'
            ),
            'ref': (
                {
                    'type': (
                        'pdf' if self.ref_pdf_url
                        else ('local' if self.ref_image_template else 'archive')
                    ),
                    'id': self.ref_archive_id,
                    'label': self.ref_label_ar,
                    'leafOffset': self.ref_leaf_offset,
                    'imageTemplate': self.ref_image_template,
                    'openTemplate': self.ref_open_template,
                    'pdfUrl': self.ref_pdf_url,
                    'pdfPageOffset': int(self.ref_pdf_page_offset),
                    'maxPage': self.ref_max_page,
                }
                if self.ref_archive_id or self.ref_image_template or self.ref_pdf_url
                else None
            ),
            'closedPages': [asdict(r) for r in self.closed_pages],
            'shortPages': {
                **{
                    str(page): int(lines)
                    for page, lines in self.line_count_overrides
                },
                **{
                    str(r.page): r.target_lines for r in self.closed_pages
                },
            },
            'linePageTransfer': bool(self.line_page_transfer),
            'headerDownCascade': bool(self.header_down_cascade),
            'protectedTrailingLines': {
                str(page): int(count)
                for page, count in self.protected_trailing_lines
            },
        }


def _word_space_ar(space: str) -> str:
    return {
        'shemrly': 'الشمرلي',
        'qpc': 'QPC',
    }.get(space, space)


# The cases already present in data/*.db. These are editor choices, not guesses:
# Madinah/Qatar have a hard page word range; Shemrly/Azhar are continuous.
PROFILE_PRESETS: dict[str, dict] = {
    'azhar': {
        'id': 'azhar',
        'name_ar': 'الأزهر',
        'description_ar': '١٥ سطراً، تدفّق مستمر، وراية السورة ٣ أسطر',
        'profile': LayoutProfile(
            lines_per_page=15,
            page_end_mode='continuous',
            surah_name_lines=1,
            surah_info_lines=1,
            basmallah_lines=1,
        ),
        'short_pages': {'2': 6, '3': 5},
    },
    'madinah_qatar': {
        'id': 'madinah_qatar',
        'name_ar': 'المدينة / قطر',
        'description_ar': (
            '١٥ سطراً، حدود الصفحة ثابتة وموجّهة لنهاية الآية، '
            'واسم السورة مع البسملة سطران'
        ),
        'profile': LayoutProfile(
            lines_per_page=15,
            page_end_mode='ayah',
            surah_name_lines=1,
            surah_info_lines=0,
            basmallah_lines=1,
        ),
        'short_pages': {'1': 8, '2': 8},
    },
    'shemrly': {
        'id': 'shemrly',
        'name_ar': 'الشمرلي',
        'description_ar': (
            '١٥ سطراً اسميّاً، تدفّق مستمر، وراية من سطرين؛ '
            'المصدر الحالي يتضمن صفحات فعلية من ١٢–١٥ سطراً'
        ),
        'profile': LayoutProfile(
            lines_per_page=15,
            page_end_mode='continuous',
            surah_name_lines=1,
            surah_info_lines=0,
            basmallah_lines=1,
        ),
        'short_pages': {'2': 8, '3': 8},
    },
    'mesaha': {
        'id': 'mesaha',
        'name_ar': 'المساحة الأميرية',
        'description_ar': (
            '١٢ سطراً، تدفّق مستمر، وراية السورة: اسم + معلومات + بسملة'
        ),
        'profile': LayoutProfile(
            lines_per_page=12,
            page_end_mode='continuous',
            surah_name_lines=1,
            surah_info_lines=1,
            basmallah_lines=1,
        ),
        'short_pages': {'2': 8, '3': 8},
    },
}


def public_profile_presets() -> list[dict]:
    out = []
    for preset in PROFILE_PRESETS.values():
        out.append({
            'id': preset['id'],
            'name_ar': preset['name_ar'],
            'description_ar': preset['description_ar'],
            'profile': preset['profile'].as_client_dict(),
            'short_pages': dict(preset.get('short_pages') or {}),
        })
    return out


# Shemrly word ranges kept on the short opening pages after reshape.
_FATIHA = ClosedPageRule(
    page=2,
    ayah_first=8,
    ayah_last=38,
    next_page_first_word=45,
    next_page=3,
    target_lines=6,  # surah_name + basmallah + 4 ayah
)
_BAQARAH_OPEN = ClosedPageRule(
    page=3,
    ayah_first=45,
    ayah_last=76,
    next_page_first_word=77,
    next_page=4,
    target_lines=5,  # surah_name + basmallah + 3 ayah
)
_MESAHA_FATIHA = ClosedPageRule(
    page=2,
    ayah_first=8,
    ayah_last=38,
    next_page_first_word=45,
    next_page=3,
    target_lines=8,  # surah name + info + basmallah + 5 ayah
)
_MESAHA_BAQARAH_OPEN = ClosedPageRule(
    page=3,
    ayah_first=45,
    ayah_last=76,
    next_page_first_word=77,
    next_page=4,
    target_lines=8,  # surah name + info + basmallah + 5 ayah
)

AZHAR = LayoutEdition(
    id='azhar',
    name_ar='مصحف الأزهر',
    subtitle_ar=(
        'طابق السطور مع المطبوع جنباً إلى جنب. البذرة من تخطيط الشمرلي '
        '(١٥ سطراً دائماً؛ راية السورة: اسم + معلومات + بسملة = ٣ من ١٥؛ '
        'الفاتحة ٦، أول البقرة ٥). '
        'اسحب كلمة إلى سطر لتغيير الحد.'
    ),
    mushaf_version='الأزهر',
    layout_db=AZHAR_LAYOUT_DATABASE,
    seed_source_db=SHAMARLY_LAYOUT_DATABASE,
    word_space='shemrly',
    script_db=QURAN_SCRIPT_DATABASE,
    min_page=AZHAR_LAYOUT_MIN_PAGE,
    max_page=AZHAR_LAYOUT_MAX_PAGE,
    profile=PROFILE_PRESETS['azhar']['profile'],
    font_name='Amiri Quran',
    undo_table='azhar_layout_undo',
    progress_table='azhar_layout_progress',
    payload_kind='azhar',
    ref_archive_id='shamarlyshamarly',
    ref_label_ar='مرجع الشمرلي',
    ref_leaf_offset=-1,
    ref_image_template=None,
    ref_open_template=None,
    # The temporary Shamarly scan has 522 leaves; Azhar work continues to 525.
    ref_max_page=522,
    closed_pages=(_FATIHA, _BAQARAH_OPEN),
    storage_key='az_layout_page',
    cloud_enabled=True,
    line_page_transfer=True,
    header_down_cascade=True,
    protected_trailing_lines=(
        (494, 2),
        (516, 2),
        (518, 2),
        (521, 2),
        (522, 2),
    ),
)

BAHRAIN = LayoutEdition(
    id='bahrain',
    name_ar='مصحف البحرين',
    subtitle_ar=(
        'طابق مصحف البحرين المطبوع مع تخطيط المدينة ١٤٢١ وخط Digital Khatt. '
        'حدود كل صفحة ثابتة، ويمكن تعديل حدود السطور داخلها بأمان.'
    ),
    mushaf_version='البحرين',
    layout_db=BAHRAIN_LAYOUT_DATABASE,
    seed_source_db=QPC_V2_LAYOUT_DATABASE,
    word_space='qpc',
    script_db=BAHRAIN_LAYOUT_DATABASE,
    min_page=1,
    max_page=604,
    profile=PROFILE_PRESETS['madinah_qatar']['profile'],
    font_name='Digital Khatt',
    undo_table='bahrain_layout_undo',
    progress_table='bahrain_layout_progress',
    payload_kind='canonical_qpc',
    ref_archive_id=None,
    ref_label_ar='مرجع مصحف البحرين',
    ref_leaf_offset=0,
    ref_image_template=None,
    ref_open_template=None,
    # Remote islamhouse PDF — rendered client-side via AtharPdfRef (no local cache).
    ref_pdf_url=BAHRAIN_REF_PDF_URL,
    ref_pdf_page_offset=5,
    line_count_overrides=((1, 8), (2, 8)),
    storage_key='layout_studio_bahrain_page',
    cloud_enabled=True,
)

MESAHA = LayoutEdition(
    id='mesaha',
    name_ar='مصحف المساحة الأميرية',
    subtitle_ar=(
        'بذرة آلية محافظة من طبعة ١٣٤٢هـ: النص القرآني كامل ومرتب بلا '
        'تكرار، وحدود السطور المستخرجة مرفقة بدرجة ثقة. طابق كل صفحة '
        'بالصورة المطبوعة قبل اعتمادها.'
    ),
    mushaf_version='المساحة الأميرية',
    layout_db=MESAHA_LAYOUT_DATABASE,
    seed_source_db=None,
    word_space='shemrly',
    script_db=QURAN_SCRIPT_DATABASE,
    min_page=MESAHA_LAYOUT_MIN_PAGE,
    max_page=MESAHA_LAYOUT_MAX_PAGE,
    profile=PROFILE_PRESETS['mesaha']['profile'],
    font_name='Amiri Quran',
    undo_table='mesaha_layout_undo',
    progress_table='mesaha_layout_progress',
    payload_kind='canonical_script',
    ref_archive_id=MESAHA_ARCHIVE_ID,
    ref_label_ar='مصحف المساحة الأميرية ١٣٤٢هـ',
    # Layout page N is Archive leaf N-1 (Archive leaves are zero-based).
    ref_leaf_offset=-1,
    ref_image_template=None,
    ref_open_template=None,
    closed_pages=(_MESAHA_FATIHA, _MESAHA_BAQARAH_OPEN),
    storage_key='layout_studio_mesaha_page',
    cloud_enabled=True,
)

_REGISTRY: dict[str, LayoutEdition] = {
    AZHAR.id: AZHAR,
    BAHRAIN.id: BAHRAIN,
    MESAHA.id: MESAHA,
}


def get_edition(edition_id: str) -> LayoutEdition | None:
    if not edition_id:
        return None
    return _REGISTRY.get(str(edition_id).strip().lower())


def require_edition(edition_id: str) -> LayoutEdition:
    edition = get_edition(edition_id)
    if edition is None:
        raise KeyError(edition_id)
    return edition


def list_editions() -> list[LayoutEdition]:
    return list(_REGISTRY.values())


def default_edition() -> LayoutEdition:
    return AZHAR


def public_editions() -> list[dict]:
    return [
        {
            'id': e.id,
            'name_ar': e.name_ar,
            'word_space': e.word_space,
            'word_id_space': e.word_id_space,
            'lines_per_page': e.lines_per_page,
            'profile': e.profile.as_client_dict(),
            'font_name': e.font_name,
            'min_page': e.min_page,
            'max_page': e.max_page,
            'studio_path': f'/layout-studio/{e.id}',
            'short_pages': {
                **{
                    str(page): int(lines)
                    for page, lines in e.line_count_overrides
                },
                **{
                    str(r.page): r.target_lines for r in e.closed_pages
                },
            },
            'protected_trailing_lines': {
                str(page): int(count)
                for page, count in e.protected_trailing_lines
            },
        }
        for e in list_editions()
    ]


def known_edition_ids() -> Iterable[str]:
    return _REGISTRY.keys()
