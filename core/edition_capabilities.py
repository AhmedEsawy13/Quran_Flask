"""Canonical capabilities for cloud-backed mushaf editor editions.

These values describe application behavior, not SQLite columns.  Compatibility
sets in :mod:`core.config` are projections of this registry so existing callers
keep working while validation moves to explicit capabilities.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class EditorEditionCapability:
    edition: str
    editor_enabled: bool = True
    cloud_draft_enabled: bool = True
    publish_enabled: bool = True
    public_read_enabled: bool = True

    def as_database_row(self) -> dict[str, object]:
        return asdict(self)


EDITOR_EDITION_CAPABILITIES: tuple[EditorEditionCapability, ...] = (
    EditorEditionCapability('قطر'),
    EditorEditionCapability('الكويت'),
    EditorEditionCapability('البحرين'),
)

_BY_EDITION = {
    capability.edition: capability
    for capability in EDITOR_EDITION_CAPABILITIES
}


def get_editor_edition_capability(
    edition: str | None,
) -> EditorEditionCapability | None:
    return _BY_EDITION.get((edition or '').strip())


def editions_with(capability: str) -> frozenset[str]:
    """Return edition IDs for which a named boolean capability is enabled."""
    if capability not in {
        'editor_enabled',
        'cloud_draft_enabled',
        'publish_enabled',
        'public_read_enabled',
    }:
        raise ValueError(f'unknown edition capability: {capability}')
    return frozenset(
        row.edition
        for row in EDITOR_EDITION_CAPABILITIES
        if getattr(row, capability)
    )


def database_capability_rows() -> list[dict[str, object]]:
    """Expected Supabase rows, sorted for deterministic readiness checks."""
    return [
        row.as_database_row()
        for row in sorted(
            EDITOR_EDITION_CAPABILITIES,
            key=lambda capability: capability.edition,
        )
    ]
