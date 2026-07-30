(() => {
    const $ = (id) => document.getElementById(id);
    const body = document.body;
    const cloudConfigured = body.dataset.cloud === '1';
    const actionLabels = {};
    try {
        JSON.parse(body.dataset.actions || '[]').forEach((a) => {
            actionLabels[a.id] = a.label;
        });
    } catch { /* ignore */ }

    const els = {
        login: $('act-login'),
        loginForm: $('act-login-form'),
        loginUsername: $('act-login-username'),
        loginPassword: $('act-login-password'),
        loginError: $('act-login-error'),
        loginSubmit: $('act-login-submit'),
        auth: $('act-auth'),
        filters: $('act-filters'),
        edition: $('act-edition'),
        action: $('act-action'),
        actor: $('act-actor'),
        q: $('act-q'),
        reset: $('act-reset'),
        exportJson: $('act-export-json'),
        exportCsv: $('act-export-csv'),
        status: $('act-status'),
        feed: $('act-feed'),
        more: $('act-more'),
    };

    const state = {
        cloud: cloudConfigured,
        authenticated: !cloudConfigured,
        user: null,
        items: [],
        cursor: null,
        loading: false,
    };

    function escapeHtml(s) {
        return String(s)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    function toArDigits(n) {
        return String(n).replace(/\d/g, (d) => '٠١٢٣٤٥٦٧٨٩'[d]);
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

    function renderAuth() {
        if (!els.auth) return;
        if (!state.cloud) {
            els.auth.textContent = 'لا يوجد سجل سحابي في هذا الوضع (محلي فقط).';
            return;
        }
        if (state.authenticated && state.user) {
            els.auth.textContent = `مسجّل: ${state.user.name || state.user.id}`;
        } else if (state.authenticated) {
            els.auth.textContent = 'متصل';
        } else {
            els.auth.textContent = 'يلزم تسجيل الدخول لعرض السجل';
        }
    }

    function showLogin() {
        if (els.login) els.login.hidden = false;
    }

    function hideLogin() {
        if (els.login) els.login.hidden = true;
    }

    function deepLink(item) {
        const edition = item.edition || '';
        if (item.action && item.action.startsWith('mark_review')) {
            const page = item.page_number ? `?page=${item.page_number}` : '';
            return `/waqf-mark-review${page}`;
        }
        if (item.action && item.action.startsWith('layout_')) {
            const id = edition || 'bahrain';
            const page = item.page_number || (item.meta && item.meta.page_from);
            return page
                ? `/layout-studio/${encodeURIComponent(id)}?page=${page}`
                : `/layout-studio/${encodeURIComponent(id)}`;
        }
        if (edition && (item.surah || item.page_number)) {
            const params = new URLSearchParams({ edition });
            if (item.page_number) params.set('page', String(item.page_number));
            if (item.surah && item.ayah != null) {
                params.set('surah', String(item.surah));
                params.set('ayah', String(item.ayah));
            }
            return `/mushaf-editor?${params.toString()}`;
        }
        return '/mushaf-editor';
    }

    function whereText(item) {
        const bits = [];
        if (item.edition) bits.push(item.edition);
        if (item.page_number != null) bits.push(`ص ${toArDigits(item.page_number)}`);
        if (item.surah && item.ayah != null) {
            bits.push(`${toArDigits(item.surah)}:${toArDigits(item.ayah)}`);
        }
        if (item.word_id != null) bits.push(`كلمة ${toArDigits(item.word_id)}`);
        return bits.join(' · ');
    }

    function deltaText(item) {
        const oldS = item.old_symbol;
        const newS = item.new_symbol;
        if (oldS == null && newS == null) return '';
        const a = (oldS === '' || oldS == null) ? '∅' : oldS;
        const b = (newS === '' || newS == null) ? '∅' : newS;
        if (a === b) return '';
        return `${a} → ${b}`;
    }

    function detailText(item) {
        const meta = item.meta && typeof item.meta === 'object' ? item.meta : null;
        if (!meta) return '';
        if (meta.change_summary) return String(meta.change_summary);
        const bits = [];
        if (meta.decision) bits.push(String(meta.decision));
        if (meta.word_text) bits.push(String(meta.word_text));
        if (meta.note) bits.push(String(meta.note));
        if (meta.op && !meta.change_summary) bits.push(String(meta.op));
        return bits.join(' · ');
    }

    function fillActors(actors) {
        if (!els.actor) return;
        const selected = els.actor.value;
        const keep = [{ id: '', name: 'الكل' }].concat(actors || []);
        els.actor.innerHTML = keep.map((a) => (
            `<option value="${escapeHtml(a.id || '')}">${escapeHtml(a.name || a.id || '')}</option>`
        )).join('');
        if (selected && keep.some((a) => String(a.id) === selected)) {
            els.actor.value = selected;
        }
    }

    function downloadBlob(filename, mime, text) {
        const blob = new Blob([text], { type: mime });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = filename;
        a.click();
        URL.revokeObjectURL(url);
    }

    function exportJson() {
        downloadBlob(
            `athar-activity-${Date.now()}.json`,
            'application/json;charset=utf-8',
            JSON.stringify(state.items, null, 2),
        );
    }

    function csvEscape(v) {
        const s = v == null ? '' : String(v);
        if (/[",\n]/.test(s)) return `"${s.replace(/"/g, '""')}"`;
        return s;
    }

    function exportCsv() {
        const headers = [
            'at', 'actor_name', 'action', 'edition', 'page_number',
            'surah', 'ayah', 'word_id', 'old_symbol', 'new_symbol', 'detail',
        ];
        const lines = [headers.join(',')];
        state.items.forEach((item) => {
            lines.push([
                item.at,
                item.actor_name,
                item.action,
                item.edition,
                item.page_number,
                item.surah,
                item.ayah,
                item.word_id,
                item.old_symbol,
                item.new_symbol,
                detailText(item),
            ].map(csvEscape).join(','));
        });
        downloadBlob(
            `athar-activity-${Date.now()}.csv`,
            'text/csv;charset=utf-8',
            `\ufeff${lines.join('\n')}`,
        );
    }

    function formatWhen(iso) {
        if (!iso) return '';
        try {
            const d = new Date(iso);
            if (Number.isNaN(d.getTime())) return iso;
            return d.toLocaleString('ar', {
                year: 'numeric', month: 'short', day: 'numeric',
                hour: '2-digit', minute: '2-digit',
            });
        } catch {
            return iso;
        }
    }

    function renderFeed(append) {
        if (!append) els.feed.innerHTML = '';
        if (!state.items.length) {
            els.feed.innerHTML = `<p class="act-empty">${
                state.cloud
                    ? 'لا أحداث مطابقة للتصفية.'
                    : 'السجل السحابي غير مفعّل على هذا الجهاز.'
            }</p>`;
            els.more.hidden = true;
            return;
        }
        const html = state.items.map((item) => {
            const act = actionLabels[item.action] || item.action || '—';
            const who = item.actor_name || '—';
            const where = whereText(item);
            const delta = deltaText(item);
            const detail = detailText(item);
            const href = deepLink(item);
            return `<li class="act-item">
                <div class="act-item-top">
                    <span class="act-who">${escapeHtml(who)}</span>
                    <time class="act-when">${escapeHtml(formatWhen(item.at))}</time>
                </div>
                <div class="act-action">${escapeHtml(act)}</div>
                ${where ? `<div class="act-where">${escapeHtml(where)}</div>` : ''}
                ${delta ? `<div class="act-delta">${escapeHtml(delta)}</div>` : ''}
                ${detail ? `<div class="act-detail">${escapeHtml(detail)}</div>` : ''}
                <a class="act-link" href="${escapeHtml(href)}">افتح الموقع</a>
            </li>`;
        }).join('');
        if (append) els.feed.insertAdjacentHTML('beforeend', html);
        else els.feed.innerHTML = html;
        els.more.hidden = !state.cursor;
    }

    function filterParams(extra) {
        const params = new URLSearchParams();
        const edition = (els.edition.value || '').trim();
        const action = (els.action.value || '').trim();
        const actor = els.actor ? (els.actor.value || '').trim() : '';
        const q = (els.q.value || '').trim();
        if (edition) params.set('edition', edition);
        if (action) params.set('action', action);
        if (actor) params.set('actor_id', actor);
        if (q) params.set('q', q);
        params.set('limit', '40');
        if (extra) {
            Object.entries(extra).forEach(([k, v]) => {
                if (v != null && v !== '') params.set(k, String(v));
            });
        }
        return params;
    }

    async function loadFeed({ append } = {}) {
        if (state.loading) return;
        if (state.cloud && !state.authenticated) {
            showLogin();
            els.status.textContent = 'سجّل الدخول لعرض السجل';
            return;
        }
        state.loading = true;
        els.status.textContent = append ? 'جارٍ التحميل…' : 'جارٍ جلب الأحداث…';
        els.more.disabled = true;
        try {
            const extra = append && state.cursor
                ? { before_at: state.cursor.before_at, before_id: state.cursor.before_id }
                : null;
            const data = await api(`/api/activity?${filterParams(extra)}`);
            const items = data.items || [];
            if (append) state.items = state.items.concat(items);
            else state.items = items;
            state.cursor = data.next_cursor || null;
            if (data.actions) {
                Object.assign(actionLabels, data.actions);
            }
            if (!append && Array.isArray(data.actors)) {
                fillActors(data.actors);
            }
            renderFeed(!!append);
            els.status.textContent = state.items.length
                ? `${toArDigits(state.items.length)} حدث`
                : 'لا نتائج';
        } catch (err) {
            if (err.status === 401) {
                state.authenticated = false;
                showLogin();
                els.status.textContent = 'يلزم تسجيل الدخول';
            } else {
                els.status.textContent = err.message || 'تعذّر التحميل';
            }
        } finally {
            state.loading = false;
            els.more.disabled = false;
        }
    }

    async function checkAuth() {
        try {
            const data = await api('/api/mushaf-editor/auth/status');
            state.cloud = !!data.cloud;
            state.authenticated = !!data.authenticated;
            state.user = data.user || null;
            if (data.login_required) showLogin();
            else hideLogin();
        } catch {
            state.cloud = cloudConfigured;
            state.authenticated = !cloudConfigured;
            hideLogin();
        }
        renderAuth();
    }

    els.filters.addEventListener('submit', (e) => {
        e.preventDefault();
        state.cursor = null;
        loadFeed({ append: false });
    });
    els.reset.addEventListener('click', () => {
        els.edition.value = '';
        els.action.value = '';
        if (els.actor) els.actor.value = '';
        els.q.value = '';
        state.cursor = null;
        loadFeed({ append: false });
    });
    els.more.addEventListener('click', () => loadFeed({ append: true }));
    if (els.exportJson) els.exportJson.addEventListener('click', exportJson);
    if (els.exportCsv) els.exportCsv.addEventListener('click', exportCsv);

    if (els.loginForm) {
        els.loginForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            const username = (els.loginUsername.value || '').trim();
            const password = els.loginPassword.value || '';
            els.loginSubmit.disabled = true;
            els.loginError.hidden = true;
            try {
                const data = await api('/api/mushaf-editor/login', {
                    method: 'POST',
                    body: JSON.stringify({ username, password }),
                });
                state.authenticated = true;
                state.user = data.user || { name: username };
                hideLogin();
                renderAuth();
                await loadFeed({ append: false });
            } catch (err) {
                els.loginError.textContent = err.message === 'invalid credentials'
                    ? 'بيانات الدخول غير صحيحة'
                    : (err.message || 'تعذّر الدخول');
                els.loginError.hidden = false;
            } finally {
                els.loginSubmit.disabled = false;
            }
        });
    }

    (async function init() {
        await checkAuth();
        await loadFeed({ append: false });
    })();
})();
