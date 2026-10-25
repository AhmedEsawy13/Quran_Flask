/* مختبر الوقف — extras layered on waqf_guide.js (lab page only):
   • verse drawer: click a result → reciter stops + printed marks without leaving the lab
   • saved searches (localStorage) + copy-link for the current search */
(function () {
    'use strict';
    const results = document.getElementById('wq-lab-results');
    if (!results) return;
    const AR = '٠١٢٣٤٥٦٧٨٩';
    const toAr = n => String(n).replace(/\d/g, d => AR[d]);
    const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g,
        c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

    /* ── verse drawer ─────────────────────────────────────────── */
    const drawer = document.createElement('aside');
    drawer.className = 'wq-peek'; drawer.hidden = true;
    drawer.setAttribute('role', 'dialog'); drawer.setAttribute('aria-label', 'تفاصيل الآية');
    drawer.innerHTML = '<div class="wq-peek-head"><span class="wq-peek-title"></span>'
        + '<a class="wq-peek-open" href="#">افتح في مُكْث ←</a>'
        + '<button type="button" class="wq-peek-close" aria-label="إغلاق"><i class="fas fa-xmark" aria-hidden="true"></i></button></div>'
        + '<div class="wq-peek-body"></div>';
    document.body.appendChild(drawer);
    const titleEl = drawer.querySelector('.wq-peek-title');
    const openEl = drawer.querySelector('.wq-peek-open');
    const bodyEl = drawer.querySelector('.wq-peek-body');
    let lastFocus = null, token = 0;
    const cache = new Map();

    function close() { drawer.hidden = true; token++; if (lastFocus) lastFocus.focus?.(); }
    drawer.querySelector('.wq-peek-close').addEventListener('click', close);
    document.addEventListener('keydown', e => { if (e.key === 'Escape' && !drawer.hidden) close(); });

    function render(d, focusWpos) {
        const words = d.words || [];
        const stopCount = {};
        (d.union_stops || []).forEach(u => { stopCount[u.wpos] = u; });
        const total = d.reciters_total || 0;
        const marksByWpos = {};
        (d.mushafs || []).forEach(m => (m.marks || []).forEach(k => {
            (marksByWpos[k.wpos] = marksByWpos[k.wpos] || []).push([m.name || m.id, k.symbol]);
        }));
        const flow = words.map((w, i) => {
            const u = stopCount[i];
            const heat = u ? Math.max(1, Math.round(5 * u.count / Math.max(total, 1))) : 0;
            const mk = marksByWpos[i];
            const tip = [u ? `${toAr(u.count)} من ${toAr(total)} قرّاء يقفون` : '',
                (mk || []).map(x => `${x[0]}: ${x[1]}`).join(' · ')].filter(Boolean).join(' — ');
            return `<span class="wq-pw${i === focusWpos ? ' wq-pw-focus' : ''}${u ? ' wq-pw-stop wq-heat-' + heat : ''}${u && u.solo ? ' wq-pw-solo' : ''}"`
                + (tip ? ` title="${esc(tip)}"` : '') + `>${esc(w)}`
                + (u ? `<sup class="wq-pw-n">${toAr(u.count)}</sup>` : '')
                + (mk ? `<span class="wq-pw-m">${esc([...new Set(mk.map(x => x[1]))].join(' '))}</span>` : '')
                + '</span>';
        }).join(' ');

        const rec = Object.entries(d.per_reciter || {}).map(([rid, r]) => {
            const stops = (r.stops || []).map(s => `<span class="wq-pr-stop">${esc(words[s.wpos] || '')}</span>`).join('');
            return `<div class="wq-pr"><span class="wq-pr-name">${esc(r.name_ar || rid)}</span>${stops || '<span class="wq-pr-none">بلا وقف</span>'}</div>`;
        }).join('');

        const mush = (d.mushafs || []).filter(m => (m.marks || []).length).map(m =>
            `<div class="wq-pr"><span class="wq-pr-name">${esc(m.name || m.id)}</span>`
            + m.marks.map(k => `<span class="wq-pr-stop">${esc(words[k.wpos] || '')} <b>${esc(k.symbol)}</b></span>`).join('')
            + '</div>').join('');

        bodyEl.innerHTML = `<div class="wq-peek-verse" dir="rtl">${flow}</div>`
            + '<p class="wq-peek-key">الرقم أعلى الكلمة = عدد القرّاء الواقفين · الرموز تحتها = علامات المصاحف</p>'
            + `<h3>القرّاء</h3><div class="wq-pr-list">${rec}</div>`
            + (mush ? `<h3>المصاحف</h3><div class="wq-pr-list">${mush}</div>` : '');
    }

    async function peek(s, a, wpos, trigger) {
        const my = ++token;
        lastFocus = trigger || document.activeElement;
        const key = s + ':' + a;
        titleEl.textContent = `${toAr(s)}:${toAr(a)}`;
        const url = new URL('/waqf', location.origin);
        url.searchParams.set('surah', s); url.searchParams.set('ayah', a);
        if (Number.isFinite(wpos)) url.searchParams.set('wpos', wpos);
        openEl.href = url.pathname + url.search;
        drawer.hidden = false;
        bodyEl.innerHTML = '<div class="athar-state athar-state-loading">جارٍ التحميل…</div>';
        try {
            let d = cache.get(key);
            if (!d) { d = await window.AtharApi.json(`/api/waqf/${s}/${a}`); cache.set(key, d); }
            if (my !== token) return;
            render(d, wpos);
            bodyEl.querySelector('.wq-pw-focus')?.scrollIntoView({ block: 'nearest' });
        } catch (_e) {
            if (my === token) bodyEl.innerHTML = '<div class="athar-state athar-state-error">تعذّر تحميل الآية</div>';
        }
    }

    // Capture phase on an ancestor: runs before the guide's per-panel handlers,
    // which would navigate away to /waqf. Modified clicks keep that behaviour.
    results.addEventListener('click', e => {
        if (e.ctrlKey || e.metaKey || e.shiftKey || e.button) return;
        const hit = e.target.closest('.wq-hit');
        if (!hit || !hit.dataset.s || !hit.dataset.a) return;
        e.stopPropagation(); e.preventDefault();
        const w = parseInt(hit.dataset.wpos, 10);
        peek(+hit.dataset.s, +hit.dataset.a, Number.isFinite(w) ? w : NaN, hit);
    }, true);

    /* ── saved searches + share link ──────────────────────────── */
    const KEY = 'athar.waqfLab.saved.v1';
    const load = () => { try { return JSON.parse(localStorage.getItem(KEY) || '[]'); } catch (_e) { return []; } };
    const store = list => { try { localStorage.setItem(KEY, JSON.stringify(list.slice(0, 30))); } catch (_e) {} };
    const sid = s => [s.q, s.mode || '', s.exact ? 1 : 0].join('|');
    function currentSearch() {
        const p = new URLSearchParams(location.search);
        const q = (p.get('q') || '').trim();
        return q ? { q, mode: p.get('mode') || '', exact: p.get('exact') === '1' } : null;
    }
    function hrefOf(s) {
        const u = new URL('/waqf-lab', location.origin);
        u.searchParams.set('tab', 'word'); u.searchParams.set('q', s.q);
        if (s.mode) u.searchParams.set('mode', s.mode);
        if (s.exact) u.searchParams.set('exact', '1');
        return u.pathname + u.search;
    }
    const savedBar = document.createElement('div');
    savedBar.className = 'wq-saved'; savedBar.hidden = true;
    const free = document.querySelector('#wq-panel-word .wq-research-free');
    if (free) free.insertAdjacentElement('afterend', savedBar);

    function renderSaved() {
        const list = load();
        savedBar.hidden = !list.length;
        savedBar.innerHTML = list.length ? '<span class="wq-saved-label">محفوظاتي</span>' + list.map((s, i) =>
            `<span class="wq-saved-item"><a href="${esc(hrefOf(s))}">${esc(s.q)}${s.mode === 'before' ? ' <small>قبل</small>' : ''}</a>`
            + `<button type="button" data-del="${i}" aria-label="حذف">×</button></span>`).join('') : '';
    }
    savedBar.addEventListener('click', e => {
        const b = e.target.closest('[data-del]'); if (!b) return;
        const list = load(); list.splice(+b.dataset.del, 1); store(list); renderSaved(); decorate();
    });

    function decorate() {
        const cnt = document.querySelector('#wq-research-results .wq-research-count');
        const cur = currentSearch();
        if (!cnt || !cur || cnt.querySelector('.wq-save')) return;
        const saved = load().some(s => sid(s) === sid(cur));
        const save = document.createElement('button');
        save.type = 'button'; save.className = 'wq-research-export wq-save';
        save.innerHTML = saved ? '<i class="fas fa-star"></i> محفوظ' : '<i class="far fa-star"></i> حفظ البحث';
        save.addEventListener('click', () => {
            const list = load(), i = list.findIndex(s => sid(s) === sid(cur));
            if (i >= 0) list.splice(i, 1); else list.unshift(cur);
            store(list); renderSaved();
            save.innerHTML = i >= 0 ? '<i class="far fa-star"></i> حفظ البحث' : '<i class="fas fa-star"></i> محفوظ';
        });
        const copy = document.createElement('button');
        copy.type = 'button'; copy.className = 'wq-research-export';
        copy.innerHTML = '<i class="fas fa-link"></i> نسخ الرابط';
        copy.addEventListener('click', async () => {
            const url = location.origin + hrefOf(cur);
            try { await navigator.clipboard.writeText(url); copy.textContent = 'تم النسخ ✓'; }
            catch (_e) { window.prompt('انسخ الرابط', url); }
        });
        cnt.append(save, copy);
    }
    renderSaved();
    const target = document.getElementById('wq-research-results');
    if (target) new MutationObserver(decorate).observe(target, { childList: true });
})();
