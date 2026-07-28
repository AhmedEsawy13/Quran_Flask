/* ═══════════════════════════════════════════════════════════════════
   Layout Studio — reshape mushaf pages (edition from AtharLayoutStudio).
   Default edition: azhar (Shemrly seed, Amiri). Drag a word onto a line
   to move the break; Cancel (X) aborts.
   Config (injected by layout_studio.html):
     window.AtharLayoutStudio = { id, apiBase, minPage, maxPage, ref, … }
   Endpoints (per edition):
     GET  {apiBase}/page/<n>
     GET/POST {apiBase}/profile
     POST {apiBase}/line-break|pull-next-word|push-last-word|merge-line|line-center
          |header-move|undo
     GET  {apiBase}/undo-status?page_number=
     GET/POST {apiBase}/progress
   ═══════════════════════════════════════════════════════════════════ */
(function () {
    'use strict';
    const $ = id => document.getElementById(id);
    const { stripEmbeddedWaqf } = window.AtharMushaf;
    const { toAr, clearPageChrome, renderPageChrome } = window.AtharPageChrome;

    const CFG = window.AtharLayoutStudio || {};
    const MIN_PAGE = Number(CFG.minPage) || 2;
    const MAX_PAGE = Number(CFG.maxPage) || 522;
    const API_BASE = CFG.apiBase || '/api/layout-studio/azhar';
    const PROFILE_API = `${API_BASE}/profile`;
    const PAGE_BY_AYAH_BASE = CFG.pageByAyahBase || '/api/azhar/page-by-ayah';
    const STORAGE_KEY = CFG.storageKey || 'layout_studio_page';
    const DRAG_THRESHOLD = 6;
    document.documentElement.style.setProperty(
        '--az-quran-font',
        `"${CFG.fontName || 'AmiriQuran'}"`
    );

    const REF_SOURCE = CFG.ref
        ? {
            type: CFG.ref.type || 'archive',
            id: CFG.ref.id || '',
            label: CFG.ref.label || 'مرجع',
            leafOffset: Number(CFG.ref.leafOffset) || 0,
            imageTemplate: CFG.ref.imageTemplate || '',
            openTemplate: CFG.ref.openTemplate || '',
            pdfUrl: CFG.ref.pdfUrl || '',
            pdfPageOffset: Number(CFG.ref.pdfPageOffset) || 0,
        }
        : { type: 'archive', id: 'shamarlyshamarly', label: 'مرجع الشمرلي', leafOffset: -1 };
    const REF_IMG_WIDTH = 1024;
    const REF_DEBOUNCE_MS = 120;

    const els = {
        main: $('athar-main'),
        page: $('az-page'),
        pageNum: $('az-page-num'),
        juz: $('az-juz'),
        surah: $('az-surah'),
        pageLabel: $('az-page-label'),
        progress: $('az-progress'),
        reviewed: $('az-reviewed'),
        jumpInput: $('az-jump-page'),
        jumpBtn: $('az-jump-go'),
        jumpSurah: $('az-jump-surah'),
        jumpAyah: $('az-jump-ayah'),
        jumpAyahBtn: $('az-jump-ayah-go'),
        cancelBar: $('az-cancel-bar'),
        cancel: $('az-cancel'),
        prev: $('az-prev'),
        next: $('az-next'),
        undo: $('az-undo'),
        status: $('az-status'),
        editionMeta: $('az-edition-meta'),
        profilePanel: $('az-profile-panel'),
        profileForm: $('az-profile-form'),
        profilePreset: $('az-profile-preset'),
        profilePresetNote: $('az-profile-preset-note'),
        profileLines: $('az-profile-lines'),
        profileSurahName: $('az-profile-surah-name'),
        profileSurahInfo: $('az-profile-surah-info'),
        profileBasmallah: $('az-profile-basmallah'),
        profileBudget: $('az-profile-budget'),
        profileSave: $('az-profile-save'),
        refTitle: $('az-ref-title'),
        refOpen: $('az-ref-open'),
        refImg: $('az-ref-img'),
        refFrame: $('az-ref-frame'),
        refLoading: $('az-ref-loading'),
        refFallback: $('az-ref-fallback'),
        refFallbackBtn: $('az-ref-fallback-btn'),
    };

    const state = {
        page: clampPage(parseInt(localStorage.getItem(STORAGE_KEY) || String(MIN_PAGE), 10)),
        reviewedPages: new Set(),
        busy: false,
        drag: null,
        refUrl: '',
        undoAvailable: 0,
        pageSlotBudget: Number(CFG.linesPerPage) || 15,
    };
    const pageRequests = window.AtharMushaf.createRequestGate();
    const progressRequests = window.AtharMushaf.createRequestGate();
    const refPrefetch = new Set();
    let refLoadToken = 0;
    let refTimer = 0;

    function clampPage(n) {
        if (!Number.isFinite(n)) return MIN_PAGE;
        return Math.min(MAX_PAGE, Math.max(MIN_PAGE, n));
    }
    function persist() {
        localStorage.setItem(STORAGE_KEY, String(state.page));
    }

    const status = window.AtharUi.createStatus(els.status, {
        visibleClass: 'az-show', errorClass: 'az-err', defaultDuration: 2200,
    });
    function setStatus(msg, isErr) {
        status.show(msg, { error: !!isErr });
    }

    /* ── Universal layout profile ────────────────────────────────── */

    function cleanProfile(value) {
        const raw = value || {};
        return {
            lines_per_page: Number(raw.lines_per_page) || 15,
            page_end_mode: raw.page_end_mode === 'ayah' ? 'ayah' : 'continuous',
            surah_name_lines: Math.max(1, Number(raw.surah_name_lines) || 1),
            surah_info_lines: Math.max(0, Number(raw.surah_info_lines) || 0),
            basmallah_lines: Math.max(0, Number(raw.basmallah_lines) || 0),
        };
    }

    function selectedPageEndMode() {
        const checked = document.querySelector(
            'input[name="az-page-end-mode"]:checked'
        );
        return checked ? checked.value : 'continuous';
    }

    function readProfileForm() {
        return cleanProfile({
            lines_per_page: els.profileLines && els.profileLines.value,
            page_end_mode: selectedPageEndMode(),
            surah_name_lines: els.profileSurahName && els.profileSurahName.value,
            surah_info_lines: els.profileSurahInfo && els.profileSurahInfo.value,
            basmallah_lines: els.profileBasmallah && els.profileBasmallah.value,
        });
    }

    function updateProfileBudget() {
        if (!els.profileBudget || !els.profileForm) return true;
        const profile = readProfileForm();
        const header = profile.surah_name_lines
            + profile.surah_info_lines
            + profile.basmallah_lines;
        const ayahLines = profile.lines_per_page - header;
        const valid = ayahLines >= 1;
        els.profileBudget.textContent = valid
            ? `راية السورة الكاملة: ${toAr(header)} · المتبقي للآيات: ${toAr(ayahLines)}`
            : 'راية السورة لا تترك سطراً للآيات';
        els.profileBudget.classList.toggle('az-invalid', !valid);
        if (els.profileSave) els.profileSave.disabled = !valid;
        return valid;
    }

    function fillProfileForm(profileValue) {
        if (!els.profileForm) return;
        const profile = cleanProfile(profileValue);
        els.profileLines.value = String(profile.lines_per_page);
        els.profileSurahName.value = String(profile.surah_name_lines);
        els.profileSurahInfo.value = String(profile.surah_info_lines);
        els.profileBasmallah.value = String(profile.basmallah_lines);
        document.querySelectorAll('input[name="az-page-end-mode"]').forEach(input => {
            input.checked = input.value === profile.page_end_mode;
        });
        updateProfileBudget();
    }

    function initProfileForm() {
        if (!els.profileForm) return;
        const presets = Array.isArray(CFG.profilePresets) ? CFG.profilePresets : [];
        const describePreset = preset => {
            if (!els.profilePresetNote) return;
            const shortPages = Object.entries(preset && preset.short_pages || {})
                .map(([page, lines]) => `${toAr(page)} ← ${toAr(lines)}`)
                .join('، ');
            els.profilePresetNote.textContent = [
                preset && preset.description_ar || '',
                shortPages ? `الصفحات القصيرة: ${shortPages}` : '',
            ].filter(Boolean).join(' · ');
        };
        const sameProfile = (leftValue, rightValue) => {
            const left = cleanProfile(leftValue);
            const right = cleanProfile(rightValue);
            return [
                'lines_per_page', 'page_end_mode', 'surah_name_lines',
                'surah_info_lines', 'basmallah_lines',
            ].every(key => left[key] === right[key]);
        };
        if (els.profilePreset) {
            presets.forEach(preset => {
                const option = document.createElement('option');
                option.value = preset.id || '';
                option.textContent = preset.name_ar || preset.id || '';
                els.profilePreset.appendChild(option);
            });
            els.profilePreset.addEventListener('change', () => {
                const preset = presets.find(item => item.id === els.profilePreset.value);
                if (!preset) {
                    if (els.profilePresetNote) els.profilePresetNote.textContent = '';
                    return;
                }
                fillProfileForm(preset.profile);
                describePreset(preset);
            });
        }
        const current = CFG.profile || { lines_per_page: CFG.linesPerPage };
        fillProfileForm(current);
        const matching = presets.find(preset => sameProfile(preset.profile, current));
        if (matching && els.profilePreset) {
            els.profilePreset.value = matching.id;
            describePreset(matching);
        }
        els.profileForm.querySelectorAll('input').forEach(input => {
            input.addEventListener('input', updateProfileBudget);
            input.addEventListener('change', updateProfileBudget);
        });
        els.profileForm.addEventListener('submit', saveProfile);
    }

    async function saveProfile(event) {
        event.preventDefault();
        if (state.busy || !updateProfileBudget()) return;
        const profile = readProfileForm();
        state.busy = true;
        if (els.profileSave) els.profileSave.disabled = true;
        try {
            const data = await window.AtharApi.json(PROFILE_API, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ profile }),
            });
            CFG.profile = data.profile || profile;
            CFG.linesPerPage = Number(CFG.profile.lines_per_page) || 15;
            state.pageSlotBudget = CFG.linesPerPage;
            if (els.editionMeta && data.meta_label) {
                els.editionMeta.textContent = data.meta_label;
            }
            if (els.profilePanel) els.profilePanel.open = false;
            setStatus('تم حفظ قواعد التخطيط');
            await loadPage();
        } catch (e) {
            const msg = (e && e.message) || (e && e.error) || '';
            setStatus(msg || 'تعذّر حفظ قواعد التخطيط', true);
        } finally {
            state.busy = false;
            if (els.profileSave) els.profileSave.disabled = false;
            updateProfileBudget();
        }
    }

    /* Same fit pipeline as mushaf_editor / memorize:
       sizePages → createFontSizer (per-page line count; short pages 6/5)
       → createLineJustifier.
       Short pages (الفاتحة / أول البقرة) size to their real line count.
       Side-by-side scan + digital share one dual-page budget. */
    const PAGE_RATIO = 0.66;
    function sizePages() {
        const main = document.querySelector('.az-main');
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
            + outerHeight(document.querySelector('.az-bar'))
            + outerHeight(document.querySelector('.az-hint'))
            + outerHeight(document.querySelector('.az-page-header'))
            + mainPad;
        const stacked = window.matchMedia('(max-width: 900px)').matches;
        window.AtharPageChrome.sizePages({
            cssVarPrefix: 'az', pages: stacked ? 1 : 2, ratio: PAGE_RATIO,
            gutter: stacked ? 0 : 18, floor: true,
            getAvailH: () => stacked
                ? Math.max(280, availableWidth / PAGE_RATIO)
                : Math.max(280, window.innerHeight - fixedChrome),
            getAvailW: () => availableWidth,
        });
    }

    const applyFontSize = window.AtharPageChrome.createFontSizer({
        pageEls: () => [els.page].filter(p => p && p.children.length),
        lineSelector: '.az-line', innerSelector: '.az-line-inner',
        cssVarName: '--az-fs',
        // Backend profile supplies the physical slot budget (short pages included).
        linesPerPage: () => state.pageSlotBudget || Number(CFG.linesPerPage) || 15,
        minLineScale: 0.95,
        cacheKey: () => `${CFG.id || 'layout'}-${state.page}-${state.pageSlotBudget}`,
    });

    const justifyLines = window.AtharPageChrome.createLineJustifier({
        containerEls: () => [els.page],
        lineSelector: '.az-line', innerSelector: '.az-line-inner', wordSelector: '.az-word',
        // Justify to the rendered text box. The compact handle lives in the
        // page padding and does not reduce the Quran line width.
        availableWidth: line => line.clientWidth,
        // Amiri has no kashida ladder here — spacing + scaleX like non-feature path.
        featureSettings: () => '',
    });

    /** Centered / special lines skip the justifier — still clamp if too wide. */
    function clampCenteredLines() {
        if (!els.page) return;
        els.page.querySelectorAll('.az-line[data-justify="0"] .az-line-inner, .az-line-special').forEach(inner => {
            const line = inner.closest('.az-line') || inner.parentElement;
            if (!line) return;
            if (inner.classList.contains('az-line-special')) {
                // Specials are the line root when wrapSpecial:false
                const avail = line.clientWidth;
                const natural = inner.scrollWidth;
                if (avail > 0 && natural > avail + 0.5) {
                    inner.style.transform = `scaleX(${Math.max(0.72, avail / natural)})`;
                    inner.style.transformOrigin = 'center center';
                } else {
                    inner.style.transform = '';
                }
                return;
            }
            inner.style.transform = 'none';
            const avail = Math.min(
                line.clientWidth,
                inner.clientWidth || line.clientWidth
            );
            const natural = inner.scrollWidth;
            if (avail > 0 && natural > avail + 0.5) {
                inner.style.transform = `scaleX(${Math.max(0.5, avail / natural)})`;
                inner.style.transformOrigin = 'right center';
            }
        });
    }

    function fitPages() {
        sizePages();
        applyFontSize();
        requestAnimationFrame(() => {
            justifyLines();
            clampCenteredLines();
        });
    }

    const AZHAR_MARK = {
        'م': 'ۘ', 'لا': 'ۙ', 'ج': 'ۚ', 'ق': 'ۗ', 'قلى': 'ۗ',
        'ص': 'ۖ', 'س': 'ۜ', 'ع': 'ۛ', 'ر': 'ۗ',
    };
    const AYAH_NUMBER_RE = /^[٠-٩۰-۹]+$/;

    function bakeAzharMark(text, symbol) {
        const mark = AZHAR_MARK[symbol] || '';
        if (!mark) return text;
        const m = text.match(/^(.*?)([ \s][٠-٩۰-۹]+)?$/);
        if (m && m[2]) return m[1] + mark + m[2];
        return text + mark;
    }

    /* ── Drag spots ─────────────────────────────────────────────── */

    function clearDropHover() {
        if (!els.page) return;
        els.page.querySelectorAll('.az-drop-hover').forEach(el => el.classList.remove('az-drop-hover'));
    }

    function markDropTargets(on) {
        if (!els.page) return;
        els.page.querySelectorAll('.az-line[data-line-type="ayah"]').forEach(line => {
            line.classList.toggle('az-drop-target', on);
        });
        if (!on) clearDropHover();
    }

    function setCancelBar(visible) {
        if (!els.cancelBar) return;
        els.cancelBar.hidden = !visible;
    }

    function lineAtPoint(x, y) {
        const stack = document.elementsFromPoint(x, y);
        for (const el of stack) {
            if (el.classList && el.classList.contains('az-cancel-btn')) return null;
            if (el.id === 'az-cancel-bar' || (el.closest && el.closest('#az-cancel-bar'))) return null;
            const line = el.closest ? el.closest('.az-line[data-line-type="ayah"]') : null;
            if (line && els.page && els.page.contains(line)) return line;
        }
        return null;
    }

    function cancelDrag() {
        const d = state.drag;
        if (!d) return;
        if (d.pointerId != null && d.sourceEl && d.sourceEl.releasePointerCapture) {
            try { d.sourceEl.releasePointerCapture(d.pointerId); } catch (_e) { /* ignore */ }
        }
        if (d.ghost && d.ghost.parentNode) d.ghost.parentNode.removeChild(d.ghost);
        if (d.sourceEl) d.sourceEl.classList.remove('az-word-dragging');
        markDropTargets(false);
        setCancelBar(false);
        document.body.classList.remove('az-dragging');
        state.drag = null;
    }

    function beginDragActive(d) {
        if (d.active) return;
        d.active = true;
        document.body.classList.add('az-dragging');
        d.sourceEl.classList.add('az-word-dragging');
        markDropTargets(true);
        setCancelBar(true);
        const ghost = document.createElement('div');
        ghost.className = 'az-drag-ghost';
        ghost.textContent = d.displayText;
        ghost.setAttribute('aria-hidden', 'true');
        document.body.appendChild(ghost);
        d.ghost = ghost;
        moveGhost(d.x, d.y);
    }

    function moveGhost(x, y) {
        const d = state.drag;
        if (!d || !d.ghost) return;
        d.ghost.style.transform = `translate(${x + 10}px, ${y + 10}px)`;
    }

    function updateDropHover(x, y) {
        clearDropHover();
        const line = lineAtPoint(x, y);
        if (line) line.classList.add('az-drop-hover');
        return line;
    }

    function resolveDropAction(sourceLineNumber, wordId, wordIdsOnLine, targetLineNumber) {
        if (targetLineNumber === sourceLineNumber) {
            // Same line: break after this word (it becomes the line end).
            if (wordIdsOnLine[wordIdsOnLine.length - 1] === wordId) {
                return { error: 'هذه الكلمة آخر السطر أصلاً — اختر كلمة قبلها لكسر السطر' };
            }
            return { lineNumber: sourceLineNumber, wordId, role: 'end' };
        }
        if (targetLineNumber > sourceLineNumber) {
            // Later line: move the break so this word leaves the source line
            // (break after the previous word). Drop line is direction only —
            // capacity cascade places the overflow on following ayah lines
            // within the same surah.
            const idx = wordIdsOnLine.indexOf(wordId);
            if (idx <= 0) {
                return { error: 'هذه الكلمة أول السطر — اسحب كلمة بعدها أو أفلتها على نفس السطر' };
            }
            return {
                lineNumber: sourceLineNumber,
                wordId: wordIdsOnLine[idx - 1],
                role: 'end',
            };
        }
        // Earlier line: fold prior words up so this word starts its line.
        if (wordIdsOnLine[0] === wordId) {
            return { error: 'هذه الكلمة أول السطر أصلاً — اسحب كلمة بعدها لطيّ ما قبلها للأعلى' };
        }
        return { lineNumber: sourceLineNumber, wordId, role: 'start' };
    }

    function onPointerDown(e, meta) {
        if (state.busy || state.drag) return;
        if (e.button != null && e.button !== 0) return;
        state.drag = {
            pointerId: e.pointerId,
            sourceEl: meta.el,
            sourceLineNumber: meta.lineNumber,
            wordId: meta.wordId,
            wordIdsOnLine: meta.wordIdsOnLine,
            displayText: meta.displayText,
            x0: e.clientX,
            y0: e.clientY,
            x: e.clientX,
            y: e.clientY,
            active: false,
            ghost: null,
        };
        try { meta.el.setPointerCapture(e.pointerId); } catch (_e) { /* ignore */ }
        e.preventDefault();
    }

    function onPointerMove(e) {
        const d = state.drag;
        if (!d || e.pointerId !== d.pointerId) return;
        d.x = e.clientX;
        d.y = e.clientY;
        const dist = Math.hypot(d.x - d.x0, d.y - d.y0);
        if (!d.active && dist >= DRAG_THRESHOLD) beginDragActive(d);
        if (!d.active) return;
        moveGhost(d.x, d.y);
        updateDropHover(d.x, d.y);
        e.preventDefault();
    }

    function onPointerUp(e) {
        const d = state.drag;
        if (!d || e.pointerId !== d.pointerId) return;
        const wasActive = d.active;
        const x = e.clientX;
        const y = e.clientY;
        const sourceLine = d.sourceLineNumber;
        const wordId = d.wordId;
        const wordIds = d.wordIdsOnLine.slice();
        cancelDrag();
        if (!wasActive) return;

        const targetLine = lineAtPoint(x, y);
        if (!targetLine) {
            setStatus('أُلغي النقل');
            return;
        }
        const targetLineNumber = parseInt(targetLine.dataset.lineNumber, 10);
        const action = resolveDropAction(sourceLine, wordId, wordIds, targetLineNumber);
        if (action.error) {
            setStatus(action.error, true);
            return;
        }
        setLineBreak(action.lineNumber, action.wordId, action.role);
    }

    function bindWordDrag(span, meta) {
        span.addEventListener('pointerdown', e => onPointerDown(e, { ...meta, el: span }));
    }

    /* ── Render (same AtharMushaf contract as mushaf_editor) ──────── */

    function attachLineTools(root, line) {
        const lineNumber = line.line_number;
        const tools = document.createElement('div');
        tools.className = 'az-line-tools az-ayah-tools';

        const menuBtn = document.createElement('button');
        menuBtn.type = 'button';
        menuBtn.className = 'az-line-tool az-line-menu';
        menuBtn.title = 'أدوات السطر';
        menuBtn.setAttribute('aria-label', menuBtn.title);
        menuBtn.setAttribute('aria-expanded', 'false');
        menuBtn.innerHTML = '<i class="fas fa-ellipsis-vertical" aria-hidden="true"></i>';

        const actions = document.createElement('div');
        actions.className = 'az-line-actions';
        menuBtn.addEventListener('click', e => {
            e.stopPropagation();
            const opening = !tools.classList.contains('az-tools-open');
            root.parentElement?.querySelectorAll('.az-tools-open').forEach(other => {
                if (other !== tools) {
                    other.classList.remove('az-tools-open');
                    other.querySelector('.az-line-menu')?.setAttribute(
                        'aria-expanded', 'false'
                    );
                }
            });
            tools.classList.toggle('az-tools-open', opening);
            menuBtn.setAttribute('aria-expanded', String(opening));
        });

        const pullBtn = document.createElement('button');
        pullBtn.type = 'button';
        pullBtn.className = 'az-line-tool az-pull-btn';
        pullBtn.title = 'سحب أول كلمة من السطر التالي إلى هذا السطر';
        pullBtn.setAttribute('aria-label', pullBtn.title);
        pullBtn.innerHTML = '<i class="fas fa-arrow-up" aria-hidden="true"></i>';
        pullBtn.addEventListener('click', e => {
            e.stopPropagation();
            pullNextWord(lineNumber);
        });

        const pushBtn = document.createElement('button');
        pushBtn.type = 'button';
        pushBtn.className = 'az-line-tool az-push-btn';
        pushBtn.title = 'دفع آخر كلمة إلى السطر التالي (أو الصفحة التالية)';
        pushBtn.setAttribute('aria-label', pushBtn.title);
        pushBtn.innerHTML = '<i class="fas fa-arrow-down" aria-hidden="true"></i>';
        pushBtn.addEventListener('click', e => {
            e.stopPropagation();
            pushLastWord(lineNumber);
        });

        const mergeBtn = document.createElement('button');
        mergeBtn.type = 'button';
        mergeBtn.className = 'az-line-tool az-merge-btn';
        mergeBtn.title = 'دمج مع السطر التالي';
        mergeBtn.setAttribute('aria-label', 'دمج مع السطر التالي');
        mergeBtn.innerHTML = '<i class="fas fa-compress-alt" aria-hidden="true"></i>';
        mergeBtn.addEventListener('click', e => {
            e.stopPropagation();
            mergeLine(lineNumber);
        });

        const centerBtn = document.createElement('button');
        const isCentered = Boolean(line.is_centered);
        centerBtn.type = 'button';
        centerBtn.className = `az-line-tool az-center-btn${isCentered ? ' az-active' : ''}`;
        centerBtn.title = isCentered ? 'إلغاء توسيط السطر' : 'توسيط السطر';
        centerBtn.setAttribute('aria-label', centerBtn.title);
        centerBtn.setAttribute('aria-pressed', String(isCentered));
        centerBtn.innerHTML = '<i class="fas fa-align-center" aria-hidden="true"></i>';
        centerBtn.addEventListener('click', e => {
            e.stopPropagation();
            setLineCentered(lineNumber, !isCentered);
        });

        actions.appendChild(pullBtn);
        actions.appendChild(pushBtn);
        actions.appendChild(mergeBtn);
        actions.appendChild(centerBtn);
        tools.appendChild(menuBtn);
        tools.appendChild(actions);
        root.appendChild(tools);
    }

    function attachHeaderTools(root, line) {
        const lineNumber = line.line_number;
        const labels = {
            surah_name: 'اسم السورة',
            surah_info: 'معلومات السورة',
            basmallah: 'البسملة',
        };
        const label = labels[line.line_type] || 'العنوان';
        const tools = document.createElement('div');
        tools.className = 'az-line-tools az-header-tools';

        const makeButton = (direction, icon, action) => {
            const button = document.createElement('button');
            button.type = 'button';
            button.className = `az-line-tool az-header-move az-header-${direction}`;
            button.title = `${action} ${label} سطراً واحداً`;
            button.setAttribute('aria-label', button.title);
            button.innerHTML = `<i class="fas fa-arrow-${icon}" aria-hidden="true"></i>`;
            button.addEventListener('click', event => {
                event.stopPropagation();
                moveHeader(lineNumber, direction, label);
            });
            return button;
        };

        tools.appendChild(makeButton('up', 'up', 'نقل'));
        tools.appendChild(makeButton('down', 'down', 'نقل'));
        root.appendChild(tools);
    }

    function applyLineSpan(root, line) {
        const raw = Number(line && line.slot_span);
        const span = Math.max(0, Number.isFinite(raw) ? raw : 1);
        root.dataset.slotSpan = String(span);
        root.style.setProperty('--az-line-span', String(span));
    }

    function renderPage(payload) {
        cancelDrag();
        const container = els.page;
        if (!payload) {
            container.replaceChildren();
            clearPageChrome({
                juzEl: els.juz, surahEl: els.surah, pageNumberEl: els.pageNum,
                juzGlyphClass: 'athar-page-juz-glyph',
            });
            return;
        }
        state.pageSlotBudget = Math.max(
            1,
            Number(payload.lines_per_page)
                || Number(payload.default_lines_per_page)
                || Number(CFG.linesPerPage)
                || 15
        );
        container.style.setProperty('--az-page-slots', String(state.pageSlotBudget));

        window.AtharMushaf.renderMushafLines(container, payload.lines || [], {
            lineClass: 'az-line',
            surahClass: 'az-line az-line-special',
            surahInfoClass: 'az-line az-line-special az-line-surah-info',
            basmalaClass: 'az-line az-line-special',
            wrapSpecial: false,
            contentClass: 'az-line-inner',
            separator: ' ',
            wordClass: 'az-word',
            countWord: () => false,
            textForWord: ({ word }) => {
                let clean = stripEmbeddedWaqf(word.text || '');
                const entries = Array.isArray(word.waqf_symbols) ? word.waqf_symbols : [];
                const selected = entries.find(
                    e => e.version === (CFG.mushafVersion || 'الأزهر')
                );
                const sym = (selected && selected.symbols) || '';
                if (sym) clean = bakeAzharMark(clean, sym);
                if (AYAH_NUMBER_RE.test(clean) && !clean.startsWith('۝')) clean = `۝${clean}`;
                return clean;
            },
            decorateSpecial: (root, { line, kind }) => {
                root.dataset.lineNumber = String(line.line_number);
                root.dataset.lineType = line.line_type || kind || '';
                root.dataset.justify = '0';
                applyLineSpan(root, line);
                attachHeaderTools(root, line);
            },
            decorateLine: (root, { line }) => {
                root.dataset.lineNumber = String(line.line_number);
                root.dataset.lineType = line.line_type || 'ayah';
                root.dataset.justify = line.is_centered ? '0' : '1';
                applyLineSpan(root, line);
                if (line.line_type === 'ayah') attachLineTools(root, line);
            },
            decorateWord: (wordElement, { line, word, wordIndex }) => {
                const words = line.words || [];
                const wordIdsOnLine = words.map(w => w.word_index);
                const isStart = wordIndex === 0;
                const isEnd = wordIndex === words.length - 1;
                if (isStart) wordElement.classList.add('az-word-start');
                if (isEnd) wordElement.classList.add('az-word-end');
                if (AYAH_NUMBER_RE.test(stripEmbeddedWaqf(word.text || ''))) {
                    wordElement.classList.add('az-ayah-end');
                }
                const display = wordElement.textContent || '';
                const clean = stripEmbeddedWaqf(word.text || '');
                wordElement.dataset.wordId = String(word.word_index);
                wordElement.dataset.lineNumber = String(line.line_number);
                wordElement.dataset.text = clean;
                wordElement.tabIndex = 0;
                wordElement.setAttribute('role', 'button');
                const tip = [
                    isStart ? 'بداية السطر' : '',
                    isEnd ? 'نهاية السطر' : '',
                    'اسحب إلى سطر لتغيير الحد',
                ].filter(Boolean).join(' · ');
                wordElement.title = tip;
                wordElement.setAttribute('aria-label', `${display}. ${tip}`);
                bindWordDrag(wordElement, {
                    lineNumber: line.line_number,
                    wordId: word.word_index,
                    wordIdsOnLine,
                    displayText: display,
                });
            },
        });

        renderPageChrome({
            payload, juzEl: els.juz, surahEl: els.surah, pageNumberEl: els.pageNum,
            juzGlyphClass: 'athar-page-juz-glyph',
            surahGlyphClass: 'athar-page-surah-glyph',
            surahTextClass: 'athar-page-surah-text',
        });
    }

    /* ── Printed reference (Archive.org images or remote PDF via pdf.js) ─ */
    function pageToLeaf(page) {
        return page + (REF_SOURCE.leafOffset || 0);
    }
    function pdfPageNumber(page) {
        return page + (Number(REF_SOURCE.pdfPageOffset) || 0);
    }
    function refPdfUrl(page) {
        const base = REF_SOURCE.pdfUrl || '';
        if (!base) return '';
        return `${base}#page=${pdfPageNumber(page)}&zoom=page-fit`;
    }
    function refImageUrl(page) {
        if (REF_SOURCE.type === 'pdf') return '';
        if (REF_SOURCE.type === 'local' && REF_SOURCE.imageTemplate) {
            return REF_SOURCE.imageTemplate.replace('{page}', String(page));
        }
        return `https://archive.org/download/${REF_SOURCE.id}/page/leaf${pageToLeaf(page)}_w${REF_IMG_WIDTH}.jpg`;
    }
    function refOpenUrl(page) {
        if (REF_SOURCE.pdfUrl || REF_SOURCE.type === 'pdf') return refPdfUrl(page);
        if (REF_SOURCE.type === 'local') {
            return (
                REF_SOURCE.openTemplate || REF_SOURCE.imageTemplate
            ).replace('{page}', String(page));
        }
        // Details /page/N is 1-based (leaf0 → /page/1).
        return `https://archive.org/details/${REF_SOURCE.id}/page/${pageToLeaf(page) + 1}`;
    }
    function showRefState({ loading = false, image = false, frame = false, fallback = false } = {}) {
        if (els.refLoading) els.refLoading.hidden = !loading;
        if (els.refImg) els.refImg.hidden = !image;
        if (els.refFrame) els.refFrame.hidden = !frame;
        if (els.refFallback) els.refFallback.hidden = !fallback;
    }
    function clearReference() {
        state.refUrl = '';
        if (els.refOpen) els.refOpen.hidden = true;
        showRefState();
        if (els.refImg) {
            els.refImg.removeAttribute('src');
            els.refImg.alt = 'صفحة المصحف المطبوع';
        }
        if (els.refFrame) els.refFrame.removeAttribute('src');
    }
    function openReference() {
        if (!state.refUrl) return;
        window.open(state.refUrl, '_blank', 'noopener');
    }
    function prefetchRef(page) {
        if (REF_SOURCE.type === 'pdf') return;
        if (page < MIN_PAGE || page > MAX_PAGE) return;
        const url = refImageUrl(page);
        if (refPrefetch.has(url)) return;
        refPrefetch.add(url);
        const img = new Image();
        img.decoding = 'async';
        img.src = url;
    }
    function syncReference(page) {
        clearTimeout(refTimer);
        if (!Number.isFinite(page) || page < MIN_PAGE || page > MAX_PAGE) {
            clearReference();
            return;
        }
        if (!els.refImg && !els.refFrame) {
            clearReference();
            return;
        }
        state.refUrl = refOpenUrl(page);
        if (els.refOpen) {
            els.refOpen.hidden = false;
            const label = REF_SOURCE.type === 'archive'
                ? `فتح ${REF_SOURCE.label} في الأرشيف`
                : `فتح ${REF_SOURCE.label}`;
            els.refOpen.title = label;
            els.refOpen.setAttribute('aria-label', label);
        }
        if (els.refTitle) els.refTitle.textContent = REF_SOURCE.label;
        const token = ++refLoadToken;
        refTimer = setTimeout(() => {
            if (token !== refLoadToken) return;
            showRefState({ loading: true });
            if (els.refFrame) {
                els.refFrame.hidden = true;
                els.refFrame.removeAttribute('src');
            }
            if (REF_SOURCE.type === 'pdf') {
                if (!window.AtharPdfRef || !els.refImg || !REF_SOURCE.pdfUrl) {
                    showRefState({ fallback: true });
                    return;
                }
                const pdfPage = pdfPageNumber(page);
                window.AtharPdfRef.renderPage(REF_SOURCE.pdfUrl, pdfPage, { maxWidth: REF_IMG_WIDTH })
                    .then((blobUrl) => {
                        if (token !== refLoadToken) return;
                        els.refImg.alt = `${REF_SOURCE.label} — صفحة ${page}`;
                        const onLoad = () => {
                            if (token !== refLoadToken) return;
                            showRefState({ image: true });
                            window.AtharPdfRef.prefetchNeighbors(
                                REF_SOURCE.pdfUrl, pdfPage, { maxWidth: REF_IMG_WIDTH },
                            );
                        };
                        const onError = () => {
                            if (token !== refLoadToken) return;
                            showRefState({ fallback: true });
                        };
                        els.refImg.onload = onLoad;
                        els.refImg.onerror = onError;
                        els.refImg.src = blobUrl;
                        if (els.refImg.complete && els.refImg.naturalWidth) onLoad();
                    })
                    .catch(() => {
                        if (token !== refLoadToken) return;
                        showRefState({ fallback: true });
                    });
                return;
            }
            if (!els.refImg) {
                showRefState({ fallback: true });
                return;
            }
            els.refImg.alt = `${REF_SOURCE.label} — صفحة ${page}`;
            const onLoad = () => {
                if (token !== refLoadToken) return;
                showRefState({ image: true });
            };
            const onError = () => {
                if (token !== refLoadToken) return;
                showRefState({ fallback: true });
            };
            els.refImg.onload = onLoad;
            els.refImg.onerror = onError;
            els.refImg.src = refImageUrl(page);
            prefetchRef(page - 1);
            prefetchRef(page + 1);
        }, REF_DEBOUNCE_MS);
    }

    async function loadPage() {
        const request = pageRequests.next();
        const page = state.page;
        window.AtharUi.setBusy(els.main, true);
        syncReference(page);
        try {
            const data = await window.AtharApi.json(`${API_BASE}/page/${page}`);
            if (!pageRequests.isCurrent(request)) return;
            renderPage(data);
            els.pageLabel.textContent = `${toAr(page)} / ${toAr(MAX_PAGE)}`;
            updateNav();
            updateReviewedCheckbox();
            refreshUndoStatus();
            fitPages();
        } catch (e) {
            if (pageRequests.isCurrent(request)) setStatus('تعذّر تحميل الصفحة', true);
        } finally {
            if (pageRequests.isCurrent(request)) window.AtharUi.setBusy(els.main, false);
        }
    }

    function setUndoAvailable(n) {
        state.undoAvailable = Math.max(0, Number(n) || 0);
        if (els.undo) {
            els.undo.disabled = state.busy || state.undoAvailable < 1;
            els.undo.title = state.undoAvailable
                ? `تراجع (${toAr(state.undoAvailable)})`
                : 'لا يوجد تعديل للتراجع عنه';
        }
    }

    async function refreshUndoStatus() {
        const page = state.page;
        try {
            const data = await window.AtharApi.json(
                `${API_BASE}/undo-status?page_number=${page}`
            );
            if (state.page !== page) return;
            setUndoAvailable(data.undo_available);
        } catch (e) {
            if (state.page === page) setUndoAvailable(0);
        }
    }

    async function setLineBreak(lineNumber, wordId, role) {
        if (state.busy) return;
        const boundary = role === 'start' ? 'start' : 'end';
        state.busy = true;
        window.AtharUi.setBusy(els.main, true);
        updateNav();
        try {
            const data = await window.AtharApi.json(`${API_BASE}/line-break`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    page_number: state.page,
                    line_number: lineNumber,
                    word_id: wordId,
                    role: boundary,
                }),
            });
            if (data.page) {
                renderPage(data.page);
                fitPages();
            }
            if (typeof data.undo_available === 'number') setUndoAvailable(data.undo_available);
            if (data.unchanged) {
                if (data.reason === 'already_line_start') {
                    setStatus('هذه الكلمة أول السطر أصلاً');
                } else if (data.reason === 'already_line_end') {
                    setStatus('هذه الكلمة آخر السطر أصلاً');
                } else {
                    setStatus(boundary === 'start' ? 'هذه الكلمة بداية السطر أصلاً' : 'هذه الكلمة نهاية السطر أصلاً');
                }
            } else {
                setStatus(boundary === 'start' ? 'تم ضبط بداية السطر' : 'تم ضبط نهاية السطر');
            }
        } catch (e) {
            const msg = (e && e.message) || (e && e.error) || '';
            setStatus(msg && /سور|بسمل|فاصل|سطر/.test(msg) ? msg : 'تعذّر ضبط حد السطر', true);
        } finally {
            state.busy = false;
            window.AtharUi.setBusy(els.main, false);
            updateNav();
        }
    }

    async function mergeLine(lineNumber) {
        if (state.busy) return;
        state.busy = true;
        window.AtharUi.setBusy(els.main, true);
        updateNav();
        try {
            const data = await window.AtharApi.json(`${API_BASE}/merge-line`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    page_number: state.page,
                    line_number: lineNumber,
                }),
            });
            if (data.page) {
                renderPage(data.page);
                fitPages();
            }
            if (typeof data.undo_available === 'number') setUndoAvailable(data.undo_available);
            setStatus('تم دمج السطر مع التالي');
        } catch (e) {
            setStatus('تعذّر الدمج', true);
        } finally {
            state.busy = false;
            window.AtharUi.setBusy(els.main, false);
            updateNav();
        }
    }

    async function pullNextWord(lineNumber) {
        if (state.busy) return;
        state.busy = true;
        window.AtharUi.setBusy(els.main, true);
        updateNav();
        try {
            const data = await window.AtharApi.json(`${API_BASE}/pull-next-word`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    page_number: state.page,
                    line_number: lineNumber,
                }),
            });
            if (data.page) {
                renderPage(data.page);
                fitPages();
            }
            if (typeof data.undo_available === 'number') setUndoAvailable(data.undo_available);
            setStatus(
                data.crossed_page || data.from_page !== state.page
                    ? 'تم سحب كلمة من الصفحة التالية'
                    : 'تم سحب كلمة من السطر التالي'
            );
        } catch (e) {
            const msg = (e && e.message) || (e && e.error) || '';
            setStatus(msg || 'تعذّر سحب الكلمة من السطر التالي', true);
        } finally {
            state.busy = false;
            window.AtharUi.setBusy(els.main, false);
            updateNav();
        }
    }

    async function pushLastWord(lineNumber) {
        if (state.busy) return;
        state.busy = true;
        window.AtharUi.setBusy(els.main, true);
        updateNav();
        try {
            const data = await window.AtharApi.json(`${API_BASE}/push-last-word`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    page_number: state.page,
                    line_number: lineNumber,
                }),
            });
            if (data.page) {
                renderPage(data.page);
                fitPages();
            }
            if (typeof data.undo_available === 'number') setUndoAvailable(data.undo_available);
            setStatus(
                data.crossed_page
                    ? 'تم دفع الكلمة إلى الصفحة التالية'
                    : 'تم دفع الكلمة إلى السطر التالي'
            );
        } catch (e) {
            const msg = (e && e.message) || (e && e.error) || '';
            setStatus(msg || 'تعذّر دفع الكلمة إلى السطر التالي', true);
        } finally {
            state.busy = false;
            window.AtharUi.setBusy(els.main, false);
            updateNav();
        }
    }

    async function setLineCentered(lineNumber, isCentered) {
        if (state.busy) return;
        state.busy = true;
        window.AtharUi.setBusy(els.main, true);
        updateNav();
        try {
            const data = await window.AtharApi.json(`${API_BASE}/line-center`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    page_number: state.page,
                    line_number: lineNumber,
                    is_centered: Boolean(isCentered),
                }),
            });
            if (data.page) {
                renderPage(data.page);
                fitPages();
            }
            if (typeof data.undo_available === 'number') setUndoAvailable(data.undo_available);
            setStatus(isCentered ? 'تم توسيط السطر' : 'تم إلغاء توسيط السطر');
        } catch (e) {
            setStatus('تعذّر تغيير توسيط السطر', true);
        } finally {
            state.busy = false;
            window.AtharUi.setBusy(els.main, false);
            updateNav();
        }
    }

    async function moveHeader(lineNumber, direction, label) {
        if (state.busy) return;
        state.busy = true;
        window.AtharUi.setBusy(els.main, true);
        updateNav();
        try {
            const data = await window.AtharApi.json(`${API_BASE}/header-move`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    page_number: state.page,
                    line_number: lineNumber,
                    direction,
                }),
            });
            if (data.page) {
                renderPage(data.page);
                fitPages();
            }
            if (typeof data.undo_available === 'number') {
                setUndoAvailable(data.undo_available);
            }
            if (data.crossed_page) {
                setStatus(
                    data.moved_to_page < state.page
                        ? `تم نقل ${label} إلى الصفحة السابقة`
                        : `تم نقل ${label} إلى الصفحة التالية`
                );
            } else {
                setStatus(
                    direction === 'up'
                        ? `تم رفع ${label} سطراً`
                        : `تم خفض ${label} سطراً`
                );
            }
        } catch (e) {
            const msg = (e && e.message) || (e && e.error) || '';
            setStatus(msg || `تعذّر نقل ${label}`, true);
        } finally {
            state.busy = false;
            window.AtharUi.setBusy(els.main, false);
            updateNav();
        }
    }

    async function undoLast() {
        if (state.busy || state.undoAvailable < 1) return;
        state.busy = true;
        window.AtharUi.setBusy(els.main, true);
        updateNav();
        try {
            const data = await window.AtharApi.json(`${API_BASE}/undo`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ page_number: state.page }),
            });
            if (data.page) {
                renderPage(data.page);
                fitPages();
            }
            if (typeof data.undo_available === 'number') setUndoAvailable(data.undo_available);
            else await refreshUndoStatus();
            setStatus('تم التراجع');
        } catch (e) {
            setStatus('تعذّر التراجع', true);
            await refreshUndoStatus();
        } finally {
            state.busy = false;
            window.AtharUi.setBusy(els.main, false);
            updateNav();
        }
    }

    function updateNav() {
        els.prev.disabled = state.page <= MIN_PAGE;
        els.next.disabled = state.page >= MAX_PAGE;
        if (els.undo) els.undo.disabled = state.busy || state.undoAvailable < 1;
    }

    async function loadProgress() {
        const request = progressRequests.next();
        try {
            const data = await window.AtharApi.json(`${API_BASE}/progress`);
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
        const total = MAX_PAGE - MIN_PAGE + 1;
        els.progress.textContent = `${toAr(state.reviewedPages.size)} / ${toAr(total)} مطابِقة`;
        els.progress.setAttribute('aria-valuenow', String(state.reviewedPages.size));
        els.progress.setAttribute('aria-valuemax', String(total));
    }
    function updateReviewedCheckbox() {
        els.reviewed.checked = state.reviewedPages.has(state.page);
    }

    els.reviewed.addEventListener('change', async () => {
        const reviewed = els.reviewed.checked;
        const page = state.page;
        els.reviewed.disabled = true;
        try {
            await window.AtharApi.json(`${API_BASE}/progress`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ page_number: page, reviewed }),
            });
            if (reviewed) state.reviewedPages.add(page);
            else state.reviewedPages.delete(page);
            updateProgressLabel();
            setStatus('تم حفظ حالة المطابقة');
        } catch (e) {
            els.reviewed.checked = !reviewed;
            setStatus('تعذّر حفظ المطابقة', true);
        } finally {
            els.reviewed.disabled = false;
        }
    });

    function goTo(page) {
        cancelDrag();
        state.page = clampPage(page);
        persist();
        loadPage();
    }
    els.prev.addEventListener('click', () => { if (state.page > MIN_PAGE) goTo(state.page - 1); });
    els.next.addEventListener('click', () => { if (state.page < MAX_PAGE) goTo(state.page + 1); });
    if (els.undo) els.undo.addEventListener('click', () => { undoLast(); });
    els.jumpBtn.addEventListener('click', () => {
        const p = parseInt(els.jumpInput.value, 10);
        if (!Number.isFinite(p) || p < MIN_PAGE || p > MAX_PAGE) {
            setStatus(`رقم صفحة غير صالح (${toAr(MIN_PAGE)}–${toAr(MAX_PAGE)})`, true);
            return;
        }
        els.jumpInput.value = '';
        goTo(p);
    });
    els.jumpInput.addEventListener('keydown', e => { if (e.key === 'Enter') els.jumpBtn.click(); });

    els.jumpAyahBtn.addEventListener('click', async () => {
        const s = parseInt(els.jumpSurah.value, 10);
        const a = parseInt(els.jumpAyah.value, 10);
        if (!Number.isFinite(s) || !Number.isFinite(a) || s < 1 || a < 1) {
            setStatus('أدخل سورة وآية صالحتين', true);
            return;
        }
        try {
            const data = await window.AtharApi.json(`${PAGE_BY_AYAH_BASE}/${s}/${a}`);
            if (data.page_number) goTo(data.page_number);
        } catch (e) {
            setStatus('تعذّر إيجاد صفحة الآية', true);
        }
    });

    if (els.cancel) {
        els.cancel.addEventListener('pointerdown', e => e.stopPropagation());
        els.cancel.addEventListener('click', e => {
            e.preventDefault();
            e.stopPropagation();
            if (state.drag) {
                cancelDrag();
                setStatus('أُلغي النقل');
            }
        });
    }
    if (els.refOpen) els.refOpen.addEventListener('click', openReference);
    if (els.refFallbackBtn) els.refFallbackBtn.addEventListener('click', openReference);

    document.addEventListener('pointermove', onPointerMove);
    document.addEventListener('pointerup', onPointerUp);
    document.addEventListener('pointercancel', e => {
        const d = state.drag;
        if (d && e.pointerId === d.pointerId) {
            cancelDrag();
            setStatus('أُلغي النقل');
        }
    });

    document.addEventListener('keydown', e => {
        if (e.key === 'Escape' && state.drag) {
            e.preventDefault();
            cancelDrag();
            setStatus('أُلغي النقل');
            return;
        }
        if ((e.metaKey || e.ctrlKey) && (e.key === 'z' || e.key === 'Z')) {
            e.preventDefault();
            undoLast();
            return;
        }
        if (e.target.tagName === 'INPUT') return;
        if (e.key === 'ArrowLeft') els.next.click();
        if (e.key === 'ArrowRight') els.prev.click();
    });

    let resizeId = 0;
    window.addEventListener('resize', () => {
        clearTimeout(resizeId);
        resizeId = setTimeout(fitPages, 120);
    });

    initProfileForm();
    loadProgress();
    loadPage();
})();
