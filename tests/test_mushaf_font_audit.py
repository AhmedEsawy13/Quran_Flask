"""Pure regression tests for the browser-level mushaf font auditor."""

from pathlib import Path

from scripts.audit_mushaf_fonts import (
    SCENARIOS,
    SOURCES,
    THRESHOLDS,
    parse_page_number,
    selected_names,
    validate_observations,
)


def observation(page=353, render=1, **overrides):
    value = {
        'page': page,
        'render_index': render,
        'font_size': 20.0,
        'line_count': 15,
        'min_scale': 0.96,
        'max_scale': 1.05,
        'max_spacing': 2.0,
        'max_edge': 0.7,
        'worst_compression_line': {'line': 4, 'text': 'اختبار'},
        'worst_expansion_line': {'line': 5, 'text': 'اختبار'},
        'worst_spacing_line': {'line': 6, 'text': 'اختبار'},
        'worst_edge_line': {'line': 7, 'text': 'اختبار'},
    }
    value.update(overrides)
    return value


def test_parse_page_number_supports_arabic_and_ascii_digits():
    assert parse_page_number('صفحة ٣٥٨') == 358
    assert parse_page_number('Page 507') == 507
    assert parse_page_number('') == 0


def test_audit_catalog_covers_three_madinah_editions_and_scenarios():
    assert set(SOURCES) == {'qpc_v1', 'qpc_v2', 'digital_khatt'}
    assert set(SCENARIOS) == {'desktop', 'mobile', 'spread'}
    assert {342, 353, 358, 460, 507, 509, 539} <= set(SOURCES['qpc_v1']['risk_pages'])
    assert {69, 353, 358, 507, 511} <= set(SOURCES['qpc_v2']['risk_pages'])
    assert {69, 353, 358, 507, 511} <= set(SOURCES['digital_khatt']['risk_pages'])
    assert selected_names('all', SOURCES) == ['qpc_v1', 'digital_khatt', 'qpc_v2']


def test_auditor_measures_page_font_size_not_a_line_override():
    source = Path('scripts/audit_mushaf_fonts.py').read_text(encoding='utf-8')
    assert "getComputedStyle(page).getPropertyValue('--dk-fs')" in source
    assert 'inline_transform: inner.style.transform' in source
    assert 'line_width: lineRect.width' in source
    assert 'page.wait_for_timeout(240)' in source
    chrome = Path('static/js/athar-page-chrome.js').read_text(encoding='utf-8')
    assert 'attempt < 4' in chrome


def test_validator_accepts_values_inside_all_budgets():
    assert validate_observations([observation()], 'qpc_v1', 'desktop') == []


def test_validator_reports_line_level_geometry_failures():
    failures = validate_observations([
        observation(min_scale=0.90, max_spacing=4.5, max_edge=3.0, max_scale=1.25),
    ], 'digital_khatt', 'desktop')

    assert {failure.metric for failure in failures} == {
        'min_scale', 'max_spacing', 'max_edge', 'max_scale',
    }
    assert all(failure.line is not None for failure in failures)


def test_spread_validator_enforces_facing_page_size_ratio():
    failures = validate_observations([
        observation(page=69, render=7, font_size=20.0),
        observation(page=70, render=7, font_size=16.0),
    ], 'digital_khatt', 'spread')

    ratio_failure = next(item for item in failures if item.metric == 'facing_font_ratio')
    assert ratio_failure.actual == 1.25
    assert ratio_failure.limit == THRESHOLDS['max_facing_font_ratio']


def test_spread_expansion_budget_is_distinct_from_single_page_budget():
    assert validate_observations(
        [observation(max_scale=1.19)], 'digital_khatt', 'spread'
    ) == []
    failures = validate_observations(
        [observation(max_scale=1.19)], 'digital_khatt', 'desktop'
    )
    assert [item.metric for item in failures] == ['max_scale']
