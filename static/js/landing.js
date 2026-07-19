/* أثَر landing — live Madinah page in the hero, with source + tajweed toggles. */
(function () {
    'use strict';

    var PAGE = 1;
    var BASMALA_GLYPH = '\u00F3';
    var PAGE_RATIO = 0.66;
    var OLD_MADINA_PAGE_RATIO = 0.72;
    var reduceMotion = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    var TOOLS_DIM_MS = 2200;
    var state = {
        src: 'digital_khatt',
        tajweedOn: true,
        tajweedCache: new Map(),
        payload: null,
        renderToken: 0,
        dimTimer: null,
    };

    function $(id) { return document.getElementById(id); }

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

    function syncTools() {
        document.querySelectorAll('.lp-src-btn').forEach(function (btn) {
            var on = btn.getAttribute('data-src') === state.src;
            btn.setAttribute('aria-pressed', String(on));
        });
        var tj = $('lp-tajweed');
        if (tj) tj.setAttribute('aria-pressed', String(state.tajweedOn));
        var card = $('lp-mushaf');
        if (!card) return;
        card.classList.toggle('lp-src-digital-khatt', state.src === 'digital_khatt');
        card.classList.toggle('lp-src-qpc-v1', state.src === 'qpc_v1');
        card.classList.toggle('lp-tajweed', state.tajweedOn);
    }

    function clearToolsDim() {
        var card = $('lp-mushaf');
        if (state.dimTimer) {
            clearTimeout(state.dimTimer);
            state.dimTimer = null;
        }
        if (card) card.classList.remove('lp-tools-dim');
    }

    function scheduleToolsDim() {
        var card = $('lp-mushaf');
        if (!card || reduceMotion) return;
        clearToolsDim();
        state.dimTimer = setTimeout(function () {
            state.dimTimer = null;
            if (!card.classList.contains('is-ready')) return;
            if (card.matches(':hover') || card.contains(document.activeElement)) return;
            card.classList.add('lp-tools-dim');
        }, TOOLS_DIM_MS);
    }

    function sizeHeroPage() {
        var Chrome = window.AtharPageChrome;
        if (!Chrome || !Chrome.sizePages) return;
        Chrome.sizePages({
            cssVarPrefix: 'lp',
            pages: 1,
            ratio: state.src === 'qpc_v1' ? OLD_MADINA_PAGE_RATIO : PAGE_RATIO,
            gutter: 0,
            spreadPad: 0,
            minW: 220,
            minH: 340,
            getAvailH: function () {
                return Math.max(340, Math.min(window.innerHeight * 0.72, 620));
            },
            getAvailW: function () {
                var stage = $('lp-mushaf-stage');
                var w = stage ? stage.clientWidth : window.innerWidth * 0.42;
                return Math.max(220, Math.min(w - 24, 420));
            },
        });
    }

    function featureSettings() {
        return state.src === 'qpc_v1'
            ? '"ss01", "ss02", "ss03", "ss05", "ss08"'
            : '"ss01", "ss02", "ss03", "ss05", "ss08"';
    }

    function fitPage() {
        var Chrome = window.AtharPageChrome;
        var pageEl = $('lp-page');
        var card = $('lp-mushaf');
        if (!Chrome || !pageEl) return;
        var applyFont = Chrome.createFontSizer({
            cssVarName: '--lp-fs',
            pageEls: function () { return [pageEl]; },
            lineSelector: '.lp-line',
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
            featureSettings: featureSettings,
        });
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
        if (card) card.classList.add('is-ready');
    }

    /* ── tajweed overlay (same approach as تثبيت) ───────────────────── */
    function _isCombiningMark(cp) {
        return (cp >= 0x0610 && cp <= 0x061A) || (cp >= 0x064B && cp <= 0x065F)
            || (cp >= 0x06D6 && cp <= 0x06ED) || (cp >= 0x08D3 && cp <= 0x08FF)
            || cp === 0x0670;
    }
    function _alignSkeleton(ch) {
        var cp = ch.codePointAt(0);
        if (cp === 0x0622 || cp === 0x0623 || cp === 0x0625 || cp === 0x0627
            || cp === 0x0671 || cp === 0x0621 || cp === 0x0624 || cp === 0x0626) return 'A';
        if (cp === 0x0649 || cp === 0x064A) return 'Y';
        if (cp === 0x0629) return 'H';
        return ch;
    }
    function _alignDisplayToSource(srcChars, dispChars) {
        var n = srcChars.length, m = dispChars.length;
        var dp = Array.from({ length: n + 1 }, function () { return new Int32Array(m + 1); });
        var i, j;
        for (i = 1; i <= n; i++) dp[i][0] = dp[i - 1][0] - 1;
        for (j = 1; j <= m; j++) dp[0][j] = dp[0][j - 1] - 1;
        for (i = 1; i <= n; i++) for (j = 1; j <= m; j++) {
            var sc = _alignSkeleton(srcChars[i - 1]) === _alignSkeleton(dispChars[j - 1]) ? 2 : -1;
            dp[i][j] = Math.max(dp[i - 1][j - 1] + sc, dp[i - 1][j] - 1, dp[i][j - 1] - 1);
        }
        var res = new Array(m).fill(-1);
        i = n; j = m;
        while (i > 0 && j > 0) {
            var score = _alignSkeleton(srcChars[i - 1]) === _alignSkeleton(dispChars[j - 1]) ? 2 : -1;
            if (dp[i][j] === dp[i - 1][j - 1] + score) { res[j - 1] = i - 1; i--; j--; }
            else if (dp[i][j] === dp[i - 1][j] - 1) i--;
            else j--;
        }
        return res;
    }
    function overlayTajweedOnDisplay(dispWord, parts) {
        var srcChars = [], srcCls = [];
        (parts || []).forEach(function (p) {
            Array.from(p.text || '').forEach(function (ch) {
                srcChars.push(ch);
                srcCls.push(p.cls || '');
            });
        });
        var dispChars = Array.from(dispWord || '');
        var dcls = new Array(dispChars.length).fill('');
        if (srcChars.length && srcCls.some(Boolean)) {
            var amap = _alignDisplayToSource(srcChars, dispChars);
            for (var j = 0; j < dispChars.length; j++) {
                var si = amap[j];
                if (si >= 0) dcls[j] = srcCls[si];
            }
            var i = 0;
            while (i < dispChars.length) {
                var start = i; i++;
                while (i < dispChars.length && _isCombiningMark(dispChars[i].codePointAt(0))) i++;
                var chosen = '';
                for (var k = start; k < i; k++) { if (dcls[k]) { chosen = dcls[k]; break; } }
                for (k = start; k < i; k++) dcls[k] = chosen;
            }
        }
        function esc(s) {
            return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
        }
        var html = '', cur = null, buf = '';
        for (j = 0; j < dispChars.length; j++) {
            var cl = dcls[j];
            if (cl !== cur) {
                if (buf) html += cur ? '<tajweed class="' + cur + '">' + esc(buf) + '</tajweed>' : esc(buf);
                buf = '';
                cur = cl;
            }
            buf += dispChars[j];
        }
        if (buf) html += cur ? '<tajweed class="' + cur + '">' + esc(buf) + '</tajweed>' : esc(buf);
        return html;
    }
    function getNormalizedTajweedHtml(html) {
        var hamzaRe = /[ءأؤإئ]/;
        return String(html || '')
            .replace(/<span[^>]*class=["']?end["']?[^>]*>.*?<\/span>/gi, '')
            .trim()
            .replace(
                /(<tajweed\s+class=["']?madda_obligatory["']?>)([\s\S]*?)(<\/tajweed>)([\s\S]*?)(?= |$)/g,
                function (match, open, inner, close, after) {
                    return (!hamzaRe.test(inner) && !hamzaRe.test(after))
                        ? '<tajweed class="madda_munfasil">' + inner + '</tajweed>' + after
                        : match;
                }
            );
    }
    function parseTajweedIntoWords(html) {
        var tmp = document.createElement('div');
        tmp.innerHTML = html;
        var tokens = [];
        Array.from(tmp.childNodes).forEach(function (node) {
            if (node.nodeType === 3) {
                if (node.textContent) tokens.push({ text: node.textContent, cls: '' });
            } else if (node.nodeType === 1) {
                var cls = (node.getAttribute('class') || '').trim();
                if (cls === 'end') return;
                if (node.textContent) tokens.push({ text: node.textContent, cls: cls });
            }
        });
        var subTokens = [];
        tokens.forEach(function (tok) {
            var parts = tok.text.split(' ');
            for (var i = 0; i < parts.length; i++) {
                var isLast = i === parts.length - 1;
                if (parts[i]) subTokens.push({ text: parts[i], cls: tok.cls, boundary: !isLast });
                else if (!isLast) subTokens.push({ text: '', cls: tok.cls, boundary: true });
            }
        });
        var segments = [];
        var segParts = [];
        var segRules = new Set();
        function flush() {
            var combined = segParts.map(function (p) { return p.text; }).join('');
            if (combined.trim()) {
                var finalParts = segParts;
                if (segRules.has('madda_obligatory')) {
                    var hamzaRe = /[ءأؤإئ]/;
                    var madIdx = segParts.map(function (p) { return p.cls; }).lastIndexOf('madda_obligatory');
                    var tIn = (segParts[madIdx] && segParts[madIdx].text) || '';
                    var tAfter = segParts.slice(madIdx + 1).map(function (p) { return p.text; }).join('');
                    if (!hamzaRe.test(tIn) && !hamzaRe.test(tAfter)) {
                        finalParts = segParts.map(function (p) {
                            return p.cls === 'madda_obligatory' ? { text: p.text, cls: 'madda_munfasil' } : p;
                        });
                    }
                }
                segments.push({ parts: finalParts.map(function (p) { return { text: p.text, cls: p.cls }; }) });
            }
            segParts = [];
            segRules = new Set();
        }
        subTokens.forEach(function (sub) {
            if (sub.text) {
                segParts.push({ text: sub.text, cls: sub.cls });
                if (sub.cls) segRules.add(sub.cls);
            }
            if (sub.boundary) flush();
        });
        flush();
        return segments;
    }
    async function getTajweedSegments(surah, ayah) {
        var key = surah + ':' + ayah;
        if (state.tajweedCache.has(key)) return state.tajweedCache.get(key);
        var segments = [];
        try {
            var data = await window.AtharApi.json('/api/tajweed/' + surah + '/' + ayah);
            segments = parseTajweedIntoWords(getNormalizedTajweedHtml(data.html));
        } catch (e) {
            segments = [];
        }
        state.tajweedCache.set(key, segments);
        return segments;
    }
    function clearTajweedFromPage() {
        var pageEl = $('lp-page');
        if (!pageEl) return;
        pageEl.querySelectorAll('.lp-word[data-key]').forEach(function (span) {
            span.textContent = span.dataset.text || span.textContent || '';
        });
    }
    async function applyTajweedToPage(token) {
        if (!state.tajweedOn) return;
        var pageEl = $('lp-page');
        if (!pageEl) return;
        var ayahSpans = new Map();
        pageEl.querySelectorAll('.lp-word[data-key]').forEach(function (span) {
            var key = span.dataset.key;
            if (!ayahSpans.has(key)) ayahSpans.set(key, []);
            ayahSpans.get(key).push(span);
        });
        for (var entry of ayahSpans) {
            if (token != null && token !== state.renderToken) return;
            var key = entry[0];
            var spans = entry[1];
            var parts = key.split(':').map(Number);
            var segments = await getTajweedSegments(parts[0], parts[1]);
            if (!state.tajweedOn || (token != null && token !== state.renderToken)) return;
            spans.forEach(function (span) {
                var wpos = parseInt(span.dataset.wpos, 10);
                var seg = Number.isFinite(wpos) ? segments[wpos] : null;
                var disp = span.dataset.text || span.textContent || '';
                if (seg && seg.parts.some(function (p) { return p.cls; })) {
                    span.innerHTML = overlayTajweedOnDisplay(disp, seg.parts);
                } else {
                    span.textContent = disp;
                }
            });
        }
    }

    function renderHeroPage(payload) {
        var pageEl = $('lp-page');
        var juzEl = $('lp-juz');
        var surahEl = $('lp-surah');
        var footEl = $('lp-page-num');
        if (!pageEl || !window.AtharMushaf || !window.AtharPageChrome) return;

        var Chrome = window.AtharPageChrome;
        var surahHeaderGlyph = Chrome.surahHeaderGlyph;
        var token = ++state.renderToken;

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
            decorateWord: function (el, ctx) {
                var text = el.textContent || '';
                el.dataset.text = text;
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

        syncTools();
        sizeHeroPage();
        requestAnimationFrame(function () {
            requestAnimationFrame(function () {
                fitPage();
                scheduleToolsDim();
                if (state.tajweedOn) {
                    applyTajweedToPage(token).then(function () {
                        if (token === state.renderToken) requestAnimationFrame(fitPage);
                    });
                }
            });
        });
    }

    async function loadHeroMushaf() {
        var stage = $('lp-mushaf-stage');
        if (!stage || !window.AtharApi || !window.AtharMushaf) return;
        syncTools();
        try {
            var client = window.AtharMushaf.createPageClient({
                getSource: function () { return state.src; },
                getVersions: function () { return []; },
            });
            var payload = await client.byNumber(PAGE);
            if (!payload) throw new Error('empty page');
            state.payload = payload;
            stage.classList.remove('is-failed');
            renderHeroPage(payload);
        } catch (err) {
            stage.classList.add('is-failed');
        }
    }

    function bindTools() {
        var card = $('lp-mushaf');
        if (card) {
            card.addEventListener('mouseenter', clearToolsDim);
            card.addEventListener('focusin', clearToolsDim);
            card.addEventListener('mouseleave', scheduleToolsDim);
            card.addEventListener('focusout', function (e) {
                if (!card.contains(e.relatedTarget)) scheduleToolsDim();
            });
        }
        document.querySelectorAll('.lp-src-btn').forEach(function (btn) {
            btn.addEventListener('click', function () {
                var next = btn.getAttribute('data-src');
                if (!next || next === state.src) return;
                clearToolsDim();
                state.src = next;
                if (card) card.classList.remove('is-ready');
                syncTools();
                loadHeroMushaf();
            });
        });
        var tj = $('lp-tajweed');
        if (tj) {
            tj.addEventListener('click', function () {
                clearToolsDim();
                state.tajweedOn = !state.tajweedOn;
                syncTools();
                if (!state.tajweedOn) {
                    clearTajweedFromPage();
                    requestAnimationFrame(fitPage);
                    scheduleToolsDim();
                    return;
                }
                var token = state.renderToken;
                applyTajweedToPage(token).then(function () {
                    if (token === state.renderToken) requestAnimationFrame(fitPage);
                    scheduleToolsDim();
                });
            });
        }
    }

    var resizeTimer;
    window.addEventListener('resize', function () {
        clearTimeout(resizeTimer);
        resizeTimer = setTimeout(function () {
            var card = $('lp-mushaf');
            if (!card || !card.classList.contains('is-ready')) return;
            sizeHeroPage();
            requestAnimationFrame(fitPage);
        }, 120);
    });

    revealCards();
    bindTools();
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', loadHeroMushaf);
    } else {
        loadHeroMushaf();
    }
})();
