(() => {
    'use strict';
    const $ = id => document.getElementById(id);
    const requestedBook = new URLSearchParams(location.search).get('book');
    const state = { page: 1, pages: 1, summary: null, source: ['muktafa', 'manar'].includes(requestedBook) ? requestedBook : 'muktafa' };
    const api = (url, opts) => window.AtharApi.json(url, opts);

    function escapeHtml(value) {
        return String(value == null ? '' : value).replace(/[&<>'"]/g, c => ({
            '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'
        })[c]);
    }
    function toast(message, error = false) {
        const el = $('cr-toast');
        el.textContent = message; el.hidden = false; el.classList.toggle('cr-error', error);
        clearTimeout(toast.timer); toast.timer = setTimeout(() => { el.hidden = true; }, 2800);
    }
    function metric(value, label, detail = '') {
        return `<div class="cr-metric"><strong>${escapeHtml(value)}</strong><span>${label}</span><small>${escapeHtml(detail)}</small></div>`;
    }
    async function loadSummary() {
        const source = state.source; const s = await api(`/api/classical-review/${source}/summary`);
        if (source !== state.source) return; state.summary = s;
        const isManar = source === 'manar';
        $('cr-title').textContent = isManar ? 'منار الهدى للأشموني' : 'المكتفى لأبي عمرو الداني';
        $('cr-subtitle').textContent = isManar
            ? 'راجع الأحكام التي لم يجد فحص التتبّع الآلي دليلًا قريبًا لها، ثم أكّد بقاءها أو استبعدها.'
            : 'راجع المواضع غير اليقينية، وقارن نص الكتاب بموضعه في القرآن، ثم اقبل الحكم أو استبعده.';
        $('cr-export').href = `/api/classical-review/${source}/export`;
        $('cr-release-title').textContent = isManar ? 'هل يبقى منار الهدى منشورًا؟' : 'هل يُضاف المكتفى إلى التطبيق؟';
        $('cr-release-copy').textContent = isManar
            ? 'منار منشور حاليًا. لا يمكن تثبيت قرار الإبقاء حتى تُراجع الأحكام الاحترازية؛ والاستبعاد النهائي يزيل الكتاب من العرض من دون حذف قاعدة المصدر.'
            : 'لا يمكن اعتماد الكتاب حتى يُتخذ قرار في جميع المواضع الـ167 غير اليقينية. الاعتماد يُسجَّل منفصلًا ولا يمحو نص المصدر.';
        $('cr-reject-book').textContent = isManar ? 'إزالة الكتاب من العرض' : 'عدم إضافة الكتاب';
        $('cr-add-book').textContent = isManar ? 'اعتماد وإبقاء الكتاب' : 'اعتماد وإضافة الكتاب';
        $('cr-metrics').innerHTML = isManar ? [
            metric(`${s.confident_rate}%`, 'محاذاة مقبولة آليًا', `${s.confident.toLocaleString('ar')} حكمًا`),
            metric(`${s.source_traceable_rate}%`, 'دليل مصدر آلي', `${s.source_traceable.toLocaleString('ar')} من ${s.total_extracted.toLocaleString('ar')}`),
            metric(`${s.quran_aligned_rate}%`, 'صحة موضع القرآن', `${s.quran_aligned.toLocaleString('ar')} حكمًا`),
            metric(s.explicit_missing.toLocaleString('ar'), 'أحكام صريحة مفقودة', `${s.explicit_expected.toLocaleString('ar')} مفتاحًا صريحًا مغطى`),
            metric(s.review.pending.toLocaleString('ar'), 'فحص بشري احترازي', `${s.review.approved.toLocaleString('ar')} مؤكد · ${s.review.rejected.toLocaleString('ar')} مستبعد`),
        ].join('') : [
            metric(`${s.confident_rate}%`, 'استخراج عالي الثقة', `${s.confident.toLocaleString('ar')} من ${s.total_extracted.toLocaleString('ar')}`),
            metric(`${s.matched_rate}%`, 'له موضع قرآني', `${s.matched.toLocaleString('ar')} مطابق · ${s.unmatched.toLocaleString('ar')} بلا موضع`),
            metric(`${s.source_traceable_rate}%`, 'قابل للتتبع في المصدر', `${s.source_traceable.toLocaleString('ar')} حكمًا عالي الثقة`),
            metric(`${s.quran_aligned_rate}%`, 'صحة محاذاة عالي الثقة', `${s.exact_or_prefix.toLocaleString('ar')} مباشر · ${s.orthographic_fuzzy.toLocaleString('ar')} فرق رسم`),
            metric(s.review.pending.toLocaleString('ar'), 'بانتظار المراجع', `${s.review.approved.toLocaleString('ar')} مقبول · ${s.review.rejected.toLocaleString('ar')} مستبعد`),
        ].join('');
        $('cr-caveat').hidden = false; $('cr-caveat').textContent = s.claim_limit;
        const bd = s.book_decision || {};
        $('cr-book-note').value = bd.reviewer_note || '';
        $('cr-book-state').textContent = bd.decision === 'add' ? (isManar ? 'الحالة: مؤكد للإبقاء' : 'الحالة: معتمد للإضافة') : bd.decision === 'reject' ? (isManar ? 'الحالة: مقرر إزالته من العرض' : 'الحالة: غير معتمد') : (isManar ? 'الحالة: منشور، والمراجعة النهائية جارية' : 'الحالة: القرار النهائي لم يُتخذ');
        $('cr-add-book').disabled = s.review.pending > 0;
    }
    function renderWords(item) {
        if (!item.verse_words.length) return '<div class="cr-empty">أدخل رقم الآية ثم حمّل كلماتها واختر كلمة الوقف.</div>';
        return `<div class="cr-verse" data-role="verse">${item.verse_words.map((word, i) =>
            `<button type="button" class="cr-word ${i === item.effective_wpos ? 'cr-stop' : ''}" data-wpos="${i}">${escapeHtml(word)}</button>`).join('')}</div>`;
    }
    function card(item) {
        const d = item.review || {}; const ayah = item.effective_ayah == null ? '' : item.effective_ayah;
        const status = d.decision || 'pending';
        return `<article class="cr-card" data-id="${item.id}" data-surah="${item.surah}">
          <div class="cr-card-main">
            <div class="cr-card-head"><div class="cr-badges">
              <span class="cr-badge">سورة ${item.surah}</span><span class="cr-badge">السجل ${item.id}</span>
              <span class="cr-badge ${item.alignment === 'unmatched' ? 'cr-unmatched' : ''}">${item.alignment === 'matched' ? `الآية ${item.ayah} · الكلمة ${item.wpos + 1}` : 'بلا محاذاة'}</span>
            </div><span class="cr-grade">${escapeHtml(item.grade_raw)}</span></div>
            <p class="cr-quote">${escapeHtml(item.quote)}</p>
            <p class="cr-note">${escapeHtml(item.note || 'لا توجد علّة منقولة في هذا السجل.')}</p>
            ${renderWords(item)}
            <div class="cr-correction"><label>رقم الآية<input data-role="ayah" type="number" min="1" value="${ayah}"></label>
              <input data-role="wpos" type="hidden" value="${item.effective_wpos == null ? '' : item.effective_wpos}">
              <button type="button" data-action="load-verse">تحميل الآية / تغيير الموضع</button></div>
            <textarea class="cr-review-note" data-role="note" placeholder="سبب القبول أو الاستبعاد">${escapeHtml(d.reviewer_note || '')}</textarea>
            <div class="cr-actions"><button class="cr-approve" data-action="approve" type="button">قبول وإضافة</button>
              <button class="cr-reject" data-action="reject" type="button">استبعاد</button>
              ${status !== 'pending' ? '<button class="cr-reset" data-action="pending" type="button">إلغاء القرار</button>' : ''}</div>
          </div>
          <aside class="cr-card-source"><p class="cr-source-label">${escapeHtml(item.source_locator)}</p><p class="cr-source-text">${escapeHtml(item.source_context)}</p></aside>
        </article>`;
    }
    async function loadItems() {
        const source = state.source;
        $('cr-list').innerHTML = '<div class="cr-skeleton">جارٍ تحميل مواضع المراجعة…</div>';
        const qs = new URLSearchParams({ status: $('cr-status').value, alignment: $('cr-alignment').value, page: state.page, limit: 12 });
        if ($('cr-surah').value) qs.set('surah', $('cr-surah').value);
        const data = await api(`/api/classical-review/${source}/items?${qs}`);
        if (source !== state.source) return;
        state.pages = data.pages; $('cr-result-count').textContent = `${data.total.toLocaleString('ar')} موضعًا`;
        $('cr-list').innerHTML = data.items.length ? data.items.map(card).join('') : '<div class="cr-empty">لا توجد مواضع مطابقة لهذا المرشح.</div>';
        $('cr-page-label').textContent = `صفحة ${data.page.toLocaleString('ar')} من ${data.pages.toLocaleString('ar')}`;
        $('cr-prev').disabled = data.page <= 1; $('cr-next').disabled = data.page >= data.pages;
    }
    async function loadVerse(cardEl) {
        const surah = cardEl.dataset.surah; const ayah = cardEl.querySelector('[data-role="ayah"]').value;
        if (!ayah) return toast('أدخل رقم الآية أولًا', true);
        try {
            const data = await api(`/api/classical-review/${state.source}/verse/${surah}/${ayah}`);
            const box = document.createElement('div'); box.className = 'cr-verse'; box.dataset.role = 'verse';
            box.innerHTML = data.words.map((word, i) => `<button type="button" class="cr-word" data-wpos="${i}">${escapeHtml(word)}</button>`).join('');
            const old = cardEl.querySelector('[data-role="verse"], .cr-empty'); old.replaceWith(box);
            cardEl.querySelector('[data-role="wpos"]').value = ''; toast('اختر كلمة الوقف من الآية');
        } catch (e) { toast(e.message || 'تعذر تحميل الآية', true); }
    }
    async function decide(cardEl, decision) {
        const body = { row_id: Number(cardEl.dataset.id), decision, note: cardEl.querySelector('[data-role="note"]').value };
        if (decision === 'approve') {
            body.ayah = cardEl.querySelector('[data-role="ayah"]').value;
            body.wpos = cardEl.querySelector('[data-role="wpos"]').value;
        }
        try {
            await api(`/api/classical-review/${state.source}/decision`, { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(body) });
            toast(decision === 'approve' ? 'تم قبول الموضع' : decision === 'reject' ? 'تم استبعاد الموضع' : 'أُلغي القرار');
            await Promise.all([loadSummary(), loadItems()]);
        } catch (e) { toast(e.message || 'تعذر حفظ القرار', true); }
    }
    async function decideBook(decision) {
        try {
            await api(`/api/classical-review/${state.source}/book-decision`, { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({decision, note: $('cr-book-note').value}) });
            toast(decision === 'add' ? 'تم اعتماد قرار الكتاب' : 'سُجل قرار استبعاد الكتاب'); await loadSummary();
        } catch (e) { toast(e.message || 'تعذر حفظ قرار الكتاب', true); }
    }
    $('cr-list').addEventListener('click', event => {
        const word = event.target.closest('.cr-word');
        if (word) { const box = word.closest('.cr-verse'); box.querySelectorAll('.cr-word').forEach(w => w.classList.remove('cr-stop')); word.classList.add('cr-stop'); word.closest('.cr-card').querySelector('[data-role="wpos"]').value = word.dataset.wpos; return; }
        const button = event.target.closest('[data-action]'); if (!button) return;
        const cardEl = button.closest('.cr-card'); if (button.dataset.action === 'load-verse') loadVerse(cardEl); else decide(cardEl, button.dataset.action);
    });
    $('cr-apply').addEventListener('click', () => { state.page = 1; loadItems().catch(e => toast(e.message, true)); });
    $('cr-prev').addEventListener('click', () => { if (state.page > 1) { state.page--; loadItems(); } });
    $('cr-next').addEventListener('click', () => { if (state.page < state.pages) { state.page++; loadItems(); } });
    $('cr-add-book').addEventListener('click', () => decideBook('add'));
    $('cr-reject-book').addEventListener('click', () => decideBook('reject'));
    document.querySelectorAll('.cr-book-tab').forEach(button => button.addEventListener('click', () => {
        if (button.dataset.source === state.source) return;
        state.source = button.dataset.source; state.page = 1;
        document.querySelectorAll('.cr-book-tab').forEach(tab => tab.classList.toggle('cr-active', tab === button));
        $('cr-status').value = 'pending'; $('cr-alignment').value = 'all'; $('cr-surah').value = '';
        history.replaceState(null, '', `?book=${state.source}`);
        Promise.all([loadSummary(), loadItems()]).catch(e => toast(e.message, true));
    }));
    document.querySelectorAll('.cr-book-tab').forEach(tab => tab.classList.toggle('cr-active', tab.dataset.source === state.source));
    Promise.all([loadSummary(), loadItems()]).catch(e => toast(e.message || 'تعذر تحميل صفحة المراجعة', true));
})();
