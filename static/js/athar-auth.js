/* أثَر — one sign-in for every editor tool.
 *
 * Loaded on every page of an editor deployment (athar_shell_head). It
 *   • adds the account button to the app bar: «دخول», or the editor's name
 *     with «خروج», or «غير متصل بالسحابة» on a server without Supabase;
 *   • opens one shared sign-in panel whenever an /api/ call answers 401
 *     login_required, then retries that call — so a save made while signed
 *     out is not lost, and tools without their own gate still work;
 *   • exposes AtharAuth.status() / prompt() / logout() and fires an
 *     «athar:auth» event on window when the session changes.
 * Sign-in is needed only on a cloud-connected server, and only to write
 * (and to read the activity log / review queues). Reading pages never needs it.
 */
(function () {
    'use strict';

    const STATUS_URL = '/api/mushaf-editor/auth/status';
    const LOGIN_URL = '/api/mushaf-editor/login';
    const LOGOUT_URL = '/api/mushaf-editor/logout';
    const nativeFetch = window.fetch.bind(window);

    let current = null;          // last /auth/status payload
    let statusPromise = null;
    let pending = null;          // one open prompt shared by every caller
    let dialog = null;
    let dismissed = false;       // «لاحقًا» pressed: no more automatic prompts on this page
    let manualOpen = false;      // opened from the app-bar button

    function emit() {
        window.dispatchEvent(new CustomEvent('athar:auth', { detail: current }));
        renderButton();
    }

    async function status(force) {
        if (statusPromise && !force) return statusPromise;
        statusPromise = nativeFetch(STATUS_URL, { credentials: 'same-origin' })
            .then((r) => r.json().catch(() => ({})))
            .then((data) => { current = data || {}; renderButton(); return current; })
            .catch(() => { current = { cloud: false, authenticated: true }; renderButton(); return current; });
        return statusPromise;
    }

    /* ── panel ─────────────────────────────────────────────────── */
    function buildDialog() {
        dialog = document.createElement('dialog');
        dialog.className = 'athar-auth';
        dialog.setAttribute('dir', 'rtl');
        dialog.innerHTML = `
            <form class="athar-auth-card" method="dialog" autocomplete="on">
                <p class="athar-kicker">أثَر · المحرّرون</p>
                <h2 class="athar-auth-title">تسجيل الدخول</h2>
                <p class="athar-auth-hint" data-hint>حساب شخصي لكل محرّر. يلزم للحفظ في السحابة؛ القراءة لا تحتاجه.</p>
                <label class="athar-auth-label" for="athar-auth-user">اسم المستخدم</label>
                <input class="athar-field" id="athar-auth-user" name="username" type="text" required
                       autocomplete="username" dir="ltr" spellcheck="false">
                <label class="athar-auth-label" for="athar-auth-pass">كلمة المرور</label>
                <input class="athar-field" id="athar-auth-pass" name="password" type="password" required
                       autocomplete="current-password" dir="ltr">
                <p class="athar-auth-error" role="alert" hidden></p>
                <div class="athar-auth-actions">
                    <button class="athar-button athar-button-accent" type="submit" value="login">دخول</button>
                    <button class="athar-button athar-button-secondary" type="button" data-cancel>لاحقًا</button>
                </div>
            </form>`;
        document.body.appendChild(dialog);
        const form = dialog.querySelector('form');
        const err = dialog.querySelector('.athar-auth-error');
        form.addEventListener('submit', async (e) => {
            e.preventDefault();
            const submit = form.querySelector('[type=submit]');
            submit.disabled = true;
            err.hidden = true;
            try {
                const r = await nativeFetch(LOGIN_URL, {
                    method: 'POST', credentials: 'same-origin',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ username: form.username.value.trim(), password: form.password.value }),
                });
                const data = await r.json().catch(() => ({}));
                if (!r.ok) {
                    err.textContent = data.error === 'invalid credentials'
                        ? 'اسم المستخدم أو كلمة المرور غير صحيحة'
                        : (r.status === 503 ? 'خدمة الدخول غير متاحة على هذا الخادم' : 'تعذّر تسجيل الدخول');
                    err.hidden = false;
                    return;
                }
                form.password.value = '';
                current = { cloud: true, authenticated: true, user: data.user, login_required: false };
                statusPromise = Promise.resolve(current);
                // A page that was left un-loaded after «لاحقًا» loads its data now.
                const reload = dismissed && manualOpen;
                close(data.user);
                emit();
                if (reload) location.reload();
            } catch (_e) {
                err.textContent = 'تعذّر الاتصال بالخادم';
                err.hidden = false;
            } finally {
                submit.disabled = false;
            }
        });
        dialog.querySelector('[data-cancel]').addEventListener('click', () => { dismissed = true; close(null); });
        dialog.addEventListener('cancel', (e) => { e.preventDefault(); dismissed = true; close(null); });
    }

    function close(user) {
        if (dialog && dialog.open) dialog.close();
        const p = pending;
        pending = null;
        if (p) p.resolve(user);
    }

    /* Show the panel; resolves with the signed-in user, or null if dismissed.
     * After «لاحقًا» only the app-bar button (manual) opens it again. */
    function prompt(hint, opts) {
        const manual = !!(opts && opts.manual);
        if (pending) return pending.promise;
        if (dismissed && !manual) return Promise.resolve(null);
        manualOpen = manual;
        if (!dialog) buildDialog();
        dialog.querySelector('[data-hint]').textContent = hint
            || 'حساب شخصي لكل محرّر. يلزم للحفظ في السحابة؛ القراءة لا تحتاجه.';
        dialog.querySelector('.athar-auth-error').hidden = true;
        let resolve;
        const promise = new Promise((r) => { resolve = r; });
        pending = { promise, resolve };
        dialog.showModal();
        requestAnimationFrame(() => dialog.querySelector('#athar-auth-user').focus());
        return promise;
    }

    async function logout() {
        try { await nativeFetch(LOGOUT_URL, { method: 'POST', credentials: 'same-origin' }); } catch (_e) { /* ignore */ }
        current = Object.assign({}, current, { authenticated: false, user: null, login_required: true });
        statusPromise = Promise.resolve(current);
        emit();
    }

    /* ── 401 → sign in → retry ─────────────────────────────────── */
    function isApi(input) {
        const url = new URL(typeof input === 'string' ? input : input.url, location.href);
        return url.origin === location.origin && url.pathname.startsWith('/api/')
            && ![STATUS_URL, LOGIN_URL, LOGOUT_URL].includes(url.pathname);
    }

    window.fetch = async function (input, init) {
        const response = await nativeFetch(input, init);
        if (response.status !== 401 || !isApi(input)) return response;
        const body = await response.clone().json().catch(() => null);
        if (!body || !body.login_required) return response;
        const user = await prompt('سجّل الدخول للمتابعة؛ يُستأنف ما كنت تفعله تلقائيًا ولا يضيع.');
        return user ? nativeFetch(input, init) : response;
    };

    /* ── app-bar button ────────────────────────────────────────── */
    function renderButton() {
        const bar = document.querySelector('.athar-bar');
        if (!bar || !current) return;
        let btn = bar.querySelector('.athar-account');
        if (!btn) {
            btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'athar-account';
            btn.addEventListener('click', () => {
                if (!current || !current.cloud) return;
                if (current.user) {
                    if (window.confirm(`تسجيل الخروج من حساب «${current.user.name || ''}»؟`)) logout();
                } else {
                    prompt(null, { manual: true });
                }
            });
            const theme = bar.querySelector('[data-athar-theme]');
            bar.insertBefore(btn, theme || null);
        }
        if (!current.cloud) {
            btn.textContent = 'غير متصل بالسحابة';
            btn.title = 'هذا الخادم لا يتصل بالسحابة: لا يلزم دخول، ولا تُحفظ تعديلات مصاحف السحابة هنا.';
            btn.dataset.state = 'local';
        } else if (current.user) {
            btn.innerHTML = '<span class="athar-account-dot" aria-hidden="true"></span>';
            btn.appendChild(document.createTextNode(current.user.name || 'محرّر'));
            btn.title = 'مسجّل الدخول — اضغط للخروج';
            btn.dataset.state = 'in';
        } else {
            btn.textContent = 'دخول';
            btn.title = 'تسجيل الدخول للحفظ في السحابة';
            btn.dataset.state = 'out';
        }
    }

    window.AtharAuth = Object.freeze({ status, prompt, logout });
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => status());
    } else {
        status();
    }
})();
