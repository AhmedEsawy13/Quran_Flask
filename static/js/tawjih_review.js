(() => {
    'use strict';
    const $ = id => document.getElementById(id);
    const state = { page: 1, pages: 1 };
    const api = (url, opts) => window.AtharApi.json(url, opts);
    const GRADES = ['تام', 'كاف', 'حسن', 'جائز', 'قبيح', 'لازم', 'لا يوقف'];
    const STATUS_LABEL = {
        review: 'للمراجعة',
        published: 'منشور',
        skipped: 'مستبعد',
    };

    function escapeHtml(value) {
        return String(value == null ? '' : value).replace(/[&<>'"]/g, c => ({
            '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'
        })[c]);
    }
    function safeHttpsHost(raw, hosts) {
        try {
            const url = new URL(String(raw || ''));
            if (url.protocol === 'https:' && hosts.has(url.hostname)) return url.href;
        } catch (_e) { /* ignore malformed */ }
        return '';
    }
    const VIDEO_HOSTS = new Set(['video.twimg.com']);
    const PHOTO_HOSTS = new Set(['pbs.twimg.com']);
    const YT_HOSTS = new Set(['www.youtube-nocookie.com']);
    const DRIVE_HOSTS = new Set(['drive.google.com', 'docs.google.com']);
    const TWEET_HOSTS = new Set(['x.com', 'www.x.com', 'twitter.com']);
    function renderAttachments(list) {
        if (!Array.isArray(list) || !list.length) return '';
        const chunks = [];
        const photos = [];
        for (const att of list) {
            if (!att || !att.type) continue;
            if (att.type === 'video') {
                const src = safeHttpsHost(att.src, VIDEO_HOSTS);
                if (!src || !new URL(src).pathname.toLowerCase().endsWith('.mp4')) continue;
                chunks.push(`<video class="cr-tawjih-video" controls playsinline preload="metadata" src="${escapeHtml(src)}"></video>`);
            } else if (att.type === 'youtube') {
                const src = safeHttpsHost(att.embed, YT_HOSTS);
                if (!src || !src.includes('/embed/')) continue;
                chunks.push(`<div class="cr-tawjih-embed"><iframe src="${escapeHtml(src)}" title="فيديو" allow="fullscreen" allowfullscreen loading="lazy"></iframe></div>`);
            } else if (att.type === 'drive') {
                const href = safeHttpsHost(att.href, DRIVE_HOSTS);
                const preview = safeHttpsHost(att.preview, DRIVE_HOSTS);
                let block = '<div class="cr-tawjih-drive">';
                if (href) block += `<a class="cr-tawjih-drive-chip" href="${escapeHtml(href)}" target="_blank" rel="noopener">${escapeHtml(att.label || 'ملف على درايف')}</a>`;
                if (preview && preview.includes('/file/')) {
                    block += `<div class="cr-tawjih-embed"><iframe src="${escapeHtml(preview)}" title="ملف درايف" loading="lazy"></iframe></div>`;
                }
                block += '</div>';
                chunks.push(block);
            } else if (att.type === 'photo') {
                const src = safeHttpsHost(att.src, PHOTO_HOSTS);
                if (src) photos.push(src);
            }
        }
        if (photos.length) {
            chunks.push(`<div class="cr-tawjih-photos">${photos.map(src => `<img src="${escapeHtml(src)}" alt="" loading="lazy">`).join('')}</div>`);
        }
        return chunks.length ? `<div class="cr-tawjih-media">${chunks.join('')}</div>` : '';
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
        const s = await api('/api/tawjih-review/summary');
        $('cr-metrics').innerHTML = [
            metric(s.published.toLocaleString('ar'), 'منشور', 'align_conf = 1'),
            metric(s.review.toLocaleString('ar'), 'بانتظار المراجعة', ''),
            metric(s.skipped.toLocaleString('ar'), 'مستبعد', ''),
            metric(s.total.toLocaleString('ar'), 'المجموع', ''),
        ].join('');
    }
    function renderWords(item) {
        if (!item.verse_words || !item.verse_words.length) {
            return '<div class="cr-empty">أدخل رقم السورة والآية ثم حمّل كلماتها واختر كلمة الوقف.</div>';
        }
        return `<div class="cr-verse" data-role="verse">${item.verse_words.map((word, i) =>
            `<button type="button" class="cr-word ${i === item.wpos ? 'cr-stop' : ''}" data-wpos="${i}">${escapeHtml(word)}</button>`).join('')}</div>`;
    }
    function card(item) {
        const surah = item.surah == null ? '' : item.surah;
        const ayah = item.ayah == null ? '' : item.ayah;
        const wpos = item.wpos == null ? '' : item.wpos;
        const statusLabel = STATUS_LABEL[item.status] || item.status;
        const tweetHref = safeHttpsHost(item.url, TWEET_HOSTS);
        const url = tweetHref
            ? `<a href="${escapeHtml(tweetHref)}" target="_blank" rel="noopener">التغريدة</a>`
            : 'التغريدة';
        const gradeOptions = ['<option value="">بدون حكم</option>'].concat(
            GRADES.map(g => `<option value="${escapeHtml(g)}" ${g === item.grade ? 'selected' : ''}>${escapeHtml(g)}</option>`)
        ).join('');
        return `<article class="cr-card" data-id="${item.id}">
          <div class="cr-card-main">
            <div class="cr-card-head"><div class="cr-badges">
              <span class="cr-badge ${item.status === 'review' ? 'cr-unmatched' : ''}">${escapeHtml(statusLabel)}</span>
              <span class="cr-badge">${escapeHtml(item.tweet_id)}</span>
              ${item.surah ? `<span class="cr-badge">سورة ${item.surah} · الآية ${item.ayah}</span>` : '<span class="cr-badge cr-unmatched">بلا محاذاة</span>'}
            </div>${item.grade ? `<span class="cr-grade">${escapeHtml(item.grade)}</span>` : ''}</div>
            ${item.quote ? `<p class="cr-quote">${escapeHtml(item.quote)}</p>` : ''}
            ${renderWords(item)}
            <div class="cr-correction">
              <label>السورة<input data-role="surah" type="number" min="1" max="114" value="${surah}"></label>
              <label>رقم الآية<input data-role="ayah" type="number" min="1" value="${ayah}"></label>
              <input data-role="wpos" type="hidden" value="${wpos}">
              <label>الحكم<select data-role="grade">${gradeOptions}</select></label>
              <button type="button" data-action="load-verse">تحميل الآية</button>
            </div>
            <div class="cr-actions">
              <button class="cr-approve" data-action="add" type="button">إضافة</button>
              <button class="cr-reject" data-action="discard" type="button">استبعاد</button>
            </div>
          </div>
          <aside class="cr-card-source">
            <p class="cr-source-label">${url}</p>
            ${renderAttachments(item.attachments)}
            <p class="cr-source-text cr-tweet">${escapeHtml(item.tweet_body || item.note || '')}</p>
          </aside>
        </article>`;
    }
    async function loadItems() {
        $('cr-list').innerHTML = '<div class="cr-skeleton">جارٍ تحميل مواضع المراجعة…</div>';
        const qs = new URLSearchParams({ status: $('cr-status').value, page: state.page, limit: 12 });
        const data = await api(`/api/tawjih-review/items?${qs}`);
        state.pages = data.pages;
        $('cr-result-count').textContent = `${data.total.toLocaleString('ar')} تغريدة`;
        $('cr-list').innerHTML = data.items.length ? data.items.map(card).join('') : '<div class="cr-empty">لا توجد تغريدات مطابقة لهذا المرشح.</div>';
        $('cr-page-label').textContent = `صفحة ${data.page.toLocaleString('ar')} من ${data.pages.toLocaleString('ar')}`;
        $('cr-prev').disabled = data.page <= 1;
        $('cr-next').disabled = data.page >= data.pages;
    }
    async function loadVerse(cardEl) {
        const surah = cardEl.querySelector('[data-role="surah"]').value;
        const ayah = cardEl.querySelector('[data-role="ayah"]').value;
        if (!surah || !ayah) return toast('أدخل رقم السورة والآية أولًا', true);
        try {
            const data = await api(`/api/tawjih-review/verse/${surah}/${ayah}`);
            const box = document.createElement('div'); box.className = 'cr-verse'; box.dataset.role = 'verse';
            box.innerHTML = data.words.map((word, i) => `<button type="button" class="cr-word" data-wpos="${i}">${escapeHtml(word)}</button>`).join('');
            const old = cardEl.querySelector('[data-role="verse"], .cr-empty'); old.replaceWith(box);
            cardEl.querySelector('[data-role="wpos"]').value = ''; toast('اختر كلمة الوقف من الآية');
        } catch (e) { toast(e.message || 'تعذر تحميل الآية', true); }
    }
    async function decide(cardEl, decision) {
        const body = { id: Number(cardEl.dataset.id), decision };
        if (decision === 'add') {
            body.surah = cardEl.querySelector('[data-role="surah"]').value;
            body.ayah = cardEl.querySelector('[data-role="ayah"]').value;
            body.wpos = cardEl.querySelector('[data-role="wpos"]').value;
            const grade = cardEl.querySelector('[data-role="grade"]').value;
            if (grade) body.grade = grade;
            if (body.wpos === '' || body.surah === '' || body.ayah === '') {
                return toast('إضافة البطاقة تتطلب سورة وآية وكلمة مختارة', true);
            }
        }
        try {
            await api('/api/tawjih-review/decision', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(body),
            });
            toast(decision === 'add' ? 'أُضيفت البطاقة إلى مُكْث' : 'استُبعدت التغريدة');
            await Promise.all([loadSummary(), loadItems()]);
        } catch (e) { toast(e.message || 'تعذر حفظ القرار', true); }
    }
    $('cr-list').addEventListener('click', event => {
        const word = event.target.closest('.cr-word');
        if (word) {
            const box = word.closest('.cr-verse');
            box.querySelectorAll('.cr-word').forEach(w => w.classList.remove('cr-stop'));
            word.classList.add('cr-stop');
            word.closest('.cr-card').querySelector('[data-role="wpos"]').value = word.dataset.wpos;
            return;
        }
        const button = event.target.closest('[data-action]');
        if (!button) return;
        const cardEl = button.closest('.cr-card');
        if (button.dataset.action === 'load-verse') loadVerse(cardEl);
        else decide(cardEl, button.dataset.action);
    });
    $('cr-apply').addEventListener('click', () => { state.page = 1; loadItems().catch(e => toast(e.message, true)); });
    $('cr-prev').addEventListener('click', () => { if (state.page > 1) { state.page--; loadItems(); } });
    $('cr-next').addEventListener('click', () => { if (state.page < state.pages) { state.page++; loadItems(); } });
    Promise.all([loadSummary(), loadItems()]).catch(e => toast(e.message || 'تعذر تحميل صفحة المراجعة', true));
})();
