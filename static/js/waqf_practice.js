/* تدريب الوقف — mark where you stopped, grade against printed mushaf marks
   only (for now). Result shows whether each stop has a mushaf mark and which. */
(function () {
    'use strict';
    const $ = id => document.getElementById(id);
    const toAr = window.AtharMushaf.toArabicDigits;

    const els = {
        surah: $('wp-surah'), from: $('wp-from'), to: $('wp-to'), mushaf: $('wp-mushaf'),
        load: $('wp-load'), hint: $('wp-hint'), intro: $('wp-intro'), pageState: $('wp-page-state'), rangeLabel: $('wp-range-label'),
        rangeTrigger: $('wp-range-trigger'), rangePanel: $('wp-range-panel'),
        mushafTrigger: $('wp-mushaf-trigger'), mushafPanel: $('wp-mushaf-panel'), mushafLabel: $('wp-mushaf-label'),
        passageSec: $('wp-passage-sec'), passage: $('wp-passage'),
        count: $('wp-count'), clear: $('wp-clear'), grade: $('wp-grade'),
        rec: $('wp-rec'), recIcon: $('wp-rec-icon'), recLabel: $('wp-rec-label'), recNote: $('wp-rec-note'),
        follow: $('wp-follow'),
        tajweed: $('wp-tajweed'), tajweedSec: $('wp-tajweed-sec'), tajweedBody: $('wp-tajweed-body'),
        resultSec: $('wp-result-sec'), score: $('wp-score'), scoreNum: $('wp-score-num'),
        scoreTitle: $('wp-score-title'), tGood: $('wp-t-good'), tNote: $('wp-t-note'),
        tErr: $('wp-t-err'), legend: $('wp-legend'), graded: $('wp-graded'), followups: $('wp-followups'),
    };

    // Button state helpers (follow/tajweed are aria-pressed buttons,
    // not checkboxes). Popover behavior comes from the shared أثَر UI layer.
    const isPressed = btn => !!btn && btn.getAttribute('aria-pressed') === 'true';
    const setPressed = (btn, val) => { if (btn) btn.setAttribute('aria-pressed', val ? 'true' : 'false'); };
    const popovers = window.AtharUi.createPopoverGroup();

    const state = { verses: [], stops: new Set() /* "ayah:wpos" */ };
    const catalog = window.AtharMushaf.createVerseCatalog();
    const surahRequests = window.AtharMushaf.createRequestGate();
    const passageRequests = window.AtharMushaf.createRequestGate();
    const gradeRequests = window.AtharMushaf.createRequestGate();
    // Phoneme recite-follow: reference entries {skel,ayah,wpos} + a resync cursor
    // (wi = word we're on, anchor = index into the recited skeleton where it begins).
    const rec = { on: false, ref: [], wi: 0, anchor: 0, cur: null };

    // verdict → display. Order = legend order. Graded vs mushaf marks only.
    const VERDICT = {
        excellent: { cls: 'ex',   name: 'علامة قوية',  tip: 'وقف لازم في المصحف' },
        good:      { cls: 'good', name: 'علامة جائزة', tip: 'قلى / ج / معانقة / رأس آية' },
        ok:        { cls: 'ok',   name: 'الوصل أولى',  tip: 'صلى أو سكتة — الوقف مسموح' },
        unmarked:  { cls: 'un',   name: 'بلا علامة',   tip: 'لا علامة وقف في هذا المصحف' },
        error:     { cls: 'err',  name: 'لا وقف',      tip: 'علامة «لا» — لا يُوقف عليه' },
    };

    const markCaption = stop => {
        if (stop && stop.has_mark && stop.mark) {
            return `علامة المصحف: ${stop.mark}` + (stop.label ? ` — ${stop.label}` : '');
        }
        return stop && stop.label ? stop.label : 'بلا علامة في هذا المصحف';
    };

    function showPageState(kind, message) {
        if (!els.pageState) return;
        els.pageState.hidden = !message;
        if (message) window.AtharUi.renderState(els.pageState, kind, message);
        else els.pageState.replaceChildren();
    }

    /* ── setup ──────────────────────────────────────────────────────── */
    async function init() {
        showPageState('loading', 'جارٍ تهيئة التدريب…');
        els.load.disabled = true;
        let versions;
        try {
            [, versions] = await Promise.all([
                catalog.loadSurahs(),
                window.AtharApi.json('/api/mushaf-versions'),
            ]);
        } catch (error) {
            showPageState('error', 'تعذّر تهيئة بيانات التدريب.');
            return;
        }
        catalog.renderSurahOptions(els.surah);
        const prefer = ['المدينة الجديد', 'المدينة القديم'];
        const ordered = [...prefer.filter(v => versions.includes(v)),
                         ...versions.filter(v => !prefer.includes(v))];
        els.mushaf.innerHTML = ordered.map(v => `<option value="${v}">${v}</option>`).join('');
        if (els.mushafLabel) els.mushafLabel.textContent = els.mushaf.value;
        els.mushaf.addEventListener('change', () => {
            if (els.mushafLabel) els.mushafLabel.textContent = els.mushaf.value;
            if (state.verses.length) loadPassage();
        });
        els.surah.addEventListener('change', onSurah);
        els.from.addEventListener('change', () => { if (+els.to.value < +els.from.value) els.to.value = els.from.value; });
        els.load.addEventListener('click', loadPassage);
        els.clear.addEventListener('click', clearStops);
        els.grade.addEventListener('click', gradeStops);
        if (els.rec) els.rec.addEventListener('click', toggleRecord);
        if (els.follow) els.follow.addEventListener('click', () => {
            setPressed(els.follow, !isPressed(els.follow));
            if (!isPressed(els.follow)) clearReciting();
        });
        if (els.tajweed) els.tajweed.addEventListener('click', () => setPressed(els.tajweed, !isPressed(els.tajweed)));
        popovers.register(els.rangeTrigger, els.rangePanel);
        popovers.register(els.mushafTrigger, els.mushafPanel);
        if (els.rangeTrigger) els.rangeTrigger.addEventListener('click', () => popovers.toggle(els.rangeTrigger, els.rangePanel));
        if (els.mushafTrigger) els.mushafTrigger.addEventListener('click', () => popovers.toggle(els.mushafTrigger, els.mushafPanel));
        document.addEventListener('click', e => { if (!e.target.closest('.wp-pop')) popovers.close(); });
        if (!await onSurah()) return;
        // deep link ?surah=&from=&to=
        const p = new URLSearchParams(location.search);
        const requestedSurah = Number(p.get('surah'));
        const hasRequestedSurah = Number.isInteger(requestedSurah)
            && [...els.surah.options].some(option => Number(option.value) === requestedSurah);
        if (hasRequestedSurah) { els.surah.value = String(requestedSurah); if (!await onSurah()) return; }
        if (p.get('from') && [...els.from.options].some(o => o.value === p.get('from'))) els.from.value = p.get('from');
        if (p.get('to') && [...els.to.options].some(o => o.value === p.get('to'))) els.to.value = p.get('to');
        showPageState('', '');
        els.load.disabled = false;
        if (hasRequestedSurah) loadPassage();
        let resizeId = 0;
        window.addEventListener('resize', () => {
            clearTimeout(resizeId);
            resizeId = setTimeout(() => {
                if (els.passage?.classList.contains('wp-ml-pages')) fitPracticePages();
            }, 120);
        });
    }

    async function onSurah() {
        const request = surahRequests.next();
        passageRequests.cancel();
        gradeRequests.cancel();
        window.AtharUi.setBusy(els.load, false);
        window.AtharUi.setBusy(els.grade, false);
        els.load.disabled = true;
        const s = +els.surah.value || 1;
        try {
            const n = await catalog.getAyahCount(s);
            if (!surahRequests.isCurrent(request)) return false;
            catalog.renderAyahOptions(els.from, n, { selected: 1 });
            catalog.renderAyahOptions(els.to, n, { selected: Math.min(n, 5) });
            showPageState('', '');
            els.load.disabled = false;
            return true;
        } catch (error) {
            if (surahRequests.isCurrent(request)) {
                showPageState('error', 'تعذّر تحميل آيات السورة.');
            }
            return false;
        }
    }

    /* ── load a passage as tappable words ──────────────────────────── */
    async function loadPassage() {
        const s = +els.surah.value, f = +els.from.value;
        let t = +els.to.value;
        const mushaf = els.mushaf.value;
        if (t < f) { t = f; els.to.value = String(f); }
        if (t - f > 20) { showPageState('error', 'المقطع طويل — اختر ٢١ آية أو أقل.'); return; }
        const request = passageRequests.next();
        gradeRequests.cancel();
        window.AtharUi.setBusy(els.grade, false);
        els.load.disabled = true;
        window.AtharUi.setBusy(els.load, true);
        showPageState('loading', 'جارٍ تحميل المقطع…');
        try {
            if (rec.on) stopRecord();
            const j = await window.AtharApi.json(`/api/waqf-practice/passage/${s}/${f}/${t}`);
            if (!passageRequests.isCurrent(request)) return;
            state.verses = j.verses || [];
            state.stops.clear();
            // Always prefer real mushaf page cards (same layout engine as تثبيت).
            let renderedLayout = await renderMushafLayout(s, f, t, mushaf, request);
            if (!passageRequests.isCurrent(request)) return;
            if (!renderedLayout) renderPassage();
            const name = catalog.nameOf(s);
            if (els.rangeLabel) els.rangeLabel.textContent = `${name} · ${toAr(f)}${t > f ? '–' + toAr(t) : ''}`;
            els.hint.hidden = false;
            if (els.intro) els.intro.hidden = true;
            els.passageSec.hidden = false;
            els.resultSec.hidden = true;
            showPageState('', '');
            updateCount();
            els.passageSec.scrollIntoView({ behavior: 'smooth', block: 'start' });
        } catch (e) {
            if (passageRequests.isCurrent(request)) showPageState('error', 'تعذّر تحميل المقطع.');
        } finally {
            if (passageRequests.isCurrent(request)) {
                els.load.disabled = false;
                window.AtharUi.setBusy(els.load, false);
            }
        }
    }

    // Tap a word to toggle a stop — shared by the plain and mushaf-layout views.
    function wirePassageClicks() {
        els.passage.onclick = e => {
            const b = e.target.closest('.wp-word'); if (!b) return;
            const k = b.dataset.key;
            if (state.stops.has(k)) { state.stops.delete(k); b.classList.remove('wp-stopped'); }
            else { state.stops.add(k); b.classList.add('wp-stopped'); }
            updateCount();
        };
    }

    function renderPassage() {
        els.passage.className = 'wp-passage';
        els.passage.innerHTML = '';
        state.verses.forEach(v => {
            const line = document.createElement('div');
            line.className = 'wp-verse';
            const last = v.words.length - 1;
            window.AtharMushaf.renderWordRun(line, v.words, {
                tagName: 'button', separator: ' ',
                classForWord: ({ index }) => 'wp-word' + (index === last ? ' wp-word-end' : ''),
                renderWord: (button, { raw, index }) => {
                    button.type = 'button';
                    button.dataset.key = `${v.ayah}:${index}`;
                    button.dataset.ayah = String(v.ayah);
                    button.dataset.wpos = String(index);
                    button.textContent = raw;
                },
            });
            line.appendChild(document.createTextNode(' '));
            const num = document.createElement('span');
            num.className = 'wp-ayah-num';
            num.textContent = toAr(v.ayah);
            line.appendChild(num);
            els.passage.appendChild(line);
        });
        wirePassageClicks();
    }

    /* ── Printed page cards (same layout engine as تثبيت) ─────────────
       Full mushaf pages with fixed ratio, 15-line geometry, surah/basmala
       glyphs, and justified nowrap lines. In-range words stay tappable;
       out-of-range words are dimmed context. */
    const { getWaqfDisplayData, stripEmbeddedWaqf } = window.AtharMushaf;
    const { surahHeaderGlyph, renderPageChrome } = window.AtharPageChrome;
    const BASMALA_GLYPH = '\u00F3';
    const ARABIC_DIGITS_ONLY = /^[٠-٩]+$/;
    const withAyahOrnament = text => ARABIC_DIGITS_ONLY.test(text) ? '۝' + text : text;
    const integratedWaqfGlyph = entry => {
        const data = getWaqfDisplayData(entry && entry.symbols, entry && entry.version);
        return data ? data.text : '';
    };
    const layoutSourceFor = mushaf => (mushaf === 'المدينة القديم' ? 'qpc_v1' : 'digital_khatt');
    const PAGE_RATIO = 0.66;
    const OLD_MADINA_PAGE_RATIO = 0.72;
    let _layoutSrc = 'digital_khatt';
    let _layoutMushaf = 'المدينة الجديد';
    const _hasArabic = s => /[ء-ي]/.test(s || '');

    function sizePracticePages() {
        const host = els.passage;
        if (!host || !host.classList.contains('wp-ml-pages')) return;
        const appbar = document.querySelector('.athar-bar')?.getBoundingClientRect().height || 50;
        const toolbar = document.getElementById('wp-bar')?.getBoundingClientRect().height || 56;
        const ratio = _layoutSrc === 'qpc_v1' ? OLD_MADINA_PAGE_RATIO : PAGE_RATIO;
        const headFootPad = 64;
        window.AtharPageChrome.sizePages({
            cssVarPrefix: 'wp',
            pages: 1,
            ratio,
            gutter: 0, edgePad: 0, minW: 240, minH: 320,
            getAvailH: () => Math.max(320, Math.min(
                window.innerHeight - appbar - toolbar - 120,
                (host.clientWidth - 8) / ratio + headFootPad + 24
            )) - headFootPad,
            getAvailW: () => Math.max(240, Math.min(host.clientWidth - 28, 560)),
        });
    }

    const applyPracticeFontSize = window.AtharPageChrome.createFontSizer({
        pageEls: () => [...els.passage.querySelectorAll('.wp-ml-page')],
        lineSelector: '.wp-ml-line', innerSelector: '.wp-ml-line-inner',
        cssVarName: '--wp-fs', linesPerPage: 15,
        fitScale: 0.94, minLineScale: 0.88, minFontSize: 12,
        maxPageFitRatio: 1.15,
        cacheKey: () => `${_layoutSrc}|${_layoutMushaf}|${els.passage.querySelectorAll('.wp-ml-page').length}`,
    });

    /* Same Madinah feature ladders as تثبيت — from AtharPageChrome. */
    const {
        digitalKhattFeatureCandidates,
        oldMadinaFeatureCandidates,
    } = window.AtharPageChrome;

    const justifyPracticeLines = window.AtharPageChrome.createLineJustifier({
        containerEls: () => [...els.passage.querySelectorAll('.wp-ml-page')],
        lineSelector: '.wp-ml-line', innerSelector: '.wp-ml-line-inner',
        wordSelector: '.wp-word, .wp-ml-ctx, .wp-ml-num',
        featureCandidates: () => (_layoutSrc === 'qpc_v1'
            ? oldMadinaFeatureCandidates(100)
            : _layoutSrc === 'digital_khatt' ? digitalKhattFeatureCandidates(100) : []),
        minFeatureScale: () => (
            _layoutSrc === 'qpc_v1' || _layoutSrc === 'digital_khatt' ? 0.95 : 1
        ),
        maxWordSpacing: (_lineEl, inner) => {
            if (_layoutSrc !== 'qpc_v1' && _layoutSrc !== 'digital_khatt') return Infinity;
            const fontSize = parseFloat(getComputedStyle(inner).fontSize) || 20;
            return Math.max(1.5, Math.min(4, fontSize * 0.12));
        },
        maxStretch: () => (_layoutSrc === 'digital_khatt' ? 1.15 : _layoutSrc === 'qpc_v1' ? 1.18 : Infinity),
    });

    function fitPracticePages() {
        sizePracticePages();
        applyPracticeFontSize(true);
        requestAnimationFrame(() => {
            justifyPracticeLines();
            // Centered / special lines aren't justified — still clamp if wider than the page.
            els.passage.querySelectorAll('.wp-ml-line[data-justify="0"] .wp-ml-line-inner, .wp-ml-line-basmala, .wp-ml-line-surah').forEach(inner => {
                const line = inner.closest('.wp-ml-line') || inner.parentElement;
                if (!line) return;
                inner.style.transform = 'none';
                const avail = line.clientWidth;
                const natural = inner.scrollWidth;
                if (avail > 0 && natural > avail + 0.5) {
                    inner.style.transform = `scaleX(${Math.max(0.72, avail / natural)})`;
                    inner.style.transformOrigin = 'center center';
                }
            });
        });
    }

    async function renderMushafLayout(s, f, t, mushaf, request) {
        const source = layoutSourceFor(mushaf);
        _layoutSrc = source;
        _layoutMushaf = mushaf;
        const client = window.AtharMushaf.createPageClient({
            getSource: () => source,
            getVersions: () => [mushaf],
        });
        let pages;
        try {
            pages = await window.AtharMushaf.loadPageRange({
                client, surah: s, fromAyah: f, toAyah: t, maxPages: 8,
                isCurrent: () => passageRequests.isCurrent(request),
            });
        } catch (e) {
            return false;
        }
        if (!pages || !pages.length) return false;
        if (window.AtharMushaf.maxAyahOnPage(pages[pages.length - 1], s) < t) return false;
        return renderLayoutPages(pages, s, f, t, mushaf);
    }

    function renderLayoutPages(pages, s, f, t, mushaf) {
        const src = layoutSourceFor(mushaf);
        const oldSelected = mushaf === 'المدينة القديم';
        els.passage.className = 'wp-passage wp-ml wp-ml-pages'
            + (src === 'qpc_v1' ? ' wp-ml-src-qpc-v1' : ' wp-ml-src-digital-khatt');
        els.passage.replaceChildren();
        let rendered = 0;
        pages.forEach(payload => {
            if (!(payload.lines || []).length) return;
            rendered += 1;
            const card = document.createElement('div');
            card.className = 'wp-ml-card athar-page-card';

            const head = document.createElement('div');
            head.className = 'wp-ml-page-header athar-page-head';
            const juzEl = document.createElement('span');
            juzEl.className = 'wp-ml-head-juz athar-page-head-juz';
            const surahEl = document.createElement('span');
            surahEl.className = 'wp-ml-head-surah athar-page-head-surah';
            head.append(juzEl, surahEl);

            const page = document.createElement('div');
            page.className = 'wp-ml-page' + (src === 'qpc_v1' ? ' wp-ml-src-qpc-v1' : ' wp-ml-src-digital-khatt');
            page.dataset.page = String(payload.page_number || '');

            window.AtharMushaf.renderMushafLines(page, payload.lines || [], {
                lineClass: 'wp-ml-line',
                contentClass: 'wp-ml-line-inner',
                surahClass: 'wp-ml-line-surah',
                basmalaClass: 'wp-ml-line-basmala wp-ml-basmala-glyph',
                textForSpecial: ({ line, kind }) => kind === 'surah'
                    ? (surahHeaderGlyph(line.surah_number) || line.display_text || '')
                    : BASMALA_GLYPH,
                decorateSpecial: (element, { line, kind }) => {
                    if (kind === 'surah' && surahHeaderGlyph(line.surah_number)) {
                        element.classList.add('wp-ml-surah-glyph');
                    }
                    element.setAttribute('aria-label', line.display_text || (kind === 'basmala' ? 'بسم الله الرحمن الرحيم' : ''));
                },
                countWord: ({ raw }) => _hasArabic(raw),
                classForWord: ({ counted, word }) => {
                    if (!counted) return 'wp-ml-num';
                    return Number(word.surah) === s && Number(word.ayah) >= f && Number(word.ayah) <= t
                        ? 'wp-word' : 'wp-ml-ctx';
                },
                identityKey: ({ word, position }) => Number(word.surah) === s
                    && Number(word.ayah) >= f && Number(word.ayah) <= t ? `${word.ayah}:${position}` : null,
                textForWord: ({ word, raw }) => {
                    if (oldSelected) {
                        const entries = Array.isArray(word.waqf_symbols) ? word.waqf_symbols : [];
                        const oldMark = entries.find(entry => entry && entry.version === 'المدينة القديم');
                        return withAyahOrnament(stripEmbeddedWaqf(raw) + (oldMark ? integratedWaqfGlyph(oldMark) : ''));
                    }
                    return withAyahOrnament(raw);
                },
                decorateLine: (element, { line }) => {
                    if ((line.words || []).length) element.dataset.justify = line.is_centered ? '0' : '1';
                },
                decorateWord: (element, { counted, word }) => {
                    if (!counted || !element.classList.contains('wp-word')) return;
                    element.dataset.ayah = String(word.ayah);
                },
            });

            const foot = document.createElement('div');
            foot.className = 'wp-ml-page-footer';
            const footPage = document.createElement('span');
            footPage.className = 'wp-ml-foot-page';
            foot.appendChild(footPage);

            renderPageChrome({
                payload, juzEl, surahEl, pageNumberEl: footPage,
                getSurahName: num => catalog.nameOf(num) || '',
                juzGlyphClass: 'athar-page-juz-glyph',
                surahGlyphClass: 'athar-page-surah-glyph',
                surahTextClass: 'athar-page-surah-text',
            });

            card.append(head, page, foot);
            els.passage.appendChild(card);
        });
        if (!rendered) return false;
        wirePassageClicks();
        const runFit = () => requestAnimationFrame(() => requestAnimationFrame(fitPracticePages));
        runFit();
        if (document.fonts && document.fonts.ready) {
            document.fonts.ready.then(() => {
                if (els.passage.classList.contains('wp-ml-pages')) runFit();
            }).catch(() => {});
        }
        return true;
    }

    function clearStops() {
        state.stops.clear();
        els.passage.querySelectorAll('.wp-stopped').forEach(b => b.classList.remove('wp-stopped'));
        updateCount();
    }

    function updateCount() {
        const n = state.stops.size;
        els.count.textContent = n ? `علّمتَ ${toAr(n)} موضع وقف` : 'لم تُعلّم أي وقف بعد';
        els.grade.disabled = n === 0;
    }

    /* ── grade ─────────────────────────────────────────────────────── */
    async function gradeStops() {
        const request = gradeRequests.next();
        const stops = [...state.stops].map(k => {
            const [ayah, wpos] = k.split(':').map(Number);
            return { ayah, wpos };
        });
        els.grade.disabled = true;
        window.AtharUi.setBusy(els.grade, true);
        showPageState('loading', 'جارٍ تقييم مواضع الوقف…');
        try {
            const j = await window.AtharApi.json('/api/waqf-practice/grade', {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    surah: +els.surah.value, from_ayah: +els.from.value,
                    to_ayah: +els.to.value, mushaf: els.mushaf.value, stops,
                }),
            });
            if (!gradeRequests.isCurrent(request)) return;
            renderResult(j);
            showPageState('', '');
        } catch (e) {
            if (gradeRequests.isCurrent(request)) showPageState('error', 'تعذّر التقييم.');
        } finally {
            if (gradeRequests.isCurrent(request)) {
                els.grade.disabled = false;
                window.AtharUi.setBusy(els.grade, false);
            }
        }
    }

    /* ── recite & auto-mark stops — zipformer PHONEME ASR ──────────────
       The model emits phonemes; we DP-align the recited phoneme stream to the
       passage's reference phonemes (fetched per-word from the backend) to follow
       position, and the model's silence token gives وقف stops. */
    const setRecNote = m => { if (els.recNote) els.recNote.textContent = m || ''; };
    const _PH_KEEP = 'ءابتثجحخدذرزسشصضطظعغفقكلمنهوي';
    function _phSkel(s) {           // consonant skeleton (matches the backend aligner)
        s = (s || '').replace(/[ٱأإآ]/g, 'ا').replace(/ة/g, 'ه').replace(/ى/g, 'ي');
        let out = '';
        for (const c of s) if (_PH_KEEP.indexOf(c) >= 0 && out[out.length - 1] !== c) out += c;
        return out;
    }
    // Phonetically-similar consonants the acoustic model confuses (nasals, sibilants,
    // emphatics, throat letters, glides). A substitution WITHIN a group is cheap so a
    // single model slip doesn't break the alignment.
    const _SIM = {};
    for (const g of ['من', 'سصز', 'تطدض', 'ذظث', 'هحخ', 'عغءه', 'قك', 'ويا', 'رل'])
        for (const c of g) _SIM[c] = (_SIM[c] || '') + g;
    const _subCost = (a, b) => a === b ? 0 : (_SIM[a] && _SIM[a].indexOf(b) >= 0 ? 0.4 : 1);
    function _wed(a, b) {           // weighted edit distance (similar subs discounted)
        const m = a.length, n = b.length;
        if (!m) return n; if (!n) return m;
        let prev = Array.from({ length: n + 1 }, (_, j) => j);
        for (let i = 1; i <= m; i++) {
            const cur = [i];
            for (let j = 1; j <= n; j++)
                cur[j] = Math.min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + _subCost(a[i - 1], b[j - 1]));
            prev = cur;
        }
        return prev[n];
    }
    // Best local match of reference skeleton `es` inside `rs` near index `from` (the
    // start may slip ±2 to absorb an extra/dropped char, length varies around |es|).
    function _bestMatch(rs, from, es) {
        let best = { sim: -1, start: from, len: es.length };
        const s0 = Math.max(0, from - 2), s1 = Math.min(rs.length, from + 2);
        for (let start = s0; start <= s1; start++) {
            const loK = Math.max(1, es.length - 2), hiK = Math.min(rs.length - start, es.length + 3);
            for (let k = loK; k <= hiK; k++) {
                const sim = 1 - _wed(rs.substr(start, k), es) / es.length;
                if (sim > best.sim) best = { sim, start, len: k };
            }
        }
        return best;
    }

    // Fetch the passage's reference phoneme entries {ph, ayah, wpos}.
    async function buildPhonemeRef() {
        rec.ref = []; rec.wi = 0; rec.anchor = 0; rec.cur = null; rec.lastPhonemes = '';
        const s = +els.surah.value, f = +els.from.value, t = +els.to.value;
        try {
            const j = await window.AtharApi.json(`/api/waqf-practice/phonemes/${s}/${f}/${t}`);
            rec.ref = (j.entries || []).map(e => ({ ph: e.ph, skel: _phSkel(e.ph), ayah: e.ayah, wpos: e.wpos }));
        } catch (e) { rec.ref = []; }
    }

    async function toggleRecord() {
        if (rec.on) { stopRecord(); return; }
        if (!window.MushafZipformer) { setRecNote('وحدة التعرّف غير متوفرة'); return; }
        if (!state.verses.length) { setRecNote('حمّل مقطعًا أولًا'); return; }
        await buildPhonemeRef();
        if (!rec.ref.length) { setRecNote('تعذّر تجهيز مرجع التلاوة'); return; }
        try {
            await window.MushafZipformer.start({
                onStatus: setRecNote,
                onActive: on => {
                    rec.on = on;
                    els.rec.classList.toggle('is-listening', on);
                    if (els.recIcon) els.recIcon.className = on ? 'fas fa-stop' : 'fas fa-microphone';
                    if (els.recLabel) els.recLabel.textContent = on ? 'إيقاف التسجيل' : 'سجّل وقوفي';
                    if (!on) { clearReciting(); if (els.tajweed && isPressed(els.tajweed)) requestTajweed(); }
                },
                onPhonemes: alignPhonemes,
                onSilence: markAutoStop,
            });
        } catch (e) {
            setRecNote('تعذّر التشغيل: ' + ((e && (e.message || e.name)) || e));
        }
    }
    function stopRecord() { try { window.MushafZipformer && window.MushafZipformer.stop(); } catch (e) {} }

    function highlightWord(ayah, wpos) {
        if (!els.follow || !isPressed(els.follow)) return;
        els.passage.querySelectorAll('.wp-reciting').forEach(b => b.classList.remove('wp-reciting'));
        const b = els.passage.querySelector(`.wp-word[data-key="${ayah}:${wpos}"]`);
        if (b) { b.classList.add('wp-reciting'); b.scrollIntoView({ block: 'nearest', behavior: 'smooth' }); }
    }
    function clearReciting() { els.passage.querySelectorAll('.wp-reciting').forEach(b => b.classList.remove('wp-reciting')); }

    // Sliding-window resync alignment of the recited phoneme skeleton to the reference
    // word entries. Unlike a committed cursor, it RE-ANCHORS on every advance and can
    // look ahead to skip a garbled word and resync — so a single bad match never wedges
    // the follow. (The old greedy cursor advanced its word pointer on a skip WITHOUT
    // moving the recited cursor, cascading into a permanent stall — verified it froze
    // the highlight for the rest of the passage after ~6 words even on clean input.)
    // Mirrors the reference project (Iam-Muslim/ReciteQuran) phonetic matcher.
    const _WP_ACCEPT = 0.5;        // confirm the current word at/above this similarity
    const _WP_JUMP = 0.6;          // resync forward only on a clearly-strong lookahead
    const _WP_LOOK = 5;            // upcoming words scanned when resyncing
    const _WP_PRIOR = 0.06;        // per-word penalty for jumping ahead (favour chronological)
    function alignPhonemes(recited) {
        rec.lastPhonemes = recited || '';
        const rs = _phSkel(recited);
        let advanced = false, guard = 0;
        while (rec.wi < rec.ref.length && guard++ < rec.ref.length + _WP_LOOK) {
            const es = rec.ref[rec.wi].skel;
            if (!es) { rec.wi++; continue; }
            const tail = rs.length - rec.anchor;
            if (tail < es.length - 1) break;                   // wait for more recited input

            const m = _bestMatch(rs, rec.anchor, es);
            if (m.sim >= _WP_ACCEPT) {                          // current word matched here
                rec.anchor = m.start + m.len;
                rec.cur = rec.ref[rec.wi]; highlightWord(rec.cur.ayah, rec.cur.wpos); rec.wi++; advanced = true; continue;
            }
            // current word didn't match — has the reciter already moved ahead of it?
            let jump = null, expStart = rec.anchor;
            for (let i = rec.wi + 1; i <= Math.min(rec.wi + _WP_LOOK, rec.ref.length - 1); i++) {
                expStart += rec.ref[i - 1].skel.length;
                if (rs.length - expStart < rec.ref[i].skel.length - 1) break;   // not recited yet
                const mi = _bestMatch(rs, expStart, rec.ref[i].skel);
                const score = mi.sim - (i - rec.wi) * _WP_PRIOR;
                if (score >= _WP_JUMP && (!jump || score > jump.score)) jump = { score, i, end: mi.start + mi.len };
            }
            if (jump) {                                         // resync forward to where the reciter is
                rec.anchor = jump.end; rec.wi = jump.i + 1;
                rec.cur = rec.ref[jump.i]; highlightWord(rec.cur.ayah, rec.cur.wpos); advanced = true; continue;
            }
            if (tail > es.length + 6) {                         // waited too long: step past, keep pace
                rec.anchor = Math.min(rs.length, rec.anchor + es.length);
                rec.cur = rec.ref[rec.wi]; highlightWord(rec.cur.ayah, rec.cur.wpos); rec.wi++; advanced = true; continue;
            }
            break;
        }
        if (advanced) setRecNote(`تابعتُ ${toAr(rec.wi)} / ${toAr(rec.ref.length)}`);
    }
    // A detected pause (model silence) seals the current word as a stop.
    function markAutoStop() {
        if (!rec.cur) return;
        const key = rec.cur.ayah + ':' + rec.cur.wpos;
        if (state.stops.has(key)) return;
        state.stops.add(key);
        const b = els.passage.querySelector(`.wp-word[data-key="${key}"]`);
        if (b) b.classList.add('wp-stopped');
        updateCount();
    }

    /* ── tajweed error detection (quran-transcript, server-side) ───────
       POST the full recited phoneme stream; the backend splits it per verse
       (char-level alignment to the reference) and diffs each against the
       rule-correct phonetization → rule-named errors mapped to words. */
    async function requestTajweed() {
        const ph = (rec.lastPhonemes || '').trim();
        if (!ph) { renderTajweed(null); return; }
        setRecNote('تحليل التجويد…');
        try {
            const j = await window.AtharApi.json('/api/waqf-practice/tajweed', {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    surah: +els.surah.value, from_ayah: +els.from.value,
                    to_ayah: +els.to.value, phonemes: ph,
                }),
            });
            renderTajweed(j);
        } catch (e) { renderTajweed(null); }
    }
    function _tjMessage(e) {
        const rule = (e.rules && e.rules[0]) || '';
        if (e.type === 'tajweed' && e.exp_len != null && e.got_len != null) {
            const kind = e.got_len < e.exp_len ? 'قصّرتَ' : 'أطلتَ';
            return `${rule ? rule + ' — ' : 'مدّ — '}${kind} (الصواب ${toAr(e.exp_len)} حركات، قرأتَ ${toAr(e.got_len)})`;
        }
        if (e.op === 'delete') return `أسقطتَ «${e.expected}»${rule ? ' — ' + rule : ''}`;
        if (e.op === 'insert') return `زدتَ «${e.got}»${rule ? ' — ' + rule : ''}`;
        if (e.type === 'tashkeel') return `ضبط: «${e.expected}» ← قرأتَ «${e.got}»`;
        return `نطق: الصواب «${e.expected}»، قرأتَ «${e.got}»`;  // normal replace = letter/مخرج
    }
    function renderTajweed(j) {
        if (!els.tajweedSec) return;
        setRecNote('');
        els.passage.querySelectorAll('.wp-tj-err').forEach(b => b.classList.remove('wp-tj-err'));
        if (!j || j.available === false) { els.tajweedSec.hidden = true; return; }
        const errs = (j.errors || []).filter(e => e.type !== 'tashkeel');   // hide bare harakat noise
        els.tajweedSec.hidden = false;
        if (!errs.length) {
            els.tajweedBody.innerHTML = '<div class="wp-tj-ok"><i class="fas fa-circle-check"></i> لم تُرصد أخطاء تجويد ظاهرة — أحسنت 🌿</div>';
            return;
        }
        // group by word
        const byWord = new Map();
        errs.forEach(e => { const k = e.ayah + ':' + e.wpos; (byWord.get(k) || byWord.set(k, []).get(k)).push(e); });
        let html = '';
        byWord.forEach((list, key) => {
            const b = els.passage.querySelector(`.wp-word[data-key="${key}"]`);
            if (b) b.classList.add('wp-tj-err');
            const word = b ? b.textContent : '';
            const [ay] = key.split(':');
            html += `<div class="wp-tj-row"><span class="wp-tj-w">${word}</span>`
                + `<span class="wp-tj-a">${toAr(ay)}</span><ul class="wp-tj-list">`
                + list.map(e => `<li class="wp-tj-${e.type}">${_tjMessage(e)}</li>`).join('') + '</ul></div>';
        });
        els.tajweedBody.innerHTML = html;
        els.tajweedSec.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }

    function scoreTitle(score, errors) {
        if (errors === 0 && score >= 95) return 'ممتاز — وقوفك يوافق علامات المصحف';
        if (score >= 85) return 'أحسنت — راجع المواضع بلا علامة';
        if (score >= 65) return 'جيّد — قارن وقوفك بعلامات المصحف';
        return 'يحتاج مراجعة — توقّف عند «لا» أو فاتك لازم';
    }

    function renderResult(j) {
        const errors = j.summary.errors;
        els.scoreNum.textContent = toAr(j.score);
        els.score.className = 'wp-score ' + (j.score >= 85 ? 'wp-score-hi' : j.score >= 65 ? 'wp-score-mid' : 'wp-score-lo');
        els.score.setAttribute('aria-label', `نتيجة التقييم ${toAr(j.score)} بالمئة`);
        els.scoreTitle.textContent = scoreTitle(j.score, errors);
        els.tGood.textContent = toAr(j.summary.good);
        els.tNote.textContent = toAr(j.summary.notes);
        els.tErr.textContent = toAr(errors);

        // legend of the verdicts that actually appeared
        const seen = new Set(j.stops.map(s => s.verdict));
        if (j.broken_lazim.length) seen.add('error');
        els.legend.innerHTML = Object.keys(VERDICT).filter(v => seen.has(v)).map(v => {
            const d = VERDICT[v];
            return `<span class="wp-leg athar-chip"><span class="wp-dot wp-w-${d.cls}"></span>${d.name}</span>`;
        }).join('');

        const verdictAt = new Map(j.stops.map(s => [s.ayah + ':' + s.wpos, s]));
        const brokenAt = new Map(j.broken_lazim.map(b => [b.ayah + ':' + b.wpos, b]));
        const idealAt = new Map(j.ideal.map(b => [b.ayah + ':' + b.wpos, b]));

        els.graded.innerHTML = '';
        state.verses.forEach(v => {
            const line = document.createElement('div');
            line.className = 'wp-verse';
            window.AtharMushaf.renderWordRun(line, v.words, {
                wordClass: 'wp-gword', separator: ' ',
                decorateWord: (span, { index }) => {
                    const key = v.ayah + ':' + index;
                    const s = verdictAt.get(key);
                    if (s) {
                        const d = VERDICT[s.verdict] || VERDICT.unmarked;
                        span.classList.add('wp-stop', 'wp-w-' + d.cls);
                        span.title = markCaption(s);
                        const badge = document.createElement('sup');
                        badge.className = 'wp-mark-badge' + (s.has_mark ? '' : ' is-empty');
                        badge.textContent = s.has_mark && s.mark ? s.mark : '—';
                        badge.setAttribute('aria-label', markCaption(s));
                        span.appendChild(badge);
                    } else if (brokenAt.has(key)) {
                        const b = brokenAt.get(key);
                        span.classList.add('wp-missed-lazim');
                        span.title = `وقف لازم فاتك — علامة المصحف: ${b.mark || 'م'}`;
                        const badge = document.createElement('sup');
                        badge.className = 'wp-mark-badge';
                        badge.textContent = b.mark || 'م';
                        span.appendChild(badge);
                    } else if (idealAt.has(key)) {
                        const b = idealAt.get(key);
                        span.classList.add('wp-ideal');
                        span.title = `موضع بعلامة ${b.mark || ''} (لم تقف عنده)`;
                        const badge = document.createElement('sup');
                        badge.className = 'wp-mark-badge is-ideal';
                        badge.textContent = b.mark || '';
                        span.appendChild(badge);
                    }
                },
            });
            line.appendChild(document.createTextNode(' '));
            const num = document.createElement('span');
            num.className = 'wp-ayah-num';
            num.textContent = toAr(v.ayah);
            line.appendChild(num);
            els.graded.appendChild(line);
        });

        // follow-ups: broken لازم + missed ideal mushaf marks
        let fu = '';
        if (j.broken_lazim.length) {
            fu += `<div class="wp-fu wp-fu-err"><i class="fas fa-triangle-exclamation"></i> `
                + `<b>وقفٌ لازم فاتك</b> (علامة م): `
                + j.broken_lazim.map(b => `<span class="wp-fu-w">${b.word}</span> <small>${toAr(b.ayah)}</small>`).join('، ') + '</div>';
        }
        if (j.ideal.length) {
            fu += `<div class="wp-fu wp-fu-tip"><i class="fas fa-star"></i> `
                + `<b>علامات مصحف</b> كان يمكنك الوقف عندها: `
                + j.ideal.map(b => `<span class="wp-fu-w">${b.word}<sup class="wp-mark-badge is-ideal">${b.mark || ''}</sup></span> <small>${toAr(b.ayah)}</small>`).join('، ') + '</div>';
        }
        els.followups.innerHTML = fu;
        els.resultSec.hidden = false;
        els.resultSec.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }

    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
    else init();
})();
