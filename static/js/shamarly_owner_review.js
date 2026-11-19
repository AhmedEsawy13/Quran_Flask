/* Shamarly word-ownership review: is the red ink the whole word, no more and no less? Saved in the cloud (or the
   local review store) — see modules/shamarly_owner_review.py. */
(function () {
  'use strict';
  const $ = (s, r = document) => r.querySelector(s);
  const REASONS = {
    missing_letter: 'ينقصها حرف', missing_mark: 'تنقصها علامة', extra_letter: 'فيها حرف زائد',
    extra_mark: 'فيها علامة زائدة', waqf: 'علامة وقف',
  };
  const NAMES = { right: 'صحيح', wrong: 'خطأ', prev: 'علامة للسابقة', next: 'علامة للاحقة', unsure: 'لست متأكدًا' };
  const params = new URLSearchParams(location.search);
  const state = { set: params.get('set') || '', data: null };
  const drafts = {};          // card id -> {reasons, note} typed before a verdict was chosen

  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const isWord = (t) => !!t && !/^[٠-٩\s]+$/.test(t);     // an ayah number is not a neighbour word
  const img = (id) => `/api/mushaf-editor/shamarly-owner/card?set=${encodeURIComponent(state.data.set)}&f=${encodeURIComponent(id)}.jpg`;

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
        else $('#so-grid').innerHTML = '<p class="note">يلزم تسجيل الدخول لعرض البطاقات — زر «دخول» أعلى الصفحة.</p>';
      });
      return;
    }
    $('#so-grid').innerHTML = '<p class="note err">يلزم تسجيل الدخول.</p>';
  }

  function renderBar() {
    const cards = state.data.cards, done = cards.filter((c) => c.decision).length;
    $('#au-count').textContent = `${done} / ${cards.length}`;
    $('#au-bar').style.width = `${cards.length ? (100 * done) / cards.length : 0}%`;
  }

  function cardHtml(c) {
    const d = c.decision, draft = drafts[c.id] || {};
    const verdict = d ? d.verdict : null;
    const reasons = d ? d.reasons : (draft.reasons || []);
    const note = d ? d.note : (draft.note || '');
    const pick = (v, label) => `<button type="button" data-v="${v}" class="${v} ${verdict === v ? 'on' : ''}">${label}</button>`;
    const status = d
      ? `<div class="status">حُسم: ${NAMES[d.verdict]}${Object.keys(d.moves || {}).length ? ` <span class="moves">· ${Object.keys(d.moves).length} نقلة في السطر</span>` : ''}${d.stale ? ' <span class="warn">(على صورة أقدم)</span>' : ''}<button type="button" data-undo>تراجع</button></div>`
      : '';
    const chips = Object.entries(REASONS).map(([k, label]) => `<label><input type="checkbox" data-r="${k}" ${reasons.includes(k) ? 'checked' : ''}>${label}</label>`).join('');
    return `<figure class="card ${d ? 'decided' : ''}" data-id="${esc(c.id)}">
      <img loading="lazy" src="${img(c.id)}" alt="" width="720" height="500">
      <div class="body">
        <div class="head"><span class="word">${esc(c.text)}</span><span class="where">ص ${c.page} · س ${c.line} · ك ${c.word_index}</span></div>
        <div class="ctx">${esc(c.prev)} <b>${esc(c.text)}</b> ${esc(c.next)}</div>
        ${status}
        <div class="picker">${pick('right', 'صحيح')}${pick('wrong', 'خطأ')}${isWord(c.prev) ? pick('prev', `فيها علامة لـ«${esc(c.prev)}»`) : ''}${isWord(c.next) ? pick('next', `فيها علامة لـ«${esc(c.next)}»`) : ''}${pick('unsure', 'لست متأكدًا')}</div>
        <div class="reasons" ${verdict === 'wrong' ? '' : 'hidden'}>${chips}</div>
        <textarea data-note maxlength="500" placeholder="ملاحظة (اختيارية)">${esc(note)}</textarea>
        ${c.has_line ? '<button type="button" class="line-open" data-line>محرر السطر — صحّح الملكية بنفسك</button>' : ''}
      </div></figure>`;
  }

  function render() {
    renderBar();
    const list = state.data.cards;
    $('#so-grid').innerHTML = list.length ? list.map(cardHtml).join('') : '<p class="note">لا بطاقات هنا.</p>';
  }

  async function load() {
    try {
      state.data = await api(`/api/mushaf-editor/shamarly-owner${state.set ? `?set=${encodeURIComponent(state.set)}` : ''}`);
    } catch (e) {
      if (e.message !== 'login') $('#so-grid').innerHTML = `<p class="note err">${esc(e.message)}</p>`;
      return;
    }
    state.set = state.data.set;
    $('#so-set').innerHTML = state.data.sets.map((s) => `<option ${s === state.set ? 'selected' : ''}>${esc(s)}</option>`).join('');
    $('#so-store').textContent = state.data.store === 'cloud' ? 'تُحفظ في السحابة' : 'تُحفظ في القاعدة المحلية (لا سحابة على هذا الخادم)';
    if (state.data.note) $('#so-note').textContent += ` ${state.data.note}`;
    const u = new URL(location.href); u.searchParams.set('set', state.set); history.replaceState(null, '', u);
    render();
  }

  function readCard(fig) {
    return {
      reasons: [...fig.querySelectorAll('[data-r]:checked')].map((el) => el.dataset.r),
      note: fig.querySelector('[data-note]').value,
    };
  }

  async function decide(card, fig, verdict, undo, moves) {
    const { reasons, note } = readCard(fig);
    const body = { set: state.set, id: card.id, verdict, reasons, note };
    if (moves) body.moves = moves;
    try {
      const r = await api('/api/mushaf-editor/shamarly-owner/decision', {
        method: undo ? 'DELETE' : 'POST', body: JSON.stringify(body),
      });
      card.decision = r.decision;
      if (undo) drafts[card.id] = { reasons, note }; else delete drafts[card.id];
      const top = fig.getBoundingClientRect().top;
      fig.outerHTML = cardHtml(card);
      if (document.body.classList.contains('hide-done') && card.decision) {
        const next = [...$('#so-grid').querySelectorAll('.card:not(.decided)')].find((el) => el.getBoundingClientRect().top >= top - 2);
        if (next) window.scrollBy(0, next.getBoundingClientRect().top - top);
      }
      renderBar();
      return true;
    } catch (e) { if (e.message !== 'login') toast(`لم يُحفظ: ${e.message}`); return false; }
  }

  const cardOf = (fig) => state.data.cards.find((c) => c.id === fig.dataset.id);

  $('#so-grid').addEventListener('click', (ev) => {
    const fig = ev.target.closest('.card');
    if (!fig) return;
    const card = cardOf(fig);
    const pick = ev.target.closest('[data-v]');
    if (pick) {
      if (pick.dataset.v === 'wrong' && !card.decision) {
        // show the reasons first; a second press (or a reason) saves
        const box = fig.querySelector('.reasons');
        if (box.hidden) { box.hidden = false; pick.classList.add('on'); return; }
      }
      decide(card, fig, pick.dataset.v, false); return;
    }
    if (ev.target.closest('[data-undo]')) { decide(card, fig, '', true); return; }
    if (ev.target.closest('[data-line]')) { openLine(card); return; }
    if (ev.target.tagName === 'IMG') { $('#lb img').src = ev.target.src; $('#lb').classList.add('on'); }
  });
  // a reason ticked, or a note left, re-saves a decided card (or a pending «خطأ») with it
  $('#so-grid').addEventListener('change', (ev) => {
    const fig = ev.target.closest('.card');
    if (!fig) return;
    const card = cardOf(fig);
    const pending = fig.querySelector('.reasons:not([hidden])') && !card.decision;
    if (card.decision) decide(card, fig, card.decision.verdict, false);
    else if (pending && ev.target.matches('[data-r]')) decide(card, fig, 'wrong', false);
    else drafts[card.id] = readCard(fig);
  });

  $('#lb').addEventListener('click', () => $('#lb').classList.remove('on'));
  $('#au-hide').addEventListener('change', (ev) => document.body.classList.toggle('hide-done', ev.target.checked));
  $('#so-set').addEventListener('change', (ev) => { state.set = ev.target.value; load(); });

  // --- line editor: the card's whole line as exported; moves are saved with the verdict -------------------------
  // first and last differ most: the cycle wraps between two neighbouring words
  const COLOURS = ['#c62828', '#1565c0', '#2e7d32', '#ef6c00', '#6a1b9a', '#00838f', '#ad1457', '#37474f'];
  const le = { card: null, line: null, owner: {}, original: {}, selected: new Set(), history: [], zoom: 1 };
  const ownerName = (o) => (o === 'up' ? 'السطر الأعلى' : o === 'down' ? 'السطر الأسفل' : null);

  async function openLine(card) {
    try {
      le.line = await api(`/api/mushaf-editor/shamarly-owner/line?set=${encodeURIComponent(state.set)}&id=${encodeURIComponent(card.id)}`);
    } catch (e) { if (e.message !== 'login') toast(`تعذّر فتح السطر: ${e.message}`); return; }
    le.card = card;
    le.original = Object.fromEntries(Object.entries(le.line.owners).map(([o, ws]) => [o, (ws || [])[0] ?? null]));
    le.owner = { ...le.original, ...((card.decision && card.decision.moves) || {}) };
    le.selected = new Set(); le.history = []; le.zoom = 1;
    $('#le-title').textContent = `«${card.text}» · ص ${card.page} · السطر ${le.line.line_number}`;
    $('#le').hidden = false;
    renderLine();
    scrollToWord();
  }

  function scrollToWord() {                    // open with the card's word in the middle of the stage
    const w = le.line.words.find((x) => x.word_index === le.line.word_index);
    const stage = $('.le-stage'), vb = $('#le-svg').viewBox.baseVal;
    if (!w || !vb.width) return;
    const px = (((w.cell[0] + w.cell[1]) / 2 - vb.x) / vb.width) * $('#le-svg').getBoundingClientRect().width;
    stage.scrollLeft = px - stage.clientWidth / 2;
  }

  function closeLine(force) {
    if (!force && pendingMoves().length && !confirm('في السطر نقلات غير محفوظة ستُفقد. إغلاق؟')) return;
    $('#le').hidden = true; le.card = null;
  }

  const pendingMoves = () => Object.keys(le.owner).filter((o) => le.owner[o] !== le.original[o]);

  function isMark(c) {
    const [, y0, , y1] = c.font_bbox;
    return c.is_mark ?? ((y1 - y0) < le.line.line_height * 0.42);
  }

  // a letter body brings its counters and the marks over it that share its owner (as in Shemrly's line editor)
  function cluster(id) {
    const comps = le.line.components;
    const clicked = comps.find((c) => c.id === id);
    if (clicked && clicked.hole_of) id = clicked.hole_of;
    const body = comps.find((c) => c.id === id);
    const holes = comps.filter((c) => c.hole_of === id).map((c) => c.id);
    if (!body || (isMark(body) && !holes.length)) return [id, ...holes];
    const [bx0, , bx1] = body.font_bbox;
    return [id, ...holes, ...comps.filter((c) => {
      if (c.id === id || c.hole_of || !isMark(c) || le.owner[c.id] !== le.owner[id]) return false;
      const cx = (c.font_bbox[0] + c.font_bbox[2]) / 2;
      return cx >= bx0 - 4 && cx <= bx1 + 4;
    }).map((c) => c.id)];
  }

  function give(target) {
    if (!le.selected.size) { toast('حدّد حرفًا أو علامة أولًا'); return; }
    const words = le.line.words.map((w) => w.word_index);
    le.history.push({ ...le.owner });
    let moved = 0;
    le.selected.forEach((id) => {
      let to = target;
      if (target === 'left' || target === 'right') {
        const i = words.indexOf(le.owner[id]);
        to = i >= 0 ? words[i + (target === 'left' ? 1 : -1)] : undefined;
      }
      if (to !== undefined && le.owner[id] !== to) { le.owner[id] = to; moved += 1; }
    });
    // counters follow their letter
    le.line.components.filter((c) => c.hole_of && le.selected.has(c.hole_of)).forEach((c) => { le.owner[c.id] = le.owner[c.hole_of]; });
    if (!moved) le.history.pop();
    le.selected.clear();
    renderLine();
  }

  function renderLine() {
    const L = le.line, words = L.words;
    const colour = Object.fromEntries(words.map((w, i) => [w.word_index, COLOURS[i % COLOURS.length]]));
    const xs = L.components.flatMap((c) => [c.font_bbox[0], c.font_bbox[2]]).concat(words.flatMap((w) => w.cell));
    const ys = L.components.flatMap((c) => [c.font_bbox[1], c.font_bbox[3]]);
    const x0 = Math.min(...xs) - 20, x1 = Math.max(...xs) + 20;
    const top = Math.max(...ys, L.line_height) + 70, bottom = Math.min(...ys, 0) - 20;
    const svg = $('#le-svg');
    svg.setAttribute('viewBox', `${x0} ${-top} ${x1 - x0} ${top - bottom}`);
    const stageW = $('.le-stage').clientWidth || 800;
    const fitH = 220;                                  // the line opens about 220 px tall, wider than the stage
    const base = Math.max(stageW, fitH * (x1 - x0) / (top - bottom));
    svg.style.width = `${Math.round(base * le.zoom)}px`;
    const groups = {};
    L.components.forEach((c) => { const o = le.owner[c.id]; (groups[o] = groups[o] || []).push(c.path); });
    const fill = (o) => (o === 'up' || o === 'down' ? '#9e9e9e' : colour[o] || '#222');
    const labels = words.map((w) => `<text x="${(w.cell[0] + w.cell[1]) / 2}" y="${-top + 44}" fill="${colour[w.word_index]}"${w.word_index === le.line.word_index ? ' text-decoration="underline"' : ''}>${esc(w.token || '—')}</text>`).join('');
    const fills = Object.entries(groups).map(([o, paths]) => `<path d="${esc(paths.join(' '))}" fill="${fill(o === 'null' ? null : (o === 'up' || o === 'down' ? o : Number(o)))}" fill-rule="nonzero" pointer-events="none"></path>`).join('');
    const byId = Object.fromEntries(L.components.map((c) => [c.id, c]));
    const area = (c) => (c.font_bbox[2] - c.font_bbox[0]) * (c.font_bbox[3] - c.font_bbox[1]);
    const hits = [...L.components].sort((a, b) => area(b) - area(a)).map((c) => `<path class="hit" data-o="${esc(c.id)}" d="${esc(c.path)}"><title>${esc(ownerName(le.owner[c.id]) || (words.find((w) => w.word_index === le.owner[c.id]) || {}).token || '—')}</title></path>`).join('');
    const outline = (ids, cls) => (ids.length ? `<path class="${cls}" d="${esc(ids.map((id) => byId[id].path).join(' '))}" pointer-events="none"></path>` : '');
    svg.innerHTML = labels + fills + outline(pendingMoves(), 'moved') + outline([...le.selected], 'sel') + hits;
    $('#le-words').innerHTML = words.map((w) => `<button type="button" data-give="${w.word_index}" style="color:${colour[w.word_index]}" class="${w.word_index === le.line.word_index ? 'me' : ''}">${esc(w.token || '—')}</button>`).join('');
    const n = pendingMoves().length;
    $('#le-count').textContent = n ? `${n} مسار نُقل` : 'لا نقلات';
    $('#le [data-save]').disabled = !n && !Object.keys((le.card.decision && le.card.decision.moves) || {}).length;
    $('#le [data-undo-move]').disabled = !le.history.length;
    const nb = L.neighbours || { up: true, down: true };    // sets exported before neighbours were known
    $('#le [data-give="up"]').hidden = !nb.up;
    $('#le [data-give="down"]').hidden = !nb.down;
  }

  async function saveLine() {
    const card = le.card;
    const moves = Object.fromEntries(pendingMoves().map((o) => [o, le.owner[o]]));
    const fig = $('#so-grid').querySelector(`.card[data-id="${CSS.escape(card.id)}"]`);
    // after a fix the verdict is about the corrected word: «صحيح» unless the reviewer already chose another
    const verdict = card.decision ? card.decision.verdict : 'right';
    if (await decide(card, fig, verdict, false, moves)) {
      toast(Object.keys(moves).length ? `حُفظت ${Object.keys(moves).length} نقلة مع الحكم «${NAMES[verdict]}»` : 'أُلغيت النقلات');
      closeLine(true);
    }
  }

  $('#le').addEventListener('click', (ev) => {
    if (ev.target === $('#le') || ev.target.closest('[data-close]')) { closeLine(false); return; }
    const hit = ev.target.closest('[data-o]');
    if (hit) {
      const ids = cluster(hit.dataset.o);
      const on = !le.selected.has(ids[0]);
      ids.forEach((id) => (on ? le.selected.add(id) : le.selected.delete(id)));
      renderLine(); return;
    }
    const g = ev.target.closest('[data-give]');
    if (g) { const v = g.dataset.give; give(v === 'up' || v === 'down' ? v : Number(v)); return; }
    if (ev.target.closest('[data-clear]')) { le.selected.clear(); renderLine(); return; }
    if (ev.target.closest('[data-undo-move]')) { const p = le.history.pop(); if (p) { le.owner = p; renderLine(); } return; }
    if (ev.target.closest('[data-reset]')) { le.history.push({ ...le.owner }); le.owner = { ...le.original }; le.selected.clear(); renderLine(); return; }
    const z = ev.target.closest('[data-zoom]');
    if (z) { le.zoom = Math.min(4, Math.max(0.5, le.zoom * (z.dataset.zoom === '1' ? 1.4 : 1 / 1.4))); renderLine(); return; }
    if (ev.target.closest('[data-save]')) saveLine();
  });
  document.addEventListener('keydown', (ev) => {
    if ($('#le').hidden) return;
    if (ev.key === 'Escape') closeLine(false);
    if (ev.key === 'ArrowLeft' || ev.key === 'ArrowRight') { ev.preventDefault(); give(ev.key === 'ArrowLeft' ? 'left' : 'right'); }
  });

  load();
})();
