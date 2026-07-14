/* تدريب الوقف — mark where you stopped, get graded against the printed mushaf
   marks and the classical rulings (الداني + الأشموني). No audio/ASR. */
(function () {
    'use strict';
    const $ = id => document.getElementById(id);
    const toAr = n => String(n).replace(/[0-9]/g, d => '٠١٢٣٤٥٦٧٨٩'[d]);

    const els = {
        surah: $('wp-surah'), from: $('wp-from'), to: $('wp-to'), mushaf: $('wp-mushaf'),
        load: $('wp-load'), hint: $('wp-hint'), rangeLabel: $('wp-range-label'),
        rangeTrigger: $('wp-range-trigger'), rangePanel: $('wp-range-panel'),
        mushafTrigger: $('wp-mushaf-trigger'), mushafPanel: $('wp-mushaf-panel'), mushafLabel: $('wp-mushaf-label'),
        passageSec: $('wp-passage-sec'), passage: $('wp-passage'),
        count: $('wp-count'), clear: $('wp-clear'), grade: $('wp-grade'),
        rec: $('wp-rec'), recIcon: $('wp-rec-icon'), recLabel: $('wp-rec-label'), recNote: $('wp-rec-note'),
        follow: $('wp-follow'), layout: $('wp-layout'),
        tajweed: $('wp-tajweed'), tajweedSec: $('wp-tajweed-sec'), tajweedBody: $('wp-tajweed-body'),
        resultSec: $('wp-result-sec'), score: $('wp-score'), scoreNum: $('wp-score-num'),
        scoreTitle: $('wp-score-title'), tGood: $('wp-t-good'), tNote: $('wp-t-note'),
        tErr: $('wp-t-err'), legend: $('wp-legend'), graded: $('wp-graded'), followups: $('wp-followups'),
    };

    // Button state helpers (follow/tajweed/layout are now aria-pressed buttons,
    // not checkboxes) + a small popover pair mirroring mushaf_memorize.js's
    // togglePopover/closePopovers pattern for the new المقطع/المصحف chips.
    const isPressed = btn => !!btn && btn.getAttribute('aria-pressed') === 'true';
    const setPressed = (btn, val) => { if (btn) btn.setAttribute('aria-pressed', val ? 'true' : 'false'); };
    const POPOVERS = [];
    function registerPopover(trigger, panel) { if (trigger && panel) POPOVERS.push({ trigger, panel }); }
    function closePopovers(except) {
        POPOVERS.forEach(({ trigger, panel }) => {
            if (panel === except) return;
            panel.hidden = true;
            trigger.setAttribute('aria-expanded', 'false');
        });
    }
    function togglePopover(trigger, panel) {
        const opening = panel.hidden;
        closePopovers(opening ? panel : null);
        panel.hidden = !opening;
        trigger.setAttribute('aria-expanded', String(opening));
    }

    const state = { surahs: [], ayahCount: {}, verses: [], stops: new Set() /* "ayah:wpos" */ };
    // Phoneme recite-follow: reference entries {skel,ayah,wpos} + a resync cursor
    // (wi = word we're on, anchor = index into the recited skeleton where it begins).
    const rec = { on: false, ref: [], wi: 0, anchor: 0, cur: null };

    // verdict → display. Order = legend order.
    const VERDICT = {
        excellent: { cls: 'ex',   name: 'وقفٌ تام',    tip: 'أفضل مواضع الوقف' },
        good:      { cls: 'good', name: 'وقفٌ حَسَن',   tip: 'وقفٌ جيّد' },
        ok:        { cls: 'ok',   name: 'جائز',        tip: 'يجوز، والوصل قد يكون أولى' },
        caution:   { cls: 'caut', name: 'موضع خلاف',   tip: 'أجازه بعضهم ومنعه آخرون' },
        unmarked:  { cls: 'un',   name: 'بلا نصّ',     tip: 'ليس موضع وقفٍ منصوصًا عليه' },
        error:     { cls: 'err',  name: 'وقفٌ خاطئ',   tip: 'لا يُوقف عليه — يُخلّ بالمعنى' },
    };

    /* ── setup ──────────────────────────────────────────────────────── */
    async function init() {
        const [surahs, versions] = await Promise.all([
            fetch('/api/surahs').then(r => r.json()).catch(() => []),
            fetch('/api/mushaf-versions').then(r => r.json()).catch(() => []),
        ]);
        state.surahs = Array.isArray(surahs) ? surahs : [];
        els.surah.innerHTML = state.surahs.map(s =>
            `<option value="${s.number ?? s}">${toAr(s.number ?? s)}. ${s.name ?? ''}</option>`).join('');
        const prefer = ['المدينة الجديد', 'المدينة القديم'];
        const ordered = [...prefer.filter(v => versions.includes(v)),
                         ...versions.filter(v => !prefer.includes(v))];
        els.mushaf.innerHTML = ordered.map(v => `<option value="${v}">${v}</option>`).join('');
        if (els.mushafLabel) els.mushafLabel.textContent = els.mushaf.value;
        updateLayoutToggle();
        els.mushaf.addEventListener('change', () => {
            if (els.mushafLabel) els.mushafLabel.textContent = els.mushaf.value;
            updateLayoutToggle();
        });
        if (els.layout) els.layout.addEventListener('click', () => {
            setPressed(els.layout, !isPressed(els.layout));
            if (state.verses.length) loadPassage();
        });
        els.surah.addEventListener('change', onSurah);
        els.from.addEventListener('change', () => { if (+els.to.value < +els.from.value) els.to.value = els.from.value; });
        els.load.addEventListener('click', loadPassage);
        els.clear.addEventListener('click', clearStops);
        els.grade.addEventListener('click', gradeStops);
        if (els.rec) els.rec.addEventListener('click', toggleRecord);
        if (els.follow) els.follow.addEventListener('click', () => {
            setPressed(els.follow, !isPressed(els.follow));
            if (!isPressed(els.follow)) clearReciting();
        });
        if (els.tajweed) els.tajweed.addEventListener('click', () => setPressed(els.tajweed, !isPressed(els.tajweed)));
        registerPopover(els.rangeTrigger, els.rangePanel);
        registerPopover(els.mushafTrigger, els.mushafPanel);
        if (els.rangeTrigger) els.rangeTrigger.addEventListener('click', () => togglePopover(els.rangeTrigger, els.rangePanel));
        if (els.mushafTrigger) els.mushafTrigger.addEventListener('click', () => togglePopover(els.mushafTrigger, els.mushafPanel));
        document.addEventListener('click', e => { if (!e.target.closest('.mz-pop')) closePopovers(); });
        await onSurah();
        // deep link ?surah=&from=&to=
        const p = new URLSearchParams(location.search);
        if (p.get('surah')) { els.surah.value = p.get('surah'); await onSurah(); }
        if (p.get('from') && [...els.from.options].some(o => o.value === p.get('from'))) els.from.value = p.get('from');
        if (p.get('to') && [...els.to.options].some(o => o.value === p.get('to'))) els.to.value = p.get('to');
        if (p.get('surah')) loadPassage();
    }

    async function onSurah() {
        const s = +els.surah.value || 1;
        if (!state.ayahCount[s]) {
            const list = await fetch(`/api/surahs/${s}/ayahs`).then(r => r.json()).catch(() => []);
            state.ayahCount[s] = Array.isArray(list) ? list.length : 0;
        }
        const n = state.ayahCount[s] || 0;
        const opts = Array.from({ length: n }, (_, i) => `<option value="${i + 1}">${toAr(i + 1)}</option>`).join('');
        els.from.innerHTML = opts;
        els.to.innerHTML = opts;
        els.from.value = '1';
        els.to.value = String(Math.min(n, 5));
    }

    /* ── load a passage as tappable words ──────────────────────────── */
    async function loadPassage() {
        const s = +els.surah.value, f = +els.from.value, t = +els.to.value;
        if (t < f) { els.to.value = els.from.value; return; }
        if (t - f > 20) { alert('المقطع طويل — اختر ٢١ آية أو أقل.'); return; }
        els.load.disabled = true;
        try {
            if (rec.on) stopRecord();
            const j = await fetch(`/api/waqf-practice/passage/${s}/${f}/${t}`).then(r => r.json());
            state.verses = j.verses || [];
            state.stops.clear();
            // Madinah page-layout view (optional) renders the real mushaf lines;
            // it keys words the same way (ayah:wpos) so tap/grade/ASR are unchanged.
            if (els.layout && isPressed(els.layout) && isMadinah()) await renderMushafLayout(s, f, t, els.mushaf.value);
            else renderPassage();
            const name = (state.surahs.find(x => (x.number ?? x) === s) || {}).name || '';
            if (els.rangeLabel) els.rangeLabel.textContent = `${name} · ${toAr(f)}${t > f ? '–' + toAr(t) : ''}`;
            els.hint.hidden = false;
            els.passageSec.hidden = false;
            els.resultSec.hidden = true;
            updateCount();
            els.passageSec.scrollIntoView({ behavior: 'smooth', block: 'start' });
        } catch (e) {
            alert('تعذّر تحميل المقطع.');
        } finally {
            els.load.disabled = false;
        }
    }

    function wordSpan(ayah, wpos, text, isEnd) {
        const b = document.createElement('button');
        b.type = 'button';
        b.className = 'wp-word' + (isEnd ? ' wp-word-end' : '');
        b.dataset.key = ayah + ':' + wpos;
        b.dataset.ayah = ayah; b.dataset.wpos = wpos;
        b.textContent = text;
        return b;
    }

    // Tap a word to toggle a stop — shared by the plain and mushaf-layout views.
    function wirePassageClicks() {
        els.passage.onclick = e => {
            const b = e.target.closest('.wp-word'); if (!b) return;
            const k = b.dataset.key;
            if (state.stops.has(k)) { state.stops.delete(k); b.classList.remove('wp-stopped'); }
            else { state.stops.add(k); b.classList.add('wp-stopped'); }
            updateCount();
        };
    }

    function renderPassage() {
        els.passage.className = 'wp-passage';
        els.passage.innerHTML = '';
        state.verses.forEach(v => {
            const line = document.createElement('div');
            line.className = 'wp-verse';
            const last = v.words.length - 1;
            v.words.forEach((w, i) => {
                line.appendChild(wordSpan(v.ayah, i, w, i === last));
                line.appendChild(document.createTextNode(' '));
            });
            const num = document.createElement('span');
            num.className = 'wp-ayah-num';
            num.textContent = toAr(v.ayah);
            line.appendChild(num);
            els.passage.appendChild(line);
        });
        wirePassageClicks();
    }

    /* ── Madinah page-layout view (المدينة الجديد / القديم) ─────────────
       Reuses the qpc-v1 604-page layout + Old-Madina font that تثبيت uses.
       The layout words align 1:1 with the passage words per ayah (verified),
       so wpos = running count of real words per ayah maps to the grader. */
    const isMadinah = () => ['المدينة الجديد', 'المدينة القديم'].includes(els.mushaf.value);
    // The mushaf-page view only exists for the two Madinah prints (qpc-v1 layout).
    // Defaults back on every time the selection lands on a Madinah print, since
    // "مشاف page styling" is the whole point of this page's design.
    function updateLayoutToggle() {
        if (!els.layout) return;
        const madinah = isMadinah();
        els.layout.hidden = !madinah;
        if (madinah) setPressed(els.layout, true);
    }
    const _hasArabic = s => /[ء-ي]/.test(s || '');
    const _maxAyahOnPage = (page, s) => {
        let mx = 0;
        (page.lines || []).forEach(ln => (ln.words || []).forEach(w => { if (w.surah === s && w.ayah > mx) mx = w.ayah; }));
        return mx;
    };

    async function renderMushafLayout(s, f, t, mushaf) {
        const mv = 'mushaf_version=' + encodeURIComponent(mushaf);
        let page;
        try { page = await fetch(`/api/qpc-v1/page-by-ayah/${s}/${f}?${mv}`).then(r => r.json()); }
        catch (e) { renderPassage(); return; }
        if (!page || !page.lines) { renderPassage(); return; }
        const pages = [page];
        let guard = 0;
        while (guard++ < 8 && _maxAyahOnPage(page, s) < t) {
            const next = (page.page_number | 0) + 1;
            try { page = await fetch(`/api/qpc-v1/page/${next}?${mv}`).then(r => r.json()); }
            catch (e) { break; }
            if (!page || !page.lines) break;
            pages.push(page);
        }
        const lines = [];
        pages.forEach(p => (p.lines || []).forEach(ln => lines.push(ln)));
        renderLayoutLines(lines, s, f, t);
    }

    const _lineTouchesRange = (ln, s, f, t) =>
        (ln.words || []).some(w => w.surah === s && w.ayah >= f && w.ayah <= t);

    function renderLayoutLines(lines, s, f, t) {
        // render window: first → last line that touches the selected range
        let start = lines.findIndex(ln => _lineTouchesRange(ln, s, f, t));
        let end = -1;
        for (let i = lines.length - 1; i >= 0; i--) { if (_lineTouchesRange(lines[i], s, f, t)) { end = i; break; } }
        if (start < 0) { renderPassage(); return; }        // range not found on page → fall back
        // pull in a leading surah header / basmala when the passage opens a surah
        while (start > 0 && ['surah_name', 'basmallah'].includes(lines[start - 1].line_type)) start--;

        els.passage.className = 'wp-passage wp-ml';
        els.passage.innerHTML = '';
        const wpos = new Map();                             // ayah → next real-word index
        for (let i = start; i <= end; i++) {
            const ln = lines[i];
            if (ln.line_type === 'surah_name') {
                const d = document.createElement('div'); d.className = 'wp-ml-surah'; d.textContent = ln.display_text || ''; els.passage.appendChild(d); continue;
            }
            if (ln.line_type === 'basmallah') {
                const d = document.createElement('div'); d.className = 'wp-ml-basmala'; d.textContent = ln.display_text || 'بِسْمِ اللَّهِ الرَّحْمَٰنِ الرَّحِيمِ'; els.passage.appendChild(d); continue;
            }
            const lineEl = document.createElement('div');
            lineEl.className = 'wp-ml-line' + (ln.is_centered ? ' is-centered' : '');
            (ln.words || []).forEach(w => {
                const raw = w.text || '';
                if (!_hasArabic(raw)) {                     // ۝N ayah-number glyph — not a word
                    const g = document.createElement('span'); g.className = 'wp-ml-num'; g.textContent = raw; lineEl.appendChild(g); return;
                }
                const pos = wpos.get(w.ayah) ?? 0; wpos.set(w.ayah, pos + 1);
                const el = document.createElement('span');
                if (w.surah === s && w.ayah >= f && w.ayah <= t) {
                    el.className = 'wp-word';
                    el.dataset.key = w.ayah + ':' + pos; el.dataset.ayah = w.ayah; el.dataset.wpos = pos;
                } else {
                    el.className = 'wp-ml-ctx';            // out-of-range context word (dimmed, inert)
                }
                el.textContent = raw;
                lineEl.appendChild(el);
            });
            els.passage.appendChild(lineEl);
        }
        wirePassageClicks();
    }

    function clearStops() {
        state.stops.clear();
        els.passage.querySelectorAll('.wp-stopped').forEach(b => b.classList.remove('wp-stopped'));
        updateCount();
    }

    function updateCount() {
        const n = state.stops.size;
        els.count.textContent = n ? `علّمتَ ${toAr(n)} موضع وقف` : 'لم تُعلّم أي وقف بعد';
        els.grade.disabled = n === 0;
    }

    /* ── grade ─────────────────────────────────────────────────────── */
    async function gradeStops() {
        const stops = [...state.stops].map(k => {
            const [ayah, wpos] = k.split(':').map(Number);
            return { ayah, wpos };
        });
        els.grade.disabled = true;
        try {
            const j = await fetch('/api/waqf-practice/grade', {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    surah: +els.surah.value, from_ayah: +els.from.value,
                    to_ayah: +els.to.value, mushaf: els.mushaf.value, stops,
                }),
            }).then(r => r.json());
            renderResult(j);
        } catch (e) {
            alert('تعذّر التقييم.');
        } finally {
            els.grade.disabled = false;
        }
    }

    /* ── recite & auto-mark stops — zipformer PHONEME ASR ──────────────
       The model emits phonemes; we DP-align the recited phoneme stream to the
       passage's reference phonemes (fetched per-word from the backend) to follow
       position, and the model's silence token gives وقف stops. */
    const setRecNote = m => { if (els.recNote) els.recNote.textContent = m || ''; };
    const _PH_KEEP = 'ءابتثجحخدذرزسشصضطظعغفقكلمنهوي';
    function _phSkel(s) {           // consonant skeleton (matches the backend aligner)
        s = (s || '').replace(/[ٱأإآ]/g, 'ا').replace(/ة/g, 'ه').replace(/ى/g, 'ي');
        let out = '';
        for (const c of s) if (_PH_KEEP.indexOf(c) >= 0 && out[out.length - 1] !== c) out += c;
        return out;
    }
    // Phonetically-similar consonants the acoustic model confuses (nasals, sibilants,
    // emphatics, throat letters, glides). A substitution WITHIN a group is cheap so a
    // single model slip doesn't break the alignment.
    const _SIM = {};
    for (const g of ['من', 'سصز', 'تطدض', 'ذظث', 'هحخ', 'عغءه', 'قك', 'ويا', 'رل'])
        for (const c of g) _SIM[c] = (_SIM[c] || '') + g;
    const _subCost = (a, b) => a === b ? 0 : (_SIM[a] && _SIM[a].indexOf(b) >= 0 ? 0.4 : 1);
    function _wed(a, b) {           // weighted edit distance (similar subs discounted)
        const m = a.length, n = b.length;
        if (!m) return n; if (!n) return m;
        let prev = Array.from({ length: n + 1 }, (_, j) => j);
        for (let i = 1; i <= m; i++) {
            const cur = [i];
            for (let j = 1; j <= n; j++)
                cur[j] = Math.min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + _subCost(a[i - 1], b[j - 1]));
            prev = cur;
        }
        return prev[n];
    }
    // Best local match of reference skeleton `es` inside `rs` near index `from` (the
    // start may slip ±2 to absorb an extra/dropped char, length varies around |es|).
    function _bestMatch(rs, from, es) {
        let best = { sim: -1, start: from, len: es.length };
        const s0 = Math.max(0, from - 2), s1 = Math.min(rs.length, from + 2);
        for (let start = s0; start <= s1; start++) {
            const loK = Math.max(1, es.length - 2), hiK = Math.min(rs.length - start, es.length + 3);
            for (let k = loK; k <= hiK; k++) {
                const sim = 1 - _wed(rs.substr(start, k), es) / es.length;
                if (sim > best.sim) best = { sim, start, len: k };
            }
        }
        return best;
    }

    // Fetch the passage's reference phoneme entries {ph, ayah, wpos}.
    async function buildPhonemeRef() {
        rec.ref = []; rec.wi = 0; rec.anchor = 0; rec.cur = null; rec.lastPhonemes = '';
        const s = +els.surah.value, f = +els.from.value, t = +els.to.value;
        try {
            const j = await fetch(`/api/waqf-practice/phonemes/${s}/${f}/${t}`).then(r => r.json());
            rec.ref = (j.entries || []).map(e => ({ ph: e.ph, skel: _phSkel(e.ph), ayah: e.ayah, wpos: e.wpos }));
        } catch (e) { rec.ref = []; }
    }

    async function toggleRecord() {
        if (rec.on) { stopRecord(); return; }
        if (!window.MushafZipformer) { setRecNote('وحدة التعرّف غير متوفرة'); return; }
        if (!state.verses.length) { setRecNote('حمّل مقطعًا أولًا'); return; }
        await buildPhonemeRef();
        if (!rec.ref.length) { setRecNote('تعذّر تجهيز مرجع التلاوة'); return; }
        try {
            await window.MushafZipformer.start({
                onStatus: setRecNote,
                onActive: on => {
                    rec.on = on;
                    els.rec.classList.toggle('mz-listening', on);
                    if (els.recIcon) els.recIcon.className = on ? 'fas fa-stop' : 'fas fa-microphone';
                    if (els.recLabel) els.recLabel.textContent = on ? 'إيقاف التسجيل' : 'سجّل وقوفي';
                    if (!on) { clearReciting(); if (els.tajweed && isPressed(els.tajweed)) requestTajweed(); }
                },
                onPhonemes: alignPhonemes,
                onSilence: markAutoStop,
            });
        } catch (e) {
            setRecNote('تعذّر التشغيل: ' + ((e && (e.message || e.name)) || e));
        }
    }
    function stopRecord() { try { window.MushafZipformer && window.MushafZipformer.stop(); } catch (e) {} }

    function highlightWord(ayah, wpos) {
        if (!els.follow || !isPressed(els.follow)) return;
        els.passage.querySelectorAll('.wp-reciting').forEach(b => b.classList.remove('wp-reciting'));
        const b = els.passage.querySelector(`.wp-word[data-key="${ayah}:${wpos}"]`);
        if (b) { b.classList.add('wp-reciting'); b.scrollIntoView({ block: 'nearest', behavior: 'smooth' }); }
    }
    function clearReciting() { els.passage.querySelectorAll('.wp-reciting').forEach(b => b.classList.remove('wp-reciting')); }

    // Sliding-window resync alignment of the recited phoneme skeleton to the reference
    // word entries. Unlike a committed cursor, it RE-ANCHORS on every advance and can
    // look ahead to skip a garbled word and resync — so a single bad match never wedges
    // the follow. (The old greedy cursor advanced its word pointer on a skip WITHOUT
    // moving the recited cursor, cascading into a permanent stall — verified it froze
    // the highlight for the rest of the passage after ~6 words even on clean input.)
    // Mirrors the reference project (Iam-Muslim/ReciteQuran) phonetic matcher.
    const _WP_ACCEPT = 0.5;        // confirm the current word at/above this similarity
    const _WP_JUMP = 0.6;          // resync forward only on a clearly-strong lookahead
    const _WP_LOOK = 5;            // upcoming words scanned when resyncing
    const _WP_PRIOR = 0.06;        // per-word penalty for jumping ahead (favour chronological)
    function alignPhonemes(recited) {
        rec.lastPhonemes = recited || '';
        const rs = _phSkel(recited);
        let advanced = false, guard = 0;
        while (rec.wi < rec.ref.length && guard++ < rec.ref.length + _WP_LOOK) {
            const es = rec.ref[rec.wi].skel;
            if (!es) { rec.wi++; continue; }
            const tail = rs.length - rec.anchor;
            if (tail < es.length - 1) break;                   // wait for more recited input

            const m = _bestMatch(rs, rec.anchor, es);
            if (m.sim >= _WP_ACCEPT) {                          // current word matched here
                rec.anchor = m.start + m.len;
                rec.cur = rec.ref[rec.wi]; highlightWord(rec.cur.ayah, rec.cur.wpos); rec.wi++; advanced = true; continue;
            }
            // current word didn't match — has the reciter already moved ahead of it?
            let jump = null, expStart = rec.anchor;
            for (let i = rec.wi + 1; i <= Math.min(rec.wi + _WP_LOOK, rec.ref.length - 1); i++) {
                expStart += rec.ref[i - 1].skel.length;
                if (rs.length - expStart < rec.ref[i].skel.length - 1) break;   // not recited yet
                const mi = _bestMatch(rs, expStart, rec.ref[i].skel);
                const score = mi.sim - (i - rec.wi) * _WP_PRIOR;
                if (score >= _WP_JUMP && (!jump || score > jump.score)) jump = { score, i, end: mi.start + mi.len };
            }
            if (jump) {                                         // resync forward to where the reciter is
                rec.anchor = jump.end; rec.wi = jump.i + 1;
                rec.cur = rec.ref[jump.i]; highlightWord(rec.cur.ayah, rec.cur.wpos); advanced = true; continue;
            }
            if (tail > es.length + 6) {                         // waited too long: step past, keep pace
                rec.anchor = Math.min(rs.length, rec.anchor + es.length);
                rec.cur = rec.ref[rec.wi]; highlightWord(rec.cur.ayah, rec.cur.wpos); rec.wi++; advanced = true; continue;
            }
            break;
        }
        if (advanced) setRecNote(`تابعتُ ${toAr(rec.wi)} / ${toAr(rec.ref.length)}`);
    }
    // A detected pause (model silence) seals the current word as a stop.
    function markAutoStop() {
        if (!rec.cur) return;
        const key = rec.cur.ayah + ':' + rec.cur.wpos;
        if (state.stops.has(key)) return;
        state.stops.add(key);
        const b = els.passage.querySelector(`.wp-word[data-key="${key}"]`);
        if (b) b.classList.add('wp-stopped');
        updateCount();
    }

    /* ── tajweed error detection (quran-transcript, server-side) ───────
       POST the full recited phoneme stream; the backend splits it per verse
       (char-level alignment to the reference) and diffs each against the
       rule-correct phonetization → rule-named errors mapped to words. */
    async function requestTajweed() {
        const ph = (rec.lastPhonemes || '').trim();
        if (!ph) { renderTajweed(null); return; }
        setRecNote('تحليل التجويد…');
        try {
            const j = await fetch('/api/waqf-practice/tajweed', {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    surah: +els.surah.value, from_ayah: +els.from.value,
                    to_ayah: +els.to.value, phonemes: ph,
                }),
            }).then(r => r.json());
            renderTajweed(j);
        } catch (e) { renderTajweed(null); }
    }
    function _tjMessage(e) {
        const rule = (e.rules && e.rules[0]) || '';
        if (e.type === 'tajweed' && e.exp_len != null && e.got_len != null) {
            const kind = e.got_len < e.exp_len ? 'قصّرتَ' : 'أطلتَ';
            return `${rule ? rule + ' — ' : 'مدّ — '}${kind} (الصواب ${toAr(e.exp_len)} حركات، قرأتَ ${toAr(e.got_len)})`;
        }
        if (e.op === 'delete') return `أسقطتَ «${e.expected}»${rule ? ' — ' + rule : ''}`;
        if (e.op === 'insert') return `زدتَ «${e.got}»${rule ? ' — ' + rule : ''}`;
        if (e.type === 'tashkeel') return `ضبط: «${e.expected}» ← قرأتَ «${e.got}»`;
        return `نطق: الصواب «${e.expected}»، قرأتَ «${e.got}»`;  // normal replace = letter/مخرج
    }
    function renderTajweed(j) {
        if (!els.tajweedSec) return;
        setRecNote('');
        els.passage.querySelectorAll('.wp-tj-err').forEach(b => b.classList.remove('wp-tj-err'));
        if (!j || j.available === false) { els.tajweedSec.hidden = true; return; }
        const errs = (j.errors || []).filter(e => e.type !== 'tashkeel');   // hide bare harakat noise
        els.tajweedSec.hidden = false;
        if (!errs.length) {
            els.tajweedBody.innerHTML = '<div class="wp-tj-ok"><i class="fas fa-circle-check"></i> لم تُرصد أخطاء تجويد ظاهرة — أحسنت 🌿</div>';
            return;
        }
        // group by word
        const byWord = new Map();
        errs.forEach(e => { const k = e.ayah + ':' + e.wpos; (byWord.get(k) || byWord.set(k, []).get(k)).push(e); });
        let html = '';
        byWord.forEach((list, key) => {
            const b = els.passage.querySelector(`.wp-word[data-key="${key}"]`);
            if (b) b.classList.add('wp-tj-err');
            const word = b ? b.textContent : '';
            const [ay] = key.split(':');
            html += `<div class="wp-tj-row"><span class="wp-tj-w">${word}</span>`
                + `<span class="wp-tj-a">${toAr(ay)}</span><ul class="wp-tj-list">`
                + list.map(e => `<li class="wp-tj-${e.type}">${_tjMessage(e)}</li>`).join('') + '</ul></div>';
        });
        els.tajweedBody.innerHTML = html;
        els.tajweedSec.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }

    function scoreTitle(score, errors) {
        if (errors === 0 && score >= 95) return 'ممتاز — وقوفك سليم';
        if (score >= 85) return 'أحسنت — وقوفٌ جيّد مع ملاحظات يسيرة';
        if (score >= 65) return 'جيّد — راجِع المواضع المُشكِلة';
        return 'يحتاج مراجعة — تأمّل مواضع الوقف الخاطئة';
    }

    function renderResult(j) {
        const errors = j.summary.errors;
        els.scoreNum.textContent = toAr(j.score);
        els.score.className = 'wp-score ' + (j.score >= 85 ? 'wp-score-hi' : j.score >= 65 ? 'wp-score-mid' : 'wp-score-lo');
        els.scoreTitle.textContent = scoreTitle(j.score, errors);
        els.tGood.textContent = toAr(j.summary.good);
        els.tNote.textContent = toAr(j.summary.notes);
        els.tErr.textContent = toAr(errors);

        // legend of the verdicts that actually appeared
        const seen = new Set(j.stops.map(s => s.verdict));
        if (j.broken_lazim.length) seen.add('error');
        els.legend.innerHTML = Object.keys(VERDICT).filter(v => seen.has(v)).map(v => {
            const d = VERDICT[v];
            return `<span class="wp-leg"><span class="wp-dot wp-w-${d.cls}"></span>${d.name}</span>`;
        }).join('');

        // per-stop verdict lookup + broken-lazim positions
        const verdictAt = new Map(j.stops.map(s => [s.ayah + ':' + s.wpos, s]));
        const brokenAt = new Set(j.broken_lazim.map(b => b.ayah + ':' + b.wpos));
        const idealAt = new Set(j.ideal.map(b => b.ayah + ':' + b.wpos));

        els.graded.innerHTML = '';
        state.verses.forEach(v => {
            const line = document.createElement('div');
            line.className = 'wp-verse';
            const last = v.words.length - 1;
            v.words.forEach((w, i) => {
                const key = v.ayah + ':' + i;
                const span = document.createElement('span');
                span.className = 'wp-gword';
                span.textContent = w;
                const s = verdictAt.get(key);
                if (s) {
                    const d = VERDICT[s.verdict];
                    span.classList.add('wp-stop', 'wp-w-' + d.cls);
                    span.title = (s.label || d.name) + (s.sources && s.sources.length
                        ? ' — ' + s.sources.map(x => (x.name ? x.name + ': ' : '') + x.label).join('، ') : '');
                } else if (brokenAt.has(key)) {
                    span.classList.add('wp-missed-lazim');
                    span.title = 'وقف لازم فاتك — يجب الوقف هنا';
                } else if (idealAt.has(key)) {
                    span.classList.add('wp-ideal');
                    span.title = 'موضع وقفٍ مثاليّ (لم تقف عنده)';
                }
                line.appendChild(span);
                line.appendChild(document.createTextNode(' '));
            });
            const num = document.createElement('span');
            num.className = 'wp-ayah-num';
            num.textContent = toAr(v.ayah);
            line.appendChild(num);
            els.graded.appendChild(line);
        });

        // follow-ups: broken لازم + missed ideal stops
        let fu = '';
        if (j.broken_lazim.length) {
            fu += `<div class="wp-fu wp-fu-err"><i class="fas fa-triangle-exclamation"></i> `
                + `<b>وقفٌ لازم فاتك</b> (يجب الوقف): `
                + j.broken_lazim.map(b => `<span class="wp-fu-w">${b.word}</span> <small>${toAr(b.ayah)}</small>`).join('، ') + '</div>';
        }
        if (j.ideal.length) {
            fu += `<div class="wp-fu wp-fu-tip"><i class="fas fa-star"></i> `
                + `<b>مواضع وقفٍ مثالية</b> كان يمكنك الوقف عندها: `
                + j.ideal.map(b => `<span class="wp-fu-w">${b.word}</span> <small>${toAr(b.ayah)}</small>`).join('، ') + '</div>';
        }
        els.followups.innerHTML = fu;
        els.resultSec.hidden = false;
        els.resultSec.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }

    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
    else init();
})();
