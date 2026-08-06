(() => {
    const select = document.getElementById('azr-surah');
    const ayahBody = document.getElementById('azr-table-body');
    const markBody = document.getElementById('azr-mark-body');
    const ayahView = document.getElementById('azr-ayah-view');
    const markView = document.getElementById('azr-mark-view');
    const viewHint = document.getElementById('azr-view-hint');
    const viewButtons = [...document.querySelectorAll('[data-azr-view]')];
    const showEmpty = document.getElementById('azr-show-empty');
    const meta = document.getElementById('azr-meta');
    const title = document.getElementById('azr-surah-title');
    const printButton = document.getElementById('azr-print');
    const stats = {
        ayahs: document.getElementById('azr-stat-ayahs'),
        marked: document.getElementById('azr-stat-marked'),
        marks: document.getElementById('azr-stat-marks'),
        empty: document.getElementById('azr-stat-empty'),
    };
    const state = { payload: null, view: 'ayah' };
    let requestController = null;

    const esc = (value) => String(value ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');

    const number = (value) => Number(value || 0).toLocaleString('ar-EG');

    function renderMark(mark) {
        return `<span class="azr-mark-chip" title="${esc(mark.context || mark.word)}">`
            + `<span class="azr-mark-glyph">${esc(mark.glyph || '')}</span>`
            + `<b>${esc(mark.write || mark.mark || '')}</b>`
            + `<small>كلمة ${number(mark.word_index)}</small>`
            + `</span>`;
    }

    function renderWords(words) {
        return (words || []).map((word) => {
            const marked = Boolean(word.mark);
            const mark = marked
                ? `<span class="azr-inline-mark" aria-label="${esc(word.write || word.mark)}">${esc(word.glyph || '')}<small>${esc(word.write || word.mark)}</small></span>`
                : '';
            return `<span class="azr-word${marked ? ' is-marked' : ''}">`
                + `${esc(word.text)}${mark}</span>`;
        }).join(' ');
    }

    function renderAyahRows(rows) {
        if (!rows.length) {
            ayahBody.innerHTML = '<tr><td colspan="3" class="azr-empty">لا توجد آيات مطابقة لهذا الفلتر.</td></tr>';
            return;
        }

        ayahBody.innerHTML = rows.map((row) => {
            const marks = row.marks && row.marks.length
                ? row.marks.map(renderMark).join('')
                : '<span class="azr-no-mark">لا توجد علامة مسجلة</span>';
            return `<tr class="${row.mark_count ? '' : 'is-empty'}">`
                + `<th scope="row" class="azr-ayah-ref">${number(row.ayah)}</th>`
                + `<td class="azr-ayah-text">${renderWords(row.words)}</td>`
                + `<td class="azr-ayah-marks">${marks}</td>`
                + `</tr>`;
        }).join('');
    }

    function renderMarkLedger(payload) {
        const marks = (payload.rows || []).flatMap((row) => (
            (row.marks || []).map((mark) => ({ ...mark, ayah: row.ayah }))
        ));
        if (!marks.length) {
            markBody.innerHTML = '<tr><td colspan="4" class="azr-empty">لا توجد علامات مسجلة في هذه السورة.</td></tr>';
            return;
        }
        markBody.innerHTML = marks.map((mark) => (
            `<tr>`
            + `<th scope="row" class="azr-ayah-ref">${number(mark.ayah)}</th>`
            + `<td class="azr-ledger-word">${esc(mark.word)}<small>كلمة ${number(mark.word_index)}</small></td>`
            + `<td class="azr-context">${esc(mark.context || mark.word)}</td>`
            + `<td class="azr-ayah-marks">${renderMark(mark)}</td>`
            + `</tr>`
        )).join('');
    }

    function renderVisible() {
        if (!state.payload) return;
        const payload = state.payload;
        const allRows = payload.rows || [];
        const rows = showEmpty?.checked
            ? allRows
            : allRows.filter((row) => row.mark_count > 0);
        const filterText = state.view === 'ayah' && !showEmpty?.checked
            ? ` · عرض ${number(rows.length)} آية`
            : '';
        meta.textContent = `السورة ${number(payload.surah)} · ${number(payload.ayah_count)} آية · `
            + `${number(payload.mark_count)} علامة في ${number(payload.ayahs_with_marks)} آية${filterText}`;
        renderAyahRows(rows);
        renderMarkLedger(payload);
    }

    function setView(view) {
        state.view = view === 'marks' ? 'marks' : 'ayah';
        const marks = state.view === 'marks';
        if (ayahView) ayahView.hidden = marks;
        if (markView) markView.hidden = !marks;
        if (showEmpty) showEmpty.disabled = marks;
        viewButtons.forEach((button) => {
            const active = button.dataset.azrView === state.view;
            button.classList.toggle('is-active', active);
            button.setAttribute('aria-pressed', active ? 'true' : 'false');
        });
        if (viewHint) {
            viewHint.textContent = marks
                ? 'صف واحد لكل علامة مسجلة — مناسب للمراجعة السريعة وتسجيل موضع الكلمة.'
                : 'كل آية في صف مستقل، والعلامات ملوّنة داخل الكلمات.';
        }
    }

    function render(payload) {
        state.payload = payload;
        title.textContent = payload.surah_name || `رقم ${payload.surah}`;
        if (stats.ayahs) stats.ayahs.textContent = number(payload.ayah_count);
        if (stats.marked) stats.marked.textContent = number(payload.ayahs_with_marks);
        if (stats.marks) stats.marks.textContent = number(payload.mark_count);
        if (stats.empty) stats.empty.textContent = number(payload.ayah_count - payload.ayahs_with_marks);
        renderVisible();
        setView(state.view);
    }

    async function loadSurah(surah) {
        if (requestController) requestController.abort();
        requestController = new AbortController();
        state.payload = null;
        ayahBody.innerHTML = '<tr><td colspan="3" class="azr-empty">جارٍ تحميل السورة…</td></tr>';
        markBody.innerHTML = '<tr><td colspan="4" class="azr-empty">جارٍ تحميل السورة…</td></tr>';
        meta.textContent = 'جارٍ تحميل البيانات…';
        Object.values(stats).forEach((element) => {
            if (element) element.textContent = '—';
        });
        try {
            const response = await fetch(`/api/azhar-waqf-review/surah/${encodeURIComponent(surah)}`, {
                signal: requestController.signal,
                headers: { Accept: 'application/json' },
            });
            const payload = await response.json();
            if (!response.ok) throw new Error(payload.error || 'تعذّر تحميل السورة');
            render(payload);
            const url = new URL(window.location.href);
            url.searchParams.set('surah', surah);
            window.history.replaceState({}, '', url);
        } catch (error) {
            if (error.name === 'AbortError') return;
            meta.textContent = 'تعذّر تحميل البيانات';
            ayahBody.innerHTML = `<tr><td colspan="3" class="azr-empty azr-error">${esc(error.message)}</td></tr>`;
            markBody.innerHTML = `<tr><td colspan="4" class="azr-empty azr-error">${esc(error.message)}</td></tr>`;
        }
    }

    select?.addEventListener('change', () => loadSurah(select.value));
    printButton?.addEventListener('click', () => window.print());
    viewButtons.forEach((button) => {
        button.addEventListener('click', () => setView(button.dataset.azrView));
    });
    showEmpty?.addEventListener('change', renderVisible);

    const initial = new URLSearchParams(window.location.search).get('surah');
    if (initial && [...select.options].some((option) => option.value === initial)) {
        select.value = initial;
    }
    if (select?.value) loadSurah(select.value);
})();
