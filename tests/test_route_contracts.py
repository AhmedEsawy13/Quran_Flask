"""Guard the committed API method/auth/cache/status/shape inventory."""
from __future__ import annotations

import json
from pathlib import Path

from pipeline.generate_route_contracts import OUTPUT_PATH, build_inventory


def test_api_route_contract_inventory_has_no_silent_drift():
    expected = json.loads(OUTPUT_PATH.read_text(encoding='utf-8'))
    actual = build_inventory()
    assert actual == expected, (
        'API route contract changed. If intentional, run '
        '`python3 pipeline/generate_route_contracts.py`, inspect the diff, '
        'and commit the updated inventory.'
    )


def test_every_api_contract_declares_required_dimensions():
    inventory = build_inventory()
    assert inventory['route_count'] == len(inventory['routes'])
    assert inventory['route_count'] >= 100
    required = {
        'path', 'endpoint', 'methods', 'auth', 'availability', 'feature',
        'success_cache', 'declared_statuses', 'success_keys', 'error_keys',
        'dynamic_status', 'dynamic_success', 'dynamic_error',
        'response_kinds', 'source',
    }
    for route in inventory['routes']:
        assert required <= set(route), route['path']
        assert route['methods'], route['path']
        assert route['auth'] in {'public', 'editor', 'admin'}, route['path']
        assert route['success_cache'] in {'public-1h', 'no-store'}, route['path']
        assert 200 in route['declared_statuses'], route['path']
        assert Path(route['source']).suffix == '.py', route['path']


def test_sensitive_editor_aliases_are_not_mislabeled_public():
    routes = {row['path']: row for row in build_inventory()['routes']}
    for path, contract in routes.items():
        if path.startswith('/api/azhar-layout/'):
            assert contract['auth'] == 'editor', path
