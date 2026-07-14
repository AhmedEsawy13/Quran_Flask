/* ===========================================================================
 * أثَر — shared mushaf page-layout fetch helpers.
 *
 * Three of the app's four page-layout sources (digital_khatt, qpc_v1, and
 * قطر/الكويت via the editor) are built by the same backend assembler
 * (_assemble_layout_page() in modules/layouts.py) and share one JSON shape;
 * شمرلي is architecturally different (page-local glyph substitution) but
 * exposes the same /page and /page-by-ayah route shape, so it fits the same
 * fetch pattern too. This file only extracts that fetch layer — each
 * consumer (تثبيت, تدريب) still owns its own DOM-building, CSS class prefix,
 * and interaction model.
 *
 * Plain global, no bundler in this codebase — same loading pattern as
 * theme.js. Load before any page that calls window.MushafLayoutCore.
 * ======================================================================== */
(function () {
    'use strict';

    function pageApiBase(sourceKey) {
        if (sourceKey === 'qpc_v1') return '/api/qpc-v1';
        if (sourceKey === 'shamarly') return '/api/shamarly';
        return '/api/digital-khatt';
    }

    async function fetchPageByAyah(base, surah, ayah, extraQuery) {
        const q = extraQuery ? `?${extraQuery}` : '';
        const resp = await fetch(`${base}/page-by-ayah/${surah}/${ayah}${q}`);
        if (!resp.ok) throw new Error('page load failed');
        return resp.json();
    }

    async function fetchPageByNumber(base, pageNumber, extraQuery) {
        const q = extraQuery ? `?${extraQuery}` : '';
        const resp = await fetch(`${base}/page/${pageNumber}${q}`);
        if (!resp.ok) throw new Error('page load failed');
        return resp.json();
    }

    window.MushafLayoutCore = { pageApiBase, fetchPageByAyah, fetchPageByNumber };
})();
