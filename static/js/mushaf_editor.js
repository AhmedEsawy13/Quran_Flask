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
     POST /api/mushaf-editor/publish   {edition}  (admin)
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
        prev: $('ed-prev'), next: $('ed-next'),
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
        pendingList: $('ed-pending-list'),
        pendingHint: $('ed-pending-hint'),
        pendingConfirm: $('ed-pending-confirm'),
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
        state.edition = btn.dataset.edition;
        persist();
        updateEditionUI();
        closePopup();
        loadProgress();
        loadPage();
        loadAudit();
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
    }

    const applyFontSize = window.AtharPageChrome.createFontSizer({
        pageEls: () => [els.page].filter(p => p && p.children.length),
        lineSelector: '.ed-line', innerSelector: '.ed-line-inner',
        cssVarName: '--ed-fs', linesPerPage: 15,
        cacheKey: () => state.edition,
    });

    function khattFeatureSettings() {
        const seq = [];
        for (let lvl = 1; lvl <= 5; lvl += 1) for (const t of ['jt', 'dc', 'kt']) seq.push(`${t}0${lvl}`);
        return seq.map(f => `'${f}' 1`).join(', ');
    }

    const justifyLines = window.AtharPageChrome.createLineJustifier({
        containerEls: () => [els.page],
        lineSelector: '.ed-line', innerSelector: '.ed-line-inner', wordSelector: '.ed-word',
        // الكويت / Al Shamiya: progressive jalt+jt/dc/kt (all-at-once overshoots).
        // قطر keeps the compact Madina-style dump as a single candidate.
        featureSettings: () => (state.edition === 'الكويت' ? '' : khattFeatureSettings()),
        featureCandidates: () => (
            state.edition === 'الكويت'
                ? window.AtharPageChrome.alShamiyaFeatureCandidates(100)
                : null
        ),
        minFeatureScale: () => (state.edition === 'الكويت' ? 0.94 : 1),
        // Cap residual gaps so leftover slack prefers kashida over rivers,
        // but leave a little room — printed Naskh is not pure stretch either.
        maxWordSpacing: () => (state.edition === 'الكويت' ? 1.75 : Infinity),
        preferExpansion: () => state.edition === 'الكويت',
        preferExpansionSlack: 3,
    });

    function fitPages() {
        sizePages();
        applyFontSize();
        requestAnimationFrame(justifyLines);
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
    async function loadPage() {
        const request = spreadRequests.next();
        const page = state.page;
        const spread = pageToSpread(page);
        const edition = state.edition;
        const wantRight = page % 2 === 1;
        window.AtharUi.setBusy(els.main, true);
        try {
            const query = window.AtharMushaf.buildQuery({ params: { edition } });
            const data = await window.AtharApi.json(`/api/mushaf-editor/spread/${spread}${query}`);
            if (!spreadRequests.isCurrent(request)) return false;
            const payload = wantRight ? data.right : data.left;
            renderPage(payload || null);
            els.pageLabel.textContent = `${toAr(page)} / ${toAr(MAX_PAGE)}`;
            state.currentPages = payload ? [payload.page_number] : [];
            updateReviewedCheckbox();
            updateNavButtons();
            fitPages();
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
    }

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
            setStatus('تم حفظ علامة الوقف');
            loadAudit();
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
    }
    function renderPendingList(changes) {
        if (!els.pendingList) return;
        els.pendingList.innerHTML = '';
        if (!changes.length) {
            const empty = document.createElement('li');
            empty.className = 'ed-pending-empty';
            empty.textContent = 'لا توجد تغييرات معلّقة — المسودّة مطابقة للمنشور.';
            els.pendingList.appendChild(empty);
            if (els.pendingConfirm) els.pendingConfirm.disabled = true;
            if (els.pendingHint) {
                els.pendingHint.textContent = `نسخة «${state.edition}»: لا شيء للنشر.`;
            }
            return;
        }
        if (els.pendingHint) {
            els.pendingHint.textContent = `نسخة «${state.edition}»: ${toAr(changes.length)} تغيير معلّق قبل النشر للقراء.`;
        }
        if (els.pendingConfirm) els.pendingConfirm.disabled = false;
        changes.forEach(ch => {
            const li = document.createElement('li');
            li.className = 'ed-pending-row';
            const coords = document.createElement('div');
            coords.className = 'ed-pending-coords';
            coords.textContent = `${ch.surah}:${ch.ayah}` + (ch.word_text ? '' : ` · كلمة ${ch.token_index + 1}`);
            const word = document.createElement('div');
            word.className = 'ed-pending-word';
            word.textContent = ch.word_text || '—';
            const row = document.createElement('div');
            row.className = 'ed-pending-change';
            const oldEl = document.createElement('span');
            oldEl.className = 'ed-pending-old';
            oldEl.textContent = ch.old_symbol ? waqfGlyph(ch.old_symbol) : '∅';
            oldEl.title = ch.old_symbol || 'بلا علامة منشورة';
            const arrow = document.createElement('span');
            arrow.textContent = '←';
            const newEl = document.createElement('span');
            newEl.className = 'ed-pending-new';
            newEl.textContent = ch.new_symbol ? waqfGlyph(ch.new_symbol) : '∅';
            newEl.title = ch.new_symbol || 'مسح العلامة';
            row.append(oldEl, arrow, newEl);
            li.append(coords, word, row);
            els.pendingList.appendChild(li);
        });
    }
    async function openPendingPanel() {
        if (!els.pendingPanel) return;
        els.pendingPanel.hidden = false;
        if (els.pendingBackdrop) els.pendingBackdrop.hidden = false;
        if (els.pendingList) els.pendingList.innerHTML = '<li class="ed-pending-empty">جارٍ التحميل…</li>';
        if (els.pendingConfirm) els.pendingConfirm.disabled = true;
        try {
            const query = window.AtharMushaf.buildQuery({ params: { edition: state.edition } });
            const data = await window.AtharApi.json(`/api/mushaf-editor/pending${query}`);
            renderPendingList(data.changes || []);
        } catch (_e) {
            if (els.pendingList) {
                els.pendingList.innerHTML = '<li class="ed-pending-empty">تعذّر تحميل التغييرات</li>';
            }
            setStatus('تعذّر تحميل المسودّة', true);
        }
    }
    if (els.pendingClose) els.pendingClose.addEventListener('click', closePendingPanel);
    if (els.pendingBackdrop) els.pendingBackdrop.addEventListener('click', closePendingPanel);
    if (els.pendingConfirm) {
        els.pendingConfirm.addEventListener('click', async () => {
            els.pendingConfirm.disabled = true;
            try {
                const data = await window.AtharApi.json('/api/mushaf-editor/publish', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ edition: state.edition }),
                });
                setStatus(`تم اعتماد ${toAr(data.published || 0)} علامة`);
                closePendingPanel();
                loadAudit();
            } catch (e) {
                if (e && e.status === 403) setStatus('صلاحية المشرف مطلوبة', true);
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

    /* ── Init ────────────────────────────────────────────────────── */
    buildLegend();
    buildPopupButtons();
    updateEditionUI();
    (async () => {
        const ok = await bootstrapAuth();
        if (ok) await enterEditor();
    })();
})();
