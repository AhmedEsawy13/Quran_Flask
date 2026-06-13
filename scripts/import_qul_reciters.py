#!/usr/bin/env python3
"""Import / auto-sync memorization reciters from the Quranic Universal Audio
(QUL) release.

Source (CC-BY-4.0):
  https://github.com/Wider-Community/quranic-universal-audio

Each reciter is published as a .zip containing word_timestamps.json.gz (and
verse/letter timestamp variants) + catalog.json. The memorize player only needs
`word_timestamps.json.gz` (same format already used for Husary).

── Manual mode (download a .zip yourself) ──────────────────────────────────
  1) Download the reciter .zip from a release on the page above.
  2) Run:  python scripts/import_qul_reciters.py <reciter_id> <path-to.zip>
     e.g.  python scripts/import_qul_reciters.py minshawi ~/Downloads/minshawi.zip
     This extracts word_timestamps.json.gz into reciters/<dir>/ where <dir> is
     the path configured below (and in app.py MEMORIZATION_RECITERS[<id>]).
  3) Make sure MEMORIZATION_RECITERS[<reciter_id>] in app.py has the right
     'audio_tmpl' (a per-surah mp3 URL, e.g. https://server10.mp3quran.net/minsh/{surah:03d}.mp3).
  4) Restart the app — the reciter now appears in the memorize «القارئ» list.

── Auto-sync mode (no manual download) ──────────────────────────────────────
  Checks the LATEST GitHub release of Wider-Community/quranic-universal-audio
  and re-downloads only the reciters whose data actually changed (compared via
  the release's manifest.json `content_hash`, tracked in
  reciters/.qul_sync_state.json).

    python scripts/import_qul_reciters.py --sync             # download changes
    python scripts/import_qul_reciters.py --sync --check     # dry run; exit 1 if changes
    python scripts/import_qul_reciters.py --sync --reciters husary,minshawi
    python scripts/import_qul_reciters.py --sync --token $GITHUB_TOKEN

  `--check` exits 0 when everything is up to date and 1 when at least one
  reciter changed (or is newly available) — handy for a scheduled CI job that
  only opens a PR when there's something to update.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
import zipfile

# reciter_id -> target dir (must match app.py MEMORIZATION_RECITERS[*]['dir']).
# The directory's basename is also the reciter's slug in the QUL manifest.
TARGET_DIRS = {
    'husary':      'reciters/mahmoud_khalil_al_husary_mp3quran',
    'ahmed_amer':  'reciters/ahmed_amer_tvquran',
    'burhaji':     'reciters/mohammed_burhaji_yt',
    'minshawi':    'reciters/mohammed_siddiq_al_minshawi_mp3quran',
    'abdulbasit':  'reciters/abdulbasit_abdulsamad_tarteel',
    'afasy':       'reciters/afasy_qul',
    'banna':       'reciters/mahmoud_ali_al_banna_qdc',
    'maher':       'reciters/maher_al_muaiqly_qdc',
    'sufi':        'reciters/abdur_rashid_sufi_qdc',
    'maasaraawi':  'reciters/ahmed_issa_al_maasaraawi_mp3quran',
    'abdulhakam':  'reciters/mahmoud_abdul_hakam_mp3quran',
    'shaheen':     'reciters/ahmed_shaheen_mp3quran',
    'huthaifi':    'reciters/ali_al_huthaifi_mp3quran',
    'akhdar':      'reciters/ibrahim_al_akhdar_drive',
    'ayyub':       'reciters/mohammed_ayyub_drive',
}
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WANTED = ('word_timestamps.json.gz', 'verse_timestamps.json.gz',
          'letter_timestamps.json.gz', 'catalog.json')

QUL_REPO = 'Wider-Community/quranic-universal-audio'
GITHUB_API = 'https://api.github.com'
STATE_PATH = os.path.join(ROOT, 'reciters', '.qul_sync_state.json')


# ── manual mode ──────────────────────────────────────────────────────────


def import_zip(rid: str, zip_path: str) -> None:
    if rid not in TARGET_DIRS:
        sys.exit(f"unknown reciter_id {rid!r}; add it to TARGET_DIRS + app.py MEMORIZATION_RECITERS")
    if not os.path.exists(zip_path):
        sys.exit(f"zip not found: {zip_path}")
    out_dir = os.path.join(ROOT, TARGET_DIRS[rid])
    _extract(zip_path, out_dir)
    if not os.path.exists(os.path.join(out_dir, 'word_timestamps.json.gz')):
        sys.exit("ERROR: word_timestamps.json.gz not found in the zip")
    print(f"done — set MEMORIZATION_RECITERS['{rid}']['audio_tmpl'] in app.py and restart.")


def _extract(zip_path: str, out_dir: str) -> None:
    os.makedirs(out_dir, exist_ok=True)
    with zipfile.ZipFile(zip_path) as z:
        for member in z.namelist():
            base = os.path.basename(member)
            if base in WANTED:
                with z.open(member) as src, open(os.path.join(out_dir, base), 'wb') as dst:
                    dst.write(src.read())
                print("  wrote", os.path.relpath(os.path.join(out_dir, base), ROOT))


# ── auto-sync mode ───────────────────────────────────────────────────────


def _get_json(url: str, token: str | None):
    headers = {
        'Accept': 'application/vnd.github+json',
        'User-Agent': 'quran-flask-qul-sync',
    }
    if token:
        headers['Authorization'] = f'Bearer {token}'
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read())


def _download(url: str, dest: str, token: str | None) -> None:
    headers = {'User-Agent': 'quran-flask-qul-sync'}
    if token:
        headers['Authorization'] = f'Bearer {token}'
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=300) as resp, open(dest, 'wb') as fh:
        while True:
            chunk = resp.read(1 << 16)
            if not chunk:
                break
            fh.write(chunk)


def fetch_latest_manifest(token: str | None = None) -> dict:
    """Fetch the latest release's manifest.json for QUL_REPO."""
    try:
        release = _get_json(f"{GITHUB_API}/repos/{QUL_REPO}/releases/latest", token)
    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            raise
        listing = _get_json(f"{GITHUB_API}/repos/{QUL_REPO}/releases?per_page=1", token)
        if not listing:
            raise RuntimeError(f"{QUL_REPO} has no releases") from exc
        release = listing[0]

    for asset in release.get('assets') or []:
        if asset.get('name') == 'manifest.json':
            return _get_json(asset['browser_download_url'], token)
    raise RuntimeError(f"latest release of {QUL_REPO} has no manifest.json asset")


