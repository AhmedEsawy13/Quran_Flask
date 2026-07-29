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
     GET /api/digital-khatt/page(-by-ayah)/…  Madinah 1441 (QPC v4) page
     GET /api/qpc-v2/page(-by-ayah)/…         Madinah 1421 (Digital Khatt V2) page
     GET /api/qpc-v1/page(-by-ayah)/…         Madinah 1405 (QPC v1) page
     GET /api/tajweed/<s>/<a>                  tajweed-annotated verse HTML
     GET /api/mushaf-versions                  waqf print list
   ═══════════════════════════════════════════════════════════════════ */
(function () {
    'use strict';

    const $ = id => document.getElementById(id);
    const { getWaqfDisplayData, stripEmbeddedWaqf } = window.AtharMushaf;

    const els = {
        bar:         $('mz-bar'),
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
        prev:        $('mz-prev'),
        next:        $('mz-next'),
        player:      $('mz-player'),
        play:        $('mz-play'),
        stop:        $('mz-stop'),
        prevStep:    $('mz-prev-step'),
        nextStep:    $('mz-next-step'),
        now:         $('mz-now'),
        remaining:   $('mz-remaining'),
        playerReciter: $('mz-player-reciter'),
        timeCur:     $('mz-time-cur'),
        timeDur:     $('mz-time-dur'),
        progress:    $('mz-progress'),
        progressFill:$('mz-progress-fill'),
        audio:       $('mz-audio'),
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
    const MADINAH_SOURCES = new Set(['qpc_v1', 'qpc_v2', 'digital_khatt']);
    const DIGITAL_KHATT_SOURCES = new Set(['qpc_v2', 'digital_khatt']);
    const isMadinahSource = source => MADINAH_SOURCES.has(source);
    const isDigitalKhattSource = source => DIGITAL_KHATT_SOURCES.has(source);

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
        playbackGeneration: 0,
        finishTimer: null,
        pendingSeek: false,
        playing: false,
        activeKey: null,
        stepVerses: [],         // verses overlapping the current step's [start,end]
        activeWords: [],        // flat {key,wpos,start,end} for word-by-word follow
        curWordId: '',          // currently lit word ("key#wpos") — avoids churn
        curFollowAyah: null,    // verse the audio is currently inside
        followFlipping: false,  // guard: one page-flip at a time while following
        selectionRange: null,   // committed [startAyah, endAyah], independent of hidden controls
        rangeDraft: null,       // { anchor, previousRange } while waiting for the end verse
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
        syncToolbar();
    }
    function revealVerse(key) {
        if (!key) return;
        wordsInSpread(`.mz-word[data-key="${key}"]`).forEach(w => w.classList.add('mz-reveal'));
    }
    function setFocusMode(on) {
        state.focusMode = !!on;
        document.body.classList.toggle('mz-focus', state.focusMode);
        requestAnimationFrame(() => { if (state.focusPage) { sizePages(); applyFontSize(true); justifyLines(); } });
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
        if (els.tbTajweed) {
            els.tbTajweed.classList.toggle('mz-on', state.tajweedOn);
            els.tbTajweed.setAttribute('aria-pressed', String(state.tajweedOn));
        }
        if (els.tbHide) {
            els.tbHide.classList.toggle('mz-on', state.hideText);
            els.tbHide.setAttribute('aria-pressed', String(state.hideText));
        }
        if (els.tbLayout) {
            const single = state.layoutMode === 'single';
            els.tbLayout.classList.toggle('mz-on', single);
            els.tbLayout.setAttribute('aria-pressed', String(single));
            const i = els.tbLayout.querySelector('i');
            if (i) i.className = single ? 'fas fa-book' : 'fas fa-book-open';
        }
    }

    const BASMALA_GLYPH = '\u00F3'; // QCF Basmala font: whole basmala in one glyph

    // Surah-name banner glyph data + function now live in athar-page-chrome.js
    // (shared with مصحف-editor, which was re-porting a drifted copy of this).
    const { surahHeaderGlyph, clearPageChrome, renderPageChrome } = window.AtharPageChrome;

    /* ── Waqf symbol normalization — ported from the main app so the memorize
       page renders the same glyphs in the same fonts. ─────────────────────── */
    // The combining glyph(s) for an in-text (folded) waqf entry — used to render
    // المدينة القديم and الشمرلي exactly like the embedded المدينة الجديد marks.
    function integratedWaqfGlyph(entry) {
        const data = getWaqfDisplayData(entry && entry.symbols, entry && entry.version);
        return data ? data.text : '';
    }

    /* ── Status / hint ─────────────────────────────────────────────── */
    const status = window.AtharUi.createStatus(els.status, {
        visibleClass: 'mz-show',
        errorClass: 'mz-err',
        defaultDuration: 2200,
    });
    function setStatus(msg, isErr) {
        if (!msg) { status.clear(); return; }
        status.show(msg, { error: !!isErr, duration: isErr ? 4200 : (/^جارٍ/.test(msg) ? 0 : 2200) });
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
        if (isMadinahSource(savedSrc) || savedSrc === 'shamarly') {
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
            const saved = JSON.parse(localStorage.getItem('mz_waqf_print') || '[]');
            if (Array.isArray(saved)) state.mushafVersions = saved.filter(v => typeof v === 'string');
        } catch (e) { state.mushafVersions = []; }
        _waqfVisible = !!(localStorage.getItem('quranApp_waqfVisible') ?? (state.mushafVersions.length ? '1' : ''));
    }

    /* ── Waqf mushaf-version pills ─────────────────────────────────────
       The page layout and printed waqf edition are independent. The three
       supported sets are mutually exclusive: Madinah new/old are folded into
       Madinah text when possible; Shemrly (and every set on a Shemrly glyph
       page) is drawn as a readable overlay. */
    const WAQF_CHOICES = ['المدينة الجديد', 'المدينة القديم', 'الشمرلي'];
    function syncWaqfChoiceButtons() {
        if (!els.waqfPills) return;
        els.waqfPills.querySelectorAll('.mz-waqf-pill').forEach(button => {
            const selected = state.mushafVersions.includes(button.textContent);
            button.classList.toggle('mz-on', selected);
            button.setAttribute('aria-checked', selected ? 'true' : 'false');
        });
    }
    async function loadWaqfPills() {
        if (!els.waqfPills) return;
        let versions = [];
        try {
            versions = await window.AtharApi.json('/api/mushaf-versions');
        } catch (e) { versions = []; }
        versions = WAQF_CHOICES.filter(v => versions.includes(v));
        // Keep exactly one supported print selected; default to new Madinah for
        // existing users who have never chosen a waqf edition.
        state.mushafVersions = state.mushafVersions.filter(v => versions.includes(v)).slice(0, 1);
        if (!state.mushafVersions.length && versions.length) state.mushafVersions = [versions[0]];
        saveSetting('mz_waqf_print', JSON.stringify(state.mushafVersions));
        if (els.tbWaqf) els.tbWaqf.checked = waqfMarksOn();
        els.waqfPills.innerHTML = '';
        versions.forEach(v => {
            const btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'mz-waqf-pill';
            btn.setAttribute('role', 'radio');
            btn.textContent = v;
            btn.addEventListener('click', () => toggleWaqfVersion(v));
            els.waqfPills.appendChild(btn);
        });
        syncWaqfChoiceButtons();
    }
    function toggleWaqfVersion(version) {
        if (!WAQF_CHOICES.includes(version)) return;
        state.mushafVersions = [version];
        _waqfVisible = true;
        if (els.tbWaqf) els.tbWaqf.checked = true;
        syncWaqfChoiceButtons();
        saveSetting('mz_waqf_print', JSON.stringify(state.mushafVersions));
        saveSetting('quranApp_waqfVisible', '1');
        if (state.focusPage) renderSpread(state.focusPage);
    }

    // Simple on/off for the current mushaf's printed waqf marks (مصحف المدينة —
    // applies to all three Madinah layouts). Backed by the
    // mushaf-version overlay: showing = "المدينة" is in the active versions.
    let _waqfVisible = false;
    const waqfMarksOn = () => _waqfVisible;
    function setWaqfMarks(on) {
        _waqfVisible = !!on;
        saveSetting('quranApp_waqfVisible', _waqfVisible ? '1' : '');
        if (els.tbWaqf) els.tbWaqf.checked = _waqfVisible;
        // Re-render from cached payloads. The selected edition is fetched even
        // while hidden, so visibility never changes the page request or layout.
        [cards.right, cards.left].forEach(c => renderCard(c, c._payload || null));
        if (state.hideText) pageEls().forEach(p => p && p.classList.add('mz-hide'));
        applySelectionHighlight();
        requestAnimationFrame(justifyLines);
        if (state.tajweedOn) applyTajweedToPage().then(() => requestAnimationFrame(justifyLines));
    }

    /* ── Arabic-Indic digits + juz ─────────────────────────────────────
       Data + functions now live in athar-page-chrome.js (shared with
       مصحف-editor, which was re-porting a drifted copy of this). */
    const { toAr, juzNumber, juzFromAyah, JUZ_NAME, JUZ_START_PAGE } = window.AtharPageChrome;

    const ARABIC_DIGITS_ONLY = /^[٠-٩]+$/;
    const withAyahOrnament = text => ARABIC_DIGITS_ONLY.test(text) ? '۝' + text : text;

    // The Digital Khatt / QPC-v2 / QPC-v1 source text embeds مصحف المدينة's printed waqf
    // mark as a combining character (U+06D6–U+06DC: ۖۗۘۙۚۛۜ) on whichever word
    // carries it. These are the source of truth — we keep them when the waqf
    // toggle is on and strip them when off (re-rendering on toggle). No DB overlay.
    const updateJustifyLabel = () => { els.justifyVal.textContent = toAr(state.justify) + '٪'; };

    /* ── Surah list + per-surah memo ───────────────────────────────── */
    async function loadSurahs() {
        const data = await window.AtharApi.json('/api/surahs');
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
            list = await window.AtharApi.json('/api/memorization-reciters');
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
            this._destroyed = false;
            this._pendingSeeked = false;
            this._seekTimer = 0;
            this._pendingPlayResolves = new Set();
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
            if (this._destroyed || !this._div || !this._div.isConnected) return;
            this._player = new YT.Player(this._div, {
                width: 320,
                height: 180,
                videoId: this._videoId,
                playerVars: { autoplay: 0, controls: 0, disablekb: 1, fs: 0, rel: 0, playsinline: 1 },
                events: {
                    onReady: () => {
                        if (this._destroyed) return;
                        this._ready = true;
                        if (this._vol != null) this.volume = this._vol;  // apply pending volume
                        this._dispatch('loadedmetadata');
                    },
                    onStateChange: e => {
                        if (this._destroyed) return;
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
            if (this._destroyed) return;
            (this._listeners[event] || []).forEach(cb => {
                try { cb({ type: event, target: this, currentTarget: this }); } catch (e) {}
            });
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
            if (this._destroyed || !this._player || !this._ready) return;
            this._pendingSeeked = true;
            try { this._player.seekTo(t, true); } catch (e) {}
            // Fallback: fire 'seeked' after 500 ms in case state-change never fires
            // (e.g. seek happens while the player is already at the right state).
            clearTimeout(this._seekTimer);
            this._seekTimer = setTimeout(() => {
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
                if (this._destroyed) { resolve(); return; }
                this._pendingPlayResolves.add(resolve);
                const doPlay = () => {
                    this._pendingPlayResolves.delete(resolve);
                    if (!this._destroyed) try { this._player.playVideo(); } catch (e) {}
                    resolve();
                };
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
            this._destroyed = true;
            clearTimeout(this._seekTimer);
            this._pendingPlayResolves.forEach(resolve => resolve());
            this._pendingPlayResolves.clear();
            try { if (this._player && this._player.destroy) this._player.destroy(); } catch (e) {}
            if (this._div && this._div.parentNode) this._div.parentNode.removeChild(this._div);
            this._listeners = {};
        }
    }

    // Named audio event callbacks so they can be re-attached to a fresh adapter
    // whenever the reciter switches between native-MP3 and YouTube backends.
    function _onAudioSeeked(event) {
        if (!event || event.currentTarget === els.audio) state.pendingSeek = false;
    }
    function _onAudioEnded(event) {
        if (event && event.currentTarget !== els.audio) return;
        if (state.playing && state.stepIdx >= 0 && state.stepIdx < state.schedule.length) advanceStep();
    }
    function attachAudioEvents(obj) {
        obj.addEventListener('seeked', _onAudioSeeked);
        obj.addEventListener('ended', _onAudioEnded);
    }

    // Keep a reference to the original <audio> element so we can restore it
    // when switching away from a YouTube reciter back to an MP3 reciter.
    const _nativeAudio = $('mz-audio');

    let _memoRequest = 0;
    let _boundaryRequest = 0;
    async function loadSurahMemo(surah) {
        const request = ++_memoRequest;
        ++_boundaryRequest;
        const query = memoQuery();
        setStatus('جارٍ تحميل بيانات السورة…');
        const data = await window.AtharApi.json(`/api/memorization/${surah}${query}`);
        if (request !== _memoRequest) return false;
        if (!data || !Array.isArray(data.verses) || !data.verses.length) throw new Error('memo load failed');
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
        commitRangeFromControls();

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
        return true;
    }

    // Reload segment boundaries when split mode/sensitivity changes (same surah/audio).
    async function reloadMemoBoundaries() {
        if (!state.memo) return;
        const request = ++_boundaryRequest;
        const surah = state.surah;
        const query = memoQuery();
        try {
            const data = await window.AtharApi.json(`/api/memorization/${surah}${query}`);
            if (request !== _boundaryRequest || surah !== state.surah || query !== memoQuery()) return;
            if (!data || !Array.isArray(data.verses) || !data.verses.length) return;
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

    function normalizeAyahRange(a, b) {
        a = parseInt(a, 10);
        b = parseInt(b, 10);
        if (!Number.isFinite(a) || !Number.isFinite(b)) return null;
        if (b < a) { const t = a; a = b; b = t; }
        return [a, b];
    }
    function cloneRange(range) {
        return range ? [range[0], range[1]] : null;
    }
    function setRangeControls(range) {
        if (range) {
            els.from.value = String(range[0]);
            els.to.value = String(range[1]);
        } else {
            els.from.selectedIndex = -1;
            els.to.selectedIndex = -1;
        }
    }
    function selectedAyahRange() {
        return cloneRange(state.selectionRange);
    }
    function visualAyahRange() {
        return state.rangeDraft
            ? [state.rangeDraft.anchor, state.rangeDraft.anchor]
            : selectedAyahRange();
    }
    function syncRangeCancelUi() {
        const picking = !!state.rangeDraft;
        document.body.classList.toggle('mz-range-picking', picking);
        if (!els.stop) return;
        const hasRange = picking || !!state.selectionRange;
        const label = picking
            ? 'إلغاء اختيار بداية النطاق'
            : hasRange
                ? 'إنهاء الجلسة وإلغاء النطاق'
                : 'إيقاف';
        els.stop.title = label;
        els.stop.setAttribute('aria-label', label);
    }
    function setCommittedRange(a, b) {
        const range = normalizeAyahRange(a, b);
        state.selectionRange = range;
        state.rangeDraft = null;
        setRangeControls(range);
        rebuildSelectedKeys();
        syncRangeCancelUi();
        return range;
    }
    function commitRangeFromControls() {
        return setCommittedRange(els.from.value, els.to.value);
    }
    function beginRangePick(ayah) {
        state.rangeDraft = {
            anchor: ayah,
            previousRange: cloneRange(state.selectionRange),
        };
        setRangeControls([ayah, ayah]);
        rebuildSelectedKeys();
        applySelectionHighlight();
        syncRangeCancelUi();
        if (els.now) els.now.textContent = 'اختر آية النهاية…';
        updateHint();
    }
    function completeRangePick(ayah) {
        if (!state.rangeDraft) return null;
        const anchor = state.rangeDraft.anchor;
        const range = setCommittedRange(anchor, ayah);
        if (els.now && !state.playing) els.now.textContent = '';
        updateHint();
        return range;
    }
    function cancelRangePick({ silent = false } = {}) {
        if (!state.rangeDraft) return false;
        const previous = cloneRange(state.rangeDraft.previousRange);
        state.rangeDraft = null;
        state.selectionRange = previous;
        setRangeControls(previous);
        rebuildSelectedKeys();
        applySelectionHighlight();
        syncRangeCancelUi();
        if (els.now && !state.playing) els.now.textContent = '';
        updateHint();
        if (!silent) setStatus('أُلغي اختيار النطاق');
        return true;
    }
    function clearRangeSelection({ silent = false } = {}) {
        state.rangeDraft = null;
        state.selectionRange = null;
        setRangeControls(null);
        state.selectedKeys.clear();
        applySelectionHighlight();
        syncRangeCancelUi();
        updateHint();
        if (!silent) setStatus('أُلغي النطاق');
    }
    function selectedVerses(range = selectedAyahRange()) {
        if (!range) return [];
        const [a, b] = range;
        const out = [];
        for (let k = a; k <= b; k++) { const v = state.verseByAyah.get(k); if (v) out.push(v); }
        return out;
    }
    function rebuildSelectedKeys() {
        const range = visualAyahRange();
        state.selectedKeys = new Set();
        if (!range) return;
        const [a, b] = range;
        for (let k = a; k <= b; k++) state.selectedKeys.add(`${state.surah}:${k}`);
    }

    // Live feedback on how the current split settings divide the selection.
    function updateHint() {
        updateEstimate();
        if (!els.hint) return;
        if (!state.memo || !els.splitLong.checked) { els.hint.textContent = ''; return; }
        let splitVerses = 0, totalPhrases = 0;
        selectedVerses(visualAyahRange()).forEach(v => {
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
        if (els.volBtn) {
            els.volBtn.setAttribute('aria-pressed', String(v === 0));
        }
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
        els.est.innerHTML = sec ? `<i class="fas fa-clock" aria-hidden="true"></i> المدة المتوقعة للجلسة: <b>${fmtDur(sec)}</b>` : '';
    }

    /* ── Mushaf source ─────────────────────────────────────────────── */
    function applySrcClass() {
        [cards.right.page, cards.left.page].forEach(p => {
            if (!p) return;
            p.classList.toggle('mz-src-qpc-v1', state.src === 'qpc_v1');
            p.classList.toggle('mz-src-digital-khatt', isDigitalKhattSource(state.src));
            p.classList.toggle('mz-src-shamarly', state.src === 'shamarly');
            p.classList.toggle('mz-tajweed', state.tajweedOn && state.src !== 'shamarly');
        });
    }
    /* ── الشمرلي (Shemrly) page-local fonts ────────────────────────────
       Shemrly is a page-image mushaf: each page has its own font whose glyphs
       draw the words exactly as printed. Only the pages we ship a font for can
       render; the API tags others 'legacy-word-position' and we show a note.
       Each word's glyph is page-local, so a card's font = that page's font.
       The page list itself is fetched from /api/shamarly/pages (backed by a
       filesystem scan) rather than hardcoded, so it can't drift out of sync
       with the actual .woff2 files shipped in static/fonts/. */
    let SHEMRLY_PAGES = [];
    let SHEMRLY_PAGE_SET = new Set();
    async function loadShemrlyPages() {
        try {
            const data = await window.AtharApi.json('/api/shamarly/pages');
            if (Array.isArray(data.pages) && data.pages.length) {
                SHEMRLY_PAGES = data.pages;
                SHEMRLY_PAGE_SET = new Set(SHEMRLY_PAGES);
            }
        } catch (e) { /* keep empty; shamarly picker/switch just won't have pages */ }
    }
    const _shemrlyFontPromises = new Map();
    function ensureShemrlyFont(fontName) {
        if (!fontName || !window.FontFace) return Promise.resolve();
        if (_shemrlyFontPromises.has(fontName)) return _shemrlyFontPromises.get(fontName);
        const ff = new FontFace(fontName, `url("/static/fonts/${fontName}.woff2")`);
        const p = ff.load().then(f => document.fonts.add(f)).catch(() => {});
        _shemrlyFontPromises.set(fontName, p);
        return p;
    }
    const nearestShemrlyPage = (page) =>
        SHEMRLY_PAGES.reduce((best, p) => Math.abs(p - page) < Math.abs(best - page) ? p : best, SHEMRLY_PAGES[0]);
    function pageVersions() {
        return state.mushafVersions.slice(0, 1);
    }
    const mushafPages = window.AtharMushaf.createPageClient({
        getSource: () => state.src,
        getVersions: pageVersions,
    });
    async function fetchPageByAyah(surah, ayah) {
        return mushafPages.byAyah(surah, ayah);
    }
    async function fetchPageByNumber(pageNumber) {
        return mushafPages.byNumber(pageNumber);
    }

    /* ── Waqf marks renderer (same structure/fonts/colours as the main page) ─ */
    function appendWaqfMarks(span, entries) {
        window.AtharMushaf.appendWaqfEntries(span, entries);
    }

    /* ── Render one page into a card ───────────────────────────────── */
    function renderCard(card, payload) {
        const pageEl = card.page;
        card._payload = payload;   // cache for cheap re-render (e.g. waqf toggle)
        if (!payload) {
            window.AtharPageChrome.renderEmptyState(pageEl, { baseClass: 'mz-page-empty' });
            clearPageChrome({
                juzEl: card.juz, surahEl: card.surah, pageNumberEl: card.foot,
                juzGlyphClass: 'athar-page-juz-glyph',
            });
            pageEl.classList.remove('mz-has-page');
            return;
        }
        // Shemrly renders only on pages we ship a font for; the API marks the rest
        // 'legacy-word-position' (glyphs we can't draw) — show a friendly note instead.
        if (state.src === 'shamarly' && payload.glyph_mapping_mode !== 'shemrly-page-local') {
            pageEl.classList.remove('mz-has-page');
            pageEl.style.removeProperty('font-family');
            window.AtharPageChrome.renderEmptyState(pageEl, {
                baseClass: 'mz-page-empty', extraClass: 'mz-page-na', icon: 'fa-circle-info',
                message: 'هذه الصفحة غير متوفرة بخط الشمرلي بعد',
            });
            clearPageChrome({
                juzEl: card.juz, surahEl: card.surah, pageNumberEl: card.foot,
                juzGlyphClass: 'athar-page-juz-glyph',
            });
            card.foot.textContent = toAr(payload.page_number || '');
            return;
        }
        // Page-local Shemrly font: every word on this page draws with it.
        if (state.src === 'shamarly' && payload.font_name) pageEl.style.fontFamily = `"${payload.font_name}", serif`;
        else pageEl.style.removeProperty('font-family');

        pageEl.classList.add('mz-has-page');
        window.AtharMushaf.renderMushafLines(pageEl, payload.lines || [], {
            lineClass: 'mz-line', contentClass: 'mz-line-inner', wordClass: 'mz-word',
            surahClass: 'mz-line-surah', basmalaClass: 'mz-line-basmala mz-basmala-glyph',
            textForSpecial: ({ line, kind }) => kind === 'surah'
                ? (surahHeaderGlyph(line.surah_number) || line.display_text || '')
                : BASMALA_GLYPH,
            decorateSpecial: (element, { line, kind }) => {
                if (kind === 'surah' && surahHeaderGlyph(line.surah_number)) element.classList.add('mz-surah-glyph');
                element.setAttribute('aria-label', line.display_text || (kind === 'basmala' ? 'بسم الله الرحمن الرحيم' : ''));
            },
            textForWord: ({ word, raw }) => {
                const entries = Array.isArray(word.waqf_symbols) ? word.waqf_symbols : [];
                const selectedWaqf = state.mushafVersions[0] || 'المدينة الجديد';
                if (state.src === 'shamarly') return raw;
                if (!waqfMarksOn()) return withAyahOrnament(stripEmbeddedWaqf(raw));
                if (selectedWaqf === 'المدينة الجديد') return withAyahOrnament(raw);
                const selectedMark = entries.find(entry => entry && entry.version === selectedWaqf);
                return withAyahOrnament(
                    stripEmbeddedWaqf(raw) + (selectedMark ? integratedWaqfGlyph(selectedMark) : '')
                );
            },
            decorateWord: (element, { word }) => {
                element.dataset.text = element.textContent;
                const entries = Array.isArray(word.waqf_symbols) ? word.waqf_symbols : [];
                const overlay = state.src === 'shamarly'
                    ? entries.filter(Boolean)
                    : [];
                if (!overlay.length) return;
                element._waqf = overlay;
                if (waqfMarksOn()) appendWaqfMarks(element, overlay);
            },
            decorateLine: (element, { line }) => {
                if ((line.words || []).length) element.dataset.justify = line.is_centered ? '0' : '1';
            },
        });

        // Shemrly's layout-DB page numbers don't match the 604-page Madina numbering,
        // so derive its juz from the page's first ayah instead of the page number.
        renderPageChrome({
            payload, juzEl: card.juz, surahEl: card.surah, pageNumberEl: card.foot,
            getJuzNumber: page => state.src === 'shamarly'
                ? juzFromAyah(page.anchor_surah_number, page.anchor_ayah_number)
                : juzNumber(page.page_number),
            getSurahName: surahNameOf,
            juzGlyphClass: 'athar-page-juz-glyph',
            surahGlyphClass: 'athar-page-surah-glyph',
            surahTextClass: 'athar-page-surah-text',
        });
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

    const pageRequests = window.AtharMushaf.createRequestGate();
    async function renderSpread(focusPage, intent) {
        const request = intent == null ? pageRequests.next() : intent;
        try {
            if (state.layoutMode === 'single') {
                // Single page: show the focus page itself in the right card; hide the left.
                const fp = await fetchPageByNumber(focusPage);
                if (state.src === 'shamarly' && fp) await ensureShemrlyFont(fp.font_name);
                if (!pageRequests.isCurrent(request)) return false;
                state.focusPage = focusPage;
                state.spread = [focusPage, null];
                renderCard(cards.right, fp);
                renderCard(cards.left, null);
            } else {
                const [right, left] = spreadFor(focusPage);
                const canLoad = page => state.src !== 'shamarly' || SHEMRLY_PAGE_SET.has(page);
                const [rp, lp] = await Promise.all([
                    canLoad(right) ? fetchPageByNumber(right) : Promise.resolve(null),
                    left !== right && left <= PAGE_MAX && canLoad(left) ? fetchPageByNumber(left) : Promise.resolve(null),
                ]);
                if (state.src === 'shamarly') await Promise.all([rp, lp].map(p => p && ensureShemrlyFont(p.font_name)));
                if (!pageRequests.isCurrent(request)) return false;
                state.focusPage = focusPage;
                state.spread = [right, left];
                renderCard(cards.right, rp);
                renderCard(cards.left, lp);
            }
        } catch (e) {
            if (pageRequests.isCurrent(request)) setStatus('تعذّر تحميل الصفحة', true);
            return false;
        }
        applySrcClass();
        if (state.hideText) pageEls().forEach(p => p && p.classList.add('mz-hide'));
        sizePages();
        applyFontSize();
        applySelectionHighlight();
        requestAnimationFrame(justifyLines);
        if (state.tajweedOn) applyTajweedToPage().then(() => requestAnimationFrame(justifyLines));
        updateNavButtons();

        // font-display:swap means the source's web-font may not be loaded yet on
        // the first switch to it — applyFontSize() above then measured fallback
        // metrics and over-fit the size, so the page "grows" when the real font
        // swaps in. Re-fit once the font is ready (no-op when already loaded).
        const srcFont = isDigitalKhattSource(state.src) ? 'Digital Khatt'
            : state.src === 'qpc_v1' ? 'Old Madina' : null;
        if (srcFont && document.fonts && !document.fonts.check(`16px "${srcFont}"`)) {
            const fp = focusPage;
            document.fonts.load(`16px "${srcFont}"`).then(() => {
                if (state.focusPage === fp) { applyFontSize(true); requestAnimationFrame(justifyLines); }
            }).catch(() => {});
        }
        return true;
    }

    // Make the page(s) as large as the freed centre allows, keeping a mushaf
    // portrait ratio, fitting both width (n pages) and height. Fit MATH lives in
    // athar-page-chrome.js (shared with مصحف-editor); the measurement strategy
    // below is تثبيت's own — deliberately the viewport + fixed chrome, NEVER a
    // rendered element's height (reading the stage-area's clientHeight created a
    // feedback loop: a taller page grew the scroll area, which grew the next
    // page…), so a pure window-based formula gives ONE fixed page box that stays
    // put — the page simply sits centred in the stage.
    const PAGE_RATIO = 0.66;            // Digital Khatt / Shemrly width ÷ height
    const OLD_MADINA_PAGE_RATIO = 0.72; // 1405 print needs a wider text block
    function sizePages() {
        const stage = els.stage;
        if (!stage) return;
        const topbar = els.bar?.getBoundingClientRect().height || 52;
        const appbar = document.querySelector('.athar-bar')?.getBoundingClientRect().height || 50;
        const vMargin = 12;          // tight breathing room — chrome is slim, no bottom dock
        const headFootPad = 72;      // header + footer + card padding (vertical)
        const navAndGaps = 2 * 44 + 12; // room for the edge nav arrows
        window.AtharPageChrome.sizePages({
            cssVarPrefix: 'mz',
            pages: state.layoutMode === 'single' ? 1 : 2,
            ratio: state.src === 'qpc_v1' ? OLD_MADINA_PAGE_RATIO : PAGE_RATIO,
            gutter: 16, edgePad: 20,
            getAvailH: () => Math.max(280, window.innerHeight - topbar - appbar - vMargin) - headFootPad,
            getAvailW: () => Math.max(240, stage.clientWidth - navAndGaps),
        });
    }

    const pageEls = () => [cards.right.page, cards.left.page];
    const wordsInSpread = sel => {
        const out = [];
        pageEls().forEach(p => p && p.querySelectorAll(sel).forEach(w => out.push(w)));
        return out;
    };

    /* ── Justification (kashida features + scaleX fill) ─────────────────
       Shared algorithm + Madinah feature ladders live in athar-page-chrome.js. */
    const {
        digitalKhattFeatureCandidates,
        oldMadinaFeatureCandidates,
    } = window.AtharPageChrome;
    const justifyLines = window.AtharPageChrome.createLineJustifier({
        containerEls: pageEls,
        lineSelector: '.mz-line', innerSelector: '.mz-line-inner', wordSelector: '.mz-word',
        featureCandidates: () => state.src === 'qpc_v1'
            ? oldMadinaFeatureCandidates(state.justify)
            : isDigitalKhattSource(state.src)
                ? digitalKhattFeatureCandidates(state.justify)
                : [],
        minFeatureScale: () => (
            isMadinahSource(state.src) ? 0.95 : 1
        ),
        maxWordSpacing: (_lineEl, inner) => {
            if (!isMadinahSource(state.src)) return Infinity;
            const fontSize = parseFloat(getComputedStyle(inner).fontSize) || 20;
            return Math.max(1.5, Math.min(4, fontSize * 0.12));
        },
        maxStretch: () => (
            // The full 604-page audit found 3 Digital Khatt and 17 Old Madina
            // lines whose strongest font alternates still end short. These
            // ceilings cover those rare lines (14.6% / 17.2% required) while
            // leaving feature shaping and capped word spacing as the primary
            // strategy for every ordinary line.
            state.layoutMode === 'dual' ? 1.20
                : isDigitalKhattSource(state.src) ? 1.15
                : state.src === 'qpc_v1' ? 1.18
                    : Infinity
        ),
        stretchOnly: () => state.src === 'shamarly',
    });
    // Fit each page/spread against an explicit compression budget. Including the
    // focus page in the key prevents a difficult page from inheriting a font size
    // measured against an unrelated page's lines. In a two-page spread, fit each
    // printed page independently: forcing the easier face to inherit its partner's
    // smaller size created 25–36% short-line expansion outliers.
    const applyFontSize = window.AtharPageChrome.createFontSizer({
        pageEls: () => pageEls().filter(p => p && p.classList.contains('mz-has-page')),
        lineSelector: '.mz-line', innerSelector: '.mz-line-inner',
        cssVarName: '--dk-fs', linesPerPage: 15,
        cacheKey: () => `${state.src}|${state.layoutMode}|${state.focusPage || 0}`,
        sharedSize: false,
        maxPageFitRatio: 1.15,
        // Narrow mobile pages can contain an exceptionally long printed line
        // (notably Digital Khatt page 507). Allow the compression-budget fitter
        // to reach its calculated ~10px size instead of stopping at 10.5px.
        minFontSize: 9.5,
        minLineScale: () => (
            isMadinahSource(state.src) ? 0.95 : 0
        ),
    });

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
        const intent = pageRequests.next();
        try {
            const payload = await fetchPageByAyah(surah, ayah);
            if (!pageRequests.isCurrent(intent)) return false;
            const rendered = await renderSpread(payload.page_number, intent);
            if (!rendered || !pageRequests.isCurrent(intent)) return false;
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
            const data = await window.AtharApi.json(`/api/tajweed/${surah}/${ayah}`);
            segments = parseTajweedIntoWords(getNormalizedTajweedHtml(data.html));
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
        if (state.src === 'shamarly' && SHEMRLY_PAGES.length) {
            els.prev.disabled = !state.focusPage || state.focusPage <= SHEMRLY_PAGES[0];
            els.next.disabled = !state.focusPage || state.focusPage >= SHEMRLY_PAGES[SHEMRLY_PAGES.length - 1];
            return;
        }
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
        const intent = pageRequests.next();
        focusPage = Math.max(PAGE_MIN, Math.min(PAGE_MAX, focusPage));
        setStatus('جارٍ تحميل الصفحة…');
        const rendered = await renderSpread(focusPage, intent);
        if (!rendered || !pageRequests.isCurrent(intent)) return false;
        setStatus('');
        return true;
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
            if (!state.playing || state.pendingSeek || state.stepIdx < 0 || els.audio.paused) return;
            const step = state.schedule[state.stepIdx];
            if (!step) return;
            updateProgress();
            followTick();
            if (els.audio.currentTime >= step.end - EPS) advanceStep();
        }, 40);
    }
    const stopMonitor = () => { if (state.monitorId) { clearInterval(state.monitorId); state.monitorId = null; } };

    function seekTo(t, generation) {
        state.pendingSeek = true;
        const audio = els.audio;
        const apply = () => {
            if (generation !== state.playbackGeneration || audio !== els.audio || state.stepIdx < 0) return;
            try { audio.currentTime = t; } catch (e) {}
            audio.play().catch(() => {});
        };
        if (audio.readyState >= 1) apply();
        else audio.addEventListener('loadedmetadata', apply, { once: true });
    }

    async function playStep(k, atTime, generation) {
        generation = generation == null ? state.playbackGeneration : generation;
        if (generation !== state.playbackGeneration || !state.schedule.length) return;
        if (k >= state.schedule.length) {
            if (els.loop.checked) { k = 0; } else { finishPlayback(generation); return; }
        }
        state.pendingSeek = true;
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
        if (generation !== state.playbackGeneration || state.stepIdx !== k || !state.schedule.length) return;
        markActive(`${state.surah}:${firstAyah}`);
        state.curFollowAyah = firstAyah;
        scrollActiveIntoView();
        seekTo(atTime != null ? atTime : step.start, generation);
        els.now.textContent = `${surahNameOf(state.surah)} · ${step.label}` + (step.repTotal > 1 ? ` (${toAr(step.rep)}/${toAr(step.repTotal)})` : '');
        saveSetting('mz_last_pos', `${state.surah}:${step.ayah}`);
        saveSetting('quranApp_lastPosition', `${state.surah}:${step.ayah}`);
    }
    const advanceStep = () => {
        if (!state.playing || state.pendingSeek || state.stepIdx < 0) return;
        playStep(state.stepIdx + 1, null, state.playbackGeneration);
    };

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
        setProgress(overall);
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

    function setProgress(frac) {
        const percent = Math.round(Math.max(0, Math.min(1, Number(frac) || 0)) * 100);
        els.progressFill.style.width = `${percent}%`;
        els.progress.setAttribute('aria-valuenow', String(percent));
        els.progress.setAttribute('aria-valuetext', `${toAr(percent)}٪`);
    }

    // Click anywhere on the session progress bar to jump within the schedule.
    function seekOverall(frac) {
        const n = state.schedule.length;
        if (!n) return;
        frac = Math.max(0, Math.min(0.99999, frac));
        setProgress(frac);
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
        const run = () => { sizePages(); applyFontSize(true); requestAnimationFrame(justifyLines); };
        requestAnimationFrame(run);
        setTimeout(run, 380);
    }

    async function startPlayback() {
        if (state.rangeDraft) {
            setStatus('اختر آية النهاية أو ألغِ الاختيار أولًا', true);
            return;
        }
        const range = selectedAyahRange();
        if (!range) {
            setStatus('اختر بداية النطاق ونهايته أولًا', true);
            return;
        }
        const generation = ++state.playbackGeneration;
        window.clearTimeout(state.finishTimer);
        state.finishTimer = null;
        state.pendingSeek = false;
        try { els.audio.pause(); } catch (e) {}
        stopMonitor();
        rebuildSelectedKeys();
        clearDone();   // fresh progress reveal for this run
        state.schedule = buildSchedule();
        if (!state.schedule.length) { setStatus('لا توجد آيات في النطاق المحدد', true); return; }
        setProgress(0);
        const [a] = range;
        setStatus('جارٍ فتح صفحة المصحف…');
        const ok = await ensureVerseVisible(state.surah, a);
        if (generation !== state.playbackGeneration) return;
        if (!ok) { setStatus('تعذّر تحديد موضع الآية في المصحف', true); return; }
        applySelectionHighlight();
        setStatus('');
        state.playing = true;
        els.player.classList.add('mz-show');
        els.player.setAttribute('aria-hidden', 'false');
        refitForPlayer();
        setPlayIcon(true);
        startMonitor();
        playStep(0, null, generation);
    }
    function finishPlayback(generation) {
        if (generation != null && generation !== state.playbackGeneration) return;
        state.playing = false; stopMonitor(); els.audio.pause(); setPlayIcon(false); markActive(null);
        state.pendingSeek = false;
        clearWordHighlight();
        setProgress(1);
        els.now.textContent = 'تم — أحسنت! 🌿';
        if (els.remaining) els.remaining.textContent = '';
        window.clearTimeout(state.finishTimer);
        const completedGeneration = state.playbackGeneration;
        state.finishTimer = setTimeout(() => {
            if (!state.playing && completedGeneration === state.playbackGeneration) setProgress(0);
        }, 1200);
    }
    function stopPlayback() {
        ++state.playbackGeneration;
        window.clearTimeout(state.finishTimer);
        state.finishTimer = null;
        state.playing = false; state.stepIdx = -1; state.schedule = []; state.pendingSeek = false; stopMonitor(); els.audio.pause(); setPlayIcon(false); markActive(null);
        clearWordHighlight(); clearDone(); state.stepVerses = []; state.activeWords = []; state.curFollowAyah = null;
        setProgress(0);
        els.now.textContent = '';
        if (els.remaining) els.remaining.textContent = '';
        els.player.classList.remove('mz-show');
        els.player.setAttribute('aria-hidden', 'true');
        refitForPlayer();
    }
    function togglePlay() {
        if (els.audio.paused) {
            if (state.stepIdx < 0) playStep(0, null, state.playbackGeneration); else els.audio.play().catch(() => {});
            state.playing = true; setPlayIcon(true); startMonitor();
        } else { els.audio.pause(); state.playing = false; setPlayIcon(false); }
    }
    function setPlayIcon(playing) {
        const i = els.play.querySelector('i');
        if (i) i.className = playing ? 'fas fa-pause' : 'fas fa-play';
        els.play.setAttribute('aria-label', playing ? 'إيقاف مؤقت' : 'تشغيل');
    }

    // Attach 'seeked' and 'ended' listeners to the initial native audio element.
    // loadSurahMemo calls attachAudioEvents() again whenever the backend switches.
    attachAudioEvents(els.audio);

    /* ── Recite & follow (streaming ASR, beta) ─────────────────────────
       Lazy-loads static/mushaf_asr.js (onnxruntime-web + the FastConformer
       streaming model). The module emits recognised Arabic words; we match
       them against the selected verses in order to follow / reveal / advance. */
    let _asrLoaded = false, _asrActive = false, _asrStarting = false, _asrSession = 0;
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
        const range = selectedAyahRange();
        if (!range) return [];
        const [a, b] = range;
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

    function stopReciteFollow(showMessage) {
        ++_asrSession;
        _asrStarting = false;
        _asrActive = false;
        try { if (window.MushafASR) window.MushafASR.stop(); } catch (e) {}
        if (els.reciteBtn) {
            window.AtharUi.setBusy(els.reciteBtn, false);
            els.reciteBtn.classList.remove('mz-listening');
            els.reciteBtn.setAttribute('aria-pressed', 'false');
            els.reciteBtn.setAttribute('aria-label', 'بدء التسميع والمتابعة');
        }
        showAsrLive(false);
        if (showMessage && els.asrNote) els.asrNote.textContent = 'تم إيقاف التسميع';
    }

    async function startReciteFollow() {
        if (_asrActive || _asrStarting) { stopReciteFollow(true); return; }
        const session = ++_asrSession;
        _asrStarting = true;
        window.AtharUi.setBusy(els.reciteBtn, true);
        if (els.asrNote) els.asrNote.textContent = 'جارٍ تحضير نموذج التعرّف… (قد يستغرق التحميل أول مرة)';
        try {
            if (!_asrLoaded) { await loadScript('/static/js/mushaf_asr.js?v=25'); _asrLoaded = true; }
            if (session !== _asrSession) return;
            if (!window.MushafASR) throw new Error('module missing');

            // make sure the selected verses are actually on screen before we map words
            await renderSelection();
            if (session !== _asrSession) return;
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
                onStatus: (msg) => {
                    if (session !== _asrSession) return;
                    if (els.asrNote) els.asrNote.textContent = msg;
                    if (els.asrLiveText && /استمع|listen/i.test(msg)) showAsrLive(true);
                },
                onActive: (on) => {
                    if (session !== _asrSession) return;
                    _asrStarting = false;
                    _asrActive = on;
                    if (els.reciteBtn) {
                        window.AtharUi.setBusy(els.reciteBtn, false);
                        els.reciteBtn.classList.toggle('mz-listening', on);
                        els.reciteBtn.setAttribute('aria-pressed', String(on));
                        els.reciteBtn.setAttribute('aria-label', on ? 'إيقاف التسميع والمتابعة' : 'بدء التسميع والمتابعة');
                    }
                    showAsrLive(on);
                },
                // Running recognised transcript → live display + word-by-word follow.
                onTranscript: (text) => {
                    if (session !== _asrSession || !_asrActive) return;
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
            if (session === _asrSession) _asrStarting = false;
        } catch (e) {
            if (session !== _asrSession) return;
            _asrStarting = false;
            _asrActive = false;
            if (els.reciteBtn) {
                window.AtharUi.setBusy(els.reciteBtn, false);
                els.reciteBtn.classList.remove('mz-listening');
                els.reciteBtn.setAttribute('aria-pressed', 'false');
                els.reciteBtn.setAttribute('aria-label', 'بدء التسميع والمتابعة');
            }
            showAsrLive(false);
            console.error('[recite] failed:', e);
            const msg = (e && (e.message || e.name)) ? (e.message || e.name) : String(e);
            if (els.asrNote) els.asrNote.textContent = 'تعذّر التشغيل: ' + msg;
        }
    }

    /* ── Wiring ────────────────────────────────────────────────────── */
    async function onSurahChange() {
        stopReciteFollow(false);
        stopPlayback();
        const surah = parseInt(els.surah.value, 10) || 1;
        try {
            const loaded = await loadSurahMemo(surah);
            if (!loaded) return;
            saveSetting('mz_last_pos', `${surah}:1`);
            await renderSelection();   // jump the mushaf straight to the chosen surah
        }
        catch (e) { setStatus('تعذّر تحميل بيانات السورة', true); }
    }
    const liveSelection = () => {
        stopReciteFollow(false);
        if (state.focusPage) { rebuildSelectedKeys(); applySelectionHighlight(); }
        updateHint();
    };

    /* ── Top-bar labels (reciter / repeat / mushaf source) ─────────── */
    const SRC_NAMES = {
        digital_khatt: 'المدينة ١٤٤١',
        qpc_v2: 'المدينة ١٤٢١',
        qpc_v1: 'المدينة ١٤٠٥',
        shamarly: 'الشمرلي',
    };
    function syncBarLabels() {
        if (els.reciterLabel) els.reciterLabel.textContent = state.reciterName || 'القارئ';
        if (els.repsBadge) els.repsBadge.textContent = '×' + toAr(parseInt(els.verseReps.value, 10) || 1);
        if (els.srcLabel) els.srcLabel.textContent = SRC_NAMES[state.src] || 'المصحف';
    }

    /* ── Popovers (reciter / mushaf source) ────────────────────────── */
    const popovers = window.AtharUi.createPopoverGroup();
    popovers.register(els.reciterTrigger, els.reciterPanel);
    popovers.register(els.srcTrigger, els.srcPanel);
    function closePopovers(except) { popovers.close(except); }
    function togglePopover(trigger, panel) {
        popovers.toggle(trigger, panel);
    }
    document.addEventListener('click', (e) => {
        if (!e.target.closest('.mz-pop')) closePopovers();
    });

    /* ── Tap-to-pick sheet (juz / surah / page) ────────────────────── */
    let _pickerKind = null;
    let _pickerReturnFocus = null;
    function openPicker(kind) {
        _pickerReturnFocus = document.activeElement;
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
            pages.forEach(p => list.appendChild(pickerItem(toAr(p), p, p === curPage, () => navigateToPage(p), '', true)));
        }
        els.picker.hidden = false;
        if (kind !== 'surah') requestAnimationFrame(() => {
            const target = els.pickerList.querySelector('.mz-picker-item.mz-current, .mz-picker-item');
            if (target) target.focus();
        });
    }
    function pickerItem(label, num, current, onPick, searchKey, numberOnly) {
        const b = document.createElement('button');
        b.type = 'button'; b.className = 'mz-picker-item' + (current ? ' mz-current' : '') + (numberOnly ? ' mz-number-only' : '');
        b.dataset.search = (searchKey || label);
        b.innerHTML = numberOnly
            ? `<span class="mz-pi-num">${toAr(num)}</span>`
            : `<span class="mz-pi-num">${toAr(num)}</span><span>${label}</span>`;
        b.addEventListener('click', () => { closePicker(); onPick(); });
        if (current) requestAnimationFrame(() => b.scrollIntoView({ block: 'center' }));
        return b;
    }
    function closePicker() {
        if (els.picker) els.picker.hidden = true;
        _pickerKind = null;
        const target = _pickerReturnFocus;
        _pickerReturnFocus = null;
        if (target && document.contains(target)) requestAnimationFrame(() => target.focus());
    }
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
        if (!state.rangeDraft) {
            beginRangePick(ayah);
            setStatus('اختر آية النهاية…');
        } else {
            const range = completeRangePick(ayah);
            const [a, b] = range;
            applySelectionHighlight();
            setStatus(a === b ? `الآية ${toAr(a)}` : `النطاق ${toAr(a)}–${toAr(b)} · اضغط ▶`);
        }
    }

    function bindEvents() {
        els.surah.addEventListener('change', onSurahChange);
        els.from.addEventListener('change', () => {
            stopReciteFollow(false);
            const nextFrom = els.from.value;
            cancelRangePick({ silent: true });
            els.from.value = nextFrom;
            autoSetTo(parseInt(els.from.value, 10));
            commitRangeFromControls();
            renderSelection();
        });
        els.to.addEventListener('change', () => {
            const nextTo = els.to.value;
            cancelRangePick({ silent: true });
            els.to.value = nextTo;
            commitRangeFromControls();
            liveSelection();
        });

        els.start.addEventListener('click', () => {
            els.start.disabled = true;
            startPlayback().finally(() => { els.start.disabled = false; });
        });
        els.play.addEventListener('click', () => {
            if (!state.schedule.length || state.stepIdx < 0) startPlayback(); else togglePlay();
        });
        els.stop.addEventListener('click', () => {
            stopReciteFollow(false);
            stopPlayback();
            clearRangeSelection();
        });

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
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                if (!els.picker.hidden) closePicker();
                else if (!cancelRangePick()) closePopovers();
                return;
            }
            if (e.key !== 'Tab' || !els.picker || els.picker.hidden) return;
            const focusable = [...els.picker.querySelectorAll('button:not(:disabled), input:not([hidden])')]
                .filter(el => el.offsetParent !== null);
            if (!focusable.length) return;
            const first = focusable[0], last = focusable[focusable.length - 1];
            if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
            else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
        });
        if (els.prevStep) els.prevStep.addEventListener('click', () => {
            if (!state.schedule.length) return;
            playStep(state.stepIdx <= 0 ? 0 : state.stepIdx - 1);
        });
        if (els.nextStep) els.nextStep.addEventListener('click', () => {
            if (!state.schedule.length) return;
            playStep(Math.min(state.schedule.length - 1, Math.max(0, state.stepIdx) + 1));
        });
        const adjacentPage = direction => {
            if (!state.focusPage) return null;
            if (state.src === 'shamarly' && SHEMRLY_PAGES.length) {
                const pages = SHEMRLY_PAGES.filter(page => direction < 0 ? page < state.focusPage : page > state.focusPage);
                return direction < 0 ? pages[pages.length - 1] : pages[0];
            }
            const step = state.layoutMode === 'single' ? 1 : 2;
            return state.focusPage + direction * step;
        };
        const navPrev = () => { const page = adjacentPage(-1); if (page) gotoSpread(page); };
        const navNext = () => { const page = adjacentPage(1); if (page) gotoSpread(page); };
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
            stopReciteFollow(false);
            // Preserve the reading position by surah/ayah, not page number: Shemrly's
            // layout-DB pages don't match the 604-page Madina numbering, so keeping the
            // page number would jump to unrelated content when crossing that boundary.
            const firstWord = wordsInSpread('.mz-word[data-key]')[0];
            const selectedRange = selectedAyahRange();
            const anchorKey = firstWord ? firstWord.dataset.key
                : `${state.surah}:${selectedRange ? selectedRange[0] : 1}`;
            state.src = els.src.value;
            saveSetting('mz_src', state.src);
            syncSrcCapabilities();
            syncBarLabels();
            closePopovers();
            if (!state.focusPage) return;
            stopPlayback();
            state.tajweedCache.clear();
            const intent = pageRequests.next();
            try {
                const [s, a] = anchorKey.split(':').map(Number);
                const payload = await fetchPageByAyah(s, a);   // page in the NEW source
                if (!pageRequests.isCurrent(intent)) return;
                let target = payload.page_number;
                if (state.src === 'shamarly' && !SHEMRLY_PAGE_SET.has(target)) {
                    setStatus('خط الشمرلي متاح لصفحات مختارة — تم الانتقال لأقرب صفحة متاحة');
                    target = nearestShemrlyPage(target);
                }
                setStatus('جارٍ تحميل الصفحة…');
                const rendered = await renderSpread(target, intent);
                if (rendered && pageRequests.isCurrent(intent)) setStatus('');
            } catch (e) {
                if (pageRequests.isCurrent(intent)) renderSpread(state.focusPage, intent);
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
        if (els.reciter) els.reciter.addEventListener('change', async () => {
            state.reciter = els.reciter.value;
            saveSetting('quranApp_memoReciter', state.reciter);
            stopPlayback();
            try {
                const loaded = await loadSurahMemo(state.surah);
                if (loaded) syncBarLabels();
            } catch (e) { setStatus('تعذّر تحميل القارئ', true); }
        });

        els.splitMode.addEventListener('change', () => { state.splitModeVal = els.splitMode.value; reloadMemoBoundaries(); });
        els.gap.addEventListener('input', () => { state.gapMs = parseInt(els.gap.value, 10) || 250; els.gapVal.textContent = state.gapMs + 'ms'; });
        els.gap.addEventListener('change', reloadMemoBoundaries);

        // Hide-for-testing toggles (topbar + sidebar)
        const toggleHide = () => setHideMode(!state.hideText);
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
        if (els.progress) els.progress.addEventListener('keydown', e => {
            if (!state.schedule.length) return;
            const current = parseInt(els.progress.getAttribute('aria-valuenow'), 10) || 0;
            const rtl = getComputedStyle(els.progress).direction === 'rtl';
            let next = current;
            if (e.key === 'Home') next = 0;
            else if (e.key === 'End') next = 100;
            else if (e.key === 'ArrowLeft') next += rtl ? 5 : -5;
            else if (e.key === 'ArrowRight') next += rtl ? -5 : 5;
            else return;
            e.preventDefault();
            e.stopPropagation();
            seekOverall(Math.max(0, Math.min(100, next)) / 100);
        });
        if (els.tbHide) els.tbHide.addEventListener('click', () => setHideMode(!state.hideText));
        if (els.tbWaqf) {
            els.tbWaqf.checked = _waqfVisible;
            els.tbWaqf.addEventListener('change', () => setWaqfMarks(els.tbWaqf.checked));
        }
        setupVolume();
        // Recite & follow (lazy-load the ASR module)
        if (els.reciteBtn) els.reciteBtn.addEventListener('click', startReciteFollow);
        window.addEventListener('pagehide', () => stopReciteFollow(false));

        let resizeId = 0;
        window.addEventListener('resize', () => {
            clearTimeout(resizeId);
            resizeId = setTimeout(() => { if (state.focusPage) { sizePages(); applyFontSize(true); justifyLines(); } }, 120);
        });
    }

    let _selectionRequest = 0;
    async function renderSelection() {
        const request = ++_selectionRequest;
        rebuildSelectedKeys();
        const range = visualAyahRange();
        if (!range) {
            applySelectionHighlight();
            setStatus('');
            return true;
        }
        const [a] = range;
        setStatus('جارٍ فتح صفحة المصحف…');
        const ok = await ensureVerseVisible(state.surah, a);
        if (request !== _selectionRequest) return false;
        if (!ok) {
            // Shemrly only ships select pages; don't treat a missing one as an error.
            setStatus(state.src === 'shamarly'
                ? 'هذه الآية غير متوفرة بخط الشمرلي بعد — اختر سورة/آية ضمن الصفحات المتاحة'
                : 'تعذّر تحديد موضع الآية في المصحف', state.src !== 'shamarly');
            return;
        }
        applySelectionHighlight();
        setStatus('');
        return true;
    }

    function applyDeepLink() {
        const p = new URLSearchParams(location.search);
        const src = p.get('src');
        if (isMadinahSource(src)) {
            state.src = src;
            els.src.value = src;
            saveSetting('mz_src', src);
            applySrcClass();
            syncBarLabels();
        }
        const tj = p.get('tajweed');
        if (tj === '1' || tj === '0') { state.tajweedOn = tj === '1'; syncTajweedButton(); saveSetting('quranApp_tajweedEnabled', state.tajweedOn); }
        const jq = parseInt(p.get('justify'), 10);
        if (Number.isFinite(jq)) { state.justify = Math.max(0, Math.min(100, jq)); els.justify.value = state.justify; updateJustifyLabel(); saveSetting('quranApp_khattJustify', state.justify); }
        const wq = p.get('waqf');
        if (wq != null) {
            const selected = wq.split(',').map(s => s.trim()).find(v => WAQF_CHOICES.includes(v));
            state.mushafVersions = [selected || WAQF_CHOICES[0]];
            saveSetting('mz_waqf_print', JSON.stringify(state.mushafVersions));
            syncWaqfChoiceButtons();
        }
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
        const flag = new URLSearchParams(location.search).get('asr');
        if (flag === '1') localStorage.setItem('mz_asr_dev', '1');
        else if (flag === '0') localStorage.removeItem('mz_asr_dev');
        const dev = flag === '1' || (flag !== '0' && localStorage.getItem('mz_asr_dev') === '1');
        const box = $('mz-asr-dev');
        if (box) box.hidden = !dev;
    }

    async function init() {
        loadSettings();
        gateReciteFeature();
        syncSrcCapabilities();
        bindEvents();
        await loadShemrlyPages();
        await loadWaqfPills();
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
            const loaded = await loadSurahMemo(parseInt(els.surah.value, 10) || 1);
            if (!loaded) return;
            if (hasDeepLink) {
                const p = new URLSearchParams(location.search);
                const from = parseInt(p.get('from'), 10), to = parseInt(p.get('to'), 10);
                if (from && [...els.from.options].some(o => +o.value === from)) els.from.value = from;
                if (to && [...els.to.options].some(o => +o.value === to)) els.to.value = to;
                commitRangeFromControls();
            }
            await renderSelection();
            if (state.hideText) setHideMode(true);
            // Re-fit once the mushaf fonts are actually loaded (initial measure
            // may have used fallback metrics).
            if (document.fonts && document.fonts.ready) {
                document.fonts.ready.then(() => {
                    if (state.focusPage) { applyFontSize(true); requestAnimationFrame(justifyLines); }
                });
            }
        } catch (e) {
            setStatus('تعذّر تهيئة الصفحة', true);
        }
    }

    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
    else init();
})();
