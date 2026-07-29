(() => {
    const $ = (id) => document.getElementById(id);
    const body = document.body;
    const editions = JSON.parse(body.dataset.editions || '[]');
    const symbols = JSON.parse(body.dataset.symbols || '[]');
    const defaultEdition = body.dataset.defaultEdition || (editions[0] && editions[0].id) || 'الشمرلي';
    let minPage = parseInt(body.dataset.minPage || '2', 10);
    let maxPage = parseInt(body.dataset.maxPage || '522', 10);
    const startPage = parseInt(body.dataset.startPage || String(minPage), 10);

    const athar = window.AtharMushaf || {};
    const normalizeGlyph = typeof athar.normalizeNonWarshWaqfText === 'function'
        ? athar.normalizeNonWarshWaqfText
        : (s) => s;

    const els = {
        edition: $('wmr-edition'),
        page: $('wmr-page'),
        prev: $('wmr-prev'),
        next: $('wmr-next'),
        meta: $('wmr-meta'),
        progress: $('wmr-progress'),
        legend: $('wmr-legend'),
        list: $('wmr-list'),
        missingNote: $('wmr-missing-note'),
        missingSave: $('wmr-missing-save'),
        missingList: $('wmr-missing-list'),
        done: $('wmr-done'),
        exportBtn: $('wmr-export'),
        sheet: $('wmr-sheet'),
        sheetBackdrop: $('wmr-sheet-backdrop'),
        sheetWord: $('wmr-sheet-word'),
        sheetCancel: $('wmr-sheet-cancel'),
        glyphs: $('wmr-glyphs'),
        toast: $('wmr-toast'),
        pageFont: $('wmr-page-font'),
        auth: $('wmr-auth'),
        login: $('wmr-login'),
        loginForm: $('wmr-login-form'),
        loginUsername: $('wmr-login-username'),
        loginPassword: $('wmr-login-password'),
        loginError: $('wmr-login-error'),
        loginSubmit: $('wmr-login-submit'),
        loginSkip: $('wmr-login-skip'),
    };

    const state = {
        edition: localStorage.getItem('wmr_edition') || defaultEdition,
        page: clampPage(parseInt(localStorage.getItem('wmr_page_shemrly') || String(startPage), 10)),
        items: [],
        usePageFont: false,
        fontName: '',
        decisions: {},
        pendingWrong: null,
        reviewedPages: new Set(),
        cloud: false,
        authenticated: true,
        storage: 'local',
        userName: '',
    };

    function clampPage(n) {
        if (!Number.isFinite(n)) return minPage;
        return Math.min(maxPage, Math.max(minPage, n));
    }

    function storeKey() {
        return `wmr_decisions_v2_${state.edition}`;
    }

    function loadStore() {
        try {
            return JSON.parse(localStorage.getItem(storeKey()) || '{}') || {};
        } catch {
            return {};
        }
    }

    function saveStore() {
        localStorage.setItem(storeKey(), JSON.stringify(state.decisions));
    }

    function itemKey(item) {
        return String(item.word_id);
    }

    function toAr(n) {
        return String(n).replace(/\d/g, (d) => '٠١٢٣٤٥٦٧٨٩'[d]);
    }

    function fromArDigits(raw) {
        return String(raw || '')
            .replace(/[٠-٩]/g, (d) => '٠١٢٣٤٥٦٧٨٩'.indexOf(d))
            .replace(/[^\d]/g, '');
    }

    function setPageInput(n) {
        els.page.value = toAr(n);
    }

    function readPageInput() {
        return clampPage(parseInt(fromArDigits(els.page.value), 10));
    }

    function toast(msg) {
        els.toast.textContent = msg;
        els.toast.hidden = false;
        clearTimeout(toast._t);
        toast._t = setTimeout(() => { els.toast.hidden = true; }, 2200);
    }

    function escapeHtml(s) {
        return String(s)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    function markGlyph(code) {
        if (!code) return '';
        if (code === 'ركوع') return code;
        return normalizeGlyph(code) || code;
    }

    function canSyncServer() {
        return !state.cloud || state.authenticated;
    }

    function renderAuth() {
        if (!els.auth) return;
        if (!state.cloud) {
            els.auth.textContent = 'حفظ محلي على الجهاز (وضع تطوير)';
            return;
        }
        if (state.authenticated) {
            const name = state.userName ? ` · ${state.userName}` : '';
            els.auth.innerHTML = `متصل بالخادم${escapeHtml(name)}`
                + ` <button type="button" id="wmr-logout">خروج</button>`;
            const btn = $('wmr-logout');
            if (btn) btn.addEventListener('click', logout);
        } else {
            els.auth.innerHTML = 'غير مسجّل — الحفظ محلي فقط'
                + ' <button type="button" id="wmr-show-login">دخول</button>';
            const btn = $('wmr-show-login');
            if (btn) btn.addEventListener('click', () => showLogin(false));
        }
    }

    function showLogin(force) {
        if (!els.login) return;
        if (!state.cloud && !force) return;
        els.login.hidden = false;
        if (els.loginError) {
            els.loginError.hidden = true;
            els.loginError.textContent = '';
        }
        if (els.loginPassword) els.loginPassword.value = '';
        if (els.loginUsername) {
            requestAnimationFrame(() => els.loginUsername.focus());
        }
    }

    function hideLogin() {
        if (els.login) els.login.hidden = true;
    }

    async function checkAuth() {
        try {
            const data = await api('/api/mushaf-editor/auth/status');
            state.cloud = !!data.cloud;
            state.authenticated = !!data.authenticated;
            state.userName = (data.user && data.user.name) || '';
            if (data.login_required) showLogin(true);
            else hideLogin();
        } catch {
            state.cloud = false;
            state.authenticated = true;
            state.userName = '';
            hideLogin();
        }
        renderAuth();
    }

    async function logout() {
        try {
            await api('/api/mushaf-editor/logout', { method: 'POST', body: '{}' });
        } catch { /* ignore */ }
        state.authenticated = false;
        state.userName = '';
        renderAuth();
        if (state.cloud) showLogin(true);
        toast('خرجت من الجلسة');
    }

    function decisionFor(item) {
        const pageMap = state.decisions[String(state.page)] || {};
        return pageMap[itemKey(item)] || null;
    }

    async function persistDecision(item, decision) {
        if (!canSyncServer()) return;
        const payload = {
            edition: state.edition,
            page_number: state.page,
            word_id: item.word_id,
        };
        try {
            if (!decision) {
                await api('/api/waqf-mark-review/decisions', {
                    method: 'DELETE',
                    body: JSON.stringify(payload),
                });
            } else {
                await api('/api/waqf-mark-review/decisions', {
                    method: 'POST',
                    body: JSON.stringify({
                        ...payload,
                        decision: decision.decision,
                        our_mark: decision.our_mark,
                        correct_mark: decision.correct_mark,
                        surah: decision.surah != null ? decision.surah : item.surah,
                        ayah: decision.ayah != null ? decision.ayah : item.ayah,
                        text: decision.text || item.text || '',
                    }),
                });
            }
        } catch (err) {
            if (err.status === 401) {
                state.authenticated = false;
                renderAuth();
                showLogin(true);
                toast('سجّل الدخول لمزامنة القرارات');
            } else {
                toast(err.message || 'تعذّر الحفظ على الخادم');
            }
        }
    }

    function setDecision(item, decision) {
        const page = String(state.page);
        if (!state.decisions[page]) state.decisions[page] = {};
        if (!decision) delete state.decisions[page][itemKey(item)];
        else {
            state.decisions[page][itemKey(item)] = {
                decision: decision.decision,
                our_mark: decision.our_mark,
                correct_mark: decision.correct_mark,
                word_id: item.word_id,
                surah: decision.surah != null ? decision.surah : item.surah,
                ayah: decision.ayah != null ? decision.ayah : item.ayah,
                text: decision.text || item.text || '',
            };
        }
        if (state.decisions[page] && !Object.keys(state.decisions[page]).length) {
            delete state.decisions[page];
        }
        saveStore();
        persistDecision(item, decision ? state.decisions[page] && state.decisions[page][itemKey(item)] : null);
    }

    function missingNotes() {
        return (state.decisions._missing || {})[String(state.page)] || [];
    }

    async function saveMissing(text) {
        const page = String(state.page);
        if (!state.decisions._missing) state.decisions._missing = {};
        if (!state.decisions._missing[page]) state.decisions._missing[page] = [];
        const localNote = { text, at: new Date().toISOString() };
        state.decisions._missing[page].push(localNote);
        saveStore();
        renderMissing();
        if (!canSyncServer()) return;
        try {
            const data = await api('/api/waqf-mark-review/notes', {
                method: 'POST',
                body: JSON.stringify({
                    edition: state.edition,
                    page_number: state.page,
                    note: text,
                }),
            });
            if (data.note && data.note.id != null) {
                localNote.id = data.note.id;
                if (data.note.at) localNote.at = data.note.at;
                saveStore();
            }
        } catch (err) {
            if (err.status === 401) {
                state.authenticated = false;
                renderAuth();
                showLogin(true);
            }
            toast(err.message || 'حُفظت محليًا فقط');
        }
    }

    async function api(url, opts) {
        const res = await fetch(url, {
            credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json', ...(opts && opts.headers) },
            ...opts,
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
            const err = new Error(data.error || res.statusText);
            err.status = res.status;
            err.data = data;
            throw err;
        }
        return data;
    }

    function mergeDecisions(server) {
        const merged = { ...loadStore() };
        const missingLocal = merged._missing || {};
        const missingServer = (server && server._missing) || {};
        Object.keys(server || {}).forEach((key) => {
            if (key === '_missing') return;
            merged[key] = { ...(merged[key] || {}), ...server[key] };
        });
        const missing = { ...missingLocal };
        Object.keys(missingServer).forEach((page) => {
            const localList = missing[page] || [];
            const serverList = missingServer[page] || [];
            const seen = new Set(localList.map((n) => `${n.id || ''}|${n.text}`));
            const combined = [...localList];
            serverList.forEach((n) => {
                const sig = `${n.id || ''}|${n.text}`;
                if (!seen.has(sig)) combined.push(n);
            });
            missing[page] = combined;
        });
        if (Object.keys(missing).length) merged._missing = missing;
        else delete merged._missing;
        state.decisions = merged;
        saveStore();
    }

    async function migrateLocalToServer() {
        if (!canSyncServer()) return;
        const local = loadStore();
        const jobs = [];
        Object.keys(local).forEach((page) => {
            if (page === '_missing') return;
            const map = local[page] || {};
            Object.keys(map).forEach((wordId) => {
                const d = map[wordId];
                if (!d || !d.decision) return;
                jobs.push(api('/api/waqf-mark-review/decisions', {
                    method: 'POST',
                    body: JSON.stringify({
                        edition: state.edition,
                        page_number: parseInt(page, 10),
                        word_id: parseInt(wordId, 10),
                        decision: d.decision,
                        our_mark: d.our_mark,
                        correct_mark: d.correct_mark,
                        surah: d.surah,
                        ayah: d.ayah,
                        text: d.text || '',
                    }),
                }).catch(() => null));
            });
        });
        const missing = local._missing || {};
        Object.keys(missing).forEach((page) => {
            (missing[page] || []).forEach((n) => {
                if (!n || !n.text || n.id != null) return;
                jobs.push(api('/api/waqf-mark-review/notes', {
                    method: 'POST',
                    body: JSON.stringify({
                        edition: state.edition,
                        page_number: parseInt(page, 10),
                        note: n.text,
                    }),
                }).catch(() => null));
            });
        });
        if (jobs.length) await Promise.all(jobs);
    }

    async function loadServerDecisions() {
        if (!canSyncServer()) return;
        try {
            await migrateLocalToServer();
            const data = await api(
                `/api/waqf-mark-review/decisions?edition=${encodeURIComponent(state.edition)}`,
            );
            state.storage = data.storage || state.storage;
            mergeDecisions(data.decisions || {});
        } catch (err) {
            if (err.status === 401) {
                state.authenticated = false;
                renderAuth();
            }
        }
    }

    function renderLegend() {
        els.legend.innerHTML = symbols.map((s) => (
            `<span class="wmr-legend-chip">`
            + `<span class="wmr-legend-glyph">${escapeHtml(s.glyph || markGlyph(s.code))}</span>`
            + `<span>${escapeHtml(s.name)}</span>`
            + `</span>`
        )).join('');
    }

    async function loadProgress() {
        try {
            const data = await api(`/api/waqf-mark-review/progress?edition=${encodeURIComponent(state.edition)}`);
            state.reviewedPages = new Set(data.reviewed_pages || []);
            if (data.min_page) minPage = data.min_page;
            if (data.max_page) maxPage = data.max_page;
            if (data.storage) state.storage = data.storage;
        } catch {
            state.reviewedPages = new Set();
        }
        renderProgress();
    }

    function renderProgress() {
        const span = maxPage - minPage + 1;
        els.progress.textContent = `${toAr(state.reviewedPages.size)} / ${toAr(span)} صفحة`;
    }

    function ensurePageFont(fontName, usePageFont) {
        if (!usePageFont || !fontName) {
            els.pageFont.textContent = '';
            return;
        }
        const url = `/static/fonts/${fontName}.woff2`;
        els.pageFont.textContent = `
            @font-face {
                font-family: 'WmrShemrlyPage';
                src: url('${url}') format('woff2');
                font-display: swap;
            }
        `;
    }

    function renderMissing() {
        const notes = missingNotes();
        els.missingList.innerHTML = notes.map((n) => `<li>${escapeHtml(n.text)}</li>`).join('');
    }

    function wordHtml(item) {
        const useGlyph = state.usePageFont && item.text_glyph;
        const text = useGlyph ? item.text_glyph : (item.text || '');
        const cls = useGlyph ? 'wmr-word is-shemrly' : 'wmr-word';
        return `<span class="${cls}" dir="rtl">${escapeHtml(text)}</span>`;
    }

    function renderList() {
        if (!state.items.length) {
            els.list.innerHTML = '<p class="wmr-empty">لا علامات وقف مسجّلة عندنا في هذه الصفحة — راجع الناقص بالأسفل إن وُجدت.</p>';
            return;
        }
        els.list.innerHTML = state.items.map((item) => {
            const d = decisionFor(item);
            const decision = d ? d.decision : '';
            const glyph = item.mark_glyph || markGlyph(item.mark);
            const corrGlyph = d && d.correct_mark != null
                ? markGlyph(d.correct_mark)
                : '';
            const place = [
                item.line != null ? `سطر ${toAr(item.line)}` : '',
                item.word_on_line != null ? `كلمة ${toAr(item.word_on_line)}` : '',
            ].filter(Boolean).join(' · ');
            return `<article class="wmr-card" role="listitem" data-word-id="${item.word_id}" data-decision="${decision}">
                <div class="wmr-card-top">
                    <span class="wmr-ref">${toAr(item.surah)}:${toAr(item.ayah)}</span>
                    <span class="wmr-place">${place}</span>
                </div>
                <div class="wmr-word-row">
                    ${wordHtml(item)}
                    <span class="wmr-mark" title="${escapeHtml(item.mark)}"><span class="wmr-mark-glyph">${escapeHtml(glyph)}</span></span>
                </div>
                <div class="wmr-actions">
                    <button type="button" class="wmr-act${decision === 'ok' ? ' is-on' : ''}" data-decision="ok">صح</button>
                    <button type="button" class="wmr-act${decision === 'wrong' ? ' is-on' : ''}" data-decision="wrong">خطأ</button>
                    <button type="button" class="wmr-act${decision === 'extra' ? ' is-on' : ''}" data-decision="extra">زائد</button>
                </div>
                ${corrGlyph !== '' || (d && d.decision === 'wrong')
                    ? `<p class="wmr-correction">التصحيح: ${escapeHtml(corrGlyph || '∅')}</p>`
                    : ''}
            </article>`;
        }).join('');
    }

    async function loadPage() {
        els.meta.textContent = 'جارٍ التحميل…';
        els.list.innerHTML = '';
        try {
            const data = await api(
                `/api/waqf-mark-review/page/${state.page}?edition=${encodeURIComponent(state.edition)}`,
            );
            state.items = data.items || [];
            state.usePageFont = !!data.use_page_font;
            state.fontName = data.font_name || '';
            if (data.min_page) minPage = data.min_page;
            if (data.max_page) maxPage = data.max_page;
            ensurePageFont(state.fontName, state.usePageFont);
            const fontNote = state.usePageFont ? ' · خط الشمرلي' : ' · خط عثماني';
            const anchor = (data.anchor_surah && data.anchor_ayah)
                ? ` · ${toAr(data.anchor_surah)}:${toAr(data.anchor_ayah)}`
                : '';
            const reviewed = state.reviewedPages.has(state.page) ? ' · مُراجَعة' : '';
            els.meta.textContent = `${toAr(state.items.length)} علامة${anchor}${fontNote}${reviewed}`;
            renderList();
            renderMissing();
        } catch (err) {
            els.meta.textContent = 'تعذّر التحميل';
            els.list.innerHTML = `<p class="wmr-empty">${escapeHtml(err.message || 'خطأ')}</p>`;
        }
    }

    function openWrongSheet(item) {
        state.pendingWrong = item;
        const g = item.mark_glyph || markGlyph(item.mark);
        els.sheetWord.innerHTML = `${wordHtml(item)} <span class="wmr-mark"><span class="wmr-mark-glyph">${escapeHtml(g)}</span></span>`;
        els.glyphs.innerHTML = symbols.map((s) => (
            `<button type="button" class="wmr-glyph" data-code="${escapeHtml(s.code)}">`
            + `<span class="wmr-glyph-sym">${escapeHtml(s.glyph || markGlyph(s.code))}</span>`
            + `<span class="wmr-glyph-name">${escapeHtml(s.name)}</span>`
            + `</button>`
        )).join('') + (
            `<button type="button" class="wmr-glyph" data-code="">`
            + `<span class="wmr-glyph-sym">∅</span>`
            + `<span class="wmr-glyph-name">بلا علامة</span>`
            + `</button>`
        );
        els.sheet.hidden = false;
    }

    function closeSheet() {
        state.pendingWrong = null;
        els.sheet.hidden = true;
    }

    els.list.addEventListener('click', (ev) => {
        const btn = ev.target.closest('.wmr-act');
        if (!btn) return;
        const card = btn.closest('.wmr-card');
        if (!card) return;
        const wordId = parseInt(card.dataset.wordId, 10);
        const item = state.items.find((x) => x.word_id === wordId);
        if (!item) return;
        const kind = btn.dataset.decision;
        if (kind === 'wrong') {
            openWrongSheet(item);
            return;
        }
        setDecision(item, { decision: kind, our_mark: item.mark });
        renderList();
    });

    els.glyphs.addEventListener('click', (ev) => {
        const btn = ev.target.closest('.wmr-glyph');
        if (!btn || !state.pendingWrong) return;
        const item = state.pendingWrong;
        const code = btn.dataset.code || '';
        setDecision(item, {
            decision: 'wrong',
            our_mark: item.mark,
            correct_mark: code,
            word_id: item.word_id,
            surah: item.surah,
            ayah: item.ayah,
            text: item.text,
        });
        closeSheet();
        renderList();
    });

    els.sheetBackdrop.addEventListener('click', closeSheet);
    els.sheetCancel.addEventListener('click', closeSheet);

    els.missingSave.addEventListener('click', async () => {
        const text = (els.missingNote.value || '').trim();
        if (!text) return;
        await saveMissing(text);
        els.missingNote.value = '';
        toast('حُفظت ملاحظة الناقص');
    });

    els.done.addEventListener('click', async () => {
        try {
            await api('/api/waqf-mark-review/progress', {
                method: 'POST',
                body: JSON.stringify({
                    edition: state.edition,
                    page_number: state.page,
                    reviewed: true,
                }),
            });
            state.reviewedPages.add(state.page);
            renderProgress();
            toast('وُسِمت الصفحة كمُراجَعة');
            if (state.page < maxPage) {
                state.page += 1;
                setPageInput(state.page);
                localStorage.setItem('wmr_page_shemrly', String(state.page));
                await loadPage();
            }
        } catch (err) {
            state.reviewedPages.add(state.page);
            renderProgress();
            if (err.status === 401) {
                state.authenticated = false;
                renderAuth();
                showLogin(true);
            }
            toast(err.status === 401
                ? 'حُفظ محليًا — سجّل الدخول لاحقًا لمزامنة التقدّم'
                : (err.message || 'حُفظ محليًا'));
            if (state.page < maxPage) {
                state.page += 1;
                setPageInput(state.page);
                localStorage.setItem('wmr_page_shemrly', String(state.page));
                await loadPage();
            }
        }
    });

    els.exportBtn.addEventListener('click', () => {
        const blob = new Blob([JSON.stringify({
            edition: state.edition,
            exported_at: new Date().toISOString(),
            storage: state.storage,
            decisions: state.decisions,
            reviewed_pages: [...state.reviewedPages],
        }, null, 2)], { type: 'application/json' });
        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = `waqf-mark-review-${state.edition}.json`;
        a.click();
        URL.revokeObjectURL(a.href);
    });

    if (els.loginForm) {
        els.loginForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            const username = (els.loginUsername && els.loginUsername.value || '').trim();
            const password = (els.loginPassword && els.loginPassword.value) || '';
            if (els.loginSubmit) els.loginSubmit.disabled = true;
            if (els.loginError) els.loginError.hidden = true;
            try {
                const data = await api('/api/mushaf-editor/login', {
                    method: 'POST',
                    body: JSON.stringify({ username, password }),
                });
                state.authenticated = true;
                state.userName = (data.user && data.user.name) || username;
                hideLogin();
                renderAuth();
                await loadServerDecisions();
                await loadProgress();
                renderList();
                renderMissing();
                toast('تم الدخول — جارٍ المزامنة');
            } catch (err) {
                if (els.loginError) {
                    els.loginError.textContent = err.message === 'invalid credentials'
                        ? 'بيانات الدخول غير صحيحة'
                        : (err.message || 'تعذّر الدخول');
                    els.loginError.hidden = false;
                }
            } finally {
                if (els.loginSubmit) els.loginSubmit.disabled = false;
            }
        });
    }
    if (els.loginSkip) {
        els.loginSkip.addEventListener('click', () => {
            hideLogin();
            toast('متابعة محليًا — لن تُزامَن القرارات حتى تسجّل الدخول');
        });
    }

    function syncChrome() {
        els.edition.value = state.edition;
        setPageInput(state.page);
        localStorage.setItem('wmr_edition', state.edition);
        localStorage.setItem('wmr_page_shemrly', String(state.page));
    }

    els.edition.addEventListener('change', async () => {
        state.edition = els.edition.value;
        state.decisions = loadStore();
        syncChrome();
        await loadServerDecisions();
        await loadProgress();
        await loadPage();
    });

    els.page.addEventListener('change', async () => {
        state.page = readPageInput();
        syncChrome();
        await loadPage();
    });

    els.prev.addEventListener('click', async () => {
        await goPrev();
    });

    els.next.addEventListener('click', async () => {
        await goNext();
    });

    async function goPrev() {
        const next = clampPage(state.page - 1);
        if (next === state.page) return;
        state.page = next;
        syncChrome();
        await loadPage();
    }

    async function goNext() {
        const next = clampPage(state.page + 1);
        if (next === state.page) return;
        state.page = next;
        syncChrome();
        await loadPage();
    }

    /* Phone: swipe horizontally to change page.
       Arabic/RTL — finger right = next page, finger left = previous. */
    const swipe = { x: 0, y: 0, active: false, ignore: false };
    const SWIPE_MIN = 56;
    const SWIPE_RATIO = 1.35;

    function swipeTargetIgnored(target) {
        return !!target.closest(
            'button, a, input, select, textarea, .wmr-sheet, .wmr-footer, .wmr-actions, .wmr-glyphs, .wmr-login',
        );
    }

    document.addEventListener('touchstart', (ev) => {
        if (ev.touches.length !== 1) {
            swipe.active = false;
            return;
        }
        const t = ev.touches[0];
        swipe.x = t.clientX;
        swipe.y = t.clientY;
        swipe.active = true;
        swipe.ignore = swipeTargetIgnored(ev.target);
    }, { passive: true });

    document.addEventListener('touchend', async (ev) => {
        if (!swipe.active || swipe.ignore) {
            swipe.active = false;
            return;
        }
        swipe.active = false;
        if (els.sheet && !els.sheet.hidden) return;
        const t = ev.changedTouches[0];
        if (!t) return;
        const dx = t.clientX - swipe.x;
        const dy = t.clientY - swipe.y;
        if (Math.abs(dx) < SWIPE_MIN) return;
        if (Math.abs(dx) < Math.abs(dy) * SWIPE_RATIO) return;
        if (dx > 0) await goNext();
        else await goPrev();
    }, { passive: true });

    (async function init() {
        const known = editions.map((e) => e.id);
        if (!known.includes(state.edition) && known.length) {
            state.edition = known[0];
        }
        state.decisions = loadStore();
        state.page = clampPage(state.page);
        syncChrome();
        renderLegend();
        await checkAuth();
        await loadServerDecisions();
        await loadProgress();
        await loadPage();
    })();
})();