def load_state() -> dict:
    if os.path.exists(STATE_PATH):
        with open(STATE_PATH, encoding='utf-8') as fh:
            return json.load(fh)
    return {'release_version': None, 'reciters': {}}


def save_state(state: dict) -> None:
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    with open(STATE_PATH, 'w', encoding='utf-8') as fh:
        json.dump(state, fh, ensure_ascii=False, indent=2, sort_keys=True)
        fh.write('\n')


def _scope_reciters(reciters_arg: str | None) -> list[str]:
    if reciters_arg:
        ids = [r.strip() for r in reciters_arg.split(',') if r.strip()]
        unknown = [r for r in ids if r not in TARGET_DIRS]
        if unknown:
            sys.exit(f"unknown reciter_id(s): {', '.join(unknown)}")
        return ids
    # default: every reciter we already have a local copy of
    return [rid for rid, d in TARGET_DIRS.items()
            if os.path.isdir(os.path.join(ROOT, d))]


def compute_updates(state: dict, manifest: dict, reciter_ids: list[str]) -> list[dict]:
    """Return [{reciter_id, slug, status, content_hash, zip_url}, ...] for
    reciters whose manifest content_hash differs from our stored baseline."""
    recs = manifest.get('recitations') or {}
    base = state.get('reciters') or {}
    updates = []
    for rid in reciter_ids:
        slug = os.path.basename(TARGET_DIRS[rid])
        latest = recs.get(slug)
        if not latest:
            print(f"  ? {rid} ({slug}) not found in latest release — skipping", file=sys.stderr)
            continue
        old_hash = (base.get(rid) or {}).get('content_hash')
        new_hash = latest.get('content_hash')
        if old_hash == new_hash:
            continue
        updates.append({
            'reciter_id': rid,
            'slug': slug,
            'status': 'new' if old_hash is None else 'updated',
            'content_hash': new_hash,
            'ts_version': latest.get('ts_version'),
            'zip_url': latest.get('zip_url'),
        })
    return updates


def sync(check_only: bool, reciter_ids: list[str], token: str | None) -> int:
    state = load_state()
    try:
        manifest = fetch_latest_manifest(token)
    except (urllib.error.URLError, RuntimeError) as exc:
        print(f"error: could not fetch the latest QUL release: {exc}", file=sys.stderr)
        return 2

    updates = compute_updates(state, manifest, reciter_ids)
    latest_version = manifest.get('release_version')
    print(f"latest QUL release: {latest_version}  (you have: {state.get('release_version') or '?'})")

    if not updates:
        print(f"all {len(reciter_ids)} reciter(s) up to date.")
        return 0

    for u in updates:
        label = 'new' if u['status'] == 'new' else 'updated'
        print(f"  ~ {u['reciter_id']} ({u['slug']}) — {label}, ts {u['ts_version']}")

    if check_only:
        print(f"\n{len(updates)} reciter(s) changed. Re-run with --sync (no --check) to download.")
        return 1

    for u in updates:
        out_dir = os.path.join(ROOT, TARGET_DIRS[u['reciter_id']])
        os.makedirs(out_dir, exist_ok=True)
        zip_path = os.path.join(out_dir, f"{u['slug']}.zip")
        print(f"  downloading {u['slug']}.zip ...")
        _download(u['zip_url'], zip_path, token)
        _extract(zip_path, out_dir)
        os.remove(zip_path)
        state.setdefault('reciters', {})[u['reciter_id']] = {
            'slug': u['slug'],
            'content_hash': u['content_hash'],
            'ts_version': u['ts_version'],
        }

    state['release_version'] = latest_version
    save_state(state)
    print(f"\nsynced {len(updates)} reciter(s) to {latest_version}.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                      formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--sync', action='store_true',
                         help='auto-sync from the latest QUL GitHub release')
    parser.add_argument('--check', action='store_true',
                         help='with --sync: only report changes (exit 1 if any), do not download')
    parser.add_argument('--reciters', help='comma-separated reciter_ids to sync (default: all installed)')
    parser.add_argument('--token', help='GitHub token to raise the API rate limit (optional)')
    parser.add_argument('reciter_id', nargs='?', help='(manual mode) reciter_id, e.g. minshawi')
    parser.add_argument('zip_path', nargs='?', help='(manual mode) path to a downloaded .zip')
    args = parser.parse_args()

    if args.sync:
        token = args.token or os.environ.get('GITHUB_TOKEN') or os.environ.get('GH_TOKEN')
        return sync(args.check, _scope_reciters(args.reciters), token)

    if not args.reciter_id or not args.zip_path:
        parser.print_help()
        print("\nknown reciter_ids:", ', '.join(TARGET_DIRS))
        return 1
    import_zip(args.reciter_id, args.zip_path)
    return 0


if __name__ == '__main__':
    sys.exit(main())
