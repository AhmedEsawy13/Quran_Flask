"""Cloud edition support is explicit and independent of legacy DB columns."""
from __future__ import annotations

from core import mushaf_waqf
from core import supabase_editor as sb
from core.config import (
    CLOUD_EDITOR_EDITIONS,
    EDITOR_EDITIONS,
    PUBLIC_CLOUD_WAQF_EDITIONS,
    PUBLISHABLE_EDITOR_EDITIONS,
)
from core.edition_capabilities import (
    database_capability_rows,
    editions_with,
    get_editor_edition_capability,
)
from pipeline.check_supabase_readiness import _compare_edition_capabilities


EXPECTED = frozenset({'قطر', 'الكويت', 'البحرين'})


def test_compatibility_sets_are_registry_projections():
    assert EDITOR_EDITIONS == editions_with('editor_enabled') == EXPECTED
    assert CLOUD_EDITOR_EDITIONS == editions_with('cloud_draft_enabled') == EXPECTED
    assert PUBLISHABLE_EDITOR_EDITIONS == editions_with('publish_enabled') == EXPECTED
    assert PUBLIC_CLOUD_WAQF_EDITIONS == editions_with('public_read_enabled') == EXPECTED
    assert get_editor_edition_capability(' البحرين ').publish_enabled is True
    assert get_editor_edition_capability('unknown') is None


def test_cloud_edition_validation_does_not_require_sqlite_column(monkeypatch):
    monkeypatch.setattr(sb, 'is_configured', lambda: True)
    monkeypatch.setattr(
        mushaf_waqf,
        '_get_mushaf_version_whitelist',
        lambda: frozenset({'المدينة الجديد'}),
    )

    assert mushaf_waqf._is_valid_mushaf_version('البحرين') is True
    assert mushaf_waqf._is_valid_mushaf_version('المدينة الجديد') is True
    assert mushaf_waqf._is_valid_mushaf_version('not-an-edition') is False


def test_cloud_edition_falls_back_to_sqlite_contract_offline(monkeypatch):
    monkeypatch.setattr(sb, 'is_configured', lambda: False)
    monkeypatch.setattr(
        mushaf_waqf,
        '_get_mushaf_version_whitelist',
        lambda: frozenset({'قطر'}),
    )

    assert mushaf_waqf._is_valid_mushaf_version('قطر') is True
    assert mushaf_waqf._is_valid_mushaf_version('البحرين') is False


def test_readiness_detects_missing_extra_and_mismatched_capabilities():
    exact = database_capability_rows()
    assert _compare_edition_capabilities(exact) == {
        'missing': [],
        'unexpected': [],
        'mismatched': {},
    }

    drifted = [dict(row) for row in exact if row['edition'] != 'الكويت']
    next(row for row in drifted if row['edition'] == 'البحرين')[
        'publish_enabled'
    ] = False
    drifted.append({
        'edition': 'غير معروف',
        'editor_enabled': True,
        'cloud_draft_enabled': True,
        'publish_enabled': True,
        'public_read_enabled': True,
    })
    errors = _compare_edition_capabilities(drifted)

    assert errors['missing'] == ['الكويت']
    assert errors['unexpected'] == ['غير معروف']
    assert errors['mismatched']['البحرين']['publish_enabled'] == {
        'expected': True,
        'actual': False,
    }


def test_supabase_migrations_seed_registry_capabilities():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    for name in ('supabase_editor_schema.sql', 'supabase_atomic_publish.sql'):
        sql = (root / 'pipeline' / name).read_text(encoding='utf-8')
        assert 'create table if not exists public.editor_edition_capabilities' in sql
        assert 'check (not publish_enabled or cloud_draft_enabled)' in sql
        assert 'grant select on table public.editor_edition_capabilities to service_role' in sql
        for edition in EXPECTED:
            assert f"('{edition}', true, true, true, true, now())" in sql
