"""Push/pull hand-labeled waqf crops + ONNX model via Supabase Storage + table.

Requires SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY (same as mushaf editor).
Run SQL once: pipeline/supabase_cv_waqf_hand.sql
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[2]
HAND_ROOT = ROOT / 'data' / 'cv' / 'crops_hand'
MODEL_ONNX = ROOT / 'models' / 'waqf_glyph.onnx'
MODEL_CLASSES = ROOT / 'models' / 'waqf_glyph_classes.json'
MODEL_META = ROOT / 'models' / 'waqf_glyph.json'

BUCKET = 'cv-waqf-hand'
TIMEOUT = 60


class SyncError(RuntimeError):
    pass


def _load_dotenv() -> None:
    env_path = ROOT / '.env'
    if not env_path.is_file():
        return
    for line in env_path.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, val = line.split('=', 1)
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        os.environ.setdefault(key, val)


def _base() -> str:
    return (os.environ.get('SUPABASE_URL') or '').strip().rstrip('/')


def _key() -> str:
    return (os.environ.get('SUPABASE_SERVICE_ROLE_KEY') or '').strip()


def _require_config() -> tuple[str, str]:
    _load_dotenv()
    base, key = _base(), _key()
    if not base or not key:
        raise SyncError(
            'SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY required '
            '(set in .env or environment)'
        )
    return base, key


def _headers(json_body: bool = True) -> dict[str, str]:
    _, key = _require_config()
    h = {
        'apikey': key,
        'Authorization': f'Bearer {key}',
    }
    if json_body:
        h['Content-Type'] = 'application/json'
    return h


def _rest(path: str, *, method: str = 'GET', **kwargs) -> requests.Response:
    base, _ = _require_config()
    url = f'{base}/rest/v1/{path.lstrip("/")}'
    return requests.request(method, url, headers=_headers(), timeout=TIMEOUT, **kwargs)


def _storage(path: str, *, method: str = 'GET', headers: dict | None = None,
             **kwargs) -> requests.Response:
    base, _ = _require_config()
    url = f'{base}/storage/v1/{path.lstrip("/")}'
    h = _headers(json_body=False)
    if headers:
        h.update(headers)
    return requests.request(method, url, headers=h, timeout=TIMEOUT, **kwargs)


def ensure_bucket() -> None:
    r = _storage('bucket', method='GET')
    if r.status_code != 200:
        raise SyncError(f'list buckets failed: {r.status_code} {r.text[:300]}')
    names = {b.get('id') or b.get('name') for b in r.json()}
    if BUCKET in names:
        print(f'bucket ok: {BUCKET}')
        return
    r = _storage(
        'bucket',
        method='POST',
        headers={'Content-Type': 'application/json'},
        data=json.dumps({
            'id': BUCKET,
            'name': BUCKET,
            'public': False,
            'file_size_limit': 5_242_880,
        }),
    )
    if r.status_code not in (200, 201):
        raise SyncError(
            f'create bucket failed: {r.status_code} {r.text[:400]}\n'
            f'Run pipeline/supabase_cv_waqf_hand.sql in the SQL editor first.'
        )
    print(f'created bucket: {BUCKET}')


def ensure_table() -> None:
    r = _rest(
        'cv_waqf_hand_labels?select=id&limit=1',
        method='GET',
    )
    if r.status_code == 200:
        return
    raise SyncError(
        f'table cv_waqf_hand_labels missing or inaccessible '
        f'({r.status_code}): {r.text[:300]}\n'
        f'Run pipeline/supabase_cv_waqf_hand.sql in the Supabase SQL editor.'
    )


def _object_path(rel: str) -> str:
    return rel.lstrip('/')


def upload_bytes(object_path: str, data: bytes, content_type: str) -> None:
    # upsert
    r = _storage(
        f'object/{BUCKET}/{_object_path(object_path)}',
        method='POST',
        headers={
            'Content-Type': content_type,
            'x-upsert': 'true',
        },
        data=data,
    )
    if r.status_code not in (200, 201):
        raise SyncError(f'upload {object_path}: {r.status_code} {r.text[:300]}')


def download_bytes(object_path: str) -> bytes:
    r = _storage(f'object/{BUCKET}/{_object_path(object_path)}', method='GET')
    if r.status_code != 200:
        raise SyncError(f'download {object_path}: {r.status_code} {r.text[:300]}')
    return r.content


def list_objects(prefix: str) -> list[str]:
    """Recursive list under prefix (Storage list is one level; walk folders)."""
    out: list[str] = []

    def walk(folder: str) -> None:
        body = {
            'prefix': folder,
            'limit': 1000,
            'offset': 0,
        }
        r = _storage(
            f'object/list/{BUCKET}',
            method='POST',
            headers={'Content-Type': 'application/json'},
            data=json.dumps(body),
        )
        if r.status_code != 200:
            raise SyncError(f'list {folder}: {r.status_code} {r.text[:300]}')
        for item in r.json():
            name = item.get('name') or ''
            if not name:
                continue
            # folders end with metadata id null and no metadata.mimetype sometimes
            full = f'{folder}{name}' if folder.endswith('/') or not folder else f'{folder}/{name}'
            full = full.lstrip('/')
            is_folder = item.get('id') is None and not item.get('metadata')
            if is_folder:
                walk(full + '/')
            else:
                out.append(full)

    walk(prefix if prefix.endswith('/') or not prefix else prefix + '/')
    if not prefix:
        walk('')
    return out


def load_local_labels(slug: str) -> list[dict]:
    path = HAND_ROOT / slug / 'labels.jsonl'
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    return rows


def write_local_labels(slug: str, rows: list[dict]) -> None:
    dest = HAND_ROOT / slug
    dest.mkdir(parents=True, exist_ok=True)
    path = dest / 'labels.jsonl'
    with path.open('w', encoding='utf-8') as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + '\n')


def fetch_remote_labels(slug: str | None = None) -> list[dict]:
    q = 'cv_waqf_hand_labels?select=*&order=created_at.asc'
    if slug:
        q += f'&slug=eq.{slug}'
    r = _rest(q)
    if r.status_code != 200:
        raise SyncError(f'fetch labels: {r.status_code} {r.text[:300]}')
    rows = []
    for row in r.json():
        rows.append({
            'id': row['id'],
            'edition': row['edition'],
            'slug': row['slug'],
            'page': row['page'],
            'symbol': row['symbol'],
            'box': row['box'],
            'crop': row['crop_path'],
            'created_at': row.get('created_at'),
        })
    return rows


def upsert_labels(rows: list[dict]) -> None:
    if not rows:
        return
    payload = []
    for row in rows:
        payload.append({
            'id': row['id'],
            'edition': row['edition'],
            'slug': row['slug'],
            'page': int(row['page']),
            'symbol': row['symbol'],
            'box': row['box'],
            'crop_path': row.get('crop') or row.get('crop_path'),
            'created_at': row.get('created_at'),
        })
    base, key = _require_config()
    h = {
        'apikey': key,
        'Authorization': f'Bearer {key}',
        'Content-Type': 'application/json',
        'Prefer': 'resolution=merge-duplicates,return=minimal',
    }
    r = requests.post(
        f'{base}/rest/v1/cv_waqf_hand_labels',
        headers=h,
        data=json.dumps(payload),
        timeout=TIMEOUT,
    )
    if r.status_code not in (200, 201):
        raise SyncError(f'upsert labels: {r.status_code} {r.text[:400]}')


def merge_by_id(local: list[dict], remote: list[dict]) -> list[dict]:
    by_id: dict[str, dict] = {}
    for row in remote + local:
        rid = row.get('id')
        if not rid:
            continue
        prev = by_id.get(rid)
        if prev is None:
            by_id[rid] = row
            continue
        # Prefer the one with later created_at when both exist
        a = str(prev.get('created_at') or '')
        b = str(row.get('created_at') or '')
        by_id[rid] = row if b >= a else prev
    return sorted(by_id.values(), key=lambda r: (r.get('slug', ''), int(r.get('page') or 0), r.get('id') or ''))


def push_hand(slug: str, *, include_model: bool = True) -> None:
    ensure_bucket()
    ensure_table()
    local = load_local_labels(slug)
    remote = fetch_remote_labels(slug)
    merged = merge_by_id(local, remote)
    print(f'{slug}: local={len(local)} remote={len(remote)} merged={len(merged)}')

    uploaded = 0
    for row in merged:
        crop_rel = row.get('crop') or row.get('crop_path')
        if not crop_rel:
            continue
        local_path = ROOT / crop_rel
        if not local_path.is_file():
            # try class folder from id
            print(f'  skip missing crop file: {crop_rel}')
            continue
        object_path = crop_rel  # data/cv/crops_hand/...
        upload_bytes(object_path, local_path.read_bytes(), 'image/png')
        uploaded += 1

    write_local_labels(slug, merged)
    labels_object = f'data/cv/crops_hand/{slug}/labels.jsonl'
    upload_bytes(
        labels_object,
        (HAND_ROOT / slug / 'labels.jsonl').read_bytes(),
        'application/json',
    )
    upsert_labels(merged)
    print(f'uploaded {uploaded} crops + labels.jsonl + {len(merged)} table rows')

    if include_model:
        for path, ctype in (
            (MODEL_ONNX, 'application/octet-stream'),
            (MODEL_CLASSES, 'application/json'),
            (MODEL_META, 'application/json'),
        ):
            if path.is_file():
                obj = f'models/{path.name}'
                upload_bytes(obj, path.read_bytes(), ctype)
                print(f'uploaded {obj}')


def pull_hand(slug: str, *, include_model: bool = True) -> None:
    ensure_bucket()
    ensure_table()
    remote = fetch_remote_labels(slug)
    local = load_local_labels(slug)
    merged = merge_by_id(local, remote)
    print(f'{slug}: local={len(local)} remote={len(remote)} merged={len(merged)}')

    downloaded = 0
    for row in merged:
        crop_rel = row.get('crop') or row.get('crop_path')
        if not crop_rel:
            continue
        dest = ROOT / crop_rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            data = download_bytes(crop_rel)
        except SyncError as exc:
            print(f'  missing remote crop {crop_rel}: {exc}')
            continue
        dest.write_bytes(data)
        downloaded += 1

    write_local_labels(slug, merged)
    print(f'downloaded {downloaded} crops; wrote labels.jsonl ({len(merged)} rows)')

    if include_model:
        for name in ('waqf_glyph.onnx', 'waqf_glyph_classes.json', 'waqf_glyph.json'):
            obj = f'models/{name}'
            dest = ROOT / 'models' / name
            try:
                data = download_bytes(obj)
            except SyncError:
                print(f'  no remote {obj}')
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
            print(f'downloaded {obj}')


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description='Sync hand waqf crops with Supabase')
    p.add_argument('action', choices=('push', 'pull', 'status'))
    p.add_argument('--slug', default='shamarly', help='edition slug (default shamarly)')
    p.add_argument('--no-model', action='store_true', help='skip ONNX model files')
    args = p.parse_args(argv)
    try:
        if args.action == 'status':
            _require_config()
            ensure_bucket()
            ensure_table()
            remote = fetch_remote_labels(args.slug)
            local = load_local_labels(args.slug)
            print(f'slug={args.slug} local={len(local)} remote={len(remote)}')
            return 0
        if args.action == 'push':
            push_hand(args.slug, include_model=not args.no_model)
            return 0
        if args.action == 'pull':
            pull_hand(args.slug, include_model=not args.no_model)
            return 0
    except SyncError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
