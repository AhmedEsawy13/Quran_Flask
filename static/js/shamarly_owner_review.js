/* «فحص المشكوك» in Quran_Flask: the same page as ShemrlyMushaf's /word-check-sample — one doubtful word at a time;
   judge it, or fix it in the line editor under it and judge it. Both views are drawn from the exported outline
   shapes, so a fix redraws them at once. Decisions (and moves) go to the cloud, or the local review store — see
   modules/shamarly_owner_review.py. */
(() => {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const params = new URLSearchParams(location.search);
  const API = '/api/mushaf-editor/shamarly-owner';
  const LABEL = { right: 'صحيحة', wrong: 'خاطئة', unsure: 'لست متأكدًا', prev: 'علامة للسابقة', next: 'علامة للاحقة' };
  const KIND = (v) => (v === 'prev' || v === 'next' ? 'wrong' : v);      // older verdicts count as «خاطئة»
  const RED = '#cd2323', INK = '#141310';
  const COLOURS = ['#c62828', '#1565c0', '#2e7d32', '#ef6c00', '#6a1b9a', '#00838f', '#ad1457', '#37474f'];
  let set = params.get('set') || '';
  let items = [];
  let cur = 0;
  let saving = Promise.resolve();
  let showToken = 0;
  const lines = {};                      // card id -> exported line (fetched once)

  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  function status(text, err = false) {
    const s = $('wcStatus');
    s.textContent = text || '';
    s.classList.toggle('err', err);
  }

  async function api(url, opts) {
    const r = await fetch(url, Object.assign({ credentials: 'same-origin', headers: { 'Content-Type': 'application/json' } }, opts));
    let body = {};
    try { body = await r.json(); } catch (_) { /* empty */ }
    if (r.status === 401) { login(); throw new Error('يلزم تسجيل الدخول'); }
    if (!r.ok) throw new Error(body.message || body.error || `HTTP ${r.status}`);
    return body;
  }

  function login() {
    if (window.AtharAuth) window.AtharAuth.prompt('القرارات تُحفظ في السحابة باسمك.').then((user) => { if (user) load(); });
  }

  const verdictOf = (it) => (it.decision ? it.decision.verdict : null);
  const movesOf = (it) => (it.decision && it.decision.moves) || {};
  const changed = (it) => Object.keys(movesOf(it)).length > 0;

  // --- header: stats, bar, grid --------------------------------------------------------------------------
  function renderStats() {
    const c = { right: 0, wrong: 0, unsure: 0 };
    let fixed = 0;
    items.forEach((it) => { const v = verdictOf(it); if (v) c[KIND(v)] += 1; if (changed(it)) fixed += 1; });
    const done = c.right + c.wrong + c.unsure;
    const n = items.length || 1;
    $('wcStats').innerHTML = [['', 'حُكم عليها', `${done} / ${items.length}`], ['r', LABEL.right, c.right], ['w', LABEL.wrong, c.wrong],
      ['u', LABEL.unsure, c.unsure], ['f', 'عُدّلت', fixed]].map(([cls, label, value]) => `<span class="chip ${cls}"><b>${value}</b> ${label}</span>`).join('');
    $('wcBar').innerHTML = [['right', 'var(--wc-green)'], ['wrong', 'var(--wc-red)'], ['unsure', 'var(--wc-amber)']]
      .map(([k, colour]) => `<span style="width:${(100 * c[k]) / n}%;background:${colour}"></span>`).join('');
    const grid = $('wcGrid');
    if (grid.childElementCount !== items.length) {
      grid.innerHTML = items.map((it, i) => `<button type="button" data-i="${i}" title="${esc(it.text)}">${i + 1}</button>`).join('');
    }
    [...grid.children].forEach((b, i) => {
      const v = verdictOf(items[i]);
      b.className = (v ? KIND(v)[0] : '') + (changed(items[i]) ? ' f' : '') + (i === cur ? ' cur' : '');
    });
    $('wcChanged').hidden = !items[cur] || !changed(items[cur]);
  }

  // --- the two views, drawn from the outline shapes ------------------------------------------------------
  function ownersNow(it, line) {
    const base = Object.fromEntries(Object.entries(line.owners).map(([o, ws]) => [o, (ws || [])[0] ?? null]));
    return Object.assign(base, movesOf(it));
  }

  function drawViews(it, line, owner) {
    const wi = it.word_index;
    const order = line.words.map((w) => w.word_index);
    const k = order.indexOf(wi);
    const near = new Set([order[k - 1], wi, order[k + 1]]);
    const comps = line.components;
    const byId = Object.fromEntries(comps.map((c) => [c.id, c]));
    // a counter is drawn with its letter so it stays open; whose it is shows as a ring when that differs
    const drawOwner = (c) => owner[c.hole_of && byId[c.hole_of] ? c.hole_of : c.id];
    const nearBoxes = comps.filter((c) => near.has(owner[c.id])).map((c) => c.font_bbox);
    if (!comps.some((c) => owner[c.id] === wi && !c.hole_of)) {
      $('wcContext').innerHTML = $('wcOwned').innerHTML = '<p class="note" style="padding:12px">الكلمة لا تملك حبرًا الآن — أصلحها في المحرر.</p>';
      return;
    }
    const pad = 24;
    const x0 = Math.min(...nearBoxes.map((b) => b[0])) - pad, x1 = Math.max(...nearBoxes.map((b) => b[2])) + pad;
    const top = Math.max(...comps.map((c) => c.font_bbox[3])) + 12, bottom = Math.min(...comps.map((c) => c.font_bbox[1])) - 12;
    const mine = [], rest = [];
    comps.forEach((c) => (drawOwner(c) === wi ? mine : rest).push(c.path));
    const rings = comps.filter((c) => c.hole_of && byId[c.hole_of] && ((owner[c.id] === wi) !== (owner[c.hole_of] === wi))).map((c) => {
      const [bx0, by0, bx1, by1] = c.font_bbox;
      const r = Math.max(bx1 - bx0, by1 - by0) / 2 + 8;
      return `<circle cx="${(bx0 + bx1) / 2}" cy="${-(by0 + by1) / 2}" r="${r}" fill="none" stroke="#d62828" stroke-width="3" vector-effect="non-scaling-stroke"></circle>`;
    }).join('');
    const svg = (a, b) => `<svg viewBox="${x0} ${-top} ${x1 - x0} ${top - bottom}" xmlns="http://www.w3.org/2000/svg">${a}${b}${rings}</svg>`;
    const path = (d, fill, op = 1) => (d.length ? `<path d="${esc(d.join(' '))}" fill="${fill}" fill-opacity="${op}" fill-rule="nonzero"></path>` : '');
    $('wcContext').innerHTML = svg(path(rest, INK), path(mine, RED));
    $('wcOwned').innerHTML = svg(path(rest, INK, 0.14), path(mine, INK));
  }

  async function lineOf(it) {
    if (!lines[it.id]) lines[it.id] = await api(`${API}/line?set=${encodeURIComponent(set)}&id=${encodeURIComponent(it.id)}`);
    return lines[it.id];
  }

  function drawFallback(it) {      // a set exported without lines: the card image (both views stacked)
    $('wcContext').innerHTML = `<img alt="" src="${API}/card?set=${encodeURIComponent(set)}&f=${encodeURIComponent(it.id)}.jpg">`;
    $('wcOwned').innerHTML = '<p class="note" style="padding:12px">في الصورة فوق.</p>';
  }

  // --- one word ------------------------------------------------------------------------------------------
  function show(i) {
    if (!items.length || !closeEditor()) return;
    cur = (i + items.length) % items.length;
    const it = items[cur];
    const token = ++showToken;
    $('wcWords').innerHTML = [[it.prev, 'n'], [it.text, 't'], [it.next, 'n']].filter(([t]) => t).map(([t, cls]) => `<span class="${cls}">${esc(t)}</span>`).join('');
    $('wcWhere').textContent = `${cur + 1} من ${items.length} · صفحة ${it.page} · سطر ${it.line} · كلمة ${it.word_index}`;
    $('wcWhy').hidden = !it.why;
    $('wcWhy').textContent = it.why ? `المطلوب: ${it.why}` : '';
    $('wcContext').innerHTML = $('wcOwned').innerHTML = '';
    if (it.has_line) {
      lineOf(it).then((line) => { if (token === showToken) drawViews(it, line, ownersNow(it, line)); })
        .catch((e) => status(`تعذّر رسم الكلمة: ${e.message}`, true));
      const nx = items[cur + 1];
      if (nx && nx.has_line) lineOf(nx).catch(() => {});        // the next word is ready when you get there
    } else drawFallback(it);
    $('wcFix').disabled = !it.has_line;
    markVerdict();
    $('wcNote').value = (it.decision && it.decision.note) || '';
    showReasons();
    status(it.decision && it.decision.stale ? 'تنبيه: صُدِّرت البطاقة من جديد بعد هذا الحكم — راجعه.' : '');
    renderStats();
  }

  function markVerdict() {
    const v = KIND(verdictOf(items[cur]));
    ['right', 'wrong', 'unsure'].forEach((k) => $('wc' + k[0].toUpperCase() + k.slice(1)).classList.toggle('on', v === k));
  }

  function showReasons() {
    const it = items[cur];
    const box = $('wcReasons');
    box.hidden = !it || KIND(verdictOf(it)) !== 'wrong';
    const rs = (it && it.decision && it.decision.reasons) || [];
    box.querySelectorAll('.wc-r').forEach((b) => b.classList.toggle('on', rs.includes(b.dataset.r)));
  }

  function save(verdict, extra = {}) {
    const it = items[cur];
    if (!it) return Promise.reject(new Error('no word'));
    const note = $('wcNote').value.trim();
    const before = it.decision;
    const reasons = verdict === 'wrong' ? (extra.reasons || (before && before.reasons) || []) : [];
    it.decision = Object.assign({}, before || {}, { verdict, note, reasons }, extra.moves ? { moves: extra.moves } : {});
    renderStats(); showReasons(); markVerdict();
    const body = { set, id: it.id, verdict, note, reasons };
    if (extra.moves) body.moves = extra.moves;
    saving = saving.then(() => api(`${API}/decision`, { method: 'POST', body: JSON.stringify(body) }))
      .then((r) => {
        it.decision = r.decision;
        renderStats();
        status(`حُفظ: ${LABEL[verdict]}${changed(it) ? ` · عُدّلت (${Object.keys(movesOf(it)).length} نقلة)` : ''}`);
      })
      .catch((e) => { it.decision = before; renderStats(); showReasons(); markVerdict(); status(`لم يُحفظ: ${e.message}. أعد المحاولة.`, true); throw e; });
    return saving;
  }

  function nextOpen() {
    for (let k = 1; k <= items.length; k += 1) {
      const i = (cur + k) % items.length;
      if (!verdictOf(items[i])) return show(i);
    }
    status('كل كلمات المجموعة لها حكم. شكرًا.');
  }

  // --- the line editor, inline under the word ------------------------------------------------------------
  const le = { it: null, line: null, owner: {}, original: {}, selected: new Set(), history: [], zoom: 1 };
  const pendingMoves = () => Object.keys(le.owner).filter((o) => le.owner[o] !== le.original[o]);
  const editorOpen = () => !$('wcDrawer').hidden;

  async function openEditor() {
    const it = items[cur];
    if (!it || !it.has_line) return;
    let line;
    try { line = await lineOf(it); } catch (e) { status(`تعذّر فتح السطر: ${e.message}`, true); return; }
    Object.assign(le, { it, line, selected: new Set(), history: [], zoom: 1 });
    le.original = Object.fromEntries(Object.entries(line.owners).map(([o, ws]) => [o, (ws || [])[0] ?? null]));
    le.owner = ownersNow(it, line);
    $('wcDrawerTitle').textContent = `محرر السطر · ${it.text} · صفحة ${it.page} · سطر ${line.line_number}`;
    $('wcDrawer').hidden = false;
    renderLine();
    scrollToWord();
    $('wcDrawer').scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  }

  function closeEditor(ask = true) {
    if (!editorOpen()) return true;
    const it = le.it;
    const unsaved = it && JSON.stringify(Object.fromEntries(pendingMoves().map((o) => [o, le.owner[o]]))) !== JSON.stringify(movesOf(it));
    if (ask && unsaved && !confirm('في السطر نقلات غير محفوظة ستُفقد. إغلاق؟')) return false;
    $('wcDrawer').hidden = true;
    if (it && lines[it.id] && it === items[cur]) drawViews(it, lines[it.id], ownersNow(it, lines[it.id]));
    return true;
  }

  function scrollToWord() {
    const w = le.line.words.find((x) => x.word_index === le.it.word_index);
    const stage = document.querySelector('.le-stage'), svg = $('leSvg'), vb = svg.viewBox.baseVal;
    if (!w || !vb.width) return;
    const px = (((w.cell[0] + w.cell[1]) / 2 - vb.x) / vb.width) * svg.getBoundingClientRect().width;
    stage.scrollLeft = px - stage.clientWidth / 2;
  }

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
    if (!le.selected.size) { status('حدّد حرفًا أو علامة أولًا', true); return; }
    const order = le.line.words.map((w) => w.word_index);
    le.history.push({ ...le.owner });
    let moved = 0;
    le.selected.forEach((id) => {
      let to = target;
      if (target === 'left' || target === 'right') {
        const i = order.indexOf(le.owner[id]);
        to = i >= 0 ? order[i + (target === 'left' ? 1 : -1)] : undefined;
      }
      if (to !== undefined && le.owner[id] !== to) { le.owner[id] = to; moved += 1; }
    });
    le.line.components.filter((c) => c.hole_of && le.selected.has(c.hole_of)).forEach((c) => { le.owner[c.id] = le.owner[c.hole_of]; });
    if (!moved) le.history.pop();
    le.selected.clear();
    status('');
    renderLine();
  }

  function renderLine() {
    const L = le.line, words = L.words;
    const colour = Object.fromEntries(words.map((w, i) => [w.word_index, COLOURS[i % COLOURS.length]]));
    const xs = L.components.flatMap((c) => [c.font_bbox[0], c.font_bbox[2]]).concat(words.flatMap((w) => w.cell));
    const ys = L.components.flatMap((c) => [c.font_bbox[1], c.font_bbox[3]]);
    const x0 = Math.min(...xs) - 20, x1 = Math.max(...xs) + 20;
    const top = Math.max(...ys, L.line_height) + 70, bottom = Math.min(...ys, 0) - 20;
    const svg = $('leSvg');
    svg.setAttribute('viewBox', `${x0} ${-top} ${x1 - x0} ${top - bottom}`);
    const stageW = document.querySelector('.le-stage').clientWidth || 800;
    svg.style.width = `${Math.round(Math.max(stageW, 220 * (x1 - x0) / (top - bottom)) * le.zoom)}px`;
    const groups = {};
    L.components.forEach((c) => { const o = String(le.owner[c.id]); (groups[o] = groups[o] || []).push(c.path); });
    const fill = (o) => (o === 'up' || o === 'down' ? '#9e9e9e' : colour[o] || '#222');
    const labels = words.map((w) => `<text x="${(w.cell[0] + w.cell[1]) / 2}" y="${-top + 44}" fill="${colour[w.word_index]}"${w.word_index === le.it.word_index ? ' text-decoration="underline"' : ''}>${esc(w.token || '—')}</text>`).join('');
    const fills = Object.entries(groups).map(([o, paths]) => `<path d="${esc(paths.join(' '))}" fill="${fill(o)}" fill-rule="nonzero" pointer-events="none"></path>`).join('');
    const byId = Object.fromEntries(L.components.map((c) => [c.id, c]));
    const area = (c) => (c.font_bbox[2] - c.font_bbox[0]) * (c.font_bbox[3] - c.font_bbox[1]);
    const name = (o) => (o === 'up' ? 'السطر الأعلى' : o === 'down' ? 'السطر الأسفل' : (words.find((w) => w.word_index === o) || {}).token || '—');
    const hits = [...L.components].sort((a, b) => area(b) - area(a)).map((c) => `<path class="hit" data-o="${esc(c.id)}" d="${esc(c.path)}"><title>${esc(name(le.owner[c.id]))}</title></path>`).join('');
    const outline = (ids, cls) => (ids.length ? `<path class="${cls}" d="${esc(ids.map((id) => byId[id].path).join(' '))}" pointer-events="none"></path>` : '');
    svg.innerHTML = labels + fills + outline(pendingMoves(), 'moved') + outline([...le.selected], 'sel') + hits;
    $('leWords').innerHTML = words.map((w) => `<button type="button" data-give="${w.word_index}" style="color:${colour[w.word_index]}" class="${w.word_index === le.it.word_index ? 'me' : ''}">${esc(w.token || '—')}</button>`).join('');
    const n = pendingMoves().length;
    $('leCount').textContent = n ? `${n} مسار نُقل` : 'لا نقلات';
    document.querySelector('#wcDrawer [data-undo-move]').disabled = !le.history.length;
    const nb = L.neighbours || { up: true, down: true };
    document.querySelector('#wcDrawer [data-give="up"]').hidden = !nb.up;
    document.querySelector('#wcDrawer [data-give="down"]').hidden = !nb.down;
    drawViews(le.it, L, le.owner);                 // the views above follow the edit as it happens
  }

  async function saveLine() {
    const it = le.it;
    const moves = Object.fromEntries(pendingMoves().map((o) => [o, le.owner[o]]));
    // after a fix the verdict is about the corrected word: «صحيحة» unless the reviewer already chose another
    const verdict = verdictOf(it) || 'right';
    try {
      await save(verdict, { moves });
      $('wcDrawer').hidden = true;
      drawViews(it, le.line, ownersNow(it, le.line));
      status(Object.keys(moves).length
        ? `حُفظ الإصلاح (${Object.keys(moves).length} نقلة) مع الحكم «${LABEL[verdict]}». غيّره إن لم تصر صحيحة.`
        : 'أُلغيت النقلات.');
      $('wcRight').focus();
    } catch (_e) { /* status says why */ }
  }

  $('wcDrawer').addEventListener('click', (ev) => {
    const hit = ev.target.closest('[data-o]');
    if (hit) {
      const ids = cluster(hit.dataset.o);
      const on = !le.selected.has(ids[0]);
      ids.forEach((id) => (on ? le.selected.add(id) : le.selected.delete(id)));
      renderLine(); return;
    }
    const g = ev.target.closest('[data-give]');
    if (g) { const v = g.dataset.give; give(['up', 'down', 'left', 'right'].includes(v) ? v : Number(v)); return; }
    if (ev.target.closest('[data-clear]')) { le.selected.clear(); renderLine(); return; }
    if (ev.target.closest('[data-undo-move]')) { const p = le.history.pop(); if (p) { le.owner = p; renderLine(); } return; }
    if (ev.target.closest('[data-reset]')) { le.history.push({ ...le.owner }); le.owner = { ...le.original }; le.selected.clear(); renderLine(); return; }
    const z = ev.target.closest('[data-zoom]');
    if (z) { le.zoom = Math.min(4, Math.max(0.5, le.zoom * (z.dataset.zoom === '1' ? 1.4 : 1 / 1.4))); renderLine(); return; }
    if (ev.target.closest('[data-save]')) saveLine();
  });
  $('wcDrawerClose').addEventListener('click', () => closeEditor());

  // --- sets ----------------------------------------------------------------------------------------------
  function load() {
    $('wcWhere').textContent = 'جارٍ التحميل…';
    api(`${API}${set ? `?set=${encodeURIComponent(set)}` : ''}`)
      .then((data) => {
        set = data.set;
        items = data.cards || [];
        $('wcSets').innerHTML = data.sets.map((s) => `<button type="button" class="chip" role="tab" data-set="${esc(s)}" aria-selected="${s === set}">${esc((data.titles || {})[s] || s)}</button>`).join('');
        $('wcStore').textContent = data.store === 'cloud' ? 'تُحفظ في السحابة' : 'تُحفظ في القاعدة المحلية (لا سحابة على هذا الخادم)';
        const q = new URLSearchParams(location.search); q.set('set', set); history.replaceState({}, '', `${location.pathname}?${q}`);
        $('wcGrid').replaceChildren();
        const first = items.findIndex((it) => !verdictOf(it));
        show(first < 0 ? 0 : first);
      })
      .catch((e) => { $('wcWhere').textContent = ''; status(`تعذّر التحميل: ${e.message}`, true); });
  }

  $('wcSets').addEventListener('click', (ev) => {
    const b = ev.target.closest('[data-set]');
    if (!b || b.dataset.set === set || !closeEditor()) return;
    set = b.dataset.set;
    load();
  });

  // --- controls ------------------------------------------------------------------------------------------
  document.querySelectorAll('.wc-v').forEach((b) => b.addEventListener('click', async () => {
    try {
      await save(b.dataset.v);
      // a wrong word stays open for its reasons; Enter or «التالية» moves on
      if (b.dataset.v !== 'wrong' && cur < items.length - 1) show(cur + 1);
    } catch (_e) { /* status already says why */ }
  }));
  document.querySelectorAll('.wc-r').forEach((b) => b.addEventListener('click', () => {
    const it = items[cur];
    if (!it || KIND(verdictOf(it)) !== 'wrong') return;
    const rs = new Set((it.decision && it.decision.reasons) || []);
    if (rs.has(b.dataset.r)) rs.delete(b.dataset.r); else rs.add(b.dataset.r);
    save('wrong', { reasons: [...rs] }).catch(() => {});
  }));
  $('wcFix').addEventListener('click', openEditor);
  $('wcPrev').addEventListener('click', () => show(cur - 1));
  $('wcNext').addEventListener('click', () => show(cur + 1));
  $('wcNextOpen').addEventListener('click', nextOpen);
  $('wcGrid').addEventListener('click', (ev) => { const b = ev.target.closest('[data-i]'); if (b) show(Number(b.dataset.i)); });
  $('wcNote').addEventListener('change', () => { const v = verdictOf(items[cur]); if (v) save(v).catch(() => {}); });
  document.addEventListener('keydown', (e) => {
    if (editorOpen()) {
      if (e.key === 'Escape') closeEditor();
      else if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') { e.preventDefault(); give(e.key === 'ArrowLeft' ? 'left' : 'right'); }
      return;
    }
    if (e.target === $('wcNote')) { if (e.key === 'Enter') $('wcNote').blur(); return; }
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    // physical keys, so an Arabic keyboard layout works too
    const digit = /^(?:Digit|Numpad)([1-8])$/.exec(e.code)?.[1];
    // a shortcut must not also press the focused button (Enter would judge the next word too)
    if (digit || ['Enter', 'ArrowLeft', 'ArrowRight'].includes(e.key) || ['KeyE', 'KeyN'].includes(e.code)) e.preventDefault();
    if (digit === '1') $('wcRight').click();
    else if (digit === '2') $('wcWrong').click();
    else if (digit === '3') $('wcUnsure').click();
    else if (digit && KIND(verdictOf(items[cur])) === 'wrong' && '45678'.includes(digit)) {
      document.querySelectorAll('.wc-r')['45678'.indexOf(digit)].click();
    } else if (e.code === 'KeyE') openEditor();
    else if (e.key === 'Enter' && KIND(verdictOf(items[cur])) === 'wrong') show(cur + 1);
    else if (e.key === 'ArrowLeft') show(cur + 1);      // right to left: left is forward
    else if (e.key === 'ArrowRight') show(cur - 1);
    else if (e.code === 'KeyN') nextOpen();
  });

  load();
})();
