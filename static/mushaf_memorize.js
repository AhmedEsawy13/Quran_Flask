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
        headJuz:      $('mz-head-juz'),
        headSurah:    $('mz-head-surah'),
        footPage:     $('mz-foot-page'),
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
        tajweedCache: new Map(), // 'surah:ayah' → parsed per-word coloured runs
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

        // Mushaf source — a local choice here wins; otherwise inherit the main
        // app's font so the two pages show the same mushaf by default.
        const savedSrc = localStorage.getItem('mz_src');
        if (savedSrc === 'qpc_v1' || savedSrc === 'digital_khatt') {
            state.src = savedSrc;
        } else {
            const mainFont = localStorage.getItem('quranApp_font');
            if (mainFont === 'old_madina') state.src = 'qpc_v1';
            else if (mainFont === 'digital_khatt') state.src = 'digital_khatt';
        }
        els.src.value = state.src;
        applySrcClass();
    }

    /* ── Arabic-Indic digit helper ─────────────────────────────────── */
    const toAr = n => String(n).replace(/[0-9]/g, d => '٠١٢٣٤٥٦٧٨٩'[d]);

    /* ── Juz lookup ────────────────────────────────────────────────────
       Standard 604-page Madinah mushaf juz boundaries (page each juz starts
       on). Both the 1421 and 1405 prints share these, so it works for either
       source. Juz label is shown in the running head, e.g. «الجزء الحادي عشر». */
    const JUZ_START_PAGE = [1, 22, 42, 62, 82, 102, 121, 142, 162, 182,
        201, 222, 242, 262, 282, 302, 322, 342, 362, 382,
        402, 422, 442, 462, 482, 502, 522, 542, 562, 582];
    const JUZ_NAME = ['الأول', 'الثاني', 'الثالث', 'الرابع', 'الخامس', 'السادس',
        'السابع', 'الثامن', 'التاسع', 'العاشر', 'الحادي عشر', 'الثاني عشر',
        'الثالث عشر', 'الرابع عشر', 'الخامس عشر', 'السادس عشر', 'السابع عشر',
        'الثامن عشر', 'التاسع عشر', 'العشرون', 'الحادي والعشرون', 'الثاني والعشرون',
        'الثالث والعشرون', 'الرابع والعشرون', 'الخامس والعشرون', 'السادس والعشرون',
        'السابع والعشرون', 'الثامن والعشرون', 'التاسع والعشرون', 'الثلاثون'];
    function juzLabel(pageNumber) {
        let j = 1;
        for (let i = 0; i < JUZ_START_PAGE.length; i++) {
            if (pageNumber >= JUZ_START_PAGE[i]) j = i + 1; else break;
        }
        return `الجزء ${JUZ_NAME[j - 1]}`;
    }

    /* Verse-number ornament: quran_script stores the ayah marker as a bare
       Arabic-Indic digit. Prefixing U+06DD (END OF AYAH) makes the mushaf font
       draw the decorative circle around it, exactly like the main page. */
    const ARABIC_DIGITS_ONLY = /^[٠-٩]+$/;
    function withAyahOrnament(text) {
        return ARABIC_DIGITS_ONLY.test(text) ? '۝' + text : text;
    }

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

        // Word position within each ayah, counted across the WHOLE page (a verse
        // can wrap onto several lines), so tajweed colours align to the right word.
        const ayahWPos = new Map();

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
                        const text = withAyahOrnament(w.text || '');
                        span.textContent = text;
                        span.dataset.text = text; // original, for tajweed restore
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

        // Running head (juz · right, surah · left) + footer (page number · centre)
        els.footPage.textContent  = `صفحة ${toAr(payload.page_number)}`;
        const surahName = surahNameOf(payload.anchor_surah_number);
        els.headSurah.textContent = surahName ? `سورة ${surahName}` : '';
        els.headJuz.textContent   = juzLabel(payload.page_number);

        applySrcClass();
        applyFontSize();
        applySelectionHighlight();
        requestAnimationFrame(justifyLines);
        // Tajweed overlay rewrites each word's HTML and so changes its width;
        // re-justify once it has been applied.
        if (state.tajweedOn) applyTajweedToPage().then(() => requestAnimationFrame(justifyLines));
        updateNavButtons();
    }

    function surahNameOf(num) {
        const s = state.surahs.find(x => (x.number ?? x) === num);
        return s ? (s.name ?? '') : '';
    }

    /* ── Justification ─────────────────────────────────────────────── */
    /* Real kashida elongation via OpenType features — the exact mapping the
       main app's slider uses. Digital Khatt exposes 'jalt'/'cv01'/'cv02';
       the Old Madina (QPC v1) font exposes the 'jt0n'/'dc0n'/'kt0n' family. */
    function khattFeatureSettings(strength) {
        const s = Math.max(0, Math.min(100, Number(strength) || 0));
        if (s <= 0) return '';
        if (state.src === 'digital_khatt') {
            const levels = [
                `'jalt' 1`,
                `'jalt' 1, 'cv02' 1`,
                `'jalt' 1, 'cv01' 1`,
                `'jalt' 1, 'cv01' 1, 'cv02' 1`,
            ];
            const level = Math.min(levels.length, Math.max(1, Math.ceil((s / 100) * levels.length)));
            return levels[level - 1] || '';
        }
        // Old Madina: graduated justification-alternate feature sequence
        const seq = [];
        for (let lvl = 1; lvl <= 5; lvl += 1) {
            for (const t of ['jt', 'dc', 'kt']) seq.push(`${t}0${lvl}`);
        }
        const count = Math.round((s / 100) * seq.length);
        if (count <= 0) return '';
        return seq.slice(0, count).map(f => `'${f}'`).join(',');
    }

    function justifyLines() {
        const jFrac    = state.justify / 100;
        const features = khattFeatureSettings(state.justify);
        els.page.querySelectorAll('.mz-line').forEach(lineEl => {
            const inner = lineEl.querySelector('.mz-line-inner');
            if (!inner) return;
            inner.style.transform = 'none';
            inner.style.fontFeatureSettings = '';

            const avail     = lineEl.clientWidth;
            const isJustify = lineEl.dataset.justify === '1';
            const plain     = inner.scrollWidth;
            if (!plain) return;

            // Elongate the glyphs with kashida features first — but only when the
            // line both should be justified and has room to grow. This keeps the
            // stretch looking like a real mushaf rather than a horizontal squash.
            if (isJustify && features && plain < avail) {
                inner.style.fontFeatureSettings = features;
            }

            const natural = inner.scrollWidth;
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

    /* Per-letter tajweed overlay — ported verbatim from the main app so the
       colouring is identical here. The pipeline:
         1. /api/tajweed/<s>/<a> → source-orthography HTML with <tajweed> spans
         2. normalise (drop verse-number marker, reclassify منفصل)
         3. parse into per-word coloured letter runs
         4. align those runs onto the displayed QPC word and emit <tajweed> spans
            WITHOUT changing the displayed orthography.                          */

    function _isCombiningMark(cp) {
        return (cp >= 0x064B && cp <= 0x065F) || cp === 0x0670 ||
               (cp >= 0x06D6 && cp <= 0x06ED) || (cp >= 0x0610 && cp <= 0x061A) ||
               (cp >= 0x0653 && cp <= 0x0658) || cp === 0x06E5 || cp === 0x06E6;
    }

    // Fold orthographic variants so equivalent letters match across spellings.
    function _alignSkeleton(ch) {
        const cp = ch.codePointAt(0);
        if (cp === 0x0622 || cp === 0x0623 || cp === 0x0625 || cp === 0x0627 ||
            cp === 0x0671 || cp === 0x0621 || cp === 0x0624 || cp === 0x0626) return 'A';
        if (cp === 0x0649 || cp === 0x064A) return 'Y';
        if (cp === 0x0629) return 'H';
        return ch;
    }

    // Needleman–Wunsch: for each display-char, the source index it aligns to (-1 = none).
    function _alignDisplayToSource(srcChars, dispChars) {
        const n = srcChars.length, m = dispChars.length;
        const dp = Array.from({ length: n + 1 }, () => new Int32Array(m + 1));
        for (let i = 1; i <= n; i++) dp[i][0] = dp[i - 1][0] - 1;
        for (let j = 1; j <= m; j++) dp[0][j] = dp[0][j - 1] - 1;
        for (let i = 1; i <= n; i++) {
            for (let j = 1; j <= m; j++) {
                const sc = _alignSkeleton(srcChars[i - 1]) === _alignSkeleton(dispChars[j - 1]) ? 2 : -1;
                dp[i][j] = Math.max(dp[i - 1][j - 1] + sc, dp[i - 1][j] - 1, dp[i][j - 1] - 1);
            }
        }
        const res = new Array(m).fill(-1);
        let i = n, j = m;
        while (i > 0 && j > 0) {
            const sc = _alignSkeleton(srcChars[i - 1]) === _alignSkeleton(dispChars[j - 1]) ? 2 : -1;
            if (dp[i][j] === dp[i - 1][j - 1] + sc) { res[j - 1] = i - 1; i--; j--; }
            else if (dp[i][j] === dp[i - 1][j] - 1) { i--; }
            else { j--; }
        }
        return res;
    }

    function overlayTajweedOnDisplay(dispWord, parts) {
        const srcChars = [];
        const srcCls = [];
        for (const p of (parts || [])) {
            for (const ch of p.text) { srcChars.push(ch); srcCls.push(p.cls || ''); }
        }
        const dispChars = [...dispWord];
        const dcls = new Array(dispChars.length).fill('');
        if (srcChars.length && srcCls.some(c => c)) {
            const amap = _alignDisplayToSource(srcChars, dispChars);
            for (let j = 0; j < dispChars.length; j++) {
                const si = amap[j];
                if (si >= 0) dcls[j] = srcCls[si];
            }
            // Keep each base letter and its combining marks one colour.
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
            if (cl !== cur) {
                if (buf) html += cur ? `<tajweed class="${cur}">${esc(buf)}</tajweed>` : esc(buf);
                buf = ''; cur = cl;
            }
            buf += dispChars[j];
        }
        if (buf) html += cur ? `<tajweed class="${cur}">${esc(buf)}</tajweed>` : esc(buf);
        return html;
    }

    function _reclassifyMunfasilInHtml(html) {
        const _hamzaRe = /[ءأؤإئ]/;
        return (html || '').replace(
            /(<tajweed\s+class=["']?madda_obligatory["']?>)([\s\S]*?)(<\/tajweed>)([\s\S]*?)(?= |$)/g,
            (match, open, inner, close, afterInSameWord) => {
                if (!_hamzaRe.test(inner) && !_hamzaRe.test(afterInSameWord)) {
                    return `<tajweed class="madda_munfasil">${inner}</tajweed>${afterInSameWord}`;
                }
                return match;
            }
        );
    }

    function getNormalizedTajweedHtml(html) {
        return _reclassifyMunfasilInHtml(
            (html || '').replace(/<span[^>]*class=["']?end["']?[^>]*>.*?<\/span>/gi, '').trim()
        );
    }

    // Parse the normalised HTML into per-word coloured runs: [{parts:[{text,cls}]}]
    function parseTajweedIntoWords(html) {
        const tmp = document.createElement('div');
        tmp.innerHTML = html;

        const tokens = [];
        for (const node of tmp.childNodes) {
            if (node.nodeType === 3) {
                const t = node.textContent;
                if (t) tokens.push({ text: t, cls: '' });
            } else if (node.nodeType === 1) {
                const cls = (node.getAttribute('class') || '').trim();
                if (cls === 'end') continue;
                const t = node.textContent;
                if (t) tokens.push({ text: t, cls });
            }
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
        let segParts = [];
        let segRules = new Set();
        const flush = () => {
            const combined = segParts.map(p => p.text).join('');
            if (combined.trim()) {
                const _hamzaRe = /[ءأؤإئ]/;
                let finalParts = segParts;
                if (segRules.has('madda_obligatory')) {
                    const madIdx = segParts.map(p => p.cls).lastIndexOf('madda_obligatory');
                    const textInMad    = segParts[madIdx]?.text || '';
                    const textAfterMad = segParts.slice(madIdx + 1).map(p => p.text).join('');
                    if (!_hamzaRe.test(textInMad) && !_hamzaRe.test(textAfterMad)) {
                        finalParts = segParts.map(p =>
                            p.cls === 'madda_obligatory' ? { ...p, cls: 'madda_munfasil' } : p
                        );
                    }
                }
                segments.push({ parts: finalParts.map(p => ({ text: p.text, cls: p.cls })) });
            }
            segParts = [];
            segRules = new Set();
        };
        for (const sub of subTokens) {
            if (sub.text) {
                segParts.push({ text: sub.text, cls: sub.cls });
                if (sub.cls) segRules.add(sub.cls);
            }
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
            if (resp.ok) {
                const data = await resp.json();
                segments = parseTajweedIntoWords(getNormalizedTajweedHtml(data.html));
            }
        } catch (e) { segments = []; }
        state.tajweedCache.set(key, segments);
        return segments;
    }

    async function applyTajweedToPage() {
        if (!state.tajweedOn) return;

        // Group word spans by verse key; each span carries its position-in-verse.
        const ayahSpans = new Map(); // 'surah:ayah' → [span, ...]
        els.page.querySelectorAll('.mz-word[data-key]').forEach(span => {
            const key = span.dataset.key;
            if (!ayahSpans.has(key)) ayahSpans.set(key, []);
            ayahSpans.get(key).push(span);
        });

        for (const [key, spans] of ayahSpans) {
            const [surah, ayah] = key.split(':').map(Number);
            const segments = await getTajweedSegments(surah, ayah);
            if (!state.tajweedOn) return; // toggled off mid-fetch
            spans.forEach(span => {
                const wpos = parseInt(span.dataset.wpos, 10);
                const seg  = Number.isFinite(wpos) ? segments[wpos] : null;
                const disp = span.dataset.text || span.textContent || '';
                if (seg && seg.parts.some(p => p.cls)) {
                    span.innerHTML = overlayTajweedOnDisplay(disp, seg.parts);
                } else {
                    span.textContent = disp;
                }
            });
        }
    }

    function clearTajweedFromPage() {
        els.page.querySelectorAll('.mz-word').forEach(span => {
            span.textContent = span.dataset.text || span.textContent || '';
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
                applyTajweedToPage().then(() => requestAnimationFrame(justifyLines));
            } else {
                clearTajweedFromPage();
                requestAnimationFrame(justifyLines);
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

    // Optional deep link: /memorize?surah=2&from=255&to=255&src=qpc_v1
    function applyDeepLink() {
        const p = new URLSearchParams(location.search);
        const src = p.get('src');
        if (src === 'qpc_v1' || src === 'digital_khatt') {
            state.src = src;
            els.src.value = src;
            saveSetting('mz_src', src);
            applySrcClass();
        }
        const tj = p.get('tajweed');
        if (tj === '1' || tj === '0') {
            state.tajweedOn = tj === '1';
            syncTajweedButton();
            saveSetting('quranApp_tajweedEnabled', state.tajweedOn);
        }
        const jq = parseInt(p.get('justify'), 10);
        if (Number.isFinite(jq)) {
            state.justify = Math.max(0, Math.min(100, jq));
            els.justify.value = state.justify;
            updateJustifyLabel();
            saveSetting('quranApp_khattJustify', state.justify);
        }
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
