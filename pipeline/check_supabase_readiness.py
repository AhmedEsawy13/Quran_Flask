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

EXPECTED_VERSIONS = {'editor': 4, 'layout': 2}
CV_STORAGE_BUCKET = 'cv-waqf-hand'
REQUIRED_PATHS = {
    '/editor_invites',
    '/editor_marks',
    '/editor_audit',
    '/editor_progress',
    '/editor_layout_pages',
    '/editor_layout_profiles',
    '/athar_schema_versions',
    '/cv_waqf_hand_labels',
    '/rpc/publish_editor_edition',
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
    result = {
        'supabase': sb._base(),
        'schema_versions': actual,
        'required_schema_versions': EXPECTED_VERSIONS,
        'missing_capabilities': missing_paths,
        'missing_storage': missing_storage,
        'version_errors': version_errors,
    }
    if missing_paths or missing_storage or version_errors:
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
