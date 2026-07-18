/* ═══════════════════════════════════════════════════════════════════
   أثَر — shared mushaf page CHROME: sizing, line-justification, running
   juz/surah head data, page-number labels, and empty-state rendering.

   Deliberately separate from athar-mushaf.js (that module's own header
   says page-specific typography/sizing stays out of its scope — this file
   is exactly that: the "how big, how justified, what's the running head"
   concern, extracted from تثبيت (mushaf_memorize.js, the more mature/
   canonical implementation) so مصحف-editor stops re-porting a drifted
   copy of the same code.

   Every consumer supplies its own selectors/CSS-var-prefix/class names —
   same "caller owns its DOM contract" convention as
   AtharMushaf.renderMushafLines. No mz-/ed- prefix is hardcoded here.
   ═══════════════════════════════════════════════════════════════════ */
(function () {
    'use strict';

    const toAr = n => String(n).replace(/[0-9]/g, d => '٠١٢٣٤٥٦٧٨٩'[d]);
    const pageNumberLabel = n => `صفحة ${toAr(n)}`;

    /* ── Juz ─────────────────────────────────────────────────────────── */
    const JUZ_START_PAGE = [1, 22, 42, 62, 82, 102, 121, 142, 162, 182,
        201, 222, 242, 262, 282, 302, 322, 342, 362, 382,
        402, 422, 442, 462, 482, 502, 522, 542, 562, 582];
    const JUZ_NAME = ['الأول', 'الثاني', 'الثالث', 'الرابع', 'الخامس', 'السادس',
        'السابع', 'الثامن', 'التاسع', 'العاشر', 'الحادي عشر', 'الثاني عشر',
        'الثالث عشر', 'الرابع عشر', 'الخامس عشر', 'السادس عشر', 'السابع عشر',
        'الثامن عشر', 'التاسع عشر', 'العشرون', 'الحادي والعشرون', 'الثاني والعشرون',
        'الثالث والعشرون', 'الرابع والعشرون', 'الخامس والعشرون', 'السادس والعشرون',
        'السابع والعشرون', 'الثامن والعشرون', 'التاسع والعشرون', 'الثلاثون'];
    function juzNumber(pageNumber) {
        let j = 1;
        for (let i = 0; i < JUZ_START_PAGE.length; i++) {
            if (pageNumber >= JUZ_START_PAGE[i]) j = i + 1; else break;
        }
        return j;
    }
    // Juz' start boundaries as [surah, ayah] (Hafs/Madina, Tanzil standard). Used
    // when the page number isn't the 604-page Madina numbering — e.g. Shemrly,
    // whose layout-DB pages don't line up with JUZ_START_PAGE — so the juz can be
    // derived from the surah/ayah on the page instead.
    const JUZ_START_AYAH = [[1,1],[2,142],[2,253],[3,92],[4,24],[4,148],[5,82],[6,111],
        [7,88],[8,41],[9,93],[11,6],[12,53],[15,1],[17,1],[18,75],[21,1],[23,1],[25,21],
        [27,56],[29,46],[33,31],[36,28],[39,32],[41,47],[46,1],[51,31],[58,1],[67,1],[78,1]];
    function juzFromAyah(surah, ayah) {
        if (!surah) return 1;
        let j = 1;
        for (let i = 0; i < JUZ_START_AYAH.length; i++) {
            const [s, a] = JUZ_START_AYAH[i];
            if (surah > s || (surah === s && ayah >= a)) j = i + 1; else break;
        }
        return j;
    }
    // QCF Common font: each juz NAME is one glyph at U+E000+juz (E01E = الجزء الثلاثون).
    const juzGlyph = j => (j >= 1 && j <= 30) ? String.fromCodePoint(0xE000 + j) : '';

    /* ── Surah-name banner glyphs (surah_names.woff2): glyph-id rank == surah,
       so surah N → SURAH_HEADER_CP[N-1] (NOT codepoint order). ───────────── */
    const SURAH_HEADER_CP = [
        0xFC45, 0xFC46, 0xFC47, 0xFC4A, 0xFC4B, 0xFC4E, 0xFC4F, 0xFC51, 0xFC52, 0xFC53,
        0xFC55, 0xFC56, 0xFC58, 0xFC5A, 0xFC5B, 0xFC5C, 0xFC5D, 0xFC5E, 0xFC61, 0xFC62,
        0xFC64, 0xFB51, 0xFB52, 0xFB54, 0xFB55, 0xFB57, 0xFB58, 0xFB5A, 0xFB5B, 0xFB5D,
        0xFB5E, 0xFB60, 0xFB61, 0xFB63, 0xFB64, 0xFB66, 0xFB67, 0xFB69, 0xFB6A, 0xFB6C,
        0xFB6D, 0xFB6F, 0xFB70, 0xFB72, 0xFB73, 0xFB75, 0xFB76, 0xFB78, 0xFB79, 0xFB7B,
        0xFB7C, 0xFB7E, 0xFB7F, 0xFB81, 0xFB82, 0xFB84, 0xFB85, 0xFB87, 0xFB88, 0xFB8A,
        0xFB8B, 0xFB8D, 0xFB8E, 0xFB90, 0xFB91, 0xFB93, 0xFB94, 0xFB96, 0xFB97, 0xFB99,
        0xFB9A, 0xFB9C, 0xFB9D, 0xFB9F, 0xFBA0, 0xFBA2, 0xFBA3, 0xFBA5, 0xFBA6, 0xFBA8,
        0xFBA9, 0xFBAB, 0xFBAC, 0xFBAE, 0xFBAF, 0xFBB1, 0xFBB2, 0xFBB4, 0xFBB5, 0xFBB7,
        0xFBB8, 0xFBBA, 0xFBBB, 0xFBBD, 0xFBBE, 0xFBC0, 0xFBC1, 0xFBD3, 0xFBD4, 0xFBD6,
        0xFBD7, 0xFBD9, 0xFBDA, 0xFBDC, 0xFBDD, 0xFBDF, 0xFBE0, 0xFBE2, 0xFBE3, 0xFBE5,
        0xFBE6, 0xFBE8, 0xFBE9, 0xFBEB,
    ];
    const surahHeaderGlyph = n => (n >= 1 && n <= 114) ? String.fromCodePoint(SURAH_HEADER_CP[n - 1]) : '';

    /* ── Page sizing ─────────────────────────────────────────────────────
       Fits `pages` page-cards into an available box at a fixed mushaf
       ratio, writing --{cssVarPrefix}-page-w/-h onto <html>. The available
       box itself is 100% caller-defined (getAvailH/getAvailW). Both consumers
       subtract their own fixed chrome from the viewport rather than measuring
       a page-dependent stage height (which creates a growth feedback loop),
       while this function owns only the shared fit math. */
    function sizePages(config) {
        const {
            getAvailH, getAvailW, cssVarPrefix,
            pages = 2, ratio = 0.66, gutter = 0, spreadPad = 0,
            minW = 150, minH = 230, floor = false,
        } = config || {};
        if (typeof getAvailH !== 'function' || typeof getAvailW !== 'function' || !cssVarPrefix) return;
        const pageCount = Math.max(1, Math.floor(Number(pages) || 1));
        const pageRatio = Number.isFinite(Number(ratio)) && Number(ratio) > 0 ? Number(ratio) : 0.66;
        const measuredH = Number(getAvailH());
        const measuredW = Number(getAvailW());
        const availH = Math.max(minH, Number.isFinite(measuredH) ? measuredH : minH);
        const availW = Math.max(minW, Number.isFinite(measuredW) ? measuredW : minW);
        const g = pageCount > 1 ? Math.max(0, Number(gutter) || 0) : 0;
        const pad = Math.max(0, Number(spreadPad) || 0);
        let h = availH;
        let w = h * pageRatio;
        const totalW = w * pageCount + g + pad;
        if (totalW > availW) {
            // A very narrow host can leave less room than its own gutters. Keep
            // the scale positive; the caller's minW/minH then deliberately makes
            // the stage scroll instead of producing negative CSS dimensions.
            const widthBudget = Math.max(1, availW - g - pad);
            const s = widthBudget / (w * pageCount);
            w *= s; h *= s;
        }
        w = Math.max(minW, floor ? Math.floor(w) : w);
        h = Math.max(minH, floor ? Math.floor(h) : h);
        document.documentElement.style.setProperty(`--${cssVarPrefix}-page-w`, w + 'px');
        document.documentElement.style.setProperty(`--${cssVarPrefix}-page-h`, h + 'px');
        return { width: w, height: h };
    }

    /* ── Font sizing ─────────────────────────────────────────────────────
       Picks one font size per fitted page box so a typical line ~fills the
       line width, memoized on `cacheKey()` so paging never rescales (only
       a real viewport/source/layout change, or an explicit force, re-fits). */
    function createFontSizer(config) {
        const {
            pageEls, lineSelector, innerSelector, cssVarName,
            linesPerPage = 15, cacheKey = () => '', fitScale = 1,
            minLineScale = 0, minFontSize = 11, sharedSize = true,
            maxPageFitRatio = Infinity,
        } = config || {};
        let fitFs = 0, fitValues = [], fitKey = '';
        return function applyFontSize(force) {
            const pages = (typeof pageEls === 'function' ? pageEls() : []).filter(Boolean);
            if (!pages.length) return;
            const key = `${cacheKey()}|${Math.round(pages[0].clientHeight)}|${Math.round(pages[0].clientWidth)}`;
            if (!force && key === fitKey && fitFs) {
                pages.forEach((p, i) => p.style.setProperty(
                    cssVarName,
                    ((sharedSize ? fitFs : fitValues[i]) || fitFs) + 'px'
                ));
                return;
            }
            let chosen = 0;
            const fitted = [];
            pages.forEach(p => {
                const h = p.clientHeight || 1;
                const lineH = h / linesPerPage;
                const maxFs = lineH * 0.92;
                const rawMinFontSize = typeof minFontSize === 'function' ? minFontSize(p) : minFontSize;
                const resolvedMinFontSize = Number.isFinite(Number(rawMinFontSize))
                    ? Math.max(8, Math.min(16, Number(rawMinFontSize)))
                    : 11;
                let fs = Math.max(resolvedMinFontSize, lineH * 0.62);
                p.style.setProperty(cssVarName, fs + 'px');

                const inners = [...p.querySelectorAll(`${lineSelector}[data-justify="1"] ${innerSelector}`)];
                const ratios = [];
                inners.forEach(inner => {
                    inner.style.transform = 'none';
                    inner.style.fontFeatureSettings = '';
                    inner.style.fontVariationSettings = '';
                    inner.style.wordSpacing = '';
                    const avail = inner.parentElement.clientWidth;
                    const nat = inner.scrollWidth;
                    if (nat > 0 && avail > 0) ratios.push(avail / nat);
                });
                if (ratios.length) {
                    ratios.sort((a, b) => a - b);
                    const med = ratios[Math.floor(ratios.length / 2)] || 1;
                    const rawFitScale = typeof fitScale === 'function' ? fitScale(p) : fitScale;
                    const resolvedFitScale = Number.isFinite(Number(rawFitScale))
                        ? Math.max(0.75, Math.min(1.25, Number(rawFitScale)))
                        : 1;
                    const rawMinLineScale = typeof minLineScale === 'function'
                        ? minLineScale(p)
                        : minLineScale;
                    const resolvedMinLineScale = Number.isFinite(Number(rawMinLineScale))
                        ? Math.max(0, Math.min(1, Number(rawMinLineScale)))
                        : 0;
                    const typicalFit = fs * med * 0.98 * resolvedFitScale;
                    // Median fitting keeps a typical line attractive, but can
                    // make an unusually long line 10–17% narrower via scaleX.
                    // When requested, cap that distortion by lowering the whole
                    // page's font size before per-line justification runs.
                    const compressionFit = resolvedMinLineScale > 0
                        ? fs * ratios[0] * 0.99 / resolvedMinLineScale
                        : Infinity;
                    fs = Math.max(resolvedMinFontSize, Math.min(maxFs, typicalFit, compressionFit));
                }
                fitted.push(fs);
                chosen = chosen ? Math.min(chosen, fs) : fs;
            });
            if (chosen) {
                const rawMaxPageFitRatio = Number(maxPageFitRatio);
                const resolvedMaxPageFitRatio = Number.isFinite(rawMaxPageFitRatio)
                    ? Math.max(1, Math.min(2, rawMaxPageFitRatio))
                    : Infinity;
                const appliedFits = fitted.map(fs => Math.min(fs, chosen * resolvedMaxPageFitRatio));
                fitFs = chosen; fitValues = appliedFits; fitKey = key;
                pages.forEach((p, i) => p.style.setProperty(
                    cssVarName,
                    (sharedSize ? chosen : (appliedFits[i] || chosen)) + 'px'
                ));
            }
        };
    }

    /* ── Line justification ─────────────────────────────────────────────
       Full-justifies every non-centered line (data-justify="1"): condense
       via scaleX if it's too wide; otherwise elongate with the font's own
       kashida OpenType features (caller-supplied — font-specific tags,
       e.g. Digital Khatt vs. Old Madina use different feature names) and
       fill the remainder with word-spacing; a single word with slack left
       gets scaleX instead. Callers may provide several feature candidates so
       each line can choose the closest fitting Arabic alternates, plus caps
       for residual word spacing/stretch. `stretchOnly` opts a source out of
       kashida entirely in favor of a gentle scaleX-only fill (شمرلي's
       whole-word page glyphs can't take kashida/word-spacing at all). */
    function createLineJustifier(config) {
        const {
            containerEls, lineSelector, innerSelector, wordSelector,
            featureSettings = () => '', featureCandidates = null,
            minFeatureScale = 1, maxWordSpacing = Infinity, maxStretch = Infinity,
            stretchOnly = () => false,
        } = config || {};
        const resolveNumber = (value, fallback, lineEl, inner) => {
            const raw = typeof value === 'function' ? value(lineEl, inner) : value;
            const parsed = Number(raw);
            return Number.isFinite(parsed) ? parsed : fallback;
        };
        return function justifyLines() {
            const els = (typeof containerEls === 'function' ? containerEls() : []).filter(Boolean);
            const lines = [];
            els.forEach(el => el.querySelectorAll(lineSelector).forEach(l => lines.push(l)));
            const gentle = stretchOnly();
            const features = gentle ? '' : featureSettings();
            lines.forEach(lineEl => {
                const inner = lineEl.querySelector(innerSelector);
                if (!inner) return;
                inner.style.transform = 'none';
                inner.style.fontFeatureSettings = '';
                inner.style.fontVariationSettings = '';
                inner.style.wordSpacing = '';
                const avail = lineEl.clientWidth;
                if (!avail || lineEl.dataset.justify !== '1') return;
                const natural = inner.scrollWidth;
                if (!natural) return;

                if (natural > avail + 0.5) {                  // too long → condense to fit
                    inner.style.transform = `scaleX(${Math.max(0.5, avail / natural)})`;
                    return;
                }
                if (gentle) {                                  // page glyphs → gentle stretch
                    inner.style.transform = `scaleX(${Math.min(1.5, avail / natural)})`;
                    return;
                }
                let width = natural;
                let chosenFeatures = '';
                const candidateList = gentle ? [] : (
                    typeof featureCandidates === 'function'
                        ? featureCandidates(lineEl, inner)
                        : featureCandidates
                );
                const candidates = Array.isArray(candidateList) && candidateList.length
                    ? candidateList.filter(Boolean)
                    : (features ? [features] : []);
                const featureScaleFloor = Math.max(
                    0.5,
                    Math.min(1, resolveNumber(minFeatureScale, 1, lineEl, inner))
                );
                let bestDistance = Math.abs(avail - natural);
                candidates.forEach(candidate => {
                    inner.style.fontFeatureSettings = candidate;
                    const candidateWidth = inner.scrollWidth;
                    if (!candidateWidth) return;
                    const fitScale = avail / candidateWidth;
                    if (candidateWidth > avail + 0.5 && fitScale < featureScaleFloor) return;
                    const distance = Math.abs(avail - candidateWidth);
                    if (distance < bestDistance) {
                        bestDistance = distance;
                        chosenFeatures = candidate;
                        width = candidateWidth;
                    }
                });
                inner.style.fontFeatureSettings = chosenFeatures;

                // A slightly over-wide alternate is preferable to large word
                // gaps; gently bring it back to the exact line width.
                if (width > avail + 0.5) {
                    inner.style.transform = `scaleX(${avail / width})`;
                    return;
                }
                const gaps = inner.querySelectorAll(wordSelector).length - 1;
                const slack = avail - width;
                if (slack > 0.5 && gaps > 0) {
                    const spacingCap = Math.max(0, resolveNumber(maxWordSpacing, Infinity, lineEl, inner));
                    const spacing = Math.min(slack / gaps, spacingCap);
                    if (spacing > 0) inner.style.wordSpacing = spacing + 'px';

                    // If the spacing cap leaves a little width unfilled, spread
                    // that remainder across the shaped line instead of reopening
                    // conspicuous gaps between words.
                    const spacedWidth = inner.scrollWidth;
                    if (spacedWidth && spacedWidth < avail - 0.5) {
                        const stretchCap = Math.max(1, resolveNumber(maxStretch, Infinity, lineEl, inner));
                        const stretch = Math.min(avail / spacedWidth, stretchCap);
                        if (stretch > 1.0005) inner.style.transform = `scaleX(${stretch})`;
                    }
                } else if (slack > 0.5) {
                    inner.style.transform = `scaleX(${avail / width})`;
                }
            });
        };
    }

    /* ── Running head / page number ──────────────────────────────────── */
    function collectPageSurahs(payload) {
        const seen = new Set();
        const result = [];
        const add = value => {
            const n = Number(value);
            if (!Number.isInteger(n) || n < 1 || n > 114 || seen.has(n)) return;
            seen.add(n);
            result.push(n);
        };
        ((payload && payload.lines) || []).forEach(line => {
            (line.words || []).forEach(word => add(word.surah));
            if (line.line_type === 'surah_name') add(line.surah_number);
        });
        if (!result.length && payload) add(payload.anchor_surah_number);
        return result;
    }

    function clearPageChrome(config) {
        const { juzEl, surahEl, pageNumberEl, juzGlyphClass = '' } = config || {};
        if (juzEl) {
            juzEl.replaceChildren();
            if (juzGlyphClass) juzEl.classList.remove(juzGlyphClass);
            juzEl.removeAttribute('title');
            juzEl.removeAttribute('aria-label');
        }
        if (surahEl) surahEl.replaceChildren();
        if (pageNumberEl) pageNumberEl.textContent = '';
    }

    function renderPageChrome(config) {
        const {
            payload, juzEl, surahEl, pageNumberEl,
            getJuzNumber = page => juzNumber(page.page_number),
            getSurahName = () => '',
            juzGlyphClass = '', surahGlyphClass = '', surahTextClass = '',
        } = config || {};
        clearPageChrome({ juzEl, surahEl, pageNumberEl, juzGlyphClass });
        if (!payload) return;

        collectPageSurahs(payload).forEach(number => {
            if (!surahEl) return;
            const name = String(getSurahName(number) || '').trim();
            const accessibleName = name || toAr(number);
            const glyph = surahHeaderGlyph(number);
            const item = document.createElement('span');
            if (glyph) {
                if (surahGlyphClass) item.className = surahGlyphClass;
                item.textContent = glyph;
                item.setAttribute('aria-label', `سورة ${accessibleName}`);
            } else {
                if (surahTextClass) item.className = surahTextClass;
                item.textContent = `سورة ${accessibleName}`;
            }
            surahEl.appendChild(item);
        });

        const jn = Number(getJuzNumber(payload));
        if (juzEl && Number.isInteger(jn) && jn >= 1 && jn <= 30) {
            const label = `الجزء ${JUZ_NAME[jn - 1]}`;
            const glyph = juzGlyph(jn);
            if (glyph && juzGlyphClass) {
                juzEl.classList.add(juzGlyphClass);
                juzEl.textContent = glyph;
                juzEl.title = label;
                juzEl.setAttribute('aria-label', label);
            } else {
                juzEl.textContent = label;
            }
        }
        if (pageNumberEl && payload.page_number != null) {
            pageNumberEl.textContent = pageNumberLabel(payload.page_number);
        }
    }

    /* ── Empty state ─────────────────────────────────────────────────── */
    function renderEmptyState(container, options) {
        const { icon = 'fa-book-quran', message = '', baseClass, extraClass = '' } = options || {};
        if (!container || !baseClass) return;
        const empty = document.createElement('div');
        empty.className = `${baseClass}${extraClass ? ' ' + extraClass : ''}`;
        const iconEl = document.createElement('i');
        iconEl.className = `fas ${icon}`;
        iconEl.setAttribute('aria-hidden', 'true');
        empty.appendChild(iconEl);
        if (message) {
            const text = document.createElement('span');
            text.textContent = message;
            empty.appendChild(text);
        }
        container.replaceChildren(empty);
    }

    window.AtharPageChrome = Object.freeze({
        toAr,
        pageNumberLabel,
        JUZ_NAME,
        JUZ_START_PAGE,
        juzNumber,
        juzFromAyah,
        juzGlyph,
        surahHeaderGlyph,
        sizePages,
        createFontSizer,
        createLineJustifier,
        collectPageSurahs,
        clearPageChrome,
        renderPageChrome,
        renderEmptyState,
    });
})();
