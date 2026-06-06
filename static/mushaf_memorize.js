/* ═══════════════════════════════════════════════════════════════════
   Mushaf Memorize — visual memorization on the Digital Khatt (Madinah)
   page layout, with synced Husary recitation.

   Flow: pick surah + ayah range → jump to the real mushaf page holding the
   first selected verse → highlight the target verses in place → play the
   range (Husary), spotlighting the verse currently being recited and
   auto-flipping pages as the recitation crosses a page boundary.

   Reuses three existing endpoints:
     GET /api/surahs                                  list of surahs
     GET /api/memorization/<surah>                    audio_url + per-verse [start,end] (seconds)
     GET /api/digital-khatt/page-by-ayah/<s>/<a>      new Madinah mushaf page payload
     GET /api/digital-khatt/page/<n>
     GET /api/qpc-v1/page-by-ayah/<s>/<a>             old Madinah 1405 mushaf page payload
     GET /api/qpc-v1/page/<n>
     GET /api/tajweed/<s>/<a>                         tajweed-annotated verse HTML
   ═══════════════════════════════════════════════════════════════════ */
(function () {
    'use strict';

    const $ = id => document.getElementById(id);

    const els = {
        surah:        $('mz-surah'),
        from:         $('mz-from'),
        to:           $('mz-to'),
        reps:         $('mz-reps'),
        loop:         $('mz-loop'),
        src:          $('mz-src'),
        start:        $('mz-start'),
        status:       $('mz-status'),
        page:         $('mz-page'),
        empty:        $('mz-empty'),
        footSurah:    $('mz-foot-surah'),
        footPage:     $('mz-foot-page'),
        footJuz:      $('mz-foot-juz'),
        prev:         $('mz-prev'),
        next:         $('mz-next'),
        player:       $('mz-player'),
        play:         $('mz-play'),
        stop:         $('mz-stop'),
        now:          $('mz-now'),
        progress:     $('mz-progress'),
        progressFill: $('mz-progress-fill'),
        audio:        $('mz-audio'),
        themeToggle:  $('mz-theme-toggle'),
        tajweed:      $('mz-tajweed'),
        justify:      $('mz-justify'),
        justifyVal:   $('mz-justify-val'),
    };

    const EPS = 0.05;
    const PAGE_MIN = 1, PAGE_MAX = 604;

    const state = {
        surahs: [],
        surah: 1,
        memo: null,
        verseByAyah: new Map(),
        selectedKeys: new Set(),
        page: null,
        pageNumber: null,
        schedule: [],
        stepIdx: -1,
        monitorId: null,
        pendingSeek: false,
        playing: false,
        activeKey: null,
        justify: 50,            // 0–100 horizontal-stretch level (shared with main app)
        tajweedOn: false,
        tajweedCache: new Map(), // 'surah:ayah' → array of per-word class strings
        src: 'digital_khatt',   // 'digital_khatt' | 'qpc_v1'
    };

    /* ── Status helper ─────────────────────────────────────────────── */
    function setStatus(msg, isErr) {
        els.status.textContent = msg || '';
        els.status.classList.toggle('mz-err', !!isErr);
    }

    /* ── Theme (light / dark / sepia) — shared with main app ──────── */
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
            saved = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches
                ? 'dark' : 'light';
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
        const title = { light: 'الوضع الليلي', dark: 'الوضع البُنّي (السيبيا)', sepia: 'الوضع النهاري' }[theme] || '';
        els.themeToggle.querySelector('i').className = icon;
        els.themeToggle.title = title;
    }

    /* ── Persist / load shared settings ───────────────────────────── */
    function saveSetting(key, value) {
        localStorage.setItem(key, String(value));
    }

    function loadSettings() {
        // Justify slider — synced with quranApp_khattJustify (default 50)
        const rawJ = parseInt(localStorage.getItem('quranApp_khattJustify') ?? '50', 10);
        state.justify = Number.isFinite(rawJ) ? Math.max(0, Math.min(100, rawJ)) : 50;
        els.justify.value = state.justify;
        updateJustifyLabel();

        // Tajweed — synced with quranApp_tajweedEnabled
        state.tajweedOn = localStorage.getItem('quranApp_tajweedEnabled') === 'true';
        syncTajweedButton();

        // Mushaf source — remembered locally
        const savedSrc = localStorage.getItem('mz_src');
        if (savedSrc === 'qpc_v1' || savedSrc === 'digital_khatt') {
            state.src = savedSrc;
            els.src.value = savedSrc;
        }
        applySrcClass();
    }

    /* ── Arabic-Indic digit helper ─────────────────────────────────── */
    const toAr = n => String(n).replace(/[0-9]/g, d => '٠١٢٣٤٥٦٧٨٩'[d]);

    /* ── Justify helpers ───────────────────────────────────────────── */
    function updateJustifyLabel() {
        els.justifyVal.textContent = toAr(state.justify) + '٪';
    }

    /* ── Surah list ────────────────────────────────────────────────── */
    async function loadSurahs() {
        const resp = await fetch('/api/surahs');
        const data = await resp.json();
        state.surahs = Array.isArray(data) ? data : [];
        els.surah.innerHTML = state.surahs.map(s => {
            const num  = s.number ?? s;
            const name = s.name ?? `سورة ${num}`;
            return `<option value="${num}">${toAr(num)}. ${name}</option>`;
        }).join('');
    }

    /* ── Load per-surah timing + populate ayah selects ────────────── */
    async function loadSurahMemo(surah) {
        setStatus('جارٍ تحميل بيانات السورة…');
        const resp = await fetch(`/api/memorization/${surah}`);
        if (!resp.ok) throw new Error('memo load failed');
        const data = await resp.json();
        state.memo = data;
        state.surah = surah;
        state.verseByAyah = new Map(data.verses.map(v => [v.ayah, v]));

        const opts = data.verses.map(v => `<option value="${v.ayah}">${toAr(v.ayah)}</option>`).join('');
        els.from.innerHTML = opts;
        els.to.innerHTML   = opts;

        // Restore saved last position if this is the right surah
        const saved = localStorage.getItem('mz_last_pos');
        if (saved) {
            const [savedSurah, savedFrom] = saved.split(':').map(Number);
            if (savedSurah === surah && data.verses.some(v => v.ayah === savedFrom)) {
                els.from.value = String(savedFrom);
            } else {
                els.from.value = String(data.verses[0].ayah);
            }
        } else {
            els.from.value = String(data.verses[0].ayah);
        }
        autoSetTo(parseInt(els.from.value, 10), data.verses);

        els.audio.src = data.audio_url;
        els.audio.load();
        setStatus('');
    }

    /* ── Auto-advance "to" when "from" changes ─────────────────────── */
    const DEFAULT_RANGE = 4; // verses after "from" to include by default

    function autoSetTo(fromAyah, verses) {
        const toVal = parseInt(els.to.value, 10);
        if (toVal >= fromAyah) return; // already valid, leave it
        const list = verses || [...state.verseByAyah.values()].sort((a, b) => a.ayah - b.ayah);
        const target = fromAyah + DEFAULT_RANGE;
        const best = list
            .map(v => v.ayah)
            .filter(a => a >= fromAyah)
            .reduce((acc, a) => (a <= target ? a : acc), fromAyah);
        els.to.value = String(best);
    }

    /* ── Selection helpers ─────────────────────────────────────────── */
    function selectedAyahRange() {
        let a = parseInt(els.from.value, 10);
        let b = parseInt(els.to.value, 10);
        if (!Number.isFinite(a)) a = 1;
        if (!Number.isFinite(b)) b = a;
        if (b < a) { const t = a; a = b; b = t; }
        return [a, b];
    }

    function rebuildSelectedKeys() {
        const [a, b] = selectedAyahRange();
        state.selectedKeys = new Set();
        for (let k = a; k <= b; k++) state.selectedKeys.add(`${state.surah}:${k}`);
    }

    /* ── Mushaf source ─────────────────────────────────────────────── */
    function applySrcClass() {
        els.page.classList.toggle('mz-src-qpc-v1',      state.src === 'qpc_v1');
        els.page.classList.toggle('mz-src-digital-khatt', state.src === 'digital_khatt');
    }

    function pageApiBase() {
        return state.src === 'qpc_v1' ? '/api/qpc-v1' : '/api/digital-khatt';
    }

    /* ── Page fetching ─────────────────────────────────────────────── */
    async function fetchPageByAyah(surah, ayah) {
        const resp = await fetch(`${pageApiBase()}/page-by-ayah/${surah}/${ayah}`);
        if (!resp.ok) throw new Error('page load failed');
        return resp.json();
    }
    async function fetchPageByNumber(pageNumber) {
        const resp = await fetch(`${pageApiBase()}/page/${pageNumber}`);
        if (!resp.ok) throw new Error('page load failed');
        return resp.json();
    }

    /* ── Page rendering ────────────────────────────────────────────── */
    function renderPage(payload) {
        state.page       = payload;
        state.pageNumber = payload.page_number;
        if (els.empty) els.empty.style.display = 'none';

        const frag = document.createDocumentFragment();
        (payload.lines || []).forEach(line => {
            const lineEl = document.createElement('div');
            lineEl.className = 'mz-line';

            const type = line.line_type;
            if (type === 'surah_name') {
                const inner = document.createElement('div');
                inner.className = 'mz-line-surah';
                inner.textContent = line.display_text || '';
                lineEl.appendChild(inner);
            } else if (type === 'basmallah') {
                const inner = document.createElement('div');
                inner.className = 'mz-line-basmala';
                inner.textContent = line.display_text || '';
                lineEl.appendChild(inner);
            } else {
                const inner = document.createElement('div');
                inner.className = 'mz-line-inner';
                const words = line.words || [];
                if (words.length) {
                    // Track word position within each ayah for tajweed mapping
                    const ayahWPos = new Map();
                    words.forEach((w, i) => {
                        const span = document.createElement('span');
                        span.className = 'mz-word';
                        span.textContent = w.text || '';
                        if (w.surah != null && w.ayah != null) {
                            const key = `${w.surah}:${w.ayah}`;
                            span.dataset.key  = key;
                            const pos = ayahWPos.get(key) ?? 0;
                            span.dataset.wpos = String(pos);
                            ayahWPos.set(key, pos + 1);
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

        els.page.innerHTML = '';
        els.page.appendChild(frag);

        // Footer
        els.footPage.textContent  = `صفحة ${toAr(payload.page_number)}`;
        const surahName = surahNameOf(payload.anchor_surah_number);
        els.footSurah.textContent = surahName ? `سورة ${surahName}` : '';
        const isOld = payload.source === 'qpc_v1';
        els.footJuz.textContent   = isOld ? 'مصحف المدينة ١٤٠٥' : 'مصحف المدينة';

        applySrcClass();
        applyFontSize();
        applySelectionHighlight();
        requestAnimationFrame(justifyLines);
        if (state.tajweedOn) applyTajweedToPage();
        updateNavButtons();
    }

    function surahNameOf(num) {
        const s = state.surahs.find(x => (x.number ?? x) === num);
        return s ? (s.name ?? '') : '';
    }

    /* ── Justification ─────────────────────────────────────────────── */
    function justifyLines() {
        const jFrac = state.justify / 100;
        els.page.querySelectorAll('.mz-line').forEach(lineEl => {
            const inner = lineEl.querySelector('.mz-line-inner');
            if (!inner) return;
            inner.style.transform = 'none';
            const natural = inner.scrollWidth;
            if (!natural) return;
            const avail     = lineEl.clientWidth;
            const isJustify = lineEl.dataset.justify === '1';
            let scale;
            if (isJustify) {
                const fullScale = Math.max(0.35, Math.min(1.9, avail / natural));
                if (natural > avail) {
                    // Line overflows: always shrink to fit regardless of slider
                    scale = fullScale;
                } else {
                    // Line fits: interpolate between 1× and full justify
                    scale = 1 + (fullScale - 1) * jFrac;
                }
            } else {
                // Centered line (surah header, short last line): only shrink if needed
                scale = natural > avail ? Math.max(0.35, avail / natural) : 1;
            }
            inner.style.transform = `scaleX(${scale})`;
        });
    }

    function applyFontSize() {
        const h = els.page.clientHeight || 1;
        const linesPerPage = (state.page && state.page.lines_per_page) || 15;
        const lineH = h / linesPerPage;
        const fs    = Math.max(12, Math.round(lineH * 0.6));
        els.page.style.setProperty('--dk-fs', fs + 'px');
    }

    /* ── Highlighting ──────────────────────────────────────────────── */
    function applySelectionHighlight() {
        const hasSel = state.selectedKeys.size > 0;
        els.page.classList.toggle('mz-has-selection', hasSel);
        els.page.querySelectorAll('.mz-word').forEach(w => {
            const k = w.dataset.key;
            w.classList.toggle('mz-sel', !!k && state.selectedKeys.has(k));
        });
        if (state.activeKey) markActive(state.activeKey);
    }

    function markActive(key) {
        state.activeKey = key;
        els.page.querySelectorAll('.mz-word.mz-act').forEach(w => w.classList.remove('mz-act'));
        if (!key) return;
        els.page.querySelectorAll(`.mz-word[data-key="${key}"]`).forEach(w => w.classList.add('mz-act'));
    }

    async function ensureVerseVisible(surah, ayah) {
        const key = `${surah}:${ayah}`;
        if (els.page.querySelector(`.mz-word[data-key="${key}"]`)) return true;
        try {
            const payload = await fetchPageByAyah(surah, ayah);
            renderPage(payload);
            return !!els.page.querySelector(`.mz-word[data-key="${key}"]`);
        } catch (e) {
            return false;
        }
    }

    /* ── Tajweed ───────────────────────────────────────────────────── */
    function syncTajweedButton() {
        els.tajweed.classList.toggle('mz-on', state.tajweedOn);
        els.tajweed.setAttribute('aria-pressed', String(state.tajweedOn));
        els.page.classList.toggle('mz-tajweed', state.tajweedOn);
    }

    // Parse the tajweed API HTML into an array of primary rule names, one per word.
    function parseTajweedWordClasses(html) {
        const div = document.createElement('div');
        div.innerHTML = html;
        const wordClasses = [];
        let curClasses = new Set();
        let hasText    = false;

        function flush() {
            if (hasText) {
                wordClasses.push(curClasses.size > 0 ? [...curClasses][0] : '');
                curClasses = new Set();
                hasText = false;
            }
        }

        div.childNodes.forEach(node => {
            if (node.nodeType === Node.TEXT_NODE) {
                const parts = node.textContent.split(' ');
                parts.forEach((part, i) => {
                    if (i > 0) flush();
                    if (part) hasText = true;
                });
            } else if (node.nodeName === 'TAJWEED') {
                const cls  = node.getAttribute('class') || '';
                const parts = node.textContent.split(' ');
                parts.forEach((part, i) => {
                    if (i > 0) flush();
                    if (part) {
                        hasText = true;
                        if (cls) curClasses.add(cls);
                    }
                });
            }
        });
        flush();
        return wordClasses;
    }

    async function applyTajweedToPage() {
        if (!state.tajweedOn) return;

        // Collect word spans grouped by verse key, preserving DOM order
        const ayahSpans = new Map(); // 'surah:ayah' → [span, ...]
        els.page.querySelectorAll('.mz-word[data-key]').forEach(span => {
            const key = span.dataset.key;
            if (!ayahSpans.has(key)) ayahSpans.set(key, []);
            ayahSpans.get(key).push(span);
        });

        for (const [key, spans] of ayahSpans) {
            let classes;
            if (state.tajweedCache.has(key)) {
                classes = state.tajweedCache.get(key);
            } else {
                const [surah, ayah] = key.split(':');
                try {
                    const resp = await fetch(`/api/tajweed/${surah}/${ayah}`);
                    if (!resp.ok) continue;
                    const data = await resp.json();
                    classes = parseTajweedWordClasses(data.html);
                    state.tajweedCache.set(key, classes);
                } catch (e) { continue; }
            }
            spans.forEach((span, i) => {
                // Strip old tajweed classes
                [...span.classList].forEach(c => { if (c.startsWith('tj-')) span.classList.remove(c); });
                const cls = classes[i] || '';
                if (cls) span.classList.add('tj-' + cls);
            });
        }
    }

    function clearTajweedFromPage() {
        els.page.querySelectorAll('.mz-word').forEach(span => {
            [...span.classList].forEach(c => { if (c.startsWith('tj-')) span.classList.remove(c); });
        });
    }

    /* ── Manual page navigation ────────────────────────────────────── */
    function updateNavButtons() {
        els.prev.disabled = !state.pageNumber || state.pageNumber <= PAGE_MIN;
        els.next.disabled = !state.pageNumber || state.pageNumber >= PAGE_MAX;
    }
    async function gotoPage(n) {
        n = Math.max(PAGE_MIN, Math.min(PAGE_MAX, n));
        try {
            setStatus('جارٍ تحميل الصفحة…');
            const payload = await fetchPageByNumber(n);
            renderPage(payload);
            setStatus('');
        } catch (e) {
            setStatus('تعذّر تحميل الصفحة', true);
        }
    }

    /* ── Audio schedule + playback ─────────────────────────────────── */
    function buildSchedule() {
        const [a, b] = selectedAyahRange();
        const reps = parseInt(els.reps.value, 10) || 1;
        const steps = [];
        for (let ayah = a; ayah <= b; ayah++) {
            const v = state.verseByAyah.get(ayah);
            if (!v) continue;
            for (let r = 0; r < reps; r++) {
                steps.push({ ayah, start: v.start, end: v.end, rep: r + 1, repTotal: reps });
            }
        }
        return steps;
    }

    function startMonitor() {
        stopMonitor();
        state.monitorId = setInterval(() => {
            if (state.pendingSeek || state.stepIdx < 0 || els.audio.paused) return;
            const step = state.schedule[state.stepIdx];
            if (!step) return;
            updateProgress();
            if (els.audio.currentTime >= step.end - EPS) advanceStep();
        }, 40);
    }
    function stopMonitor() {
        if (state.monitorId) { clearInterval(state.monitorId); state.monitorId = null; }
    }

    function seekTo(t) {
        state.pendingSeek = true;
        const apply = () => {
            try { els.audio.currentTime = t; } catch (e) {}
            els.audio.play().catch(() => {});
        };
        if (els.audio.readyState >= 1) apply();
        else els.audio.addEventListener('loadedmetadata', apply, { once: true });
    }

    async function playStep(k) {
        if (k >= state.schedule.length) {
            if (els.loop.checked) { k = 0; }
            else { finishPlayback(); return; }
        }
        state.stepIdx = k;
        const step = state.schedule[k];
        await ensureVerseVisible(state.surah, step.ayah);
        markActive(`${state.surah}:${step.ayah}`);
        scrollActiveIntoView();
        seekTo(step.start);

        const repTxt = step.repTotal > 1 ? ` · تكرار ${toAr(step.rep)}/${toAr(step.repTotal)}` : '';
        els.now.textContent = `${surahNameOf(state.surah)} · آية ${toAr(step.ayah)}${repTxt}`;

        // Save position so main app and next session can continue here
        saveSetting('mz_last_pos', `${state.surah}:${step.ayah}`);
        saveSetting('quranApp_lastPosition', `${state.surah}:${step.ayah}`);
    }
    const advanceStep = () => playStep(state.stepIdx + 1);

    function scrollActiveIntoView() {
        const first = els.page.querySelector('.mz-word.mz-act');
        if (first) first.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    }

    function updateProgress() {
        const step = state.schedule[state.stepIdx];
        if (!step) return;
        const span = Math.max(0.001, step.end - step.start);
        const frac = Math.max(0, Math.min(1, (els.audio.currentTime - step.start) / span));
        const overall = (state.stepIdx + frac) / state.schedule.length;
        els.progressFill.style.width = `${Math.round(overall * 100)}%`;
    }

    async function startPlayback() {
        rebuildSelectedKeys();
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
        setPlayIcon(true);
        startMonitor();
        playStep(0);
    }

    function finishPlayback() {
        state.playing = false;
        stopMonitor();
        els.audio.pause();
        setPlayIcon(false);
        markActive(null);
        els.progressFill.style.width = '100%';
        els.now.textContent = 'تم — أحسنت! 🌿';
        setTimeout(() => { if (!state.playing) els.progressFill.style.width = '0%'; }, 1200);
    }

    function stopPlayback() {
        state.playing = false;
        state.stepIdx = -1;
        stopMonitor();
        els.audio.pause();
        setPlayIcon(false);
        markActive(null);
        els.progressFill.style.width = '0%';
        els.player.classList.remove('mz-show');
        els.player.setAttribute('aria-hidden', 'true');
    }

    function togglePlay() {
        if (els.audio.paused) {
            if (state.stepIdx < 0) { playStep(0); }
            else { els.audio.play().catch(() => {}); }
            state.playing = true;
            setPlayIcon(true);
            startMonitor();
        } else {
            els.audio.pause();
            state.playing = false;
            setPlayIcon(false);
        }
    }
    function setPlayIcon(playing) {
        const i = els.play.querySelector('i');
        if (i) i.className = playing ? 'fas fa-pause' : 'fas fa-play';
    }

    els.audio.addEventListener('seeked', () => { state.pendingSeek = false; });
    els.audio.addEventListener('ended', () => {
        if (state.stepIdx >= 0 && state.stepIdx < state.schedule.length) advanceStep();
    });

    /* ── Wiring ────────────────────────────────────────────────────── */
    async function onSurahChange() {
        stopPlayback();
        const surah = parseInt(els.surah.value, 10) || 1;
        try {
            await loadSurahMemo(surah);
            saveSetting('mz_last_pos', `${surah}:1`);
        } catch (e) {
            setStatus('تعذّر تحميل بيانات السورة', true);
        }
    }

    function bindEvents() {
        els.surah.addEventListener('change', onSurahChange);

        // "from" changes → auto-advance "to" if it's now before "from"
        els.from.addEventListener('change', () => {
            const fromAyah = parseInt(els.from.value, 10);
            autoSetTo(fromAyah);
            if (state.page) {
                rebuildSelectedKeys();
                applySelectionHighlight();
            }
        });

        // "to" changes → keep selection highlight live
        els.to.addEventListener('change', () => {
            if (!state.page) return;
            rebuildSelectedKeys();
            applySelectionHighlight();
        });

        els.start.addEventListener('click', () => {
            els.start.disabled = true;
            startPlayback().finally(() => { els.start.disabled = false; });
        });

        els.play.addEventListener('click', togglePlay);
        els.stop.addEventListener('click', stopPlayback);
        els.prev.addEventListener('click', () => state.pageNumber && gotoPage(state.pageNumber - 1));
        els.next.addEventListener('click', () => state.pageNumber && gotoPage(state.pageNumber + 1));

        // Progress bar seek
        els.progress.addEventListener('click', (e) => {
            if (!state.schedule.length) return;
            const rect = els.progress.getBoundingClientRect();
            const frac = Math.max(0, Math.min(1, (rect.right - e.clientX) / rect.width));
            const target = Math.min(state.schedule.length - 1, Math.floor(frac * state.schedule.length));
            playStep(target);
        });

        // Tajweed toggle
        els.tajweed.addEventListener('click', () => {
            state.tajweedOn = !state.tajweedOn;
            syncTajweedButton();
            saveSetting('quranApp_tajweedEnabled', state.tajweedOn);
            if (state.tajweedOn) {
                applyTajweedToPage();
            } else {
                clearTajweedFromPage();
            }
        });

        // Justify slider
        els.justify.addEventListener('input', () => {
            state.justify = parseInt(els.justify.value, 10);
            updateJustifyLabel();
            saveSetting('quranApp_khattJustify', state.justify);
            if (state.page) requestAnimationFrame(justifyLines);
        });

        // Mushaf source selector
        els.src.addEventListener('change', () => {
            state.src = els.src.value;
            saveSetting('mz_src', state.src);
            // Reload the current page with the new source, if a page is already showing
            if (state.pageNumber) {
                stopPlayback();
                state.tajweedCache.clear();
                gotoPage(state.pageNumber);
            }
        });

        let resizeId = 0;
        window.addEventListener('resize', () => {
            clearTimeout(resizeId);
            resizeId = setTimeout(() => { if (state.page) { applyFontSize(); justifyLines(); } }, 120);
        });
    }

    async function renderSelection() {
        rebuildSelectedKeys();
        const [a] = selectedAyahRange();
        setStatus('جارٍ فتح صفحة المصحف…');
        const ok = await ensureVerseVisible(state.surah, a);
        if (!ok) { setStatus('تعذّر تحديد موضع الآية في المصحف', true); return; }
        applySelectionHighlight();
        setStatus('');
    }

    // Optional deep link: /memorize?surah=2&from=255&to=255
    function applyDeepLink() {
        const p = new URLSearchParams(location.search);
        const surah = parseInt(p.get('surah'), 10);
        if (!surah) return false;
        if ([...els.surah.options].some(o => +o.value === surah)) els.surah.value = surah;
        return true;
    }

    /* ── Init ──────────────────────────────────────────────────────── */
    async function init() {
        initTheme();
        loadSettings();
        bindEvents();
        try {
            await loadSurahs();

            // Restore last-used surah from local state
            const savedPos = localStorage.getItem('mz_last_pos');
            if (savedPos) {
                const savedSurah = parseInt(savedPos.split(':')[0], 10);
                if (savedSurah && [...els.surah.options].some(o => +o.value === savedSurah)) {
                    els.surah.value = String(savedSurah);
                }
            }

            const hasDeepLink = applyDeepLink();
            await loadSurahMemo(parseInt(els.surah.value, 10) || 1);

            if (hasDeepLink) {
                const p = new URLSearchParams(location.search);
                const from = parseInt(p.get('from'), 10);
                const to   = parseInt(p.get('to'),   10);
                if (from && [...els.from.options].some(o => +o.value === from)) els.from.value = from;
                if (to   && [...els.to.options].some(o   => +o.value === to))   els.to.value   = to;
                await renderSelection();
            }
        } catch (e) {
            setStatus('تعذّر تهيئة الصفحة', true);
        }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
