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
    const toAr = n => String(n).replace(/[0-9]/g, d => '٠١٢٣٤٥٦٧٨٩'[d]);
    const fromAr = s => String(s).replace(/[٠-٩]/g, d => '٠١٢٣٤٥٦٧٨٩'.indexOf(d));

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

    // The printed-mushaf DB stores abbreviations (ج/ق/ص/م/لا/س/ع); show the
    // real Uthmanic-Hafs waqf glyph instead (as the main page does).
    const WAQF_GLYPH = {
        'م':  'ۘ',  // ۘ  وقف لازم
        'لا': 'ۙ',  // ۙ  لا وقف
        'ق':  'ۗ',  // ۗ  قلى — الوقف أولى
        'ص':  'ۖ',  // ۖ  صلى — الوصل أولى
        'ج':  'ۚ',  // ۚ  جائز
        'س':  'ۜ',  // ۜ  سكتة
        'ع':  'ۛ',  // ۛ  معانقة
    };
    const waqfGlyph = s => WAQF_GLYPH[s] || s;

    // Breath presets (max comfortable seconds per breath).
    const BREATH = { short: 7, medium: 13, long: 20 };

    const els = {
        surah: $('wq-surah'), ayah: $('wq-ayah'), search: $('wq-search'),
        searchClear: $('wq-search-clear'), searchResults: $('wq-search-results'),
        prev: $('wq-prev'), next: $('wq-next'), theme: $('wq-theme'), status: $('wq-status'),
        barVerse: $('wq-bar-verse'),
        verseCard: $('wq-verse-card'), verseTitle: $('wq-verse-title'), verseMeta: $('wq-verse-meta'),
        bestStops: $('wq-best-stops'), verseFlow: $('wq-verse-flow'),
        recCard: $('wq-rec-card'), breathPicker: $('wq-breath-picker'),
        recSummary: $('wq-rec-summary'), recPlan: $('wq-rec-plan'),
        matrixCard: $('wq-matrix-card'), matrix: $('wq-matrix'), matrixLegend: $('wq-matrix-legend'),
        recitersCard: $('wq-reciters-card'), reciters: $('wq-reciters'),
        researchToggle: $('wq-research-toggle'), researchBody: $('wq-research-body'),
        researchInput: $('wq-research-input'), researchForms: $('wq-research-forms'),
        researchResults: $('wq-research-results'),
        panelWord: $('wq-panel-word'), panelSolos: $('wq-panel-solos'),
        panelStats: $('wq-panel-stats'), panelMandatory: $('wq-panel-mandatory'),
        panelPatterns: $('wq-panel-patterns'), panelCluster: $('wq-panel-cluster'),
        solosContent: $('wq-solos-content'),
        statsContent: $('wq-stats-content'), mandatoryContent: $('wq-mandatory-content'),
        patternsContent: $('wq-patterns-content'), clusterContent: $('wq-cluster-content'),
    };

    const state = { surahs: [], surah: 2, ayah: 255, ayahCount: {}, data: null, busy: false, breathL: BREATH.medium };

    /* ── status toast ─────────────────────────────────────────── */
    let toastId = 0;
    function setStatus(msg, isErr) {
        clearTimeout(toastId);
        if (!msg) { els.status.classList.remove('wq-show'); return; }
        els.status.textContent = msg;
        els.status.classList.toggle('wq-err', !!isErr);
        els.status.classList.add('wq-show');
        if (!isErr) toastId = setTimeout(() => els.status.classList.remove('wq-show'), 1600);
    }

    /* ── theme (shared أثَر engine: cycles white → dark → sepia) ─── */
    function themeIcon(t) {
        return t === 'dark' ? 'fas fa-moon' : t === 'sepia' ? 'fas fa-leaf' : 'fas fa-sun';
    }
    function initTheme() {
        // theme.js already applied the shared theme on load; just sync the icon.
        const i = els.theme.querySelector('i');
        if (i) i.className = themeIcon(window.AtharTheme.get());
    }
    els.theme.addEventListener('click', () => { window.AtharTheme.cycle(); });
    document.addEventListener('athar:theme', initTheme);

    /* ── data loading ─────────────────────────────────────────── */
    async function loadSurahs() {
        const resp = await fetch('/api/surahs');
        state.surahs = await resp.json();
        els.surah.innerHTML = state.surahs.map(s => {
            const num = s.number ?? s, name = s.name ?? `سورة ${num}`;
            return `<option value="${num}">${toAr(num)}. ${name}</option>`;
        }).join('');
    }
    function surahName(num) {
        const s = state.surahs.find(x => (x.number ?? x) === num);
        return s ? (s.name ?? '') : '';
    }
    async function loadAyahOptions(surah) {
        if (!state.ayahCount[surah]) {
            const resp = await fetch(`/api/surahs/${surah}/ayahs`);
            const list = await resp.json();
            state.ayahCount[surah] = Array.isArray(list) ? list.length : 0;
        }
        const n = state.ayahCount[surah] || 0;
        els.ayah.innerHTML = Array.from({ length: n }, (_, i) =>
            `<option value="${i + 1}">${toAr(i + 1)}</option>`).join('');
    }

    async function loadVerse(surah, ayah) {
        if (state.busy) return;
        state.busy = true;
        setStatus('جارٍ التحميل…');
        try {
            const resp = await fetch(`/api/waqf/${surah}/${ayah}`);
            if (!resp.ok) throw new Error('load failed');
            state.data = await resp.json();
            state.surah = surah; state.ayah = ayah;
            els.surah.value = String(surah);
            els.ayah.value = String(ayah);
            render(state.data);
            setStatus('');
            const url = new URL(location.href);
            url.searchParams.set('surah', surah); url.searchParams.set('ayah', ayah);
            history.replaceState(null, '', url);
        } catch (e) {
            setStatus('تعذّر تحميل بيانات هذه الآية', true);
        } finally {
            state.busy = false;
            updateStepper();
        }
    }
    function updateStepper() {
        els.prev.disabled = state.ayah <= 1;
        els.next.disabled = state.ayah >= (state.ayahCount[state.surah] || Infinity);
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
        els.researchResults.innerHTML = '<div class="wq-research-loading">…جارٍ البحث</div>';
        try {
            let url = '/api/waqf-research?word=' + encodeURIComponent(word);
            if (exact) url += '&exact=1';
            if (mode) url += '&mode=' + mode;
            const resp = await fetch(url);
            const d = await resp.json();
            researchState = { word, mode, forms: d.forms || [], occ: d.occurrences || [], form: d.active_form || null, waqf: null };
            renderResearch();
        } catch (e) {
            els.researchResults.innerHTML = '<div class="wq-research-empty">تعذّر البحث</div>';
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
        els.researchResults.innerHTML = `<div class="wq-research-count">${toAr(list.length)} موضعًا</div>` + modeNote + list.map(o => {
            const ref = `${toAr(o.surah)}:${toAr(o.ayah)}`;
            const sname = (state.surahs.find(s => s.number === o.surah) || {}).name || '';
            const ent = Object.entries(o.marks || {});
            const marks = ent.length
                ? `<span class="wq-research-marks" title="${ent.map(([k, v]) => k + ' ' + v).join(' · ')}">`
                  + ent.map(([k, v]) => `<span class="wq-rmark waqf-uthmanic" data-m="${k}">${v}</span>`).join('') + '</span>'
                : '<span class="wq-research-nomark" title="لا علامة وقف مطبوعة">—</span>';
            return `<button class="wq-research-item" type="button" data-s="${o.surah}" data-a="${o.ayah}" title="افتح ${sname} ${ref} لرؤية وقوف القرّاء والمصاحف">
                <span class="wq-research-ref">${sname} <b>${ref}</b></span>
                <span class="wq-research-ctx" dir="rtl">${o.context}</span>${marks}
                <i class="fas fa-chevron-left wq-research-go"></i>
            </button>`;
        }).join('');
    }

    /* ── solo stops (انفرادات القرّاء) ────────────────────────────── */
    let solosCache = null;
    let solosReciterCache = {};

    async function loadSolosSummary() {
        if (solosCache) { renderSolosSummary(); return; }
        els.solosContent.innerHTML = '<div class="wq-research-loading">…جارٍ التحليل</div>';
        try {
            const resp = await fetch('/api/waqf-research/solos');
            solosCache = await resp.json();
            renderSolosSummary();
        } catch { els.solosContent.innerHTML = '<div class="wq-research-empty">تعذّر التحميل</div>'; }
    }

    function renderSolosSummary() {
        const reciters = (solosCache.reciters || []).slice().sort((a, b) => b.solo_count - a.solo_count);
        if (!reciters.length) { els.solosContent.innerHTML = '<div class="wq-research-empty">لا بيانات</div>'; return; }
        els.solosContent.innerHTML =
            '<div class="wq-solos-desc">مواضع وقف كل قارئ التي لم يشاركه فيها أحد من بقية القرّاء</div>'
            + '<div class="wq-solos-grid">' + reciters.map(r =>
                `<button class="wq-solos-card" data-rid="${r.id}" type="button">
                    <span class="wq-solos-name">${r.name_ar}</span>
                    <span class="wq-solos-count">${toAr(r.solo_count)}</span>
                    <span class="wq-solos-label">انفراد</span>
                </button>`
            ).join('') + '</div>';
    }

    async function loadSolosDetail(rid) {
        if (solosReciterCache[rid]) { renderSolosDetail(solosReciterCache[rid]); return; }
        els.solosContent.innerHTML = '<div class="wq-research-loading">…جارٍ التحميل</div>';
        try {
            const resp = await fetch('/api/waqf-research/solos?reciter=' + encodeURIComponent(rid));
            const d = await resp.json();
            solosReciterCache[rid] = d;
            renderSolosDetail(d);
        } catch { els.solosContent.innerHTML = '<div class="wq-research-empty">تعذّر التحميل</div>'; }
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
        els.solosContent.innerHTML = header + '<div class="wq-solos-list">' + renderSoloItems(list) + '</div>';
        const frow = els.solosContent.querySelector('.wq-research-frow');
        if (frow) frow.addEventListener('click', e => {
            const btn = e.target.closest('.wq-wfilter'); if (!btn) return;
            frow.querySelectorAll('.wq-wfilter').forEach(b => b.classList.remove('wq-wfilter-active'));
            btn.classList.add('wq-wfilter-active');
            const f = btn.dataset.sf;
            const filtered = !f ? stops : f === 'yes' ? stops.filter(o => o.has_waqf) : stops.filter(o => !o.has_waqf);
            els.solosContent.querySelector('.wq-solos-list').innerHTML = renderSoloItems(filtered);
        });
    }

    function renderSoloItems(list) {
        if (!list.length) return '<div class="wq-research-empty">لا نتائج</div>';
        return list.map(o => {
            const ref = `${toAr(o.surah)}:${toAr(o.ayah)}`;
            const sname = (state.surahs.find(s => s.number === o.surah) || {}).name || '';
            const ent = Object.entries(o.marks || {});
            const marks = ent.length
                ? `<span class="wq-research-marks" title="${ent.map(([k, v]) => k + ' ' + v).join(' · ')}">`
                  + ent.map(([k, v]) => `<span class="wq-rmark waqf-uthmanic" data-m="${k}">${v}</span>`).join('') + '</span>'
                : '<span class="wq-research-nomark" title="لا علامة وقف مطبوعة">—</span>';
            return `<button class="wq-research-item" type="button" data-s="${o.surah}" data-a="${o.ayah}" title="افتح ${sname} ${ref}">
                <span class="wq-research-ref">${sname} <b>${ref}</b></span>
                <span class="wq-research-ctx" dir="rtl">${o.context}</span>${marks}
                <i class="fas fa-chevron-left wq-research-go"></i>
            </button>`;
        }).join('');
    }

    /* ── إحصائيات (stats tab) ──────────────────────────────────── */
    let statsCache = null, consensusCache = null, statsView = 'surahs';

    async function loadStats() {
        if (statsCache) { renderStats(); return; }
        els.statsContent.innerHTML = '<div class="wq-research-loading">…جارٍ التحليل</div>';
        try {
            const resp = await fetch('/api/waqf-research/stats');
            statsCache = await resp.json();
            statsView = 'surahs';
            renderStats();
        } catch { els.statsContent.innerHTML = '<div class="wq-research-empty">تعذّر التحميل</div>'; }
    }

    async function loadConsensus() {
        if (consensusCache) { renderConsensus(); return; }
        els.statsContent.innerHTML = '<div class="wq-research-loading">…جارٍ التحميل</div>';
        try {
            const resp = await fetch('/api/waqf-research/stats?view=consensus');
            consensusCache = await resp.json();
            renderConsensus();
        } catch { els.statsContent.innerHTML = '<div class="wq-research-empty">تعذّر التحميل</div>'; }
    }

    function renderStats() {
        const surahs = (statsCache.surahs || []).slice().sort((a, b) => b.divergent - a.divergent);
        const topV = statsCache.top_divergent || [];
        const totalDiv = surahs.reduce((s, x) => s + x.divergent, 0);
        const totalCons = surahs.reduce((s, x) => s + x.consensus, 0);

        let tabs = `<div class="wq-stats-subtabs">
            <button class="wq-stats-subtab${statsView === 'surahs' ? ' wq-lab-tab-active' : ''}" data-sv="surahs">السور</button>
            <button class="wq-stats-subtab${statsView === 'verses' ? ' wq-lab-tab-active' : ''}" data-sv="verses">أكثر الآيات اختلافًا</button>
            <button class="wq-stats-subtab${statsView === 'consensus' ? ' wq-lab-tab-active' : ''}" data-sv="consensus">مواضع الاتفاق</button>
        </div>`;

        let body = '';
        if (statsView === 'surahs') {
            body = `<div class="wq-stats-summary">${toAr(totalDiv)} موضع اختلاف · ${toAr(totalCons)} موضع اتفاق تام</div>`
                + '<div class="wq-stats-list">' + surahs.filter(s => s.total > 0).map(s => {
                    const pct = s.total ? Math.round(s.consensus / s.total * 100) : 0;
                    return `<div class="wq-stats-row">
                        <span class="wq-stats-sname">${s.name} <b>${toAr(s.surah)}</b></span>
                        <span class="wq-stats-bar"><span class="wq-stats-fill" style="width:${pct}%"></span></span>
                        <span class="wq-stats-nums"><span class="wq-stats-cons">${toAr(s.consensus)}</span> / <span class="wq-stats-div">${toAr(s.divergent)}</span></span>
                    </div>`;
                }).join('') + '</div>';
        } else if (statsView === 'verses') {
            body = '<div class="wq-solos-list">' + topV.slice(0, 60).map(v => {
                const sname = (state.surahs.find(s => s.number === v.surah) || {}).name || '';
                return `<button class="wq-research-item" type="button" data-s="${v.surah}" data-a="${v.ayah}">
                    <span class="wq-research-ref">${sname} <b>${toAr(v.surah)}:${toAr(v.ayah)}</b></span>
                    <span class="wq-stats-badge wq-stats-div">${toAr(v.divergent)} اختلاف</span>
                    <span class="wq-stats-badge wq-stats-cons">${toAr(v.consensus)} اتفاق</span>
                    <i class="fas fa-chevron-left wq-research-go"></i>
                </button>`;
            }).join('') + '</div>';
        }
        els.statsContent.innerHTML = tabs + body;
    }

    function renderConsensus() {
        const items = consensusCache.consensus || [];
        let tabs = `<div class="wq-stats-subtabs">
            <button class="wq-stats-subtab" data-sv="surahs">السور</button>
            <button class="wq-stats-subtab" data-sv="verses">أكثر الآيات اختلافًا</button>
            <button class="wq-stats-subtab wq-lab-tab-active" data-sv="consensus">مواضع الاتفاق</button>
        </div>`;
        let body = `<div class="wq-solos-desc">مواضع وقف اتفق عليها جميع القرّاء ولها علامة مطبوعة في المصاحف</div>`
            + `<div class="wq-research-count">${toAr(items.length)} موضعًا</div>`
            + '<div class="wq-solos-list">' + items.map(o => {
                const sname = (state.surahs.find(s => s.number === o.surah) || {}).name || '';
                const ent = Object.entries(o.marks || {});
                const marks = ent.length
                    ? `<span class="wq-research-marks">${ent.map(([k, v]) => `<span class="wq-rmark waqf-uthmanic" data-m="${k}">${v}</span>`).join('')}</span>` : '';
                return `<button class="wq-research-item" type="button" data-s="${o.surah}" data-a="${o.ayah}">
                    <span class="wq-research-ref">${sname} <b>${toAr(o.surah)}:${toAr(o.ayah)}</b></span>
                    <span class="wq-research-ctx" dir="rtl">${o.context}</span>${marks}
                    <i class="fas fa-chevron-left wq-research-go"></i>
                </button>`;
            }).join('') + '</div>';
        els.statsContent.innerHTML = tabs + body;
    }

    /* ── الوقف اللازم والممنوع (mandatory tab) ──────────────────── */
    let mandatoryCache = null, mandView = 'mandatory';

    async function loadMandatory() {
        if (mandatoryCache) { renderMandatory(); return; }
        els.mandatoryContent.innerHTML = '<div class="wq-research-loading">…جارٍ التحميل</div>';
        try {
            const resp = await fetch('/api/waqf-research/mandatory');
            mandatoryCache = await resp.json();
            renderMandatory();
        } catch { els.mandatoryContent.innerHTML = '<div class="wq-research-empty">تعذّر التحميل</div>'; }
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
        let body = `<div class="wq-solos-desc">${descs[mandView]}</div>`;
        if (mandView === 'embracing') {
            body += '<div class="wq-solos-list">' + renderEmbracingItems(embr) + '</div>';
        } else {
            body += '<div class="wq-solos-list">' + renderMandItems(mandView === 'mandatory' ? mand : forb) + '</div>';
        }
        els.mandatoryContent.innerHTML = tabs + body;
    }

    function renderEmbracingItems(list) {
        if (!list.length) return '<div class="wq-research-empty">لا نتائج</div>';
        return list.map(o => {
            const sname = (state.surahs.find(s => s.number === o.surah) || {}).name || '';
            const ref = `${toAr(o.surah)}:${toAr(o.ayah)}`;
            const pair = o.pair || [];
            const pairHtml = pair.map(p => {
                const ent = Object.entries(p.marks || {});
                const marks = ent.length
                    ? `<span class="wq-research-marks">${ent.map(([k, v]) => `<span class="wq-rmark waqf-uthmanic" data-m="${k}">${v}</span>`).join('')}</span>` : '';
                return `<span class="wq-muan-word">${p.word}</span>${marks}`;
            }).join('<span class="wq-muan-or">أو</span>');
            const agree = o.agreement === 'full'
                ? '<span class="wq-mand-agree" title="جميع المصاحف متفقة"><i class="fas fa-check-double"></i></span>'
                : '<span class="wq-mand-partial" title="اختلاف بين المصاحف"><i class="fas fa-exclamation-triangle"></i></span>';
            return `<button class="wq-research-item wq-muan-item" type="button" data-s="${o.surah}" data-a="${o.ayah}">
                <span class="wq-research-ref">${sname} <b>${ref}</b></span>
                <span class="wq-muan-pair" dir="rtl">${pairHtml}</span>${agree}
                <i class="fas fa-chevron-left wq-research-go"></i>
            </button>`;
        }).join('');
    }

    function renderMandItems(list) {
        if (!list.length) return '<div class="wq-research-empty">لا نتائج</div>';
        return list.map(o => {
            const sname = (state.surahs.find(s => s.number === o.surah) || {}).name || '';
            const ent = Object.entries(o.marks || {});
            const marks = ent.length
                ? `<span class="wq-research-marks" title="${ent.map(([k, v]) => k + ' ' + v).join(' · ')}">`
                  + ent.map(([k, v]) => `<span class="wq-rmark waqf-uthmanic" data-m="${k}">${v}</span>`).join('') + '</span>' : '';
            const agree = o.agreement === 'full'
                ? '<span class="wq-mand-agree" title="جميع المصاحف متفقة"><i class="fas fa-check-double"></i></span>'
                : '<span class="wq-mand-partial" title="اختلاف بين المصاحف"><i class="fas fa-exclamation-triangle"></i></span>';
            return `<button class="wq-research-item" type="button" data-s="${o.surah}" data-a="${o.ayah}">
                <span class="wq-research-ref">${sname} <b>${toAr(o.surah)}:${toAr(o.ayah)}</b></span>
                <span class="wq-research-ctx" dir="rtl">${o.context}</span>${marks}${agree}
                <i class="fas fa-chevron-left wq-research-go"></i>
            </button>`;
        }).join('');
    }

    /* ── اختلاف المصاحف (cross-verse patterns) ─────────────────── */
    let patternsCache = null;

    async function loadPatterns() {
        if (patternsCache) { renderPatterns(); return; }
        els.patternsContent.innerHTML = '<div class="wq-research-loading">…جارٍ التحليل</div>';
        try {
            const resp = await fetch('/api/waqf-research/patterns');
            patternsCache = await resp.json();
            renderPatterns();
        } catch { els.patternsContent.innerHTML = '<div class="wq-research-empty">تعذّر التحميل</div>'; }
    }

    function renderPatterns() {
        const items = patternsCache.disagreements || [];
        els.patternsContent.innerHTML =
            `<div class="wq-solos-desc">مواضع وضع فيها كل مصحف علامة وقف مختلفة عن الآخر</div>`
            + `<div class="wq-research-count">${toAr(items.length)} موضع اختلاف</div>`
            + '<div class="wq-solos-list">' + items.map(o => {
                const sname = (state.surahs.find(s => s.number === o.surah) || {}).name || '';
                const ent = Object.entries(o.marks || {});
                const marks = ent.length
                    ? `<span class="wq-research-marks" title="${ent.map(([k, v]) => k + ': ' + v).join(' · ')}">`
                      + ent.map(([k, v]) => `<span class="wq-rmark waqf-uthmanic" data-m="${k}">${v}</span>`).join('') + '</span>' : '';
                return `<button class="wq-research-item" type="button" data-s="${o.surah}" data-a="${o.ayah}">
                    <span class="wq-research-ref">${sname} <b>${toAr(o.surah)}:${toAr(o.ayah)}</b></span>
                    <span class="wq-research-ctx" dir="rtl">${o.context}</span>${marks}
                    <i class="fas fa-chevron-left wq-research-go"></i>
                </button>`;
            }).join('') + '</div>';
    }

    /* ── تشابه القرّاء (reciter clustering) ────────────────────── */
    let clusterCache = null;

    async function loadCluster() {
        if (clusterCache) { renderCluster(); return; }
        els.clusterContent.innerHTML = '<div class="wq-research-loading">…جارٍ التحليل</div>';
        try {
            const resp = await fetch('/api/waqf-research/clustering');
            clusterCache = await resp.json();
            renderCluster();
        } catch { els.clusterContent.innerHTML = '<div class="wq-research-empty">تعذّر التحميل</div>'; }
    }

    function renderCluster() {
        const groups = clusterCache.groups || [];
        const topPairs = clusterCache.pairs || [];
        let html = '<div class="wq-solos-desc">تشابه أنماط التنفّس والوقف بين القرّاء عبر القرآن كله (مؤشر جاكار)</div>';

        if (topPairs.length) {
            html += '<div class="wq-cluster-top"><span class="wq-research-flabel">أقرب القرّاء تشابهًا</span>';
            html += topPairs.slice(0, 10).map(p =>
                `<div class="wq-cluster-pair">
                    <span class="wq-cluster-name">${p.n1}</span>
                    <span class="wq-cluster-sim">${Math.round(p.similarity * 100)}٪</span>
                    <span class="wq-cluster-name">${p.n2}</span>
                </div>`
            ).join('') + '</div>';
        }

        html += '<div class="wq-solos-grid">' + groups.map(g => {
            const peersHtml = g.peers.map(p =>
                `<span class="wq-cluster-peer">${p.name_ar} <b>${Math.round(p.similarity * 100)}٪</b></span>`
            ).join('');
            return `<div class="wq-cluster-card">
                <span class="wq-solos-name">${g.name_ar}</span>
                <span class="wq-solos-count">${toAr(g.total_breaths)}</span>
                <span class="wq-solos-label">موضع تنفّس</span>
                <div class="wq-cluster-peers">${peersHtml}</div>
            </div>`;
        }).join('') + '</div>';

        els.clusterContent.innerHTML = html;
    }

    function setupResearch() {
        if (!els.researchToggle) return;
        els.researchToggle.addEventListener('click', () => {
            const open = els.researchBody.hidden;
            els.researchBody.hidden = !open;
            els.researchToggle.setAttribute('aria-expanded', String(open));
        });
        document.querySelectorAll('.wq-lab-tab').forEach(tab => tab.addEventListener('click', () => {
            document.querySelectorAll('.wq-lab-tab').forEach(t => t.classList.remove('wq-lab-tab-active'));
            tab.classList.add('wq-lab-tab-active');
            const which = tab.dataset.tab;
            els.panelWord.hidden = which !== 'word';
            els.panelSolos.hidden = which !== 'solos';
            els.panelStats.hidden = which !== 'stats';
            els.panelMandatory.hidden = which !== 'mandatory';
            els.panelPatterns.hidden = which !== 'patterns';
            els.panelCluster.hidden = which !== 'cluster';
            if (which === 'solos') loadSolosSummary();
            if (which === 'stats') loadStats();
            if (which === 'mandatory') loadMandatory();
            if (which === 'patterns') loadPatterns();
            if (which === 'cluster') loadCluster();
        }));
        document.querySelectorAll('.wq-research-chip').forEach(c =>
            c.addEventListener('click', () => runResearch(c.dataset.word, c.dataset.exact === '1', c.dataset.mode || '')));
        if (els.researchInput) els.researchInput.addEventListener('keydown', e => {
            if (e.key === 'Enter') runResearch(els.researchInput.value);
        });
        els.researchForms.addEventListener('click', e => {
            const fb = e.target.closest('.wq-form-chip');
            if (fb) { researchState.form = fb.dataset.form || null; researchState.waqf = null; renderResearch(); return; }
            const wb = e.target.closest('.wq-wfilter');
            if (wb) { researchState.waqf = wb.dataset.waqf || null; renderResearch(); }
        });
        els.researchResults.addEventListener('click', async e => {
            const b = e.target.closest('.wq-research-item'); if (!b) return;
            const s = +b.dataset.s, a = +b.dataset.a;
            if (s !== state.surah) await loadAyahOptions(s);
            await loadVerse(s, a);
            if (els.verseCard) els.verseCard.scrollIntoView({ behavior: 'smooth', block: 'start' });
        });
        els.patternsContent.addEventListener('click', async e => {
            const item = e.target.closest('.wq-research-item'); if (!item) return;
            const s = +item.dataset.s, a = +item.dataset.a;
            if (s !== state.surah) await loadAyahOptions(s);
            await loadVerse(s, a);
            if (els.verseCard) els.verseCard.scrollIntoView({ behavior: 'smooth', block: 'start' });
        });
        els.statsContent.addEventListener('click', async e => {
            const st = e.target.closest('.wq-stats-subtab');
            if (st) {
                const sv = st.dataset.sv;
                if (sv === 'consensus') { statsView = 'consensus'; loadConsensus(); }
                else { statsView = sv; renderStats(); }
                return;
            }
            const item = e.target.closest('.wq-research-item');
            if (item) {
                const s = +item.dataset.s, a = +item.dataset.a;
                if (s !== state.surah) await loadAyahOptions(s);
                await loadVerse(s, a);
                if (els.verseCard) els.verseCard.scrollIntoView({ behavior: 'smooth', block: 'start' });
            }
        });
        els.mandatoryContent.addEventListener('click', async e => {
            const mt = e.target.closest('.wq-stats-subtab');
            if (mt) { mandView = mt.dataset.mv; renderMandatory(); return; }
            const item = e.target.closest('.wq-research-item');
            if (item) {
                const s = +item.dataset.s, a = +item.dataset.a;
                if (s !== state.surah) await loadAyahOptions(s);
                await loadVerse(s, a);
                if (els.verseCard) els.verseCard.scrollIntoView({ behavior: 'smooth', block: 'start' });
            }
        });
        els.solosContent.addEventListener('click', async e => {
            const back = e.target.closest('.wq-solos-back');
            if (back) { renderSolosSummary(); return; }
            const card = e.target.closest('.wq-solos-card');
            if (card) { loadSolosDetail(card.dataset.rid); return; }
            const item = e.target.closest('.wq-research-item');
            if (item) {
                const s = +item.dataset.s, a = +item.dataset.a;
                if (s !== state.surah) await loadAyahOptions(s);
                await loadVerse(s, a);
                if (els.verseCard) els.verseCard.scrollIntoView({ behavior: 'smooth', block: 'start' });
            }
        });
    }

    /* ── render ───────────────────────────────────────────────── */
    /* ── segment audio (seek-and-stop in a reciter's surah mp3) ─────── */
    const audio = new Audio();
    audio.preload = 'none';
    let audioStopAt = null, playingBtn = null;
    function clearPlaying() {
        if (playingBtn) { const i = playingBtn.querySelector('i'); if (i) i.className = playingBtn.dataset.icon || 'fas fa-play'; playingBtn.classList.remove('wq-playing'); }
        playingBtn = null;
        document.querySelectorAll('.wq-guide-seg.wq-guide-active').forEach(el => el.classList.remove('wq-guide-active'));
    }
    // Play a guide-segment card (bounded) and highlight the card while it plays.
    function playGuideSeg(card, btn, url, absStart, absEnd) {
        const wasPlaying = playingBtn === btn && !audio.paused;
        playSegment(url, absStart, absEnd, btn);
        if (!wasPlaying && card) card.classList.add('wq-guide-active');
    }
    audio.addEventListener('timeupdate', () => {
        if (audioStopAt != null && audio.currentTime >= audioStopAt) { audio.pause(); audioStopAt = null; clearPlaying(); }
    });
    audio.addEventListener('ended', () => { audioStopAt = null; clearPlaying(); });
    function playSegment(url, absStart, absEnd, btn) {
        if (!url || absEnd <= absStart) return;
        if (playingBtn === btn && !audio.paused) { audio.pause(); audioStopAt = null; clearPlaying(); return; }
        clearPlaying();
        const begin = () => { try { audio.currentTime = absStart; } catch (e) {} audioStopAt = absEnd; audio.play().catch(() => {}); };
        playingBtn = btn;
        if (btn) { btn.classList.add('wq-playing'); const i = btn.querySelector('i'); if (i) { btn.dataset.icon = i.className; i.className = 'fas fa-pause'; } }
        if (audio.src !== url) { audio.src = url; audio.addEventListener('loadedmetadata', begin, { once: true }); audio.load(); }
        else begin();
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

    // Classify printed-mushaf marks into breath rules.
    function waqfCategories(d) {
        const lazim = new Set(), forbidden = new Set(), saktah = new Set(), positive = new Set();
        (d.mushafs || []).forEach(m => m.marks.forEach(mk => {
            if (mk.symbol === 'م') lazim.add(mk.wpos);
            else if (mk.symbol === 'لا') forbidden.add(mk.wpos);
            else if (mk.symbol === 'س') saktah.add(mk.wpos);
            if (['م', 'ج', 'ق', 'ص', 'ع'].includes(mk.symbol)) positive.add(mk.wpos);
        }));
        forbidden.forEach(w => { if (positive.has(w)) forbidden.delete(w); }); // a real stop elsewhere wins
        return { lazim, forbidden, saktah };
    }

    function render(d) {
        clearPlaying(); audio.pause();
        renderVerse(d);
        renderRecommendation(d);
        renderMatrix(d);
        renderReciters(d);
    }

    /* ── breath recommendation ─────────────────────────────────── */
    function cumAt(d, wpos) {
        const t = d.ref_times && d.ref_times[wpos];
        return (typeof t === 'number') ? t : 0;
    }
    // Breath plan: keep each breath ≤ L seconds, breathing only at attested
    // reciter stops — but ALWAYS stop at a وقف لازم (م, mandatory hard-cut),
    // and NEVER breathe at a سكتة (س, pause-without-breath) or a لا (no-stop).
    //
    // For short breath on long verses (e.g. 4:23, 72s), mushaf-backed stops
    // (where any mushaf has ص/ج/ق AND at least one reciter confirms) become
    // anchor points — giving the plan structure even when few reciters agree.
    //
    // Within each span between hard cuts, prefer stops with higher reciter
    // consensus + mushaf backing: score = consensus_ratio * 0.3 + mushaf * 0.2
    // + position_ratio * 0.5, so stops where reciters AND mushafs agree land
    // naturally on the strongest positions.
    function recommendBreaths(d, L) {
        const cats = waqfCategories(d);
        const lastW = d.words.length - 1;
        const total = d.reciters_total || 1;
        const majorityN = Math.floor(total / 2) + 1;

        // Effective breath count: forward stops + repeat from_wpos.
        // A reciter who pauses at word 10 and backs up to re-read BREATHED at
        // word 10 — that's a valid breathing point even though it's not a waqf.
        const breathCount = new Map();
        (d.union_stops || []).forEach(u => breathCount.set(u.wpos, u.count));
        (d.reciters || []).forEach(r => {
            (d.per_reciter[r.id].repeats || []).forEach(rp => {
                breathCount.set(rp.from_wpos, (breathCount.get(rp.from_wpos) || 0) + 1);
            });
        });

        // Mushaf marks at each wpos.
        const mushafAtWpos = new Set();
        (d.mushafs || []).forEach(m => m.marks.forEach(mk => {
            if (['م', 'ج', 'ق', 'ص', 'ع'].includes(mk.symbol)) mushafAtWpos.add(mk.wpos);
        }));

        // Mushaf-backed stops: any mushaf mark + at least one reciter breathes.
        const mushafBacked = new Set([...breathCount.keys()]
            .filter(w => mushafAtWpos.has(w) && w < lastW
                && !cats.lazim.has(w) && !cats.saktah.has(w) && !cats.forbidden.has(w)));

        // Consensus: majority of reciters breathe at this position (forward OR repeat).
        const consensusMandatory = (L >= BREATH.medium)
            ? new Set([...breathCount.entries()]
                .filter(([w, c]) => c >= majorityN && w < lastW
                    && !cats.lazim.has(w) && !cats.saktah.has(w) && !cats.forbidden.has(w))
                .map(([w]) => w))
            : new Set();

        // For short breath on long verses: mushaf-backed positions as anchors.
        const verseDur = d.ref_full || 0;
        const needAnchors = L < BREATH.medium && verseDur > L * 3;
        const anchors = needAnchors ? mushafBacked : new Set();

        const hardCuts = new Set([...cats.lazim, ...consensusMandatory, ...anchors]);
        const mandatory = [...hardCuts].filter(w => w < lastW).sort((a, b) => a - b);

        // All breathing positions (forward + repeat) as optional candidates.
        const optional = [...breathCount.keys()]
            .filter(w => w < lastW && !cats.saktah.has(w) && !cats.forbidden.has(w) && !hardCuts.has(w))
            .sort((a, b) => a - b);

        const breaths = [];
        let prevWpos = -1, prevCum = 0;
        for (const spanEnd of [...mandatory, lastW]) {
            const opts = optional.filter(w => w > prevWpos && w < spanEnd);
            let curCum = prevCum, i = 0;
            while (i < opts.length) {
                const remaining = cumAt(d, spanEnd) - curCum;
                if (remaining <= L) break;

                const cands = [];
                for (let j = i; j < opts.length; j++) {
                    const dur = cumAt(d, opts[j]) - curCum;
                    if (dur > L) break;
                    cands.push(j);
                }
                if (!cands.length) { breaths.push(opts[i]); curCum = cumAt(d, opts[i]); i += 1; continue; }

                let bestJ = cands[cands.length - 1], bestScore = -1;
                const maxDur = cumAt(d, opts[cands[cands.length - 1]]) - curCum;
                for (const j of cands) {
                    const dur = cumAt(d, opts[j]) - curCum;
                    const posRatio = maxDur > 0 ? dur / maxDur : 1;
                    const consRatio = (breathCount.get(opts[j]) || 1) / total;
                    const hasMushaf = mushafBacked.has(opts[j]) ? 1 : 0;
                    const score = consRatio * 0.3 + hasMushaf * 0.2 + posRatio * 0.5;
                    if (score > bestScore) { bestScore = score; bestJ = j; }
                }
                breaths.push(opts[bestJ]); curCum = cumAt(d, opts[bestJ]); i = bestJ + 1;
            }
            if (spanEnd !== lastW) breaths.push(spanEnd);
            prevWpos = spanEnd; prevCum = cumAt(d, spanEnd);
        }
        return { breaths, breathCount, mandatory: cats.lazim, consensusMandatory, mushafBacked: anchors, saktah: cats.saktah };
    }
    function renderRecommendation(d) {
        const canPlan = !!d.ref_times && d.words.length > 0;
        els.recCard.hidden = !canPlan;
        if (!canPlan) return;
        const L = state.breathL;
        const { breaths, breathCount, mandatory, consensusMandatory, mushafBacked, saktah } = recommendBreaths(d, L);
        const lastW = d.words.length - 1;
        const bounds = [-1, ...breaths, lastW];
        const nBreaths = bounds.length - 1;
        const ref = d.per_reciter[d.ref_reciter];

        const label = L <= BREATH.short ? 'قصير' : L >= BREATH.long ? 'طويل' : 'متوسط';
        let summary = `بنَفَس <b>${label}</b> (~${toAr(L)}ث للنفَس) تُقرأ الآية في `
            + `<b>${toAr(nBreaths)}</b> ${nBreaths === 1 ? 'نفَس واحد' : (nBreaths === 2 ? 'نفَسين' : 'أنفاس')}`
            + ` — قِف عند المواضع المُبيّنة.`;
        if (mandatory.size) summary += ` <span class="wq-must-note">يجب الوقف عند علامة اللزوم (م).</span>`;
        if (consensusMandatory.size) summary += ` <span class="wq-consensus-note">اتفق أغلب القرّاء على الوقف في مواضع، فاعتُمدت نقاط وقف ثابتة.</span>`;
        if (mushafBacked && mushafBacked.size) summary += ` <span class="wq-mushaf-note">استُخدمت علامات المصحف المطبوعة (ص/ج/ق) التي يؤكدها قارئ كنقاط وقف.</span>`;
        if (saktah.size) summary += ` <span class="wq-sakt-note">السكتة (س) ليست موضع تنفّس.</span>`;
        if (ref && ref.name_ar) {
            summary += `<br><span class="wq-ref-note" title="اخترنا قراءة هذا القارئ لأنه الأقرب لمتوسط زمن القرّاء وأقلّهم إعادات، فتُستخدم وتيرته لتقسيم الأنفاس بدقّة بصرف النظر عن طول النفَس المختار">`
                + `<i class="fas fa-circle-info"></i> الأزمنة مقاسة على قراءة <b>${ref.name_ar}</b>، وزر <i class="fas fa-play"></i> يشغّل من صوته</span>`;
        }
        els.recSummary.innerHTML = summary;

        // attestation + repeats from the reciters, keyed by word position
        const uByWpos = new Map((d.union_stops || []).map(u => [u.wpos, u]));
        const repeatsByWpos = new Map();   // from_wpos → [{name, to_wpos}]
        const repeatsByToWpos = new Map(); // to_wpos → [{name, from_wpos}]
        d.reciters.forEach(r => (d.per_reciter[r.id].repeats || []).forEach(rp => {
            if (!repeatsByWpos.has(rp.from_wpos)) repeatsByWpos.set(rp.from_wpos, []);
            repeatsByWpos.get(rp.from_wpos).push({ name: r.name_ar, to_wpos: rp.to_wpos });
            if (!repeatsByToWpos.has(rp.to_wpos)) repeatsByToWpos.set(rp.to_wpos, []);
            repeatsByToWpos.get(rp.to_wpos).push({ name: r.name_ar, from_wpos: rp.from_wpos });
        }));

        // If a breath segment's first word is also where some reciter's later
        // repeat resumes from (to_wpos), and that repeat's pause point
        // (from_wpos) falls within the SAME segment, show that word at the end
        // of the PREVIOUS segment too — its reading naturally continues from
        // there, and the "إعادة" marker later in this segment already starts
        // its re-read text from that same word (e.g. 59:2: «...مِّنَ ٱللَّهِ
        // فَأَتَىٰهُمُ» then «ٱللَّهُ ... يَحۡتَسِبُواْ ↩إعادة فَأَتَىٰهُمُ ...»).
        const leadInEnds = new Set();   // index k whose segment gains bounds[k+1]+1
        const consumedRepeats = new Set(); // "from-to" pairs already shown via duplication below
        for (let k = 0; k < bounds.length - 2; k++) {
            const to = bounds[k + 1], nextTo = bounds[k + 2];
            const cands = repeatsByToWpos.get(to + 1) || [];
            const hit = cands.filter(rp => rp.from_wpos <= nextTo);
            if (hit.length) {
                leadInEnds.add(k);
                // a true single-word self-repeat is fully represented by the
                // duplicated word at the start of the next segment below
                hit.filter(rp => rp.from_wpos === to + 1)
                    .forEach(rp => consumedRepeats.add(rp.from_wpos + '-' + (to + 1)));
            }
        }

        // If a segment's start is exactly where some reciter resumes after
        // backing up to the start of the PREVIOUS segment (i.e. they re-read
        // that whole segment before continuing), re-show the previous
        // segment's words, prefixed onto this one — same idea as above but
        // for a multi-word repeat spanning a full breath segment.
        const prependRanges = new Map(); // k -> [first_wpos, last_wpos] to re-show before this segment
        for (let k = 1; k < bounds.length - 1; k++) {
            const prevFrom = bounds[k - 1] + 1, prevTo = bounds[k];
            const hit = (repeatsByWpos.get(prevTo) || []).find(rp => rp.to_wpos === prevFrom);
            if (hit) {
                prependRanges.set(k, [prevFrom, prevTo]);
                consumedRepeats.add(prevTo + '-' + prevFrom);
            }
        }

        els.recPlan.innerHTML = '';
        for (let k = 0; k < bounds.length - 1; k++) {
            const from = bounds[k] + 1, to = bounds[k + 1];
            const fromDisp = from;
            const toDisp = leadInEnds.has(k) ? to + 1 : to;
            const segDur = cumAt(d, to) - (k === 0 ? 0 : cumAt(d, bounds[k]));
            const isLast = k === bounds.length - 2;
            const endsMandatory = !isLast && mandatory.has(to);
            const endsConsensus = !isLast && !endsMandatory && consensusMandatory.has(to);
            const endsMushaf = !isLast && !endsMandatory && !endsConsensus && mushafBacked && mushafBacked.has(to);
            const u = uByWpos.get(to);
            const line = document.createElement('div');
            line.className = 'wq-rec-line' + (segDur > L + 0.5 ? ' wq-rec-over' : '');

            const num = document.createElement('span');
            num.className = 'wq-rec-num'; num.textContent = toAr(k + 1);

            const play = document.createElement('button');
            play.className = 'wq-play'; play.type = 'button';
            play.title = 'استمع لهذا المقطع'; play.setAttribute('aria-label', 'استماع');
            play.innerHTML = '<i class="fas fa-play"></i>';
            if (ref && ref.audio_url) {
                const absStart = ref.verse_start + (from > 0 ? cumAt(d, from - 1) : 0);
                const absEnd = ref.verse_start + cumAt(d, to);
                play.addEventListener('click', () => playSegment(ref.audio_url, absStart, absEnd, play));
            } else play.disabled = true;

            const main = document.createElement('div');
            main.className = 'wq-rec-main';
            const words = document.createElement('span');
            words.className = 'wq-rec-words';

            // If some reciter backs up to re-read this whole segment's
            // natural lead-in (a multi-word repeat ending exactly where this
            // segment starts), show that re-read text first, dotted-underlined.
            const prepend = prependRanges.get(k);
            if (prepend) {
                const [pFrom, pTo] = prepend;
                for (let wi = pFrom; wi <= pTo; wi++) {
                    if (wi > pFrom) words.appendChild(document.createTextNode(' '));
                    const rs = document.createElement('span');
                    rs.className = 'wq-guide-w-repeat';
                    rs.textContent = d.words[wi] || '';
                    rs.title = 'يعيد بعض القرّاء قراءة هذا المقطع قبل الاستمرار';
                    words.appendChild(rs);
                }
                words.appendChild(document.createTextNode(' '));
            }

            // Any reciter repeats (pause → back up → re-read) that fall inside
            // this breath segment are shown IN PLACE, as part of the natural
            // recitation flow: a small "إعادة" marker followed by the re-read
            // words (dotted-underline, same style as the per-reciter cards) —
            // rather than attributing the repeat to a specific reciter's name.
            // Identical repeat spans from multiple reciters are merged into one.
            // Repeats already represented above (lead-in duplication / prepend)
            // are skipped here to avoid showing the same re-read text twice.
            const patterns = new Map();   // "to-from" → {from_wpos, to_wpos, names:[]}
            for (let w = fromDisp; w <= toDisp; w++) {
                (repeatsByWpos.get(w) || []).forEach(rp => {
                    if (consumedRepeats.has(rp.from_wpos + '-' + rp.to_wpos)) return;
                    const key = rp.to_wpos + '-' + w;
                    let p = patterns.get(key);
                    if (!p) { p = { from_wpos: w, to_wpos: rp.to_wpos, names: [] }; patterns.set(key, p); }
                    p.names.push(rp.name);
                });
            }
            const repeatsAt = new Map();  // from_wpos → [patterns]
            patterns.forEach(p => {
                if (!repeatsAt.has(p.from_wpos)) repeatsAt.set(p.from_wpos, []);
                repeatsAt.get(p.from_wpos).push(p);
            });

            // If the previous segment was extended to lead into this one (a
            // single-word self-repeat), this segment's first word repeats
            // that lead-in word — style it the same as other re-read text.
            const dupFirst = k > 0 && leadInEnds.has(k - 1);
            for (let wi = fromDisp; wi <= toDisp; wi++) {
                if (wi > fromDisp || prepend) words.appendChild(document.createTextNode(' '));
                if (wi === fromDisp && dupFirst) {
                    const rs = document.createElement('span');
                    rs.className = 'wq-guide-w-repeat';
                    rs.textContent = d.words[wi] || '';
                    rs.title = 'يعيد بعض القرّاء قراءة هذه الكلمة بعد الوقف';
                    words.appendChild(rs);
                } else {
                    words.appendChild(document.createTextNode(d.words[wi] || ''));
                }
                (repeatsAt.get(wi) || []).forEach(p => {
                    const mark = document.createElement('span');
                    mark.className = 'wq-rec-repeat-mark';
                    mark.innerHTML = '<i class="fas fa-rotate-left"></i> إعادة';
                    mark.title = `يعيد ${p.names.join('، ')} القراءة من «${d.words[p.to_wpos] || ''}»`;
                    words.append(' ', mark, ' ');
                    for (let rw = p.to_wpos; rw <= p.from_wpos; rw++) {
                        if (rw > p.to_wpos) words.appendChild(document.createTextNode(' '));
                        const rs = document.createElement('span');
                        rs.className = 'wq-guide-w-repeat';
                        rs.textContent = d.words[rw] || '';
                        words.appendChild(rs);
                    }
                });
            }
            main.appendChild(words);

            const meta = document.createElement('span');
            meta.className = 'wq-rec-meta';
            // a mandatory stop is always flagged (even when reciters also stop there);
            // otherwise show how many of the reciters actually stop at this point.
            let attest = '';
            if (!isLast) {
                if (endsMandatory) attest += '<span class="wq-must-badge">لازم</span>';
                else if (endsConsensus) attest += `<span class="wq-consensus-badge" title="اتفق أغلب القرّاء (${toAr(u ? u.count : 0)}/${toAr(d.reciters_total)}) على الوقف هنا، فاعتُمد نقطة وقف ثابتة بصرف النظر عن طول النفَس">وقف الأغلبية</span>`;
                else if (endsMushaf) attest += '<span class="wq-mushaf-badge" title="علامة وقف مطبوعة في المصحف يوافقها قارئ">يوافق مصحفًا</span>';
                const bc = breathCount.get(to) || (u ? u.count : 0);
                if (bc > 0) attest += `<span class="wq-rec-cons${bc === 1 ? ' wq-rec-cons-solo' : ''}" title="عدد القرّاء الذين يتنفّسون هنا (وقف أو إعادة)">${bc === 1 ? 'انفرد' : toAr(bc) + '/' + toAr(d.reciters_total)} <i class="fas fa-users"></i></span>`;
            }
            meta.innerHTML = attest
                + `<span class="wq-rec-dur"><i class="fas fa-${isLast ? 'flag-checkered' : 'lungs'}"></i> ${toAr(segDur.toFixed(1))}ث</span>`;

            line.append(num, play, main, meta);
            els.recPlan.appendChild(line);
        }
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
        flow.innerHTML = '';
        const uByWpos = new Map(d.union_stops.map(u => [u.wpos, u]));
        d.words.forEach((text, wpos) => {
            const w = document.createElement('span');
            w.className = 'wq-word';
            w.textContent = text;
            const u = uByWpos.get(wpos);
            if (u) w.classList.add('wq-word-stop');
            flow.appendChild(w);
            if (u) flow.appendChild(stopChip(u, d.reciters_total));
        });
    }

    function renderMatrix(d) {
        const mushafs = d.mushafs || [];
        // columns = union of reciter stops AND printed-mushaf waqf marks
        const posSet = new Set(d.union_stops.map(u => u.wpos));
        mushafs.forEach(m => m.marks.forEach(mk => posSet.add(mk.wpos)));
        const cols = [...posSet].sort((a, b) => a - b);
        els.matrixCard.hidden = cols.length === 0;
        if (!cols.length) { els.matrix.innerHTML = ''; renderMatrixLegend(d, []); return; }

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
                    body += `<td class="${strong}"><span class="wq-wsym waqf-uthmanic wq-w-${meta.cls}" title="${meta.name} — ${meta.desc}">${waqfGlyph(sym)}</span></td>`;
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
            const qasr = det.qasr_munfasil ? ' <span class="wq-qasr-mini" title="يقرأ بقصر المدّ المنفصل (حركتان) — قراءته أسرع">قصر</span>' : '';
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

        const symsHere = [...new Set(mushafs.flatMap(m => m.marks.map(mk => mk.symbol)))];
        const hasStrong = cols.some(isStrong);
        const hasOnMushaf = d.reciters.some(r => (d.per_reciter[r.id].stops || []).some(s => {
            const u = uByWpos.get(s.wpos); return u && u.solo && mushafMarked(s.wpos);
        }));
        renderMatrixLegend(d, symsHere, { strong: hasStrong, onMushaf: hasOnMushaf });
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
        ['المدينة', 'الشمرلي', 'الأزهر', 'قطر', 'الكويت'].forEach(id => {
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
        const hit = state.surahs.find(s => norm(s.name || '').includes(target));
        return hit ? (hit.number ?? null) : null;
    }
    async function doSearch() {
        const raw = els.search.value.trim();
        if (!raw) { hideSearchResults(); return; }
        const parsed = parseSearch(raw);
        if (parsed) {
            if (parsed.surah < 1 || parsed.surah > 114) { setStatus('رقم سورة غير صحيح', true); return; }
            hideSearchResults();
            await loadAyahOptions(parsed.surah);
            const max = state.ayahCount[parsed.surah] || 1;
            const ayah = Math.min(Math.max(1, parsed.ayah), max);
            await loadVerse(parsed.surah, ayah);
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
    function hideSearchResults() {
        if (!els.searchResults) return;
        els.searchResults.hidden = true;
        els.searchResults.innerHTML = '';
    }
    async function showWordResults(query) {
        if (!els.searchResults) return;
        els.searchResults.hidden = false;
        els.searchResults.innerHTML = '<div class="wq-search-loading">جارٍ البحث…</div>';
        try {
            const resp = await fetch(`/api/search?q=${encodeURIComponent(query)}&limit=8`);
            const data = await resp.json();
            const results = data.results || [];
            if (!results.length) {
                els.searchResults.innerHTML = '<div class="wq-search-empty">لا توجد نتائج لهذه الكلمات</div>';
                return;
            }
            els.searchResults.innerHTML = '';
            results.forEach(r => {
                const btn = document.createElement('button');
                btn.type = 'button';
                btn.className = 'wq-search-result';
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
                    await loadAyahOptions(r.surah_number);
                    await loadVerse(r.surah_number, r.ayah_number);
                });
                els.searchResults.appendChild(btn);
            });
        } catch (e) {
            els.searchResults.innerHTML = '<div class="wq-search-empty">تعذّر البحث الآن</div>';
        }
    }

    /* ── events ───────────────────────────────────────────────── */
    els.surah.addEventListener('change', async () => {
        const s = +els.surah.value;
        await loadAyahOptions(s);
        await loadVerse(s, 1);
    });
    els.ayah.addEventListener('change', () => loadVerse(+els.surah.value, +els.ayah.value));
    els.prev.addEventListener('click', () => { if (state.ayah > 1) loadVerse(state.surah, state.ayah - 1); });
    els.next.addEventListener('click', () => loadVerse(state.surah, state.ayah + 1));
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
            results.forEach(r => r.classList.remove('wq-sr-active'));
            results[idx].classList.add('wq-sr-active');
            results[idx].scrollIntoView({ block: 'nearest' });
        } else if (e.key === 'ArrowUp' && results.length) {
            e.preventDefault();
            let idx = results.findIndex(r => r.classList.contains('wq-sr-active'));
            idx = idx <= 0 ? results.length - 1 : idx - 1;
            results.forEach(r => r.classList.remove('wq-sr-active'));
            results[idx].classList.add('wq-sr-active');
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
        els.breathPicker.querySelectorAll('.wq-breath-btn').forEach(b => b.classList.toggle('wq-on', b === btn));
        if (state.data) renderRecommendation(state.data);
    });
    // matrix cell → play that reciter's segment up to the clicked stop
    if (els.matrix) els.matrix.addEventListener('click', e => {
        const cell = e.target.closest('.wq-cell-play');
        if (!cell || !state.data) return;
        playReciterStop(state.data, cell.dataset.rid, parseInt(cell.dataset.wpos, 10), cell);
    });

    /* ── init ─────────────────────────────────────────────────── */
    async function init() {
        initTheme();
        setupResearch();
        try {
            await loadSurahs();
            const p = new URLSearchParams(location.search);
            const surah = Math.min(Math.max(1, parseInt(p.get('surah'), 10) || 2), 114);
            await loadAyahOptions(surah);
            const ayah = Math.min(Math.max(1, parseInt(p.get('ayah'), 10) || (surah === 2 ? 255 : 1)),
                state.ayahCount[surah] || 1);
            await loadVerse(surah, ayah);
        } catch (e) {
            setStatus('تعذّر تهيئة الصفحة', true);
        }
    }
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
    else init();
})();
