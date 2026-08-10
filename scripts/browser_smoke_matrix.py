#!/usr/bin/env python3
"""Run critical browser journeys at desktop and mobile widths.

The matrix uses the normal Flask application and real local APIs. Cloud editor
configuration and third-party requests are disabled so the result is stable in
CI and cannot write reviewer data outside the checkout.

    python3 scripts/browser_smoke_matrix.py
    python3 scripts/browser_smoke_matrix.py --journey memorize --scenario mobile
    python3 scripts/browser_smoke_matrix.py --base-url http://127.0.0.1:5001
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sys
import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

from werkzeug.serving import make_server


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

READ_ONLY_RUNTIME_FILES = (PROJECT_ROOT / "data/mushaf_waqf.db",)


SCENARIOS: dict[str, dict[str, Any]] = {
    "desktop": {"width": 1366, "height": 900, "is_mobile": False},
    "mobile": {"width": 390, "height": 844, "is_mobile": True},
}

# These expensive edge cases are specific to the fixed-viewport Quran stage;
# keep the rest of the project's smoke journeys on the standard two widths.
MEMORIZE_EDGE_SCENARIOS: dict[str, dict[str, Any]] = {
    "phone_narrow": {"width": 360, "height": 800, "is_mobile": True},
    "landscape_short": {"width": 844, "height": 390, "is_mobile": True},
}
ALL_SCENARIOS = {**SCENARIOS, **MEMORIZE_EDGE_SCENARIOS}


@dataclass(frozen=True)
class Journey:
    name: str
    label: str
    path: str
    shell_selector: str
    ready_expression: str


JOURNEYS: tuple[Journey, ...] = (
    Journey(
        "reader", "Reader", "/read", "#reader-title",
        "document.querySelectorAll('#surah-select option').length === 114"
        " && document.querySelectorAll('#quran-text .word-token').length > 0",
    ),
    Journey(
        "memorize", "تثبيت", "/memorize?src=qpc_v2&surah=1&from=1&to=1&layout=single",
        "#mz-bar", "document.querySelectorAll('.mz-page.mz-has-page .mz-line').length > 0",
    ),
    Journey(
        "waqf", "مكث", "/waqf?surah=2&ayah=255", "#wq-title",
        "!document.querySelector('#wq-verse-card').hidden"
        " && document.querySelectorAll('#wq-verse-flow .wq-word').length > 0",
    ),
    Journey(
        "editor", "Mushaf editor", f"/mushaf-editor?edition={quote('البحرين')}&page=17",
        "#ed-title", "document.querySelectorAll('#ed-page .ed-line').length > 0"
        " && document.querySelector('#ed-page-label').textContent.trim().length > 0",
    ),
    Journey(
        "layout_studio", "Layout Studio", "/layout-studio/bahrain", "#az-title",
        "document.querySelectorAll('#az-page .az-line').length > 0"
        " && document.querySelector('#az-page-label').textContent.trim().length > 0",
    ),
    Journey(
        "mark_review", "Mark review", "/waqf-mark-review", "#wmr-title",
        "document.querySelector('#wmr-meta').textContent.trim().length > 0"
        " && !document.querySelector('#wmr-meta').textContent.includes('التحميل')"
        " && document.querySelector('#wmr-list').children.length > 0",
    ),
    Journey(
        "cv_labeling", "CV labeling",
        f"/cv-waqf?edition={quote('البحرين')}&page=17&mode=label", ".cvw-title",
        "!document.querySelector('#cvw-img').hidden"
        " && document.querySelector('#cvw-img').naturalWidth > 0"
        " && document.querySelectorAll('#cvw-word option').length > 1"
        " && document.querySelector('#cvw-empty').hidden",
    ),
)


@dataclass
class Result:
    journey: str
    label: str
    scenario: str
    path: str
    passed: bool
    duration_ms: int
    errors: list[str]
    screenshot: str | None = None


class LocalSmokeServer:
    """Run every feature locally with cloud persistence deliberately off."""

    _CLOUD_KEYS = (
        "SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY", "EDITOR_SESSION_SECRET",
        "SUPABASE_ANON_KEY",
    )

    def __init__(self, host: str = "127.0.0.1", port: int = 0):
        self._saved_env = {key: os.environ.get(key) for key in self._CLOUD_KEYS}
        for key in self._CLOUD_KEYS:
            os.environ.pop(key, None)
        try:
            from app import create_app

            logging.getLogger("werkzeug").setLevel(logging.ERROR)
            app = create_app({"core", "reading", "memorize", "breathing", "editor"})
            app.config.update(TESTING=False)
            self._server = make_server(host, port, app, threaded=True)
            self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
            self.base_url = f"http://{host}:{self._server.server_port}"
        except Exception:
            self._restore_env()
            raise

    def _restore_env(self) -> None:
        for key, value in self._saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def __enter__(self) -> "LocalSmokeServer":
        self._thread.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self._server.shutdown()
        self._thread.join(timeout=5)
        self._restore_env()


def selected(value: str, choices: list[str]) -> list[str]:
    if value == "all":
        return choices
    if value not in choices:
        raise ValueError(f"unknown selection: {value}")
    return [value]


def runtime_fingerprints() -> dict[Path, str]:
    return {
        path: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in READ_ONLY_RUNTIME_FILES
        if path.is_file()
    }


def _visible_loading_text(page: Any) -> list[str]:
    return page.evaluate(
        r"""() => [...document.querySelectorAll('body *')]
          .filter(el => {
            const s = getComputedStyle(el);
            if (s.display === 'none' || s.visibility === 'hidden' || el.hidden) return false;
            const text = (el.childElementCount ? '' : el.textContent || '').trim();
            return /جار[يٍ]?\s+التحميل|جارٍ\s+التحميل/.test(text);
          })
          .map(el => (el.textContent || '').trim().slice(0, 120))"""
    )


def _shell_geometry(page: Any, selector: str) -> dict[str, Any]:
    return page.locator(selector).evaluate(
        """el => {
          const r = el.getBoundingClientRect();
          const s = getComputedStyle(el);
          return {
            visible: r.width > 0 && r.height > 0 && s.display !== 'none'
              && s.visibility !== 'hidden' && !el.hidden,
            left: r.left, right: r.right, top: r.top, bottom: r.bottom,
            viewportWidth: window.innerWidth, viewportHeight: window.innerHeight,
          };
        }"""
    )


def _run_journey(
    browser: Any,
    base_url: str,
    journey: Journey,
    scenario_name: str,
    timeout_ms: int,
    report_dir: Path,
) -> Result:
    import time

    scenario = ALL_SCENARIOS[scenario_name]
    context = browser.new_context(
        viewport={"width": scenario["width"], "height": scenario["height"]},
        is_mobile=scenario["is_mobile"],
        device_scale_factor=1,
        locale="ar-EG",
        reduced_motion="reduce",
    )
    page = context.new_page()
    errors: list[str] = []
    local_origin = urlparse(base_url)

    def route_request(route: Any) -> None:
        parsed = urlparse(route.request.url)
        if journey.name == "cv_labeling" and parsed.path.startswith("/api/cv-waqf/image/"):
            # The scans are deliberately not committed. Keep UI smoke deterministic
            # while the labels/words/queue still come from their real local APIs.
            route.fulfill(
                status=200,
                content_type="image/svg+xml",
                body=(
                    '<svg xmlns="http://www.w3.org/2000/svg" width="1024" height="1536" '
                    'viewBox="0 0 1024 1536"><rect width="1024" height="1536" fill="#fffdf8"/>'
                    '<path d="M96 180h832M96 260h832M96 340h832" stroke="#d7cdbd" stroke-width="4"/>'
                    '</svg>'
                ),
            )
            return
        if parsed.scheme in {"data", "blob", "about"} or (
            parsed.hostname == local_origin.hostname and parsed.port == local_origin.port
        ):
            route.continue_()
        else:
            route.abort("blockedbyclient")

    def record_response(response: Any) -> None:
        parsed = urlparse(response.url)
        if (
            parsed.hostname == local_origin.hostname
            and parsed.port == local_origin.port
            and response.status >= 400
        ):
            errors.append(f"HTTP {response.status}: {parsed.path}")

    def record_console(message: Any) -> None:
        text = message.text
        if message.type == "error" and not text.startswith("Failed to load resource"):
            errors.append(f"console error: {text}")

    page.route("**/*", route_request)
    page.on("pageerror", lambda error: errors.append(f"page error: {error}"))
    page.on("console", record_console)
    page.on("response", record_response)
    started = time.monotonic()
    screenshot: str | None = None
    try:
        page.goto(f"{base_url}{journey.path}", wait_until="domcontentloaded", timeout=timeout_ms)
        page.locator(journey.shell_selector).wait_for(state="visible", timeout=timeout_ms)
        page.wait_for_function(f"() => Boolean({journey.ready_expression})", timeout=timeout_ms)
        page.evaluate("() => document.fonts ? document.fonts.ready : Promise.resolve()")
        page.wait_for_timeout(180)

        geometry = _shell_geometry(page, journey.shell_selector)
        if not geometry["visible"]:
            errors.append("critical shell is not visible")
        tolerance = 3
        if geometry["left"] < -tolerance or geometry["right"] > geometry["viewportWidth"] + tolerance:
            errors.append(
                "critical shell overflows viewport "
                f"({geometry['left']:.1f}..{geometry['right']:.1f} / {geometry['viewportWidth']})"
            )

        loading = _visible_loading_text(page)
        if loading:
            errors.append(f"visible loading state remained: {loading[0]}")

        if journey.name == "memorize":
            stage = page.evaluate(
                """() => {
                  const area = document.querySelector('.mz-stage-area');
                  const shell = document.querySelector('.mz-zoom-shell');
                  const spread = document.querySelector('.mz-spread');
                  const page = document.querySelector('.mz-page.mz-has-page');
                  const ar = area.getBoundingClientRect();
                  const sr = shell.getBoundingClientRect();
                  const pr = page.getBoundingClientRect();
                  const textRects = [...page.querySelectorAll(
                    '.mz-line[data-justify="1"] .mz-line-inner'
                  )].map(element => element.getBoundingClientRect());
                  return {
                    bodyWidth: document.body.scrollWidth,
                    viewportWidth: innerWidth,
                    areaHeight: ar.height,
                    areaScrollHeight: area.scrollHeight,
                    areaScrollWidth: area.scrollWidth,
                    shellHeight: sr.height,
                    shellWidth: sr.width,
                    overflow: getComputedStyle(area).overflow,
                    single: document.body.classList.contains('mz-single'),
                    fitTransform: getComputedStyle(spread).transform,
                    minTextInset: Math.min(...textRects.flatMap(rect => [
                      rect.left - pr.left, pr.right - rect.right,
                    ])),
                  };
                }"""
            )
            if stage["bodyWidth"] > stage["viewportWidth"] + 1:
                errors.append(
                    f"memorize body overflows ({stage['bodyWidth']} / {stage['viewportWidth']})"
                )
            if stage["overflow"] not in {"auto", "scroll"}:
                errors.append("memorize stage cannot scroll a zoomed or short page")
            if stage["fitTransform"] != "none":
                errors.append("fit mode keeps an outer transform on the Quran page")
            if stage["minTextInset"] < 3:
                errors.append(
                    f"Quran text reaches outside its safe frame inset ({stage['minTextInset']:.1f}px)"
                )
            if scenario["width"] < 700 and not stage["single"]:
                errors.append("memorize did not force single-page mode on a narrow viewport")
            if stage["shellHeight"] > stage["areaHeight"] + 1 and (
                stage["areaScrollHeight"] < stage["shellHeight"] - 1
            ):
                errors.append("tall Quran page is clipped instead of scrollable")

            page.locator('#mz-zoom-in').click()
            page.wait_for_timeout(80)
            zoomed = page.evaluate(
                "() => Number(getComputedStyle(document.documentElement).getPropertyValue('--mz-user-zoom'))"
            )
            if zoomed <= 1:
                errors.append("Quran zoom-in control did not increase the scale")
            page.locator('#mz-zoom-fit').click()
            fitted = page.evaluate(
                "() => Number(getComputedStyle(document.documentElement).getPropertyValue('--mz-user-zoom'))"
            )
            if abs(fitted - 1) > 0.01:
                errors.append("Quran fit control did not restore 100%")
    except Exception as exc:  # Playwright exposes useful assertion text here.
        errors.append(str(exc).split("Call log:", 1)[0].strip())

    passed = not errors
    if not passed:
        report_dir.mkdir(parents=True, exist_ok=True)
        shot = report_dir / f"{scenario_name}-{journey.name}.png"
        try:
            page.screenshot(path=str(shot), full_page=True)
            screenshot = str(shot)
        except Exception as exc:
            errors.append(f"screenshot failed: {exc}")
    duration_ms = round((time.monotonic() - started) * 1000)
    context.close()
    return Result(
        journey=journey.name,
        label=journey.label,
        scenario=scenario_name,
        path=journey.path,
        passed=passed,
        duration_ms=duration_ms,
        errors=errors,
        screenshot=screenshot,
    )


def write_report(report_dir: Path, base_url: str, results: list[Result]) -> None:
    report_dir.mkdir(parents=True, exist_ok=True)
    generated_at = datetime.now(timezone.utc).isoformat()
    payload = {
        "generated_at": generated_at,
        "base_url": base_url,
        "passed": all(item.passed for item in results),
        "results": [asdict(item) for item in results],
    }
    (report_dir / "report.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    lines = [
        "# Browser smoke matrix", "", f"Generated: `{generated_at}`", "",
        "| Journey | Viewport | Result | Duration |", "|---|---|---:|---:|",
    ]
    for item in results:
        mark = "PASS" if item.passed else "FAIL"
        lines.append(f"| {item.label} | {item.scenario} | {mark} | {item.duration_ms} ms |")
        for error in item.errors:
            lines.append(f"\n- `{item.scenario}/{item.journey}`: {error}")
    (report_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", help="test an existing server instead of starting Flask")
    parser.add_argument("--scenario", default="all", choices=["all", *ALL_SCENARIOS])
    parser.add_argument("--journey", default="all", choices=["all", *(j.name for j in JOURNEYS)])
    parser.add_argument("--timeout-ms", type=int, default=20_000)
    parser.add_argument("--headed", action="store_true")
    parser.add_argument("--report-dir", type=Path, default=PROJECT_ROOT / "artifacts/browser-smoke")
    return parser.parse_args()


def run(args: argparse.Namespace, base_url: str) -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Playwright is missing. Run: pip install -r requirements-dev.txt", file=sys.stderr)
        return 2

    journeys = [j for j in JOURNEYS if args.journey in {"all", j.name}]
    if args.scenario == "all":
        pairs = [(scenario, journey) for scenario in SCENARIOS for journey in journeys]
        memorize = next((journey for journey in journeys if journey.name == "memorize"), None)
        if memorize:
            pairs.extend((scenario, memorize) for scenario in MEMORIZE_EDGE_SCENARIOS)
    elif args.scenario in MEMORIZE_EDGE_SCENARIOS:
        pairs = [
            (args.scenario, journey) for journey in journeys if journey.name == "memorize"
        ]
    else:
        pairs = [(args.scenario, journey) for journey in journeys]
    results: list[Result] = []
    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch(headless=not args.headed)
        except Exception as exc:
            print(f"Chromium is unavailable: {exc}", file=sys.stderr)
            print("Run: python3 -m playwright install chromium", file=sys.stderr)
            return 2
        try:
            for scenario, journey in pairs:
                result = _run_journey(
                    browser, base_url.rstrip("/"), journey, scenario,
                    args.timeout_ms, args.report_dir,
                )
                results.append(result)
                status = "PASS" if result.passed else "FAIL"
                print(f"{status:4} {scenario:15} {journey.name:14} {result.duration_ms:>6} ms")
                for error in result.errors:
                    print(f"     {error}")
        finally:
            browser.close()

    write_report(args.report_dir, base_url, results)
    passed = sum(item.passed for item in results)
    print(f"\n{passed}/{len(results)} journeys passed; report: {args.report_dir / 'report.md'}")
    return 0 if passed == len(results) else 1


def main() -> int:
    args = parse_args()
    if args.base_url:
        return run(args, args.base_url)
    before = runtime_fingerprints()
    with LocalSmokeServer() as server:
        exit_code = run(args, server.base_url)
    after = runtime_fingerprints()
    changed = [str(path.relative_to(PROJECT_ROOT)) for path in before if after.get(path) != before[path]]
    if changed:
        print(f"ERROR read-only browser journeys modified runtime data: {', '.join(changed)}", file=sys.stderr)
        return 1
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
