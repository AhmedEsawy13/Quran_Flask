#!/usr/bin/env python3
"""Exercise critical Athar routes locally or against a deployed base URL."""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@dataclass(frozen=True)
class Check:
    name: str
    path: str
    expected_status: int = 200


CORE_CHECKS = (
    Check('health', '/api/health'),
    Check('surah catalog', '/api/surahs'),
    Check('ayah text', '/api/surahs/2/ayahs/255'),
    Check('Arabic search', f'/api/search?q={quote("الصدقات")}&limit=10'),
)
APP_CHECKS = (
    Check('reading page', '/'),
    Check('memorization page', '/memorize'),
    Check('waqf practice', '/waqf-practice'),
    Check('practice passage', '/api/waqf-practice/passage/2/1/3'),
)
EDITOR_CHECKS = (
    Check('waqf reviewer', '/waqf-mark-review'),
    Check('activity browser', '/activity'),
    Check('activity feed', '/api/activity'),
    Check('Mesaha studio', '/layout-studio/mesaha'),
    Check('Mesaha split page', '/api/layout-studio/mesaha/page/61'),
    Check(
        'Mesaha confidence queue',
        '/api/layout-studio/mesaha/import-confidence',
    ),
)


class LocalClient:
    def __init__(self, include_editor: bool):
        import app as quran_app

        features = {'core', 'reading', 'memorize', 'breathing'}
        if include_editor:
            features.add('editor')
        self._client = quran_app.create_app(features).test_client()

    def get(self, path: str):
        return self._client.get(path)


class RemoteClient:
    def __init__(self, base_url: str):
        self._base_url = base_url.rstrip('/')
        self._session = requests.Session()
        self._session.headers['User-Agent'] = 'Athar-production-smoke/1'

    def get(self, path: str):
        return self._session.get(
            f'{self._base_url}{path}',
            timeout=25,
            allow_redirects=True,
        )


def _json(response):
    try:
        return response.get_json()
    except AttributeError:
        return response.json()


def run(client, *, include_editor: bool) -> list[str]:
    checks = [*CORE_CHECKS, *APP_CHECKS]
    if include_editor:
        checks.extend(EDITOR_CHECKS)
    failures = []
    for check in checks:
        response = client.get(check.path)
        if response.status_code != check.expected_status:
            failures.append(
                f'{check.name}: HTTP {response.status_code}, '
                f'expected {check.expected_status}'
            )
            continue
        if check.name == 'health':
            payload = _json(response)
            if payload.get('status') != 'healthy':
                failures.append(f'health: {payload!r}')
        elif check.name == 'Arabic search':
            keys = {
                row.get('verse_key')
                for row in (_json(response).get('results') or [])
            }
            if not {'9:58', '9:60'} <= keys:
                failures.append(f'Arabic search: missing verses, got {sorted(keys)}')
        elif check.name == 'Mesaha split page':
            payload = _json(response)
            line = next(
                (
                    row for row in payload.get('lines') or []
                    if int(row.get('line_number') or 0) == 12
                ),
                {},
            )
            if {word.get('surah') for word in line.get('words') or []} != {2}:
                failures.append('Mesaha split page: foreign-surah words detected')
        elif check.name == 'Mesaha confidence queue':
            payload = _json(response)
            if len(payload.get('pages') or []) != 826:
                failures.append('Mesaha confidence queue: expected 826 pages')
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument('--local', action='store_true')
    target.add_argument('--base-url')
    parser.add_argument('--include-editor', action='store_true')
    args = parser.parse_args()

    if args.local:
        client = LocalClient(args.include_editor)
        label = 'local Flask application'
    else:
        client = RemoteClient(args.base_url)
        label = args.base_url
    failures = run(client, include_editor=args.include_editor)
    if failures:
        print(f'SMOKE FAILED: {label}', file=sys.stderr)
        for failure in failures:
            print(f'- {failure}', file=sys.stderr)
        return 1
    print(f'SMOKE PASS: {label}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
