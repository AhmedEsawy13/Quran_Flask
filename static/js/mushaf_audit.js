/* In-editor review of a whole-book CV audit: every decision is saved in the cloud
   (the mark as a draft, plus the decision itself) — see modules/audit_review.py. */
(function () {
  'use strict';
  const $ = (s, r = document) => r.querySelector(s);
  const SYMS = ['ج', 'ص', 'ق', 'م', 'لا', 'ع', 'س'];
  const ACTIONABLE = new Set(['shift', 'shift_unsure', 'add', 'maybe', 'differs', 'missed']);
  const params = new URLSearchParams(location.search);
  const state = { edition: params.get('edition') || 'البحرين', tab: params.get('tab') || '', data: null };
  let tabKey = '';

  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const sym = (s, cls = '') => s ? `<span class="sym ${cls}">${esc(s)}</span>` : '<span class="sym none">—</span>';
  const pct = (x) => `${Math.round((x || 0) * 100)}%`;
  const crop = (f) => `/api/mushaf-editor/book-audit/crop?edition=${encodeURIComponent(state.edition)}&f=${encodeURIComponent(f)}`;

  function toast(msg) {
    const t = $('#au-toast');
    t.textContent = msg; t.hidden = false;
    clearTimeout(toast._t); toast._t = setTimeout(() => { t.hidden = true; }, 3500);
  }

  async function api(url, opts) {
    const r = await fetch(url, Object.assign({ credentials: 'same-origin', headers: { 'Content-Type': 'application/json' } }, opts));
    let body = {};
    try { body = await r.json(); } catch (_) { /* crop or empty */ }
    if (r.status === 401) { showLogin(); throw new Error('login'); }
    if (!r.ok) throw new Error(body.message || body.error || `HTTP ${r.status}`);
    return body;
  }

  // One sign-in panel for every tool (static/js/athar-auth.js).
  function showLogin() {
    if (window.AtharAuth) {
      window.AtharAuth.prompt('القرارات تُحفظ في السحابة باسمك.').then((user) => {
        if (user) load();
        else $('#au-main').innerHTML = '<p class="note">يلزم تسجيل الدخول لعرض البطاقات — زر «دخول» أعلى الصفحة.</p>';
      });
      return;
    }
    $('#au-main').innerHTML = '<p class="note err">يلزم تسجيل الدخول.</p>';
  }


  // What "the image is right" does on each tab.
  function imageLabel(i) {
    if (i.tab === 'missed') return 'غير مطبوعة — احذفها';
    if (i.tab === 'shift' || i.tab === 'shift_unsure') return `انقلها إلى «${i.text}»`;
    if (i.tab === 'differs') return `الصورة صحيحة: ${i.cv}`;
    return `أضِف ${i.cv}`;
  }

  function verdict(i) {
    if (i.tab === 'confirmed') return `في القاعدة ${sym(i.db, 'db')} — وُجدت مطبوعة`;
    if (i.from_key) return `في القاعدة على «${esc(i.from_text)}» ${sym(i.db, 'db')} ← في الصورة على «${esc(i.text)}» ${sym(i.cv, 'cv')}<small>ثقة ${pct(i.conf)}</small>`;
    if (i.tab === 'add' || i.tab === 'maybe') return `في الصورة ${sym(i.cv, 'cv')} — ليست في القاعدة<small>ثقة ${pct(i.conf)}</small>`;
    if (i.tab === 'differs') return `القاعدة ${sym(i.db, 'db')} ← النموذج ${sym(i.cv, 'cv')}<small>ثقة ${pct(i.conf)}</small>`;
    return `في القاعدة ${sym(i.db, 'db')}<small>لم يُكتشف في الصورة</small>`;
  }

  function refBadge(i) {
    if (!['add', 'maybe', 'differs'].includes(i.tab)) return '';
    if (i.lean > 0) return '<div class="ref img">المدينة/الأزهر مع الصورة</div>';
    if (i.lean < 0) return '<div class="ref db">المدينة/الأزهر مع القاعدة — والطبعات قد تختلف، فالحكم للصورة</div>';
    return '';
  }

  function statusLine(i) {
    if (i.decision) {
      const what = i.decision.decision === 'ok' ? 'القاعدة صحيحة' : `الصحيح ${sym(i.decision.mark)}`;
      const where = state.data.review_only
        ? (i.decision.decision === 'ok' ? '' : '<small>— يُطبَّق على القاعدة لاحقًا</small>')
        : `<small>— في السحابة ${sym(i.cloud)}</small>`;
      return `<div class="status">✓ حُسمت: ${what}${where}<button type="button" data-act="undo">تراجع</button></div>`;
    }
    if (state.data.review_only) return '';
    const base = i.from_key ? '' : (i.db || '');
    if ((i.cloud || '') !== base) return `<div class="status pend">في السحابة الآن ${sym(i.cloud)} (غير ما في القاعدة)</div>`;
    return '';
  }

  function card(i, n) {
    const [s, a, w] = i.word_key.split(':');
    const others = Object.entries(i.others || {}).map(([k, v]) => `<span class="oth"><i>${esc(k.replace('المدينة ', 'م. '))}</i>${esc(v)}</span>`).join('');
    const imgs = `<img loading="lazy" src="${crop(i.crop)}" alt="" title="ما رآه النموذج">` +
      (i.from_crop ? `<img loading="lazy" src="${crop(i.from_crop)}" alt="" title="موضع القاعدة">` : '');
    const acts = i.actionable && !i.decision ? `
      <div class="acts">
        <button type="button" class="yes" data-act="image">${esc(imageLabel(i))}</button>
        <button type="button" class="no" data-act="db">القاعدة صحيحة</button>
      </div>
      <div class="picker" title="علامة أخرى على «${esc(i.text)}»">${SYMS.map((x) => `<button type="button" data-act="set" data-sym="${x}" class="${i.cloud === x ? 'on' : ''}">${x}</button>`).join('')}<button type="button" data-act="set" data-sym="">✕</button></div>` : '';
    return `<figure class="card${i.decision ? ' decided' : ''}" data-n="${n}">${imgs}
      <figcaption class="body">
        <div class="head"><span class="word">${esc(i.text)}</span><span class="where">${s}:${a} · كلمة ${w} · ص ${i.page}</span>
          ${state.data.review_only ? '' : `<a href="/mushaf-editor?edition=${encodeURIComponent(state.edition)}&page=${i.page}" target="_blank" rel="noopener">الصفحة ↖</a>`}</div>
        <div class="verdict">${verdict(i)}</div>
        ${refBadge(i)}${i.note ? `<div class="cnote">${esc(i.note)}</div>` : ''}
        <div class="others">${others}</div>
        ${statusLine(i)}${acts}
      </figcaption></figure>`;
  }

  function render() {
    const d = state.data;
    const items = d.items;
    const counts = {};
    items.forEach((i) => { counts[i.tab] = (counts[i.tab] || 0) + 1; });
    const tabs = d.tabs.filter((t) => counts[t.id]);
    if (!tabs.some((t) => t.id === state.tab)) state.tab = (tabs[0] || {}).id || '';
    $('#au-tabs').innerHTML = tabs.map((t) => {
      const list = items.filter((i) => i.tab === t.id);
      const done = list.filter((i) => i.decision).length;
      const label = ACTIONABLE.has(t.id) ? `${done}/${list.length}` : list.length;
      return `<button role="tab" data-tab="${t.id}" aria-selected="${t.id === state.tab}">${esc(t.title)} <b>${label}</b></button>`;
    }).join('');
    const act = items.filter((i) => i.actionable);
    const done = act.filter((i) => i.decision).length;
    $('#au-bar').style.width = `${act.length ? (100 * done / act.length) : 0}%`;
    $('#au-count').textContent = `حُسم ${done} من ${act.length}`;
    const sm = d.summary || {};
    $('#au-stat').textContent = `${d.built} · تطابق ${pct(sm.exact_recall)}` + (d.review_only ? ' · مراجعة فقط: القرارات تُسجَّل ولا تُغيّر القاعدة الآن' : '');
    $('#au-editor').hidden = !!d.review_only;
    const tab = d.tabs.find((t) => t.id === state.tab);
    const list = items.map((i, n) => [i, n]).filter(([i]) => i.tab === state.tab);
    $('#au-main').innerHTML = `<p class="note">${esc(tab ? tab.note : '')}</p><div class="grid">${list.map(([i, n]) => card(i, n)).join('') || '<p class="note">لا شيء هنا.</p>'}</div>`;
    const key = `${state.edition}|${state.tab}`;
    if (key !== tabKey) { tabKey = key; window.scrollTo(0, 0); }
  }

  async function load() {
    $('#au-edition').value = state.edition;
    $('#au-msg') && ($('#au-msg').textContent = 'جارٍ التحميل…');
    try {
      state.data = await api(`/api/mushaf-editor/book-audit?edition=${encodeURIComponent(state.edition)}`);
      render();
    } catch (err) {
      if (err.message !== 'login') $('#au-main').innerHTML = `<p class="note err">${esc(err.message)}</p>`;
    }
  }

  async function decide(n, act, symbol) {
    const i = state.data.items[n];
    const el = document.querySelector(`.card[data-n="${n}"]`);
    el && el.querySelectorAll('button').forEach((b) => { b.disabled = true; });
    const body = { edition: state.edition, tab: i.tab, word_key: i.word_key };
    try {
      let res;
      if (act === 'undo') res = await api('/api/mushaf-editor/book-audit/decision', { method: 'DELETE', body: JSON.stringify(body) });
      else res = await api('/api/mushaf-editor/book-audit/decision', { method: 'POST', body: JSON.stringify(Object.assign(body, { choice: act, symbol })) });
      i.decision = res.decision;
      i.cloud = (res.marks || {})[i.word_key] ?? i.cloud;
      if (i.from_key) i.from_cloud = (res.marks || {})[i.from_key] ?? i.from_cloud;
      render();
    } catch (err) {
      if (err.message !== 'login') toast(`لم يُحفظ: ${err.message}`);
      el && el.querySelectorAll('button').forEach((b) => { b.disabled = false; });
    }
  }

  document.addEventListener('click', (e) => {
    const t = e.target.closest('button[data-tab]');
    if (t) { state.tab = t.dataset.tab; history.replaceState(null, '', `?edition=${encodeURIComponent(state.edition)}&tab=${state.tab}`); render(); return; }
    const b = e.target.closest('button[data-act]');
    if (b) { decide(Number(b.closest('.card').dataset.n), b.dataset.act, b.dataset.sym); return; }
    const img = e.target.closest('.card img');
    if (img) { $('#lb img').src = img.src; $('#lb').classList.add('on'); return; }
    if (e.target.closest('#lb')) $('#lb').classList.remove('on');
  });
  $('#au-edition').addEventListener('change', (e) => {
    state.edition = e.target.value; state.tab = '';
    history.replaceState(null, '', `?edition=${encodeURIComponent(state.edition)}`);
    load();
  });
  const hide = $('#au-hide');
  try { hide.checked = localStorage.getItem('au_hide') === '1'; } catch (_) { /* storage blocked */ }
  document.body.classList.toggle('hide-done', hide.checked);
  hide.addEventListener('change', () => {
    document.body.classList.toggle('hide-done', hide.checked);
    try { localStorage.setItem('au_hide', hide.checked ? '1' : '0'); } catch (_) { /* storage blocked */ }
  });
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') $('#lb').classList.remove('on'); });
  load();
}());
