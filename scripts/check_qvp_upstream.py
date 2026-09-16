#!/usr/bin/env python3
"""Track quran-engine / QVP page releases against Athar's pin.

Pins live in data/qvp_upstream.json. The reader reads QVP_RELEASE from
frontend/lib/qvp.ts — those two must match.

    python3 scripts/check_qvp_upstream.py
    python3 scripts/check_qvp_upstream.py --offline
    python3 scripts/check_qvp_upstream.py --apply

`--apply` writes a newer page CDN release and/or engine/npm acknowledgement
into the pin and qvp.ts after a QVP1 smoke of pages 1, 42, 272, 540.
It does not rewrite the Athar lite fork (family/mark overlay).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import struct
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PIN_PATH = ROOT / "data" / "qvp_upstream.json"
QVP_TS = ROOT / "frontend" / "lib" / "qvp.ts"
ENGINE_REPO = "quran-ws/quran-engine"
RELEASE_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")
DATA_TAG_RE = re.compile(r"^data-(v\d+\.\d+\.\d+)$")
ENGINE_TAG_RE = re.compile(r"^(?:engine-)?(v\d+\.\d+\.\d+)$")
QVP_RELEASE_RE = re.compile(r'export const QVP_RELEASE = "(v\d+\.\d+\.\d+)"')
SMOKE_PAGES = (1, 42, 272, 540)


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


def engine_tags(tags: list[str]) -> list[str]:
    found: list[str] = []
    for tag in tags:
        if tag.startswith("data-"):
            continue
        match = ENGINE_TAG_RE.match(tag)
        if match:
            found.append(match.group(1))
    return found


def page_candidates(tags: list[str]) -> list[str]:
    found: set[str] = set()
    for tag in tags:
        data = DATA_TAG_RE.match(tag)
        if data:
            found.add(data.group(1))
        elif parse_version(tag) and not tag.startswith("data-"):
            found.add(tag if tag.startswith("v") else f"v{tag}")
    return sorted(found, key=lambda item: parse_version(item) or (0, 0, 0))


def smoke_qvp1(url: str, expected_page: int) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "athar-qvp-upstream-check"})
    with urllib.request.urlopen(request, timeout=30) as response:
        data = response.read()
    if data[:4] != b"QVP1":
        raise RuntimeError(f"{url} is not a QVP1 page (magic={data[:4]!r})")
    version = struct.unpack_from("<H", data, 4)[0]
    number = struct.unpack_from("<H", data, 8)[0]
    if version != 1:
        raise RuntimeError(f"{url} format version is {version}, Athar lite only reads 1")
    if number != expected_page:
        raise RuntimeError(f"{url} header page={number}, expected {expected_page}")


def discover_page_versions(cdn: str, tags: list[str]) -> list[str]:
    available = []
    for version in page_candidates(tags):
        if http_status(f"{cdn.rstrip('/')}/{version}/001.qvp") == 200:
            available.append(version)
    return available


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
    newest_tag = latest_semver_tag(engine_tags(tags))
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
    available = discover_page_versions(cdn, tags)
    newer_pages = [version for version in available if version_gt(version, pinned_pages)]
    if newer_pages:
        newest_pages = latest_semver_tag(newer_pages)
        problems.append(
            f"QVP page CDN has {newest_pages} (and {', '.join(sorted(newer_pages))}). "
            f"Athar still pins {pinned_pages}. Bump pages.release and QVP_RELEASE after a smoke of pages 1, 42, 272."
        )
    return problems


def write_github_output(changed: bool) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(f"changed={'true' if changed else 'false'}\n")


def apply_updates() -> int:
    pin = load_pin()
    tags = github_tags()
    cdn = pin["pages"]["cdn"].rstrip("/")
    log: list[str] = [
        "Auto-sync from https://github.com/quran-ws/quran-engine releases.",
        "",
    ]
    changed = False

    newest_engine = latest_semver_tag(engine_tags(tags))
    if newest_engine and newest_engine != pin["engine"]["acknowledged_git_tag"]:
        log.append(
            f"- engine git {pin['engine']['acknowledged_git_tag']} → {newest_engine} "
            "(acknowledge only; lite fork unchanged)"
        )
        pin["engine"]["acknowledged_git_tag"] = newest_engine
        pin["lite"]["source_ref"] = newest_engine
        changed = True

    npm_latest = npm_version(pin["engine"]["npm_package"])
    if parse_version(npm_latest) != parse_version(pin["engine"]["npm"]):
        log.append(f"- npm {pin['engine']['npm_package']} {pin['engine']['npm']} → {npm_latest}")
        pin["engine"]["npm"] = npm_latest.lstrip("v")
        changed = True

    available = discover_page_versions(cdn, tags)
    newest_pages = latest_semver_tag(available)
    pinned_pages = pin["pages"]["release"]
    if newest_pages and newest_pages != pinned_pages:
        try:
            for page in SMOKE_PAGES:
                smoke_qvp1(f"{cdn}/{newest_pages}/{page:03d}.qvp", page)
        except (urllib.error.URLError, TimeoutError, RuntimeError) as error:
            log.append(f"- skipped page bump to {newest_pages}: smoke failed ({error})")
        else:
            log.append(
                f"- pages {pinned_pages} → {newest_pages} "
                f"(QVP1 smoke ok on {', '.join(str(p) for p in SMOKE_PAGES)})"
            )
            pin["pages"]["release"] = newest_pages
            pin["notes"] = (
                f"Auto-synced pages {newest_pages} from {ENGINE_REPO}. "
                "Format still QVP1. Athar lite fork kept for family/mark overlay."
            )
            text = QVP_TS.read_text(encoding="utf-8")
            updated, count = QVP_RELEASE_RE.subn(
                f'export const QVP_RELEASE = "{newest_pages}"',
                text,
                count=1,
            )
            if count != 1:
                raise SystemExit("Could not update QVP_RELEASE in frontend/lib/qvp.ts")
            QVP_TS.write_text(updated, encoding="utf-8")
            changed = True

    if changed:
        PIN_PATH.write_text(json.dumps(pin, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        offline = check_offline(pin)
        if offline:
            raise SystemExit("apply left the pin inconsistent:\n  - " + "\n  - ".join(offline))
        print("\n".join(log))
        print("\nchanged=true")
        write_github_output(True)
        return 0

    print("QVP pin already matches latest quran-engine releases.")
    print("changed=false")
    write_github_output(False)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true", help="only compare the pin to frontend/lib/qvp.ts")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="bump the pin and QVP_RELEASE to the latest engine tag, npm version, and CDN pages",
    )
    args = parser.parse_args(argv)
    if args.apply:
        if args.offline:
            raise SystemExit("--apply cannot be combined with --offline")
        return apply_updates()
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
