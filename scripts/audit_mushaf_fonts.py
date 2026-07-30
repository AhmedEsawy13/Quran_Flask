#!/usr/bin/env python3
"""Browser-level typography audit for the تثبيت mushaf renderer.

The fast ``risk`` mode checks the historically difficult pages on pull
requests. ``full`` walks all 604 pages of all three Madinah editions in desktop,
mobile, and facing-page layouts. The command starts an isolated Flask server,
uses headless Chromium, writes JSON + Markdown reports, and exits non-zero when
any rendering budget is exceeded.

    python3 scripts/audit_mushaf_fonts.py --mode risk
    python3 scripts/audit_mushaf_fonts.py --mode full --report-dir artifacts/mushaf-font-audit
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import threading
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlencode

import requests
from werkzeug.serving import make_server


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

PAGE_MIN = 1
PAGE_MAX = 604

SOURCES: dict[str, dict[str, Any]] = {
    "qpc_v1": {
        "label": "Old Madinah 1405",
        "api": "qpc-v1",
        "risk_pages": [
            29, 51, 88, 89, 127, 246, 274, 279, 353, 358, 378,
            400, 402, 507, 536, 570, 577,
        ],
        "single_max_expansion": 1.18,
    },
    "digital_khatt": {
        "label": "Madinah 1441 (QPC v4)",
        "api": "digital-khatt",
        "risk_pages": [
            29, 41, 60, 69, 168, 261, 279, 349, 353, 358, 442,
            445, 448, 477, 507, 511, 557, 594,
        ],
        "single_max_expansion": 1.15,
    },
    "qpc_v2": {
        "label": "Madinah 1421 (Digital Khatt V2)",
        "api": "qpc-v2",
        "risk_pages": [
            29, 41, 60, 69, 168, 261, 279, 343, 349, 353, 358,
            385, 445, 448, 477, 507, 511, 557,
        ],
        "single_max_expansion": 1.15,
    },
}

SCENARIOS: dict[str, dict[str, Any]] = {
    "desktop": {"label": "Desktop single", "width": 1280, "height": 720, "layout": "single"},
    "mobile": {"label": "Mobile single", "width": 390, "height": 844, "layout": "single"},
    "spread": {"label": "Desktop spread", "width": 1280, "height": 720, "layout": "dual"},
}

THRESHOLDS = {
    "min_scale": 0.95,
    "max_word_spacing_px": 4.0,
    "max_edge_error_px": 1.1,
    "max_spread_expansion": 1.20,
    "max_facing_font_ratio": 1.15,
}

ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")


@dataclass(frozen=True)
class Violation:
    source: str
    scenario: str
    page: int
    metric: str
    actual: float
    limit: float
    line: int | None = None
    text: str = ""


class LocalAuditServer:
    """Run the normal Flask app on an ephemeral local port."""

    def __init__(self, host: str = "127.0.0.1", port: int = 0):
        from app import create_app

        logging.getLogger("werkzeug").setLevel(logging.ERROR)
        self._server = make_server(
            host,
            port,
            create_app({"core", "memorize"}),
            threaded=True,
        )
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self.base_url = f"http://{host}:{self._server.server_port}"

    def __enter__(self) -> "LocalAuditServer":
        self._thread.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self._server.shutdown()
        self._thread.join(timeout=5)


def parse_page_number(value: str) -> int:
    digits = "".join(ch for ch in value.translate(ARABIC_DIGITS) if ch.isdigit())
    return int(digits) if digits else 0


def selected_names(requested: str, choices: dict[str, Any]) -> list[str]:
    if requested == "all":
        return list(choices)
    if requested not in choices:
        raise ValueError(f"Unknown selection: {requested}")
    return [requested]


def page_url(base_url: str, source: str, scenario: str, surah: int, ayah: int) -> str:
    params = {
        "src": source,
        "surah": surah,
        "from": ayah,
        "to": ayah,
        "layout": SCENARIOS[scenario]["layout"],
        "justify": 20,
        "tajweed": 0,
        "waqf": "المدينة القديم",
        "focus": 1,
        "font_audit": 1,
    }
    return f"{base_url}/memorize?{urlencode(params)}"


def page_anchor(base_url: str, source: str, page_number: int, timeout_ms: int) -> tuple[int, int]:
    api = SOURCES[source]["api"]
    response = requests.get(
        f"{base_url}/api/{api}/page/{page_number}",
        timeout=max(5, timeout_ms / 1000),
    )
    response.raise_for_status()
    payload = response.json()
    return int(payload["anchor_surah_number"]), int(payload["anchor_ayah_number"])


OBSERVE_SCRIPT = r"""
() => [...document.querySelectorAll('.mz-page.mz-has-page')].map(page => {
  const footer = page.closest('.mz-page-card')?.querySelector('.mz-foot-page')?.textContent || '';
  const lines = [...page.querySelectorAll('.mz-line')].map((line, index) => {
    if (line.dataset.justify !== '1') return null;
    const inner = line.querySelector('.mz-line-inner');
    if (!inner) return null;
    const lineRect = line.getBoundingClientRect();
    const innerRect = inner.getBoundingClientRect();
    const style = getComputedStyle(inner);
    const matrix = style.transform.match(/^matrix\(([^,]+)/);
    return {
      line: index + 1,
      scale: matrix ? Number(matrix[1]) : 1,
      spacing: Number.parseFloat(style.wordSpacing) || 0,
      edge: Math.abs(lineRect.width - innerRect.width),
      text: inner.textContent.trim().slice(0, 180),
    };
  }).filter(Boolean);
  return {
    footer,
    pageWidth: page.clientWidth,
    fontSize: Number.parseFloat(getComputedStyle(page).getPropertyValue('--dk-fs')) || 0,
    lines,
  };
})
"""


def observe(page: Any, render_index: int) -> list[dict[str, Any]]:
    raw_pages = page.evaluate(OBSERVE_SCRIPT)
    observations: list[dict[str, Any]] = []
    for raw in raw_pages:
        lines = raw["lines"]
        min_line = min(lines, key=lambda line: line["scale"], default=None)
        max_scale_line = max(lines, key=lambda line: line["scale"], default=None)
        spacing_line = max(lines, key=lambda line: line["spacing"], default=None)
        edge_line = max(lines, key=lambda line: line["edge"], default=None)
        observations.append({
            "page": parse_page_number(raw["footer"]),
            "render_index": render_index,
            "page_width": raw["pageWidth"],
            "font_size": raw["fontSize"],
            "line_count": len(lines),
            "min_scale": min_line["scale"] if min_line else 1,
            "max_scale": max_scale_line["scale"] if max_scale_line else 1,
            "max_spacing": spacing_line["spacing"] if spacing_line else 0,
            "max_edge": edge_line["edge"] if edge_line else 0,
            "worst_compression_line": min_line,
            "worst_expansion_line": max_scale_line,
            "worst_spacing_line": spacing_line,
            "worst_edge_line": edge_line,
        })
    return sorted(observations, key=lambda item: item["page"])


def settle(page: Any, timeout_ms: int) -> None:
    page.wait_for_function(
        "() => [...document.querySelectorAll('.mz-page.mz-has-page')].some(p => "
        "(p.closest('.mz-page-card')?.querySelector('.mz-foot-page')?.textContent || '').trim())",
        timeout=timeout_ms,
    )
    page.evaluate("() => document.fonts ? document.fonts.ready : Promise.resolve()")
    # renderSpread() schedules justification in requestAnimationFrame after the
    # page footer appears. A short settle window captures that final state.
    page.wait_for_timeout(80)


def visible_page_numbers(page: Any) -> list[int]:
    texts = page.locator(".mz-page.mz-has-page").evaluate_all(
        "pages => pages.map(p => p.closest('.mz-page-card')?.querySelector('.mz-foot-page')?.textContent || '')"
    )
    return sorted(parse_page_number(text) for text in texts if parse_page_number(text))


def advance(page: Any, direction: str, timeout_ms: int) -> None:
    before = visible_page_numbers(page)
    selector = "#mz-next" if direction == "next" else "#mz-prev"
    page.locator(selector).click()
    page.wait_for_function(
        "before => { const map = {'٠':'0','١':'1','٢':'2','٣':'3','٤':'4','٥':'5','٦':'6','٧':'7','٨':'8','٩':'9'}; "
        "const nums = [...document.querySelectorAll('.mz-page.mz-has-page')].map(p => { "
        "const t = p.closest('.mz-page-card')?.querySelector('.mz-foot-page')?.textContent || ''; "
        "return Number(t.replace(/[٠-٩]/g, c => map[c]).replace(/\\D/g, '')) || 0; }).filter(Boolean).sort((a,b)=>a-b); "
        "return JSON.stringify(nums) !== JSON.stringify(before); }",
        arg=before,
        timeout=timeout_ms,
    )
    settle(page, timeout_ms)


def navigate_to_exact_page(
    page: Any,
    base_url: str,
    source: str,
    scenario: str,
    target: int,
    timeout_ms: int,
) -> None:
    surah, ayah = page_anchor(base_url, source, target, timeout_ms)
    page.goto(page_url(base_url, source, scenario, surah, ayah), wait_until="domcontentloaded")
    settle(page, timeout_ms)
    for _ in range(4):
        visible = visible_page_numbers(page)
        if target in visible:
            return
        if not visible:
            break
        advance(page, "next" if max(visible) < target else "prev", timeout_ms)
    raise RuntimeError(f"Could not navigate to {source} page {target}; visible={visible_page_numbers(page)}")


def audit_risk_pages(
    page: Any,
    base_url: str,
    source: str,
    scenario: str,
    timeout_ms: int,
) -> list[dict[str, Any]]:
    by_page: dict[int, dict[str, Any]] = {}
    render_index = 0
    for target in SOURCES[source]["risk_pages"]:
        navigate_to_exact_page(page, base_url, source, scenario, target, timeout_ms)
        render_index += 1
        for item in observe(page, render_index):
            by_page[item["page"]] = item
    return list(by_page.values())


def audit_all_pages(
    page: Any,
    base_url: str,
    source: str,
    scenario: str,
    timeout_ms: int,
) -> list[dict[str, Any]]:
    page.goto(page_url(base_url, source, scenario, 1, 1), wait_until="domcontentloaded")
    settle(page, timeout_ms)
    by_page: dict[int, dict[str, Any]] = {}
    render_index = 0
    while True:
        render_index += 1
        for item in observe(page, render_index):
            by_page[item["page"]] = item
        if PAGE_MAX in by_page:
            break
        previous_max = max(by_page, default=0)
        advance(page, "next", timeout_ms)
        if max(visible_page_numbers(page), default=0) <= previous_max:
            raise RuntimeError(f"Page navigation stalled after page {previous_max}")
    missing = sorted(set(range(PAGE_MIN, PAGE_MAX + 1)) - set(by_page))
    if missing:
        raise RuntimeError(f"Audit missed pages: {missing}")
    return list(by_page.values())


def line_details(observation: dict[str, Any], key: str) -> tuple[int | None, str]:
    line = observation.get(key) or {}
    return line.get("line"), line.get("text", "")


def validate_observations(
    observations: Iterable[dict[str, Any]],
    source: str,
    scenario: str,
) -> list[Violation]:
    items = list(observations)
    violations: list[Violation] = []
    max_expansion = (
        THRESHOLDS["max_spread_expansion"]
        if SCENARIOS[scenario]["layout"] == "dual"
        else SOURCES[source]["single_max_expansion"]
    )
    checks = (
        ("min_scale", THRESHOLDS["min_scale"], "min", "worst_compression_line"),
        ("max_spacing", THRESHOLDS["max_word_spacing_px"], "max", "worst_spacing_line"),
        ("max_edge", THRESHOLDS["max_edge_error_px"], "max", "worst_edge_line"),
        ("max_scale", max_expansion, "max", "worst_expansion_line"),
    )
    for item in items:
        for metric, limit, direction, line_key in checks:
            actual = float(item[metric])
            failed = actual < limit - 0.0005 if direction == "min" else actual > limit + 0.001
            if failed:
                line, text = line_details(item, line_key)
                violations.append(Violation(source, scenario, item["page"], metric, actual, limit, line, text))

    if SCENARIOS[scenario]["layout"] == "dual":
        per_render: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for item in items:
            per_render[item["render_index"]].append(item)
        for pair in per_render.values():
            if len(pair) != 2:
                continue
            sizes = [item["font_size"] for item in pair if item["font_size"]]
            if len(sizes) == 2:
                ratio = max(sizes) / min(sizes)
                limit = THRESHOLDS["max_facing_font_ratio"]
                if ratio > limit + 0.001:
                    violations.append(Violation(source, scenario, min(item["page"] for item in pair), "facing_font_ratio", ratio, limit))
    return violations


def summarize_run(
    observations: list[dict[str, Any]],
    violations: list[Violation],
    source: str,
    scenario: str,
) -> dict[str, Any]:
    return {
        "source": source,
        "source_label": SOURCES[source]["label"],
        "scenario": scenario,
        "scenario_label": SCENARIOS[scenario]["label"],
        "pages_checked": len({item["page"] for item in observations}),
        "justified_lines_checked": sum(item["line_count"] for item in observations),
        "worst_compression_pct": round(max((1 - item["min_scale"]) * 100 for item in observations), 4),
        "max_word_spacing_px": round(max(item["max_spacing"] for item in observations), 4),
        "max_edge_error_px": round(max(item["max_edge"] for item in observations), 4),
        "max_expansion_pct": round(max((item["max_scale"] - 1) * 100 for item in observations), 4),
        "violations": [asdict(item) for item in violations],
        "passed": not violations,
    }


def write_reports(report_dir: Path, payload: dict[str, Any]) -> tuple[Path, Path]:
    report_dir.mkdir(parents=True, exist_ok=True)
    json_path = report_dir / "mushaf-font-audit.json"
    md_path = report_dir / "mushaf-font-audit.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# Mushaf font audit",
        "",
        f"- Generated: {payload['generated_at']}",
        f"- Mode: `{payload['mode']}`",
        f"- Result: **{'PASS' if payload['passed'] else 'FAIL'}**",
        "",
        "| Source | Scenario | Pages | Justified lines | Worst compression | Max spacing | Max edge error | Max expansion | Result |",
        "|---|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for run in payload["runs"]:
        lines.append(
            f"| {run['source_label']} | {run['scenario_label']} | {run['pages_checked']} | "
            f"{run['justified_lines_checked']} | {run['worst_compression_pct']:.2f}% | "
            f"{run['max_word_spacing_px']:.2f}px | {run['max_edge_error_px']:.2f}px | "
            f"{run['max_expansion_pct']:.2f}% | {'PASS' if run['passed'] else 'FAIL'} |"
        )
    violations = [item for run in payload["runs"] for item in run["violations"]]
    if violations:
        lines.extend(["", "## Violations", ""])
        for item in violations:
            location = f" page {item['page']}" + (f" line {item['line']}" if item.get("line") else "")
            lines.append(
                f"- `{item['source']}/{item['scenario']}`{location}: {item['metric']}="
                f"{item['actual']:.4f} (limit {item['limit']:.4f}) {item.get('text', '')}".rstrip()
            )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, md_path


def run(args: argparse.Namespace) -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:  # pragma: no cover - exercised in dependency-missing environments
        raise SystemExit(
            "Playwright is required. Install requirements-dev.txt, then run "
            "`python3 -m playwright install chromium`."
        ) from exc

    sources = selected_names(args.source, SOURCES)
    scenarios = selected_names(args.scenario, SCENARIOS)
    server_context: Any
    if args.base_url:
        from contextlib import nullcontext

        server_context = nullcontext(type("ExternalServer", (), {"base_url": args.base_url.rstrip("/")})())
    else:
        server_context = LocalAuditServer(args.host, args.port)

    runs: list[dict[str, Any]] = []
    with server_context as server, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=not args.headed)
        try:
            for scenario in scenarios:
                config = SCENARIOS[scenario]
                for source in sources:
                    print(f"Auditing {SOURCES[source]['label']} · {config['label']} · {args.mode}", flush=True)
                    context = browser.new_context(viewport={"width": config["width"], "height": config["height"]})
                    page = context.new_page()
                    try:
                        observations = (
                            audit_all_pages(page, server.base_url, source, scenario, args.timeout_ms)
                            if args.mode == "full"
                            else audit_risk_pages(page, server.base_url, source, scenario, args.timeout_ms)
                        )
                    finally:
                        context.close()
                    violations = validate_observations(observations, source, scenario)
                    runs.append(summarize_run(observations, violations, source, scenario))
        finally:
            browser.close()

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": args.mode,
        "thresholds": THRESHOLDS,
        "passed": all(run["passed"] for run in runs),
        "runs": runs,
    }
    json_path, md_path = write_reports(args.report_dir, payload)
    print(f"JSON report: {json_path}")
    print(f"Markdown report: {md_path}")
    print("PASS" if payload["passed"] else "FAIL")
    return 0 if payload["passed"] else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("risk", "full"), default="risk")
    parser.add_argument("--source", choices=("all", *SOURCES), default="all")
    parser.add_argument("--scenario", choices=("all", *SCENARIOS), default="all")
    parser.add_argument("--report-dir", type=Path, default=PROJECT_ROOT / "artifacts" / "mushaf-font-audit")
    parser.add_argument("--base-url", help="Audit an already-running app instead of starting Flask")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=0, help="Local server port; 0 chooses an unused port")
    parser.add_argument("--timeout-ms", type=int, default=15_000)
    parser.add_argument("--headed", action="store_true", help="Show Chromium while auditing")
    return parser


def main() -> int:
    return run(build_parser().parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
