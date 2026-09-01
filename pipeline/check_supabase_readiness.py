#!/usr/bin/env python3
"""Read-only Supabase connectivity, capability, and schema-version audit."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import supabase_editor as sb  # noqa: E402
from core.edition_capabilities import database_capability_rows  # noqa: E402

EXPECTED_VERSIONS = {'editor': 5, 'layout': 2}
CV_STORAGE_BUCKET = 'cv-waqf-hand'
REQUIRED_PATHS = {
    '/editor_invites',
    '/editor_marks',
    '/editor_audit',
    '/editor_progress',
    '/editor_layout_pages',
    '/editor_layout_profiles',
    '/editor_edition_capabilities',
    '/athar_schema_versions',
    '/cv_waqf_hand_labels',
    '/rpc/publish_editor_edition',
    '/tawjih',
    '/dr_ahmed21_posts',
}

_CAPABILITY_FIELDS = (
    'editor_enabled',
    'cloud_draft_enabled',
    'publish_enabled',
    'public_read_enabled',
)


def _enabled(value: object) -> bool:
    """Only an actual PostgREST JSON boolean enables a capability."""
    return value is True


def _compare_edition_capabilities(rows: list[dict]) -> dict:
    expected = {
        str(row['edition']): row
        for row in database_capability_rows()
    }
    actual = {
        str(row.get('edition') or ''): row
        for row in rows
        if row.get('edition')
    }
    missing = sorted(set(expected) - set(actual))
    unexpected = sorted(set(actual) - set(expected))
    mismatched = {
        edition: {
            field: {
                'expected': _enabled(expected[edition][field]),
                'actual': _enabled(actual[edition].get(field)),
            }
            for field in _CAPABILITY_FIELDS
            if _enabled(actual[edition].get(field))
            != _enabled(expected[edition][field])
        }
        for edition in sorted(set(expected) & set(actual))
    }
    mismatched = {
        edition: fields
        for edition, fields in mismatched.items()
        if fields
    }
    return {
        'missing': missing,
        'unexpected': unexpected,
        'mismatched': mismatched,
    }


def _load_local_env() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(ROOT / '.env', override=False)


def check() -> dict:
    if not sb.is_configured():
        raise RuntimeError(
            'SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required'
        )
    response = requests.get(
        f'{sb._base()}/rest/v1/',
        headers={
            **sb._headers(),
            'Accept': 'application/openapi+json',
        },
        timeout=20,
    )
    response.raise_for_status()
    paths = set((response.json().get('paths') or {}).keys())
    missing_paths = sorted(REQUIRED_PATHS - paths)

    storage_response = requests.get(
        f'{sb._base()}/storage/v1/bucket',
        headers=sb._headers(),
        timeout=20,
    )
    storage_response.raise_for_status()
    buckets = {
        str(row.get('id') or row.get('name') or '')
        for row in (storage_response.json() or [])
    }
    missing_storage = (
        [] if CV_STORAGE_BUCKET in buckets else [CV_STORAGE_BUCKET]
    )

    rows = sb._request(
        'GET',
        'athar_schema_versions',
        params={'select': 'component,version', 'order': 'component'},
    ) or []
    actual = {
        str(row['component']): int(row['version'])
        for row in rows
    }
    version_errors = {
        component: {
            'expected': expected,
            'actual': actual.get(component),
        }
        for component, expected in EXPECTED_VERSIONS.items()
        if actual.get(component) != expected
    }

    capability_rows = []
    if '/editor_edition_capabilities' in paths:
        capability_rows = sb._request(
            'GET',
            'editor_edition_capabilities',
            params={
                'select': (
                    'edition,editor_enabled,cloud_draft_enabled,'
                    'publish_enabled,public_read_enabled'
                ),
                'order': 'edition',
            },
        ) or []
        capability_errors = _compare_edition_capabilities(capability_rows)
    else:
        capability_errors = {
            'missing': sorted(
                row['edition'] for row in database_capability_rows()
            ),
            'unexpected': [],
            'mismatched': {},
        }
    result = {
        'supabase': sb._base(),
        'schema_versions': actual,
        'required_schema_versions': EXPECTED_VERSIONS,
        'missing_capabilities': missing_paths,
        'missing_storage': missing_storage,
        'version_errors': version_errors,
        'edition_capabilities': capability_rows,
        'capability_errors': capability_errors,
    }
    if (
        missing_paths
        or missing_storage
        or version_errors
        or any(capability_errors.values())
    ):
        raise RuntimeError(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def main() -> int:
    _load_local_env()
    try:
        result = check()
    except (RuntimeError, requests.RequestException, sb.SupabaseEditorError) as exc:
        print(f'SUPABASE READINESS FAILED\n{exc}', file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
