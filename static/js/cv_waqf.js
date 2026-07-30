(() => {
    const body = document.body;
    const editions = JSON.parse(body.dataset.editions || '[]');
    const symbols = JSON.parse(body.dataset.symbols || '[]');

    const els = {
        edition: document.getElementById('cvw-edition'),
        page: document.getElementById('cvw-page'),
        prev: document.getElementById('cvw-prev'),
        next: document.getElementById('cvw-next'),
        conf: document.getElementById('cvw-conf'),
        confLabel: document.getElementById('cvw-conf-label'),
        meta: document.getElementById('cvw-meta'),
        img: document.getElementById('cvw-img'),
        canvas: document.getElementById('cvw-canvas'),
        wrap: document.getElementById('cvw-wrap'),
        empty: document.getElementById('cvw-empty'),
        list: document.getElementById('cvw-list'),
        palette: document.getElementById('cvw-palette'),
        detectToggles: document.getElementById('cvw-detect-toggles'),
        labelCount: document.getElementById('cvw-label-count'),
        undo: document.getElementById('cvw-undo'),
        showCv: document.getElementById('cvw-show-cv'),
        showDb: document.getElementById('cvw-show-db'),
        showMissing: document.getElementById('cvw-show-missing'),
        showExtra: document.getElementById('cvw-show-extra'),
        modeLabel: document.getElementById('cvw-mode-label'),
        modeDetect: document.getElementById('cvw-mode-detect'),
        saveBar: document.getElementById('cvw-save-bar'),
        saveHint: document.getElementById('cvw-save-hint'),
        saveBtn: document.getElementById('cvw-save'),
        cancelBtn: document.getElementById('cvw-cancel'),
        saveSym: document.getElementById('cvw-save-sym'),
        fab: document.getElementById('cvw-fab'),
        fabSave: document.getElementById('cvw-fab-save'),
        fabCancel: document.getElementById('cvw-fab-cancel'),
    };

    const state = {
        edition: body.dataset.defaultEdition || 'الشمرلي',
        slug: 'shamarly',
        page: Number(body.dataset.minPage || 2),
        minPage: Number(body.dataset.minPage || 2),
        maxPage: Number(body.dataset.maxPage || 522),
        minConf: 0.55,
        mode: 'label', // label | detect
        payload: null, // detect payload
        labels: [], // hand labels for page
        selectedSymbol: 'ج',
        draft: null, // {x0,y0,x1,y1} image pixels
        dragging: false,
        dragStart: null,
        activeId: null,
        loading: false,
        loadGen: 0, // bumps on every navigation; stale loads abort
        saving: false,
        naturalW: 0,
        naturalH: 0,
    };

    const COLORS = {
        match: '#1f6b45',
        wrong: '#8a3b2a',
        extra: '#2a5f8a',
        missing: '#8a6a1f',
        db: 'rgba(47, 93, 74, 0.45)',
        label: '#c45c26',
        draft: '#2f5d4a',
    };

    const TAG_AR = {
        match: 'مطابق', wrong: 'مختلف', extra: 'زائد', missing: 'ناقص',
    };

    const GLYPH = Object.fromEntries(
        symbols.map((s) => [s.code, s.glyph]).concat([['none', '∅']])
    );

    function toAr(n) {
        return String(n).replace(/\d/g, (d) => '٠١٢٣٤٥٦٧٨٩'[d]);
    }

    function editionMeta() {
        const opt = els.edition.selectedOptions[0];
        return {
            id: els.edition.value,
            slug: opt?.dataset.slug || 'shamarly',
            min: Number(opt?.dataset.min || 2),
            max: Number(opt?.dataset.max || 522),
        };
    }

    function syncEditionBounds() {
        const meta = editionMeta();
        state.edition = meta.id;
        state.slug = meta.slug;
        state.minPage = meta.min;
        state.maxPage = meta.max;
        if (state.page < meta.min) state.page = meta.min;
        if (state.page > meta.max) state.page = meta.max;
        els.page.value = String(state.page);
    }

    function setMeta(text) {
        els.meta.textContent = text;
    }

    function setMode(mode) {
        state.mode = mode;
        els.modeLabel.classList.toggle('is-active', mode === 'label');
        els.modeDetect.classList.toggle('is-active', mode === 'detect');
        els.palette.hidden = mode !== 'label';
        if (els.saveBar) els.saveBar.hidden = mode !== 'label';
        els.detectToggles.hidden = mode !== 'detect';
        els.wrap.classList.toggle('is-label', mode === 'label');
        state.draft = null;
        syncSaveUi();
        loadPage();
    }

    function syncSaveUi() {
        const ready = !!(state.mode === 'label' && state.draft);
        const glyph = GLYPH[state.selectedSymbol] || state.selectedSymbol;
        if (els.saveSym) els.saveSym.textContent = glyph;
        if (els.saveBtn) els.saveBtn.disabled = !ready;
        if (els.cancelBtn) els.cancelBtn.disabled = !ready;
        if (els.saveBar) els.saveBar.classList.toggle('is-ready', ready);
        if (els.saveHint) {
            els.saveHint.textContent = ready
                ? `مربع جاهز — اضغط حفظ لنوع «${glyph}»`
                : 'ارسم مربعاً حول العلامة، ثم اضغط حفظ';
        }
        if (els.fab) {
            els.fab.hidden = !(state.mode === 'label' && ready);
            if (els.fabSave) {
                els.fabSave.textContent = `حفظ «${glyph}»`;
                els.fabSave.disabled = !ready;
            }
            if (els.fabCancel) els.fabCancel.disabled = !ready;
        }
    }

    function clearDraft() {
        state.draft = null;
        paint();
        syncSaveUi();
        setMeta('أُلغي المربع — ارسم من جديد ثم احفظ');
    }

    function selectSymbol(sym) {
        state.selectedSymbol = sym;
        for (const b of els.palette.querySelectorAll('.cvw-sym-btn')) {
            b.classList.toggle('is-active', b.dataset.symbol === sym);
        }
        syncSaveUi();
    }

    function canvasToImage(cx, cy) {
        // Map from the visible page (wrap / img), not the canvas element —
        // canvas has pointer-events:none and may not match hit-testing.
        const rect = els.wrap.getBoundingClientRect();
        const w = Math.max(1, rect.width);
        const h = Math.max(1, rect.height);
        const x = Math.round(((cx - rect.left) / w) * state.naturalW);
        const y = Math.round(((cy - rect.top) / h) * state.naturalH);
        return {
            x: Math.max(0, Math.min(state.naturalW, x)),
            y: Math.max(0, Math.min(state.naturalH, y)),
        };
    }

    async function loadPage() {
        const gen = ++state.loadGen;
        const page = state.page;
        const edition = state.edition;
        const mode = state.mode;
        state.loading = true;
        state.draft = null;
        state.activeId = null;
        syncSaveUi();
        els.empty.hidden = false;
        els.empty.textContent = 'جاري التحميل…';
        try {
            if (mode === 'label') {
                setMeta('تحميل الصفحة والتسميات…');
                await loadImageFromUrl(imageUrlFor(page), gen);
                if (gen !== state.loadGen) return;
                const packed = await fetchLabels(edition, page);
                if (gen !== state.loadGen) return;
                state.labels = packed.labels;
                paint();
                renderLabelList();
                setMeta(
                    `صفحة ${toAr(page)} · ${toAr(state.labels.length)} تسمية محفوظة · اسحب مربعاً ثم اختر الرمز`
                    + (packed.cloud ? ' · سحابة' : '')
                );
            } else {
                setMeta('جاري الكشف…');
                const url = `/api/cv-waqf/page/${page}`
                    + `?edition=${encodeURIComponent(edition)}`
                    + `&min_conf=${state.minConf}`;
                const res = await fetch(url, { credentials: 'same-origin' });
                const data = await res.json();
                if (!res.ok) throw new Error(data.error || res.statusText);
                if (gen !== state.loadGen) return;
                state.payload = data;
                state.minPage = data.min_page;
                state.maxPage = data.max_page;
                await loadImageFromUrl(data.image_url, gen);
                if (gen !== state.loadGen) return;
                paint();
                renderDetectList(data);
                const s = data.summary || {};
                setMeta(
                    `صفحة ${toAr(data.page)} · CV ${toAr(s.cv || 0)} · DB ${toAr(s.db || 0)}`
                    + ` · مطابق ${toAr(s.match || 0)} · زائد ${toAr(s.extra || 0)}`
                );
            }
            if (gen !== state.loadGen) return;
            els.empty.hidden = true;
            updateUrl();
        } catch (err) {
            if (gen !== state.loadGen) return;
            els.empty.hidden = false;
            els.empty.textContent = 'تعذّر التحميل';
            setMeta(String(err.message || err));
            console.error(err);
        } finally {
            if (gen === state.loadGen) state.loading = false;
        }
    }

    function imageUrlFor(page) {
        return `/api/cv-waqf/image/${state.slug}/${page}.jpg?t=${Date.now()}`;
    }

    function loadImageFromUrl(url, gen) {
        return new Promise((resolve, reject) => {
            const img = els.img;
            const onLoad = () => {
                cleanup();
                if (gen != null && gen !== state.loadGen) {
                    resolve(false);
                    return;
                }
                img.hidden = false;
                state.naturalW = img.naturalWidth;
                state.naturalH = img.naturalHeight;
                resizeCanvas();
                resolve(true);
            };
            const onError = () => {
                cleanup();
                reject(new Error('تعذّر تحميل صورة الصفحة'));
            };
            const cleanup = () => {
                img.removeEventListener('load', onLoad);
                img.removeEventListener('error', onError);
            };
            img.addEventListener('load', onLoad);
            img.addEventListener('error', onError);
            img.src = url.includes('?') ? url : `${url}?t=${Date.now()}`;
        });
    }

    async function fetchLabels(edition, page) {
        const url = `/api/cv-waqf/labels?edition=${encodeURIComponent(edition)}&page=${page}`;
        const res = await fetch(url, { credentials: 'same-origin' });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || res.statusText);
        return { labels: data.labels || [], cloud: !!data.cloud };
    }

    function resizeCanvas() {
        els.canvas.width = state.naturalW;
        els.canvas.height = state.naturalH;
    }

    function paint() {
        const ctx = els.canvas.getContext('2d');
        if (!ctx || !state.naturalW) return;
        ctx.clearRect(0, 0, els.canvas.width, els.canvas.height);

        if (state.mode === 'detect' && state.payload) {
            const data = state.payload;
            if (els.showDb.checked) {
                for (const m of data.db_marks || []) {
                    strokeBox(ctx, m.seat || m.box, COLORS.db, 1);
                }
            }
            if (els.showCv.checked) {
                for (const m of data.cv_marks || []) {
                    if (m.vs_db === 'extra' && !els.showExtra.checked) continue;
                    strokeBox(ctx, m.box, COLORS[m.vs_db] || COLORS.extra, 2);
                }
            }
            if (els.showMissing.checked) {
                for (const m of data.missing || []) {
                    strokeBox(ctx, m.seat || m.box, COLORS.missing, 2, true);
                }
            }
        }

        // Hand labels always visible in label mode; also overlay in detect.
        const lw = Math.max(2, Math.round(state.naturalW / 600));
        for (const lab of state.labels) {
            const active = lab.id === state.activeId;
            strokeBox(ctx, lab.box, COLORS.label, active ? lw + 1 : lw);
            labelText(ctx, lab.box, GLYPH[lab.symbol] || lab.symbol, COLORS.label);
        }

        if (state.draft) {
            // Thicker dash so the draft stays visible on high-res page bitmaps.
            const scale = Math.max(2, Math.round(state.naturalW / 500));
            strokeBox(ctx, [
                state.draft.x0, state.draft.y0, state.draft.x1, state.draft.y1,
            ], COLORS.draft, scale, true);
        }
    }

    function strokeBox(ctx, box, color, width, dashed) {
        if (!box || box.length < 4) return;
        let [x0, y0, x1, y1] = box;
        if (x1 < x0) [x0, x1] = [x1, x0];
        if (y1 < y0) [y0, y1] = [y1, y0];
        ctx.save();
        ctx.strokeStyle = color;
        ctx.lineWidth = width;
        if (dashed) ctx.setLineDash([6, 4]);
        ctx.strokeRect(x0, y0, Math.max(2, x1 - x0), Math.max(2, y1 - y0));
        ctx.restore();
    }

    function labelText(ctx, box, text, color) {
        if (!box || !text) return;
        ctx.save();
        ctx.fillStyle = color;
        ctx.font = 'bold 18px serif';
        ctx.fillText(text, box[0], Math.max(16, box[1] - 4));
        ctx.restore();
    }

    function renderLabelList() {
        els.list.innerHTML = '';
        els.labelCount.textContent = `${toAr(state.labels.length)} تسمية`;
        els.undo.hidden = state.labels.length === 0;
        if (!state.labels.length) {
            els.list.innerHTML = '<li class="cvw-item"><div class="body"><div class="txt">لا تسميات بعد — اسحب مربعاً على علامة</div></div></li>';
            return;
        }
        for (const lab of [...state.labels].reverse()) {
            const li = document.createElement('li');
            li.className = 'cvw-item' + (lab.id === state.activeId ? ' is-active' : '');
            li.innerHTML = `
                <div class="glyph">${GLYPH[lab.symbol] || lab.symbol}</div>
                <div class="body">
                    <div class="ref">${lab.symbol} · صفحة ${toAr(lab.page)}</div>
                    <div class="txt">${Math.round(lab.box[2] - lab.box[0])}×${Math.round(lab.box[3] - lab.box[1])}</div>
                </div>
                <button type="button" class="cvw-del" data-id="${lab.id}" title="حذف">×</button>
            `;
            li.addEventListener('click', (e) => {
                if (e.target.closest('.cvw-del')) return;
                state.activeId = lab.id;
                paint();
                renderLabelList();
            });
            li.querySelector('.cvw-del').addEventListener('click', async (e) => {
                e.stopPropagation();
                await deleteLabel(lab.id);
            });
            els.list.appendChild(li);
        }
    }

    function renderDetectList(data) {
        els.list.innerHTML = '';
        const rows = [];
        for (const m of data.cv_marks || []) {
            if (m.vs_db === 'extra' && !els.showExtra.checked) continue;
            if (!els.showCv.checked) continue;
            rows.push(m);
        }
        if (els.showMissing.checked) rows.push(...(data.missing || []));
        els.labelCount.textContent = `${toAr(rows.length)} كشف`;
        els.undo.hidden = true;
        for (const m of rows) {
            const li = document.createElement('li');
            li.className = 'cvw-item';
            li.innerHTML = `
                <div class="glyph">${m.glyph || m.symbol || ''}</div>
                <div class="body">
                    <div class="ref">${toAr(m.surah)}:${toAr(m.ayah)}</div>
                    <div class="txt">${m.text || ''}</div>
                </div>
                <span class="tag ${m.vs_db || ''}">${TAG_AR[m.vs_db] || ''}</span>
            `;
            els.list.appendChild(li);
        }
    }

    async function saveDraft(symbol) {
        if (state.saving) return;
        if (!state.draft) {
            setMeta('ارسم مربعاً أولاً حول العلامة');
            return;
        }
        let { x0, y0, x1, y1 } = state.draft;
        if (x1 < x0) [x0, x1] = [x1, x0];
        if (y1 < y0) [y0, y1] = [y1, y0];
        if (x1 - x0 < 4 || y1 - y0 < 4) {
            setMeta('المربع صغير جداً');
            return;
        }
        state.saving = true;
        if (els.saveBtn) els.saveBtn.disabled = true;
        if (els.fabSave) els.fabSave.disabled = true;
        setMeta('جاري الحفظ…');
        try {
            const res = await fetch('/api/cv-waqf/labels', {
                method: 'POST',
                credentials: 'same-origin',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    edition: state.edition,
                    page: state.page,
                    symbol,
                    box: [x0, y0, x1, y1],
                }),
            });
            let data = {};
            try {
                data = await res.json();
            } catch (_) {
                data = {};
            }
            if (!res.ok) {
                setMeta(data.error || `فشل الحفظ (${res.status})`);
                return;
            }
            state.labels.push(data.label);
            state.draft = null;
            state.activeId = data.label.id;
            paint();
            renderLabelList();
            setMeta(`حُفظت «${symbol}» · المجموع ${toAr(state.labels.length)} على هذه الصفحة`);
        } catch (err) {
            console.error(err);
            setMeta(`فشل الحفظ: ${err.message || err}`);
        } finally {
            state.saving = false;
            syncSaveUi();
        }
    }

    async function deleteLabel(id) {
        const res = await fetch(`/api/cv-waqf/labels/${encodeURIComponent(id)}`, {
            method: 'DELETE',
            credentials: 'same-origin',
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
            setMeta(data.error || 'فشل الحذف');
            return;
        }
        state.labels = state.labels.filter((l) => l.id !== id);
        if (state.activeId === id) state.activeId = null;
        paint();
        renderLabelList();
        setMeta('حُذفت التسمية');
    }

    function updateUrl() {
        const u = new URL(location.href);
        u.searchParams.set('page', String(state.page));
        u.searchParams.set('edition', state.edition);
        u.searchParams.set('mode', state.mode);
        history.replaceState(null, '', u);
    }

    // —— pointer draw on the wrap (canvas is overlay-only) ——
    function onPointerDown(e) {
        if (state.mode !== 'label') return;
        if (e.button != null && e.button !== 0) return;
        if (!state.naturalW) return;
        e.preventDefault();
        els.wrap.setPointerCapture(e.pointerId);
        const p = canvasToImage(e.clientX, e.clientY);
        state.dragging = true;
        state.dragStart = p;
        state.draft = { x0: p.x, y0: p.y, x1: p.x, y1: p.y };
        paint();
    }
    function onPointerMove(e) {
        if (!state.dragging || !state.dragStart) return;
        const p = canvasToImage(e.clientX, e.clientY);
        state.draft = {
            x0: state.dragStart.x,
            y0: state.dragStart.y,
            x1: p.x,
            y1: p.y,
        };
        paint();
    }
    function onPointerUp(e) {
        if (!state.dragging) return;
        state.dragging = false;
        state.dragStart = null;
        try {
            if (e && e.pointerId != null && els.wrap.hasPointerCapture?.(e.pointerId)) {
                els.wrap.releasePointerCapture(e.pointerId);
            }
        } catch (_) { /* ignore */ }
        if (state.draft) {
            const w = Math.abs(state.draft.x1 - state.draft.x0);
            const h = Math.abs(state.draft.y1 - state.draft.y0);
            if (w < 4 || h < 4) {
                state.draft = null;
                paint();
                syncSaveUi();
                setMeta('المربع صغير جداً — اسحب حول العلامة');
                return;
            }
            syncSaveUi();
            setMeta('اختر النوع من الشريط ثم اضغط حفظ');
        }
    }
    els.wrap.addEventListener('pointerdown', onPointerDown);
    els.wrap.addEventListener('pointermove', onPointerMove);
    els.wrap.addEventListener('pointerup', onPointerUp);
    els.wrap.addEventListener('pointercancel', onPointerUp);

    // palette: select type only (Save button commits — better for iPad)
    els.palette.addEventListener('click', (e) => {
        const btn = e.target.closest('.cvw-sym-btn');
        if (!btn) return;
        selectSymbol(btn.dataset.symbol);
        if (state.draft) {
            setMeta(`النوع «${GLYPH[state.selectedSymbol] || state.selectedSymbol}» — اضغط حفظ`);
        }
    });

    function onSaveClick() {
        if (!state.draft) {
            setMeta('ارسم مربعاً أولاً حول العلامة');
            return;
        }
        saveDraft(state.selectedSymbol);
    }
    els.saveBtn?.addEventListener('click', onSaveClick);
    els.fabSave?.addEventListener('click', onSaveClick);
    els.cancelBtn?.addEventListener('click', clearDraft);
    els.fabCancel?.addEventListener('click', clearDraft);

    // keyboard shortcuts for symbols
    const KEY_MAP = {
        m: 'م', ق: 'ق', 'q': 'ق', ص: 'ص', s: 'ص', ج: 'ج', j: 'ج',
        l: 'لا', ع: 'ع', a: 'ع', k: 'س', Escape: '__cancel', Backspace: '__undo',
        Enter: '__save',
    };
    window.addEventListener('keydown', (e) => {
        if (state.mode !== 'label') return;
        if (e.target.matches('input, select, textarea')) return;
        const mapped = KEY_MAP[e.key] || KEY_MAP[e.key.toLowerCase()];
        if (!mapped) return;
        e.preventDefault();
        if (mapped === '__cancel') {
            clearDraft();
            return;
        }
        if (mapped === '__undo') {
            if (state.labels.length) deleteLabel(state.labels[state.labels.length - 1].id);
            return;
        }
        if (mapped === '__save') {
            if (state.draft) saveDraft(state.selectedSymbol);
            return;
        }
        selectSymbol(mapped);
        if (state.draft) {
            setMeta(`النوع «${GLYPH[mapped] || mapped}» — اضغط حفظ أو Enter`);
        }
    });

    els.modeLabel.addEventListener('click', () => setMode('label'));
    els.modeDetect.addEventListener('click', () => setMode('detect'));
    els.undo.addEventListener('click', () => {
        if (state.labels.length) deleteLabel(state.labels[state.labels.length - 1].id);
    });

    els.edition.addEventListener('change', () => {
        syncEditionBounds();
        loadPage();
    });
    els.prev.addEventListener('click', () => {
        state.page = Math.max(state.minPage, state.page - 1);
        els.page.value = String(state.page);
        loadPage();
    });
    els.next.addEventListener('click', () => {
        state.page = Math.min(state.maxPage, state.page + 1);
        els.page.value = String(state.page);
        loadPage();
    });
    els.page.addEventListener('change', () => {
        const raw = (els.page.value || '').replace(/[٠-٩]/g, (d) => '٠١٢٣٤٥٦٧٨٩'.indexOf(d));
        const n = parseInt(raw, 10);
        if (Number.isFinite(n)) {
            state.page = Math.max(state.minPage, Math.min(state.maxPage, n));
            els.page.value = String(state.page);
            loadPage();
        }
    });
    if (els.conf) {
        els.conf.addEventListener('input', () => {
            state.minConf = Number(els.conf.value);
            els.confLabel.textContent = state.minConf.toFixed(2);
        });
        els.conf.addEventListener('change', () => {
            if (state.mode === 'detect') loadPage();
        });
    }
    for (const el of [els.showCv, els.showDb, els.showMissing, els.showExtra]) {
        el?.addEventListener('change', () => paint());
    }
    window.addEventListener('resize', () => {
        if (state.naturalW) {
            resizeCanvas();
            paint();
        }
    });

    // init
    if (editions.length) els.edition.value = state.edition;
    const params = new URLSearchParams(location.search);
    if (params.get('edition') && editions.some((e) => e.id === params.get('edition'))) {
        state.edition = params.get('edition');
        els.edition.value = state.edition;
    }
    syncEditionBounds();
    if (params.get('page')) {
        const p = parseInt(params.get('page'), 10);
        if (Number.isFinite(p)) state.page = p;
    }
    els.page.value = String(state.page);
    const startMode = params.get('mode') === 'detect' ? 'detect' : 'label';
    // activate default symbol button
    const defBtn = els.palette.querySelector(`[data-symbol="${state.selectedSymbol}"]`);
    if (defBtn) defBtn.classList.add('is-active');
    setMode(startMode);
})();
