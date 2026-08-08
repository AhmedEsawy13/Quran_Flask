"""Shared cache-policy classification for HTTP responses and route contracts."""
from __future__ import annotations


EDITOR_PRIVATE_PATH_PREFIXES = (
    '/mushaf-editor',
    '/layout-studio',
    '/azhar-layout',
    '/azhar-waqf-review',
    '/quran-integrity-review',
    '/font-lab',
    '/cv-waqf',
)

NO_STORE_API_PREFIXES = (
    '/api/mushaf-editor/',
    '/api/azhar-layout/',
    '/api/azhar-waqf-review/',
    '/api/quran-integrity/',
    '/api/layout-studio/',
    '/api/classical-review/',
    '/api/cv-waqf/',
    '/api/waqf-research/',
)


def is_editor_private_path(path: str, blueprint: str | None) -> bool:
    return blueprint == 'editor' or path.startswith(EDITOR_PRIVATE_PATH_PREFIXES)


def api_success_cache_class(path: str, blueprint: str | None) -> str:
    """Return the stable cache class for a successful API response."""
    if is_editor_private_path(path, blueprint):
        return 'no-store'
    if path.startswith(NO_STORE_API_PREFIXES):
        return 'no-store'
    return 'public-1h'
