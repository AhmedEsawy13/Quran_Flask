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
    lines_per_page: int
    font_name: str
    undo_table: str
    progress_table: str
    payload_kind: str            # how to build page JSON (azhar for now)
    ref_archive_id: str | None
    ref_label_ar: str
    ref_leaf_offset: int         # archive leaf = page + offset (Azhar: -1)
    closed_pages: tuple[ClosedPageRule, ...] = ()
    storage_key: str = ''        # localStorage prefix

    def __post_init__(self):
        if not self.storage_key:
            object.__setattr__(self, 'storage_key', f'layout_studio_{self.id}_page')

    @property
    def page_count(self) -> int:
        return self.max_page - self.min_page + 1

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

    def client_config(self) -> dict:
        """JSON-safe config injected into the studio page."""
        return {
            'id': self.id,
            'nameAr': self.name_ar,
            'subtitleAr': self.subtitle_ar,
            'mushafVersion': self.mushaf_version,
            'wordSpace': self.word_space,
            'minPage': self.min_page,
            'maxPage': self.max_page,
            'linesPerPage': self.lines_per_page,
            'fontName': self.font_name,
            'apiBase': f'/api/layout-studio/{self.id}',
            'pageByAyahBase': (
                '/api/azhar/page-by-ayah' if self.payload_kind == 'azhar' else None
            ),
            'storageKey': self.storage_key,
            'metaLabel': (
                f'{self.mushaf_version} · {self.lines_per_page} سطراً · '
                f'كلمة {_word_space_ar(self.word_space)} · {self.font_name}'
            ),
            'ref': {
                'id': self.ref_archive_id,
                'label': self.ref_label_ar,
                'leafOffset': self.ref_leaf_offset,
            } if self.ref_archive_id else None,
            'closedPages': [asdict(r) for r in self.closed_pages],
            'shortPages': {
                str(r.page): r.target_lines for r in self.closed_pages
            },
        }


def _word_space_ar(space: str) -> str:
    return {
        'shemrly': 'الشمرلي',
        'qpc': 'QPC',
    }.get(space, space)


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

AZHAR = LayoutEdition(
    id='azhar',
    name_ar='مصحف الأزهر',
    subtitle_ar=(
        'طابق السطور مع المطبوع جنباً إلى جنب. البذرة من تخطيط الشمرلي '
        '(١٥ سطراً؛ الفاتحة ٦ أسطر بالبسملة، أول البقرة ٥). '
        'اسحب كلمة إلى سطر لتغيير الحد.'
    ),
    mushaf_version='الأزهر',
    layout_db=AZHAR_LAYOUT_DATABASE,
    seed_source_db=SHAMARLY_LAYOUT_DATABASE,
    word_space='shemrly',
    script_db=QURAN_SCRIPT_DATABASE,
    min_page=AZHAR_LAYOUT_MIN_PAGE,
    max_page=AZHAR_LAYOUT_MAX_PAGE,
    lines_per_page=15,
    font_name='Amiri Quran',
    undo_table='azhar_layout_undo',
    progress_table='azhar_layout_progress',
    payload_kind='azhar',
    ref_archive_id='shamarlyshamarly',
    ref_label_ar='مرجع الشمرلي',
    ref_leaf_offset=-1,
    closed_pages=(_FATIHA, _BAQARAH_OPEN),
    storage_key='az_layout_page',
)

_REGISTRY: dict[str, LayoutEdition] = {
    AZHAR.id: AZHAR,
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
            'lines_per_page': e.lines_per_page,
            'font_name': e.font_name,
            'min_page': e.min_page,
            'max_page': e.max_page,
            'studio_path': f'/layout-studio/{e.id}',
            'short_pages': {
                str(r.page): r.target_lines for r in e.closed_pages
            },
        }
        for e in list_editions()
    ]


def known_edition_ids() -> Iterable[str]:
    return _REGISTRY.keys()
