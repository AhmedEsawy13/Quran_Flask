#!/usr/bin/env python3
"""Fail when quran-engine or QVP page data has moved past Athar's pin.

Pins live in data/qvp_upstream.json. The reader reads QVP_RELEASE from
frontend/lib/qvp.ts — those two must match.

    python3 scripts/check_qvp_upstream.py
    python3 scripts/check_qvp_upstream.py --offline

Network checks (GitHub tags, npm, CDN) are skipped with --offline.
A newer *acknowledged* git tag is not an upgrade: update the pin after
reading the changelog, then upgrade pages/lite only if format or overlay
needs it.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PIN_PATH = ROOT / "data" / "qvp_upstream.json"
QVP_TS = ROOT / "frontend" / "lib" / "qvp.ts"
ENGINE_REPO = "quran-ws/quran-engine"
RELEASE_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")
QVP_RELEASE_RE = re.compile(r'export const QVP_RELEASE = "(v\d+\.\d+\.\d+)"')


def load_pin() -> dict:
    return json.loads(PIN_PATH.read_text(encoding="utf-8"))


def parse_version(label: str) -> tuple[int, int, int] | None:
    match = RELEASE_RE.match(label.strip())
    if not match:
        return None
    return tuple(int(part) for part in match.groups())  # type: ignore[return-value]


def version_gt(left: str, right: str) -> bool:
    a, b = parse_version(left), parse_version(right)
    if a is None or b is None:
        return False
    return a > b


def code_release() -> str:
    text = QVP_TS.read_text(encoding="utf-8")
    match = QVP_RELEASE_RE.search(text)
    if not match:
        raise SystemExit(f"Could not find QVP_RELEASE in {QVP_TS}")
    return match.group(1)


def http_json(url: str, headers: dict[str, str] | None = None):
    request = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def http_status(url: str) -> int:
    request = urllib.request.Request(url, method="HEAD")
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return int(response.status)
    except urllib.error.HTTPError as error:
        return int(error.code)


def github_headers() -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "athar-qvp-upstream-check",
    }
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def github_tags() -> list[str]:
    payload = http_json(
        f"https://api.github.com/repos/{ENGINE_REPO}/tags?per_page=30",
        github_headers(),
    )
    if not isinstance(payload, list):
        raise RuntimeError(f"GitHub tags response was not a list: {payload}")
    return [str(item["name"]) for item in payload if item.get("name")]


def npm_version(package: str) -> str:
    payload = http_json(f"https://registry.npmjs.org/{package}/latest")
    version = payload.get("version")
    if not version:
        raise RuntimeError(f"npm latest for {package} has no version")
    return str(version)


def latest_semver_tag(tags: list[str]) -> str | None:
    ranked = [(parse_version(tag), tag) for tag in tags if parse_version(tag)]
    if not ranked:
        return None
    ranked.sort()
    return ranked[-1][1]


def check_offline(pin: dict) -> list[str]:
    problems: list[str] = []
    pinned_pages = pin["pages"]["release"]
    code = code_release()
    if code != pinned_pages:
        problems.append(
            f"frontend/lib/qvp.ts QVP_RELEASE={code} does not match pin pages.release={pinned_pages}"
        )
    cdn = pin["pages"]["cdn"].rstrip("/")
    expected = f"{cdn}/{pinned_pages}"
    qvp_ts = QVP_TS.read_text(encoding="utf-8")
    if expected not in qvp_ts and f"`${{QVP_RELEASE}}`" not in qvp_ts and "QVP_CDN" not in qvp_ts:
        problems.append(f"{QVP_TS} should build page URLs from the pinned CDN")
    if pin["pages"]["format"] != 1:
        problems.append("Athar lite decoder only reads QVP1; pin pages.format must stay 1 until we migrate")
    return problems


def check_online(pin: dict) -> list[str]:
    problems: list[str] = []
    pages = pin["pages"]
    engine = pin["engine"]
    tags = github_tags()
    newest_tag = latest_semver_tag(tags)
    acknowledged = engine["acknowledged_git_tag"]
    if newest_tag and version_gt(newest_tag, acknowledged):
        problems.append(
            f"quran-engine git has {newest_tag} but pin acknowledges {acknowledged}. "
            f"Read the changelog, then set engine.acknowledged_git_tag (upgrade lite/pages only if needed)."
        )

    npm_latest = npm_version(engine["npm_package"])
    pinned_npm = engine["npm"]
    if parse_version(npm_latest) != parse_version(pinned_npm):
        problems.append(
            f"{engine['npm_package']} on npm is {npm_latest}, pin is {pinned_npm}. "
            "Bump engine.npm after reviewing; do not float to latest."
        )

    cdn = pages["cdn"].rstrip("/")
    pinned_pages = pages["release"]
    newer_pages = []
    for tag in tags:
        if not version_gt(tag, pinned_pages):
            continue
        url = f"{cdn}/{tag}/001.qvp"
        status = http_status(url)
        if status == 200:
            newer_pages.append(tag)
    if newer_pages:
        newest_pages = latest_semver_tag(newer_pages)
        problems.append(
            f"QVP page CDN has {newest_pages} (and {', '.join(sorted(newer_pages))}). "
            f"Athar still pins {pinned_pages}. Bump pages.release and QVP_RELEASE after a smoke of pages 1, 42, 272."
        )
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true", help="only compare the pin to frontend/lib/qvp.ts")
    args = parser.parse_args(argv)
    pin = load_pin()
    problems = check_offline(pin)
    if not args.offline:
        try:
            problems.extend(check_online(pin))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, RuntimeError) as error:
            print(f"warning: upstream lookup failed ({error}); offline pin check only", file=sys.stderr)
            if os.environ.get("QVP_UPSTREAM_STRICT") == "1":
                problems.append(f"strict mode: upstream lookup failed: {error}")
    if problems:
        print("QVP upstream drift:")
        for item in problems:
            print(f"  - {item}")
        print(f"\nPin: {PIN_PATH}")
        return 1
    pages = pin["pages"]["release"]
    npm = pin["engine"]["npm"]
    git = pin["engine"]["acknowledged_git_tag"]
    print(f"QVP pin ok  pages={pages}  npm={pin['engine']['npm_package']}@{npm}  git={git}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
