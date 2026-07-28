/* ═══════════════════════════════════════════════════════════════════
   Waqf Guide — compare how the installed reciters stop in a chosen verse.

   Pick / search a verse → see (A) the verse with every attested stop point,
   (B) a matrix comparing where each reciter stops (align vs انفرد), and
   (C) per-reciter how each one recited it, with their repeats.

   Endpoints:
     GET /api/surahs
     GET /api/surahs/<s>/ayahs
     GET /api/waqf/<s>/<a>   → per-reciter stops + repeats + union
   ═══════════════════════════════════════════════════════════════════ */
(function () {
    'use strict';
    const $ = id => document.getElementById(id);
    const IS_LAB = document.body.classList.contains('athar-waqf-lab')
        || document.body.dataset.wqPage === 'lab';
    const EDITOR_ENABLED = document.body.dataset.editorEnabled === '1';
    const EDITOR_EDITIONS = new Set(['قطر', 'الكويت', 'البحرين']);
    function editorHref(edition, surah, ayah) {
        const url = new URL('/mushaf-editor', location.origin);
        url.searchParams.set('edition', edition);
        url.searchParams.set('surah', String(surah));
        url.searchParams.set('ayah', String(ayah));
        return url.pathname + url.search;
    }
    function editorJumpHtml(editions, surah, ayah) {
        if (!EDITOR_ENABLED || !surah || !ayah) return '';
        const links = [...new Set(editions || [])]
            .filter(e => EDITOR_EDITIONS.has(e))
            .map(e => `<a class="wq-editor-jump" href="${editorHref(e, surah, ayah)}" title="افتح في محرّر الوقف — ${e}">محرّر · ${e}</a>`);
        if (!links.length) return '';
        return `<span class="wq-editor-jumps">${links.join('')}</span>`;
    }

    const HIT_PAGE = 40;
    const labListState = {}; // key → shown count

    function marksHtml(marksObj) {
        const ent = Object.entries(marksObj || {});
        if (!ent.length) return '<span class="wq-hit-empty">بلا علامة مطبوعة</span>';
        return ent.map(([k, v]) =>
            `<span class="wq-hit-mark" title="${k}"><span class="wq-rmark ${waqfFontCls(k)}" data-m="${k}">${mushafGlyph(v, k)}</span><span>${k}</span></span>`
        ).join('');
    }

    function agreePill(agreement) {
        if (agreement === 'full') return '<span class="wq-agree-pill wq-agree-pill-full">تام</span>';
        if (agreement === 'partial') return '<span class="wq-agree-pill wq-agree-pill-partial">جزئي</span>';
        return '';
    }

    function hitRowFromOcc(o, opts = {}) {
        const marksObj = o.marks || {};
        const editorEditions = opts.editorEditions || (opts.withEditor ? Object.keys(marksObj) : null);
        const ed = editorEditions ? editorJumpHtml(editorEditions, o.surah, o.ayah) : '';
        const sname = surahName(o.surah);
        const ref = `${toAr(o.surah)}:${toAr(o.ayah)}`;
        const tip = opts.title || `افتح ${sname} ${ref}`;
        const marksBlock = opts.hideMarks ? '' : `<div class="wq-hit-marks">${opts.marksHtml != null ? opts.marksHtml : marksHtml(marksObj)}</div>`;
        const wposAttr = (o.wpos != null && o.wpos !== '') ? ` data-wpos="${o.wpos}"` : '';
        const wordAttr = o.word ? ` data-word="${String(o.word).replace(/"/g, '&quot;')}"` : '';
        return `<div class="wq-research-row">
            <button class="wq-hit${opts.extraClass ? ' ' + opts.extraClass : ''}" type="button" data-s="${o.surah}" data-a="${o.ayah}"${wposAttr}${wordAttr} title="${tip}">
                <div class="wq-hit-top">
                    <span class="wq-hit-ref">${sname} <b>${ref}</b></span>
                    <span class="wq-hit-meta">${opts.meta || ''}</span>
                </div>
                ${opts.flow ? `<div class="wq-hit-flow">${opts.flow}</div>` : ''}
                ${o.context ? `<div class="wq-hit-ctx" dir="rtl">${o.context}</div>` : ''}
                ${marksBlock}
            </button>${ed}
        </div>`;
    }

    function paginateList(key, items, renderItem) {
        if (!items.length) return '<div class="wq-research-empty">لا نتائج</div>';
        const shown = Math.min(labListState[key] || HIT_PAGE, items.length);
        labListState[key] = shown;
        const body = items.slice(0, shown).map(renderItem).join('');
        const more = shown < items.length
            ? `<button class="wq-hit-more" type="button" data-page-key="${key}" data-total="${items.length}">عرض المزيد (${toAr(items.length - shown)})</button>`
            : '';
        return `<div class="wq-hit-list" data-list-key="${key}">${body}${more}</div>`;
    }

    function toolBlurb(shortText, longText) {
        if (!longText) return `<div class="wq-tool-head"><p class="wq-tool-blurb">${shortText}</p></div>`;
        return `<details class="wq-tool-blurb-disclosure"><summary>${shortText}</summary><p class="wq-tool-blurb">${longText}</p></details>`;
    }

    function wireHitMore(root, key, items, renderItem) {
        if (!root) return;
        root.querySelectorAll('.wq-hit-more[data-page-key="' + key + '"]').forEach(btn => {
            btn.addEventListener('click', () => {
                labListState[key] = (labListState[key] || HIT_PAGE) + HIT_PAGE;
                const list = btn.closest('.wq-hit-list');
                if (!list) return;
                const wrap = document.createElement('div');
                wrap.innerHTML = paginateList(key, items, renderItem);
                list.replaceWith(wrap.firstElementChild);
                wireHitMore(root, key, items, renderItem);
            });
        });
    }
    const toAr = window.AtharMushaf.toArabicDigits;
    const fromAr = s => String(s).replace(/[٠-٩]/g, d => '٠١٢٣٤٥٦٧٨٩'.indexOf(d));
    const {
        displaySymbols, getWaqfDisplayData, isHindiVersion, isWarshVersion,
        normalizeNonWarshWaqfText,
    } = window.AtharMushaf;

    // Printed-mushaf waqf symbols → meaning + style class.
    const WAQF_SYM = {
        'م':  { name: 'لازم',       cls: 'must',  desc: 'وقف لازم — يجب الوقف' },
        'لا': { name: 'لا وقف',     cls: 'no',    desc: 'لا يوقف عليه' },
        'ق':  { name: 'الوقف أولى', cls: 'pstop', desc: 'الوقف أولى (قلى)' },
        'ص':  { name: 'الوصل أولى', cls: 'pcont', desc: 'الوصل أولى (صلى)' },
        'ج':  { name: 'جائز',       cls: 'ok',    desc: 'وقف جائز' },
        'س':  { name: 'سكتة',       cls: 'sakt',  desc: 'سكتة لطيفة بلا تنفّس' },
        'ع':  { name: 'معانقة',     cls: 'muan',  desc: 'وقف المعانقة — يُوقف على أحد الموضعين فقط' },
    };
    const symMeta = s => WAQF_SYM[s] || { name: s, cls: 'ok', desc: s };

    const waqfGlyph = s => normalizeNonWarshWaqfText(s);
    const isWarshId = isWarshVersion;
    const isHindiId = isHindiVersion;
    const waqfFontCls = mushafId => isWarshId(mushafId) ? 'waqf-warsh'
        : isHindiId(mushafId) ? 'waqf-hindi' : 'waqf-uthmanic';
    // Printed-mushaf glyph for a (possibly comma-joined) DB symbol. ورش is special:
    // ص → صه (ۖ) and ر → رأس آية (the ۝ rosette, U+06DD); a word can carry both
    // (e.g. ٱلۡقَيُّومُ 2:255 = "ر,ص") so emit صه then ۝.
    function mushafGlyph(sym, mushafId) {
        const data = getWaqfDisplayData(sym, mushafId);
        return data ? displaySymbols(data.text, mushafId).join('') : '';
    }
    // One mark rendered as its printed glyph in the right font; '∅'/empty → dash.
    function markGlyph(sym, mushafId, cls) {
        if (sym == null || sym === '' || sym === '∅') return '<span class="wq-cmp-none">بلا</span>';
        const g = mushafGlyph(sym, mushafId);
        if (!g) return '<span class="wq-cmp-none">بلا</span>';
        return `<span class="wq-mk-glyph ${waqfFontCls(mushafId)}${cls ? ' ' + cls : ''}">${g}</span>`;
    }

    // Breath presets (max comfortable seconds per breath).
    const BREATH = { short: 7, medium: 13, long: 20 };

    const els = {
        surah: $('wq-surah'), ayah: $('wq-ayah'), search: $('wq-search'),
        searchClear: $('wq-search-clear'), searchResults: $('wq-search-results'),
        prev: $('wq-prev'), next: $('wq-next'), status: $('wq-status'),
        main: $('wq-main') || $('wq-lab-main'),
        barVerse: $('wq-bar-verse'),
        verseCard: $('wq-verse-card'), verseTitle: $('wq-verse-title'), verseMeta: $('wq-verse-meta'),
        bestStops: $('wq-best-stops'), verseFlow: $('wq-verse-flow'),
        recCard: $('wq-rec-card'), breathPicker: $('wq-breath-picker'),
        recSummary: $('wq-rec-summary'), recPlan: $('wq-rec-plan'),
        matrixCard: $('wq-matrix-card'), matrix: $('wq-matrix'), matrixMobile: $('wq-matrix-mobile'), matrixLegend: $('wq-matrix-legend'),
        recitersCard: $('wq-reciters-card'), reciters: $('wq-reciters'),
        muktafaCard: $('wq-muktafa-card'), muktafa: $('wq-muktafa'), muktafaSrc: $('wq-muktafa-src'),
        researchCard: $('wq-research-card'), researchToggle: $('wq-research-toggle'), researchBody: $('wq-research-body'),
        labPicker: $('wq-lab-picker'), labPickerLabel: $('wq-lab-picker-label'),
        labSheetRoot: $('wq-lab-sheet-root'), labSheetBackdrop: $('wq-lab-sheet-backdrop'),
        labSheetClose: $('wq-lab-sheet-close'), labSheetList: $('wq-lab-sheet-list'),
        researchInput: $('wq-research-input'), researchForms: $('wq-research-forms'),
        researchResults: $('wq-research-results'),
        panelWord: $('wq-panel-word'), panelSolos: $('wq-panel-solos'),
        panelStats: $('wq-panel-stats'), panelMandatory: $('wq-panel-mandatory'),
        panelPatterns: $('wq-panel-patterns'), panelCluster: $('wq-panel-cluster'),
        panelIbtidaa: $('wq-panel-ibtidaa'), panelSaktat: $('wq-panel-saktat'),
        panelAgreement: $('wq-panel-agreement'), panelMushafSim: $('wq-panel-mushafsim'),
        mushafSimContent: $('wq-mushafsim-content'),
        solosContent: $('wq-solos-content'),
        statsContent: $('wq-stats-content'), mandatoryContent: $('wq-mandatory-content'),
        patternsContent: $('wq-patterns-content'), clusterContent: $('wq-cluster-content'),
        ibtidaaContent: $('wq-ibtidaa-content'), saktatContent: $('wq-saktat-content'),
        agreementContent: $('wq-agreement-content'),
        practiceCta: $('wq-practice-cta'),
        labFamilies: document.querySelectorAll('.wq-lab-family'),
    };

    const state = { surah: 2, ayah: 255, data: null, breathL: BREATH.medium };
    const catalog = window.AtharMushaf.createVerseCatalog();
    const navigationRequests = window.AtharMushaf.createRequestGate();

    /* ── status toast ─────────────────────────────────────────── */
    const status = window.AtharUi.createStatus(els.status, {
        visibleClass: 'wq-show', errorClass: 'wq-err', defaultDuration: 1600,
    });
    function setStatus(msg, isErr) {
        if (!msg) { status.clear(); return; }
        status.show(msg, { error: !!isErr, duration: isErr ? 0 : 1600 });
    }
    const showState = (container, kind, message) => window.AtharUi.renderState(container, kind, message);

    /* ── data loading ─────────────────────────────────────────── */
    async function loadSurahs() {
        await catalog.loadSurahs();
        if (els.surah) catalog.renderSurahOptions(els.surah);
    }
    const surahName = num => catalog.nameOf(num);
    const getAyahCount = surah => catalog.getAyahCount(surah);
    function renderAyahOptions(surah) {
        if (!els.ayah) return;
        catalog.renderAyahOptions(els.ayah, catalog.getCachedAyahCount(surah));
    }

    function syncCrossLinks(surah, ayah) {
        const s = Number(surah) || state.surah;
        const a = Number(ayah) || state.ayah;
        if (els.practiceCta) {
            els.practiceCta.href = `/waqf-practice?surah=${s}&from=${a}&to=${a}`;
        }
        const ed = document.getElementById('wq-editor-cta');
        if (ed && EDITOR_ENABLED) {
            ed.href = editorHref('قطر', s, a);
        }
    }

    function openVerseInGuide(surah, ayah, opts = {}) {
        const url = new URL('/waqf', location.origin);
        url.searchParams.set('surah', String(surah));
        url.searchParams.set('ayah', String(ayah));
        if (opts.wpos != null && opts.wpos !== '' && Number.isFinite(+opts.wpos)) {
            url.searchParams.set('wpos', String(+opts.wpos));
        }
        if (opts.word) url.searchParams.set('hl', String(opts.word));
        location.assign(url.pathname + url.search);
    }

    function readHighlightFromUrl() {
        try {
            const q = new URLSearchParams(location.search);
            const wpos = parseInt(q.get('wpos') || '', 10);
            const word = (q.get('hl') || '').trim();
            return {
                wpos: Number.isFinite(wpos) && wpos >= 0 ? wpos : null,
                word: word || null,
            };
        } catch (_e) {
            return { wpos: null, word: null };
        }
    }

    function applyVerseHighlight(d) {
        if (!els.verseFlow || !d || !d.words) return;
        const pending = state.pendingHighlight || readHighlightFromUrl();
        state.pendingHighlight = null;
        if (!pending || (pending.wpos == null && !pending.word)) return;
        let idx = pending.wpos;
        if (idx == null || idx < 0 || idx >= d.words.length) {
            const needle = (pending.word || '').replace(/\s+/g, '');
            idx = d.words.findIndex(w => String(w).replace(/\s+/g, '') === needle
                || String(w).includes(pending.word));
        }
        if (idx < 0 || idx >= d.words.length) return;
        const spans = els.verseFlow.querySelectorAll('.wq-word');
        const el = spans[idx];
        if (!el) return;
        el.classList.add('wq-word-hl');
        el.setAttribute('data-hl', '1');
        try { el.scrollIntoView({ behavior: 'smooth', block: 'nearest', inline: 'nearest' }); } catch (_e) {}
        window.setTimeout(() => el.classList.remove('wq-word-hl'), 3200);
        // Drop one-shot params so refresh doesn't keep flashing.
        try {
            const url = new URL(location.href);
            if (url.searchParams.has('wpos') || url.searchParams.has('hl')) {
                url.searchParams.delete('wpos');
                url.searchParams.delete('hl');
                history.replaceState(null, '', url);
            }
        } catch (_e) {}
    }


    function optsFromHitEl(el) {
        if (!el) return {};
        const wpos = el.dataset.wpos != null && el.dataset.wpos !== '' ? +el.dataset.wpos : null;
        return {
            wpos: Number.isFinite(wpos) ? wpos : null,
            word: el.dataset.word || null,
        };
    }

    async function navigateTo(surah, ayah, opts = {}) {
        if (IS_LAB) {
            openVerseInGuide(surah, ayah, opts);
            return;
        }
        state.pendingHighlight = {
            wpos: opts.wpos != null && Number.isFinite(+opts.wpos) ? +opts.wpos : null,
            word: opts.word || null,
        };
        const request = navigationRequests.next();
        window.AtharUi.setBusy(els.main, true);
        setStatus('جارٍ التحميل…');
        try {
            const count = await getAyahCount(surah);
            if (!navigationRequests.isCurrent(request)) return;
            renderAyahOptions(surah);
            ayah = Math.min(Math.max(1, Number(ayah) || 1), count || 1);
            els.surah.value = String(surah);
            els.ayah.value = String(ayah);
            const data = await window.AtharApi.json(`/api/waqf/${surah}/${ayah}`);
            if (!navigationRequests.isCurrent(request)) return;
            state.data = data;
            state.surah = surah;
            state.ayah = ayah;
            els.surah.value = String(surah);
            els.ayah.value = String(ayah);
            render(data);
            loadMuktafa(surah, ayah);
            syncCrossLinks(surah, ayah);
            setStatus('');
            const url = new URL(location.href);
            url.searchParams.set('surah', surah); url.searchParams.set('ayah', ayah);
            history.replaceState(null, '', url);
        } catch (e) {
            if (navigationRequests.isCurrent(request)) {
                els.surah.value = String(state.surah);
                renderAyahOptions(state.surah);
                els.ayah.value = String(state.ayah);
                setStatus('تعذّر تحميل بيانات هذه الآية', true);
            }
        } finally {
            if (navigationRequests.isCurrent(request)) {
                window.AtharUi.setBusy(els.main, false);
                updateStepper();
            }
        }
    }
    function updateStepper() {
        if (!els.prev || !els.next) return;
        const edges = window.AtharMushaf.verseEdges(state, {
            ayahCount: catalog.getCachedAyahCount(state.surah),
        });
        els.prev.disabled = edges.atStart;
        els.next.disabled = edges.atEnd;
    }

    /* ── كتب الوقف والابتداء: classical grades + العلل per stop ───────── */
    const MUKTAFA_GRADE = {
        'تام':  { cls: 'tamm',  desc: 'وقفٌ تام — يُوقف عليه ويُبتدأ بما بعده' },
        'كاف':  { cls: 'kafi',  desc: 'وقفٌ كافٍ — يُوقف عليه، وما بعده متعلقٌ به معنًى' },
        'حسن':  { cls: 'hasan', desc: 'وقفٌ حسن — يَحسُن الوقف ولا يَحسُن الابتداء بما بعده' },
        'جائز': { cls: 'jaiz',  desc: 'وقفٌ جائز' },
        'صالح': { cls: 'kafi',  desc: 'وقفٌ صالح' },
        'قبيح': { cls: 'qabih', desc: 'وقفٌ قبيح — لا يُوقف عليه' },
        'لا':   { cls: 'qabih', desc: 'ليس بوقف' },
    };
    async function loadMuktafa(surah, ayah) {
        if (!els.muktafaCard) return;
        els.muktafaCard.hidden = true;
        try {
            const j = await window.AtharApi.json(`/api/classical-waqf/${surah}/${ayah}`);
            if (surah !== state.surah || ayah !== state.ayah) return;   // stale response
            if (!j.count) return;
            const words = (state.data && state.data.words) || [];
            const srcName = id => (j.sources && j.sources[id] && j.sources[id].name) || id;
            // group by word position; within a stop, dedupe (source, grade)
            // keeping the richer علّة.
            const byPos = new Map();
            j.entries.forEach(e => {
                if (!byPos.has(e.wpos)) byPos.set(e.wpos, new Map());
                const k = e.source + '|' + e.grade;
                const g = byPos.get(e.wpos);
                if (!g.has(k) || (e.note || '').length > (g.get(k).note || '').length) g.set(k, e);
            });
            const qwc = q => ((q || '').match(/[؀-ۿ]{2,}/g) || []).length;   // words in a quote
            const stopList = [...byPos.keys()].sort((a, b) => a - b);
            let prev = -1;
            const rows = stopList.map(wpos => {
                const list = [...byPos.get(wpos).values()];
                // Show the PHRASE the imams graded, not a lone word: the mushaf
                // words up to the stop (its own last word emphasised), starting
                // from the longest quote among the sources but never crossing the
                // previous graded stop. The cap is a safety net against a
                // pathological quote, NOT a routine limit — نحاس alone quotes up
                // to 16 words (confirmed against the DB); an 8-word cap here used
                // to silently lop the FRONT off ~4% of his citations with no
                // indication anything was missing.
                const maxW = Math.min(24, Math.max(1, ...list.map(e => qwc(e.quote))));
                let start = Math.max(prev + 1, wpos - maxW + 1, 0);
                prev = wpos;
                let phrase;
                if (words.length && wpos < words.length) {
                    phrase = words.slice(start, wpos + 1).map((w, i, arr) =>
                        i === arr.length - 1 ? `<span class="wq-mk3-stopw">${w}</span>` : w).join(' ');
                } else {
                    phrase = `<span class="wq-mk3-stopw">${list[0].stop_word || ''}</span>`;
                }
                // These books constantly RELAY other scholars' rulings
                // («وقال ابن الأنباري: {X} تام»). When the backend flags
                // that, the grade is NOT necessarily the book's own author's
                // settled view — show it as "SOURCE ← عن SCHOLAR" rather
                // than a flat "SOURCE", or a relayed opinion reads as if the
                // book itself endorses it, which is the wrong waqf-type risk.
                const attrib = e => e.reported_from
                    ? `${srcName(e.source)} <span class="wq-mk3-relayed">نقلاً عن ${e.reported_from}</span>`
                    : srcName(e.source);
                // The reported_from tag only covers the OUTER attribution
                // («وقال ابن الأنباري: {X} تام»). Inside that same relayed
                // passage, the classical author often cites a FURTHER, nested
                // scholar for one specific point — «و ((ما)) صلة للكلام، وهو
                // قول الأخفش وأبي حاتم» — which never gets its own row (it's
                // not attached to a graded citation), but should still be
                // visually distinguishable when reading the علّة, not buried
                // as plain prose indistinguishable from the rest.
                // Trigger is narrow ON PURPOSE: bare «قول X» is too common for
                // non-attribution uses («في قول الله»: the WORDING of a verse,
                // not a scholar's opinion — verified false-positive on a real
                // sample) to highlight safely. «وهو قول X» ("AND IT IS the
                // opinion of X") is specifically the survey-of-views idiom
                // these books use, so require the «وهو» — never optional.
                // The name span stops at the next clause-continuation word
                // (plain prose after the name(s), verified against every real
                // «وهو قول» occurrence in the corpus) — imperfect on a few
                // longer sentences, but it's a readability aid over free text,
                // not structured data, so "mostly right" is an acceptable
                // trade-off. NOTE: \b does NOT work on Arabic letters in JS
                // regex (only recognises the ASCII word-char set), so the
                // stoppers are bounded by an explicit lookahead instead.
                const highlightCitedScholars = note => note.replace(
                    /(وهو\s+قول\s+)([^.,،؛:{}()\n]{2,35}?)(?=[.,،؛:]|\s+(?:لم|أو|إذ|لأن|حتى|قال|إلا|على)(?=[\s.,،؛:]|$)|$)/g,
                    (_, lead, name) => `${lead}<span class="wq-mk3-cited">${name}</span>`);
                const chips = list.map(e => {
                    const g = MUKTAFA_GRADE[e.grade] || { cls: 'kafi', desc: e.grade };
                    const title = e.reported_from
                        ? `${g.desc} — نقل ${srcName(e.source)} هذا عن ${e.reported_from}، وليس بالضرورة رأيه الخاص`
                        : g.desc;
                    return `<span class="wq-mk3-grade wq-mk3-${g.cls}" title="${title}">`
                        + `${e.grade_raw} <small>· ${attrib(e)}</small></span>`;
                }).join('');
                const notes = list.filter(e => (e.note || '').trim().length >= 18).map(e =>
                    `<details class="wq-mk3-note"><summary>العلّة — ${attrib(e)}</summary>`
                    + `<p>${highlightCitedScholars(e.note.trim())}</p></details>`).join('');
                return `<div class="wq-mk3-row">`
                    + `<span class="wq-mk3-phrase waqf-uthmanic" dir="rtl">${phrase}</span>${chips}${notes}</div>`;
            }).join('');
            els.muktafa.innerHTML = rows;
            const meta = Object.values(j.sources || {}).map(s2 => `${s2.title} — ${s2.author}`).join(' · ');
            els.muktafaSrc.textContent = meta;
            els.muktafaCard.hidden = false;
        } catch (e) { /* classical layer is optional — stay hidden */ }
    }

    /* ── waqf research by word (للدراسة) ──────────────────────────── */
    let researchState = { word: '', mode: '', forms: [], occ: [], form: null };

    async function runResearch(word, exact, mode) {
        word = (word || '').trim();
        mode = mode || '';
        if (!word) return;
        document.querySelectorAll('.wq-research-chip').forEach(c =>
            c.classList.toggle('wq-research-chip-active', c.dataset.word === word && (c.dataset.mode || '') === mode));
        els.researchForms.innerHTML = '';
        showState(els.researchResults, 'loading', 'جارٍ البحث…');
        try {
            let url = '/api/waqf-research?word=' + encodeURIComponent(word);
            if (exact) url += '&exact=1';
            if (mode) url += '&mode=' + mode;
            const d = await window.AtharApi.json(url);
            researchState = { word, mode, forms: d.forms || [], occ: d.occurrences || [], form: d.active_form || null, waqf: null };
            renderResearch();
            if (IS_LAB) {
                try {
                    const url = new URL(location.href);
                    url.searchParams.set('tab', 'word');
                    url.searchParams.set('family', 'words');
                    url.searchParams.set('q', word);
                    if (mode) url.searchParams.set('mode', mode); else url.searchParams.delete('mode');
                    if (exact) url.searchParams.set('exact', '1'); else url.searchParams.delete('exact');
                    history.replaceState(null, '', url);
                } catch (_e) {}
            }
        } catch (e) {
            showState(els.researchResults, 'error', 'تعذّر البحث');
        }
    }

    function renderResearch() {
        const { forms, occ, form, waqf } = researchState;
        const byForm = form ? occ.filter(o => o.form === form) : occ;
        const wWith = byForm.filter(o => o.has_waqf).length;
        const wWithout = byForm.length - wWith;

        // filter chips: by exact form, then by waqf behavior
        let bar = '';
        if (forms.length > 1) {
            bar += '<div class="wq-research-frow"><span class="wq-research-flabel">الصيغة</span>'
                + `<button class="wq-form-chip${!form ? ' wq-form-chip-active' : ''}" data-form="">الكل <b>${toAr(occ.length)}</b></button>`
                + forms.map(f => `<button class="wq-form-chip${form === f.word ? ' wq-form-chip-active' : ''}" data-form="${f.word}"><span class="wq-form-word">${f.word}</span> <b>${toAr(f.count)}</b></button>`).join('')
                + '</div>';
        }
        if (wWith && wWithout) {
            bar += '<div class="wq-research-frow"><span class="wq-research-flabel">الوقف</span>'
                + `<button class="wq-wfilter${!waqf ? ' wq-wfilter-active' : ''}" data-waqf="">الكل</button>`
                + `<button class="wq-wfilter${waqf === 'yes' ? ' wq-wfilter-active' : ''}" data-waqf="yes"><i class="fas fa-pause"></i> بعلامة وقف <b>${toAr(wWith)}</b></button>`
                + `<button class="wq-wfilter${waqf === 'no' ? ' wq-wfilter-active' : ''}" data-waqf="no">بلا علامة <b>${toAr(wWithout)}</b></button>`
                + '</div>';
        }
        els.researchForms.innerHTML = bar;

        let list = byForm;
        if (waqf === 'yes') list = list.filter(o => o.has_waqf);
        else if (waqf === 'no') list = list.filter(o => !o.has_waqf);
        if (!list.length) { els.researchResults.innerHTML = '<div class="wq-research-empty">لا نتائج</div>'; return; }

        const modeNote = researchState.mode === 'before'
            ? `<div class="wq-research-mode-note">علامات الوقف على الكلمة <b>قبل</b> «${researchState.word}»</div>` : '';
        labListState.word = HIT_PAGE;
        const renderItem = o => hitRowFromOcc(o, {
            title: `افتح ${surahName(o.surah)} ${toAr(o.surah)}:${toAr(o.ayah)} لرؤية وقوف القرّاء والمصاحف`,
        });
        els.researchResults.innerHTML = `<div class="wq-research-count">${toAr(list.length)} موضعًا</div>`
            + modeNote + paginateList('word', list, renderItem);
        wireHitMore(els.researchResults, 'word', list, renderItem);
    }

    /* ── solo stops (انفرادات القرّاء) ────────────────────────────── */
    let solosCache = null;
    let solosReciterCache = {};

    async function loadSolosSummary() {
        if (solosCache) { renderSolosSummary(); return; }
        showState(els.solosContent, 'loading', 'جارٍ التحليل…');
        try {
            solosCache = await window.AtharApi.json('/api/waqf-research/solos');
            renderSolosSummary();
        } catch { showState(els.solosContent, 'error', 'تعذّر التحميل'); }
    }

    function renderSolosSummary() {
        const reciters = (solosCache.reciters || []).slice().sort((a, b) => b.solo_count - a.solo_count);
        if (!reciters.length) { els.solosContent.innerHTML = '<div class="wq-research-empty">لا بيانات</div>'; return; }
        const maxSolo = Math.max(...reciters.map(r => r.solo_count), 1);
        els.solosContent.innerHTML =
            toolBlurb('مواضع وقف انفرد بها كل قارئ دون بقية القرّاء.')
            + '<div class="wq-solos-rank">' + reciters.map(r => {
                const pct = Math.round((r.solo_count / maxSolo) * 100);
                return `<button class="wq-solos-rank-row" data-rid="${r.id}" type="button">
                    <span class="wq-solos-rank-name">${r.name_ar}</span>
                    <span class="wq-solos-rank-count">${toAr(r.solo_count)}</span>
                    <span class="wq-solos-rank-bar"><span class="wq-solos-rank-fill" style="width:${pct}%"></span></span>
                </button>`;
            }).join('') + '</div>';
    }

    async function loadSolosDetail(rid) {
        if (solosReciterCache[rid]) { renderSolosDetail(solosReciterCache[rid]); return; }
        showState(els.solosContent, 'loading', 'جارٍ التحميل…');
        try {
            const d = await window.AtharApi.json('/api/waqf-research/solos?reciter=' + encodeURIComponent(rid));
            solosReciterCache[rid] = d;
            renderSolosDetail(d);
        } catch { showState(els.solosContent, 'error', 'تعذّر التحميل'); }
    }

    function renderSolosDetail(d) {
        const stops = d.stops || [];
        const withMark = stops.filter(o => o.has_waqf).length;
        const withoutMark = stops.length - withMark;
        let header = `<div class="wq-solos-header">
            <button class="wq-solos-back" type="button"><i class="fas fa-arrow-right"></i></button>
            <span class="wq-solos-title">${d.reciter.name_ar}</span>
            <span class="wq-research-count">${toAr(stops.length)} انفراد</span>
        </div>`;
        if (withMark && withoutMark) {
            header += '<div class="wq-research-frow"><span class="wq-research-flabel">الوقف المطبوع</span>'
                + `<button class="wq-wfilter wq-wfilter-active" data-sf="">الكل</button>`
                + `<button class="wq-wfilter" data-sf="yes"><i class="fas fa-pause"></i> يوافق مصحفًا <b>${toAr(withMark)}</b></button>`
                + `<button class="wq-wfilter" data-sf="no">بلا علامة <b>${toAr(withoutMark)}</b></button></div>`;
        }
        let list = stops;
        labListState.solos = HIT_PAGE;
        els.solosContent.innerHTML = header + renderSoloItems(list);
        wireHitMore(els.solosContent, 'solos', list, o => hitRowFromOcc(o));
        const frow = els.solosContent.querySelector('.wq-research-frow');
        if (frow) frow.addEventListener('click', e => {
            const btn = e.target.closest('.wq-wfilter'); if (!btn) return;
            frow.querySelectorAll('.wq-wfilter').forEach(b => b.classList.remove('wq-wfilter-active'));
            btn.classList.add('wq-wfilter-active');
            const f = btn.dataset.sf;
            const filtered = !f ? stops : f === 'yes' ? stops.filter(o => o.has_waqf) : stops.filter(o => !o.has_waqf);
            labListState.solos = HIT_PAGE;
            const host = els.solosContent.querySelector('.wq-hit-list')?.parentElement || els.solosContent;
            const listEl = els.solosContent.querySelector('.wq-hit-list');
            const html = renderSoloItems(filtered);
            if (listEl) listEl.outerHTML = html;
            else els.solosContent.insertAdjacentHTML('beforeend', html);
            wireHitMore(els.solosContent, 'solos', filtered, o => hitRowFromOcc(o));
        });
    }

    function renderSoloItems(list) {
        labListState.solos = HIT_PAGE;
        return paginateList('solos', list, o => hitRowFromOcc(o));
    }

    /* ── إحصائيات (stats tab) ──────────────────────────────────── */
    let statsCache = null, consensusCache = null, statsView = 'surahs';

    async function loadStats() {
        if (statsCache) { renderStats(); return; }
        showState(els.statsContent, 'loading', 'جارٍ التحليل…');
        try {
            statsCache = await window.AtharApi.json('/api/waqf-research/stats');
            statsView = 'surahs';
            renderStats();
        } catch { showState(els.statsContent, 'error', 'تعذّر التحميل'); }
    }

    async function loadConsensus() {
        if (consensusCache) { renderConsensus(); return; }
        showState(els.statsContent, 'loading', 'جارٍ التحميل…');
        try {
            consensusCache = await window.AtharApi.json('/api/waqf-research/stats?view=consensus');
            renderConsensus();
        } catch { showState(els.statsContent, 'error', 'تعذّر التحميل'); }
    }

    function renderStats() {
        const surahs = (statsCache.surahs || []).slice().sort((a, b) => b.divergent - a.divergent);
        const topV = statsCache.top_divergent || [];
        const totalDiv = surahs.reduce((s, x) => s + x.divergent, 0);
        const totalCons = surahs.reduce((s, x) => s + x.consensus, 0);

        const strip = `<div class="wq-stats-strip">
            <div class="wq-stats-strip-item"><span class="wq-stats-strip-val">${toAr(totalDiv)}</span><span class="wq-stats-strip-lbl">موضع اختلاف</span></div>
            <div class="wq-stats-strip-item"><span class="wq-stats-strip-val">${toAr(totalCons)}</span><span class="wq-stats-strip-lbl">موضع اتفاق تام</span></div>
        </div>`;
        let tabs = `<div class="wq-stats-subtabs">
            <button class="wq-stats-subtab${statsView === 'surahs' ? ' wq-lab-tab-active' : ''}" data-sv="surahs">السور</button>
            <button class="wq-stats-subtab${statsView === 'verses' ? ' wq-lab-tab-active' : ''}" data-sv="verses">أكثر الآيات اختلافًا</button>
            <button class="wq-stats-subtab${statsView === 'consensus' ? ' wq-lab-tab-active' : ''}" data-sv="consensus">مواضع الاتفاق</button>
        </div>`;

        let body = '';
        if (statsView === 'surahs') {
            body = '<div class="wq-stats-list">' + surahs.filter(s => s.total > 0).map(s => {
                    const pct = s.total ? Math.round(s.consensus / s.total * 100) : 0;
                    return `<div class="wq-stats-row">
                        <span class="wq-stats-sname">${s.name} <b>${toAr(s.surah)}</b></span>
                        <span class="wq-stats-bar"><span class="wq-stats-fill" style="width:${pct}%"></span></span>
                        <span class="wq-stats-nums"><span class="wq-stats-cons">${toAr(s.consensus)}</span> / <span class="wq-stats-div">${toAr(s.divergent)}</span></span>
                    </div>`;
                }).join('') + '</div>';
        } else if (statsView === 'verses') {
            const verses = topV.slice(0, 80);
            labListState.statsVerses = HIT_PAGE;
            const renderItem = v => hitRowFromOcc({ surah: v.surah, ayah: v.ayah, context: '', marks: {} }, {
                hideMarks: true,
                meta: `<span class="wq-stats-badge wq-stats-div">${toAr(v.divergent)} اختلاف</span>`
                    + `<span class="wq-stats-badge wq-stats-cons">${toAr(v.consensus)} اتفاق</span>`,
            });
            body = paginateList('statsVerses', verses, renderItem);
        }
        els.statsContent.innerHTML = strip + tabs + body;
        if (statsView === 'verses') {
            const verses = topV.slice(0, 80);
            wireHitMore(els.statsContent, 'statsVerses', verses, v => hitRowFromOcc({ surah: v.surah, ayah: v.ayah, context: '', marks: {} }, {
                hideMarks: true,
                meta: `<span class="wq-stats-badge wq-stats-div">${toAr(v.divergent)} اختلاف</span>`
                    + `<span class="wq-stats-badge wq-stats-cons">${toAr(v.consensus)} اتفاق</span>`,
            }));
        }
    }

    function renderConsensus() {
        const items = consensusCache.consensus || [];
        const surahs = (statsCache && statsCache.surahs) || [];
        const totalDiv = surahs.reduce((s, x) => s + x.divergent, 0);
        const totalCons = surahs.reduce((s, x) => s + x.consensus, 0);
        const strip = `<div class="wq-stats-strip">
            <div class="wq-stats-strip-item"><span class="wq-stats-strip-val">${toAr(totalDiv)}</span><span class="wq-stats-strip-lbl">موضع اختلاف</span></div>
            <div class="wq-stats-strip-item"><span class="wq-stats-strip-val">${toAr(totalCons || items.length)}</span><span class="wq-stats-strip-lbl">موضع اتفاق</span></div>
        </div>`;
        let tabs = `<div class="wq-stats-subtabs">
            <button class="wq-stats-subtab" data-sv="surahs">السور</button>
            <button class="wq-stats-subtab" data-sv="verses">أكثر الآيات اختلافًا</button>
            <button class="wq-stats-subtab wq-lab-tab-active" data-sv="consensus">مواضع الاتفاق</button>
        </div>`;
        labListState.consensus = HIT_PAGE;
        const renderItem = o => hitRowFromOcc(o, { withEditor: true, meta: '<span class="wq-agree-pill wq-agree-pill-full">كلهم</span>' });
        const body = toolBlurb('مواضع اتفق عليها جميع القرّاء ولها علامة مطبوعة.')
            + `<div class="wq-research-count">${toAr(items.length)} موضعًا</div>`
            + paginateList('consensus', items, renderItem);
        els.statsContent.innerHTML = strip + tabs + body;
        wireHitMore(els.statsContent, 'consensus', items, renderItem);
    }

    /* ── الوقف اللازم والممنوع (mandatory tab) ──────────────────── */
    let mandatoryCache = null, mandView = 'mandatory';

    async function loadMandatory() {
        if (mandatoryCache) { renderMandatory(); return; }
        showState(els.mandatoryContent, 'loading', 'جارٍ التحميل…');
        try {
            mandatoryCache = await window.AtharApi.json('/api/waqf-research/mandatory');
            renderMandatory();
        } catch { showState(els.mandatoryContent, 'error', 'تعذّر التحميل'); }
    }

    function renderMandatory() {
        const mand = mandatoryCache.mandatory || [];
        const forb = mandatoryCache.forbidden || [];
        const embr = mandatoryCache.embracing || [];
        let tabs = `<div class="wq-stats-subtabs">
            <button class="wq-stats-subtab${mandView === 'mandatory' ? ' wq-lab-tab-active' : ''}" data-mv="mandatory">
                <span class="wq-mand-chip wq-w-must">م</span> اللازم <b>${toAr(mand.length)}</b>
            </button>
            <button class="wq-stats-subtab${mandView === 'forbidden' ? ' wq-lab-tab-active' : ''}" data-mv="forbidden">
                <span class="wq-mand-chip wq-w-no">لا</span> الممنوع <b>${toAr(forb.length)}</b>
            </button>
            <button class="wq-stats-subtab${mandView === 'embracing' ? ' wq-lab-tab-active' : ''}" data-mv="embracing">
                <span class="wq-mand-chip wq-w-muan">ع</span> المعانقة <b>${toAr(embr.length)}</b>
            </button>
        </div>`;
        const descs = {
            mandatory: 'مواضع الوقف اللازم (م) — يجب الوقف عليها',
            forbidden: 'مواضع الوقف الممنوع (لا) — لا يصح الوقف عليها',
            embracing: 'وقف المعانقة (ع) — يُوقف على أحد الموضعين فقط، لا كليهما',
        };
        let body = toolBlurb(descs[mandView]);
        if (mandView === 'embracing') {
            body += renderEmbracingItems(embr);
            els.mandatoryContent.innerHTML = tabs + body;
            wireHitMore(els.mandatoryContent, 'embracing', embr, o => {
                const pair = o.pair || [];
                const flow = pair.map(p => {
                    const marks = marksHtml(p.marks || {});
                    return `<span class="wq-hit-chip">${p.word}</span><span class="wq-hit-marks" style="border:0;padding:0">${marks}</span>`;
                }).join('<span class="wq-hit-chip wq-hit-chip-muted">أو</span>');
                return hitRowFromOcc({ surah: o.surah, ayah: o.ayah, context: '', marks: {} }, {
                    hideMarks: true,
                    flow: `<div class="wq-muan-pair-block">${flow}</div>`,
                    meta: agreePill(o.agreement),
                    extraClass: 'wq-muan-item',
                });
            });
        } else {
            const items = mandView === 'mandatory' ? mand : forb;
            const key = mandView;
            body += renderMandItems(items);
            els.mandatoryContent.innerHTML = tabs + body;
            wireHitMore(els.mandatoryContent, key, items, o => hitRowFromOcc(o, { meta: agreePill(o.agreement) }));
        }
    }

    function renderEmbracingItems(list) {
        labListState.embracing = HIT_PAGE;
        return paginateList('embracing', list, o => {
            const pair = o.pair || [];
            const flow = pair.map(p => {
                const marks = marksHtml(p.marks || {});
                return `<span class="wq-hit-chip">${p.word}</span><span class="wq-hit-marks" style="border:0;padding:0">${marks}</span>`;
            }).join('<span class="wq-hit-chip wq-hit-chip-muted">أو</span>');
            return hitRowFromOcc({ surah: o.surah, ayah: o.ayah, context: '', marks: {} }, {
                hideMarks: true,
                flow: `<div class="wq-muan-pair-block">${flow}</div>`,
                meta: agreePill(o.agreement),
                extraClass: 'wq-muan-item',
            });
        });
    }

    function renderMandItems(list) {
        const key = mandView === 'mandatory' ? 'mandatory' : 'forbidden';
        labListState[key] = HIT_PAGE;
        return paginateList(key, list, o => hitRowFromOcc(o, { meta: agreePill(o.agreement) }));
    }

    /* ── اختلاف المصاحف (cross-verse patterns) ─────────────────── */
    let patternsCache = null;

    async function loadPatterns() {
        if (patternsCache) { renderPatterns(); return; }
        showState(els.patternsContent, 'loading', 'جارٍ التحليل…');
        try {
            patternsCache = await window.AtharApi.json('/api/waqf-research/patterns');
            renderPatterns();
        } catch { showState(els.patternsContent, 'error', 'تعذّر التحميل'); }
    }

    function renderPatterns() {
        const items = patternsCache.disagreements || [];
        labListState.patterns = HIT_PAGE;
        const renderItem = o => hitRowFromOcc(o, {
            withEditor: true,
            marksHtml: marksHtml(o.marks || {}),
        });
        els.patternsContent.innerHTML =
            toolBlurb('مواضع اختلفت فيها المصاحف في علامة الوقف على نفس الكلمة.')
            + `<div class="wq-research-count">${toAr(items.length)} موضع اختلاف</div>`
            + paginateList('patterns', items, renderItem);
        wireHitMore(els.patternsContent, 'patterns', items, renderItem);
    }

    /* ── اتفاق القرّاء مع المصاحف ──────────────────────────────── */
    let agreementCache = null, agreementMushaf = null;
    // How "agreement" reads, derived from each mark's directive (per mushaf).
    const agreeVerb = m => m.dir === 'choice' ? 'نسبة الوقف' : m.dir === 'stop' ? 'يقف' : 'يصِل';
    const agreeDesc = m => m.dir === 'choice'
        ? 'جائز — نسبة وقفه عنده؛ الأعلى يعامله كقلى (يقف)، الأدنى كصلى (يصِل)'
        : `${m.name} — موافق إذا ${m.dir === 'stop' ? 'وقف' : 'وصَل (لم يقف)'}`;

    async function loadAgreement() {
        if (agreementCache) { renderAgreement(); return; }
        showState(els.agreementContent, 'loading', 'جارٍ تحليل وقوف القرّاء عبر المصحف كاملًا…');
        try {
            agreementCache = await window.AtharApi.json('/api/waqf-research/mushaf-agreement');
            agreementMushaf = (agreementCache.mushafs || [])[0] || null;
            renderAgreement();
        } catch { showState(els.agreementContent, 'error', 'تعذّر التحميل'); }
    }

    function renderAgreement() {
        const d = agreementCache;
        const ver = agreementMushaf;
        const marks = d.mark_config[ver] || [];
        const glyphCls = ver === 'ورش' ? 'waqf-warsh' : 'waqf-uthmanic';
        const pct = (cell) => cell && cell[1] ? Math.round(cell[0] / cell[1] * 100) : null;
        const tabs = (d.mushafs || []).map(m =>
            `<button class="wq-stats-subtab${m === ver ? ' wq-lab-tab-active' : ''}" data-mushaf="${m}">${m}</button>`).join('');
        const warsh = ver === 'ورش'
            ? '<span class="wq-agree-leg wq-agree-leg-j"><b>صه</b> في الورش = «اصمت / قف هنا» — فالموافقة هنا أن يقف القارئ.</span>'
            : '';
        const legend = `<details class="wq-tool-blurb-disclosure"><summary>معنى الأعمدة</summary><div class="wq-agree-legend">`
            + marks.map(m => {
                let desc = agreeDesc(m);
                if (m.dir === 'choice') desc += ` (${toAr(d.jaiz[ver] || 0)} موضعًا)`;
                return `<span class="wq-agree-leg"><span class="${glyphCls} wq-agree-glyph">${m.glyph}</span> <b>${m.name}</b> — ${desc}</span>`;
            }).join('')
            + warsh
            + '</div></details>';
        const head = toolBlurb(
            `موافقة القرّاء لمصحف «${ver}». اضغط خلية أو شريطًا لعرض الآيات.`,
            'عمود ج = نسبة الوقف عند الجائز (ليس صوابًا/خطأً). الأعلى يعامله كقلى، الأدنى كصلى.'
        );
        let jLo = 1, jHi = 0;
        (d.reciters || []).forEach(r => {
            const c = d.agreement[ver][r.id]['ج'];
            if (c && c[1]) { const p = c[0] / c[1]; jLo = Math.min(jLo, p); jHi = Math.max(jHi, p); }
        });
        const rows = (d.reciters || []).map(r => {
            const ag = d.agreement[ver][r.id];
            const cells = marks.map(m => {
                const c = ag[m.sym], p = pct(c);
                if (p === null) return '<td class="wq-agree-cell wq-agree-na">—</td>';
                if (m.dir === 'choice') {
                    const rate = c[0] / c[1];
                    const t = jHi > jLo ? (rate - jLo) / (jHi - jLo) : 0.5;
                    const lean = t >= 0.6 ? 'كقلى' : t <= 0.4 ? 'كصلى' : 'متوسط';
                    const bg = `color-mix(in srgb, var(--wq-solo) ${Math.round(t * 100)}%, var(--wq-consensus))`;
                    return `<td class="wq-agree-cell wq-agree-jaiz" data-rid="${r.id}" data-mark="ج"
                        style="background:${bg};color:#fff" title="يقف عند الجائز ${toAr(p)}٪">
                        <b>${toAr(p)}٪</b><span class="wq-agree-frac">${lean}</span></td>`;
                }
                const lvl = p >= 80 ? 'hi' : p >= 50 ? 'mid' : 'lo';
                return `<td class="wq-agree-cell wq-agree-${lvl}" data-rid="${r.id}" data-mark="${m.sym}"
                    title="${m.name}: وافق ${toAr(c[0])} من ${toAr(c[1])}">
                    <b>${toAr(p)}٪</b><span class="wq-agree-frac">${toAr(c[0])}/${toAr(c[1])}</span></td>`;
            }).join('');
            const qasr = r.qasr ? '<span class="wq-agree-qasr">قصر المنفصل</span>' : '';
            return `<tr><td class="wq-agree-rname">${r.name_ar}${qasr}</td>${cells}</tr>`;
        }).join('');
        const header = `<tr><th>القارئ</th>${marks.map(m => {
            const thName = m.dir === 'choice' ? `${m.name}<br><small>نسبة الوقف</small>` : `${m.name}<br><small>${agreeVerb(m)}</small>`;
            return `<th title="${agreeDesc(m)}"><span class="${glyphCls} wq-agree-glyph">${m.glyph}</span><span class="wq-agree-th">${thName}</span></th>`;
        }).join('')}</tr>`;

        const mobileCards = (d.reciters || []).map(r => {
            const ag = d.agreement[ver][r.id];
            const markRows = marks.map(m => {
                const c = ag[m.sym], p = pct(c);
                if (p === null) return '';
                return `<div class="wq-agree-card-mark" data-rid="${r.id}" data-mark="${m.sym}" role="button" tabindex="0">
                    <span class="${glyphCls}">${m.glyph}</span>
                    <span class="wq-agree-card-bar"><span class="wq-agree-card-fill" style="width:${p}%"></span></span>
                    <b>${toAr(p)}٪</b>
                </div>`;
            }).join('');
            return `<div class="wq-agree-card"><div class="wq-agree-card-top"><b>${r.name_ar}</b></div>
                <div class="wq-agree-card-marks">${markRows}</div></div>`;
        }).join('');

        els.agreementContent.innerHTML = head
            + `<div class="wq-agree-tabs">${tabs}</div>`
            + legend
            + `<div class="wq-agree-desktop wq-agree-scroll"><table class="wq-agree-table"><thead>${header}</thead><tbody>${rows}</tbody></table></div>`
            + `<div class="wq-agree-mobile"><div class="wq-agree-card-list">${mobileCards}</div></div>`
            + '<div id="wq-agree-cases"></div>';
    }

    // Drill-down: the verses where a reciter went against a mushaf's mark.
    async function showAgreementCases(rid, mark) {
        const box = document.getElementById('wq-agree-cases');
        if (!box) return;
        const r = (agreementCache.reciters || []).find(x => x.id === rid);
        const m = (agreementCache.mark_config[agreementMushaf] || []).find(x => x.sym === mark);
        const went = m && m.dir === 'choice' ? 'وقف عند'
            : m && m.dir === 'stop' ? 'لم يقف عند' : 'وقف عند';
        showState(box, 'loading', 'جارٍ الجلب…');
        try {
            const q = `mushaf=${encodeURIComponent(agreementMushaf)}&reciter=${encodeURIComponent(rid)}&mark=${encodeURIComponent(mark)}`;
            const j = await window.AtharApi.json('/api/waqf-research/mushaf-agreement/cases?' + q);
            if (!j.verses || !j.verses.length) {
                const msg = m && m.dir === 'choice' ? 'لم يقف عند أيٍّ من مواضع الجائز.' : 'لا مخالفات — وافق العلامة في كل المواضع.';
                box.innerHTML = `<div class="wq-research-empty">${msg}</div>`; return;
            }
            labListState.agreeCases = HIT_PAGE;
            const verses = j.verses;
            const renderItem = v => hitRowFromOcc({
                surah: v.surah, ayah: v.ayah, context: '', marks: {},
            }, { hideMarks: true });
            box.innerHTML = `<div class="wq-agree-cases-head">${r ? r.name_ar : ''} — <b>${m ? m.name : mark}</b>: `
                + `${went} العلامة في <b>${toAr(j.disagreed)}</b> موضعًا`
                + `${j.capped ? ` (عُرض أول ${toAr(j.shown)})` : ''}</div>`
                + paginateList('agreeCases', verses, renderItem);
            wireHitMore(box, 'agreeCases', verses, renderItem);
        } catch { showState(box, 'error', 'تعذّر التحميل'); }
    }

    /* ── السكتات (Hafs obligatory pauses-without-breath) ───────── */
    let saktatCache = null;

    async function loadSaktat() {
        if (saktatCache) { renderSaktat(); return; }
        showState(els.saktatContent, 'loading', 'جارٍ التحميل…');
        try {
            saktatCache = await window.AtharApi.json('/api/waqf-research/saktat');
            renderSaktat();
        } catch { showState(els.saktatContent, 'error', 'تعذّر التحميل'); }
    }

    function renderSaktat() {
        const items = saktatCache.saktat || [];
        labListState.saktat = HIT_PAGE;
        const renderItem = o => {
            const cat = o.category === 'واجبة'
                ? '<span class="wq-skt-cat wq-skt-wajiba">واجبة</span>'
                : '<span class="wq-skt-cat wq-skt-jaiza">جائزة بوجهين</span>';
            const cross = o.cross_verse
                ? `<span class="wq-skt-cross">بين ${toAr(o.surah)}:${toAr(o.ayah)} و${toAr(o.next.surah)}:${toAr(o.next.ayah)}</span>` : '';
            const flow = `سكتة على <span class="wq-hit-chip">${o.on_word}</span>`
                + `<span class="wq-hit-chip wq-hit-chip-muted">ثم</span>`
                + `<span class="wq-hit-chip">${o.next_word}</span>`;
            return hitRowFromOcc({
                surah: o.surah, ayah: o.ayah,
                context: o.reason || '',
                marks: {},
                wpos: o.wpos,
                word: o.on_word,
            }, {
                hideMarks: true,
                meta: cat + cross,
                flow,
                extraClass: 'wq-skt-item',
            });
        };
        els.saktatContent.innerHTML =
            toolBlurb(`سكتات حفص: ${toAr(saktatCache.obligatory)} واجبة — وقفة يسيرة بلا تنفّس.`)
            + paginateList('saktat', items, renderItem);
        wireHitMore(els.saktatContent, 'saktat', items, renderItem);
    }

    /* ── الابتداء بما قبله (attested back-up points) ───────────── */
    let ibtidaaCache = null, ibtidaaOnlyMulti = true;

    async function loadIbtidaa() {
        if (ibtidaaCache) { renderIbtidaa(); return; }
        showState(els.ibtidaaContent, 'loading', 'جارٍ تحليل تلاوات القرّاء…');
        try {
            ibtidaaCache = await window.AtharApi.json('/api/waqf-research/ibtidaa');
            renderIbtidaa();
        } catch { showState(els.ibtidaaContent, 'error', 'تعذّر التحميل'); }
    }

    function renderIbtidaa() {
        const all = ibtidaaCache.items || [];
        const items = (ibtidaaOnlyMulti ? all.filter(o => o.count >= 2) : all).slice(0, 300);
        labListState.ibtidaa = HIT_PAGE;
        const head =
            toolBlurb(
                'وقف ثم ابتداء بما قبله — من تلاوات القرّاء.',
                'مواضع وقف عليها القارئ ثم عاد فقرأ من كلمة قبلها. كلّما زاد عدد القرّاء الذين رجعوا في الموضع نفسه قوي الدليل.'
            )
            + `<div class="wq-ibt-controls">
                 <button class="wq-stats-subtab${ibtidaaOnlyMulti ? ' wq-lab-tab-active' : ''}" data-im="multi">قارئان فأكثر (${toAr(ibtidaaCache.multi_reciter)})</button>
                 <button class="wq-stats-subtab${ibtidaaOnlyMulti ? '' : ' wq-lab-tab-active'}" data-im="all">الكل (${toAr(ibtidaaCache.count)})</button>
               </div>`;
        const renderItem = o => {
            const dist = o.back_distance === 0
                ? 'أعاد الكلمة نفسها'
                : `رجع ${toAr(o.back_distance)} ${o.back_distance <= 2 ? 'كلمة' : 'كلمات'}`;
            const markTag = o.stop_marked
                ? '<span class="wq-ibt-marked">عليه علامة</span>'
                : '<span class="wq-ibt-unmarked">بلا علامة</span>';
            const flow = `يقف على <span class="wq-hit-chip">${o.stop_word}</span>`
                + `<span class="wq-hit-chip wq-hit-chip-muted">ثم يبدأ من</span>`
                + `<span class="wq-hit-chip">${o.resume_word}</span>`
                + `<span class="wq-hit-chip wq-hit-chip-muted">${dist}</span>`;
            return hitRowFromOcc({
                surah: o.surah, ayah: o.ayah, context: o.context || '', marks: {},
                word: o.stop_word,
            }, {
                hideMarks: true,
                meta: `<span class="wq-ibt-count">${toAr(o.count)} قارئ</span>${markTag}`,
                flow,
                title: (o.reciters || []).join('، '),
                extraClass: 'wq-ibt-item',
            });
        };
        els.ibtidaaContent.innerHTML = head + paginateList('ibtidaa', items, renderItem);
        wireHitMore(els.ibtidaaContent, 'ibtidaa', items, renderItem);
    }

    /* ── تشابه القرّاء (reciter clustering) ────────────────────── */
    let clusterCache = null;

    async function loadCluster() {
        if (clusterCache) { renderCluster(); return; }
        showState(els.clusterContent, 'loading', 'جارٍ التحليل…');
        try {
            clusterCache = await window.AtharApi.json('/api/waqf-research/clustering');
            renderCluster();
        } catch { showState(els.clusterContent, 'error', 'تعذّر التحميل'); }
    }

    // Heat colour for a similarity, scaled to the actual [min,max] range so the
    // subtle differences (everyone shares the strong stops) become visible.
    function clusterHeat(sim, lo, hi, self) {
        if (self) return 'background:var(--wq-accent-strong);color:#fff';
        const t = hi > lo ? Math.max(0, Math.min(1, (sim - lo) / (hi - lo))) : 0.5;
        // light (low) → strong accent (high)
        const alpha = (0.08 + t * 0.92).toFixed(2);
        return `background:color-mix(in srgb, var(--wq-accent) ${Math.round(alpha * 100)}%, transparent);`
            + (t > 0.6 ? 'color:#fff;' : 'color:var(--wq-text);');
    }

    function renderCluster() {
        const d = clusterCache;
        const order = d.order || [];
        const lo = d.range.min, hi = d.range.max;
        const idx = order.map((o, i) => i);

        const desc = toolBlurb(
            'تشابه أنماط الوقف بين القرّاء (جاكار).',
            'القرّاء مرتّبون بحيث يتجاور المتشابهون. على الشاشات الصغيرة تُعرض المجموعات والأزواج بدل شبكة الألوان.'
        );

        const clusters = (d.clusters || []).filter(c => c.size > 1);
        const singles = (d.clusters || []).filter(c => c.size === 1).flatMap(c => c.members.map(m => m.name_ar));
        let clHtml = '<div class="wq-cl-groups">';
        clusters.forEach((c, i) => {
            clHtml += `<div class="wq-cl-group"><span class="wq-cl-gtag">المجموعة ${toAr(i + 1)} · تماسك ${toAr(Math.round(c.cohesion * 100))}٪</span>`
                + c.members.map(m => `<span class="wq-cl-chip">${m.name_ar}</span>`).join('') + '</div>';
        });
        if (singles.length) clHtml += `<div class="wq-cl-group"><span class="wq-cl-gtag wq-cl-gtag-out">قرّاء متفرّدون</span>`
            + singles.map(n => `<span class="wq-cl-chip wq-cl-chip-out">${n}</span>`).join('') + '</div>';
        clHtml += '</div>';

        const headCells = idx.map(i => `<th class="wq-cl-hth" title="${order[i].name_ar}">${toAr(i + 1)}</th>`).join('');
        const rows = order.map((ro, ri) => {
            const cells = order.map((co, ci) => {
                const s = d.matrix[ro.id][co.id];
                const self = ri === ci;
                return `<td class="wq-cl-cell" style="${clusterHeat(s, lo, hi, self)}" title="${ro.name_ar} × ${co.name_ar}: ${toAr(Math.round(s * 100))}٪">${self ? '' : toAr(Math.round(s * 100))}</td>`;
            }).join('');
            const q = ro.qasr ? '<span class="wq-cl-q" title="قصر المنفصل">قصر</span>' : '';
            return `<tr><td class="wq-cl-rh"><span class="wq-cl-rnum">${toAr(ri + 1)}</span> ${ro.name_ar}${q}</td>${cells}</tr>`;
        }).join('');
        const heat = `<div class="wq-cl-desktop wq-cl-heatwrap"><table class="wq-cl-heat"><thead><tr><th></th>${headCells}</tr></thead><tbody>${rows}</tbody></table></div>`;

        const alike = (d.similar || d.closest || []).slice(0, 6);
        const different = (d.different || []).slice(0, 6);
        const pairCard = (p, tone) => {
            const pct = toAr(Math.round((p.similarity != null ? p.similarity : p.sim || 0) * 100));
            const n1 = p.n1 || p.a || '';
            const n2 = p.n2 || p.b || '';
            return `<div class="wq-cl-pair-card"><div class="wq-cl-pair-card-top"><b>${n1} ↔ ${n2}</b><span>${pct}٪</span></div>
                <span class="wq-hit-chip wq-hit-chip-muted">${tone}</span></div>`;
        };
        const mobile = `<div class="wq-cl-mobile">
            <div class="wq-cl-sub">أبعد القرّاء تشابهًا</div>
            <div class="wq-cl-pair-cards">${different.map(p => pairCard(p, 'أقل تشابهًا')).join('')}</div>
            ${alike.length ? `<div class="wq-cl-sub">أقرب القرّاء</div><div class="wq-cl-pair-cards">${alike.map(p => pairCard(p, 'أكثر تشابهًا')).join('')}</div>` : ''}
        </div>`;

        const diff = different.map(p =>
            `<span class="wq-cl-pair"><span class="wq-cl-pair-pct">${toAr(Math.round(p.similarity * 100))}٪</span>
                <span>${p.n1} ↔ ${p.n2}</span></span>`).join('');
        const diffHtml = `<div class="wq-cl-desktop"><div class="wq-cl-sub">أبعد القرّاء تشابهًا</div><div class="wq-cl-pairs">${diff}</div></div>`;

        els.clusterContent.innerHTML = desc + clHtml + heat + diffHtml + mobile;
    }

    /* ── تقارب المصاحف (mushaf-system similarity → dendrogram) ──────── */
    let mushafSimCache = null;
    async function loadMushafSim() {
        if (mushafSimCache) { renderMushafSim(); return; }
        showState(els.mushafSimContent, 'loading', 'جارٍ مقارنة أنظمة الوقف…');
        try {
            mushafSimCache = await window.AtharApi.json('/api/waqf-research/mushaf-similarity');
            renderMushafSim();
        } catch { showState(els.mushafSimContent, 'error', 'تعذّر التحميل'); }
    }

    // A horizontal dendrogram (RTL): leaves on the right, the tree branches left
    // as the agreement drops — each fork is labelled with the % at which the two
    // sides still issue the SAME ruling. Reads top-to-bottom as "who joins whom".
    function buildDendrogram(d) {
        const order = d.order || [];
        const tree = d.tree;
        if (!tree) return '';
        const rowH = 40, padTop = 18, padBot = 10;
        const W = 600, labelW = 150, xLeaf = W - labelW, xRoot = 30;
        const yOf = {};
        order.forEach((id, i) => { yOf[id] = padTop + i * rowH + rowH / 2; });
        const sims = [];
        (function collect(n) { if (n.type === 'node') { sims.push(n.similarity); n.children.forEach(collect); } })(tree);
        const minSim = Math.min(1, ...sims);
        const sx = s => (minSim >= 1) ? xRoot : (xLeaf - (1 - s) / (1 - minSim) * (xLeaf - xRoot));
        const seg = [], forks = [], leaves = [];
        (function place(n) {
            if (n.type === 'leaf') { n._x = xLeaf; n._y = yOf[n.id]; leaves.push(n); return; }
            n.children.forEach(place);
            n._x = sx(n.similarity);
            const cy = n.children.map(c => c._y);
            n._y = (Math.min(...cy) + Math.max(...cy)) / 2;
            seg.push(`<line x1="${n._x}" y1="${Math.min(...cy)}" x2="${n._x}" y2="${Math.max(...cy)}"/>`);
            n.children.forEach(c => seg.push(`<line x1="${n._x}" y1="${c._y}" x2="${c._x}" y2="${c._y}"/>`));
            forks.push(`<g class="wq-dnd-fork"><circle cx="${n._x}" cy="${n._y}" r="13"/>`
                + `<text x="${n._x}" y="${n._y}" dy="0.32em">${toAr(Math.round(n.similarity * 100))}</text></g>`);
        })(tree);
        const H = padTop + order.length * rowH + padBot;
        const leafEls = leaves.map(l => {
            const cnt = (d.counts && d.counts[l.id] != null) ? `<tspan class="wq-dnd-cnt"> · ${toAr(d.counts[l.id])}</tspan>` : '';
            return `<g class="wq-dnd-leaf"><circle cx="${l._x}" cy="${l._y}" r="3.5"/>`
                + `<text x="${xLeaf + 12}" y="${l._y}" dy="0.32em">${l.name}${cnt}</text></g>`;
        }).join('');
        return `<div class="wq-dnd-wrap"><svg viewBox="0 0 ${W} ${H}" class="wq-dnd" role="img" aria-label="شجرة تقارب المصاحف">`
            + `<g class="wq-dnd-links">${seg.join('')}</g>${forks.join('')}${leafEls}</svg></div>`;
    }

    let mushafSimView = 'overview';
    let mushafCompare = { a: null, b: null };
    const MSP_TABS = [
        ['overview', 'نظرة عامة', 'fa-sitemap'],
        ['marks', 'التوافق لكل علامة', 'fa-list-check'],
        ['profiles', 'ما يميّز كل مصحف', 'fa-id-card'],
        ['compare', 'قارن مصحفين', 'fa-code-compare'],
    ];
    function renderMushafSim() {
        const d = mushafSimCache;
        const bar = '<div class="wq-msp-subtabs">' + MSP_TABS.map(([k, l, ic]) =>
            `<button class="wq-msp-subtab${mushafSimView === k ? ' wq-msp-subtab-on' : ''}" data-view="${k}"><i class="fas ${ic}"></i> ${l}</button>`).join('') + '</div>';
        const body = mushafSimView === 'marks' ? mspViewMarks(d)
            : mushafSimView === 'profiles' ? mspViewProfiles(d)
            : mushafSimView === 'compare' ? mspViewCompare(d)
            : mspViewOverview(d);
        els.mushafSimContent.innerHTML = bar + body;
        if (mushafSimView === 'compare') mspWireCompare(d);
    }

    /* نظرة عامة — dendrogram + closest pairs */
    function mspViewOverview(d) {
        const pairs = (d.pairs || []).slice(0, 12);
        const rows = pairs.map(p => {
            const mp = Math.round(p.meaning * 100), pl = Math.round(p.place * 100);
            return `<div class="wq-msp-row"><div class="wq-msp-names"><b>${p.a}</b> <span class="wq-msp-x">↔</span> <b>${p.b}</b></div>`
                + `<div class="wq-msp-bars"><div class="wq-msp-bar" title="نفس الموضع ونفس الحكم"><span style="width:${mp}%"></span></div>`
                + `<div class="wq-msp-val">${toAr(mp)}٪ <small>حكمًا</small></div>`
                + `<div class="wq-msp-place" title="يضعان وقفًا في نفس الموضع بغضّ النظر عن الحكم">${toAr(pl)}٪ موضعًا</div></div></div>`;
        }).join('');
        return toolBlurb('أقرب المصاحف في نظام الوقف — الشجرة على الشاشات الواسعة.')
            + '<div class="wq-msp-head">أقرب المصاحف بعضها لبعض</div>'
            + `<div class="wq-msp-list">${rows}</div>`
            + buildDendrogram(d);
    }

    /* التوافق لكل علامة — per-mark agreement + per-mushaf counts */
    function mspViewMarks(d) {
        const std = d.standard || [];
        const desc = '<div class="wq-solos-desc">لكل علامة وقف: كم موضعًا يَسِمه كل مصحف قياسي بها، ونسبة اتفاق المصاحف عند المواضع التي تحملها. '
            + '<b>الأزهر</b> يوحّد قلى وصلى في «ج»، فأعمدته في «ق» و«ص» صفر. (ورش والهندي نظامان مختلفان — انظر «ما يميّز كل مصحف».)</div>';
        const rows = (d.mark_consensus || []).map(m => {
            const ag = Math.round(m.agreement * 100);
            const meta = WAQF_SYM[m.sym] || { name: m.sym };
            const chips = std.map(v => {
                const n = m.counts[v] || 0;
                return `<span class="wq-mk-chip${n ? '' : ' wq-mk-zero'}"><b>${toAr(n)}</b><span>${v}</span></span>`;
            }).join('');
            return `<div class="wq-mk-row"><div class="wq-mk-head">`
                + `<span class="wq-wsym waqf-uthmanic wq-w-${meta.cls || 'ok'}">${m.glyph}</span>`
                + `<div class="wq-mk-meta"><div class="wq-mk-name">${meta.name} <small>(${m.sym})</small></div>`
                + `<div class="wq-mk-desc">${m.desc}</div></div>`
                + `<div class="wq-mk-agree"><div class="wq-mk-bar"><span style="width:${ag}%"></span></div>`
                + `<span class="wq-mk-agtxt">${toAr(ag)}٪ اتفاق · ${toAr(m.positions)} موضعًا</span></div></div>`
                + `<div class="wq-mk-chips">${chips}</div></div>`;
        }).join('');
        return desc + `<div class="wq-mk-list">${rows}</div>`;
    }

    /* ما يميّز كل مصحف — per-mushaf signature cards */
    function mspViewProfiles(d) {
        const sysLabel = { standard: 'نظام حفص القياسي', warsh: 'رواية ورش', indopak: 'النظام الباكستاني (IndoPak)' };
        const cards = (d.order || d.mushafs || []).map(id => {
            const p = (d.profiles || []).find(x => x.id === id);
            if (!p) return '';
            const sp = (p.special || []).map(s => `<li>${s}</li>`).join('')
                || '<li class="wq-pf-none">يتبع النظام القياسي دون تفرّدٍ بارز.</li>';
            const dist = (d.marks || []).filter(m => p.counts[m]).map(m =>
                `<span class="wq-mk-chip"><b>${toAr(p.counts[m])}</b>${markGlyph(m, id)}</span>`).join('');
            return `<div class="wq-pf-card wq-pf-${p.system}"><div class="wq-pf-top">`
                + `<span class="wq-pf-name"><i class="fas fa-book-quran"></i> ${id}</span>`
                + `<span class="wq-pf-sys">${sysLabel[p.system] || ''}</span></div>`
                + `<div class="wq-pf-stat">${toAr(p.total)} موضع وقف</div>`
                + `<ul class="wq-pf-special">${sp}</ul>`
                + (dist ? `<div class="wq-mk-chips wq-pf-dist">${dist}</div>` : '')
                + `</div>`;
        }).join('');
        return '<div class="wq-solos-desc">ما الذي يميّز كل مصحف؟ سطورٌ مستخلصة آليًّا من مقارنة علاماته ببقيّة المصاحف.</div>'
            + `<div class="wq-pf-grid">${cards}</div>`;
    }

    /* قارن مصحفين — pick two → every differing word */
    function mspViewCompare(d) {
        const ms = d.mushafs || [];
        const a = mushafCompare.a || ms[0], b = mushafCompare.b || ms[1];
        const opts = sel => ms.map(m => `<option value="${m}"${m === sel ? ' selected' : ''}>${m}</option>`).join('');
        return '<div class="wq-solos-desc">اختر مصحفين لعرض كل كلمة اختلفا في حكم الوقف عليها (اضغط أي كلمة لفتح آيتها).</div>'
            + `<div class="wq-cmp-pick"><select id="wq-cmp-a">${opts(a)}</select>`
            + `<span class="wq-cmp-vs">مقابل</span><select id="wq-cmp-b">${opts(b)}</select>`
            + `<button id="wq-cmp-go" class="wq-cmp-go" type="button"><i class="fas fa-code-compare"></i> قارن</button></div>`
            + '<div id="wq-cmp-result"></div>';
    }
    function mspWireCompare() {
        const go = document.getElementById('wq-cmp-go');
        if (go) go.onclick = mspRunCompare;
        if (mushafCompare.a && mushafCompare.b && mushafCompare.a !== mushafCompare.b) mspRunCompare();
    }
    async function mspRunCompare() {
        const a = document.getElementById('wq-cmp-a').value, b = document.getElementById('wq-cmp-b').value;
        const res = document.getElementById('wq-cmp-result');
        if (a === b) { res.innerHTML = '<div class="wq-research-empty">اختر مصحفين مختلفين.</div>'; return; }
        mushafCompare = { a, b };
        showState(res, 'loading', 'جارٍ المقارنة…');
        try {
            const j = await window.AtharApi.json('/api/waqf-research/mushaf-diff?a=' + encodeURIComponent(a) + '&b=' + encodeURIComponent(b));
            mspRenderDiff(j);
        } catch { showState(res, 'error', 'تعذّر التحميل'); }
    }
    function mspRenderDiff(j) {
        const res = document.getElementById('wq-cmp-result');
        if (!res) return;
        const agree = Math.round((j.meaning || 0) * 100);
        const ga = s => markGlyph(s, j.a, 'wq-cmp-ga'), gb = s => markGlyph(s, j.b, 'wq-cmp-gb');
        const groups = (j.groups || []).map(g =>
            `<span class="wq-cmp-group">${ga(g.a_sym)}<i class="fas fa-arrows-left-right"></i>`
            + `${gb(g.b_sym)}<span class="wq-cmp-gn">${toAr(g.count)}</span></span>`).join('');
        const verses = j.verses || [];
        labListState.cmp = HIT_PAGE;
        const renderItem = v => hitRowFromOcc({
            surah: v.surah, ayah: v.ayah,
            context: v.word || '',
            marks: {},
        }, {
            editorEditions: [j.a, j.b],
            marksHtml: `${ga(v.a_sym)}<span class="wq-hit-chip wq-hit-chip-muted">↔</span>${gb(v.b_sym)}`,
            extraClass: 'wq-cmp-case',
        });
        res.innerHTML = `<div class="wq-cmp-summary"><b>${j.a}</b> و<b>${j.b}</b> يتفقان حكمًا بنسبة <b>${toAr(agree)}٪</b>، `
            + `ويختلفان في <b>${toAr(j.differences)}</b> موضعًا${j.capped ? ` (عُرض أول ${toAr(j.shown)})` : ''}.</div>`
            + `<div class="wq-cmp-legend"><span class="wq-cmp-ga">${j.a}</span> · <span class="wq-cmp-gb">${j.b}</span></div>`
            + `<div class="wq-cmp-groups">${groups}</div>`
            + (verses.length ? paginateList('cmp', verses, renderItem) : '<div class="wq-research-empty">لا اختلاف بينهما في الحكم.</div>');
        wireHitMore(res, 'cmp', verses, renderItem);
    }

    function setupResearch() {
        if (!els.panelWord) return;
        if (els.researchToggle && els.researchBody) {
            els.researchToggle.addEventListener('click', () => {
                window.AtharUi.setDisclosure(els.researchToggle, els.researchBody);
            });
        }

        const TAB_FAMILY = {
            word: 'words', ibtidaa: 'words', saktat: 'words', mandatory: 'words',
            solos: 'reciters', stats: 'reciters', cluster: 'reciters',
            patterns: 'mushafs', agreement: 'mushafs', mushafsim: 'mushafs',
        };

        function tabLabel(tab) {
            return (tab.textContent || '').replace(/\s+/g, ' ').trim();
        }

        function setFamily(family, { selectFirst = true } = {}) {
            document.querySelectorAll('.wq-lab-family').forEach(btn => {
                const on = btn.dataset.family === family;
                btn.classList.toggle('wq-lab-family-active', on);
                btn.setAttribute('aria-selected', String(on));
            });
            const tabs = [...document.querySelectorAll('.wq-lab-tab')];
            tabs.forEach(tab => {
                const match = (tab.dataset.family || TAB_FAMILY[tab.dataset.tab]) === family;
                tab.hidden = !match;
            });
            if (selectFirst) {
                const first = tabs.find(tab => !tab.hidden);
                if (first) selectLabTab(first, { scroll: false });
            }
            if (els.labSheetList) rebuildLabSheetList();
        }

        function selectLabTab(tab, { scroll = true, closeSheet = false } = {}) {
            if (!tab) return;
            const family = tab.dataset.family || TAB_FAMILY[tab.dataset.tab];
            if (family) {
                document.querySelectorAll('.wq-lab-family').forEach(btn => {
                    const on = btn.dataset.family === family;
                    btn.classList.toggle('wq-lab-family-active', on);
                    btn.setAttribute('aria-selected', String(on));
                });
                document.querySelectorAll('.wq-lab-tab').forEach(t => {
                    const match = (t.dataset.family || TAB_FAMILY[t.dataset.tab]) === family;
                    t.hidden = !match;
                });
            }
            document.querySelectorAll('.wq-lab-tab').forEach(t => {
                const active = t === tab;
                t.classList.toggle('wq-lab-tab-active', active);
                t.setAttribute('aria-selected', String(active));
                t.tabIndex = active ? 0 : -1;
            });
            if (els.labPickerLabel) els.labPickerLabel.textContent = tabLabel(tab);
            if (els.labSheetList) {
                els.labSheetList.querySelectorAll('.wq-lab-sheet-item').forEach(item => {
                    const on = item.dataset.tab === tab.dataset.tab;
                    item.classList.toggle('is-active', on);
                    item.setAttribute('aria-selected', String(on));
                });
            }
            const which = tab.dataset.tab;
            els.panelWord.hidden = which !== 'word';
            els.panelSolos.hidden = which !== 'solos';
            els.panelStats.hidden = which !== 'stats';
            els.panelMandatory.hidden = which !== 'mandatory';
            els.panelSaktat.hidden = which !== 'saktat';
            els.panelPatterns.hidden = which !== 'patterns';
            els.panelAgreement.hidden = which !== 'agreement';
            els.panelIbtidaa.hidden = which !== 'ibtidaa';
            els.panelCluster.hidden = which !== 'cluster';
            els.panelMushafSim.hidden = which !== 'mushafsim';
            if (which === 'solos') loadSolosSummary();
            if (which === 'stats') loadStats();
            if (which === 'mandatory') loadMandatory();
            if (which === 'saktat') loadSaktat();
            if (which === 'patterns') loadPatterns();
            if (which === 'agreement') loadAgreement();
            if (which === 'ibtidaa') loadIbtidaa();
            if (which === 'cluster') loadCluster();
            if (which === 'mushafsim') loadMushafSim();
            if (scroll) {
                window.AtharUi.scrollIntoView(tab, { behavior: 'smooth', block: 'nearest', inline: 'nearest' });
            }
            if (closeSheet) setLabSheetOpen(false);
            const url = new URL(location.href);
            url.searchParams.set('tab', which);
            if (family) url.searchParams.set('family', family);
            history.replaceState(null, '', url);
        }

        function setLabSheetOpen(open) {
            if (!els.labSheetRoot || !els.labPicker) return;
            els.labSheetRoot.hidden = !open;
            els.labPicker.setAttribute('aria-expanded', String(open));
            document.body.classList.toggle('wq-lab-sheet-open', open);
            if (open) {
                const active = els.labSheetList?.querySelector('.wq-lab-sheet-item.is-active')
                    || els.labSheetList?.querySelector('.wq-lab-sheet-item');
                active?.focus();
            } else {
                els.labPicker.focus();
            }
        }

        function rebuildLabSheetList() {
            if (!els.labSheetList) return;
            els.labSheetList.innerHTML = '';
            document.querySelectorAll('.wq-lab-tab').forEach(tab => {
                if (tab.hidden) return;
                const btn = document.createElement('button');
                btn.type = 'button';
                btn.className = 'wq-lab-sheet-item' + (tab.classList.contains('wq-lab-tab-active') ? ' is-active' : '');
                btn.dataset.tab = tab.dataset.tab;
                btn.setAttribute('role', 'option');
                btn.setAttribute('aria-selected', tab.getAttribute('aria-selected') || 'false');
                btn.innerHTML = `<span>${tabLabel(tab)}</span>`;
                btn.addEventListener('click', () => {
                    selectLabTab(tab, { scroll: false, closeSheet: true });
                });
                els.labSheetList.appendChild(btn);
            });
        }

        if (els.labSheetList) rebuildLabSheetList();

        document.querySelectorAll('.wq-lab-family').forEach(btn => {
            btn.addEventListener('click', () => setFamily(btn.dataset.family));
        });

        if (els.labPicker) {
            els.labPicker.addEventListener('click', () => {
                setLabSheetOpen(els.labSheetRoot?.hidden !== false);
            });
        }
        els.labSheetBackdrop?.addEventListener('click', () => setLabSheetOpen(false));
        els.labSheetClose?.addEventListener('click', () => setLabSheetOpen(false));
        document.addEventListener('keydown', e => {
            if (e.key === 'Escape' && els.labSheetRoot && !els.labSheetRoot.hidden) {
                e.preventDefault();
                setLabSheetOpen(false);
            }
        });

        document.querySelectorAll('.wq-lab-tab').forEach(tab => tab.addEventListener('click', () => {
            selectLabTab(tab);
        }));
        els.researchBody.addEventListener('keydown', e => {
            if (!['ArrowRight', 'ArrowLeft', 'Home', 'End'].includes(e.key)) return;
            const tabs = [...document.querySelectorAll('.wq-lab-tab')].filter(t => !t.hidden);
            const current = tabs.indexOf(document.activeElement);
            if (current < 0) return;
            e.preventDefault();
            let next = current;
            if (e.key === 'Home') next = 0;
            else if (e.key === 'End') next = tabs.length - 1;
            else next = (current + (e.key === 'ArrowLeft' ? 1 : -1) + tabs.length) % tabs.length;
            tabs[next].focus();
            selectLabTab(tabs[next]);
        });
        document.querySelectorAll('.wq-research-chip').forEach(c =>
            c.addEventListener('click', () => runResearch(c.dataset.word, c.dataset.exact === '1', c.dataset.mode || '')));
        if (els.researchInput) els.researchInput.addEventListener('keydown', e => {
            if (e.key === 'Enter') runResearch(els.researchInput.value);
        });
        if (els.researchForms) els.researchForms.addEventListener('click', e => {
            const fb = e.target.closest('.wq-form-chip');
            if (fb) { researchState.form = fb.dataset.form || null; researchState.waqf = null; renderResearch(); return; }
            const wb = e.target.closest('.wq-wfilter');
            if (wb) { researchState.waqf = wb.dataset.waqf || null; renderResearch(); }
        });
        if (els.researchResults) els.researchResults.addEventListener('click', async e => {
            const b = e.target.closest('.wq-research-item, .wq-hit'); if (!b) return;
            const s = +b.dataset.s, a = +b.dataset.a;
            await navigateTo(s, a, optsFromHitEl(b));
            if (els.verseCard) els.verseCard.scrollIntoView({ behavior: 'smooth', block: 'start' });
        });
        if (els.patternsContent) els.patternsContent.addEventListener('click', async e => {
            const item = e.target.closest('.wq-research-item, .wq-hit'); if (!item) return;
            const s = +item.dataset.s, a = +item.dataset.a;
            await navigateTo(s, a, optsFromHitEl(item));
            if (els.verseCard) els.verseCard.scrollIntoView({ behavior: 'smooth', block: 'start' });
        });
        if (els.mushafSimContent) els.mushafSimContent.addEventListener('click', async e => {
            const sub = e.target.closest('.wq-msp-subtab');
            if (sub) { mushafSimView = sub.dataset.view; renderMushafSim(); return; }
            const item = e.target.closest('.wq-research-item, .wq-hit'); if (!item || !item.dataset.s) return;
            const s = +item.dataset.s, a = +item.dataset.a;
            await navigateTo(s, a, optsFromHitEl(item));
            if (els.verseCard) els.verseCard.scrollIntoView({ behavior: 'smooth', block: 'start' });
        });
        if (els.ibtidaaContent) els.ibtidaaContent.addEventListener('click', async e => {
            const sub = e.target.closest('.wq-stats-subtab');
            if (sub) { ibtidaaOnlyMulti = sub.dataset.im === 'multi'; renderIbtidaa(); return; }
            const item = e.target.closest('.wq-research-item, .wq-hit'); if (!item) return;
            const s = +item.dataset.s, a = +item.dataset.a;
            await navigateTo(s, a, optsFromHitEl(item));
            if (els.verseCard) els.verseCard.scrollIntoView({ behavior: 'smooth', block: 'start' });
        });
        if (els.saktatContent) els.saktatContent.addEventListener('click', async e => {
            const item = e.target.closest('.wq-research-item, .wq-hit'); if (!item) return;
            const s = +item.dataset.s, a = +item.dataset.a;
            await navigateTo(s, a, optsFromHitEl(item));
            if (els.verseCard) els.verseCard.scrollIntoView({ behavior: 'smooth', block: 'start' });
        });
        if (els.agreementContent) els.agreementContent.addEventListener('click', async e => {
            const tab = e.target.closest('.wq-stats-subtab[data-mushaf]');
            if (tab) { agreementMushaf = tab.dataset.mushaf; renderAgreement(); return; }
            const cell = e.target.closest('.wq-agree-cell[data-rid], .wq-agree-card-mark[data-rid]');
            if (cell) { showAgreementCases(cell.dataset.rid, cell.dataset.mark); return; }
            const hit = e.target.closest('.wq-hit, .wq-agree-case');
            if (hit && hit.dataset.s) {
                const s = +hit.dataset.s, a = +hit.dataset.a;
                await navigateTo(s, a, optsFromHitEl(hit));
                if (els.verseCard) els.verseCard.scrollIntoView({ behavior: 'smooth', block: 'start' });
            }
        });
        if (els.statsContent) els.statsContent.addEventListener('click', async e => {
            const st = e.target.closest('.wq-stats-subtab');
            if (st) {
                const sv = st.dataset.sv;
                if (sv === 'consensus') { statsView = 'consensus'; loadConsensus(); }
                else { statsView = sv; renderStats(); }
                return;
            }
            const item = e.target.closest('.wq-research-item, .wq-hit');
            if (item) {
                const s = +item.dataset.s, a = +item.dataset.a;
                await navigateTo(s, a, optsFromHitEl(item));
                if (els.verseCard) els.verseCard.scrollIntoView({ behavior: 'smooth', block: 'start' });
            }
        });
        if (els.mandatoryContent) els.mandatoryContent.addEventListener('click', async e => {
            const mt = e.target.closest('.wq-stats-subtab');
            if (mt) { mandView = mt.dataset.mv; renderMandatory(); return; }
            const item = e.target.closest('.wq-research-item, .wq-hit');
            if (item) {
                const s = +item.dataset.s, a = +item.dataset.a;
                await navigateTo(s, a, optsFromHitEl(item));
                if (els.verseCard) els.verseCard.scrollIntoView({ behavior: 'smooth', block: 'start' });
            }
        });
        if (els.solosContent) els.solosContent.addEventListener('click', async e => {
            const back = e.target.closest('.wq-solos-back');
            if (back) { renderSolosSummary(); return; }
            const card = e.target.closest('.wq-solos-card, .wq-solos-rank-row');
            if (card) { loadSolosDetail(card.dataset.rid); return; }
            const item = e.target.closest('.wq-research-item, .wq-hit');
            if (item) {
                const s = +item.dataset.s, a = +item.dataset.a;
                await navigateTo(s, a, optsFromHitEl(item));
                if (els.verseCard) els.verseCard.scrollIntoView({ behavior: 'smooth', block: 'start' });
            }
        });
    }

    /* ── render ───────────────────────────────────────────────── */
    /* ── segment audio (seek-and-stop in a reciter's surah mp3 OR YouTube) ──
       MP3 reciters play through a native <audio>; YouTube-sourced reciters
       (e.g. محمد برهجي) play through the YouTube IFrame API via a small adapter
       that mimics the <audio> interface — same approach as the memorize page, so
       برهجي works here too. A single poll loop enforces the segment end for
       whichever backend is active (YT doesn't fire timeupdate). */
    const audio = new Audio();
    audio.preload = 'none';
    let ytPlayer = null;          // lazily-created YouTube adapter (one, reused)
    let activeBackend = null;     // backend currently playing
    let audioStopAt = null, playingBtn = null, pollTimer = null;

    function isYouTubeUrl(url) { return /youtube\.com|youtu\.be/.test(url || ''); }
    function extractYoutubeId(url) {
        const m = (url || '').match(/[?&]v=([A-Za-z0-9_-]{11})/) || (url || '').match(/youtu\.be\/([A-Za-z0-9_-]{11})/);
        return m ? m[1] : null;
    }

    // Minimal YouTube IFrame adapter exposing the <audio> bits we use.
    class YTAudioAdapter {
        constructor(videoId) {
            this._videoId = videoId; this._ready = false; this._listeners = {};
            this._div = document.createElement('div');
            this._div.style.cssText = 'position:fixed;left:-9999px;top:-9999px;width:320px;height:180px;pointer-events:none;z-index:-1;';
            document.body.appendChild(this._div);
            if (window.YT && window.YT.Player) this._create();
            else {
                if (!document.getElementById('yt-iframe-api')) {
                    const s = document.createElement('script'); s.id = 'yt-iframe-api';
                    s.src = 'https://www.youtube.com/iframe_api'; document.head.appendChild(s);
                }
                const prev = window.onYouTubeIframeAPIReady;
                window.onYouTubeIframeAPIReady = () => { if (typeof prev === 'function') prev(); this._create(); };
            }
        }
        _create() {
            this._player = new YT.Player(this._div, {
                width: 320, height: 180, videoId: this._videoId,
                playerVars: { autoplay: 0, controls: 0, disablekb: 1, fs: 0, rel: 0, playsinline: 1 },
                events: {
                    onReady: () => { this._ready = true; this._dispatch('loadedmetadata'); },
                    onStateChange: e => { if (e.data === YT.PlayerState.ENDED) this._dispatch('ended'); },
                },
            });
        }
        _dispatch(ev) { (this._listeners[ev] || []).forEach(cb => { try { cb({ type: ev }); } catch (e) {} }); }
        addEventListener(ev, cb, opts) {
            (this._listeners[ev] = this._listeners[ev] || []).push(cb);
            if (opts && opts.once) { const w = e => { cb(e); this._listeners[ev] = this._listeners[ev].filter(f => f !== w); }; this._listeners[ev].pop(); this._listeners[ev].push(w); if (ev === 'loadedmetadata' && this._ready) setTimeout(() => this._dispatch('loadedmetadata'), 0); }
        }
        set src(url) { const v = extractYoutubeId(url); if (!v || v === this._videoId) return; this._videoId = v; this._ready = false; if (this._player && this._player.loadVideoById) this._player.loadVideoById({ videoId: v, startSeconds: 0 }); }
        get readyState() { return this._ready ? 4 : 0; }
        get currentTime() { try { return (this._ready && this._player.getCurrentTime()) || 0; } catch (e) { return 0; } }
        set currentTime(t) { try { if (this._ready) this._player.seekTo(t, true); } catch (e) {} }
        get paused() { try { return !this._ready || this._player.getPlayerState() !== YT.PlayerState.PLAYING; } catch (e) { return true; } }
        play() { return new Promise(res => { const go = () => { try { this._player.playVideo(); } catch (e) {} res(); }; if (this._ready) go(); else this.addEventListener('loadedmetadata', go, { once: true }); }); }
        pause() { try { if (this._ready) this._player.pauseVideo(); } catch (e) {} }
    }

    function backendFor(url) {
        if (isYouTubeUrl(url)) {
            if (!ytPlayer) ytPlayer = new YTAudioAdapter(extractYoutubeId(url));
            else ytPlayer.src = url;
            return ytPlayer;
        }
        return audio;
    }
    function stopPoll() { if (pollTimer) { clearInterval(pollTimer); pollTimer = null; } }

    function clearPlaying() {
        if (playingBtn) { const i = playingBtn.querySelector('i'); if (i) i.className = playingBtn.dataset.icon || 'fas fa-play'; playingBtn.classList.remove('wq-playing'); }
        playingBtn = null; stopPoll();
        document.querySelectorAll('.wq-guide-seg.wq-guide-active').forEach(el => el.classList.remove('wq-guide-active'));
    }
    // Play a guide-segment card (bounded) and highlight the card while it plays.
    function playGuideSeg(card, btn, url, absStart, absEnd) {
        const wasPlaying = playingBtn === btn && activeBackend && !activeBackend.paused;
        playSegment(url, absStart, absEnd, btn);
        if (!wasPlaying && card) card.classList.add('wq-guide-active');
    }
    audio.addEventListener('ended', () => { audioStopAt = null; clearPlaying(); });

    function playSegment(url, absStart, absEnd, btn) {
        if (!url || absEnd <= absStart) return;
        const backend = backendFor(url);
        if (playingBtn === btn && activeBackend && !activeBackend.paused) { activeBackend.pause(); audioStopAt = null; clearPlaying(); return; }
        clearPlaying();
        if (activeBackend && activeBackend !== backend) activeBackend.pause();
        activeBackend = backend;
        playingBtn = btn;
        if (btn) { btn.classList.add('wq-playing'); const i = btn.querySelector('i'); if (i) { btn.dataset.icon = i.className; i.className = 'fas fa-pause'; } }
        const begin = () => {
            try { backend.currentTime = absStart; } catch (e) {}
            audioStopAt = absEnd;
            const p = backend.play(); if (p && p.catch) p.catch(() => {});
            stopPoll();
            pollTimer = setInterval(() => {
                if (activeBackend && audioStopAt != null && activeBackend.currentTime >= audioStopAt) {
                    activeBackend.pause(); audioStopAt = null; clearPlaying();
                }
            }, 120);
        };
        if (backend === audio) {
            if (audio.src !== url) { audio.src = url; audio.addEventListener('loadedmetadata', begin, { once: true }); audio.load(); }
            else begin();
        } else {
            backend.src = url;
            if (backend.readyState >= 1) begin();
            else backend.addEventListener('loadedmetadata', begin, { once: true });
        }
    }
    // play a reciter's own segment that ENDS at one of their stop words
    function playReciterStop(d, rid, toWpos, btn) {
        const det = d.per_reciter[rid];
        if (!det || !det.audio_url) return;
        const stops = (det.stops || []).slice().sort((a, b) => a.wpos - b.wpos);
        const idx = stops.findIndex(s => s.wpos === toWpos);
        if (idx < 0) return;
        const startT = idx > 0 ? stops[idx - 1].time : 0;
        playSegment(det.audio_url, det.verse_start + startT, det.verse_start + stops[idx].time, btn);
    }

    function render(d) {
        clearPlaying(); audio.pause(); if (ytPlayer) ytPlayer.pause(); audioStopAt = null;
        renderVerse(d);
        renderRecommendation(d);
        renderMatrix(d);
        renderReciters(d);
    }

    /* ── ترشيح القراءة حسب نَفَسك ───────────────────────────────────
       Instead of synthesising a plan, pick a REAL reciter whose natural breath
       matches the chosen level and show exactly how HE recites the verse — his
       own phrases, his own audio. Breath capacity is measured in WORDS held per
       single breath (the longest phrase), not seconds, so a fast قصر-المنفصل
       reciter isn't mislabeled "short-breathed" merely for reciting the same
       words faster (his shorter clip is pace, not lung). قصير/متوسط/طويل = the
       reciter with the fewest / median / most words in his longest breath. */
    function reciterBreathProfile(d, r) {
        const pr = d.per_reciter[r.id];
        const phs = (pr.phrases || []).filter(p => p.last_wpos >= p.first_wpos);
        if (!phs.length) return null;
        let maxW = 0, maxWsec = 0;
        phs.forEach(p => {
            const w = p.last_wpos - p.first_wpos + 1, s = p.end - p.start;
            if (w > maxW || (w === maxW && s > maxWsec)) { maxW = w; maxWsec = s; }
        });
        return { id: r.id, name: pr.name_ar || r.name_ar, pr, phrases: phs,
                 maxW, maxWsec, nseg: phs.length, qasr: !!pr.qasr_munfasil };
    }

    function renderRecommendation(d) {
        const profiles = (d.reciters || []).map(r => reciterBreathProfile(d, r)).filter(Boolean);
        els.recCard.hidden = !profiles.length || !d.words.length;
        if (els.recCard.hidden) return;

        // Rank by breath capacity: words per breath (pace-fair), ties → seconds.
        profiles.sort((a, b) => a.maxW - b.maxW || a.maxWsec - b.maxWsec);
        const L = state.breathL;
        const pick = L <= BREATH.short ? profiles[0]
            : L >= BREATH.long ? profiles[profiles.length - 1]
                : profiles[Math.floor((profiles.length - 1) / 2)];
        const label = L <= BREATH.short ? 'قصير' : L >= BREATH.long ? 'طويل' : 'متوسط';
        const wWord = n => n <= 2 ? 'كلمتان' : n <= 10 ? 'كلمات' : 'كلمة';

        let summary = `نَفَس <b>${label}</b> — هكذا يقرؤها <b>${pick.name}</b>`
            + `<span class="wq-rec-cap"> أطول نفَس ${toAr(pick.maxW)} ${wWord(pick.maxW)} (~${toAr(pick.maxWsec.toFixed(1))}ث) · ${toAr(pick.nseg)} مقاطع</span>`;
        if (pick.qasr) summary += ` <span class="wq-qasr-note" title="يقرأ بقصر المدّ المنفصل (حركتان)، فأداؤه أسرع ويسع كلماتٍ أكثر في النفَس الواحد">قصر المنفصل</span>`;
        summary += `<br><span class="wq-ref-note"><i class="fas fa-circle-info"></i> اختر سعة نفَسك أعلاه؛ نعرض قارئًا نفَسه قصير/متوسط/طويل فعلاً — لا تقسيمًا مصطنعًا — وزر <i class="fas fa-play"></i> يشغّل من صوته.</span>`;
        els.recSummary.innerHTML = summary;

        // Render the picked reciter's ACTUAL segments using the very same builder
        // as the per-reciter cards (buildSegmentRow → getPhrases + highWater), so
        // back-ups (إعادة) are reconstructed identically and never double-counted.
        const lastW = d.words.length - 1;
        const markByWpos = new Map();
        ['المدينة الجديد', 'المدينة القديم', 'الشمرلي', 'الأزهر', 'قطر', 'الكويت', 'البحرين'].forEach(id => {
            const m = (d.mushafs || []).find(x => x.id === id);
            if (m) m.marks.forEach(mk => { if (!markByWpos.has(mk.wpos)) markByWpos.set(mk.wpos, mk.symbol); });
        });
        const soloSet = new Set((d.union_stops || []).filter(u => u.solo).map(u => u.wpos));

        els.recPlan.innerHTML = '';
        els.recPlan.appendChild(buildSegmentRow(d, pick.pr, pick.name, lastW, markByWpos, soloSet));
    }


    function stopChip(u, total) {
        const chip = document.createElement('span');
        chip.className = 'wq-chip' + (u.solo ? ' wq-chip-solo' : '');
        chip.style.setProperty('--s', (u.count / total).toFixed(2));
        const names = u.reciters.map(reciterName).join('، ');
        const dur = `~${toAr(u.avg_duration.toFixed(1))}ث`;
        if (u.solo) {
            chip.innerHTML = `<i class="fas fa-pause"></i><b>انفرد</b><span>${reciterName(u.reciters[0])}</span><span class="wq-chip-dur">${dur}</span>`;
            chip.title = `انفرد به: ${names}`;
        } else {
            chip.innerHTML = `<i class="fas fa-pause"></i><b>${toAr(u.count)}/${toAr(total)}</b><span class="wq-chip-dur">${dur}</span>`;
            chip.title = `يقف عنده: ${names} — ${dur} من بداية الآية`;
        }
        return chip;
    }

    function renderVerse(d) {
        els.verseCard.hidden = false;
        els.verseTitle.textContent = `${surahName(d.surah) ? 'سورة ' + surahName(d.surah) + ' · ' : ''}آية ${toAr(d.ayah)}`;
        if (els.barVerse) {
            els.barVerse.innerHTML = surahName(d.surah) ? `${surahName(d.surah)} · آية <b>${toAr(d.ayah)}</b>` : '';
        }
        const nStops = d.union_stops.length;
        els.verseMeta.textContent =
            `${toAr(d.reciters_total)} قرّاء · ${toAr(nStops)} ${nStops === 1 ? 'موضع وقف' : 'مواضع وقف'}`
            + (d.full_duration ? ` · ~${toAr(d.full_duration.toFixed(0))}ث` : '');

        // Best stops: merge forward + repeat counts, rank by strength, show top stops.
        const breathAll = new Map();
        (d.union_stops || []).forEach(u => breathAll.set(u.wpos, u.count));
        (d.reciters || []).forEach(r => {
            (d.per_reciter[r.id].repeats || []).forEach(rp => {
                breathAll.set(rp.from_wpos, (breathAll.get(rp.from_wpos) || 0) + 1);
            });
        });
        const mushafAt = new Set();
        (d.mushafs || []).forEach(m => m.marks.forEach(mk => mushafAt.add(mk.wpos)));
        const lastW = d.words.length - 1;
        const ranked = [...breathAll.entries()]
            .filter(([w]) => w < lastW)
            .map(([w, c]) => ({ wpos: w, count: c, mushaf: mushafAt.has(w) }))
            .sort((a, b) => b.count - a.count || (b.mushaf ? 1 : 0) - (a.mushaf ? 1 : 0));
        const majorityN = Math.floor((d.reciters_total || 1) / 2) + 1;
        const best = ranked.filter(s => s.count >= majorityN || s.mushaf).slice(0, 6);
        if (best.length && d.words.length > 5) {
            els.bestStops.hidden = false;
            els.bestStops.innerHTML = '<span class="wq-best-label"><i class="fas fa-star"></i> أفضل مواضع الوقف</span> '
                + best.map(s => {
                    const word = d.words[s.wpos] || '';
                    const pct = Math.round(s.count / d.reciters_total * 100);
                    return `<span class="wq-best-chip${s.mushaf ? ' wq-best-mushaf' : ''}" title="${toAr(s.count)}/${toAr(d.reciters_total)} قرّاء${s.mushaf ? ' + علامة مطبوعة' : ''}">`
                        + `<span class="wq-best-word">${word}</span>`
                        + `<span class="wq-best-pct">${toAr(pct)}٪</span></span>`;
                }).join('');
        } else {
            els.bestStops.hidden = true;
            els.bestStops.innerHTML = '';
        }

        const flow = els.verseFlow;
        const uByWpos = new Map(d.union_stops.map(u => [u.wpos, u]));
        window.AtharMushaf.renderWordRun(flow, d.words, {
            separator: '',
            classForWord: ({ index }) => uByWpos.has(index) ? 'wq-word wq-word-stop' : 'wq-word',
            afterWord: (element, { index }) => {
                const stop = uByWpos.get(index);
                return stop ? stopChip(stop, d.reciters_total) : null;
            },
        });
        applyVerseHighlight(d);
    }

    function renderMatrix(d) {
        const mushafs = d.mushafs || [];
        // columns = union of reciter stops AND printed-mushaf waqf marks
        const posSet = new Set(d.union_stops.map(u => u.wpos));
        mushafs.forEach(m => m.marks.forEach(mk => posSet.add(mk.wpos)));
        const cols = [...posSet].sort((a, b) => a - b);
        els.matrixCard.hidden = cols.length === 0;
        if (!cols.length) { els.matrix.innerHTML = ''; if (els.matrixMobile) { els.matrixMobile.innerHTML = ''; els.matrixMobile.hidden = true; } renderMatrixLegend(d, []); return; }

        const uByWpos = new Map(d.union_stops.map(u => [u.wpos, u]));
        const markOf = (m, wpos) => { const f = m.marks.find(x => x.wpos === wpos); return f ? f.symbol : null; };
        const reciterStops = wpos => d.reciters.some(r => (d.per_reciter[r.id].stops || []).some(s => s.wpos === wpos));
        // a position carrying a printed waqf mark in ANY shown mushaf
        const mushafMarked = wpos => mushafs.some(m => markOf(m, wpos));
        // أقوى وقف: every reciter stops here AND every shown mushaf prescribes it
        const isStrong = wpos => {
            const u = uByWpos.get(wpos);
            return !!u && u.count === d.reciters_total && mushafs.length > 0 && mushafs.every(m => markOf(m, wpos));
        };

        // header
        let head = '<thead><tr><th class="wq-rname">الموضع ←</th>';
        cols.forEach(wpos => {
            const u = uByWpos.get(wpos);
            const strong = isStrong(wpos);
            const cls = (strong ? ' wq-col-strong' : '') + (u && u.solo ? ' wq-col-solo' : (!reciterStops(wpos) ? ' wq-col-mushaf-only' : ''));
            head += `<th class="${cls}">`
                + (strong ? '<div class="wq-col-strong-tag" title="أقوى وقف: يقف عنده كل القرّاء ويوافق كل المصاحف المعروضة"><i class="fas fa-star"></i> أقوى وقف</div>' : '')
                + `<div class="wq-col-word">${d.words[wpos] || ''}</div>`
                + `<div class="wq-col-meta">كلمة ${toAr(wpos + 1)}</div></th>`;
        });
        head += '</tr></thead>';

        let body = '<tbody>';
        // printed-mushaf rows (the prescribed stops)
        mushafs.forEach(m => {
            body += `<tr class="wq-row-mushaf"><td class="wq-rname"><span class="wq-mushaf-name" data-m="${m.id}"><i class="fas fa-book-quran"></i> ${m.name}</span></td>`;
            cols.forEach(wpos => {
                const strong = isStrong(wpos) ? ' wq-col-strong' : '';
                const sym = markOf(m, wpos);
                if (sym) {
                    const meta = symMeta(sym);
                    body += `<td class="${strong}"><span class="wq-wsym ${waqfFontCls(m.id)} wq-w-${meta.cls}" title="${meta.name} — ${meta.desc}">${mushafGlyph(sym, m.id)}</span></td>`;
                } else body += `<td class="${strong}"><span class="wq-cell-empty">·</span></td>`;
            });
            body += '</tr>';
        });
        // consensus row
        body += '<tr class="wq-row-consensus"><td class="wq-rname">اتفاق القرّاء</td>';
        cols.forEach(wpos => {
            const u = uByWpos.get(wpos);
            const cls = ((isStrong(wpos) ? 'wq-col-strong ' : '') + (u && u.solo ? 'wq-col-solo' : '')).trim();
            body += `<td class="${cls}">${u ? toAr(u.count) + '/' + toAr(d.reciters_total) : '<span class="wq-cell-empty">·</span>'}</td>`;
        });
        body += '</tr>';
        // one row per reciter
        d.reciters.forEach(r => {
            const det = d.per_reciter[r.id];
            const timeByWpos = new Map((det.stops || []).map(s => [s.wpos, s.time]));
            const qasr = det.qasr_munfasil ? ' <span class="wq-qasr-mini" title="يقرأ بقصر المدّ المنفصل (حركتان) — قراءته أسرع">قصر المنفصل</span>' : '';
            body += `<tr><td class="wq-rname">${r.name_ar}${qasr}</td>`;
            cols.forEach(wpos => {
                const u = uByWpos.get(wpos);
                const strong = isStrong(wpos) ? ' wq-col-strong' : '';
                const isSolo = u && u.solo;
                const onMushaf = isSolo && mushafMarked(wpos);
                const cls = (strong + (isSolo ? ' wq-col-solo' : '')).trim();
                if (timeByWpos.has(wpos)) {
                    body += `<td class="${cls}"><button class="wq-cell-stop wq-cell-play${isSolo ? ' wq-solo' : ''}${onMushaf ? ' wq-solo-onmushaf' : ''}" type="button" data-rid="${r.id}" data-wpos="${wpos}" title="${onMushaf ? 'انفرد بالوقف هنا، لكنه يوافق علامة مطبوعة في أحد المصاحف · ' : ''}استمع لمقطع ${r.name_ar} حتى هذا الموضع"><i class="fas fa-play"></i>${toAr(timeByWpos.get(wpos).toFixed(1))}${onMushaf ? '<i class="fas fa-book-quran wq-cell-onmushaf"></i>' : ''}</button></td>`;
                } else {
                    body += `<td class="${cls}"><span class="wq-cell-empty">·</span></td>`;
                }
            });
            body += '</tr>';
        });
        body += '</tbody>';
        els.matrix.innerHTML = head + body;
        renderMatrixMobile(d, cols, {
            uByWpos, markOf, mushafMarked, isStrong, mushafs,
        });

        const symsHere = [...new Set(mushafs.flatMap(m => m.marks.map(mk => mk.symbol)))];
        const hasStrong = cols.some(isStrong);
        const hasOnMushaf = d.reciters.some(r => (d.per_reciter[r.id].stops || []).some(s => {
            const u = uByWpos.get(s.wpos); return u && u.solo && mushafMarked(s.wpos);
        }));
        renderMatrixLegend(d, symsHere, { strong: hasStrong, onMushaf: hasOnMushaf });
    }

    function renderMatrixMobile(d, cols, ctx) {
        if (!els.matrixMobile) return;
        if (!cols.length) {
            els.matrixMobile.innerHTML = '';
            els.matrixMobile.hidden = true;
            return;
        }
        const { uByWpos, markOf, mushafMarked, isStrong, mushafs } = ctx;
        const cards = cols.map(wpos => {
            const word = d.words[wpos] || '';
            const u = uByWpos.get(wpos);
            const strong = isStrong(wpos);
            const tags = [];
            if (strong) tags.push('<span class="wq-mx-tag wq-mx-tag-strong">أقوى وقف</span>');
            if (u && u.solo) tags.push('<span class="wq-mx-tag wq-mx-tag-solo">انفراد</span>');
            if (u) tags.push(`<span class="wq-mx-tag">${toAr(u.count)}/${toAr(d.reciters_total)} قرّاء</span>`);
            const mushafBits = mushafs.map(m => {
                const sym = markOf(m, wpos);
                if (!sym) return '';
                const meta = symMeta(sym);
                return `<span class="wq-mx-mushaf"><span class="wq-mx-mname">${m.name}</span>`
                    + `<span class="wq-wsym ${waqfFontCls(m.id)} wq-w-${meta.cls}">${mushafGlyph(sym, m.id)}</span></span>`;
            }).filter(Boolean).join('');
            const plays = d.reciters.map(r => {
                const det = d.per_reciter[r.id];
                const stop = (det.stops || []).find(s => s.wpos === wpos);
                if (!stop) return '';
                const isSolo = u && u.solo;
                const onMushaf = isSolo && mushafMarked(wpos);
                return `<button class="wq-cell-stop wq-cell-play${isSolo ? ' wq-solo' : ''}${onMushaf ? ' wq-solo-onmushaf' : ''}" type="button" data-rid="${r.id}" data-wpos="${wpos}" title="استمع لـ ${r.name_ar}">`
                    + `<span class="wq-mx-rname">${r.name_ar}</span>`
                    + `<i class="fas fa-play" aria-hidden="true"></i>${toAr(stop.time.toFixed(1))}</button>`;
            }).filter(Boolean).join('');
            return `<article class="wq-mx-card${strong ? ' wq-mx-card-strong' : ''}${u && u.solo ? ' wq-mx-card-solo' : ''}">
                <div class="wq-mx-top">
                    <span class="wq-mx-word" dir="rtl">${word}</span>
                    <span class="wq-mx-meta">كلمة ${toAr(wpos + 1)}</span>
                </div>
                <div class="wq-mx-tags">${tags.join('')}</div>
                ${mushafBits ? `<div class="wq-mx-marks">${mushafBits}</div>` : ''}
                ${plays ? `<div class="wq-mx-plays">${plays}</div>` : '<p class="wq-mx-empty">لا وقف مسجّل للقرّاء هنا</p>'}
            </article>`;
        }).join('');
        els.matrixMobile.innerHTML = cards;
        els.matrixMobile.hidden = false;
    }

    function renderMatrixLegend(d, syms, flags) {
        if (!els.matrixLegend) return;
        const parts = [];
        if (flags && flags.strong) parts.push('<span><span class="wq-lg-star"><i class="fas fa-star"></i></span> أقوى وقف (كل القرّاء + كل المصاحف)</span>');
        if (flags && flags.onMushaf) parts.push('<span><i class="fas fa-book-quran wq-lg-onmushaf"></i> انفراد يوافق علامة مصحف</span>');
        (d.mushafs || []).forEach(m => parts.push(`<span><span class="wq-lg wq-mushaf-dot" data-m="${m.id}"></span> ${m.name}</span>`));
        syms.sort((a, b) => Object.keys(WAQF_SYM).indexOf(a) - Object.keys(WAQF_SYM).indexOf(b))
            .forEach(s => { const mt = symMeta(s); parts.push(`<span><span class="wq-wsym waqf-uthmanic wq-w-${mt.cls}">${waqfGlyph(s)}</span> ${mt.name}</span>`); });
        els.matrixLegend.innerHTML = parts.join('');
    }

    // Phrase list for a reciter — from the backend, or derived from `stops` as a fallback.
    function getPhrases(det, lastW) {
        if (det.phrases && det.phrases.length) return det.phrases;
        const stops = (det.stops || []).slice().sort((a, b) => a.wpos - b.wpos);
        return stops.map((s, i) => ({ first_wpos: i === 0 ? 0 : stops[i - 1].wpos + 1, last_wpos: s.wpos, start: i === 0 ? 0 : stops[i - 1].time, end: s.time }))
            .concat([{ first_wpos: (stops.length ? stops[stops.length - 1].wpos + 1 : 0), last_wpos: lastW, start: stops.length ? stops[stops.length - 1].time : 0, end: det.duration }]);
    }

    // Build one row of segment-cards (same visual style as the main-page
    // دليل التلاوة) for a single reciter's phrases. Used both for a
    // standalone reciter and for the "active" voice of a group of reciters
    // who all read the verse with the same waqf pattern.
    function buildSegmentRow(d, det, name, lastW, markByWpos, soloSet) {
        const phrases = getPhrases(det, lastW);
        const row = document.createElement('div');
        row.className = 'wq-guide-row';
        row.dir = 'rtl';

        let highWater = 0;   // exclusive index of the furthest word reached
        phrases.forEach((ph, k) => {
            const isLast = k === phrases.length - 1;
            const first = ph.first_wpos, last = ph.last_wpos;
            const repeatedCount = Math.max(0, highWater - first);   // re-read leading words
            const isBackUp = repeatedCount > 0;
            highWater = Math.max(highWater, last + 1);
            // is the pause at this phrase end a clean forward waqf?
            const next = phrases[k + 1];
            const forwardStop = !isLast && next && next.first_wpos > last;

            const seg = document.createElement('div');
            seg.className = 'wq-guide-seg'
                + (isLast ? ' wq-guide-seg-last' : '')
                + (isBackUp ? ' wq-guide-seg-repeat' : '');

            const num = document.createElement('span');
            num.className = 'wq-guide-num';
            num.textContent = toAr(k + 1);
            seg.appendChild(num);

            // back-up (إعادة) or solo-waqf badge
            if (isBackUp) {
                const bdg = document.createElement('span');
                bdg.className = 'wq-guide-badge wq-guide-badge-repeat';
                bdg.innerHTML = '<i class="fas fa-rotate-left"></i> أعاد القراءة';
                bdg.title = `أعاد القارئ القراءة من «${d.words[first] || ''}»`;
                seg.appendChild(bdg);
            } else if (forwardStop && soloSet.has(last)) {
                const bdg = document.createElement('span');
                bdg.className = 'wq-guide-badge wq-guide-badge-solo';
                bdg.innerHTML = '<i class="fas fa-star"></i> انفرد';
                seg.appendChild(bdg);
            }

            // words — leading re-read words are marked
            const wordsEl = document.createElement('div');
            wordsEl.className = 'wq-guide-words';
            wordsEl.dir = 'rtl';
            for (let wi = first; wi <= last; wi++) {
                if (wi > first) wordsEl.appendChild(document.createTextNode(' '));
                const ws = document.createElement('span');
                if (isBackUp && wi < first + repeatedCount) ws.className = 'wq-guide-w-repeat';
                ws.textContent = d.words[wi] || '';
                wordsEl.appendChild(ws);
            }
            seg.appendChild(wordsEl);

            // waqf rule (printed mushaf) + time
            const foot = document.createElement('div');
            foot.className = 'wq-guide-foot';
            const sym = markByWpos.get(last);
            if (isLast) {
                foot.innerHTML = '<span class="wq-guide-sym wq-guide-ras">۝</span><span class="wq-guide-lbl wq-guide-ras">رأس الآية</span>';
            } else if (sym) {
                foot.innerHTML = `<span class="wq-guide-sym waqf-uthmanic">${waqfGlyph(sym)}</span><span class="wq-guide-lbl">${symMeta(sym).name}</span>`;
            } else {
                foot.innerHTML = `<span class="wq-guide-lbl">${isBackUp ? 'موضع الإعادة' : 'وقف'}</span>`;
            }
            const time = document.createElement('span');
            time.className = 'wq-guide-time';
            time.textContent = '~' + toAr((ph.end - ph.start).toFixed(1)) + 'ث';
            foot.appendChild(time);
            seg.appendChild(foot);

            // play this exact phrase in the reciter's voice
            if (det.audio_url) {
                const play = document.createElement('button');
                play.type = 'button';
                play.className = 'wq-guide-play';
                play.title = `استمع لمقطع ${name}`;
                play.innerHTML = '<i class="fas fa-play"></i>';
                play.addEventListener('click', () => playGuideSeg(seg, play, det.audio_url, det.verse_start + ph.start, det.verse_start + ph.end));
                seg.appendChild(play);
                seg.classList.add('wq-guide-seg-seekable');
            }

            if (!isLast) {
                const arrow = document.createElement('span');
                arrow.className = 'wq-guide-arrow';
                arrow.innerHTML = '<i class="fas fa-arrow-left"></i>';
                seg.appendChild(arrow);
            }
            row.appendChild(seg);
        });
        return row;
    }

    function renderReciters(d) {
        els.recitersCard.hidden = false;
        const wrap = els.reciters;
        wrap.innerHTML = '';
        // Durations legitimately differ between reciters — those who read with
        // قصر المد المنفصل (e.g. أحمد عامر، البنا) are faster than those who
        // lengthen it — so a shorter time is a style choice, not an error.
        const note = document.createElement('p');
        note.className = 'wq-reciters-note';
        note.innerHTML = '<i class="fas fa-circle-info"></i> تختلف الأزمنة بين القرّاء تبعًا لأدائهم (قصر المدّ المنفصل يجعل القراءة أسرع)؛ الزمن المعروض هو مدّة كل مقطع.';
        wrap.appendChild(note);
        // all positions any printed mushaf marks as a waqf — to measure how
        // closely a reciter stops only where a mushaf prescribes.
        const mushafPos = new Set((d.mushafs || []).flatMap(m => m.marks.map(mk => mk.wpos)));
        // waqf symbol at each position (المدينة first, then others) so each
        // reciter stop can show its printed waqf rule like the main-page guide.
        const markByWpos = new Map();
        ['المدينة الجديد', 'المدينة القديم', 'الشمرلي', 'الأزهر', 'قطر', 'الكويت', 'البحرين'].forEach(id => {
            const m = (d.mushafs || []).find(x => x.id === id);
            if (m) m.marks.forEach(mk => { if (!markByWpos.has(mk.wpos)) markByWpos.set(mk.wpos, mk.symbol); });
        });
        const soloSet = new Set(d.union_stops.filter(u => u.solo).map(u => u.wpos));
        const lastW = d.words.length - 1;
        const nameById = new Map(d.reciters.map(r => [r.id, r.name_ar]));

        // Reciters who pause/back up at exactly the same word positions read
        // the verse identically — collect them into ONE row of cards instead
        // of repeating it once per reciter, so the section stays manageable
        // as more reciters are installed.
        const groups = [];
        const bySig = new Map();
        d.reciters.forEach(r => {
            const det = d.per_reciter[r.id];
            const sig = getPhrases(det, lastW).map(p => `${p.first_wpos}-${p.last_wpos}`).join(',');
            let g = bySig.get(sig);
            if (!g) { g = { members: [] }; bySig.set(sig, g); groups.push(g); }
            g.members.push(r.id);
        });
        groups.sort((a, b) => b.members.length - a.members.length);

        groups.forEach(group => {
            const card = document.createElement('div');
            card.className = 'wq-reciter';

            const det0 = d.per_reciter[group.members[0]];
            const nStops = det0.stops.length;
            const onMushaf = (det0.stops || []).filter(s => mushafPos.has(s.wpos)).length;
            const nReps = det0.repeats.length;
            const durations = group.members.map(id => d.per_reciter[id].duration);
            const minD = Math.round(Math.min(...durations)), maxD = Math.round(Math.max(...durations));
            const durText = minD === maxD ? `~${toAr(minD)}ث` : `~${toAr(minD)}–${toAr(maxD)}ث`;

            const head = document.createElement('div');
            head.className = 'wq-reciter-head';

            let activeId = group.members.includes(d.ref_reciter) ? d.ref_reciter : group.members[0];
            let row, soloBlock;

            // قصر المنفصل badge — reflects the active reciter (updates on switch).
            const qasrEl = document.createElement('span');
            qasrEl.className = 'wq-qasr';
            qasrEl.innerHTML = '<i class="fas fa-gauge-high"></i> قصر المنفصل';
            qasrEl.title = 'يقرأ بقصر المدّ المنفصل (حركتان)، فتكون قراءته أسرع من قارئ الإشباع';
            const syncQasr = () => { qasrEl.hidden = !(d.per_reciter[activeId] || {}).qasr_munfasil; };

            if (group.members.length === 1) {
                const nameEl = document.createElement('span');
                nameEl.className = 'wq-reciter-name';
                nameEl.textContent = nameById.get(activeId);
                head.appendChild(nameEl);
            } else {
                // multiple reciters share this exact pattern — show their
                // names as a chip group; clicking one switches the cards
                // below to play/show that reciter's own segments.
                const namesWrap = document.createElement('div');
                namesWrap.className = 'wq-reciter-names';
                group.members.forEach(id => {
                    const qasr = !!(d.per_reciter[id] && d.per_reciter[id].qasr_munfasil);
                    const chip = document.createElement('button');
                    chip.type = 'button';
                    chip.className = 'wq-reciter-chip' + (id === activeId ? ' wq-reciter-chip-active' : '')
                        + (qasr ? ' wq-reciter-chip-qasr' : '');
                    chip.textContent = nameById.get(id);
                    chip.title = (qasr ? 'قصر المنفصل · ' : '') + 'استمع بصوت ' + nameById.get(id);
                    chip.addEventListener('click', () => {
                        if (id === activeId) return;
                        activeId = id;
                        namesWrap.querySelectorAll('.wq-reciter-chip').forEach(c => c.classList.toggle('wq-reciter-chip-active', c === chip));
                        const newRow = buildSegmentRow(d, d.per_reciter[activeId], nameById.get(activeId), lastW, markByWpos, soloSet);
                        row.replaceWith(newRow);
                        row = newRow;
                        const newSolo = buildSoloBlock(d.per_reciter[activeId]);
                        soloBlock.replaceWith(newSolo);
                        soloBlock = newSolo;
                        syncQasr();
                    });
                    namesWrap.appendChild(chip);
                });
                head.appendChild(namesWrap);
            }
            head.appendChild(qasrEl);
            syncQasr();

            const stats = document.createElement('span');
            stats.className = 'wq-reciter-stats';
            stats.innerHTML = `<span><b>${toAr(nStops)}</b> ${nStops === 1 ? 'وقفة' : 'وقفات'}</span>`
                + (mushafPos.size ? `<span class="wq-adhere" title="عدد وقفاته الواقعة على موضع وقف في أحد المصاحف"><i class="fas fa-book-quran"></i> موافقة المصحف <b>${toAr(onMushaf)}/${toAr(nStops)}</b></span>` : '')
                + (nReps ? `<span><b>${toAr(nReps)}</b> ${nReps === 1 ? 'إعادة' : 'إعادات'}</span>` : '')
                + `<span>${durText}</span>`
                + (group.members.length > 1 ? `<span class="wq-reciter-count" title="عدد القرّاء الذين قرؤوا الآية بنفس مواضع الوقف"><i class="fas fa-users"></i> ${toAr(group.members.length)}/${toAr(d.reciters_total)}</span>` : '');
            head.appendChild(stats);

            card.appendChild(head);
            soloBlock = buildSoloBlock(d.per_reciter[activeId]);
            card.appendChild(soloBlock);
            row = buildSegmentRow(d, d.per_reciter[activeId], nameById.get(activeId), lastW, markByWpos, soloSet);
            card.appendChild(row);
            wrap.appendChild(card);
        });
    }

    // What did this reciter pause at that NO other reciter did (انفرد), and does
    // a printed mushaf prescribe a waqf there? Returns an element (empty when the
    // reciter has no solo stops — hidden via CSS :empty).
    function buildSoloBlock(det) {
        const block = document.createElement('div');
        block.className = 'wq-solo-detail';
        const items = (det && det.solo_stops_detail) || [];
        if (!items.length) return block;
        const head = document.createElement('div');
        head.className = 'wq-solo-head';
        head.innerHTML = `<i class="fas fa-user-tag"></i> انفرد بالوقف <span class="wq-solo-count">${toAr(items.length)}</span>`;
        block.appendChild(head);
        const list = document.createElement('div');
        list.className = 'wq-solo-items';
        items.forEach(it => {
            const el = document.createElement('div');
            el.className = 'wq-solo-item' + (it.mushaf_matches && it.mushaf_matches.length ? ' wq-solo-item-matched' : '');
            let html = `<span class="wq-solo-word">${it.word || 'موضع'}</span>`
                     + `<span class="wq-solo-time">${toAr((it.time || 0).toFixed(1))}ث</span>`;
            if (it.mushaf_matches && it.mushaf_matches.length) {
                html += it.mushaf_matches.map(m =>
                    `<span class="wq-mushaf-match" title="يوافق علامة وقف مطبوعة في مصحف ${m.mushaf}">يوافق ${m.mushaf} <b>${m.symbol}</b></span>`
                ).join('');
            } else {
                html += `<span class="wq-solo-nomatch" title="لا توجد علامة وقف مطبوعة عند هذا الموضع في المصاحف المتوفرة">بلا علامة مطبوعة</span>`;
            }
            el.innerHTML = html;
            list.appendChild(el);
        });
        block.appendChild(list);
        return block;
    }

    const reciterName = id => {
        const r = (state.data && state.data.reciters || []).find(x => x.id === id);
        return r ? r.name_ar : id;
    };

    /* ── search ───────────────────────────────────────────────── */
    function parseSearch(raw) {
        const q = fromAr(raw.trim());
        // "2:255" or "2 255" or "2،255"
        let m = q.match(/(\d{1,3})\s*[:،,\s]\s*(\d{1,3})/);
        if (m) return { surah: +m[1], ayah: +m[2] };
        // "name 255" — match a surah name then a number
        m = q.match(/^(.+?)\s+(\d{1,3})\s*$/);
        if (m) {
            const s = findSurahByName(m[1]);
            if (s) return { surah: s, ayah: +m[2] };
        }
        // pure surah name → ayah 1
        const s = findSurahByName(q);
        if (s) return { surah: s, ayah: 1 };
        return null;
    }
    function findSurahByName(name) {
        const norm = t => t.replace(/[أإآ]/g, 'ا').replace(/ة/g, 'ه').replace(/\s|ال/g, '');
        const target = norm(name);
        if (!target) return null;
        const hit = catalog.entries.find(s => norm(s.name || '').includes(target));
        return hit ? (hit.number ?? null) : null;
    }
    async function doSearch() {
        const raw = els.search.value.trim();
        if (!raw) { hideSearchResults(); return; }
        const parsed = parseSearch(raw);
        if (parsed) {
            if (parsed.surah < 1 || parsed.surah > 114) { setStatus('رقم سورة غير صحيح', true); return; }
            hideSearchResults();
            await navigateTo(parsed.surah, parsed.ayah);
            return;
        }
        // not a verse reference → search the Quran text for these words
        if (wordQueryOf(raw).length >= 2) { await showWordResults(raw); return; }
        setStatus('اكتب رقم السورة والآية، أو اسم السورة، أو كلمات من الآية', true);
    }

    /* ── search by words ──────────────────────────────────────── */
    // strip everything but Arabic letters/spaces, to decide if a query is
    // "word-ish" enough to send to the text search endpoint.
    function wordQueryOf(raw) {
        return fromAr(raw).replace(/[^؀-ۿ\s]/g, '').trim();
    }
    const searchRequests = window.AtharMushaf.createRequestGate();
    function hideSearchResults() {
        searchRequests.cancel();
        if (!els.searchResults) return;
        els.searchResults.hidden = true;
        els.searchResults.innerHTML = '';
        els.search.setAttribute('aria-expanded', 'false');
        els.search.removeAttribute('aria-activedescendant');
    }
    async function showWordResults(query) {
        if (!els.searchResults) return;
        const request = searchRequests.next();
        els.searchResults.hidden = false;
        els.search.setAttribute('aria-expanded', 'true');
        els.search.removeAttribute('aria-activedescendant');
        els.searchResults.innerHTML = '<div class="wq-search-loading">جارٍ البحث…</div>';
        try {
            const data = await window.AtharApi.json(`/api/search?q=${encodeURIComponent(query)}&limit=8`);
            if (!searchRequests.isCurrent(request)) return;
            const results = data.results || [];
            if (!results.length) {
                els.searchResults.innerHTML = '<div class="wq-search-empty">لا توجد نتائج لهذه الكلمات</div>';
                return;
            }
            els.searchResults.innerHTML = '';
            results.forEach((r, index) => {
                const btn = document.createElement('button');
                btn.type = 'button';
                btn.className = 'wq-search-result';
                btn.id = `wq-search-result-${index}`;
                btn.setAttribute('role', 'option');
                btn.setAttribute('aria-selected', 'false');
                const ref = document.createElement('span');
                ref.className = 'wq-sr-ref';
                const sName = surahName(r.surah_number);
                ref.textContent = `${sName ? 'سورة ' + sName : 'سورة ' + toAr(r.surah_number)} · آية ${toAr(r.ayah_number)}`;
                const txt = document.createElement('span');
                txt.className = 'wq-sr-text';
                txt.textContent = r.text;
                btn.append(ref, txt);
                btn.addEventListener('click', async () => {
                    hideSearchResults();
                    els.search.value = '';
                    els.searchClear.hidden = true;
                    await navigateTo(r.surah_number, r.ayah_number);
                });
                els.searchResults.appendChild(btn);
            });
        } catch (e) {
            if (searchRequests.isCurrent(request)) els.searchResults.innerHTML = '<div class="wq-search-empty">تعذّر البحث الآن</div>';
        }
    }

    /* ── events (verse study page only) ───────────────────────── */
    if (!IS_LAB && els.surah && els.ayah && els.prev && els.next && els.search) {
    els.surah.addEventListener('change', () => navigateTo(+els.surah.value, 1));
    els.ayah.addEventListener('change', () => navigateTo(+els.surah.value, +els.ayah.value));
    async function stepVerse(delta) {
        const target = await window.AtharMushaf.stepVerse(state, delta, { getAyahCount });
        if (target) await navigateTo(target.surah, target.ayah);
    }
    els.prev.addEventListener('click', () => stepVerse(-1));
    els.next.addEventListener('click', () => stepVerse(1));
    let searchDebounce = null;
    els.search.addEventListener('input', () => {
        const raw = els.search.value;
        if (els.searchClear) els.searchClear.hidden = !raw;
        clearTimeout(searchDebounce);
        if (!raw.trim()) { hideSearchResults(); return; }
        if (parseSearch(raw)) { hideSearchResults(); return; }   // looks like a verse ref — wait for Enter
        if (wordQueryOf(raw).length < 2) { hideSearchResults(); return; }
        searchDebounce = setTimeout(() => showWordResults(raw), 350);
    });
    els.search.addEventListener('keydown', e => {
        const results = (els.searchResults && !els.searchResults.hidden)
            ? [...els.searchResults.querySelectorAll('.wq-search-result')] : [];
        if (e.key === 'ArrowDown' && results.length) {
            e.preventDefault();
            let idx = results.findIndex(r => r.classList.contains('wq-sr-active'));
            idx = (idx + 1) % results.length;
            results.forEach(r => { r.classList.remove('wq-sr-active'); r.setAttribute('aria-selected', 'false'); });
            results[idx].classList.add('wq-sr-active');
            results[idx].setAttribute('aria-selected', 'true');
            els.search.setAttribute('aria-activedescendant', results[idx].id);
            results[idx].scrollIntoView({ block: 'nearest' });
        } else if (e.key === 'ArrowUp' && results.length) {
            e.preventDefault();
            let idx = results.findIndex(r => r.classList.contains('wq-sr-active'));
            idx = idx <= 0 ? results.length - 1 : idx - 1;
            results.forEach(r => { r.classList.remove('wq-sr-active'); r.setAttribute('aria-selected', 'false'); });
            results[idx].classList.add('wq-sr-active');
            results[idx].setAttribute('aria-selected', 'true');
            els.search.setAttribute('aria-activedescendant', results[idx].id);
            results[idx].scrollIntoView({ block: 'nearest' });
        } else if (e.key === 'Enter') {
            e.preventDefault();
            const active = results.find(r => r.classList.contains('wq-sr-active'));
            if (active) active.click(); else doSearch();
        } else if (e.key === 'Escape') {
            hideSearchResults();
        }
    });
    if (els.searchClear) els.searchClear.addEventListener('click', () => {
        els.search.value = ''; els.searchClear.hidden = true; hideSearchResults(); els.search.focus();
    });
    document.addEventListener('click', e => {
        if (els.searchResults && !els.searchResults.hidden && !e.target.closest('.wq-field-search')) hideSearchResults();
    });
    if (els.breathPicker) els.breathPicker.addEventListener('click', e => {
        const btn = e.target.closest('.wq-breath-btn');
        if (!btn) return;
        state.breathL = parseInt(btn.dataset.l, 10) || BREATH.medium;
        els.breathPicker.querySelectorAll('.wq-breath-btn').forEach(b => {
            const active = b === btn;
            b.classList.toggle('wq-on', active);
            b.setAttribute('aria-pressed', String(active));
        });
        if (state.data) renderRecommendation(state.data);
    });
    // matrix cell → play that reciter's segment up to the clicked stop
    const matrixPlayRoot = els.matrixCard || els.matrix;
    if (matrixPlayRoot) matrixPlayRoot.addEventListener('click', e => {
        const cell = e.target.closest('.wq-cell-play');
        if (!cell || !state.data) return;
        playReciterStop(state.data, cell.dataset.rid, parseInt(cell.dataset.wpos, 10), cell);
    });
    }

    /* ── init ─────────────────────────────────────────────────── */
    async function init() {
        try {
            await loadSurahs();
            if (IS_LAB) {
                setupResearch();
                const p = new URLSearchParams(location.search);
                const tabId = p.get('tab');
                const family = p.get('family');
                const tab = tabId
                    ? document.querySelector(`.wq-lab-tab[data-tab="${CSS.escape(tabId)}"]`)
                    : null;
                if (tab) {
                    // selectLabTab applies the matching family
                    tab.click();
                } else if (family) {
                    document.querySelector(`.wq-lab-family[data-family="${CSS.escape(family)}"]`)?.click();
                } else {
                    document.querySelector('.wq-lab-family[data-family="words"]')?.click();
                }
                const q = (p.get('q') || '').trim();
                if (q) {
                    if (els.researchInput) els.researchInput.value = q;
                    // Ensure word panel is active, then search.
                    document.querySelector('.wq-lab-tab[data-tab="word"]')?.click();
                    runResearch(q, p.get('exact') === '1', p.get('mode') || '');
                }
                return;
            }
            const p = new URLSearchParams(location.search);
            // Legacy deep-link: /waqf?tab=solos → send to the lab workspace.
            if (p.get('tab') || p.get('family') || p.get('lab') === '1') {
                const dest = new URL('/waqf-lab', location.origin);
                if (p.get('tab')) dest.searchParams.set('tab', p.get('tab'));
                if (p.get('family')) dest.searchParams.set('family', p.get('family'));
                location.replace(dest.pathname + dest.search);
                return;
            }
            const surah = Math.min(Math.max(1, parseInt(p.get('surah'), 10) || 2), 114);
            const ayah = parseInt(p.get('ayah'), 10) || (surah === 2 ? 255 : 1);
            const wpos = parseInt(p.get('wpos'), 10);
            await navigateTo(surah, ayah, {
                wpos: Number.isFinite(wpos) && wpos >= 0 ? wpos : null,
                word: (p.get('hl') || '').trim() || null,
            });
        } catch (e) {
            setStatus('تعذّر تهيئة الصفحة', true);
        }
    }
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
    else init();
})();
