/* ═══════════════════════════════════════════════════════════════════
   Mushaf Memorize — cumulative segmented memorization on a real Madinah
   mushaf, shown as a two-page spread with synced Husary recitation.

   Pick surah + ayah range + repetition settings → the spread opens on the
   real pages holding the selection → the target verses are highlighted in
   place → the schedule plays each verse (and, when enabled, splits long
   verses into phrases and links verses cumulatively), pulsing the verse
   being recited and flipping the spread as recitation crosses pages.

   Endpoints:
     GET /api/surahs
     GET /api/memorization/<s>?mode=&gap=     audio_url + per-verse [start,end] + phrases
     GET /api/digital-khatt/page(-by-ayah)/…  new Madinah (QPC v4) page
     GET /api/qpc-v1/page(-by-ayah)/…         old Madinah 1405 page
     GET /api/tajweed/<s>/<a>                  tajweed-annotated verse HTML
     GET /api/mushaf-versions                  waqf print list
   ═══════════════════════════════════════════════════════════════════ */
(function () {
    'use strict';

    const $ = id => document.getElementById(id);

    const els = {
        surah:       $('mz-surah'),
        from:        $('mz-from'),
        to:          $('mz-to'),
        verseReps:   $('mz-verse-reps'),
        linkReps:    $('mz-link-reps'),
        cumulative:  $('mz-cumulative'),
        splitLong:   $('mz-split-long'),
        splitMode:   $('mz-split-mode'),
        gap:         $('mz-gap'),
        gapVal:      $('mz-gap-val'),
        loop:        $('mz-loop'),
        reciter:     $('mz-reciter'),
        src:         $('mz-src'),
        layout:      $('mz-layout'),
        start:       $('mz-start'),
        status:      $('mz-status'),
        hint:        $('mz-hint'),
        stage:       $('mz-stage'),
        spread:      $('mz-spread'),
        sidebarToggle: $('mz-sidebar-toggle'),
        prev:        $('mz-prev'),
        next:        $('mz-next'),
        player:      $('mz-player'),
        play:        $('mz-play'),
        stop:        $('mz-stop'),
        prevStep:    $('mz-prev-step'),
        nextStep:    $('mz-next-step'),
        loopBtn:     $('mz-loop-btn'),
        now:         $('mz-now'),
        remaining:   $('mz-remaining'),
        playerReciter: $('mz-player-reciter'),
        timeCur:     $('mz-time-cur'),
        timeDur:     $('mz-time-dur'),
        progress:    $('mz-progress'),
        progressFill:$('mz-progress-fill'),
        audio:       $('mz-audio'),
        themeToggle: $('mz-theme-toggle'),
        hideToggle:  $('mz-hide-toggle'),
        hideBtn:     $('mz-hide-btn'),
        focusToggle: $('mz-focus-toggle'),
        reciteBtn:   $('mz-recite-btn'),
        asrNote:     $('mz-asr-note'),
        asrLive:     $('mz-asr-live'),
        asrLiveText: $('mz-asr-live-text'),
        tbLayout:    $('mz-tb-layout'),
        tbTajweed:   $('mz-tb-tajweed'),
        tbHide:      $('mz-tb-hide'),
        tbWaqf:      $('mz-tb-waqf'),
        volume:      $('mz-volume'),
        volBtn:      $('mz-vol-btn'),
        volIcon:     $('mz-vol-icon'),
        est:         $('mz-est'),
        tajweed:     $('mz-tajweed'),
        justify:     $('mz-justify'),
        justifyVal:  $('mz-justify-val'),
        waqfPills:   $('mz-waqf-pills'),
        // redesigned top-bar bits
        reciterTrigger: $('mz-reciter-trigger'),
        reciterPanel:   $('mz-reciter-panel'),
        reciterLabel:   $('mz-reciter-label'),
        repsBadge:      $('mz-reps-badge'),
        srcTrigger:     $('mz-src-trigger'),
        srcPanel:       $('mz-src-panel'),
        srcLabel:       $('mz-src-label'),
        picker:         $('mz-picker'),
        pickerBackdrop: $('mz-picker-backdrop'),
        pickerClose:    $('mz-picker-close'),
        pickerTitle:    $('mz-picker-title'),
        pickerSearch:   $('mz-picker-search'),
        pickerList:     $('mz-picker-list'),
    };

    // The two page panels of the spread (right = lower/odd page, left = higher).
    const cards = {
        right: { page: $('mz-page-r'), juz: $('mz-juz-r'), surah: $('mz-surah-r'), foot: $('mz-foot-r') },
        left:  { page: $('mz-page-l'), juz: $('mz-juz-l'), surah: $('mz-surah-l'), foot: $('mz-foot-l') },
    };

    const EPS = 0.05;
    const PAGE_MIN = 1, PAGE_MAX = 604;

    const state = {
        surahs: [],
        surah: 1,
        memo: null,
        verseByAyah: new Map(),
        selectedKeys: new Set(),
        spread: [null, null],   // [rightPage, leftPage] currently rendered
        focusPage: null,
        schedule: [],
        stepIdx: -1,
        monitorId: null,
        pendingSeek: false,
        playing: false,
        activeKey: null,
        stepVerses: [],         // verses overlapping the current step's [start,end]
        activeWords: [],        // flat {key,wpos,start,end} for word-by-word follow
        curWordId: '',          // currently lit word ("key#wpos") — avoids churn
        curFollowAyah: null,    // verse the audio is currently inside
        followFlipping: false,  // guard: one page-flip at a time while following
        rangeAnchor: null,      // first verse clicked while picking a range
        justify: 50,
        tajweedOn: false,
        tajweedCache: new Map(),
        src: 'digital_khatt',
        mushafVersions: [],
        gapMs: 250,
        splitModeVal: 'acoustic',
        layoutMode: 'dual',     // 'dual' | 'single'
        reciter: 'husary',
        reciterName: 'محمود خليل الحصري',
        hideText: false,
        focusMode: false,
    };

    /* ── Hide-for-testing + focus mode ─────────────────────────────── */
    function setHideMode(on) {
        state.hideText = !!on;
        pageEls().forEach(p => p && p.classList.toggle('mz-hide', state.hideText));
        document.body.classList.toggle('mz-picking', !state.hideText);  // pointer cursor for range-pick
        if (!state.hideText) wordsInSpread('.mz-word.mz-reveal').forEach(w => w.classList.remove('mz-reveal'));
        [els.hideToggle, els.hideBtn].forEach(b => { if (b) b.setAttribute('aria-pressed', String(state.hideText)); });
        if (els.hideBtn) {
            els.hideBtn.classList.toggle('mz-on', state.hideText);
            const lbl = els.hideBtn.querySelector('span:last-child');
            if (lbl) lbl.textContent = state.hideText ? 'إظهار النص' : 'إخفاء النص للتسميع';
        }
        if (els.hideToggle) els.hideToggle.querySelector('i').className = state.hideText ? 'fas fa-eye' : 'fas fa-eye-slash';
        syncToolbar();
    }
    function revealVerse(key) {
        if (!key) return;
        wordsInSpread(`.mz-word[data-key="${key}"]`).forEach(w => w.classList.add('mz-reveal'));
    }
    function setFocusMode(on) {
        state.focusMode = !!on;
        document.body.classList.toggle('mz-focus', state.focusMode);
        if (els.focusToggle) {
            els.focusToggle.setAttribute('aria-pressed', String(state.focusMode));
            els.focusToggle.querySelector('i').className = state.focusMode ? 'fas fa-compress' : 'fas fa-expand';
        }
        // sidebar gone/back → page size changes
        requestAnimationFrame(() => { if (state.focusPage) { sizePages(); applyFontSize(); justifyLines(); } });
    }
    function toggleLayout() {
        state.layoutMode = state.layoutMode === 'single' ? 'dual' : 'single';
        if (els.layout) els.layout.value = state.layoutMode;
        document.body.classList.toggle('mz-single', state.layoutMode === 'single');
        saveSetting('mz_layout', state.layoutMode);
        syncToolbar();
        if (state.focusPage) renderSpread(state.focusPage);
    }
    // keep the floating toolbar buttons in sync with current state
    function syncToolbar() {
        if (els.tbTajweed) els.tbTajweed.classList.toggle('mz-on', state.tajweedOn);
        if (els.tbHide) els.tbHide.classList.toggle('mz-on', state.hideText);
        if (els.tbLayout) {
            els.tbLayout.classList.toggle('mz-on', state.layoutMode === 'single');
            const i = els.tbLayout.querySelector('i');
            if (i) i.className = state.layoutMode === 'single' ? 'fas fa-book' : 'fas fa-book-open';
        }
    }

    const BASMALA_GLYPH = '\u00F3'; // QCF Basmala font: whole basmala in one glyph

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

    /* ── Waqf symbol normalization — ported from the main app so the memorize
       page renders the same glyphs in the same fonts. ─────────────────────── */
    const isWarshMushafVersion = v => /ورش|warsh/i.test((v || '').toString());
    function normalizeWarshWaqfText(raw) {
        if (!raw || !raw.trim()) return '';
        return raw.split(/[،,]/).map(t => t.trim()).filter(Boolean).map(t => {
            if (t === 'ر' || t === 'ۜ') return 'ۜ';
            if (t === 'ص' || t === 'ۖ') return 'ۖ';
            return '';
        }).filter(Boolean).join('');
    }
    const WAQF_GLYPH_MAP = {
        'م': 'ۘ', 'قلى': 'ۗ', 'قلي': 'ۗ', 'ق': 'ۗ', 'صلى': 'ۖ', 'صلي': 'ۖ', 'ص': 'ۖ',
        'ج': 'ۚ', 'لا': 'ۙ', 'ع': 'ۛ',
        'ۘ': 'ۘ', 'ۗ': 'ۗ', 'ۖ': 'ۖ', 'ۚ': 'ۚ', 'ۙ': 'ۙ', 'ۛ': 'ۛ', 'ۜ': 'ۜ',
        'ؕ': 'ؕ', 'ؗ': 'ؗ', 'ؔ': 'ؔ', '۪': '۪', '۫': '۫', '۬': '۬',
    };
    function normalizeNonWarshWaqfText(raw) {
        return raw.split(/[،,]/).map(t => t.replace(/\s+/g, '').trim()).filter(Boolean)
            .map(t => WAQF_GLYPH_MAP[t] || t).join('');
    }
    function getWaqfDisplayData(raw, version) {
        raw = (raw || '').toString().trim();
        if (!raw) return null;
        if (isWarshMushafVersion(version)) {
            const n = normalizeWarshWaqfText(raw);
            return n ? { text: n, extraClass: 'waqf-warsh' } : null;
        }
        const n = normalizeNonWarshWaqfText(raw);
        if (/^[↺▶]+$/.test(n)) return null; // recording cues, not waqf
        return { text: n, extraClass: '' };
    }

    /* ── Status / hint ─────────────────────────────────────────────── */
    let _statusTimer = 0;
    function setStatus(msg, isErr) {
        if (!els.status) return;
        els.status.textContent = msg || '';
        els.status.classList.toggle('mz-err', !!isErr);
        els.status.classList.toggle('mz-show', !!msg);
        clearTimeout(_statusTimer);
        if (msg) _statusTimer = setTimeout(() => els.status.classList.remove('mz-show'), isErr ? 4200 : 2200);
    }

    /* ── Theme (light / dark / sepia) ──────────────────────────────── */
    const THEMES = ['light', 'dark', 'sepia'];
    function applyTheme(theme) {
        document.body.classList.toggle('mz-dark', theme === 'dark');
        document.body.classList.toggle('mz-sepia', theme === 'sepia');
        syncThemeIcon(theme);
    }
    function currentTheme() {
        if (document.body.classList.contains('mz-dark')) return 'dark';
        if (document.body.classList.contains('mz-sepia')) return 'sepia';
        return 'light';
    }
    function initTheme() {
        let saved = localStorage.getItem('quranApp_theme');
        if (!THEMES.includes(saved)) {
            saved = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
        }
        applyTheme(saved);
        els.themeToggle.addEventListener('click', () => {
            const next = THEMES[(THEMES.indexOf(currentTheme()) + 1) % THEMES.length];
            applyTheme(next);
            localStorage.setItem('quranApp_theme', next);
        });
    }
    function syncThemeIcon(theme) {
        const icon  = { light: 'fas fa-moon', dark: 'fas fa-sun', sepia: 'fas fa-leaf' }[theme] || 'fas fa-moon';
        const title = { light: 'الوضع الليلي', dark: 'الوضع البُنّي', sepia: 'الوضع النهاري' }[theme] || '';
        els.themeToggle.querySelector('i').className = icon;
        els.themeToggle.title = title;
    }

    const saveSetting = (k, v) => localStorage.setItem(k, String(v));

    function loadSettings() {
        const rawJ = parseInt(localStorage.getItem('quranApp_khattJustify') ?? '50', 10);
        state.justify = Number.isFinite(rawJ) ? Math.max(0, Math.min(100, rawJ)) : 50;
        els.justify.value = state.justify;
        updateJustifyLabel();

        state.tajweedOn = localStorage.getItem('quranApp_tajweedEnabled') === 'true';
        syncTajweedButton();

        const savedSrc = localStorage.getItem('mz_src');
        if (savedSrc === 'qpc_v1' || savedSrc === 'digital_khatt' || savedSrc === 'shamarly') {
            state.src = savedSrc;
        } else {
            const mainFont = localStorage.getItem('quranApp_font');
            if (mainFont === 'old_madina') state.src = 'qpc_v1';
            else if (mainFont === 'digital_khatt') state.src = 'digital_khatt';
        }
        els.src.value = state.src;
        applySrcClass();

        const savedLayout = localStorage.getItem('mz_layout');
        state.layoutMode = savedLayout === 'single' ? 'single' : 'dual';
        els.layout.value = state.layoutMode;
        document.body.classList.toggle('mz-single', state.layoutMode === 'single');

        syncToolbar();

        try {
            const saved = JSON.parse(localStorage.getItem('quranApp_mushafVersions') || '[]');
            if (Array.isArray(saved)) state.mushafVersions = saved.filter(v => typeof v === 'string');
        } catch (e) { state.mushafVersions = []; }
        _waqfVisible = !!(localStorage.getItem('quranApp_waqfVisible') ?? (state.mushafVersions.includes('المدينة') ? '1' : ''));
    }

    /* ── Waqf mushaf-version pills ─────────────────────────────────── */
    async function loadWaqfPills() {
        if (!els.waqfPills) return;
        let versions = [];
        try {
            const resp = await fetch('/api/mushaf-versions');
            if (resp.ok) versions = await resp.json();
        } catch (e) { versions = []; }
        state.mushafVersions = state.mushafVersions.filter(v => versions.includes(v));
        if (els.tbWaqf) els.tbWaqf.checked = waqfMarksOn();
        els.waqfPills.innerHTML = '';
        versions.forEach(v => {
            const btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'mz-waqf-pill';
            btn.textContent = v;
            btn.classList.toggle('mz-on', state.mushafVersions.includes(v));
            btn.addEventListener('click', () => toggleWaqfVersion(v, btn));
            els.waqfPills.appendChild(btn);
        });
    }
    function toggleWaqfVersion(version, btn) {
        const i = state.mushafVersions.indexOf(version);
        if (i >= 0) state.mushafVersions.splice(i, 1);
        else state.mushafVersions.push(version);
        btn.classList.toggle('mz-on', state.mushafVersions.includes(version));
        saveSetting('quranApp_mushafVersions', JSON.stringify(state.mushafVersions));
        if (state.focusPage) renderSpread(state.focusPage);
    }

    // Simple on/off for the current mushaf's printed waqf marks (مصحف المدينة —
    // applies to المدينة الجديد / المدينة ١٤٠٥ / Digital Khatt). Backed by the
    // mushaf-version overlay: showing = "المدينة" is in the active versions.
    let _waqfVisible = false;
    const waqfMarksOn = () => _waqfVisible;
    function setWaqfMarks(on) {
        _waqfVisible = !!on;
        saveSetting('quranApp_waqfVisible', _waqfVisible ? '1' : '');
        if (els.tbWaqf) els.tbWaqf.checked = _waqfVisible;
        // For non-Shemrly: toggle CSS visibility of embedded waqf chars (no re-fetch).
        // For Shemrly: re-render to fetch/drop DB overlay.
        if (state.src === 'shamarly') {
            const i = state.mushafVersions.indexOf('الشمرلي');
            if (on && i < 0) state.mushafVersions.push('الشمرلي');
            else if (!on && i >= 0) state.mushafVersions.splice(i, 1);
            if (state.focusPage) renderSpread(state.focusPage);
        } else {
            document.querySelectorAll('.mz-page').forEach(p => p.classList.toggle('mz-waqf-on', _waqfVisible));
        }
    }

    /* ── Arabic-Indic digits + juz ─────────────────────────────────── */
    const toAr = n => String(n).replace(/[0-9]/g, d => '٠١٢٣٤٥٦٧٨٩'[d]);

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
    const juzLabel = pageNumber => `الجزء ${JUZ_NAME[juzNumber(pageNumber) - 1]}`;
    // QCF Common font: each juz NAME is one glyph at U+E000+juz (E01E = الجزء الثلاثون).
    const juzGlyph = j => (j >= 1 && j <= 30) ? String.fromCodePoint(0xE000 + j) : '';

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

    const ARABIC_DIGITS_ONLY = /^[٠-٩]+$/;
    const withAyahOrnament = text => ARABIC_DIGITS_ONLY.test(text) ? '۝' + text : text;

    // The Digital Khatt / QPC-v1 source text embeds مصحف المدينة's printed waqf
    // mark as a combining character (U+06D6–U+06DC: ۖۗۘۙۚۛۜ) on whichever word
    // carries it. We keep these in the text and control visibility via CSS class
    // mz-waqf-on on the page container — no DB overlay needed.
    const EMBEDDED_WAQF_RE = /[ۖ-ۜ]/g;
    const stripEmbeddedWaqf = text => text.replace(EMBEDDED_WAQF_RE, '');

    const updateJustifyLabel = () => { els.justifyVal.textContent = toAr(state.justify) + '٪'; };

    /* ── Surah list + per-surah memo ───────────────────────────────── */
    async function loadSurahs() {
        const resp = await fetch('/api/surahs');
        const data = await resp.json();
        state.surahs = Array.isArray(data) ? data : [];
        els.surah.innerHTML = state.surahs.map(s => {
            const num = s.number ?? s, name = s.name ?? `سورة ${num}`;
            return `<option value="${num}">${toAr(num)}. ${name}</option>`;
        }).join('');
    }

    function memoQuery() {
        return `?reciter=${encodeURIComponent(state.reciter)}&mode=${state.splitModeVal}&gap=${state.gapMs}`;
    }

    /* ── Reciters ──────────────────────────────────────────────────── */
    async function loadReciters() {
        if (!els.reciter) return;
        let list = [];
        try {
            const resp = await fetch('/api/memorization-reciters');
            if (resp.ok) list = await resp.json();
        } catch (e) { list = []; }
        if (!list.length) list = [{ id: 'husary', name_ar: 'محمود خليل الحصري' }];
        const saved = localStorage.getItem('quranApp_memoReciter');
        if (list.some(r => r.id === saved)) state.reciter = saved;
        else if (!list.some(r => r.id === state.reciter)) state.reciter = list[0].id;
        els.reciter.innerHTML = list.map(r => `<option value="${r.id}">${r.name_ar || r.name_en || r.id}</option>`).join('');
        els.reciter.value = state.reciter;
        const cur = list.find(r => r.id === state.reciter);
        if (cur) state.reciterName = cur.name_ar || cur.name_en || state.reciter;
    }

    // ── YouTube IFrame Audio Adapter ─────────────────────────────────────────
    // Wraps the YouTube IFrame Player API to expose the same interface as
    // HTMLAudioElement so all seek/play/pause/currentTime logic works unchanged.
    // Used automatically when audio_url is a youtube.com watch URL.

    function extractYoutubeId(url) {
        if (!url) return null;
        const m = url.match(/[?&]v=([A-Za-z0-9_-]{11})/) || url.match(/youtu\.be\/([A-Za-z0-9_-]{11})/);
        return m ? m[1] : null;
    }

    class YTAudioAdapter {
        constructor(videoId) {
            this._videoId = videoId;
            this._ready = false;
            this._pendingSeeked = false;
            this._listeners = {};
            // Invisible off-screen container. YouTube requires minimum ~200×200;
            // a 1×1 or zero-size player silently refuses to initialize.
            this._div = document.createElement('div');
            this._div.style.cssText = 'position:fixed;left:-9999px;top:-9999px;width:320px;height:180px;pointer-events:none;z-index:-1;';
            document.body.appendChild(this._div);
            this._loadAPI();
        }

        _loadAPI() {
            if (window.YT && window.YT.Player) {
                this._createPlayer();
            } else {
                if (!document.getElementById('yt-iframe-api')) {
                    const s = document.createElement('script');
                    s.id = 'yt-iframe-api';
                    s.src = 'https://www.youtube.com/iframe_api';
                    document.head.appendChild(s);
                }
                const prev = window.onYouTubeIframeAPIReady;
                window.onYouTubeIframeAPIReady = () => {
                    if (typeof prev === 'function') prev();
                    this._createPlayer();
                };
            }
        }

        _createPlayer() {
            this._player = new YT.Player(this._div, {
                width: 320,
                height: 180,
                videoId: this._videoId,
                playerVars: { autoplay: 0, controls: 0, disablekb: 1, fs: 0, rel: 0, playsinline: 1 },
                events: {
                    onReady: () => {
                        this._ready = true;
                        if (this._vol != null) this.volume = this._vol;  // apply pending volume
                        this._dispatch('loadedmetadata');
                    },
                    onStateChange: e => {
                        if (e.data === YT.PlayerState.ENDED) {
                            this._dispatch('ended');
                        }
                        // Fire 'seeked' as soon as playback resumes or pauses at
                        // the new position — covers both seek-then-play and
                        // seek-while-paused cases.
                        if (this._pendingSeeked &&
                            (e.data === YT.PlayerState.PLAYING ||
                             e.data === YT.PlayerState.PAUSED)) {
                            this._pendingSeeked = false;
                            this._dispatch('seeked');
                        }
                    },
                    onError: e => console.warn('YT player error code:', e.data),
                },
            });
        }

        _dispatch(event) {
            (this._listeners[event] || []).forEach(cb => { try { cb({ type: event }); } catch (e) {} });
        }

        addEventListener(event, callback, opts) {
            if (!this._listeners[event]) this._listeners[event] = [];
            if (opts && opts.once) {
                const wrapped = (ev) => {
                    callback(ev);
                    this._listeners[event] = (this._listeners[event] || []).filter(f => f !== wrapped);
                };
                this._listeners[event].push(wrapped);
                // If already ready and caller is waiting for loadedmetadata, fire immediately.
                if (event === 'loadedmetadata' && this._ready) setTimeout(() => this._dispatch('loadedmetadata'), 0);
            } else {
                this._listeners[event].push(callback);
            }
        }

        removeEventListener(event, callback) {
            if (this._listeners[event])
                this._listeners[event] = this._listeners[event].filter(f => f !== callback);
        }

        get src() { return this._videoId ? `https://www.youtube.com/watch?v=${this._videoId}` : ''; }
        set src(url) {
            const vid = extractYoutubeId(url);
            if (!vid || vid === this._videoId) return;
            this._videoId = vid;
            this._ready = false;
            if (this._player && typeof this._player.loadVideoById === 'function')
                this._player.loadVideoById({ videoId: vid, startSeconds: 0 });
        }
        load() {} // no-op; YT player loads when the IFrame is created

        get currentTime() {
            if (!this._player || !this._ready) return 0;
            try { return this._player.getCurrentTime() || 0; } catch (e) { return 0; }
        }
        set currentTime(t) {
            if (!this._player || !this._ready) return;
            this._pendingSeeked = true;
            try { this._player.seekTo(t, true); } catch (e) {}
            // Fallback: fire 'seeked' after 500 ms in case state-change never fires
            // (e.g. seek happens while the player is already at the right state).
            setTimeout(() => {
                if (this._pendingSeeked) { this._pendingSeeked = false; this._dispatch('seeked'); }
            }, 500);
        }

        get paused() {
            if (!this._player || !this._ready) return true;
            try { return this._player.getPlayerState() !== YT.PlayerState.PLAYING; } catch (e) { return true; }
        }
        get readyState() { return this._ready ? 4 : 0; }

        play() {
            return new Promise(resolve => {
                const doPlay = () => { try { this._player.playVideo(); } catch (e) {} resolve(); };
                if (this._ready) doPlay();
                else this.addEventListener('loadedmetadata', () => doPlay(), { once: true });
            });
        }
        pause() { if (this._player && this._ready) try { this._player.pauseVideo(); } catch (e) {} }

        get volume() {
            if (this._player && this._ready) { try { return (this._player.getVolume() || 0) / 100; } catch (e) {} }
            return this._vol != null ? this._vol : 1;
        }
        set volume(v) {
            this._vol = v;
            if (this._player && this._ready) {
                try { this._player.setVolume(Math.round(v * 100)); if (v > 0) this._player.unMute(); else this._player.mute(); } catch (e) {}
            }
        }

        destroy() {
            try { if (this._player && this._player.destroy) this._player.destroy(); } catch (e) {}
            if (this._div && this._div.parentNode) this._div.parentNode.removeChild(this._div);
            this._listeners = {};
        }
    }

    // Named audio event callbacks so they can be re-attached to a fresh adapter
    // whenever the reciter switches between native-MP3 and YouTube backends.
    function _onAudioSeeked() { state.pendingSeek = false; }
    function _onAudioEnded() { if (state.stepIdx >= 0 && state.stepIdx < state.schedule.length) advanceStep(); }
    function attachAudioEvents(obj) {
        obj.addEventListener('seeked', _onAudioSeeked);
        obj.addEventListener('ended', _onAudioEnded);
    }

    // Keep a reference to the original <audio> element so we can restore it
    // when switching away from a YouTube reciter back to an MP3 reciter.
    const _nativeAudio = $('mz-audio');

    async function loadSurahMemo(surah) {
        setStatus('جارٍ تحميل بيانات السورة…');
        const resp = await fetch(`/api/memorization/${surah}${memoQuery()}`);
        if (!resp.ok) throw new Error('memo load failed');
        const data = await resp.json();
        state.memo = data;
        state.surah = surah;
        if (data.reciter_name_ar) state.reciterName = data.reciter_name_ar;
        if (els.playerReciter) els.playerReciter.textContent = state.reciterName;
        if (els.reciterLabel) els.reciterLabel.textContent = state.reciterName;
        state.verseByAyah = new Map(data.verses.map(v => [v.ayah, v]));

        const opts = data.verses.map(v => `<option value="${v.ayah}">${toAr(v.ayah)}</option>`).join('');
        els.from.innerHTML = opts;
        els.to.innerHTML   = opts;

        const saved = localStorage.getItem('mz_last_pos');
        if (saved) {
            const [savedSurah, savedFrom] = saved.split(':').map(Number);
            els.from.value = (savedSurah === surah && data.verses.some(v => v.ayah === savedFrom))
                ? String(savedFrom) : String(data.verses[0].ayah);
        } else {
            els.from.value = String(data.verses[0].ayah);
        }
        autoSetTo(parseInt(els.from.value, 10), data.verses);

        // Swap audio backend: use YouTube IFrame adapter for youtube.com URLs,
        // native <audio> for everything else (MP3 streams).
        const _ytId = extractYoutubeId(data.audio_url);
        if (_ytId) {
            if (els.audio !== _nativeAudio && typeof els.audio.destroy === 'function') els.audio.destroy();
            els.audio = new YTAudioAdapter(_ytId);
            attachAudioEvents(els.audio);
        } else {
            if (els.audio !== _nativeAudio && typeof els.audio.destroy === 'function') els.audio.destroy();
            els.audio = _nativeAudio;
            els.audio.src = data.audio_url;
            els.audio.load();
        }
        setVolume(state.volume != null ? state.volume : 1);  // carry volume across backends
        updateHint();
        setStatus('');
    }

    // Reload segment boundaries when split mode/sensitivity changes (same surah/audio).
    async function reloadMemoBoundaries() {
        if (!state.memo) return;
        try {
            const resp = await fetch(`/api/memorization/${state.surah}${memoQuery()}`);
            if (!resp.ok) return;
            const data = await resp.json();
            state.memo = data;
            state.verseByAyah = new Map(data.verses.map(v => [v.ayah, v]));
            updateHint();
        } catch (e) { /* keep previous boundaries */ }
    }

    const DEFAULT_RANGE = 4;
    function autoSetTo(fromAyah, verses) {
        const toVal = parseInt(els.to.value, 10);
        if (toVal >= fromAyah) return;
        const list = verses || [...state.verseByAyah.values()].sort((a, b) => a.ayah - b.ayah);
        const target = fromAyah + DEFAULT_RANGE;
        const best = list.map(v => v.ayah).filter(a => a >= fromAyah)
            .reduce((acc, a) => (a <= target ? a : acc), fromAyah);
        els.to.value = String(best);
    }

    function selectedAyahRange() {
        let a = parseInt(els.from.value, 10), b = parseInt(els.to.value, 10);
        if (!Number.isFinite(a)) a = 1;
        if (!Number.isFinite(b)) b = a;
        if (b < a) { const t = a; a = b; b = t; }
        return [a, b];
    }
    function selectedVerses() {
        const [a, b] = selectedAyahRange();
        const out = [];
        for (let k = a; k <= b; k++) { const v = state.verseByAyah.get(k); if (v) out.push(v); }
        return out;
    }
    function rebuildSelectedKeys() {
        const [a, b] = selectedAyahRange();
        state.selectedKeys = new Set();
        for (let k = a; k <= b; k++) state.selectedKeys.add(`${state.surah}:${k}`);
    }

    // Live feedback on how the current split settings divide the selection.
    function updateHint() {
        updateEstimate();
        if (!els.hint) return;
        if (!state.memo || !els.splitLong.checked) { els.hint.textContent = ''; return; }
        let splitVerses = 0, totalPhrases = 0;
        selectedVerses().forEach(v => {
            if ((v.phrases || []).length > 1) { splitVerses++; totalPhrases += v.phrases.length; }
        });
        els.hint.textContent = splitVerses
            ? `سيُقسَّم ${toAr(splitVerses)} ${splitVerses === 1 ? 'آية' : 'آيات'} حسب الوقف إلى ${toAr(totalPhrases)} مقطعًا`
            : '';
    }

    /* ── Volume ───────────────────────────────────────────────────── */
    function setVolume(v) {
        v = Math.max(0, Math.min(1, isFinite(v) ? v : 1));
        state.volume = v;
        try { els.audio.volume = v; } catch (e) {}
        if (els.volIcon) els.volIcon.className = v === 0 ? 'fas fa-volume-xmark' : v < 0.5 ? 'fas fa-volume-low' : 'fas fa-volume-high';
        if (els.volume && Math.round(+els.volume.value) !== Math.round(v * 100)) els.volume.value = String(Math.round(v * 100));
    }
    function setupVolume() {
        if (state.volume == null) state.volume = 1;
        if (els.volume) els.volume.addEventListener('input', () => setVolume((+els.volume.value || 0) / 100));
        if (els.volBtn) els.volBtn.addEventListener('click', () => setVolume(state.volume > 0 ? 0 : 1));
        setVolume(state.volume);
    }

    /* ── Expected session duration ─────────────────────────────────── */
    const STEP_GAP = 0.4;  // small transition/breath pad added per step, so the
                           // estimate is closer to real wall-clock time
    const stepSec = s => Math.max(0, s.end - s.start) + STEP_GAP;
    function fmtDur(sec) {
        sec = Math.round(sec);
        const m = Math.floor(sec / 60), s = sec % 60;
        if (m && s) return `${toAr(m)} د ${toAr(s)} ث`;
        if (m) return `${toAr(m)} دقيقة`;
        return `${toAr(s)} ثانية`;
    }
    function updateEstimate() {
        if (!els.est) return;
        let sec = 0;
        try { if (state.memo) buildSchedule().forEach(s => { sec += stepSec(s); }); } catch (e) { sec = 0; }
        els.est.innerHTML = sec ? `<i class="fas fa-clock"></i> المدة المتوقعة للجلسة: <b>${fmtDur(sec)}</b>` : '';
    }

    /* ── Mushaf source ─────────────────────────────────────────────── */
    function applySrcClass() {
        [cards.right.page, cards.left.page].forEach(p => {
            if (!p) return;
            p.classList.toggle('mz-src-qpc-v1', state.src === 'qpc_v1');
            p.classList.toggle('mz-src-digital-khatt', state.src === 'digital_khatt');
            p.classList.toggle('mz-src-shamarly', state.src === 'shamarly');
            p.classList.toggle('mz-tajweed', state.tajweedOn && state.src !== 'shamarly');
        });
    }
    const pageApiBase = () => state.src === 'qpc_v1' ? '/api/qpc-v1'
        : state.src === 'shamarly' ? '/api/shamarly' : '/api/digital-khatt';

    /* ── الشمرلي (Shemrly) page-local fonts ────────────────────────────
       Shemrly is a page-image mushaf: each page has its own font whose glyphs
       draw the words exactly as printed. Only the pages we ship a font for can
       render; the API tags others 'legacy-word-position' and we show a note.
       Each word's glyph is page-local, so a card's font = that page's font. */
    const SHEMRLY_PAGES = [2, 3, 333, 444, 460, 461, 462, 463, 464, 465, 466, 467, 468, 469, 470, 497, 500];
    const SHEMRLY_PAGE_SET = new Set(SHEMRLY_PAGES);
    const _shemrlyFontPromises = new Map();
    function ensureShemrlyFont(fontName) {
        if (!fontName || !window.FontFace) return Promise.resolve();
        if (_shemrlyFontPromises.has(fontName)) return _shemrlyFontPromises.get(fontName);
        const ff = new FontFace(fontName, `url("/static/fonts/${fontName}.ttf")`);
        const p = ff.load().then(f => document.fonts.add(f)).catch(() => {});
        _shemrlyFontPromises.set(fontName, p);
        return p;
    }
    const nearestShemrlyPage = (page) =>
        SHEMRLY_PAGES.reduce((best, p) => Math.abs(p - page) < Math.abs(best - page) ? p : best, SHEMRLY_PAGES[0]);
    function waqfQuery() {
        // Non-Shemrly sources use embedded waqf chars from QPC text (no DB needed).
        // Shemrly needs its own DB overlay since the font renders its own marks.
        if (state.src !== 'shamarly') return '';
        let versions = state.mushafVersions.slice();
        if (!versions.includes('الشمرلي')) versions.unshift('الشمرلي');
        if (!versions.length) return '';
        return '?' + versions.map(v => 'mushaf_version=' + encodeURIComponent(v)).join('&');
    }
    async function fetchPageByAyah(surah, ayah) {
        const resp = await fetch(`${pageApiBase()}/page-by-ayah/${surah}/${ayah}${waqfQuery()}`);
        if (!resp.ok) throw new Error('page load failed');
        return resp.json();
    }
    async function fetchPageByNumber(pageNumber) {
        const resp = await fetch(`${pageApiBase()}/page/${pageNumber}${waqfQuery()}`);
        if (!resp.ok) throw new Error('page load failed');
        return resp.json();
    }

    /* ── Waqf marks renderer (same structure/fonts/colours as the main page) ─ */
    function appendWaqfMarks(span, entries) {
        if (!Array.isArray(entries) || !entries.length) return;
        const stack = document.createElement('span');
        stack.className = 'waqf-stack';
        entries.forEach(e => {
            const version = (e && e.version) || '';
            const data = getWaqfDisplayData(e && e.symbols, version);
            if (!data) return;
            const isHindi = version === 'الهندي';
            const symbols = [...data.text].filter(ch => {
                if (!ch.trim()) return false;
                if (isHindi) {
                    const cp = ch.codePointAt(0);
                    if (ch === '۟' || ch === 'ۜ') return false;
                    if (cp >= 0xE000 && cp <= 0xF8FF) return false;
                }
                return true;
            });
            if (!symbols.length) return;
            const cls = 'waqf-symbol' + (data.extraClass ? ' ' + data.extraClass : '');
            symbols.forEach(sym => {
                const s = document.createElement('span');
                s.className = cls;
                if (version) { s.dataset.version = version; s.title = `مصحف: ${version}`; }
                s.textContent = sym;
                if (isHindi) {
                    let g = stack.querySelector(':scope > .waqf-hindi-group');
                    if (!g) { g = document.createElement('span'); g.className = 'waqf-hindi-group'; stack.appendChild(g); }
                    g.appendChild(s);
                } else stack.appendChild(s);
            });
        });
        if (stack.childNodes.length) span.appendChild(stack);
    }

    /* ── Render one page into a card ───────────────────────────────── */
    function renderCard(card, payload) {
        const pageEl = card.page;
        if (!payload) {
            pageEl.innerHTML = '<div class="mz-page-empty"><i class="fas fa-book-quran"></i></div>';
            card.juz.textContent = '';
            card.surah.textContent = '';
            card.foot.textContent = '';
            pageEl.classList.remove('mz-has-page');
            return;
        }
        // Shemrly renders only on pages we ship a font for; the API marks the rest
        // 'legacy-word-position' (glyphs we can't draw) — show a friendly note instead.
        if (state.src === 'shamarly' && payload.glyph_mapping_mode !== 'shemrly-page-local') {
            pageEl.classList.remove('mz-has-page');
            pageEl.style.removeProperty('font-family');
            pageEl.innerHTML = '<div class="mz-page-empty mz-page-na"><i class="fas fa-circle-info"></i>'
                + '<span>هذه الصفحة غير متوفرة بخط الشمرلي بعد</span></div>';
            card.juz.textContent = ''; card.surah.textContent = '';
            card.foot.textContent = toAr(payload.page_number || '');
            return;
        }
        // Page-local Shemrly font: every word on this page draws with it.
        if (state.src === 'shamarly' && payload.font_name) pageEl.style.fontFamily = `"${payload.font_name}", serif`;
        else pageEl.style.removeProperty('font-family');

        pageEl.classList.add('mz-has-page');
        pageEl.classList.toggle('mz-waqf-on', waqfMarksOn());
        const ayahWPos = new Map();
        const frag = document.createDocumentFragment();

        (payload.lines || []).forEach(line => {
            const lineEl = document.createElement('div');
            lineEl.className = 'mz-line';
            const type = line.line_type;
            if (type === 'surah_name') {
                const inner = document.createElement('div');
                inner.className = 'mz-line-surah';
                const glyph = surahHeaderGlyph(line.surah_number);
                if (glyph) { inner.classList.add('mz-surah-glyph'); inner.textContent = glyph; inner.setAttribute('aria-label', line.display_text || ''); }
                else inner.textContent = line.display_text || '';
                lineEl.appendChild(inner);
            } else if (type === 'basmallah') {
                const inner = document.createElement('div');
                inner.className = 'mz-line-basmala mz-basmala-glyph';
                inner.textContent = BASMALA_GLYPH;
                inner.setAttribute('aria-label', line.display_text || 'بسم الله الرحمن الرحيم');
                lineEl.appendChild(inner);
            } else {
                const inner = document.createElement('div');
                inner.className = 'mz-line-inner';
                const words = line.words || [];
                if (words.length) {
                    words.forEach((w, i) => {
                        const span = document.createElement('span');
                        span.className = 'mz-word';
                        // Shemrly glyphs already include the printed ayah marker; only the
                        // letter-based sources need the ۝ ornament appended.
                        const raw = w.text || '';
                        if (state.src === 'shamarly') {
                            span.textContent = raw;
                        } else {
                            const processed = withAyahOrnament(raw);
                            let last = 0;
                            for (const m of processed.matchAll(/[ۖ-ۜ]/g)) {
                                if (m.index > last) span.appendChild(document.createTextNode(processed.slice(last, m.index)));
                                const wm = document.createElement('span');
                                wm.className = 'mz-waqf-char';
                                wm.textContent = m[0];
                                span.appendChild(wm);
                                last = m.index + m[0].length;
                            }
                            if (last < processed.length) span.appendChild(document.createTextNode(processed.slice(last)));
                            if (last === 0) span.textContent = processed;
                        }
                        const text = span.textContent;
                        span.dataset.text = text;
                        if (w.surah != null && w.ayah != null) {
                            const key = `${w.surah}:${w.ayah}`;
                            span.dataset.key = key;
                            const pos = ayahWPos.get(key) ?? 0;
                            span.dataset.wpos = String(pos);
                            ayahWPos.set(key, pos + 1);
                        }
                        if (state.src === 'shamarly') {
                            span._waqf = w.waqf_symbols;
                            appendWaqfMarks(span, w.waqf_symbols);
                        }
                        inner.appendChild(span);
                        if (i < words.length - 1) inner.appendChild(document.createTextNode(' '));
                    });
                    lineEl.dataset.justify = (!line.is_centered) ? '1' : '0';
                } else {
                    inner.textContent = line.display_text || '';
                }
                lineEl.appendChild(inner);
            }
            frag.appendChild(lineEl);
        });

        pageEl.innerHTML = '';
        pageEl.appendChild(frag);

        // Running head: every surah on the page (left) + juz (right) + page number.
        const seen = new Set();
        const surahsOnPage = [];
        (payload.lines || []).forEach(l => {
            (l.words || []).forEach(w => { if (w.surah != null && !seen.has(w.surah)) { seen.add(w.surah); surahsOnPage.push(w.surah); } });
            if (l.line_type === 'surah_name' && l.surah_number != null && !seen.has(l.surah_number)) { seen.add(l.surah_number); surahsOnPage.push(l.surah_number); }
        });
        if (!surahsOnPage.length && payload.anchor_surah_number != null) surahsOnPage.push(payload.anchor_surah_number);
        card.surah.innerHTML = '';
        surahsOnPage.forEach(sn => {
            const g = surahHeaderGlyph(sn);
            const el = document.createElement('span');
            if (g) { el.className = 'mz-head-glyph-item'; el.textContent = g; el.setAttribute('aria-label', `سورة ${surahNameOf(sn)}`); }
            else { el.className = 'mz-head-text-item'; el.textContent = surahNameOf(sn) ? `سورة ${surahNameOf(sn)}` : ''; }
            card.surah.appendChild(el);
        });
        // Shemrly's layout-DB page numbers don't match the 604-page Madina numbering,
        // so derive its juz from the page's first ayah instead of the page number.
        const jn = state.src === 'shamarly'
            ? juzFromAyah(payload.anchor_surah_number, payload.anchor_ayah_number)
            : juzNumber(payload.page_number);
        const jg = juzGlyph(jn);
        const jl = `الجزء ${JUZ_NAME[jn - 1]}`;
        if (jg) { card.juz.classList.add('mz-juz-glyph'); card.juz.textContent = jg; card.juz.title = jl; card.juz.setAttribute('aria-label', jl); }
        else { card.juz.classList.remove('mz-juz-glyph'); card.juz.textContent = jl; }
        card.foot.textContent = `صفحة ${toAr(payload.page_number)}`;
    }

    function surahNameOf(num) {
        const s = state.surahs.find(x => (x.number ?? x) === num);
        return s ? (s.name ?? '') : '';
    }

    /* ── Spread (two facing pages) ─────────────────────────────────── */
    // RTL mushaf: right page = odd, left page = even (e.g. 1|2, 3|4, … 595|596).
    function spreadFor(page) {
        const right = (page % 2 === 1) ? page : page - 1;
        const left = right + 1;
        return [Math.max(PAGE_MIN, right), Math.min(PAGE_MAX, left)];
    }

    async function renderSpread(focusPage) {
        state.focusPage = focusPage;
        try {
            if (state.layoutMode === 'single') {
                // Single page: show the focus page itself in the right card; hide the left.
                state.spread = [focusPage, null];
                const fp = await fetchPageByNumber(focusPage);
                if (state.src === 'shamarly' && fp) await ensureShemrlyFont(fp.font_name);
                renderCard(cards.right, fp);
                renderCard(cards.left, null);
            } else {
                const [right, left] = spreadFor(focusPage);
                state.spread = [right, left];
                const [rp, lp] = await Promise.all([
                    fetchPageByNumber(right),
                    left !== right && left <= PAGE_MAX ? fetchPageByNumber(left) : Promise.resolve(null),
                ]);
                if (state.src === 'shamarly') await Promise.all([rp, lp].map(p => p && ensureShemrlyFont(p.font_name)));
                renderCard(cards.right, rp);
                renderCard(cards.left, lp);
            }
        } catch (e) {
            setStatus('تعذّر تحميل الصفحة', true);
            return;
        }
        applySrcClass();
        if (state.hideText) pageEls().forEach(p => p && p.classList.add('mz-hide'));
        sizePages();
        applyFontSize();
        applySelectionHighlight();
        requestAnimationFrame(justifyLines);
        if (state.tajweedOn) applyTajweedToPage().then(() => requestAnimationFrame(justifyLines));
        updateNavButtons();
    }

    // Make the page(s) as large as the freed centre allows, keeping a mushaf
    // portrait ratio, fitting both width (n pages) and height.
    const PAGE_RATIO = 0.66; // width / height
    function sizePages() {
        const stage = els.stage;
        if (!stage) return;
        const vh = window.innerHeight;
        // Available height = the stage-area's OWN box (a stable, window-derived size),
        // NOT the stage's live position. The stage is vertically centred, so reading
        // its top made availH depend on the previously-rendered page's height — which
        // resized the page frame on every navigation (the "auto-zoom"). The container
        // box is independent of what's currently rendered, so the frame stays put.
        const area = stage.closest('.mz-stage-area');
        const availH = Math.max(320, (area ? area.clientHeight : (vh - 120)) - 16);
        const n = state.layoutMode === 'single' ? 1 : 2;
        const navAndGaps = 2 * 50 + 16;                 // room for the edge nav arrows
        const availW = Math.max(260, stage.clientWidth - navAndGaps);
        const headFootPad = 78;                          // header + footer + card padding (vertical)
        const spreadPad = 28, gutter = n > 1 ? 20 : 0;

        let h = availH - headFootPad;
        let w = h * PAGE_RATIO;
        const totalW = w * n + gutter + spreadPad;
        if (totalW > availW) {
            const s = (availW - gutter - spreadPad) / (w * n);
            w *= s; h *= s;
        }
        w = Math.max(150, w);
        h = Math.max(230, h);
        document.documentElement.style.setProperty('--mz-page-w', w + 'px');
        document.documentElement.style.setProperty('--mz-page-h', h + 'px');
    }

    const pageEls = () => [cards.right.page, cards.left.page];
    const wordsInSpread = sel => {
        const out = [];
        pageEls().forEach(p => p && p.querySelectorAll(sel).forEach(w => out.push(w)));
        return out;
    };

    /* ── Justification (kashida features + scaleX fill) ────────────── */
    // Justify via the font's discrete kashida/justification features, then fill
    // the rest with a gentle horizontal stretch (the earlier, preferred logic).
    function khattFeatureSettings(strength) {
        const s = Math.max(0, Math.min(100, Number(strength) || 0));
        if (s <= 0) return '';
        if (state.src === 'digital_khatt') {
            const levels = [`'jalt' 1`, `'jalt' 1, 'cv02' 1`, `'jalt' 1, 'cv01' 1`, `'jalt' 1, 'cv01' 1, 'cv02' 1`];
            const level = Math.min(levels.length, Math.max(1, Math.ceil((s / 100) * levels.length)));
            return levels[level - 1] || '';
        }
        const seq = [];
        for (let lvl = 1; lvl <= 5; lvl += 1) for (const t of ['jt', 'dc', 'kt']) seq.push(`${t}0${lvl}`);
        const count = Math.round((s / 100) * seq.length);
        if (count <= 0) return '';
        return seq.slice(0, count).map(f => `'${f}'`).join(',');
    }
    // Full-justify every non-centered line so all lines start and end on the same
    // edges (real-mushaf look). For the Madinah mushafs we elongate with the font's
    // kashida features first, then distribute the remaining slack as space BETWEEN
    // words — no scaleX glyph distortion. Centered lines (is_center=1 → data-justify
    // "0": surah headers, basmala, short final lines) are left exactly as printed.
    // Shemrly draws whole-word page glyphs, so it keeps the gentle scaleX fill.
    function justifyLines() {
        const isShamarly = state.src === 'shamarly';
        const features = isShamarly ? '' : khattFeatureSettings(100);
        wordsInSpread('.mz-line').forEach(lineEl => {
            const inner = lineEl.querySelector('.mz-line-inner');
            if (!inner) return;
            inner.style.transform = 'none';
            inner.style.fontFeatureSettings = '';
            inner.style.fontVariationSettings = '';
            inner.style.wordSpacing = '';
            const avail = lineEl.clientWidth;
            if (!avail) return;
            if (lineEl.dataset.justify !== '1') return;       // centered line: leave as-is
            const natural = inner.scrollWidth;
            if (!natural) return;

            if (natural > avail + 0.5) {                      // too long → condense to fit
                inner.style.transform = `scaleX(${Math.max(0.5, avail / natural)})`;
                return;
            }
            if (isShamarly) {                                 // page glyphs → gentle stretch
                inner.style.transform = `scaleX(${Math.min(1.5, avail / natural)})`;
                return;
            }
            // Madinah: kashida-elongate (if it doesn't overshoot), then word-space the rest.
            let width = natural;
            if (features) {
                inner.style.fontFeatureSettings = features;
                const withK = inner.scrollWidth;
                if (withK <= avail + 0.5) width = withK;
                else { inner.style.fontFeatureSettings = ''; }
            }
            const gaps = inner.querySelectorAll('.mz-word').length - 1;
            const slack = avail - width;
            if (slack > 0.5 && gaps > 0) inner.style.wordSpacing = (slack / gaps) + 'px';
            else if (slack > 0.5) inner.style.transform = `scaleX(${avail / width})`;  // single word
        });
    }
    // Size the text so a typical line naturally fills the line width, then let
    // justifyLines word-space the rest. The page FRAME is stable (sizePages reads
    // the stage-area's own box, not the stage's live position), so this stays
    // consistent across navigation instead of zooming per page.
    function applyFontSize() {
        pageEls().forEach(p => {
            if (!p || !p.classList.contains('mz-has-page')) return;
            const h = p.clientHeight || 1;
            const lineH = h / 15;
            const maxFs = lineH * 0.92;          // never taller than the line slot
            let fs = Math.max(11, lineH * 0.62); // line-height baseline
            p.style.setProperty('--dk-fs', fs + 'px');

            // Measure justified lines at this size, then scale so the median line
            // ~fills the width (98%). Proportional scaling keeps the ratio valid.
            const inners = [...p.querySelectorAll('.mz-line[data-justify="1"] .mz-line-inner')];
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
                fs = Math.max(11, Math.min(maxFs, fs * med * 0.98));
                p.style.setProperty('--dk-fs', fs + 'px');
            }
        });
    }

    /* ── Highlighting ──────────────────────────────────────────────── */
    function applySelectionHighlight() {
        const hasSel = state.selectedKeys.size > 0;
        pageEls().forEach(p => p && p.classList.toggle('mz-has-selection', hasSel));
        wordsInSpread('.mz-word').forEach(w => {
            const k = w.dataset.key;
            w.classList.toggle('mz-sel', !!k && state.selectedKeys.has(k));
        });
        if (state.activeKey) markActive(state.activeKey);
    }
    function markActive(key) {
        state.activeKey = key;
        wordsInSpread('.mz-word.mz-act').forEach(w => w.classList.remove('mz-act'));
        if (!key) return;
        wordsInSpread(`.mz-word[data-key="${key}"]`).forEach(w => w.classList.add('mz-act'));
    }
    function scrollActiveIntoView() {
        const first = wordsInSpread('.mz-word.mz-act')[0];
        if (first) first.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    }

    /* ── Word-by-word + verse follow while audio plays ─────────────────
       Each verse carries word timestamps (v.words = [[wpos, start, end], …],
       surah-absolute seconds, 0-based to match the DOM's data-wpos). The
       monitor calls followTick() every 40ms: it lights the single word the
       reciter is on (.mz-now) and moves the verse highlight as the timeline
       crosses verse boundaries (so cumulative-link steps follow correctly). */
    function highlightCurrentWord(t) {
        const cur = state.activeWords.find(w => t >= w.start - 0.02 && t <= w.end + 0.04);
        const id = cur ? `${cur.key}#${cur.wpos}` : '';
        if (id === state.curWordId) return;
        state.curWordId = id;
        wordsInSpread('.mz-word.mz-now').forEach(el => el.classList.remove('mz-now'));
        // Words already recited in this run brighten and stay (progress reveal).
        state.activeWords.forEach(w => {
            if (w.end <= t + 0.02) wordsInSpread(`.mz-word[data-key="${w.key}"][data-wpos="${w.wpos}"]`)
                .forEach(el => el.classList.add('mz-done'));
        });
        if (cur) wordsInSpread(`.mz-word[data-key="${cur.key}"][data-wpos="${cur.wpos}"]`)
            .forEach(el => el.classList.add('mz-now', 'mz-done'));
    }
    function clearWordHighlight() {
        state.curWordId = '';
        wordsInSpread('.mz-word.mz-now').forEach(el => el.classList.remove('mz-now'));
    }
    function clearDone() { wordsInSpread('.mz-word.mz-done').forEach(el => el.classList.remove('mz-done')); }
    function followTick() {
        const t = els.audio.currentTime;
        const v = state.stepVerses.find(x => t >= x.start - EPS && t < x.end + EPS);
        if (v && v.ayah !== state.curFollowAyah) {
            state.curFollowAyah = v.ayah;
            const key = `${state.surah}:${v.ayah}`;
            if (wordsInSpread(`.mz-word[data-key="${key}"]`).length) {
                markActive(key); scrollActiveIntoView();
            } else if (!state.followFlipping) {
                state.followFlipping = true;
                ensureVerseVisible(state.surah, v.ayah).then(() => {
                    applySelectionHighlight();
                    if (state.tajweedOn) applyTajweedToPage();
                    markActive(key); scrollActiveIntoView();
                    state.followFlipping = false;
                }).catch(() => { state.followFlipping = false; });
            }
        }
        highlightCurrentWord(t);
    }

    async function ensureVerseVisible(surah, ayah) {
        const key = `${surah}:${ayah}`;
        if (wordsInSpread(`.mz-word[data-key="${key}"]`).length) return true;
        try {
            const payload = await fetchPageByAyah(surah, ayah);
            await renderSpread(payload.page_number);
            return wordsInSpread(`.mz-word[data-key="${key}"]`).length > 0;
        } catch (e) { return false; }
    }

    /* ── Tajweed (per-letter overlay, ported from main app) ────────── */
    function syncTajweedButton() {
        els.tajweed.classList.toggle('mz-on', state.tajweedOn);
        els.tajweed.setAttribute('aria-pressed', String(state.tajweedOn));
        pageEls().forEach(p => p && p.classList.toggle('mz-tajweed', state.tajweedOn && state.src !== 'shamarly'));
    }
    // Tajweed colouring is letter-level; Shemrly draws whole-word glyphs, so it
    // can't be coloured. Turn it off and disable its toggles while Shemrly is on.
    function syncSrcCapabilities() {
        const noTajweed = state.src === 'shamarly';
        if (noTajweed && state.tajweedOn) { state.tajweedOn = false; syncTajweedButton(); syncToolbar(); }
        [els.tajweed, els.tbTajweed].forEach(b => {
            if (!b) return;
            b.disabled = noTajweed;
            b.classList.toggle('mz-disabled', noTajweed);
            b.title = noTajweed ? 'غير متاح مع خط الشمرلي' : 'تلوين التجويد';
        });
    }
    function _isCombiningMark(cp) {
        return (cp >= 0x064B && cp <= 0x065F) || cp === 0x0670 ||
               (cp >= 0x06D6 && cp <= 0x06ED) || (cp >= 0x0610 && cp <= 0x061A) ||
               (cp >= 0x0653 && cp <= 0x0658) || cp === 0x06E5 || cp === 0x06E6;
    }
    function _alignSkeleton(ch) {
        const cp = ch.codePointAt(0);
        if (cp === 0x0622 || cp === 0x0623 || cp === 0x0625 || cp === 0x0627 ||
            cp === 0x0671 || cp === 0x0621 || cp === 0x0624 || cp === 0x0626) return 'A';
        if (cp === 0x0649 || cp === 0x064A) return 'Y';
        if (cp === 0x0629) return 'H';
        return ch;
    }
    function _alignDisplayToSource(srcChars, dispChars) {
        const n = srcChars.length, m = dispChars.length;
        const dp = Array.from({ length: n + 1 }, () => new Int32Array(m + 1));
        for (let i = 1; i <= n; i++) dp[i][0] = dp[i - 1][0] - 1;
        for (let j = 1; j <= m; j++) dp[0][j] = dp[0][j - 1] - 1;
        for (let i = 1; i <= n; i++) for (let j = 1; j <= m; j++) {
            const sc = _alignSkeleton(srcChars[i - 1]) === _alignSkeleton(dispChars[j - 1]) ? 2 : -1;
            dp[i][j] = Math.max(dp[i - 1][j - 1] + sc, dp[i - 1][j] - 1, dp[i][j - 1] - 1);
        }
        const res = new Array(m).fill(-1);
        let i = n, j = m;
        while (i > 0 && j > 0) {
            const sc = _alignSkeleton(srcChars[i - 1]) === _alignSkeleton(dispChars[j - 1]) ? 2 : -1;
            if (dp[i][j] === dp[i - 1][j - 1] + sc) { res[j - 1] = i - 1; i--; j--; }
            else if (dp[i][j] === dp[i - 1][j] - 1) { i--; } else { j--; }
        }
        return res;
    }
    function overlayTajweedOnDisplay(dispWord, parts) {
        const srcChars = [], srcCls = [];
        for (const p of (parts || [])) for (const ch of p.text) { srcChars.push(ch); srcCls.push(p.cls || ''); }
        const dispChars = [...dispWord];
        const dcls = new Array(dispChars.length).fill('');
        if (srcChars.length && srcCls.some(c => c)) {
            const amap = _alignDisplayToSource(srcChars, dispChars);
            for (let j = 0; j < dispChars.length; j++) { const si = amap[j]; if (si >= 0) dcls[j] = srcCls[si]; }
            let i = 0;
            while (i < dispChars.length) {
                const start = i; i++;
                while (i < dispChars.length && _isCombiningMark(dispChars[i].codePointAt(0))) i++;
                let chosen = '';
                for (let k = start; k < i; k++) { if (dcls[k]) { chosen = dcls[k]; break; } }
                for (let k = start; k < i; k++) dcls[k] = chosen;
            }
        }
        const esc = s => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
        let html = '', cur = null, buf = '';
        for (let j = 0; j < dispChars.length; j++) {
            const cl = dcls[j];
            if (cl !== cur) { if (buf) html += cur ? `<tajweed class="${cur}">${esc(buf)}</tajweed>` : esc(buf); buf = ''; cur = cl; }
            buf += dispChars[j];
        }
        if (buf) html += cur ? `<tajweed class="${cur}">${esc(buf)}</tajweed>` : esc(buf);
        return html;
    }
    function _reclassifyMunfasilInHtml(html) {
        const _hamzaRe = /[ءأؤإئ]/;
        return (html || '').replace(
            /(<tajweed\s+class=["']?madda_obligatory["']?>)([\s\S]*?)(<\/tajweed>)([\s\S]*?)(?= |$)/g,
            (match, open, inner, close, after) =>
                (!_hamzaRe.test(inner) && !_hamzaRe.test(after))
                    ? `<tajweed class="madda_munfasil">${inner}</tajweed>${after}` : match);
    }
    function getNormalizedTajweedHtml(html) {
        return _reclassifyMunfasilInHtml((html || '').replace(/<span[^>]*class=["']?end["']?[^>]*>.*?<\/span>/gi, '').trim());
    }
    function parseTajweedIntoWords(html) {
        const tmp = document.createElement('div');
        tmp.innerHTML = html;
        const tokens = [];
        for (const node of tmp.childNodes) {
            if (node.nodeType === 3) { const t = node.textContent; if (t) tokens.push({ text: t, cls: '' }); }
            else if (node.nodeType === 1) { const cls = (node.getAttribute('class') || '').trim(); if (cls === 'end') continue; const t = node.textContent; if (t) tokens.push({ text: t, cls }); }
        }
        const subTokens = [];
        for (const { text, cls } of tokens) {
            const parts = text.split(' ');
            for (let i = 0; i < parts.length; i++) {
                const isLast = i === parts.length - 1;
                if (parts[i]) subTokens.push({ text: parts[i], cls, boundary: !isLast });
                else if (!isLast) subTokens.push({ text: '', cls, boundary: true });
            }
        }
        const segments = [];
        let segParts = [], segRules = new Set();
        const flush = () => {
            const combined = segParts.map(p => p.text).join('');
            if (combined.trim()) {
                const _hamzaRe = /[ءأؤإئ]/;
                let finalParts = segParts;
                if (segRules.has('madda_obligatory')) {
                    const madIdx = segParts.map(p => p.cls).lastIndexOf('madda_obligatory');
                    const tIn = segParts[madIdx]?.text || '';
                    const tAfter = segParts.slice(madIdx + 1).map(p => p.text).join('');
                    if (!_hamzaRe.test(tIn) && !_hamzaRe.test(tAfter))
                        finalParts = segParts.map(p => p.cls === 'madda_obligatory' ? { ...p, cls: 'madda_munfasil' } : p);
                }
                segments.push({ parts: finalParts.map(p => ({ text: p.text, cls: p.cls })) });
            }
            segParts = []; segRules = new Set();
        };
        for (const sub of subTokens) {
            if (sub.text) { segParts.push({ text: sub.text, cls: sub.cls }); if (sub.cls) segRules.add(sub.cls); }
            if (sub.boundary) flush();
        }
        flush();
        return segments;
    }
    async function getTajweedSegments(surah, ayah) {
        const key = `${surah}:${ayah}`;
        if (state.tajweedCache.has(key)) return state.tajweedCache.get(key);
        let segments = [];
        try {
            const resp = await fetch(`/api/tajweed/${surah}/${ayah}`);
            if (resp.ok) { const data = await resp.json(); segments = parseTajweedIntoWords(getNormalizedTajweedHtml(data.html)); }
        } catch (e) { segments = []; }
        state.tajweedCache.set(key, segments);
        return segments;
    }
    async function applyTajweedToPage() {
        if (!state.tajweedOn || state.src === 'shamarly') return;  // Shemrly words are single glyphs — no letter-level tajweed
        const ayahSpans = new Map();
        wordsInSpread('.mz-word[data-key]').forEach(span => {
            const key = span.dataset.key;
            if (!ayahSpans.has(key)) ayahSpans.set(key, []);
            ayahSpans.get(key).push(span);
        });
        for (const [key, spans] of ayahSpans) {
            const [surah, ayah] = key.split(':').map(Number);
            const segments = await getTajweedSegments(surah, ayah);
            if (!state.tajweedOn) return;
            spans.forEach(span => {
                const wpos = parseInt(span.dataset.wpos, 10);
                const seg = Number.isFinite(wpos) ? segments[wpos] : null;
                const disp = span.dataset.text || span.textContent || '';
                if (seg && seg.parts.some(p => p.cls)) span.innerHTML = overlayTajweedOnDisplay(disp, seg.parts);
                else span.textContent = disp;
                appendWaqfMarks(span, span._waqf);
            });
        }
    }
    function clearTajweedFromPage() {
        wordsInSpread('.mz-word').forEach(span => {
            span.textContent = span.dataset.text || span.textContent || '';
            appendWaqfMarks(span, span._waqf);
        });
    }

    /* ── Navigation ────────────────────────────────────────────────── */
    function updateNavButtons() {
        if (state.layoutMode === 'single') {
            els.prev.disabled = !state.focusPage || state.focusPage <= PAGE_MIN;
            els.next.disabled = !state.focusPage || state.focusPage >= PAGE_MAX;
        } else {
            const [right] = state.spread;
            els.prev.disabled = !right || right <= PAGE_MIN;
            els.next.disabled = !right || right >= PAGE_MAX - 1;
        }
    }
    async function gotoSpread(focusPage) {
        focusPage = Math.max(PAGE_MIN, Math.min(PAGE_MAX, focusPage));
        setStatus('جارٍ تحميل الصفحة…');
        await renderSpread(focusPage);
        setStatus('');
    }

    /* ── Cumulative segmented-repetition schedule (merged الحفظ التراكمي) ── */
    function buildSchedule() {
        const vs = selectedVerses();
        const R = parseInt(els.verseReps.value, 10) || 1;
        const L = parseInt(els.linkReps.value, 10) || 1;
        const cumulative = els.cumulative.checked;
        const splitLong = els.splitLong.checked;
        const steps = [];
        const firstAyah = vs.length ? vs[0].ayah : null;

        vs.forEach((v, i) => {
            const phrases = v.phrases || [];
            // split at every waqf-phrase boundary (the reciter's own pauses),
            // regardless of verse length — short verses with an internal waqf split too.
            const usePhrases = splitLong && phrases.length > 1;
            if (usePhrases) {
                phrases.forEach((p, j) => {
                    for (let r = 0; r < R; r++)
                        steps.push({ start: p.start, end: p.end, ayah: v.ayah, label: `آية ${toAr(v.ayah)} · مقطع ${toAr(j + 1)}/${toAr(phrases.length)}`, rep: r + 1, repTotal: R });
                    if (cumulative && j > 0)
                        steps.push({ start: phrases[0].start, end: p.end, ayah: v.ayah, label: `آية ${toAr(v.ayah)} · ربط المقاطع`, rep: 1, repTotal: 1 });
                });
                steps.push({ start: v.start, end: v.end, ayah: v.ayah, label: `آية ${toAr(v.ayah)} · كاملة`, rep: 1, repTotal: 1 });
            } else {
                for (let r = 0; r < R; r++)
                    steps.push({ start: v.start, end: v.end, ayah: v.ayah, label: `آية ${toAr(v.ayah)}`, rep: r + 1, repTotal: R });
            }
            if (cumulative && i > 0)
                for (let r = 0; r < L; r++)
                    steps.push({ start: vs[0].start, end: v.end, ayah: v.ayah, label: `ربط الآيات ${toAr(firstAyah)}–${toAr(v.ayah)}`, rep: r + 1, repTotal: L });
        });
        return steps;
    }

    function startMonitor() {
        stopMonitor();
        state.monitorId = setInterval(() => {
            if (state.pendingSeek || state.stepIdx < 0 || els.audio.paused) return;
            const step = state.schedule[state.stepIdx];
            if (!step) return;
            updateProgress();
            followTick();
            if (els.audio.currentTime >= step.end - EPS) advanceStep();
        }, 40);
    }
    const stopMonitor = () => { if (state.monitorId) { clearInterval(state.monitorId); state.monitorId = null; } };

    function seekTo(t) {
        state.pendingSeek = true;
        const apply = () => { try { els.audio.currentTime = t; } catch (e) {} els.audio.play().catch(() => {}); };
        if (els.audio.readyState >= 1) apply();
        else els.audio.addEventListener('loadedmetadata', apply, { once: true });
    }

    async function playStep(k, atTime) {
        if (k >= state.schedule.length) {
            if (els.loop.checked) { k = 0; } else { finishPlayback(); return; }
        }
        state.stepIdx = k;
        const step = state.schedule[k];
        // Verses overlapping this step's time window (a cumulative-link step spans
        // several). The first is where playback begins; the follower advances from it.
        state.stepVerses = [...state.verseByAyah.values()]
            .filter(v => v.start < step.end + EPS && v.end > step.start - EPS)
            .sort((a, b) => a.ayah - b.ayah);
        state.activeWords = [];
        state.stepVerses.forEach(v => (v.words || []).forEach(w =>
            state.activeWords.push({ key: `${state.surah}:${v.ayah}`, wpos: w[0], start: w[1], end: w[2] })));
        const firstAyah = state.stepVerses.length ? state.stepVerses[0].ayah : step.ayah;
        state.curFollowAyah = null;
        clearWordHighlight();
        await ensureVerseVisible(state.surah, firstAyah);
        markActive(`${state.surah}:${firstAyah}`);
        state.curFollowAyah = firstAyah;
        scrollActiveIntoView();
        seekTo(atTime != null ? atTime : step.start);
        els.now.textContent = `${surahNameOf(state.surah)} · ${step.label}` + (step.repTotal > 1 ? ` (${toAr(step.rep)}/${toAr(step.repTotal)})` : '');
        saveSetting('mz_last_pos', `${state.surah}:${step.ayah}`);
        saveSetting('quranApp_lastPosition', `${state.surah}:${step.ayah}`);
    }
    const advanceStep = () => playStep(state.stepIdx + 1);

    const fmtTime = (sec) => {
        sec = Math.max(0, Math.floor(sec || 0));
        const m = Math.floor(sec / 60), s = sec % 60;
        return `${toAr(m)}:${toAr(String(s).padStart(2, '0'))}`;
    };
    function updateProgress() {
        const step = state.schedule[state.stepIdx];
        if (!step) return;
        const span = Math.max(0.001, step.end - step.start);
        const elapsed = Math.max(0, Math.min(span, els.audio.currentTime - step.start));
        const frac = elapsed / span;
        const overall = (state.stepIdx + frac) / state.schedule.length;
        els.progressFill.style.width = `${Math.round(overall * 100)}%`;
        if (els.timeCur) els.timeCur.textContent = fmtTime(elapsed);
        if (els.timeDur) els.timeDur.textContent = fmtTime(span);
        // remaining time for the whole repetition session (shown beside now-playing)
        if (els.remaining) {
            let prior = 0;
            for (let i = 0; i < state.stepIdx; i++) prior += stepSec(state.schedule[i]);
            const total = state.schedule.reduce((acc, st) => acc + stepSec(st), 0);
            const left = Math.max(0, total - (prior + elapsed));
            els.remaining.textContent = left > 0 ? `باقٍ ${fmtTime(left)}` : '';
        }
    }

    // Click anywhere on the session progress bar to jump within the schedule.
    function seekOverall(frac) {
        const n = state.schedule.length;
        if (!n) return;
        frac = Math.max(0, Math.min(0.99999, frac));
        const idx = Math.min(n - 1, Math.floor(frac * n));
        const within = frac * n - idx;                      // 0..1 inside the target step
        const step = state.schedule[idx];
        const t = step.start + within * Math.max(0, step.end - step.start);
        if (!state.playing) { state.playing = true; setPlayIcon(true); startMonitor(); }
        playStep(idx, t);
    }

    // The docked player grows/shrinks the stage area, so refit the page to the new
    // height — once now and once after the open/close transition settles.
    function refitForPlayer() {
        if (!state.focusPage) return;
        const run = () => { sizePages(); applyFontSize(); requestAnimationFrame(justifyLines); };
        requestAnimationFrame(run);
        setTimeout(run, 380);
    }

    async function startPlayback() {
        rebuildSelectedKeys();
        clearDone();   // fresh progress reveal for this run
        state.schedule = buildSchedule();
        if (!state.schedule.length) { setStatus('لا توجد آيات في النطاق المحدد', true); return; }
        const [a] = selectedAyahRange();
        setStatus('جارٍ فتح صفحة المصحف…');
        const ok = await ensureVerseVisible(state.surah, a);
        if (!ok) { setStatus('تعذّر تحديد موضع الآية في المصحف', true); return; }
        applySelectionHighlight();
        setStatus('');
        state.playing = true;
        els.player.classList.add('mz-show');
        els.player.setAttribute('aria-hidden', 'false');
        refitForPlayer();
        setPlayIcon(true);
        syncLoopBtn();
        startMonitor();
        playStep(0);
    }
    function finishPlayback() {
        state.playing = false; stopMonitor(); els.audio.pause(); setPlayIcon(false); markActive(null);
        clearWordHighlight();
        els.progressFill.style.width = '100%';
        els.now.textContent = 'تم — أحسنت! 🌿';
        if (els.remaining) els.remaining.textContent = '';
        setTimeout(() => { if (!state.playing) els.progressFill.style.width = '0%'; }, 1200);
    }
    function stopPlayback() {
        state.playing = false; state.stepIdx = -1; state.schedule = []; stopMonitor(); els.audio.pause(); setPlayIcon(false); markActive(null);
        clearWordHighlight(); clearDone(); state.stepVerses = []; state.activeWords = []; state.curFollowAyah = null;
        els.progressFill.style.width = '0%';
        els.now.textContent = '';
        if (els.remaining) els.remaining.textContent = '';
        els.player.classList.remove('mz-show');
        els.player.setAttribute('aria-hidden', 'true');
        refitForPlayer();
    }
    function togglePlay() {
        if (els.audio.paused) {
            if (state.stepIdx < 0) playStep(0); else els.audio.play().catch(() => {});
            state.playing = true; setPlayIcon(true); startMonitor();
        } else { els.audio.pause(); state.playing = false; setPlayIcon(false); }
    }
    function setPlayIcon(playing) {
        const i = els.play.querySelector('i');
        if (i) i.className = playing ? 'fas fa-pause' : 'fas fa-play';
        els.play.setAttribute('aria-label', playing ? 'إيقاف مؤقت' : 'تشغيل');
    }
    function syncLoopBtn() {
        if (els.loopBtn) els.loopBtn.setAttribute('aria-pressed', String(!!els.loop.checked));
    }

    // Attach 'seeked' and 'ended' listeners to the initial native audio element.
    // loadSurahMemo calls attachAudioEvents() again whenever the backend switches.
    attachAudioEvents(els.audio);

    /* ── Recite & follow (streaming ASR, beta) ─────────────────────────
       Lazy-loads static/mushaf_asr.js (onnxruntime-web + the FastConformer
       streaming model). The module emits recognised Arabic words; we match
       them against the selected verses in order to follow / reveal / advance. */
    let _asrLoaded = false, _asrActive = false;
    const _arNorm = s => (s || '')
        // strip every harakat/mark/tatweel/ayah-ornament + Arabic-Indic digits
        .replace(/[ً-ٰٟۖ-ۭ࣐-ࣿـ۝٠-٩]/g, '')
        .replace(/[إأآاٱ]/g, 'ا').replace(/[ىي]/g, 'ي').replace(/ة/g, 'ه').replace(/ؤ/g, 'و').replace(/ئ/g, 'ي')
        .replace(/\s+/g, ' ').trim();

    // Flat list of the expected words across the selected range, taken straight
    // from the ON-PAGE word elements (in mushaf reading order) so matches light up
    // the exact words in their real positions — no QPC↔DK position mismatch.
    const _isNumWord = t => /^[۝]?[٠-٩]+$/.test((t || '').trim());
    function _expectedFlat() {
        const [a, b] = selectedAyahRange();
        const out = [];
        wordsInSpread('.mz-word[data-key]').forEach(el => {
            const [s, ay] = el.dataset.key.split(':').map(Number);
            if (s !== state.surah || ay < a || ay > b) return;
            if (_isNumWord(el.dataset.text || el.textContent)) return; // skip the verse-number ornament
            const norm = _arNorm(el.dataset.text || el.textContent || '');
            if (norm) out.push({ norm, el, ayah: ay, key: el.dataset.key });
        });
        return out;
    }
    const _wmatch = (a, b) => a === b ||
        (a.length >= 4 && b.length >= 4 && (a.startsWith(b) || b.startsWith(a) || a.includes(b) || b.includes(a)));

    function loadScript(src) {
        return new Promise((resolve, reject) => {
            const s = document.createElement('script');
            s.src = src; s.onload = resolve; s.onerror = () => reject(new Error('load failed'));
            document.head.appendChild(s);
        });
    }
    function showAsrLive(on) {
        if (!els.asrLive) return;
        els.asrLive.hidden = !on;
        if (on && els.asrLiveText) els.asrLiveText.textContent = 'استمع…';
    }

    async function startReciteFollow() {
        if (_asrActive) { try { window.MushafASR && window.MushafASR.stop(); } catch (e) {} return; }
        if (els.asrNote) els.asrNote.textContent = 'جارٍ تحضير نموذج التعرّف… (قد يستغرق التحميل أول مرة)';
        try {
            if (!_asrLoaded) { await loadScript('/static/js/mushaf_asr.js?v=25'); _asrLoaded = true; }
            if (!window.MushafASR) throw new Error('module missing');

            // make sure the selected verses are actually on screen before we map words
            await renderSelection();
            // reset any previous recite highlights
            wordsInSpread('.mz-word.mz-recited').forEach(w => w.classList.remove('mz-recited'));
            const expFlat = _expectedFlat();
            let ePtr = 0, hPtr = 0, lastAyah = -1;

            const markRecited = (e) => {
                if (e.el) {
                    e.el.classList.add('mz-recited');
                    if (state.hideText) e.el.classList.add('mz-reveal');
                    e.el.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
                }
                if (e.ayah !== lastAyah) {
                    lastAyah = e.ayah;
                    markActive(e.key);
                    if (state.hideText) revealVerse(e.key);
                }
            };

            await window.MushafASR.start({
                onStatus: (msg) => { if (els.asrNote) els.asrNote.textContent = msg; if (els.asrLiveText && /استمع|listen/i.test(msg)) showAsrLive(true); },
                onActive: (on) => {
                    _asrActive = on;
                    if (els.reciteBtn) els.reciteBtn.classList.toggle('mz-listening', on);
                    showAsrLive(on);
                },
                // Running recognised transcript → live display + word-by-word follow.
                onTranscript: (text) => {
                    const heardRaw = (text || '').trim();
                    const heard = _arNorm(text).split(' ').filter(Boolean);
                    if (els.asrLiveText) els.asrLiveText.textContent = heardRaw ? heardRaw.split(' ').slice(-12).join(' ') : 'استمع…';
                    // tolerant greedy alignment of heard words to the expected sequence
                    while (hPtr < heard.length && ePtr < expFlat.length) {
                        const e = expFlat[ePtr];
                        if (_wmatch(heard[hPtr], e.norm)) { markRecited(e); ePtr++; hPtr++; continue; }
                        let found = -1;
                        for (let k = hPtr + 1; k < Math.min(hPtr + 3, heard.length); k++)
                            if (_wmatch(heard[k], e.norm)) { found = k; break; }
                        if (found >= 0) { markRecited(e); ePtr++; hPtr = found + 1; }
                        else hPtr++; // skip a noise word
                    }
                    if (els.asrNote && expFlat.length) els.asrNote.textContent = `طابقت ${toAr(ePtr)} / ${toAr(expFlat.length)} كلمة`;
                    if (ePtr >= expFlat.length && els.asrNote) els.asrNote.textContent = 'أحسنت! اكتمل التسميع 🌿';
                },
            });
        } catch (e) {
            _asrActive = false;
            if (els.reciteBtn) els.reciteBtn.classList.remove('mz-listening');
            showAsrLive(false);
            console.error('[recite] failed:', e);
            const msg = (e && (e.message || e.name)) ? (e.message || e.name) : String(e);
            if (els.asrNote) els.asrNote.textContent = 'تعذّر التشغيل: ' + msg;
        }
    }

    /* ── Wiring ────────────────────────────────────────────────────── */
    async function onSurahChange() {
        stopPlayback();
        const surah = parseInt(els.surah.value, 10) || 1;
        try {
            await loadSurahMemo(surah);
            saveSetting('mz_last_pos', `${surah}:1`);
            await renderSelection();   // jump the mushaf straight to the chosen surah
        }
        catch (e) { setStatus('تعذّر تحميل بيانات السورة', true); }
    }
    const liveSelection = () => { if (state.focusPage) { rebuildSelectedKeys(); applySelectionHighlight(); } updateHint(); };

    /* ── Top-bar labels (reciter / repeat / mushaf source) ─────────── */
    const SRC_NAMES = { digital_khatt: 'المدينة الجديد', qpc_v1: 'المدينة ١٤٠٥', shamarly: 'الشمرلي' };
    function syncBarLabels() {
        if (els.reciterLabel) els.reciterLabel.textContent = state.reciterName || 'القارئ';
        if (els.repsBadge) els.repsBadge.textContent = '×' + toAr(parseInt(els.verseReps.value, 10) || 1);
        if (els.srcLabel) els.srcLabel.textContent = SRC_NAMES[state.src] || 'المصحف';
    }

    /* ── Popovers (reciter / mushaf source) ────────────────────────── */
    function closePopovers(except) {
        [[els.reciterTrigger, els.reciterPanel], [els.srcTrigger, els.srcPanel]].forEach(([t, p]) => {
            if (!p || p === except) return;
            p.hidden = true; if (t) t.setAttribute('aria-expanded', 'false');
        });
    }
    function togglePopover(trigger, panel) {
        if (!trigger || !panel) return;
        const open = panel.hidden;
        closePopovers(open ? panel : null);
        panel.hidden = !open;
        trigger.setAttribute('aria-expanded', String(open));
    }
    document.addEventListener('click', (e) => {
        if (!e.target.closest('.mz-pop')) closePopovers();
    });

    /* ── Tap-to-pick sheet (juz / surah / page) ────────────────────── */
    let _pickerKind = null;
    function openPicker(kind) {
        _pickerKind = kind;
        const list = els.pickerList; list.innerHTML = '';
        list.classList.toggle('mz-grid', kind === 'juz' || kind === 'page');
        const curPage = state.layoutMode === 'single' ? state.focusPage : state.spread[0];
        if (kind === 'surah') {
            els.pickerTitle.textContent = 'اختر السورة';
            els.pickerSearch.hidden = false; els.pickerSearch.value = '';
            state.surahs.forEach(s => {
                const n = s.number ?? s; const name = s.name ?? '';
                list.appendChild(pickerItem(`سورة ${name}`, n, n === state.surah, () => navigateToSurah(n), name));
            });
            requestAnimationFrame(() => els.pickerSearch.focus());
        } else if (kind === 'juz') {
            els.pickerTitle.textContent = 'اختر الجزء';
            els.pickerSearch.hidden = true;
            const curJuz = juzNumber(curPage || 1);
            for (let j = 1; j <= 30; j++)
                list.appendChild(pickerItem(JUZ_NAME[j - 1], j, j === curJuz, () => navigateToJuz(j)));
        } else {
            els.pickerTitle.textContent = 'اذهب إلى صفحة';
            els.pickerSearch.hidden = true;
            const pages = state.src === 'shamarly' ? SHEMRLY_PAGES : Array.from({ length: PAGE_MAX }, (_, i) => i + 1);
            pages.forEach(p => list.appendChild(pickerItem(toAr(p), p, p === curPage, () => navigateToPage(p))));
        }
        els.picker.hidden = false;
    }
    function pickerItem(label, num, current, onPick, searchKey) {
        const b = document.createElement('button');
        b.type = 'button'; b.className = 'mz-picker-item' + (current ? ' mz-current' : '');
        b.dataset.search = (searchKey || label);
        b.innerHTML = `<span class="mz-pi-num">${toAr(num)}</span><span>${label}</span>`;
        b.addEventListener('click', () => { closePicker(); onPick(); });
        if (current) requestAnimationFrame(() => b.scrollIntoView({ block: 'center' }));
        return b;
    }
    function closePicker() { if (els.picker) els.picker.hidden = true; _pickerKind = null; }
    function filterPicker() {
        const q = (els.pickerSearch.value || '').trim();
        els.pickerList.querySelectorAll('.mz-picker-item').forEach(it => {
            it.style.display = !q || it.dataset.search.includes(q) ? '' : 'none';
        });
    }
    async function navigateToSurah(n) {
        els.surah.value = String(n);
        els.surah.dispatchEvent(new Event('change'));
    }
    async function navigateToJuz(j) {
        stopPlayback();
        await gotoSpread(JUZ_START_PAGE[j - 1]);
    }
    async function navigateToPage(p) {
        stopPlayback();
        await gotoSpread(p);
    }

    /* ── Click-to-range selection (hide OFF) ───────────────────────── */
    function handleVerseClick(ayah) {
        if (!Number.isFinite(ayah)) return;
        clearDone();   // re-selecting resets the progress reveal
        if (state.rangeAnchor == null) {
            state.rangeAnchor = ayah;
            els.from.value = String(ayah); els.to.value = String(ayah);
            rebuildSelectedKeys(); applySelectionHighlight(); updateHint();
            setStatus('اختر آية النهاية…');
        } else {
            const a = Math.min(state.rangeAnchor, ayah), b = Math.max(state.rangeAnchor, ayah);
            state.rangeAnchor = null;
            els.from.value = String(a); els.to.value = String(b);
            rebuildSelectedKeys(); applySelectionHighlight(); updateHint();
            setStatus(a === b ? `الآية ${toAr(a)}` : `النطاق ${toAr(a)}–${toAr(b)} · اضغط ▶`);
        }
    }

    function bindEvents() {
        els.surah.addEventListener('change', onSurahChange);
        els.from.addEventListener('change', () => { autoSetTo(parseInt(els.from.value, 10)); rebuildSelectedKeys(); renderSelection(); });
        els.to.addEventListener('change', liveSelection);

        els.start.addEventListener('click', () => {
            els.start.disabled = true;
            startPlayback().finally(() => { els.start.disabled = false; });
        });
        els.play.addEventListener('click', () => {
            if (!state.schedule.length || state.stepIdx < 0) startPlayback(); else togglePlay();
        });
        els.stop.addEventListener('click', stopPlayback);

        // top-bar popovers
        if (els.reciterTrigger) els.reciterTrigger.addEventListener('click', () => togglePopover(els.reciterTrigger, els.reciterPanel));
        if (els.srcTrigger) els.srcTrigger.addEventListener('click', () => togglePopover(els.srcTrigger, els.srcPanel));

        // tap-to-pick chrome + picker sheet
        [cards.right.juz, cards.left.juz].forEach(el => el && el.addEventListener('click', () => openPicker('juz')));
        [cards.right.surah, cards.left.surah].forEach(el => el && el.addEventListener('click', () => openPicker('surah')));
        [cards.right.foot, cards.left.foot].forEach(el => el && el.addEventListener('click', () => openPicker('page')));
        if (els.pickerClose) els.pickerClose.addEventListener('click', closePicker);
        if (els.pickerBackdrop) els.pickerBackdrop.addEventListener('click', closePicker);
        if (els.pickerSearch) els.pickerSearch.addEventListener('input', filterPicker);
        document.addEventListener('keydown', (e) => { if (e.key === 'Escape') { closePicker(); closePopovers(); } });
        if (els.prevStep) els.prevStep.addEventListener('click', () => {
            if (!state.schedule.length) return;
            playStep(state.stepIdx <= 0 ? 0 : state.stepIdx - 1);
        });
        if (els.nextStep) els.nextStep.addEventListener('click', () => {
            if (!state.schedule.length) return;
            playStep(Math.min(state.schedule.length - 1, Math.max(0, state.stepIdx) + 1));
        });
        if (els.loopBtn) els.loopBtn.addEventListener('click', () => {
            els.loop.checked = !els.loop.checked;
            syncLoopBtn();
        });
        const navPrev = () => { if (state.focusPage) gotoSpread(state.layoutMode === 'single' ? state.focusPage - 1 : state.spread[0] - 2); };
        const navNext = () => { if (state.focusPage) gotoSpread(state.layoutMode === 'single' ? state.focusPage + 1 : state.spread[0] + 2); };
        els.prev.addEventListener('click', navPrev);
        els.next.addEventListener('click', navNext);
        // Keyboard page-turn (RTL): → previous page, ← next page.
        document.addEventListener('keydown', (e) => {
            if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft') return;
            if (!els.picker.hidden) return;                                    // picker open
            if (e.target.closest('input, select, textarea')) return;          // typing
            if (e.metaKey || e.ctrlKey || e.altKey) return;
            e.preventDefault();
            (e.key === 'ArrowRight' ? navPrev : navNext)();
        });

        els.progress.addEventListener('click', (e) => {
            if (!state.schedule.length) return;
            const rect = els.progress.getBoundingClientRect();
            const frac = Math.max(0, Math.min(1, (rect.right - e.clientX) / rect.width));
            playStep(Math.min(state.schedule.length - 1, Math.floor(frac * state.schedule.length)));
        });

        els.tajweed.addEventListener('click', () => {
            state.tajweedOn = !state.tajweedOn;
            syncTajweedButton();
            syncToolbar();
            saveSetting('quranApp_tajweedEnabled', state.tajweedOn);
            if (state.tajweedOn) applyTajweedToPage().then(() => requestAnimationFrame(justifyLines));
            else { clearTajweedFromPage(); requestAnimationFrame(justifyLines); }
        });

        els.justify.addEventListener('input', () => {
            state.justify = parseInt(els.justify.value, 10);
            updateJustifyLabel();
            saveSetting('quranApp_khattJustify', state.justify);
            if (state.focusPage) requestAnimationFrame(justifyLines);
        });

        els.src.addEventListener('change', async () => {
            // Preserve the reading position by surah/ayah, not page number: Shemrly's
            // layout-DB pages don't match the 604-page Madina numbering, so keeping the
            // page number would jump to unrelated content when crossing that boundary.
            const firstWord = wordsInSpread('.mz-word[data-key]')[0];
            const anchorKey = firstWord ? firstWord.dataset.key
                : `${state.surah}:${selectedAyahRange()[0]}`;
            state.src = els.src.value;
            saveSetting('mz_src', state.src);
            syncSrcCapabilities();
            syncBarLabels();
            closePopovers();
            if (!state.focusPage) return;
            stopPlayback();
            state.tajweedCache.clear();
            try {
                const [s, a] = anchorKey.split(':').map(Number);
                const payload = await fetchPageByAyah(s, a);   // page in the NEW source
                let target = payload.page_number;
                if (state.src === 'shamarly' && !SHEMRLY_PAGE_SET.has(target)) {
                    setStatus('خط الشمرلي متاح لصفحات مختارة — تم الانتقال لأقرب صفحة متاحة');
                    target = nearestShemrlyPage(target);
                }
                await gotoSpread(target);
            } catch (e) {
                renderSpread(state.focusPage);
            }
        });

        els.layout.addEventListener('change', () => {
            state.layoutMode = els.layout.value === 'single' ? 'single' : 'dual';
            document.body.classList.toggle('mz-single', state.layoutMode === 'single');
            saveSetting('mz_layout', state.layoutMode);
            if (state.focusPage) renderSpread(state.focusPage);
        });

        // Cumulative controls
        els.verseReps.addEventListener('change', () => { updateHint(); syncBarLabels(); });
        els.linkReps.addEventListener('change', updateHint);
        els.cumulative.addEventListener('change', updateHint);
        els.splitLong.addEventListener('change', () => { document.body.classList.toggle('mz-split-on', els.splitLong.checked); updateHint(); });
        if (els.loop) els.loop.addEventListener('change', syncLoopBtn);
        if (els.reciter) els.reciter.addEventListener('change', async () => {
            state.reciter = els.reciter.value;
            saveSetting('quranApp_memoReciter', state.reciter);
            stopPlayback();
            try { await loadSurahMemo(state.surah); syncBarLabels(); } catch (e) { setStatus('تعذّر تحميل القارئ', true); }
        });

        els.splitMode.addEventListener('change', () => { state.splitModeVal = els.splitMode.value; reloadMemoBoundaries(); });
        els.gap.addEventListener('input', () => { state.gapMs = parseInt(els.gap.value, 10) || 250; els.gapVal.textContent = state.gapMs + 'ms'; });
        els.gap.addEventListener('change', reloadMemoBoundaries);

        // Hide-for-testing toggles (topbar + sidebar)
        const toggleHide = () => setHideMode(!state.hideText);
        if (els.hideToggle) els.hideToggle.addEventListener('click', toggleHide);
        if (els.hideBtn) els.hideBtn.addEventListener('click', toggleHide);
        // Click a word: hide ON → reveal its verse; hide OFF → pick the range.
        if (els.stage) els.stage.addEventListener('click', (e) => {
            const w = e.target.closest('.mz-word');
            if (!w || !w.dataset.key) return;
            if (state.hideText) { revealVerse(w.dataset.key); return; }
            const [s, a] = w.dataset.key.split(':').map(Number);
            if (s === state.surah) handleVerseClick(a);
        });
        // Breathing panel: verse stepper + close
        // Focus mode
        if (els.focusToggle) els.focusToggle.addEventListener('click', () => setFocusMode(!state.focusMode));
        // Floating mushaf toolbar
        if (els.tbLayout) els.tbLayout.addEventListener('click', toggleLayout);
        if (els.tbTajweed) els.tbTajweed.addEventListener('click', () => els.tajweed.click());
        if (els.progress) els.progress.addEventListener('click', e => {
            const rect = els.progress.getBoundingClientRect();
            if (!rect.width) return;
            let f = (e.clientX - rect.left) / rect.width;
            if (getComputedStyle(els.progress).direction === 'rtl') f = 1 - f;
            seekOverall(f);
        });
        if (els.tbHide) els.tbHide.addEventListener('click', () => setHideMode(!state.hideText));
        if (els.tbWaqf) {
            els.tbWaqf.checked = _waqfVisible;
            els.tbWaqf.addEventListener('change', () => setWaqfMarks(els.tbWaqf.checked));
        }
        setupVolume();
        // Recite & follow (lazy-load the ASR module)
        if (els.reciteBtn) els.reciteBtn.addEventListener('click', startReciteFollow);

        // Sidebar drawer (mobile)
        if (els.sidebarToggle) {
            els.sidebarToggle.addEventListener('click', () => document.body.classList.toggle('mz-sidebar-open'));
        }

        let resizeId = 0;
        window.addEventListener('resize', () => {
            clearTimeout(resizeId);
            resizeId = setTimeout(() => { if (state.focusPage) { sizePages(); applyFontSize(); justifyLines(); } }, 120);
        });
    }

    async function renderSelection() {
        rebuildSelectedKeys();
        const [a] = selectedAyahRange();
        setStatus('جارٍ فتح صفحة المصحف…');
        const ok = await ensureVerseVisible(state.surah, a);
        if (!ok) {
            // Shemrly only ships select pages; don't treat a missing one as an error.
            setStatus(state.src === 'shamarly'
                ? 'هذه الآية غير متوفرة بخط الشمرلي بعد — اختر سورة/آية ضمن الصفحات المتاحة'
                : 'تعذّر تحديد موضع الآية في المصحف', state.src !== 'shamarly');
            return;
        }
        applySelectionHighlight();
        setStatus('');
    }

    function applyDeepLink() {
        const p = new URLSearchParams(location.search);
        const src = p.get('src');
        if (src === 'qpc_v1' || src === 'digital_khatt') { state.src = src; els.src.value = src; saveSetting('mz_src', src); applySrcClass(); }
        const tj = p.get('tajweed');
        if (tj === '1' || tj === '0') { state.tajweedOn = tj === '1'; syncTajweedButton(); saveSetting('quranApp_tajweedEnabled', state.tajweedOn); }
        const jq = parseInt(p.get('justify'), 10);
        if (Number.isFinite(jq)) { state.justify = Math.max(0, Math.min(100, jq)); els.justify.value = state.justify; updateJustifyLabel(); saveSetting('quranApp_khattJustify', state.justify); }
        const wq = p.get('waqf');
        if (wq != null) { state.mushafVersions = wq ? wq.split(',').map(s => s.trim()).filter(Boolean) : []; saveSetting('quranApp_mushafVersions', JSON.stringify(state.mushafVersions)); }
        const ly = p.get('layout');
        if (ly === 'single' || ly === 'dual') { state.layoutMode = ly; els.layout.value = ly; saveSetting('mz_layout', ly); document.body.classList.toggle('mz-single', ly === 'single'); }
        if (p.get('hide') === '1') state.hideText = true;
        if (p.get('focus') === '1') setFocusMode(true);
        const surah = parseInt(p.get('surah'), 10);
        if (!surah) return false;
        if ([...els.surah.options].some(o => +o.value === surah)) els.surah.value = surah;
        return true;
    }

    /* ── Init ──────────────────────────────────────────────────────── */
    // Recite & follow (تسميع) is experimental and its engine files are kept local
    // (gitignored). Reveal its controls only behind a dev flag so the published app
    // doesn't show a feature whose model isn't deployed.
    function gateReciteFeature() {
        const dev = new URLSearchParams(location.search).get('asr') === '1'
            || localStorage.getItem('mz_asr_dev') === '1';
        if (dev) localStorage.setItem('mz_asr_dev', '1');
        const box = $('mz-asr-dev');
        if (box) box.hidden = !dev;
    }

    async function init() {
        initTheme();
        loadSettings();
        gateReciteFeature();
        syncSrcCapabilities();
        bindEvents();
        // واقف-marks-by-mushaf feature removed from the UI: keep no version selected
        // (Shemrly still injects its own marks via waqfQuery).
        state.mushafVersions = [];
        document.body.classList.toggle('mz-picking', !state.hideText);
        await loadReciters();
        syncBarLabels();
        document.body.classList.toggle('mz-split-on', els.splitLong.checked);
        try {
            await loadSurahs();
            const savedPos = localStorage.getItem('mz_last_pos');
            if (savedPos) {
                const savedSurah = parseInt(savedPos.split(':')[0], 10);
                if (savedSurah && [...els.surah.options].some(o => +o.value === savedSurah)) els.surah.value = String(savedSurah);
            }
            const hasDeepLink = applyDeepLink();
            await loadSurahMemo(parseInt(els.surah.value, 10) || 1);
            if (hasDeepLink) {
                const p = new URLSearchParams(location.search);
                const from = parseInt(p.get('from'), 10), to = parseInt(p.get('to'), 10);
                if (from && [...els.from.options].some(o => +o.value === from)) els.from.value = from;
                if (to && [...els.to.options].some(o => +o.value === to)) els.to.value = to;
            }
            await renderSelection();
            if (state.hideText) setHideMode(true);
            // Re-fit once the mushaf fonts are actually loaded (initial measure
            // may have used fallback metrics).
            if (document.fonts && document.fonts.ready) {
                document.fonts.ready.then(() => {
                    if (state.focusPage) { applyFontSize(); requestAnimationFrame(justifyLines); }
                });
            }
        } catch (e) {
            setStatus('تعذّر تهيئة الصفحة', true);
        }
    }

    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
    else init();
})();
