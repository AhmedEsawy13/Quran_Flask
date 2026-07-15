/* ═══════════════════════════════════════════════════════════════════
   Mushaf Editor — مصحف قطر / مصحف الكويت الحديث
   Two-page spread of the Madinah v1 (1405) layout. Click a word to set
   its waqf mark for the selected edition; words whose mark differs from
   وقوف المدينة (the seeded baseline) are highlighted.

   Endpoints:
     GET  /api/mushaf-editor/spread/<n>?edition=قطر|الكويت
     POST /api/mushaf-editor/waqf      {word_id, edition, symbol}
     GET  /api/mushaf-editor/progress?edition=...
     POST /api/mushaf-editor/progress  {edition, page_number, reviewed}
   ═══════════════════════════════════════════════════════════════════ */
(function () {
    'use strict';
    const $ = id => document.getElementById(id);
    const toAr = n => String(n).replace(/[0-9]/g, d => '٠١٢٣٤٥٦٧٨٩'[d]);
    const { normalizeNonWarshWaqfText, stripEmbeddedWaqf } = window.AtharMushaf;

    const MAX_SPREAD = 302;
    const MAX_PAGE = 604;

    // Reference material (Phase 4) — links open the actual printed edition's
    // page in a new tab so the user can compare it against the Madinah v1
    // layout shown here while adjusting waqf marks.
    //   الكويت: archive.org scan of "كويت" — confirmed PDF page 5 = Madinah
    //   page 1 (سورة الفاتحة), so PDF page = Madinah page + 4.
    const KUWAIT_PDF_ID = 'kweat--h4794794946945969';
    const KUWAIT_PAGE_OFFSET = 4;

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

    const els = {
        pageR: $('ed-page-r'), pageL: $('ed-page-l'),
        pageRNum: $('ed-page-r-num'), pageLNum: $('ed-page-l-num'),
        refR: $('ed-ref-r'), refL: $('ed-ref-l'),
        spreadLabel: $('ed-spread-label'),
        progress: $('ed-progress'),
        reviewed: $('ed-reviewed'),
        jumpInput: $('ed-jump-page'), jumpBtn: $('ed-jump-go'),
        prev: $('ed-prev'), next: $('ed-next'),
        editionBtns: Array.from(document.querySelectorAll('.ed-edition-btn')),
        status: $('ed-status'),
        legend: $('ed-legend'),
        theme: $('ed-theme'),
        popup: $('ed-popup'), popupBackdrop: $('ed-popup-backdrop'),
        popupTitle: $('ed-popup-title'), popupBaseline: $('ed-popup-baseline'),
        popupSyms: $('ed-popup-syms'), popupClear: $('ed-popup-clear'), popupClose: $('ed-popup-close'),
    };

    const state = {
        edition: localStorage.getItem('ed_edition') || 'قطر',
        spread: clampSpread(parseInt(localStorage.getItem('ed_spread') || '1', 10)),
        reviewedPages: new Set(),
        activeWord: null,
        currentPages: [],
    };
    const spreadRequests = window.AtharMushaf.createRequestGate();
    const progressRequests = window.AtharMushaf.createRequestGate();

    function clampSpread(n) {
        if (!Number.isFinite(n)) return 1;
        return Math.min(MAX_SPREAD, Math.max(1, n));
    }

    function persist() {
        localStorage.setItem('ed_edition', state.edition);
        localStorage.setItem('ed_spread', String(state.spread));
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
    }

    /* ── Edition toggle ──────────────────────────────────────────── */
    function updateEditionUI() {
        els.editionBtns.forEach(b => b.classList.toggle('ed-active', b.dataset.edition === state.edition));
        // مصحف قطر's layout (mushaf-qatar-layout.db) declares font_name "qpc-hafs".
        document.body.classList.toggle('ed-font-hafs', state.edition === 'قطر');
    }
    els.editionBtns.forEach(btn => btn.addEventListener('click', () => {
        if (btn.dataset.edition === state.edition) return;
        state.edition = btn.dataset.edition;
        persist();
        updateEditionUI();
        updateRefButtons();
        closePopup();
        loadProgress();
        loadSpread();
    }));

    /* ── Reference material (Phase 4) ───────────────────────────────
       "فتح المرجع" opens the corresponding page of the actual printed
       edition in a new tab, for visual comparison against this page. */
    function refTitle(edition) {
        return edition === 'الكويت'
            ? 'فتح صفحة المصحف (الكويت الحديث) في أرشيف PDF'
            : 'فتح الآية في تطبيق الباحث القرآني (مصحف قطر)';
    }
    function updateRefButtons() {
        [els.refR, els.refL].forEach(btn => {
            if (btn.hidden) return;
            btn.title = refTitle(state.edition);
            btn.setAttribute('aria-label', refTitle(state.edition));
        });
    }
    function openReference(btn) {
        if (btn.hidden) return;
        const page = parseInt(btn.dataset.page, 10);
        if (!Number.isFinite(page)) return;
        let url;
        if (state.edition === 'الكويت') {
            url = `https://archive.org/details/${KUWAIT_PDF_ID}/page/${page + KUWAIT_PAGE_OFFSET}`;
        } else {
            const surah = btn.dataset.surah, ayah = btn.dataset.ayah;
            if (!surah || !ayah) return;
            url = `https://tafsir.app/m-qatar/${surah}/${ayah}`;
        }
        window.open(url, '_blank', 'noopener');
    }
    els.refR.addEventListener('click', () => openReference(els.refR));
    els.refL.addEventListener('click', () => openReference(els.refL));

    /* ── Page rendering ──────────────────────────────────────────── */
    function renderPage(container, numEl, refBtn, payload) {
        container.innerHTML = '';
        if (!payload) {
            numEl.textContent = '';
            refBtn.hidden = true;
            delete refBtn.dataset.page;
            delete refBtn.dataset.surah;
            delete refBtn.dataset.ayah;
            return;
        }
        numEl.textContent = `صفحة ${toAr(payload.page_number)}`;
        refBtn.dataset.page = payload.page_number;
        if (payload.anchor_surah_number && payload.anchor_ayah_number) {
            refBtn.dataset.surah = payload.anchor_surah_number;
            refBtn.dataset.ayah = payload.anchor_ayah_number;
        } else {
            delete refBtn.dataset.surah;
            delete refBtn.dataset.ayah;
        }
        refBtn.hidden = false;
        refBtn.title = refTitle(state.edition);
        refBtn.setAttribute('aria-label', refTitle(state.edition));
        const frag = document.createDocumentFragment();
        (payload.lines || []).forEach(line => {
            const lineEl = document.createElement('div');
            const words = line.words || [];
            if (line.line_type === 'surah_name' || line.line_type === 'basmallah') {
                lineEl.className = 'ed-line ed-line-special';
                lineEl.textContent = line.display_text || '';
            } else {
                lineEl.className = 'ed-line';
                // Non-centered lines are full-justified edge-to-edge by justifyLines();
                // centered lines (surah-end, etc.) keep their natural width.
                lineEl.dataset.justify = line.is_centered ? '0' : '1';
                const inner = document.createElement('div');
                inner.className = 'ed-line-inner';
                words.forEach((w, i) => {
                    inner.appendChild(buildWordEl(w));
                    if (i < words.length - 1) inner.appendChild(document.createTextNode(' '));
                });
                lineEl.appendChild(inner);
            }
            frag.appendChild(lineEl);
        });
        container.appendChild(frag);
    }

    /* ── Page sizing & line-fit (ported from mushaf_memorize.js) ──────
       sizePages: fit both pages into the available centre space at the real
       mushaf ratio (width/height ≈ 0.66). applyFontSize: pick a per-page font
       size so a typical line nearly fills the line width. justifyLines: make
       every non-centered line span edge-to-edge — condense via scaleX if it's
       still too wide, otherwise elongate with Old Madina's kashida features
       and fill the remainder with word-spacing. Together these keep every
       word inside the page border regardless of how many words a line has. */
    const PAGE_RATIO = 0.66; // width / height
    function sizePages() {
        const main = document.querySelector('.ed-main');
        if (!main) return;
        const headPad = 24;   // .ed-page-header height + margin
        const gutter = 20;    // gap between right/left page cards
        const availH = Math.max(230, main.clientHeight - 36 - headPad);
        const availW = Math.max(300, main.clientWidth - 20 - gutter);
        let h = availH;
        let w = h * PAGE_RATIO;
        if (w * 2 > availW) {
            const s = availW / (w * 2);
            w *= s; h *= s;
        }
        w = Math.max(150, Math.floor(w));
        h = Math.max(230, Math.floor(h));
        document.documentElement.style.setProperty('--ed-page-w', w + 'px');
        document.documentElement.style.setProperty('--ed-page-h', h + 'px');
    }

    function applyFontSize() {
        [els.pageR, els.pageL].forEach(p => {
            if (!p || !p.children.length) return;
            const h = p.clientHeight || 1;
            const lineH = h / 15;
            const maxFs = lineH * 0.92;          // never taller than the line slot
            let fs = Math.max(11, lineH * 0.62); // line-height baseline
            p.style.setProperty('--ed-fs', fs + 'px');

            // Measure justified lines at this size, then scale so the median line
            // ~fills the width (98%). Proportional scaling keeps the ratio valid.
            const inners = [...p.querySelectorAll('.ed-line[data-justify="1"] .ed-line-inner')];
            const ratios = [];
            inners.forEach(inner => {
                inner.style.transform = 'none';
                inner.style.fontFeatureSettings = '';
                inner.style.wordSpacing = '';
                const avail = inner.parentElement.clientWidth;
                const nat = inner.scrollWidth;
                if (nat > 0 && avail > 0) ratios.push(avail / nat);
            });
            if (ratios.length) {
                ratios.sort((a, b) => a - b);
                const med = ratios[Math.floor(ratios.length / 2)] || 1;
                fs = Math.max(11, Math.min(maxFs, fs * med * 0.98));
                p.style.setProperty('--ed-fs', fs + 'px');
            }
        });
    }

    // Old Madina kashida/justification OpenType features, strongest setting.
    function khattFeatureSettings() {
        const seq = [];
        for (let lvl = 1; lvl <= 5; lvl += 1) for (const t of ['jt', 'dc', 'kt']) seq.push(`${t}0${lvl}`);
        return seq.map(f => `'${f}'`).join(',');
    }

    function justifyLines() {
        const features = khattFeatureSettings();
        [els.pageR, els.pageL].forEach(p => {
            if (!p) return;
            p.querySelectorAll('.ed-line').forEach(lineEl => {
                const inner = lineEl.querySelector('.ed-line-inner');
                if (!inner) return;
                inner.style.transform = 'none';
                inner.style.fontFeatureSettings = '';
                inner.style.wordSpacing = '';
                const avail = lineEl.clientWidth;
                if (!avail || lineEl.dataset.justify !== '1') return;
                const natural = inner.scrollWidth;
                if (!natural) return;

                if (natural > avail + 0.5) {              // too long → condense to fit
                    inner.style.transform = `scaleX(${Math.max(0.5, avail / natural)})`;
                    return;
                }
                // Kashida-elongate (if it doesn't overshoot), then word-space the rest.
                let width = natural;
                inner.style.fontFeatureSettings = features;
                const withK = inner.scrollWidth;
                if (withK <= avail + 0.5) width = withK;
                else inner.style.fontFeatureSettings = '';

                const gaps = inner.querySelectorAll('.ed-word').length - 1;
                const slack = avail - width;
                if (slack > 0.5 && gaps > 0) inner.style.wordSpacing = (slack / gaps) + 'px';
                else if (slack > 0.5) inner.style.transform = `scaleX(${avail / width})`; // single word
            });
        });
    }

    function fitPages() {
        sizePages();
        applyFontSize();
        requestAnimationFrame(justifyLines);
    }

    function buildWordEl(w) {
        const span = document.createElement('span');
        span.className = 'ed-word';
        span.dataset.wordId = String(w.word_index);
        const cleanText = stripEmbeddedWaqf(w.text || '');
        span.dataset.text = cleanText;
        span.textContent = cleanText;

        const entries = Array.isArray(w.waqf_symbols) ? w.waqf_symbols : [];
        const editionEntry = entries.find(e => e.version === state.edition);
        const baselineEntry = entries.find(e => e.version === 'المدينة الجديد');
        const editionSym = (editionEntry && editionEntry.symbols) || '';
        const baselineSym = (baselineEntry && baselineEntry.symbols) || '';

        span.dataset.symbol = editionSym;
        span.dataset.baseline = baselineSym;
        applyWordMark(span, editionSym, baselineSym);
        return span;
    }

    function applyWordMark(span, editionSym, baselineSym) {
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
        const baseline = baselineSym !== undefined ? baselineSym : span.dataset.baseline;
        span.classList.toggle('ed-diff', (editionSym || '') !== (baseline || ''));
        span.title = baseline
            ? `المدينة: ${waqfGlyph(baseline)} (${baseline})`
            : 'المدينة: بلا علامة';
    }

    /* ── Loading a spread ────────────────────────────────────────── */
    async function loadSpread() {
        const request = spreadRequests.next();
        const spread = state.spread;
        const edition = state.edition;
        try {
            const query = window.AtharMushaf.buildQuery({ params: { edition } });
            const data = await window.AtharApi.json(`/api/mushaf-editor/spread/${spread}${query}`);
            if (!spreadRequests.isCurrent(request)) return false;
            renderPage(els.pageR, els.pageRNum, els.refR, data.right);
            renderPage(els.pageL, els.pageLNum, els.refL, data.left);
            els.spreadLabel.textContent = `${toAr(spread)} / ${toAr(MAX_SPREAD)}`;
            state.currentPages = [data.right, data.left].filter(Boolean).map(p => p.page_number);
            updateReviewedCheckbox();
            updateNavButtons();
            fitPages();
            return true;
        } catch (e) {
            if (spreadRequests.isCurrent(request)) setStatus('تعذّر تحميل الصفحة', true);
            return false;
        }
    }

    function updateNavButtons() {
        els.prev.disabled = state.spread <= 1;
        els.next.disabled = state.spread >= MAX_SPREAD;
    }

    /* ── Progress tracking ───────────────────────────────────────── */
    async function loadProgress() {
        const request = progressRequests.next();
        const edition = state.edition;
        try {
            const query = window.AtharMushaf.buildQuery({ params: { edition } });
            const data = await window.AtharApi.json(`/api/mushaf-editor/progress${query}`);
            if (!progressRequests.isCurrent(request)) return;
            state.reviewedPages = new Set(data.reviewed_pages || []);
        } catch (e) {
            if (!progressRequests.isCurrent(request)) return;
            state.reviewedPages = new Set();
        }
        updateProgressLabel();
        updateReviewedCheckbox();
    }
    function updateProgressLabel() {
        els.progress.textContent = `${toAr(state.reviewedPages.size)} / ${toAr(MAX_PAGE)} مراجَعة`;
    }
    function updateReviewedCheckbox() {
        els.reviewed.checked = state.currentPages.length > 0
            && state.currentPages.every(p => state.reviewedPages.has(p));
    }
    els.reviewed.addEventListener('change', async () => {
        const reviewed = els.reviewed.checked;
        for (const page of state.currentPages) {
            try {
                await window.AtharApi.json('/api/mushaf-editor/progress', {
                    method: 'POST', headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ edition: state.edition, page_number: page, reviewed }),
                });
                if (reviewed) state.reviewedPages.add(page); else state.reviewedPages.delete(page);
            } catch (e) { /* ignore */ }
        }
        updateProgressLabel();
    });

    /* ── Navigation ──────────────────────────────────────────────── */
    els.prev.addEventListener('click', () => {
        if (state.spread <= 1) return;
        state.spread--;
        persist(); closePopup(); loadSpread();
    });
    els.next.addEventListener('click', () => {
        if (state.spread >= MAX_SPREAD) return;
        state.spread++;
        persist(); closePopup(); loadSpread();
    });
    els.jumpBtn.addEventListener('click', jumpToPage);
    els.jumpInput.addEventListener('keydown', e => { if (e.key === 'Enter') jumpToPage(); });
    function jumpToPage() {
        const p = parseInt(els.jumpInput.value, 10);
        if (!Number.isFinite(p) || p < 1 || p > MAX_PAGE) {
            setStatus('رقم صفحة غير صالح (١ - ٦٠٤)', true);
            return;
        }
        state.spread = clampSpread(Math.ceil(p / 2));
        els.jumpInput.value = '';
        persist(); closePopup(); loadSpread();
    }
    document.addEventListener('keydown', e => {
        if (e.target.tagName === 'INPUT' || !els.popup.hidden) return;
        if (e.key === 'ArrowLeft') els.next.click();
        if (e.key === 'ArrowRight') els.prev.click();
    });

    /* ── Word edit popup ─────────────────────────────────────────── */
    function buildPopupButtons() {
        els.popupSyms.innerHTML = '';
        Object.entries(WAQF_SYM).forEach(([sym, meta]) => {
            const b = document.createElement('button');
            b.type = 'button'; b.className = 'ed-sym-btn'; b.dataset.sym = sym;
            b.innerHTML = `<span class="ed-sym-glyph">${waqfGlyph(sym)}</span><span class="ed-sym-name">${meta.name}</span>`;
            b.addEventListener('click', () => setSymbol(sym));
            els.popupSyms.appendChild(b);
        });
    }
    els.popupClear.addEventListener('click', () => setSymbol(''));
    els.popupClose.addEventListener('click', closePopup);
    els.popupBackdrop.addEventListener('click', closePopup);

    function openPopup(wordEl) {
        if (state.activeWord) state.activeWord.classList.remove('ed-selected');
        state.activeWord = wordEl;
        wordEl.classList.add('ed-selected');

        els.popupTitle.textContent = wordEl.dataset.text || wordEl.textContent;
        const baseline = wordEl.dataset.baseline || '';
        els.popupBaseline.innerHTML = baseline
            ? `وقف المدينة هنا: <span class="ed-baseline-glyph">${waqfGlyph(baseline)}</span> (${baseline})`
            : 'لا توجد علامة وقف في المدينة عند هذه الكلمة';

        const current = wordEl.dataset.symbol || '';
        els.popupSyms.querySelectorAll('.ed-sym-btn').forEach(b => {
            b.classList.toggle('ed-active', b.dataset.sym === current);
        });

        els.popup.hidden = false;
        els.popupBackdrop.hidden = false;
    }
    function closePopup() {
        if (state.activeWord) state.activeWord.classList.remove('ed-selected');
        state.activeWord = null;
        els.popup.hidden = true;
        els.popupBackdrop.hidden = true;
    }

    async function setSymbol(sym) {
        const wordEl = state.activeWord;
        if (!wordEl) return;
        const wordId = wordEl.dataset.wordId;
        try {
            const data = await window.AtharApi.json('/api/mushaf-editor/waqf', {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ word_id: wordId, edition: state.edition, symbol: sym }),
            });
            applyWordMark(wordEl, data.symbol || '');
            requestAnimationFrame(justifyLines); // mark glyph can shift the line's width
        } catch (e) {
            setStatus('تعذّر حفظ التعديل', true);
        }
        closePopup();
    }

    document.addEventListener('click', e => {
        const w = e.target.closest('.ed-word');
        if (w) { openPopup(w); return; }
    });

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
    loadProgress();
    loadSpread();
})();
