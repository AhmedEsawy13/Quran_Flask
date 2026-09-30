"""Feature modules. Importing a module attaches its routes to a blueprint.

``load_routes()`` imports every module once, before the blueprints are
registered on an app. Order is significant only where one module builds on
another (e.g. the research routes reuse the breathing blueprint).
"""
from importlib import import_module

ROUTE_MODULES = (
    # core_bp — shared text, search, audio, mushaf pages, SEO
    'modules.quran_api',
    'modules.layouts',
    'modules.seo',
    # reading_bp / memorize_bp / breathing_bp — the public product pages
    'modules.reading',
    'modules.memorize',
    'modules.breathing',
    'modules.waqf_research',
    # editor_bp — write-capable and internal review tools (gated by ENABLE_EDITOR)
    'modules.editor',
    'modules.waqf_mark_review',
    'modules.quran_integrity_review',
    'modules.cv_waqf_ui',
    'modules.activity',
    'modules.azhar_layout',
    'modules.layout_studio',
    'modules.font_lab',
    'modules.classical_review',
    'modules.tawjih_review',
)


def load_routes():
    for name in ROUTE_MODULES:
        import_module(name)
