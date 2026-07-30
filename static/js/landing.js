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

    /** Strip Madinah waqf glyphs, then add ۝ around bare ayah digits (Azhar). */
    function displayWordText(raw) {
        var Mushaf = window.AtharMushaf;
        if (!Mushaf) return raw || '';
        return Mushaf.withAyahOrnament(Mushaf.stripEmbeddedWaqf(raw));
    }

    function lineSlotCount(payload) {
        if (!payload) return 15;
        var n = Number(payload.lines_per_page);
        if (n > 0) return n;
        var len = (payload.lines || []).length;
        return len > 0 ? len : 15;
    }

    function applyLineSlots(pageEl, payload) {
        if (!pageEl) return;
        pageEl.style.setProperty('--lp-line-slots', String(lineSlotCount(payload)));
    }

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
        document.querySelectorAll('.lp-src-btn[data-src]').forEach(function (btn) {
            var on = btn.getAttribute('data-src') === state.src;
            btn.setAttribute('aria-pressed', String(on));
        });
        var tj = $('lp-tajweed');
        if (tj) {
            tj.hidden = state.src === 'azhar';
            tj.setAttribute('aria-pressed', String(state.tajweedOn && state.src !== 'azhar'));
        }
        var card = $('lp-mushaf');
        if (!card) return;
        card.classList.toggle('lp-src-digital-khatt', state.src === 'digital_khatt');
        card.classList.toggle('lp-src-qpc-v1', state.src === 'qpc_v1');
        card.classList.toggle('lp-src-azhar', state.src === 'azhar');
        card.classList.toggle('lp-tajweed', state.tajweedOn && state.src !== 'azhar');
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

    /* Page box + font fit + justify — same AtharPageChrome path as تثبيت. */
    function pageEls() {
        var pageEl = $('lp-page');
        return pageEl ? [pageEl] : [];
    }

    function sizeHeroPage() {
        var Chrome = window.AtharPageChrome;
        if (!Chrome || !Chrome.sizePages) return;
        Chrome.sizePages({
            cssVarPrefix: 'lp',
            pages: 1,
            ratio: state.src === 'qpc_v1' ? OLD_MADINA_PAGE_RATIO
                : (state.src === 'azhar' ? 0.68 : PAGE_RATIO),
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

    var applyFontSize = window.AtharPageChrome.createFontSizer({
        pageEls: pageEls,
        lineSelector: '.lp-line',
        innerSelector: '.lp-line-inner',
        cssVarName: '--lp-fs',
        linesPerPage: function () { return lineSlotCount(state.payload); },
        cacheKey: function () {
            return state.src + '|' + lineSlotCount(state.payload);
        },
        minFontSize: 9.5,
        minLineScale: function () {
            return state.src === 'qpc_v1' || state.src === 'digital_khatt' ? 0.95 : 0;
        },
        maxPageFitRatio: 1.15,
    });

    var justifyLines = window.AtharPageChrome.createLineJustifier({
        containerEls: pageEls,
        lineSelector: '.lp-line',
        innerSelector: '.lp-line-inner',
        wordSelector: '.lp-word',
        featureCandidates: function () {
            var Chrome = window.AtharPageChrome;
            if (state.src === 'qpc_v1') return Chrome.oldMadinaFeatureCandidates(100);
            if (state.src === 'digital_khatt') return Chrome.digitalKhattFeatureCandidates(100);
            return [];
        },
        minFeatureScale: function () {
            return state.src === 'qpc_v1' || state.src === 'digital_khatt' ? 0.95 : 1;
        },
        maxWordSpacing: function (_lineEl, inner) {
            if (state.src === 'azhar') {
                var azFs = parseFloat(getComputedStyle(inner).fontSize) || 20;
                return Math.max(2, Math.min(6, azFs * 0.18));
            }
            if (state.src !== 'qpc_v1' && state.src !== 'digital_khatt') return Infinity;
            var fontSize = parseFloat(getComputedStyle(inner).fontSize) || 20;
            return Math.max(1.5, Math.min(4, fontSize * 0.12));
        },
        maxStretch: function () {
            if (state.src === 'digital_khatt') return 1.15;
            if (state.src === 'qpc_v1') return 1.18;
            if (state.src === 'azhar') return 1.12;
            return Infinity;
        },
    });

    function fitPage() {
        var card = $('lp-mushaf');
        if (!pageEls().length) return;
        sizeHeroPage();
        applyFontSize(true);
        requestAnimationFrame(function () {
            justifyLines();
            if (card) card.classList.add('is-ready');
        });
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
                return displayWordText(ctx.raw);
            },
            decorateWord: function (el, ctx) {
                var text = el.textContent || '';
                el.dataset.text = text;
                if (text.charAt(0) === '\u06DD') el.classList.add('lp-ayah-end');
            },
            decorateLine: function (el, ctx) {
                if ((ctx.line.words || []).length) {
                    el.dataset.justify = ctx.line.is_centered ? '0' : '1';
                }
            },
        });
        applyLineSlots(pageEl, payload);

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
        requestAnimationFrame(function () {
            requestAnimationFrame(function () {
                fitPage();
                scheduleToolsDim();
                if (state.tajweedOn && state.src !== 'azhar') {
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
            // Azhar layout starts at page 2 (no page 1); Madinah sources use page 1.
            var payload = state.src === 'azhar'
                ? await client.byNumber(2)
                : await client.byNumber(PAGE);
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
        document.querySelectorAll('.lp-src-btn[data-src]').forEach(function (btn) {
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
            fitPage();
        }, 120);
    });

    function toArDigits(n) {
        return String(n).replace(/\d/g, function (d) {
            return '٠١٢٣٤٥٦٧٨٩'[d];
        });
    }

    function escapeHtml(s) {
        return String(s)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    var WAQF_SYM_CLS = {
        'م': 'is-must', 'لا': 'is-no', 'ق': 'is-pstop', 'ص': 'is-pcont',
        'ج': 'is-ok', 'س': 'is-ok', 'ع': 'is-ok',
        'ۘ': 'is-must', 'ۗ': 'is-pstop', 'ۖ': 'is-pcont', 'ۚ': 'is-ok',
        'ۙ': 'is-no', 'ۛ': 'is-ok', 'ۜ': 'is-ok',
    };

    function initKursiDemo() {
        var root = $('lp-kursi');
        if (!root || !window.AtharApi || !window.AtharMushaf) return;

        var Mushaf = window.AtharMushaf;
        var Chrome = window.AtharPageChrome;
        var els = {
            status: $('lp-kursi-status'),
            verse: $('lp-kursi-verse'),
            caption: $('lp-kursi-caption'),
            meta: $('lp-kursi-meta'),
            legend: $('lp-kursi-legend'),
            lens: $('lp-kursi-lens'),
            editions: $('lp-kursi-editions'),
            page: $('lp-kursi-page-body'),
            pageCard: $('lp-kursi-page'),
            stage: $('lp-kursi-mushaf-stage'),
            juz: $('lp-kursi-juz'),
            surah: $('lp-kursi-surah'),
            pageNum: $('lp-kursi-page-num'),
        };
        var surah = Number(root.getAttribute('data-surah')) || 2;
        var ayah = Number(root.getAttribute('data-ayah')) || 255;
        var verseKey = surah + ':' + ayah;
        var preferredEditions = ['المدينة الجديد', 'الأزهر', 'الشمرلي'];
        var demo = {
            lens: 'mushaf',
            editionId: null,
            src: 'digital_khatt',
            waqf: null,
            classical: null,
            payload: null,
            pageToken: 0,
        };

        function setStatus(msg) {
            if (!els.status) return;
            els.status.hidden = !msg;
            els.status.textContent = msg || '';
        }

        function syncLensButtons() {
            if (!els.lens) return;
            els.lens.querySelectorAll('[data-lens]').forEach(function (btn) {
                btn.setAttribute(
                    'aria-pressed',
                    String(btn.getAttribute('data-lens') === demo.lens)
                );
            });
            if (els.editions) els.editions.hidden = demo.lens !== 'mushaf';
        }

        function syncSrcButtons() {
            root.querySelectorAll('[data-kursi-src]').forEach(function (btn) {
                btn.setAttribute(
                    'aria-pressed',
                    String(btn.getAttribute('data-kursi-src') === demo.src)
                );
            });
        }

        function buildEditionButtons(mushafs) {
            if (!els.editions) return;
            var list = (mushafs || []).filter(function (m) {
                return preferredEditions.indexOf(m.id) !== -1;
            });
            if (!list.length) list = (mushafs || []).slice(0, 3);
            if (!list.length) {
                els.editions.hidden = true;
                return;
            }
            if (!demo.editionId) demo.editionId = list[0].id;
            els.editions.innerHTML = list.map(function (m) {
                var on = m.id === demo.editionId;
                return '<button type="button" class="lp-src-btn" data-edition="'
                    + escapeHtml(m.id) + '" aria-pressed="' + String(on) + '">'
                    + escapeHtml(m.name || m.id) + '</button>';
            }).join('');
            els.editions.hidden = demo.lens !== 'mushaf';
        }

        function mushafGlyphNode(sym, mushafId) {
            var data = Mushaf.getWaqfDisplayData(sym, mushafId);
            if (!data) return null;
            var glyphs = Mushaf.displaySymbols(data.text, mushafId);
            if (!glyphs.length) return null;
            var span = document.createElement('span');
            var cls = WAQF_SYM_CLS[sym] || WAQF_SYM_CLS[glyphs[0]] || 'is-ok';
            span.className = 'lp-kursi-glyph ' + cls;
            span.textContent = glyphs.join('');
            span.title = sym;
            return span;
        }

        function stopChipNode(u, total) {
            var chip = document.createElement('span');
            chip.className = 'lp-kursi-chip' + (u.solo ? ' is-solo' : '');
            chip.style.setProperty('--s', (u.count / Math.max(total, 1)).toFixed(2));
            chip.innerHTML = u.solo
                ? '<b>انفرد</b>'
                : '<b>' + toArDigits(u.count) + '/' + toArDigits(total) + '</b>';
            chip.title = (u.reciters || []).join('، ');
            return chip;
        }

        function classicalChipNode(entry) {
            var chip = document.createElement('span');
            chip.className = 'lp-kursi-chip is-classical';
            chip.innerHTML = '<b>' + escapeHtml(entry.grade || entry.grade_raw || 'وقف') + '</b>';
            chip.title = entry.note || entry.quote || '';
            return chip;
        }

        function marksForLens() {
            var map = Object.create(null);
            if (!demo.waqf) return map;
            if (demo.lens === 'mushaf') {
                var mushafs = demo.waqf.mushafs || [];
                var chosen = null;
                for (var i = 0; i < mushafs.length; i++) {
                    if (mushafs[i].id === demo.editionId) { chosen = mushafs[i]; break; }
                }
                if (!chosen) chosen = mushafs[0];
                (chosen && chosen.marks || []).forEach(function (m) {
                    map[m.wpos] = { kind: 'mushaf', symbol: m.symbol, edition: chosen.id };
                });
                return map;
            }
            if (demo.lens === 'reciters') {
                (demo.waqf.union_stops || []).forEach(function (s) {
                    map[s.wpos] = { kind: 'reciter', stop: s };
                });
                return map;
            }
            ((demo.classical && demo.classical.entries) || []).forEach(function (e) {
                if (e.wpos == null) return;
                map[e.wpos] = { kind: 'classical', entry: e };
            });
            return map;
        }

        function captionForLens() {
            if (demo.lens === 'mushaf') {
                return 'علامات الطبعة المختارة بصورها من الخط العثماني — بدّل المدينة / الأزهر / الشمرلي.';
            }
            if (demo.lens === 'reciters') {
                var total = Number(demo.waqf && demo.waqf.reciters_total)
                    || ((demo.waqf && demo.waqf.reciters) || []).length || 0;
                return 'شرائح مُكْث: كم قارئًا وقف هنا من أصل ' + toArDigits(total) + '.';
            }
            var n = ((demo.classical && demo.classical.entries) || []).length;
            if (!n) return 'لا بيانات كلاسيكية جاهزة لهذا الموضع في المحاكاة.';
            return 'درجات الوقف عند الأشموني (منار الهدى) على الكلمات نفسها.';
        }

        function legendForLens() {
            if (!els.legend) return;
            if (demo.lens === 'mushaf') {
                els.legend.hidden = false;
                els.legend.innerHTML =
                    '<span><span class="lp-kursi-glyph is-must">ۘ</span> لازم</span>'
                    + '<span><span class="lp-kursi-glyph is-pstop">ۗ</span> قلى</span>'
                    + '<span><span class="lp-kursi-glyph is-ok">ۚ</span> جائز</span>'
                    + '<span><span class="lp-kursi-glyph is-pcont">ۖ</span> صلى</span>';
                return;
            }
            if (demo.lens === 'reciters') {
                els.legend.hidden = false;
                els.legend.innerHTML =
                    '<span>الرقم = اتفاق القرّاء على الوقف</span>'
                    + '<span>انفرد = قارئ واحد فقط</span>';
                return;
            }
            els.legend.hidden = false;
            els.legend.innerHTML = '<span>كاف / حسن / تام — من كتب الوقف</span>';
        }

        function renderVerse() {
            if (!demo.waqf || !els.verse) return;
            var marks = marksForLens();
            var total = Number(demo.waqf.reciters_total)
                || ((demo.waqf.reciters) || []).length || 1;
            Mushaf.renderWordRun(els.verse, demo.waqf.words || [], {
                separator: '',
                classForWord: function (ctx) {
                    return marks[ctx.index]
                        ? 'lp-kursi-word is-stop'
                        : 'lp-kursi-word';
                },
                textForWord: function (ctx) {
                    return displayWordText(ctx.raw);
                },
                afterWord: function (_el, ctx) {
                    var info = marks[ctx.index];
                    if (!info) return null;
                    if (info.kind === 'mushaf') {
                        return mushafGlyphNode(info.symbol, info.edition);
                    }
                    if (info.kind === 'reciter') {
                        return stopChipNode(info.stop, total);
                    }
                    return classicalChipNode(info.entry);
                },
            });
            els.verse.hidden = false;
            if (els.meta) {
                var nStops = (demo.waqf.union_stops || []).length;
                els.meta.hidden = false;
                els.meta.textContent = 'البقرة · آية '
                    + toArDigits(ayah) + ' · '
                    + toArDigits(total) + ' قرّاء · '
                    + toArDigits(nStops) + ' مواضع وقف';
            }
            if (els.caption) {
                els.caption.hidden = false;
                els.caption.textContent = captionForLens();
            }
            legendForLens();
            setStatus('');
            syncLensButtons();
        }

        var kursiPageEls = function () {
            return els.page ? [els.page] : [];
        };
        var applyKursiFont = Chrome && Chrome.createFontSizer
            ? Chrome.createFontSizer({
                pageEls: kursiPageEls,
                lineSelector: '.lp-line',
                innerSelector: '.lp-line-inner',
                cssVarName: '--lp-fs',
                linesPerPage: function () { return lineSlotCount(demo.payload); },
                cacheKey: function () {
                    return 'kursi|' + demo.src + '|' + lineSlotCount(demo.payload);
                },
                minFontSize: 8.5,
                minLineScale: function () {
                    return demo.src === 'qpc_v1' || demo.src === 'digital_khatt' ? 0.95 : 0;
                },
                maxPageFitRatio: 1.15,
            })
            : null;
        var justifyKursi = Chrome && Chrome.createLineJustifier
            ? Chrome.createLineJustifier({
                containerEls: kursiPageEls,
                lineSelector: '.lp-line',
                innerSelector: '.lp-line-inner',
                wordSelector: '.lp-word',
                    featureCandidates: function () {
                    if (demo.src === 'qpc_v1') return Chrome.oldMadinaFeatureCandidates(100);
                    if (demo.src === 'digital_khatt') return Chrome.digitalKhattFeatureCandidates(100);
                    return [];
                },
                minFeatureScale: function () {
                    return demo.src === 'qpc_v1' || demo.src === 'digital_khatt' ? 0.95 : 1;
                },
                maxWordSpacing: function (_lineEl, inner) {
                    if (demo.src === 'azhar') {
                        var azFs = parseFloat(getComputedStyle(inner).fontSize) || 18;
                        return Math.max(2, Math.min(6, azFs * 0.18));
                    }
                    if (demo.src !== 'qpc_v1' && demo.src !== 'digital_khatt') return Infinity;
                    var fontSize = parseFloat(getComputedStyle(inner).fontSize) || 18;
                    return Math.max(1.2, Math.min(3.5, fontSize * 0.12));
                },
                maxStretch: function () {
                    if (demo.src === 'digital_khatt') return 1.15;
                    if (demo.src === 'qpc_v1') return 1.18;
                    if (demo.src === 'azhar') return 1.12;
                    return Infinity;
                },
            })
            : null;

        function sizeKursiPage() {
            if (!Chrome || !Chrome.sizePages || !els.pageCard) return;
            Chrome.sizePages({
                cssVarPrefix: 'lp-kursi',
                pages: 1,
                ratio: demo.src === 'qpc_v1' ? OLD_MADINA_PAGE_RATIO
                    : (demo.src === 'azhar' ? 0.68 : PAGE_RATIO),
                gutter: 0,
                spreadPad: 0,
                minW: 180,
                minH: 280,
                getAvailH: function () {
                    return Math.max(280, Math.min(window.innerHeight * 0.55, 480));
                },
                getAvailW: function () {
                    var stage = els.stage;
                    var w = stage ? stage.clientWidth : 280;
                    return Math.max(180, Math.min(w - 8, 340));
                },
            });
            if (applyKursiFont) applyKursiFont(true);
            requestAnimationFrame(function () {
                if (justifyKursi) justifyKursi();
            });
        }

        function renderKursiPage(payload) {
            if (!els.page || !Chrome) return;
            var token = ++demo.pageToken;
            Mushaf.renderMushafLines(els.page, payload.lines || [], {
                lineClass: 'lp-line',
                contentClass: 'lp-line-inner',
                wordClass: 'lp-word',
                surahClass: 'lp-line-surah',
                basmalaClass: 'lp-line-basmala',
                textForSpecial: function (ctx) {
                    if (ctx.kind === 'surah') {
                        return Chrome.surahHeaderGlyph(ctx.line.surah_number)
                            || ctx.line.display_text || '';
                    }
                    return BASMALA_GLYPH;
                },
                decorateSpecial: function (el, ctx) {
                    if (ctx.kind === 'surah' && Chrome.surahHeaderGlyph(ctx.line.surah_number)) {
                        el.classList.add('lp-surah-glyph');
                    }
                },
                textForWord: function (ctx) {
                    return displayWordText(ctx.raw);
                },
                decorateWord: function (el, ctx) {
                    var text = el.textContent || '';
                    el.dataset.text = text;
                    if (text.charAt(0) === '\u06DD') el.classList.add('lp-ayah-end');
                    if (ctx.verseKey === verseKey) el.classList.add('is-kursi');
                },
                decorateLine: function (el, ctx) {
                    if ((ctx.line.words || []).length) {
                        el.dataset.justify = ctx.line.is_centered ? '0' : '1';
                    }
                },
            });
            demo.payload = payload;
            applyLineSlots(els.page, payload);
            Chrome.renderPageChrome({
                payload: payload,
                juzEl: els.juz,
                surahEl: els.surah,
                pageNumberEl: els.pageNum,
                juzGlyphClass: 'athar-page-juz-glyph',
                surahGlyphClass: 'athar-page-surah-glyph',
                surahTextClass: 'athar-page-surah-text',
            });
            if (els.pageCard) {
                els.pageCard.classList.toggle('lp-src-digital-khatt', demo.src === 'digital_khatt');
                els.pageCard.classList.toggle('lp-src-qpc-v1', demo.src === 'qpc_v1');
                els.pageCard.classList.toggle('lp-src-azhar', demo.src === 'azhar');
                els.pageCard.classList.add('is-ready');
            }
            requestAnimationFrame(function () {
                if (token !== demo.pageToken) return;
                requestAnimationFrame(sizeKursiPage);
            });
        }

        async function loadKursiPage() {
            if (!els.stage) return;
            syncSrcButtons();
            try {
                var client = Mushaf.createPageClient({
                    getSource: function () { return demo.src; },
                    getVersions: function () { return []; },
                });
                var payload = await client.byAyah(surah, ayah);
                if (!payload) throw new Error('empty');
                if (els.stage) els.stage.classList.remove('is-failed');
                renderKursiPage(payload);
            } catch (err) {
                if (els.stage) els.stage.classList.add('is-failed');
            }
        }

        if (els.lens) {
            els.lens.addEventListener('click', function (ev) {
                var btn = ev.target.closest('[data-lens]');
                if (!btn) return;
                demo.lens = btn.getAttribute('data-lens') || 'mushaf';
                renderVerse();
            });
        }
        if (els.editions) {
            els.editions.addEventListener('click', function (ev) {
                var btn = ev.target.closest('[data-edition]');
                if (!btn) return;
                demo.editionId = btn.getAttribute('data-edition');
                els.editions.querySelectorAll('[data-edition]').forEach(function (b) {
                    b.setAttribute(
                        'aria-pressed',
                        String(b.getAttribute('data-edition') === demo.editionId)
                    );
                });
                renderVerse();
            });
        }
        root.querySelectorAll('[data-kursi-src]').forEach(function (btn) {
            btn.addEventListener('click', function () {
                demo.src = btn.getAttribute('data-kursi-src') || 'digital_khatt';
                loadKursiPage();
            });
        });

        var resizeTimer;
        window.addEventListener('resize', function () {
            clearTimeout(resizeTimer);
            resizeTimer = setTimeout(sizeKursiPage, 120);
        });

        setStatus('جارٍ تحميل محاكاة آية الكرسي…');
        loadKursiPage();
        Promise.all([
            window.AtharApi.json('/api/waqf/' + surah + '/' + ayah),
            window.AtharApi.json('/api/classical-waqf/' + surah + '/' + ayah).catch(function () {
                return null;
            }),
        ]).then(function (pair) {
            demo.waqf = pair[0];
            demo.classical = pair[1];
            if (!demo.waqf || !(demo.waqf.words || []).length) {
                setStatus('تعذّر تحميل محاكاة الآية.');
                return;
            }
            buildEditionButtons(demo.waqf.mushafs || []);
            renderVerse();
        }).catch(function () {
            setStatus('تعذّر تحميل محاكاة الآية. جرّب مُكْث لاحقًا.');
        });
    }

    revealCards();
    bindTools();
    initKursiDemo();
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', loadHeroMushaf);
    } else {
        loadHeroMushaf();
    }
})();
