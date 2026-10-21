/* Mesaha waqf review: the sign the model read on each word, checked against the page and saved
   in the cloud (or the local review store) — see modules/mesaha_waqf_review.py. */
(function () {
  'use strict';
  const $ = (s, r = document) => r.querySelector(s);
  const SIGNS = ['ص', 'ق', 'ج', 'م', 'لا', 'س', 'ع'];
  const GROUPS = {
    B: { name: 'يخالف القديم والشمرلي', note: 'قرأ النموذج علامة غير علامة المدينة القديم والشمرلي على الكلمة. اختر المطبوع فعلًا.' },
    N: { name: 'لا علامة مقروءة', note: 'تقف المصاحف الأخرى على الكلمة ولم يقرأ النموذج علامة. اختر المطبوع، أو «لا شيء».' },
    C: { name: 'علامة في غير موضع وقف', note: 'علامة واثقة على كلمة لا تقف عليها المصاحف الأخرى — غالبًا حركة أو همزة.' },
    S: { name: 'عينة (أ)', note: 'عينة عشوائية من (أ). إن صحّت كلها فاعتمد (أ) كاملة من تبويبها.' },
    A: { name: '(أ) يطابق القديم/الشمرلي', note: 'العلامة المقروءة = علامة المدينة القديم أو الشمرلي.' },
  };
  const params = new URLSearchParams(location.search);
  const state = { set: params.get('set') || '', tab: params.get('tab') || 'B', data: null, busy: false };

  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const sym = (s) => s ? `<span class="sym cv">${esc(s)}</span>` : '<span class="sym none">—</span>';
  const img = (id) => `/api/mushaf-editor/mesaha-waqf/card?set=${encodeURIComponent(state.data.set)}&f=${encodeURIComponent(id)}.jpg`;

  function toast(msg) {
    const t = $('#au-toast');
    t.textContent = msg; t.hidden = false;
    clearTimeout(toast._t); toast._t = setTimeout(() => { t.hidden = true; }, 3500);
  }

  async function api(url, opts) {
    const r = await fetch(url, Object.assign({ credentials: 'same-origin', headers: { 'Content-Type': 'application/json' } }, opts));
    let body = {};
    try { body = await r.json(); } catch (_) { /* empty */ }
    if (r.status === 401) { showLogin(); throw new Error('login'); }
    if (!r.ok) throw Object.assign(new Error(body.message || body.error || `HTTP ${r.status}`), { body });
    return body;
  }

  function showLogin() {
    if (window.AtharAuth) {
      window.AtharAuth.prompt('القرارات تُحفظ في السحابة باسمك.').then((user) => {
        if (user) load();
        else $('#mw-grid').innerHTML = '<p class="note">يلزم تسجيل الدخول لعرض البطاقات — زر «دخول» أعلى الصفحة.</p>';
      });
      return;
    }
    $('#mw-grid').innerHTML = '<p class="note err">يلزم تسجيل الدخول.</p>';
  }

  function cardsOf(g) {
    if (g === 'S') { const s = new Set(state.data.a_sample); return state.data.cards.filter((c) => s.has(c.id)); }
    return state.data.cards.filter((c) => c.group === g);
  }

  function renderBar() {
    const cards = state.data.cards, done = cards.filter((c) => c.decision).length;
    $('#au-count').textContent = `${done} / ${cards.length}`;
    $('#au-bar').style.width = `${cards.length ? (100 * done) / cards.length : 0}%`;
    $('#au-tabs').innerHTML = Object.keys(GROUPS).map((g) => {
      const list = cardsOf(g), left = list.filter((c) => !c.decision).length;
      return `<button role="tab" data-g="${g}" aria-selected="${g === state.tab}">${GROUPS[g].name}<b>${left ? `${left} / ${list.length}` : '✓'}</b></button>`;
    }).join('');
    const left = cardsOf(state.tab).filter((c) => !c.decision).length;
    $('#mw-actions').hidden = false;
    $('#mw-note').textContent = GROUPS[state.tab].note + ' المربع الأحمر = ما قرأه النموذج، والخط تحت الكلمة.';
    const acc = $('#mw-accept');
    acc.textContent = left ? `اعتماد الكل كما قرأه النموذج (${left})` : 'كل بطاقات هذا التبويب محسومة';
    acc.disabled = !left || state.busy;
  }

  function cardHtml(c) {
    const hint = Object.entries(c.hint || {}).map(([k, v]) => `${esc(k)}: ${esc(v)}`).join(' · ');
    const chosen = c.decision ? c.decision.mark : null;
    const picks = [...SIGNS, ''].map((s) => `<button type="button" data-mark="${s}" class="${s ? '' : 'none'} ${chosen === s ? 'on' : ''}">${s || 'لا شيء'}</button>`).join('');
    const status = c.decision
      ? `<div class="status">حُسم: ${sym(c.decision.mark)}${c.decision.mark === (c.model || '') ? ' (كما قرأ النموذج)' : ''}<button type="button" data-undo>تراجع</button></div>`
      : '';
    return `<figure class="card ${c.decision ? 'decided' : ''}" data-id="${esc(c.id)}">
      <img loading="lazy" src="${img(c.id)}" alt="">
      <div class="body">
        <div class="head"><span class="word">${esc(c.text)}</span><span class="where">ص ${c.page} · س ${c.line} · ${esc(c.key || '')}</span></div>
        <div class="verdict">النموذج ${sym(c.model)}${c.conf != null ? `<small>ثقة ${(c.conf * 100).toFixed(1)}%</small>` : ''}</div>
        <div class="hint">${hint || 'لا تقف عليها المصاحف الأخرى'}</div>
        ${status}
        <div class="picker">${picks}</div>
      </div></figure>`;
  }

  function render() {
    renderBar();
    const list = cardsOf(state.tab);
    $('#mw-grid').innerHTML = list.length ? list.map(cardHtml).join('') : '<p class="note">لا بطاقات هنا.</p>';
  }

  function setUrl() {
    const u = new URL(location.href);
    u.searchParams.set('set', state.data.set); u.searchParams.set('tab', state.tab);
    history.replaceState(null, '', u);
  }

  async function load() {
    try {
      const q = state.set ? `?set=${encodeURIComponent(state.set)}` : '';
      state.data = await api(`/api/mushaf-editor/mesaha-waqf${q}`);
    } catch (e) {
      if (e.message !== 'login') $('#mw-grid').innerHTML = `<p class="note err">${esc(e.message)}</p>`;
      return;
    }
    state.set = state.data.set;
    $('#mw-set').innerHTML = state.data.sets.map((s) => `<option ${s === state.set ? 'selected' : ''}>${esc(s)}</option>`).join('');
    $('#mw-store').textContent = state.data.store === 'cloud' ? 'تُحفظ في السحابة' : 'تُحفظ في القاعدة المحلية (لا سحابة على هذا الخادم)';
    if (!GROUPS[state.tab]) state.tab = 'B';
    setUrl(); render();
  }

  async function decide(card, mark, undo) {
    try {
      const r = await api('/api/mushaf-editor/mesaha-waqf/decision', {
        method: undo ? 'DELETE' : 'POST', body: JSON.stringify({ set: state.set, id: card.id, mark }),
      });
      card.decision = r.decision;
      // the same word can sit on another tab (the sample is part of A)
      render();
    } catch (e) { if (e.message !== 'login') toast(`لم يُحفظ: ${e.message}`); }
  }

  $('#mw-grid').addEventListener('click', (ev) => {
    const fig = ev.target.closest('.card');
    if (!fig) return;
    const card = state.data.cards.find((c) => c.id === fig.dataset.id);
    const pick = ev.target.closest('[data-mark]');
    if (pick) { decide(card, pick.dataset.mark, false); return; }
    if (ev.target.closest('[data-undo]')) { decide(card, '', true); return; }
    if (ev.target.tagName === 'IMG') { $('#lb img').src = ev.target.src; $('#lb').classList.add('on'); }
  });
  $('#lb').addEventListener('click', () => $('#lb').classList.remove('on'));
  $('#au-tabs').addEventListener('click', (ev) => {
    const b = ev.target.closest('[data-g]');
    if (b) { state.tab = b.dataset.g; setUrl(); render(); window.scrollTo(0, 0); }
  });
  $('#au-hide').addEventListener('change', (ev) => document.body.classList.toggle('hide-done', ev.target.checked));
  $('#mw-set').addEventListener('change', (ev) => { state.set = ev.target.value; load(); });

  $('#mw-accept').addEventListener('click', async () => {
    const left = cardsOf(state.tab).filter((c) => !c.decision).length;
    if (!left || !confirm(`اعتماد ${left} بطاقة من «${GROUPS[state.tab].name}» كما قرأها النموذج؟`)) return;
    state.busy = true; renderBar();
    try {
      const r = await api('/api/mushaf-editor/mesaha-waqf/accept', { method: 'POST', body: JSON.stringify({ set: state.set, group: state.tab }) });
      toast(`اعتُمدت ${r.accepted} بطاقة`);
    } catch (e) { if (e.message !== 'login') toast(`لم يُحفظ: ${e.message}`); }
    state.busy = false;
    load();
  });

  $('#mw-import').addEventListener('change', async (ev) => {
    const file = ev.target.files[0];
    ev.target.value = '';
    if (!file) return;
    try {
      const j = JSON.parse(await file.text());
      const r = await api('/api/mushaf-editor/mesaha-waqf/import', { method: 'POST', body: JSON.stringify({ set: state.set, decisions: j.decisions || j }) });
      toast(`استُورد ${r.imported} قرارًا${r.skipped ? ` (تُرك ${r.skipped})` : ''}`);
      load();
    } catch (e) { if (e.message !== 'login') toast(`تعذّر الاستيراد: ${e.message}`); }
  });

  load();
})();
