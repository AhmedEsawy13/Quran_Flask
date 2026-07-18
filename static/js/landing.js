/* أثَر landing — load a real Madinah page into the hero visual. */
(function () {
    'use strict';

    var PAGE = 1;
    var BASMALA_GLYPH = '\u00F3';
    var reduceMotion = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    function revealCards() {
        var cards = document.querySelectorAll('.lp-card');
        if (!cards.length) return;
        if ('IntersectionObserver' in window && !reduceMotion) {
            var io = new IntersectionObserver(function (entries) {
                entries.forEach(function (e) {
                    if (e.isIntersecting) {
                        e.target.classList.add('in-view');
                        io.unobserve(e.target);
                    }
                });
            }, { threshold: 0.16 });
            cards.forEach(function (c) { io.observe(c); });
        } else {
            cards.forEach(function (c) { c.classList.add('in-view'); });
        }
    }

    function sizeHeroPage() {
        var Chrome = window.AtharPageChrome;
        if (!Chrome || !Chrome.sizePages) return;
        Chrome.sizePages({
            cssVarPrefix: 'lp',
            pages: 1,
            ratio: 0.66,
            gutter: 0,
            spreadPad: 0,
            minW: 220,
            minH: 340,
            getAvailH: function () {
                return Math.max(340, Math.min(window.innerHeight * 0.78, 640));
            },
            getAvailW: function () {
                var stage = document.getElementById('lp-mushaf-stage');
                var w = stage ? stage.clientWidth : window.innerWidth * 0.42;
                return Math.max(220, Math.min(w - 24, 420));
            },
        });
    }

    function renderHeroPage(payload) {
        var pageEl = document.getElementById('lp-page');
        var juzEl = document.getElementById('lp-juz');
        var surahEl = document.getElementById('lp-surah');
        var footEl = document.getElementById('lp-page-num');
        var card = document.getElementById('lp-mushaf');
        if (!pageEl || !window.AtharMushaf || !window.AtharPageChrome) return;

        var Chrome = window.AtharPageChrome;
        var surahHeaderGlyph = Chrome.surahHeaderGlyph;

        window.AtharMushaf.renderMushafLines(pageEl, payload.lines || [], {
            lineClass: 'lp-line',
            contentClass: 'lp-line-inner',
            wordClass: 'lp-word',
            surahClass: 'lp-line-surah',
            basmalaClass: 'lp-line-basmala',
            textForSpecial: function (ctx) {
                if (ctx.kind === 'surah') {
                    return surahHeaderGlyph(ctx.line.surah_number) || ctx.line.display_text || '';
                }
                return BASMALA_GLYPH;
            },
            decorateSpecial: function (el, ctx) {
                if (ctx.kind === 'surah' && surahHeaderGlyph(ctx.line.surah_number)) {
                    el.classList.add('lp-surah-glyph');
                }
                el.setAttribute('aria-label', ctx.line.display_text || '');
            },
            textForWord: function (ctx) {
                return window.AtharMushaf.stripEmbeddedWaqf(ctx.raw);
            },
            decorateLine: function (el, ctx) {
                if ((ctx.line.words || []).length) {
                    el.dataset.justify = ctx.line.is_centered ? '0' : '1';
                }
            },
        });

        Chrome.renderPageChrome({
            payload: payload,
            juzEl: juzEl,
            surahEl: surahEl,
            pageNumberEl: footEl,
            juzGlyphClass: 'athar-page-juz-glyph',
            surahGlyphClass: 'athar-page-surah-glyph',
            surahTextClass: 'athar-page-surah-text',
        });

        sizeHeroPage();

        function fitPage() {
            var applyFont = Chrome.createFontSizer({
                cssVarName: '--lp-fs',
                pageEls: function () { return [pageEl]; },
                lineSelector: '.lp-line',
                // Madinah pages are 15-line boxes even when a short surah
                // only fills the first few — keep that geometry so Fatiha
                // does not balloon to ~pageHeight/8.
                innerSelector: '.lp-line-inner',
                linesPerPage: 15,
                minFontSize: 14,
                fitScale: 0.94,
                minLineScale: 0.88,
            });
            var justify = Chrome.createLineJustifier({
                containerEls: function () { return [pageEl]; },
                lineSelector: '.lp-line',
                innerSelector: '.lp-line-inner',
                wordSelector: '.lp-word',
                featureSettings: function () { return '"ss01", "ss02", "ss03", "ss05", "ss08"'; },
            });
            if (applyFont) applyFont(true);
            // Centered Fatiha lines still need a gentle scaleX when wider than the card.
            pageEl.querySelectorAll('.lp-line[data-justify="0"] .lp-line-inner').forEach(function (inner) {
                var line = inner.parentElement;
                var avail = line ? line.clientWidth : 0;
                var natural = inner.scrollWidth;
                if (avail > 0 && natural > avail + 0.5) {
                    inner.style.transform = 'scaleX(' + Math.max(0.72, avail / natural) + ')';
                }
            });
            if (justify) justify();
            if (card) card.classList.add('is-ready');
        }
        requestAnimationFrame(function () { requestAnimationFrame(fitPage); });
    }

    async function loadHeroMushaf() {
        var stage = document.getElementById('lp-mushaf-stage');
        if (!stage || !window.AtharApi || !window.AtharMushaf) return;
        try {
            var client = window.AtharMushaf.createPageClient({
                getSource: function () { return 'digital_khatt'; },
                getVersions: function () { return []; },
            });
            var payload = await client.byNumber(PAGE);
            if (!payload) throw new Error('empty page');
            renderHeroPage(payload);
        } catch (err) {
            stage.classList.add('is-failed');
        }
    }

    var resizeTimer;
    window.addEventListener('resize', function () {
        clearTimeout(resizeTimer);
        resizeTimer = setTimeout(function () {
            var card = document.getElementById('lp-mushaf');
            var pageEl = document.getElementById('lp-page');
            if (!card || !card.classList.contains('is-ready') || !pageEl || !window.AtharPageChrome) return;
            sizeHeroPage();
            var applyFont = window.AtharPageChrome.createFontSizer({
                cssVarName: '--lp-fs',
                pageEls: function () { return [pageEl]; },
                lineSelector: '.lp-line',
                innerSelector: '.lp-line-inner',
                linesPerPage: 15,
                minFontSize: 14,
                fitScale: 0.94,
                minLineScale: 0.88,
            });
            var justify = window.AtharPageChrome.createLineJustifier({
                containerEls: function () { return [pageEl]; },
                lineSelector: '.lp-line',
                innerSelector: '.lp-line-inner',
                wordSelector: '.lp-word',
                featureSettings: function () { return '"ss01", "ss02", "ss03", "ss05", "ss08"'; },
            });
            requestAnimationFrame(function () {
                if (applyFont) applyFont(true);
                pageEl.querySelectorAll('.lp-line[data-justify="0"] .lp-line-inner').forEach(function (inner) {
                    var line = inner.parentElement;
                    var avail = line ? line.clientWidth : 0;
                    var natural = inner.scrollWidth;
                    if (avail > 0 && natural > avail + 0.5) {
                        inner.style.transform = 'scaleX(' + Math.max(0.72, avail / natural) + ')';
                    }
                });
                if (justify) justify();
            });
        }, 120);
    });

    revealCards();
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', loadHeroMushaf);
    } else {
        loadHeroMushaf();
    }
})();
