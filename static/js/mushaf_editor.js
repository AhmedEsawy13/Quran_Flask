/* ═══════════════════════════════════════════════════════════════════
   Mushaf Editor — مصحف قطر / مصحف الكويت الحديث
   One digital page beside a remote printed-edition reference. Click a
   word to set its waqf mark for the selected edition; words whose mark
   differs from وقوف المدينة (the seeded baseline) are highlighted.
   Peer mushafs (الأزهر / الشمرلي / المدينتان) hint when they mark a word
   you left empty. الكويت gets surah-end ركوع via seed script.

   Endpoints:
     GET  /api/mushaf-editor/auth/status
     POST /api/mushaf-editor/login | logout
     GET  /api/mushaf-editor/spread/<n>?edition=قطر|الكويت
     POST /api/mushaf-editor/waqf      {word_id, edition, symbol}
     GET  /api/mushaf-editor/progress?edition=...
     POST /api/mushaf-editor/progress  {edition, page_number, reviewed}
     POST /api/mushaf-editor/publish   {edition, expected_changes}  (admin)
     GET  /api/mushaf-editor/audit?edition=...
   ═══════════════════════════════════════════════════════════════════ */
(function () {
    'use strict';
    const $ = id => document.getElementById(id);
    const { normalizeNonWarshWaqfText, stripEmbeddedWaqf } = window.AtharMushaf;
    const { toAr, clearPageChrome, renderPageChrome } = window.AtharPageChrome;

    const MAX_SPREAD = 302;
    const MAX_PAGE = 604;

    // Printed scans on Archive.org — one JPG leaf per Madinah page.
    // Confirmed: leaf 4 = page 1 (سورة الفاتحة) for both editions, so
    // leaf = madinah_page + 3. Details URLs still use 1-based /page/N
    // (page 1 → /page/5).
    const REF_SOURCES = {
        'الكويت': { id: 'kweat--h4794794946945969', label: 'مرجع الكويت الحديث' },
        'قطر': { id: 'MushafQatar_20150445776437', label: 'مرجع مصحف قطر' },
    };
    const REF_LEAF_OFFSET = 3;
    const REF_IMG_WIDTH = 1024;
    const REF_DEBOUNCE_MS = 120;

    // Printed-mushaf waqf symbols → meaning + glyph (same as waqf_guide.js).
    const WAQF_SYM = {
        'م':  { name: 'لازم' },
        'لا': { name: 'لا وقف' },
        'ق':  { name: 'الوقف أولى' },
        'ص':  { name: 'الوصل أولى' },
        'ج':  { name: 'جائز' },
        'س':  { name: 'سكتة' },
        'ع':  { name: 'معانقة' },
        'ركوع': { name: 'يصلح الوقف هنا (ركوع)' },
    };
    const waqfGlyph = symbol => symbol === 'ركوع' ? symbol : normalizeNonWarshWaqfText(symbol);
    // ركوع marks are anchored to the ayah-end number rather than appearing
    // inline like other waqf marks — render them as a small badge above it.
    const ABOVE_VERSE_MARKS = new Set(['ركوع']);
    const PEER_VERSIONS = ['المدينة الجديد', 'المدينة القديم', 'الأزهر', 'الشمرلي'];
    const PEER_SHORT = {
        'المدينة الجديد': 'المدينة',
        'المدينة القديم': 'القديم',
        'الأزهر': 'الأزهر',
        'الشمرلي': 'الشمرلي',
    };
    const ACTION_AR = {
        set_mark: 'تعيين',
        clear_mark: 'مسح',
        review_page: 'مراجعة',
        publish: 'اعتماد',
        login: 'دخول',
    };

    const els = {
        main: $('athar-main'),
        page: $('ed-page'),
        pageNum: $('ed-page-num'),
        juz: $('ed-juz'),
        surah: $('ed-surah'),
        pageLabel: $('ed-page-label'),
        progress: $('ed-progress'),
        reviewed: $('ed-reviewed'),
        jumpInput: $('ed-jump-page'), jumpBtn: $('ed-jump-go'),
        draftsWrap: $('ed-drafts'),
        draftsOpen: $('ed-drafts-open'),
        draftsBadge: $('ed-drafts-badge'),
        draftsPrev: $('ed-drafts-prev'),
        draftsNext: $('ed-drafts-next'),
        draftsPanel: $('ed-drafts-panel'),
        draftsHint: $('ed-drafts-hint'),
        draftsList: $('ed-drafts-list'),
        prev: $('ed-prev'), next: $('ed-next'),
        bar: $('ed-bar'),
        barToggle: $('ed-bar-toggle'),
        zoomIn: $('ed-zoom-in'),
        zoomOut: $('ed-zoom-out'),
        zoomReset: $('ed-zoom-reset'),
        editionBtns: Array.from(document.querySelectorAll('.ed-edition-btn')),
        status: $('ed-status'),
        legend: $('ed-legend'),
        audit: $('ed-audit'),
        login: $('ed-login'),
        loginForm: $('ed-login-form'),
        loginCode: $('ed-login-code'),
        loginError: $('ed-login-error'),
        loginSubmit: $('ed-login-submit'),
        session: $('ed-session'),
        sessionName: $('ed-session-name'),
        publishBtn: $('ed-publish'),
        pendingPanel: $('ed-pending-panel'),
        pendingBackdrop: $('ed-pending-backdrop'),
        pendingClose: $('ed-pending-close'),
        pendingDismiss: $('ed-pending-dismiss'),
        pendingList: $('ed-pending-list'),
        pendingHint: $('ed-pending-hint'),
        pendingConfirm: $('ed-pending-confirm'),
        pendingNav: $('ed-pending-nav'),
        pendingPrev: $('ed-pending-prev'),
        pendingNext: $('ed-pending-next'),
        pendingPos: $('ed-pending-pos'),
        invitesOpen: $('ed-invites-open'),
        invitesPanel: $('ed-invites-panel'),
        invitesBackdrop: $('ed-invites-backdrop'),
        invitesClose: $('ed-invites-close'),
        invitesForm: $('ed-invites-form'),
        inviteName: $('ed-invite-name'),
        inviteRole: $('ed-invite-role'),
        inviteCode: $('ed-invite-code'),
        inviteSubmit: $('ed-invite-submit'),
        inviteCreated: $('ed-invite-created'),
        inviteCreatedCode: $('ed-invite-created-code'),
        inviteCopy: $('ed-invite-copy'),
        invitesList: $('ed-invites-list'),
        logoutBtn: $('ed-logout'),
        refTitle: $('ed-ref-title'),
        refOpen: $('ed-ref-open'),
        refImg: $('ed-ref-img'),
        refLoading: $('ed-ref-loading'),
        refFallback: $('ed-ref-fallback'),
        refFallbackBtn: $('ed-ref-fallback-btn'),
        popup: $('ed-popup'), popupBackdrop: $('ed-popup-backdrop'),
        popupTitle: $('ed-popup-title'), popupBaseline: $('ed-popup-baseline'),
        popupPeers: $('ed-popup-peers'),
        popupSyms: $('ed-popup-syms'), popupClear: $('ed-popup-clear'), popupClose: $('ed-popup-close'),
    };

    const ZOOM_MIN = 0.75;
    const ZOOM_MAX = 5;
    const ZOOM_STEP = 0.1;

    function readStoredZoom() {
        const raw = parseFloat(localStorage.getItem('ed_page_zoom') || '1');
        if (!Number.isFinite(raw)) return 1;
        return Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, Math.round(raw * 100) / 100));
    }

    const state = {
        edition: localStorage.getItem('ed_edition') || 'قطر',
        page: initialPage(),
        reviewedPages: new Set(),
        activeWord: null,
        currentPages: [],
        refUrl: '',
        refMeta: null,
        cloud: false,
        user: null,
        ready: false,
        pendingChanges: [],
        pendingIndex: -1,
        pendingPages: [],
        pageZoom: readStoredZoom(),
        barExpanded: localStorage.getItem('ed_bar_expanded') !== '0',
    };
    const spreadRequests = window.AtharMushaf.createRequestGate();
    const progressRequests = window.AtharMushaf.createRequestGate();
    let popupReturnFocus = null;
    let popupBusy = false;
    let refTimer = 0;
    let refLoadToken = 0;
    const refPrefetch = new Set();

    function clampPage(n) {
        if (!Number.isFinite(n)) return 1;
        return Math.min(MAX_PAGE, Math.max(1, n));
    }
    function clampSpread(n) {
        if (!Number.isFinite(n)) return 1;
        return Math.min(MAX_SPREAD, Math.max(1, n));
    }
    function pageToSpread(page) {
        return clampSpread(Math.ceil(page / 2));
    }
    function initialPage() {
        const savedPage = parseInt(localStorage.getItem('ed_page') || '', 10);
        if (Number.isFinite(savedPage)) return clampPage(savedPage);
        const savedSpread = parseInt(localStorage.getItem('ed_spread') || '', 10);
        if (Number.isFinite(savedSpread)) return clampPage(clampSpread(savedSpread) * 2 - 1);
        return 1;
    }

    function persist() {
        localStorage.setItem('ed_edition', state.edition);
        localStorage.setItem('ed_page', String(state.page));
        localStorage.setItem('ed_spread', String(pageToSpread(state.page)));
    }

    const status = window.AtharUi.createStatus(els.status, {
        visibleClass: 'ed-show', errorClass: 'ed-err', defaultDuration: 2200,
    });
    function setStatus(msg, isErr) {
        status.show(msg, { error: !!isErr });
    }

    /* ── Legend ──────────────────────────────────────────────────── */
    function buildLegend() {
        els.legend.innerHTML = '';
        Object.entries(WAQF_SYM).forEach(([sym, meta]) => {
            const chip = document.createElement('span');
            chip.className = 'ed-legend-chip';
            chip.innerHTML = `<span class="ed-legend-glyph">${waqfGlyph(sym)}</span><span>${meta.name} (${sym})</span>`;
            els.legend.appendChild(chip);
        });
        const diff = document.createElement('span');
        diff.className = 'ed-legend-chip ed-legend-diff';
        diff.innerHTML = '<span class="ed-legend-swatch"></span><span>يختلف عن وقف المدينة</span>';
        els.legend.appendChild(diff);
        const peer = document.createElement('span');
        peer.className = 'ed-legend-chip ed-legend-peer';
        peer.innerHTML = '<span class="ed-legend-swatch"></span><span>علامة في مصحف مرجعي (لم تُثبَّت بعد)</span>';
        els.legend.appendChild(peer);
    }

    function peerMarksFromEntries(entries) {
        const list = [];
        (Array.isArray(entries) ? entries : []).forEach(entry => {
            const version = entry && entry.version;
            const symbols = (entry && entry.symbols) || '';
            if (!version || !symbols || !PEER_VERSIONS.includes(version)) return;
            list.push({ version, symbols });
        });
        return list;
    }
    /** Underline hint: other mushafs mark this word, and the working edition does not.
     *  Exclude المدينة الجديد — that baseline is already shown via the orange ed-diff. */
    function peerHintFromList(editionSym, peerList) {
        if (editionSym) return false;
        return (peerList || []).some(p => p.version && p.version !== 'المدينة الجديد');
    }

    /* ── Edition toggle ──────────────────────────────────────────── */
    function updateEditionUI() {
        els.editionBtns.forEach(b => {
            const active = b.dataset.edition === state.edition;
            b.classList.toggle('ed-active', active);
            b.setAttribute('aria-pressed', String(active));
        });
        // قطر → KATypical Naskh; الكويت → DigitalKhatt Al-Shamiya (1978).
        document.body.classList.toggle('ed-font-qatar', state.edition === 'قطر');
        document.body.classList.toggle('ed-font-kuwait', state.edition === 'الكويت');
        document.body.classList.remove('ed-font-hafs');
        updateRefChrome();
    }
    els.editionBtns.forEach(btn => btn.addEventListener('click', () => {
        if (btn.dataset.edition === state.edition) return;
        const prevEdition = state.edition;
        state.edition = btn.dataset.edition;
        persist();
        updateEditionUI();
        closePopup();
        invalidateSpreadCache(prevEdition);
        loadProgress();
        loadPage();
        loadAudit();
        loadPendingPages();
    }));

    /* ── Reference material (Archive.org leaf images) ────────────── */
    function refSource() {
        return REF_SOURCES[state.edition] || null;
    }
    function pageToLeaf(page) {
        return page + REF_LEAF_OFFSET;
    }
    function refImageUrl(id, page) {
        return `https://archive.org/download/${id}/page/leaf${pageToLeaf(page)}_w${REF_IMG_WIDTH}.jpg`;
    }
    function refOpenUrl(id, page) {
        // Archive.org details /page/N is 1-based (leaf 4 → /page/5).
        return `https://archive.org/details/${id}/page/${pageToLeaf(page) + 1}`;
    }
    function updateRefChrome() {
        const src = refSource();
        els.refTitle.textContent = src ? src.label : 'المرجع';
        const label = src ? `فتح ${src.label} في الأرشيف` : 'فتح المرجع';
        els.refOpen.title = label;
        els.refOpen.setAttribute('aria-label', label);
    }
    function buildReferenceUrls(meta) {
        const src = refSource();
        if (!src || !meta || !Number.isFinite(meta.page)) return null;
        if (meta.page < 1 || meta.page > MAX_PAGE) return null;
        return {
            image: refImageUrl(src.id, meta.page),
            open: refOpenUrl(src.id, meta.page),
        };
    }
    function showRefState({ loading = false, image = false, fallback = false } = {}) {
        els.refLoading.hidden = !loading;
        els.refImg.hidden = !image;
        els.refFallback.hidden = !fallback;
    }
    function clearReference() {
        state.refUrl = '';
        state.refMeta = null;
        els.refOpen.hidden = true;
        showRefState();
        els.refImg.removeAttribute('src');
        els.refImg.alt = 'صفحة المصحف المطبوع';
    }
    function openReference() {
        if (!state.refUrl) return;
        window.open(state.refUrl, '_blank', 'noopener');
    }
    function prefetchRef(id, page) {
        if (page < 1 || page > MAX_PAGE) return;
        const url = refImageUrl(id, page);
        if (refPrefetch.has(url)) return;
        refPrefetch.add(url);
        const img = new Image();
        img.decoding = 'async';
        img.src = url;
    }
    function syncReference(meta) {
        clearTimeout(refTimer);
        const urls = buildReferenceUrls(meta);
        if (!urls) {
            clearReference();
            return;
        }
        state.refMeta = meta;
        state.refUrl = urls.open;
        els.refOpen.hidden = false;
        updateRefChrome();
        const token = ++refLoadToken;
        const src = refSource();
        refTimer = setTimeout(() => {
            if (token !== refLoadToken) return;
            showRefState({ loading: true });
            els.refImg.alt = `${src.label} — صفحة ${meta.page}`;
            const onLoad = () => {
                if (token !== refLoadToken) return;
                showRefState({ image: true });
                prefetchRef(src.id, meta.page + 1);
                prefetchRef(src.id, meta.page - 1);
            };
            const onError = () => {
                if (token !== refLoadToken) return;
                showRefState({ fallback: true });
            };
            els.refImg.onload = onLoad;
            els.refImg.onerror = onError;
            // Same URL can be cache-hit with no load event — force via assign.
            if (els.refImg.getAttribute('src') === urls.image && els.refImg.complete && els.refImg.naturalWidth) {
                onLoad();
                return;
            }
            els.refImg.src = urls.image;
        }, REF_DEBOUNCE_MS);
    }
    els.refOpen.addEventListener('click', openReference);
    els.refFallbackBtn.addEventListener('click', openReference);

    /* ── Page rendering ──────────────────────────────────────────── */
    function renderPage(payload) {
        const container = els.page;
        container.innerHTML = '';
        if (!payload) {
            clearPageChrome({
                juzEl: els.juz, surahEl: els.surah, pageNumberEl: els.pageNum,
                juzGlyphClass: 'athar-page-juz-glyph',
            });
            clearReference();
            return;
        }
        window.AtharMushaf.renderMushafLines(container, payload.lines || [], {
            lineClass: 'ed-line',
            surahClass: 'ed-line ed-line-special',
            basmalaClass: 'ed-line ed-line-special',
            wrapSpecial: false,
            contentClass: 'ed-line-inner',
            separator: ' ',
            wordClass: 'ed-word',
            countWord: () => false,
            textForWord: context => stripEmbeddedWaqf(context.raw),
            decorateLine: (root, { line }) => { root.dataset.justify = line.is_centered ? '0' : '1'; },
            decorateWord: (wordElement, context) => {
                const w = context.word;
                const cleanText = stripEmbeddedWaqf(w.text || '');
                wordElement.dataset.wordId = String(w.word_index);
                wordElement.dataset.text = cleanText;
                wordElement.tabIndex = 0;
                wordElement.setAttribute('role', 'button');
                const entries = Array.isArray(w.waqf_symbols) ? w.waqf_symbols : [];
                const editionEntry = entries.find(e => e.version === state.edition);
                const baselineEntry = entries.find(e => e.version === 'المدينة الجديد');
                const editionSym = (editionEntry && editionEntry.symbols) || '';
                const baselineSym = (baselineEntry && baselineEntry.symbols) || '';
                const peers = peerMarksFromEntries(entries);
                wordElement.dataset.baseline = baselineSym;
                wordElement.dataset.peers = JSON.stringify(peers);
                applyWordMark(wordElement, editionSym, baselineSym, peers);
            },
        });

        renderPageChrome({
            payload, juzEl: els.juz, surahEl: els.surah, pageNumberEl: els.pageNum,
            juzGlyphClass: 'athar-page-juz-glyph',
            surahGlyphClass: 'athar-page-surah-glyph',
            surahTextClass: 'athar-page-surah-text',
        });

        syncReference({
            page: payload.page_number,
            surah: payload.anchor_surah_number,
            ayah: payload.anchor_ayah_number,
        });
    }

    /* ── Page sizing & line-fit ────────────────────────────────────── */
    const PAGE_RATIO = 0.66; // width / height

    function zoomPercentLabel(z) {
        return `${toAr(Math.round(z * 100))}٪`;
    }

    function updateZoomUI() {
        if (els.zoomReset) els.zoomReset.textContent = zoomPercentLabel(state.pageZoom);
        if (els.zoomOut) els.zoomOut.disabled = state.pageZoom <= ZOOM_MIN + 0.001;
        if (els.zoomIn) els.zoomIn.disabled = state.pageZoom >= ZOOM_MAX - 0.001;
    }

    function setPageZoom(next, { silent } = {}) {
        const z = Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, Math.round(next * 100) / 100));
        if (Math.abs(z - state.pageZoom) < 0.001) {
            updateZoomUI();
            return;
        }
        state.pageZoom = z;
        localStorage.setItem('ed_page_zoom', String(z));
        updateZoomUI();
        fitPages();
        if (!silent) setStatus(`تكبير الصفحة ${zoomPercentLabel(z)}`);
    }

    function applyBarExpanded(expanded) {
        state.barExpanded = !!expanded;
        localStorage.setItem('ed_bar_expanded', state.barExpanded ? '1' : '0');
        if (els.bar) {
            els.bar.classList.toggle('ed-bar--compact', !state.barExpanded);
            els.bar.dataset.expanded = state.barExpanded ? 'true' : 'false';
        }
        if (els.barToggle) {
            els.barToggle.setAttribute('aria-expanded', state.barExpanded ? 'true' : 'false');
            els.barToggle.title = state.barExpanded ? 'طيّ شريط الأدوات' : 'توسيع شريط الأدوات';
            const label = els.barToggle.querySelector('.ed-bar-toggle-label');
            if (label) label.textContent = state.barExpanded ? 'طيّ' : 'توسيع';
        }
    }

    function sizePages() {
        const main = document.querySelector('.ed-main');
        if (!main) return;
        const outerHeight = element => {
            if (!element) return 0;
            const style = getComputedStyle(element);
            return element.getBoundingClientRect().height
                + (parseFloat(style.marginTop) || 0)
                + (parseFloat(style.marginBottom) || 0);
        };
        const mainStyle = getComputedStyle(main);
        const mainPad = (parseFloat(mainStyle.paddingTop) || 0)
            + (parseFloat(mainStyle.paddingBottom) || 0);
        const availableWidth = main.clientWidth - 20;
        const fixedChrome = outerHeight(document.querySelector('.athar-bar'))
            + outerHeight(document.querySelector('.ed-bar'))
            + outerHeight(els.legend)
            + outerHeight(document.querySelector('.ed-page-header'))
            + mainPad;
        const stacked = window.matchMedia('(max-width: 720px)').matches;
        // Work page + reference scan share one equal page box each (same
        // dual-page budget as the old facing-page spread).
        window.AtharPageChrome.sizePages({
            cssVarPrefix: 'ed', pages: stacked ? 1 : 2, ratio: PAGE_RATIO,
            gutter: stacked ? 0 : 18, floor: true,
            getAvailH: () => stacked ? availableWidth / PAGE_RATIO : window.innerHeight - fixedChrome,
            getAvailW: () => availableWidth,
        });
        // Apply UI zoom after the viewport fit — enlarges/shrinks both the
        // digital page and the reference panel (shared --ed-page-*).
        if (Math.abs(state.pageZoom - 1) > 0.001) {
            const root = document.documentElement;
            const w = parseFloat(getComputedStyle(root).getPropertyValue('--ed-page-w'));
            const h = parseFloat(getComputedStyle(root).getPropertyValue('--ed-page-h'));
            if (Number.isFinite(w) && Number.isFinite(h) && w > 0 && h > 0) {
                root.style.setProperty('--ed-page-w', `${Math.round(w * state.pageZoom)}px`);
                root.style.setProperty('--ed-page-h', `${Math.round(h * state.pageZoom)}px`);
            }
        }
    }

    const applyFontSize = window.AtharPageChrome.createFontSizer({
        pageEls: () => [els.page].filter(p => p && p.children.length),
        lineSelector: '.ed-line', innerSelector: '.ed-line-inner',
        cssVarName: '--ed-fs', linesPerPage: 15,
        // v3: bust stale fitFs cached against wrong page-box height.
        cacheKey: () => `${state.edition}|fs3|z${state.pageZoom}`,
    });

    const justifyLines = window.AtharPageChrome.createLineJustifier({
        containerEls: () => [els.page],
        lineSelector: '.ed-line', innerSelector: '.ed-line-inner', wordSelector: '.ed-word',
        // الكويت / Al Shamiya: progressive jalt+jt/dc/kt (all-at-once overshoots).
        // قطر / KATypical: only jalt exists — Digital Khatt jt/dc/kt tags are no-ops.
        featureSettings: () => '',
        featureCandidates: () => {
            if (state.edition === 'الكويت') {
                return window.AtharPageChrome.alShamiyaFeatureCandidates(100);
            }
            if (state.edition === 'قطر') {
                return window.AtharPageChrome.katypicalFeatureCandidates(100);
            }
            return null;
        },
        minFeatureScale: () => {
            if (state.edition === 'الكويت') return 0.94;
            // KATypical only has binary jalt (big jump). Allow mild condense
            // so elongation still wins over word rivers when jalt overshoots.
            if (state.edition === 'قطر') return 0.88;
            return 1;
        },
        // Cap residual gaps so leftover slack prefers kashida/jalt over rivers,
        // but leave a little room — printed Naskh is not pure stretch either.
        maxWordSpacing: () => (
            state.edition === 'الكويت' || state.edition === 'قطر' ? 1.75 : Infinity
        ),
        preferExpansion: () => (
            state.edition === 'الكويت' || state.edition === 'قطر'
        ),
        preferExpansionSlack: 3,
        // Avoid stringy whole-line stretch when jalt still leaves slack.
        maxStretch: () => (state.edition === 'قطر' ? 1.06 : Infinity),
    });

    function fitPages() {
        sizePages();
        // Flush CSS page-box vars before measuring — otherwise clientHeight can
        // still be the previous (often shorter) box and the font sizer locks to
        // maxFs from that stale height.
        if (els.page) void els.page.offsetHeight;
        applyFontSize();
        requestAnimationFrame(() => {
            applyFontSize();
            justifyLines();
        });
    }

    function applyWordMark(span, editionSym, baselineSym, peers) {
        span.dataset.symbol = editionSym || '';
        let mark = span.querySelector('.ed-waqf-mark');
        if (editionSym) {
            if (!mark) {
                mark = document.createElement('span');
                mark.className = 'ed-waqf-mark';
                span.appendChild(mark);
            }
            mark.textContent = waqfGlyph(editionSym);
            mark.classList.toggle('ed-mark-above', ABOVE_VERSE_MARKS.has(editionSym));
        } else if (mark) {
            mark.remove();
        }
        const baseline = baselineSym !== undefined ? baselineSym : (span.dataset.baseline || '');
        let peerList = peers;
        if (!Array.isArray(peerList)) {
            try { peerList = JSON.parse(span.dataset.peers || '[]'); } catch (_e) { peerList = []; }
        }
        const peerHint = peerHintFromList(editionSym, peerList);
        span.classList.toggle('ed-diff', (editionSym || '') !== (baseline || ''));
        span.classList.toggle('ed-peer-hint', peerHint);
        const peerTip = peerList.length
            ? peerList.map(p => `${PEER_SHORT[p.version] || p.version}: ${waqfGlyph(p.symbols)}`).join(' · ')
            : '';
        const parts = [
            baseline ? `المدينة: ${waqfGlyph(baseline)} (${baseline})` : 'المدينة: بلا علامة',
            peerTip ? `مراجع: ${peerTip}` : '',
        ].filter(Boolean);
        span.title = parts.join(' | ');
        const currentLabel = editionSym
            ? `${WAQF_SYM[editionSym]?.name || editionSym} (${editionSym})`
            : (peerHint ? 'بلا علامة — يوجد وقف في مصحف مرجعي' : 'بلا علامة');
        span.setAttribute('aria-label', `تعديل وقف ${span.dataset.text || span.textContent}: ${currentLabel}`);
    }

    /* ── Loading a page (via spread API) ──────────────────────────── */
    const spreadCache = new Map(); // `${edition}:${spread}` → payload
    const spreadPrefetching = new Set();
    function spreadCacheKey(edition, spread) {
        return `${edition}:${spread}`;
    }
    function invalidateSpreadCache(edition) {
        const prefix = `${edition}:`;
        for (const key of [...spreadCache.keys()]) {
            if (key.startsWith(prefix)) spreadCache.delete(key);
        }
        spreadPrefetching.clear();
    }
    async function fetchSpread(spread, edition, { background = false } = {}) {
        const key = spreadCacheKey(edition, spread);
        if (spreadCache.has(key)) return spreadCache.get(key);
        if (background && spreadPrefetching.has(key)) return null;
        if (background) spreadPrefetching.add(key);
        try {
            const query = window.AtharMushaf.buildQuery({ params: { edition } });
            const data = await window.AtharApi.json(`/api/mushaf-editor/spread/${spread}${query}`);
            if (state.edition === edition) spreadCache.set(key, data);
            return data;
        } finally {
            if (background) spreadPrefetching.delete(key);
        }
    }
    function prefetchNeighborSpreads(spread, edition) {
        [spread - 1, spread + 1].forEach(n => {
            if (n < 1 || n > MAX_SPREAD) return;
            if (spreadCache.has(spreadCacheKey(edition, n))) return;
            fetchSpread(n, edition, { background: true }).catch(() => {});
        });
    }
    async function loadPage() {
        const request = spreadRequests.next();
        const page = state.page;
        const spread = pageToSpread(page);
        const edition = state.edition;
        const wantRight = page % 2 === 1;
        const cacheHit = spreadCache.has(spreadCacheKey(edition, spread));
        if (!cacheHit) window.AtharUi.setBusy(els.main, true);
        try {
            const data = await fetchSpread(spread, edition);
            if (!spreadRequests.isCurrent(request)) return false;
            if (!data) {
                setStatus('تعذّر تحميل الصفحة', true);
                return false;
            }
            const payload = wantRight ? data.right : data.left;
            renderPage(payload || null);
            els.pageLabel.textContent = `${toAr(page)} / ${toAr(MAX_PAGE)}`;
            state.currentPages = payload ? [payload.page_number] : [];
            updateReviewedCheckbox();
            updateNavButtons();
            fitPages();
            prefetchNeighborSpreads(spread, edition);
            return true;
        } catch (e) {
            if (spreadRequests.isCurrent(request)) setStatus('تعذّر تحميل الصفحة', true);
            return false;
        } finally {
            if (spreadRequests.isCurrent(request)) window.AtharUi.setBusy(els.main, false);
        }
    }

    function updateNavButtons() {
        els.prev.disabled = state.page <= 1;
        els.next.disabled = state.page >= MAX_PAGE;
        updateDraftsNavButtons();
    }

    /* ── Pages with pending drafts ───────────────────────────────── */
    function closeDraftsPanel() {
        if (!els.draftsPanel) return;
        els.draftsPanel.hidden = true;
        if (els.draftsOpen) els.draftsOpen.setAttribute('aria-expanded', 'false');
    }
    function toggleDraftsPanel() {
        if (!els.draftsPanel || !els.draftsOpen) return;
        const open = els.draftsPanel.hidden;
        els.draftsPanel.hidden = !open;
        els.draftsOpen.setAttribute('aria-expanded', String(open));
    }
    function updateDraftsNavButtons() {
        const pages = state.pendingPages || [];
        const idx = pages.findIndex(p => p.page_number === state.page);
        const has = pages.length > 0;
        // Off-list: both arrows jump to an end. On first/last draft page: disable that edge.
        if (els.draftsPrev) els.draftsPrev.disabled = !has || idx === 0;
        if (els.draftsNext) els.draftsNext.disabled = !has || (idx >= 0 && idx === pages.length - 1);
        if (els.draftsList) {
            els.draftsList.querySelectorAll('.ed-drafts-row').forEach(btn => {
                const page = Number(btn.dataset.page);
                btn.classList.toggle('is-current', page === state.page);
            });
        }
    }
    function renderDraftsPages(pages) {
        state.pendingPages = Array.isArray(pages) ? pages : [];
        if (!els.draftsWrap) return;
        const n = state.pendingPages.length;
        els.draftsWrap.hidden = !state.cloud || !state.user;
        if (els.draftsBadge) els.draftsBadge.textContent = toAr(n);
        if (els.draftsOpen) {
            els.draftsOpen.classList.toggle('is-empty', n === 0);
            els.draftsOpen.title = n
                ? `${toAr(n)} صفحة فيها مسودّات معلّقة`
                : 'لا مسودّات معلّقة';
        }
        if (els.draftsHint) {
            els.draftsHint.textContent = n
                ? `نسخة «${state.edition}»: ${toAr(n)} صفحة بانتظار الاعتماد. انقر للانتقال.`
                : `نسخة «${state.edition}»: لا مسودّات معلّقة.`;
        }
        if (els.draftsList) {
            els.draftsList.innerHTML = '';
            state.pendingPages.forEach(p => {
                const li = document.createElement('li');
                const btn = document.createElement('button');
                btn.type = 'button';
                btn.className = 'ed-drafts-row';
                btn.dataset.page = String(p.page_number);
                btn.setAttribute('role', 'option');
                const title = document.createElement('span');
                title.className = 'ed-drafts-row-page';
                title.textContent = `ص ${toAr(p.page_number)}`;
                const count = document.createElement('span');
                count.className = 'ed-drafts-row-count';
                count.textContent = `${toAr(p.count)} تغيير`;
                const meta = document.createElement('span');
                meta.className = 'ed-drafts-row-meta';
                meta.textContent = (p.surah && p.ayah) ? `${p.surah}:${p.ayah}` : '';
                btn.append(title, count, meta);
                btn.addEventListener('click', () => {
                    closeDraftsPanel();
                    goToDraftPage(p.page_number);
                });
                li.appendChild(btn);
                els.draftsList.appendChild(li);
            });
        }
        updateDraftsNavButtons();
    }
    async function loadPendingPages() {
        if (!state.cloud || !state.user) {
            renderDraftsPages([]);
            return;
        }
        try {
            const query = window.AtharMushaf.buildQuery({ params: { edition: state.edition } });
            const data = await window.AtharApi.json(`/api/mushaf-editor/pending${query}`);
            renderDraftsPages(data.pages || []);
        } catch (_e) {
            renderDraftsPages([]);
        }
    }
    async function goToDraftPage(page) {
        const p = Number(page);
        if (!Number.isFinite(p) || p < 1 || p > MAX_PAGE) return;
        state.page = p;
        persist();
        closePopup();
        closeDraftsPanel();
        await loadPage();
        // Prefer focusing the first pending change on this page if the publish drawer data is loaded.
        const onPage = (state.pendingChanges || []).filter(ch => Number(ch.page_number) === p);
        if (onPage.length) {
            const idx = state.pendingChanges.indexOf(onPage[0]);
            if (idx >= 0) jumpToPendingChange(onPage[0], idx);
        } else {
            setStatus(`مسودّة · ص ${toAr(p)}`);
        }
    }
    function stepDraftPage(delta) {
        const pages = state.pendingPages || [];
        if (!pages.length) return;
        let idx = pages.findIndex(p => p.page_number === state.page);
        if (idx < 0) {
            // Not currently on a draft page — next goes to first, prev to last.
            goToDraftPage(delta > 0 ? pages[0].page_number : pages[pages.length - 1].page_number);
            return;
        }
        const next = pages[idx + delta];
        if (next) goToDraftPage(next.page_number);
    }
    if (els.draftsOpen) els.draftsOpen.addEventListener('click', toggleDraftsPanel);
    if (els.draftsPrev) els.draftsPrev.addEventListener('click', () => stepDraftPage(-1));
    if (els.draftsNext) els.draftsNext.addEventListener('click', () => stepDraftPage(1));
    document.addEventListener('click', (event) => {
        if (!els.draftsWrap || !els.draftsPanel || els.draftsPanel.hidden) return;
        if (els.draftsWrap.contains(event.target)) return;
        closeDraftsPanel();
    });

    /* ── Progress tracking ───────────────────────────────────────── */
    async function loadProgress() {
        const request = progressRequests.next();
        const edition = state.edition;
        window.AtharUi.setBusy(els.progress, true);
        try {
            const query = window.AtharMushaf.buildQuery({ params: { edition } });
            const data = await window.AtharApi.json(`/api/mushaf-editor/progress${query}`);
            if (!progressRequests.isCurrent(request)) return;
            state.reviewedPages = new Set(data.reviewed_pages || []);
        } catch (e) {
            if (!progressRequests.isCurrent(request)) return;
            state.reviewedPages = new Set();
            setStatus('تعذّر تحميل تقدّم المراجعة', true);
        } finally {
            if (progressRequests.isCurrent(request)) window.AtharUi.setBusy(els.progress, false);
        }
        updateProgressLabel();
        updateReviewedCheckbox();
    }
    function updateProgressLabel() {
        els.progress.textContent = `${toAr(state.reviewedPages.size)} / ${toAr(MAX_PAGE)} مراجَعة`;
        els.progress.setAttribute('aria-valuenow', String(state.reviewedPages.size));
    }
    function updateReviewedCheckbox() {
        els.reviewed.checked = state.currentPages.length > 0
            && state.currentPages.every(p => state.reviewedPages.has(p));
    }
    els.reviewed.addEventListener('change', async () => {
        const reviewed = els.reviewed.checked;
        const edition = state.edition;
        const pages = [...state.currentPages];
        els.reviewed.disabled = true;
        window.AtharUi.setBusy(els.reviewed.closest('.ed-review-group'), true);
        const results = await Promise.all(pages.map(async page => {
            try {
                await window.AtharApi.json('/api/mushaf-editor/progress', {
                    method: 'POST', headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ edition, page_number: page, reviewed }),
                });
                return { page, ok: true };
            } catch (e) {
                return { page, ok: false };
            }
        }));
        if (state.edition === edition) {
            results.filter(result => result.ok).forEach(result => {
                if (reviewed) state.reviewedPages.add(result.page);
                else state.reviewedPages.delete(result.page);
            });
            updateProgressLabel();
            updateReviewedCheckbox();
        }
        const failed = results.filter(result => !result.ok).length;
        if (failed) setStatus(`تعذّر تحديث ${toAr(failed)} صفحة`, true);
        else setStatus('تم تحديث حالة المراجعة');
        els.reviewed.disabled = false;
        window.AtharUi.setBusy(els.reviewed.closest('.ed-review-group'), false);
    });

    /* ── Navigation ──────────────────────────────────────────────── */
    els.prev.addEventListener('click', () => {
        if (state.page <= 1) return;
        state.page--;
        persist(); closePopup(); loadPage();
    });
    els.next.addEventListener('click', () => {
        if (state.page >= MAX_PAGE) return;
        state.page++;
        persist(); closePopup(); loadPage();
    });
    els.jumpBtn.addEventListener('click', jumpToPage);
    els.jumpInput.addEventListener('keydown', e => { if (e.key === 'Enter') jumpToPage(); });
    els.jumpInput.addEventListener('input', () => els.jumpInput.removeAttribute('aria-invalid'));
    function jumpToPage() {
        const p = parseInt(els.jumpInput.value, 10);
        if (!Number.isFinite(p) || p < 1 || p > MAX_PAGE) {
            els.jumpInput.setAttribute('aria-invalid', 'true');
            setStatus('رقم صفحة غير صالح (١ - ٦٠٤)', true);
            return;
        }
        els.jumpInput.removeAttribute('aria-invalid');
        state.page = clampPage(p);
        els.jumpInput.value = '';
        persist(); closePopup(); loadPage();
    }
    document.addEventListener('keydown', e => {
        if (!els.popup.hidden) {
            if (e.key === 'Escape' && !popupBusy) {
                e.preventDefault();
                closePopup();
            } else if (e.key === 'Tab') {
                trapPopupFocus(e);
            }
            return;
        }
        const word = e.target.closest?.('.ed-word');
        if (word && (e.key === 'Enter' || e.key === ' ')) {
            e.preventDefault();
            openPopup(word);
            return;
        }
        if (e.target.tagName === 'INPUT') return;
        if (e.key === 'ArrowLeft') els.next.click();
        if (e.key === 'ArrowRight') els.prev.click();
    });

    /* ── Word edit popup ─────────────────────────────────────────── */
    function buildPopupButtons() {
        els.popupSyms.innerHTML = '';
        Object.entries(WAQF_SYM).forEach(([sym, meta]) => {
            const b = document.createElement('button');
            b.type = 'button'; b.className = 'ed-sym-btn'; b.dataset.sym = sym;
            b.setAttribute('aria-pressed', 'false');
            b.innerHTML = `<span class="ed-sym-glyph">${waqfGlyph(sym)}</span><span class="ed-sym-name">${meta.name}</span>`;
            b.addEventListener('click', () => setSymbol(sym));
            els.popupSyms.appendChild(b);
        });
    }
    els.popupClear.addEventListener('click', () => setSymbol(''));
    els.popupClose.addEventListener('click', closePopup);
    els.popupBackdrop.addEventListener('click', closePopup);

    function renderPopupPeers(wordEl) {
        if (!els.popupPeers) return;
        els.popupPeers.innerHTML = '';
        let peers = [];
        try { peers = JSON.parse(wordEl.dataset.peers || '[]'); } catch (_e) { peers = []; }
        if (!peers.length) {
            els.popupPeers.hidden = true;
            return;
        }
        els.popupPeers.hidden = false;
        const heading = document.createElement('div');
        heading.className = 'ed-peers-heading';
        heading.textContent = 'علامات في مصاحف مرجعية — انقر لنسخها';
        els.popupPeers.appendChild(heading);
        const row = document.createElement('div');
        row.className = 'ed-peers-row';
        peers.forEach(peer => {
            const btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'ed-peer-btn';
            btn.title = `نسخ علامة ${peer.version}`;
            btn.innerHTML = (
                `<span class="ed-peer-ver">${PEER_SHORT[peer.version] || peer.version}</span>`
                + `<span class="ed-peer-glyph">${waqfGlyph(peer.symbols)}</span>`
            );
            btn.addEventListener('click', () => setSymbol(peer.symbols));
            row.appendChild(btn);
        });
        els.popupPeers.appendChild(row);
    }

    function openPopup(wordEl) {
        if (state.activeWord) state.activeWord.classList.remove('ed-selected');
        popupReturnFocus = wordEl;
        state.activeWord = wordEl;
        wordEl.classList.add('ed-selected');

        els.popupTitle.textContent = wordEl.dataset.text || wordEl.textContent;
        const baseline = wordEl.dataset.baseline || '';
        els.popupBaseline.innerHTML = baseline
            ? `وقف المدينة هنا: <span class="ed-baseline-glyph">${waqfGlyph(baseline)}</span> (${baseline})`
            : 'لا توجد علامة وقف في المدينة عند هذه الكلمة';
        renderPopupPeers(wordEl);

        const current = wordEl.dataset.symbol || '';
        els.popupSyms.querySelectorAll('.ed-sym-btn').forEach(b => {
            const active = b.dataset.sym === current;
            b.classList.toggle('ed-active', active);
            b.setAttribute('aria-pressed', String(active));
        });

        els.popup.hidden = false;
        els.popupBackdrop.hidden = false;
        document.body.classList.add('ed-popup-open');
        requestAnimationFrame(() => {
            if (els.popup.hidden) return;
            const active = els.popupSyms.querySelector('.ed-sym-btn.ed-active');
            (active || els.popupClose).focus();
        });
    }
    function closePopup() {
        if (popupBusy) return;
        if (state.activeWord) state.activeWord.classList.remove('ed-selected');
        state.activeWord = null;
        els.popup.hidden = true;
        els.popupBackdrop.hidden = true;
        document.body.classList.remove('ed-popup-open');
        const returnTo = popupReturnFocus;
        popupReturnFocus = null;
        if (returnTo && returnTo.isConnected) returnTo.focus();
    }
    function trapPopupFocus(event) {
        const peerBtns = els.popupPeers
            ? [...els.popupPeers.querySelectorAll('.ed-peer-btn')]
            : [];
        const focusable = [
            els.popupClose,
            ...peerBtns,
            ...els.popupSyms.querySelectorAll('.ed-sym-btn'),
            els.popupClear,
        ].filter(control => control && !control.disabled);
        if (!focusable.length) return;
        const index = focusable.indexOf(document.activeElement);
        if (event.shiftKey && index <= 0) {
            event.preventDefault();
            focusable[focusable.length - 1].focus();
        } else if (!event.shiftKey && index === focusable.length - 1) {
            event.preventDefault();
            focusable[0].focus();
        }
    }
    function setPopupBusy(busy) {
        popupBusy = !!busy;
        window.AtharUi.setBusy(els.popup, popupBusy);
        const peerBtns = els.popupPeers
            ? [...els.popupPeers.querySelectorAll('.ed-peer-btn')]
            : [];
        [els.popupClose, els.popupClear, ...els.popupSyms.querySelectorAll('.ed-sym-btn'), ...peerBtns]
            .forEach(control => { if (control) control.disabled = popupBusy; });
    }

    async function setSymbol(sym) {
        const wordEl = state.activeWord;
        if (!wordEl || popupBusy) return;
        const wordId = wordEl.dataset.wordId;
        let saved = false;
        setPopupBusy(true);
        try {
            const data = await window.AtharApi.json('/api/mushaf-editor/waqf', {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ word_id: wordId, edition: state.edition, symbol: sym }),
            });
            applyWordMark(wordEl, data.symbol || '', wordEl.dataset.baseline || '');
            requestAnimationFrame(justifyLines);
            saved = true;
            invalidateSpreadCache(state.edition);
            setStatus('تم حفظ علامة الوقف');
            loadAudit();
            loadPendingPages();
        } catch (e) {
            if (e && e.status === 401) {
                showLogin();
                setStatus('يلزم تسجيل الدخول', true);
            } else {
                setStatus('تعذّر حفظ التعديل', true);
            }
        } finally {
            setPopupBusy(false);
        }
        if (saved) closePopup();
    }

    document.addEventListener('click', e => {
        const w = e.target.closest('.ed-word');
        if (w) { openPopup(w); return; }
    });

    /* ── Auth / session ──────────────────────────────────────────── */
    function showLogin() {
        if (!els.login) return;
        els.login.hidden = false;
        if (els.loginError) {
            els.loginError.hidden = true;
            els.loginError.textContent = '';
        }
        if (els.loginCode) {
            els.loginCode.value = '';
            requestAnimationFrame(() => els.loginCode.focus());
        }
    }
    function hideLogin() {
        if (els.login) els.login.hidden = true;
    }
    function updateSessionUI() {
        const cloud = state.cloud;
        const user = state.user;
        const isAdmin = !!(cloud && user && user.role === 'admin');
        if (els.session) els.session.hidden = !cloud || !user;
        if (els.sessionName && user) els.sessionName.textContent = user.name || '';
        if (els.publishBtn) els.publishBtn.hidden = !isAdmin;
        if (els.invitesOpen) els.invitesOpen.hidden = !isAdmin;
    }

    function closeInvitesPanel() {
        if (els.invitesPanel) els.invitesPanel.hidden = true;
        if (els.invitesBackdrop) els.invitesBackdrop.hidden = true;
    }
    function roleLabel(role) {
        return role === 'admin' ? 'مشرف' : 'مراجع';
    }
    function renderInvitesList(invites) {
        if (!els.invitesList) return;
        els.invitesList.innerHTML = '';
        if (!invites.length) {
            const empty = document.createElement('li');
            empty.className = 'ed-invite-row-meta';
            empty.textContent = 'لا توجد دعوات بعد.';
            els.invitesList.appendChild(empty);
            return;
        }
        invites.forEach(inv => {
            const li = document.createElement('li');
            li.className = 'ed-invite-row' + (inv.active ? '' : ' is-revoked');
            const name = document.createElement('span');
            name.className = 'ed-invite-row-name';
            name.textContent = inv.name || '—';
            const btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'ed-invite-revoke';
            btn.textContent = inv.active ? 'إلغاء' : 'إعادة تفعيل';
            btn.addEventListener('click', () => toggleInvite(inv.id, !inv.active));
            const meta = document.createElement('span');
            meta.className = 'ed-invite-row-meta';
            meta.textContent = `${roleLabel(inv.role)} · ${inv.active ? 'نشط' : 'ملغى'}`;
            li.append(name, btn, meta);
            els.invitesList.appendChild(li);
        });
    }
    async function loadInvites() {
        if (!els.invitesList) return;
        try {
            const data = await window.AtharApi.json('/api/mushaf-editor/invites');
            renderInvitesList(data.invites || []);
        } catch (_e) {
            els.invitesList.innerHTML = '<li class="ed-invite-row-meta">تعذّر تحميل الدعوات</li>';
        }
    }
    async function openInvitesPanel() {
        if (!els.invitesPanel) return;
        if (els.inviteCreated) els.inviteCreated.hidden = true;
        if (els.invitesForm) els.invitesForm.reset();
        els.invitesPanel.hidden = false;
        if (els.invitesBackdrop) els.invitesBackdrop.hidden = false;
        await loadInvites();
        if (els.inviteName) els.inviteName.focus();
    }
    async function toggleInvite(id, active) {
        try {
            await window.AtharApi.json(`/api/mushaf-editor/invites/${encodeURIComponent(id)}`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ active }),
            });
            setStatus(active ? 'أُعيد تفعيل الدعوة' : 'أُلغيت الدعوة');
            await loadInvites();
        } catch (_e) {
            setStatus('تعذّر تحديث الدعوة', true);
        }
    }
    if (els.invitesOpen) els.invitesOpen.addEventListener('click', openInvitesPanel);
    if (els.invitesClose) els.invitesClose.addEventListener('click', closeInvitesPanel);
    if (els.invitesBackdrop) els.invitesBackdrop.addEventListener('click', closeInvitesPanel);
    if (els.inviteCopy) {
        els.inviteCopy.addEventListener('click', async () => {
            const code = els.inviteCreatedCode && els.inviteCreatedCode.textContent;
            if (!code) return;
            try {
                await navigator.clipboard.writeText(code);
                setStatus('تم نسخ الرمز');
            } catch (_e) {
                setStatus('انسخ الرمز يدوياً', true);
            }
        });
    }
    if (els.invitesForm) {
        els.invitesForm.addEventListener('submit', async e => {
            e.preventDefault();
            const name = (els.inviteName && els.inviteName.value || '').trim();
            const role = (els.inviteRole && els.inviteRole.value) || 'editor';
            const code = (els.inviteCode && els.inviteCode.value || '').trim();
            if (!name) return;
            if (els.inviteSubmit) els.inviteSubmit.disabled = true;
            try {
                const body = { name, role };
                if (code) body.code = code;
                const data = await window.AtharApi.json('/api/mushaf-editor/invites', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(body),
                });
                if (els.inviteCreated && els.inviteCreatedCode) {
                    els.inviteCreatedCode.textContent = data.code || '';
                    els.inviteCreated.hidden = false;
                }
                if (els.invitesForm) els.invitesForm.reset();
                setStatus(`أُنشئت دعوة لـ ${name}`);
                await loadInvites();
            } catch (err) {
                const msg = err && err.data && err.data.error;
                setStatus(msg === 'code already used' ? 'الرمز مستخدم مسبقاً' : 'تعذّر إنشاء الدعوة', true);
            } finally {
                if (els.inviteSubmit) els.inviteSubmit.disabled = false;
            }
        });
    }

    async function loadAudit() {
        if (!els.audit || !state.cloud || !state.user) {
            if (els.audit) els.audit.hidden = true;
            return;
        }
        try {
            const query = window.AtharMushaf.buildQuery({ params: { edition: state.edition } });
            const data = await window.AtharApi.json(`/api/mushaf-editor/audit${query}`);
            const items = (data.items || []).slice(0, 8);
            els.audit.innerHTML = '';
            if (!items.length) {
                els.audit.hidden = true;
                return;
            }
            els.audit.hidden = false;
            items.forEach(item => {
                const chip = document.createElement('span');
                chip.className = 'ed-audit-item';
                const who = item.actor_name || '—';
                const act = ACTION_AR[item.action] || item.action;
                let where = '';
                if (item.surah && item.ayah != null) where = ` ${item.surah}:${item.ayah}`;
                else if (item.page_number) where = ` ص${item.page_number}`;
                chip.textContent = `${who} · ${act}${where}`;
                els.audit.appendChild(chip);
            });
        } catch (_e) {
            els.audit.hidden = true;
        }
    }
    async function bootstrapAuth() {
        try {
            const data = await window.AtharApi.json('/api/mushaf-editor/auth/status');
            state.cloud = !!data.cloud;
            state.user = data.user || null;
            if (data.login_required) {
                updateSessionUI();
                showLogin();
                return false;
            }
            hideLogin();
            updateSessionUI();
            return true;
        } catch (_e) {
            state.cloud = false;
            state.user = null;
            hideLogin();
            updateSessionUI();
            return true; // local SQLite path
        }
    }
    async function enterEditor() {
        state.ready = true;
        hideLogin();
        updateSessionUI();
        await loadProgress();
        await loadPage();
        loadAudit();
        loadPendingPages();
    }
    if (els.loginForm) {
        els.loginForm.addEventListener('submit', async e => {
            e.preventDefault();
            const code = (els.loginCode && els.loginCode.value || '').trim();
            if (!code) return;
            els.loginSubmit.disabled = true;
            if (els.loginError) els.loginError.hidden = true;
            try {
                const data = await window.AtharApi.json('/api/mushaf-editor/login', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ code }),
                });
                state.user = data.user || null;
                state.cloud = true;
                await enterEditor();
            } catch (err) {
                if (els.loginError) {
                    els.loginError.textContent = (err && err.data && err.data.error === 'invalid code')
                        ? 'رمز غير صالح'
                        : 'تعذّر تسجيل الدخول';
                    els.loginError.hidden = false;
                }
            } finally {
                els.loginSubmit.disabled = false;
            }
        });
    }
    if (els.logoutBtn) {
        els.logoutBtn.addEventListener('click', async () => {
            try {
                await window.AtharApi.json('/api/mushaf-editor/logout', { method: 'POST' });
            } catch (_e) { /* ignore */ }
            state.user = null;
            updateSessionUI();
            if (state.cloud) showLogin();
        });
    }
    if (els.publishBtn) {
        els.publishBtn.addEventListener('click', openPendingPanel);
    }
    function closePendingPanel() {
        if (els.pendingPanel) els.pendingPanel.hidden = true;
        if (els.pendingBackdrop) els.pendingBackdrop.hidden = true;
        document.body.classList.remove('ed-pending-open');
        // Keep pendingChanges/pages so مسودّات nav still works after closing.
        state.pendingIndex = -1;
    }
    function openPendingDrawerShell() {
        if (!els.pendingPanel) return;
        els.pendingPanel.hidden = false;
        if (els.pendingBackdrop) els.pendingBackdrop.hidden = false;
        document.body.classList.add('ed-pending-open');
    }
    function pendingSymParts(sym) {
        const clean = (sym || '').trim();
        if (!clean) {
            return { glyph: '∅', code: 'بلا', title: 'بلا علامة منشورة' };
        }
        const glyph = waqfGlyph(clean);
        const meta = WAQF_SYM[clean];
        return {
            glyph,
            code: clean,
            title: meta ? `${meta.name} (${clean})` : clean,
        };
    }
    function appendPendingSym(row, sym, sideClass, sideLabel) {
        const parts = pendingSymParts(sym);
        const side = document.createElement('div');
        side.className = 'ed-pending-side';
        const label = document.createElement('span');
        label.className = 'ed-pending-side-label';
        label.textContent = sideLabel;
        const glyph = document.createElement('span');
        glyph.className = sideClass;
        glyph.textContent = parts.glyph;
        glyph.title = parts.title;
        const code = document.createElement('span');
        code.className = 'ed-pending-code';
        code.textContent = parts.code;
        side.append(label, glyph, code);
        row.appendChild(side);
    }
    function updatePendingNav() {
        const total = state.pendingChanges.length;
        const idx = state.pendingIndex;
        if (els.pendingNav) els.pendingNav.hidden = total === 0;
        if (els.pendingPos) {
            els.pendingPos.textContent = total
                ? `${toAr(idx + 1)} / ${toAr(total)}`
                : `${toAr(0)} / ${toAr(0)}`;
        }
        if (els.pendingPrev) els.pendingPrev.disabled = idx <= 0;
        if (els.pendingNext) els.pendingNext.disabled = idx < 0 || idx >= total - 1;
        if (els.pendingList) {
            els.pendingList.querySelectorAll('.ed-pending-row').forEach((row, i) => {
                row.classList.toggle('is-active', i === idx);
            });
            const active = els.pendingList.querySelector('.ed-pending-row.is-active');
            if (active) active.scrollIntoView({ block: 'nearest' });
        }
        if (els.pendingConfirm) {
            els.pendingConfirm.disabled = total === 0;
            els.pendingConfirm.textContent = total
                ? `اعتماد ونشر ${toAr(total)} تغيير للقراء`
                : 'اعتماد ونشر للقراء';
        }
    }
    async function jumpToPendingChange(ch, index) {
        if (!ch) return;
        if (typeof index === 'number') state.pendingIndex = index;
        updatePendingNav();
        const page = Number(ch.page_number);
        if (!Number.isFinite(page) || page < 1) {
            setStatus('تعذّر تحديد صفحة هذا الموضع', true);
            return;
        }
        // Keep the drawer open so every pending change stays visible.
        if (state.page !== page) {
            state.page = page;
            persist();
            const ok = await loadPage();
            if (!ok) return;
        }
        const wordId = ch.word_id != null ? String(ch.word_id) : '';
        const target = wordId
            ? els.page.querySelector(`.ed-word[data-word-id="${wordId}"]`)
            : null;
        if (!target) {
            setStatus(`ص ${toAr(page)} — لم يُعثر على الكلمة`, true);
            return;
        }
        els.page.querySelectorAll('.ed-word.ed-pending-focus').forEach(el => {
            el.classList.remove('ed-pending-focus');
        });
        target.classList.add('ed-pending-focus');
        target.scrollIntoView({ block: 'center', inline: 'nearest', behavior: 'smooth' });
        const oldG = ch.old_symbol ? waqfGlyph(ch.old_symbol) : '∅';
        const newG = ch.new_symbol ? waqfGlyph(ch.new_symbol) : '∅';
        setStatus(`${toAr(state.pendingIndex + 1)}/${toAr(state.pendingChanges.length)} · ${ch.surah}:${ch.ayah} · ${oldG} ← ${newG}`);
    }
    function stepPending(delta) {
        const total = state.pendingChanges.length;
        if (!total) return;
        const next = Math.max(0, Math.min(total - 1, state.pendingIndex + delta));
        jumpToPendingChange(state.pendingChanges[next], next);
    }
    function renderPendingList(changes) {
        if (!els.pendingList) return;
        els.pendingList.innerHTML = '';
        state.pendingChanges = Array.isArray(changes) ? changes : [];
        state.pendingIndex = state.pendingChanges.length ? 0 : -1;
        if (!state.pendingChanges.length) {
            const empty = document.createElement('li');
            empty.className = 'ed-pending-empty';
            empty.textContent = 'لا توجد تغييرات معلّقة — المسودّة مطابقة للمنشور.';
            els.pendingList.appendChild(empty);
            if (els.pendingHint) {
                els.pendingHint.textContent = `نسخة «${state.edition}»: لا شيء للنشر.`;
            }
            updatePendingNav();
            return;
        }
        if (els.pendingHint) {
            els.pendingHint.textContent = `نسخة «${state.edition}»: ${toAr(state.pendingChanges.length)} تغيير معلّق. كلّها مدرجة أدناه — راجعها بالسابق/التالي قبل الاعتماد.`;
        }
        state.pendingChanges.forEach((ch, index) => {
            const li = document.createElement('li');
            li.className = 'ed-pending-row';
            li.tabIndex = 0;
            li.setAttribute('role', 'button');
            li.dataset.pendingIndex = String(index);
            const pageHint = ch.page_number ? ` · ص ${toAr(ch.page_number)}` : '';
            li.setAttribute('aria-label', `تغيير ${index + 1}: ${ch.surah}:${ch.ayah}${pageHint}`);
            const coords = document.createElement('div');
            coords.className = 'ed-pending-coords';
            const badge = document.createElement('span');
            badge.className = 'ed-pending-index';
            badge.textContent = toAr(index + 1);
            coords.appendChild(badge);
            coords.appendChild(document.createTextNode(
                `${ch.surah}:${ch.ayah}` + pageHint
                + (ch.word_text ? '' : ` · كلمة ${ch.token_index + 1}`)
            ));
            const word = document.createElement('div');
            word.className = 'ed-pending-word';
            word.textContent = ch.word_text || '—';
            const row = document.createElement('div');
            row.className = 'ed-pending-change';
            appendPendingSym(row, ch.old_symbol, 'ed-pending-old', 'المنشور');
            const arrow = document.createElement('span');
            arrow.className = 'ed-pending-arrow';
            arrow.textContent = '←';
            arrow.setAttribute('aria-hidden', 'true');
            row.appendChild(arrow);
            appendPendingSym(row, ch.new_symbol, 'ed-pending-new', 'المسودّة');
            const jump = document.createElement('div');
            jump.className = 'ed-pending-jump';
            jump.textContent = 'معاينة في الصفحة';
            li.append(coords, word, row, jump);
            li.addEventListener('click', () => { jumpToPendingChange(ch, index); });
            li.addEventListener('keydown', (event) => {
                if (event.key === 'Enter' || event.key === ' ') {
                    event.preventDefault();
                    jumpToPendingChange(ch, index);
                }
            });
            els.pendingList.appendChild(li);
        });
        updatePendingNav();
        // Auto-preview the first change while keeping the full list visible.
        jumpToPendingChange(state.pendingChanges[0], 0);
    }
    async function openPendingPanel() {
        if (!els.pendingPanel) return;
        openPendingDrawerShell();
        if (els.pendingList) els.pendingList.innerHTML = '<li class="ed-pending-empty">جارٍ التحميل…</li>';
        if (els.pendingConfirm) els.pendingConfirm.disabled = true;
        if (els.pendingNav) els.pendingNav.hidden = true;
        try {
            const query = window.AtharMushaf.buildQuery({ params: { edition: state.edition } });
            const data = await window.AtharApi.json(`/api/mushaf-editor/pending${query}`);
            renderPendingList(data.changes || []);
            renderDraftsPages(data.pages || []);
        } catch (_e) {
            if (els.pendingList) {
                els.pendingList.innerHTML = '<li class="ed-pending-empty">تعذّر تحميل التغييرات</li>';
            }
            setStatus('تعذّر تحميل المسودّة', true);
        }
    }
    if (els.pendingClose) els.pendingClose.addEventListener('click', closePendingPanel);
    if (els.pendingDismiss) els.pendingDismiss.addEventListener('click', closePendingPanel);
    if (els.pendingBackdrop) els.pendingBackdrop.addEventListener('click', closePendingPanel);
    if (els.pendingPrev) els.pendingPrev.addEventListener('click', () => stepPending(-1));
    if (els.pendingNext) els.pendingNext.addEventListener('click', () => stepPending(1));
    document.addEventListener('keydown', (event) => {
        if (event.key !== 'Escape') return;
        if (els.pendingPanel && !els.pendingPanel.hidden) {
            closePendingPanel();
            return;
        }
        closeDraftsPanel();
    });
    if (els.pendingConfirm) {
        els.pendingConfirm.addEventListener('click', async () => {
            const total = state.pendingChanges.length;
            if (!total) return;
            const ok = window.confirm(
                `سيتم نشر ${toAr(total)} تغييراً معلّقاً لنسخة «${state.edition}» للقراء.\nهل تريد المتابعة؟`
            );
            if (!ok) return;
            els.pendingConfirm.disabled = true;
            try {
                const data = await window.AtharApi.json('/api/mushaf-editor/publish', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        edition: state.edition,
                        expected_changes: state.pendingChanges.map(ch => ({
                            surah: ch.surah,
                            ayah: ch.ayah,
                            token_index: ch.token_index,
                            old_symbol: ch.old_symbol || '',
                            new_symbol: ch.new_symbol || '',
                        })),
                    }),
                });
                const n = data.pending_before != null ? data.pending_before : (data.published || 0);
                setStatus(`تم اعتماد ${toAr(n)} تغيير`);
                invalidateSpreadCache(state.edition);
                closePendingPanel();
                loadAudit();
                loadPendingPages();
                loadPage();
            } catch (e) {
                if (e && e.status === 403) setStatus('صلاحية المشرف مطلوبة', true);
                else if (e && e.status === 409) {
                    setStatus('تغيّرت المسودّة أثناء المراجعة — راجع القائمة المحدّثة', true);
                    await openPendingPanel();
                }
                else setStatus('تعذّر الاعتماد', true);
                els.pendingConfirm.disabled = false;
            }
        });
    }

    /* ── Resize ──────────────────────────────────────────────────── */
    let _resizeId = 0;
    window.addEventListener('resize', () => {
        clearTimeout(_resizeId);
        _resizeId = setTimeout(fitPages, 120);
    });

    if (els.barToggle) {
        els.barToggle.addEventListener('click', () => {
            applyBarExpanded(!state.barExpanded);
            requestAnimationFrame(fitPages);
        });
    }
    if (els.zoomIn) {
        els.zoomIn.addEventListener('click', () => setPageZoom(state.pageZoom + ZOOM_STEP));
    }
    if (els.zoomOut) {
        els.zoomOut.addEventListener('click', () => setPageZoom(state.pageZoom - ZOOM_STEP));
    }
    if (els.zoomReset) {
        els.zoomReset.addEventListener('click', () => setPageZoom(1));
    }

    document.addEventListener('keydown', e => {
        if (!e.metaKey && !e.ctrlKey) return;
        const tag = (e.target && e.target.tagName) || '';
        if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
        if (e.key === '=' || e.key === '+') {
            e.preventDefault();
            setPageZoom(state.pageZoom + ZOOM_STEP);
        } else if (e.key === '-') {
            e.preventDefault();
            setPageZoom(state.pageZoom - ZOOM_STEP);
        } else if (e.key === '0') {
            e.preventDefault();
            setPageZoom(1);
        }
    });

    /* ── Init ────────────────────────────────────────────────────── */
    buildLegend();
    buildPopupButtons();
    updateEditionUI();
    applyBarExpanded(state.barExpanded);
    updateZoomUI();
    (async () => {
        const ok = await bootstrapAuth();
        if (ok) await enterEditor();
    })();
})();
