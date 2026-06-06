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
     GET /api/digital-khatt/page-by-ayah/<s>/<a>      mushaf page payload (lines/words/justification)
     GET /api/digital-khatt/page/<n>                  mushaf page payload by number
   ═══════════════════════════════════════════════════════════════════ */
(function () {
    'use strict';

    const $ = id => document.getElementById(id);

    const els = {
        surah: $('mz-surah'),
        from: $('mz-from'),
        to: $('mz-to'),
        reps: $('mz-reps'),
        loop: $('mz-loop'),
        start: $('mz-start'),
        status: $('mz-status'),
        page: $('mz-page'),
        empty: $('mz-empty'),
        footSurah: $('mz-foot-surah'),
        footPage: $('mz-foot-page'),
        footJuz: $('mz-foot-juz'),
        prev: $('mz-prev'),
        next: $('mz-next'),
        player: $('mz-player'),
        play: $('mz-play'),
        stop: $('mz-stop'),
        now: $('mz-now'),
        progress: $('mz-progress'),
        progressFill: $('mz-progress-fill'),
        audio: $('mz-audio'),
        themeToggle: $('mz-theme-toggle'),
    };

    const EPS = 0.05;       // seconds of slack at a segment end
    const PAGE_MIN = 1, PAGE_MAX = 604;

    const state = {
        surahs: [],
        surah: 1,
        memo: null,             // /api/memorization payload (verses + audio_url)
        verseByAyah: new Map(), // ayah -> verse {start,end,...}
        selectedKeys: new Set(),// "surah:ayah" currently highlighted as target
        page: null,             // current rendered page payload
        pageNumber: null,
        schedule: [],           // [{ayah, start, end}]
        stepIdx: -1,
        monitorId: null,
        pendingSeek: false,
        playing: false,
        activeKey: null,
    };

    /* ── Status helper ─────────────────────────────────────────────── */
    function setStatus(msg, isErr) {
        els.status.textContent = msg || '';
        els.status.classList.toggle('mz-err', !!isErr);
    }

    /* ── Theme ─────────────────────────────────────────────────────── */
    function initTheme() {
        const saved = localStorage.getItem('mzTheme');
        const prefersDark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
        const dark = saved ? saved === 'dark' : prefersDark;
        document.body.classList.toggle('mz-dark', dark);
        syncThemeIcon();
        els.themeToggle.addEventListener('click', () => {
            const isDark = document.body.classList.toggle('mz-dark');
            localStorage.setItem('mzTheme', isDark ? 'dark' : 'light');
            syncThemeIcon();
        });
    }
    function syncThemeIcon() {
        const dark = document.body.classList.contains('mz-dark');
        els.themeToggle.querySelector('i').className = dark ? 'fas fa-sun' : 'fas fa-moon';
    }

    /* ── Arabic-Indic digit helper for labels ──────────────────────── */
    const toAr = n => String(n).replace(/[0-9]/g, d => '٠١٢٣٤٥٦٧٨٩'[d]);

    /* ── Surah list ────────────────────────────────────────────────── */
    async function loadSurahs() {
        const resp = await fetch('/api/surahs');
        const data = await resp.json();
        state.surahs = Array.isArray(data) ? data : [];
        els.surah.innerHTML = state.surahs.map(s => {
            const num = s.number ?? s;
            const name = s.name ?? `سورة ${num}`;
            return `<option value="${num}">${toAr(num)}. ${name}</option>`;
        }).join('');
    }

    /* ── Load per-surah memorization timing + populate ayah selects ── */
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
        els.to.innerHTML = opts;
        els.from.value = data.verses[0].ayah;
        els.to.value = data.verses[Math.min(data.verses.length - 1, 4)].ayah; // first ~5 verses

        els.audio.src = data.audio_url; // host whitelisted in CSP media-src
        els.audio.load();
        setStatus('');
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

    /* ── Page rendering ────────────────────────────────────────────── */
    async function fetchPageByAyah(surah, ayah) {
        const resp = await fetch(`/api/digital-khatt/page-by-ayah/${surah}/${ayah}`);
        if (!resp.ok) throw new Error('page load failed');
        return resp.json();
    }
    async function fetchPageByNumber(pageNumber) {
        const resp = await fetch(`/api/digital-khatt/page/${pageNumber}`);
        if (!resp.ok) throw new Error('page load failed');
        return resp.json();
    }

    function renderPage(payload) {
        state.page = payload;
        state.pageNumber = payload.page_number;
        els.empty && (els.empty.style.display = 'none');

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
                    words.forEach((w, i) => {
                        const span = document.createElement('span');
                        span.className = 'mz-word';
                        span.textContent = w.text || '';
                        if (w.surah != null && w.ayah != null) {
                            span.dataset.key = `${w.surah}:${w.ayah}`;
                        }
                        inner.appendChild(span);
                        if (i < words.length - 1) inner.appendChild(document.createTextNode(' '));
                    });
                    // justified body lines stretch edge-to-edge; centered/short
                    // lines (end of surah) keep their natural width.
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
        els.footPage.textContent = `صفحة ${toAr(payload.page_number)}`;
        const surahName = surahNameOf(payload.anchor_surah_number);
        els.footSurah.textContent = surahName ? `سورة ${surahName}` : '';
        els.footJuz.textContent = payload.layout_name ? 'مصحف المدينة' : '';

        applyFontSize();
        applySelectionHighlight();
        requestAnimationFrame(justifyLines);
        updateNavButtons();
    }

    function surahNameOf(num) {
        const s = state.surahs.find(x => (x.number ?? x) === num);
        return s ? (s.name ?? '') : '';
    }

    // Scale body lines horizontally so each fills the page width (Madinah-style
    // full justification), using DOM measurement of the natural line width.
    function justifyLines() {
        const lines = els.page.querySelectorAll('.mz-line');
        lines.forEach(lineEl => {
            const inner = lineEl.querySelector('.mz-line-inner');
            if (!inner) return;
            inner.style.transform = 'none';
            const natural = inner.scrollWidth;
            if (!natural) return;
            const avail = lineEl.clientWidth;
            const justify = lineEl.dataset.justify === '1';
            let scale;
            if (justify) {
                scale = avail / natural;
                scale = Math.max(0.35, Math.min(1.9, scale));
            } else {
                // centered: only shrink if it would overflow
                scale = natural > avail ? avail / natural : 1;
            }
            inner.style.transform = `scaleX(${scale})`;
        });
    }

    function applyFontSize() {
        // Fit 15 lines into the page height; scaleX handles width.
        const h = els.page.clientHeight || 1;
        const linesPerPage = (state.page && state.page.lines_per_page) || 15;
        const lineH = h / linesPerPage;
        const fs = Math.max(12, Math.round(lineH * 0.6));
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

    // Make sure the verse `surah:ayah` is on the rendered page; fetch its page
    // if not. Returns true when (after any load) the verse is visible.
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

        // Show the page of the first selected verse with the target highlighted.
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
        } catch (e) {
            setStatus('تعذّر تحميل بيانات السورة', true);
        }
    }

    function bindEvents() {
        els.surah.addEventListener('change', onSurahChange);
        els.start.addEventListener('click', () => {
            els.start.disabled = true;
            startPlayback().finally(() => { els.start.disabled = false; });
        });
        els.play.addEventListener('click', togglePlay);
        els.stop.addEventListener('click', stopPlayback);
        els.prev.addEventListener('click', () => state.pageNumber && gotoPage(state.pageNumber - 1));
        els.next.addEventListener('click', () => state.pageNumber && gotoPage(state.pageNumber + 1));

        // Seek by clicking the progress bar (within the whole schedule).
        els.progress.addEventListener('click', (e) => {
            if (!state.schedule.length) return;
            const rect = els.progress.getBoundingClientRect();
            // RTL: progress fills from the right edge.
            const frac = Math.max(0, Math.min(1, (rect.right - e.clientX) / rect.width));
            const target = Math.min(state.schedule.length - 1, Math.floor(frac * state.schedule.length));
            playStep(target);
        });

        // Keep highlight in sync if the user tweaks the range before playing.
        [els.from, els.to].forEach(sel => sel.addEventListener('change', () => {
            if (!state.page) return;
            rebuildSelectedKeys();
            applySelectionHighlight();
        }));

        let resizeId = 0;
        window.addEventListener('resize', () => {
            clearTimeout(resizeId);
            resizeId = setTimeout(() => { if (state.page) { applyFontSize(); justifyLines(); } }, 120);
        });
    }

    // Render the selected range's mushaf page with the target verses
    // highlighted, without starting audio (used by deep links and the initial
    // "show me where these verses are" affordance).
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
        if ([...els.surah.options].some(o => +o.value === surah)) {
            els.surah.value = surah;
        }
        return true;
    }

    /* ── Init ──────────────────────────────────────────────────────── */
    async function init() {
        initTheme();
        bindEvents();
        try {
            await loadSurahs();
            const hasDeepLink = applyDeepLink();
            await loadSurahMemo(parseInt(els.surah.value, 10) || 1);
            if (hasDeepLink) {
                const p = new URLSearchParams(location.search);
                const from = parseInt(p.get('from'), 10);
                const to = parseInt(p.get('to'), 10);
                if (from && [...els.from.options].some(o => +o.value === from)) els.from.value = from;
                if (to && [...els.to.options].some(o => +o.value === to)) els.to.value = to;
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
