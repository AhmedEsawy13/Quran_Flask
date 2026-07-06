/* تدريب الوقف — mark where you stopped, get graded against the printed mushaf
   marks and the classical rulings (الداني + الأشموني). No audio/ASR. */
(function () {
    'use strict';
    const $ = id => document.getElementById(id);
    const toAr = n => String(n).replace(/[0-9]/g, d => '٠١٢٣٤٥٦٧٨٩'[d]);

    // Same Arabic folding + tolerant word match the memorize page uses for ASR follow.
    const _arNorm = s => (s || '')
        .replace(/[ً-ٰٟۖ-ۭ࣐-ࣿـ۝٠-٩]/g, '')
        .replace(/[إأآاٱ]/g, 'ا').replace(/[ىي]/g, 'ي').replace(/ة/g, 'ه').replace(/ؤ/g, 'و').replace(/ئ/g, 'ي')
        .replace(/\s+/g, ' ').trim();
    const _wmatch = (a, b) => a === b ||
        (a.length >= 4 && b.length >= 4 && (a.startsWith(b) || b.startsWith(a) || a.includes(b) || b.includes(a)));

    const els = {
        surah: $('wp-surah'), from: $('wp-from'), to: $('wp-to'), mushaf: $('wp-mushaf'),
        load: $('wp-load'), hint: $('wp-hint'), barVerse: $('wp-bar-verse'),
        passageCard: $('wp-passage-card'), passage: $('wp-passage'),
        count: $('wp-count'), clear: $('wp-clear'), grade: $('wp-grade'),
        rec: $('wp-rec'), recNote: $('wp-rec-note'), follow: $('wp-follow'),
        layout: $('wp-layout'), layoutWrap: $('wp-layout-wrap'),
        resultCard: $('wp-result-card'), score: $('wp-score'), scoreNum: $('wp-score-num'),
        scoreTitle: $('wp-score-title'), tGood: $('wp-t-good'), tNote: $('wp-t-note'),
        tErr: $('wp-t-err'), legend: $('wp-legend'), graded: $('wp-graded'), followups: $('wp-followups'),
    };

    const state = { surahs: [], ayahCount: {}, verses: [], stops: new Set() /* "ayah:wpos" */ };
    // ASR follow: flat expected words + monotonic alignment cursor.
    const rec = { on: false, exp: [], pos: 0, lastIdx: -1 };

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
        updateLayoutToggle();
        els.mushaf.addEventListener('change', updateLayoutToggle);
        if (els.layout) els.layout.addEventListener('change', () => { if (state.verses.length) loadPassage(); });
        els.surah.addEventListener('change', onSurah);
        els.from.addEventListener('change', () => { if (+els.to.value < +els.from.value) els.to.value = els.from.value; });
        els.load.addEventListener('click', loadPassage);
        els.clear.addEventListener('click', clearStops);
        els.grade.addEventListener('click', gradeStops);
        if (els.rec) els.rec.addEventListener('click', toggleRecord);
        if (els.follow) els.follow.addEventListener('change', () => { if (!els.follow.checked) clearReciting(); });
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
            buildExpected();
            // Madinah page-layout view (optional) renders the real mushaf lines;
            // it keys words the same way (ayah:wpos) so tap/grade/ASR are unchanged.
            if (els.layout && els.layout.checked && isMadinah()) await renderMushafLayout(s, f, t, els.mushaf.value);
            else renderPassage();
            const name = (state.surahs.find(x => (x.number ?? x) === s) || {}).name || '';
            els.barVerse.textContent = `${name} · ${toAr(f)}${t > f ? '–' + toAr(t) : ''}`;
            els.hint.hidden = false;
            els.passageCard.hidden = false;
            els.resultCard.hidden = true;
            updateCount();
            els.passageCard.scrollIntoView({ behavior: 'smooth', block: 'start' });
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
    function updateLayoutToggle() { if (els.layoutWrap) els.layoutWrap.hidden = !isMadinah(); }
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

    /* ── recite & auto-mark stops (FastConformer in-browser ASR) ───── */
    // Flat expected-word list in reading order; wpos = word index within its ayah.
    function buildExpected() {
        rec.exp = [];
        state.verses.forEach(v => (v.words || []).forEach((w, i) => {
            if (/^[۝٠-٩]+$/.test((w || '').trim())) return;   // skip verse-number ornaments
            const norm = _arNorm(w);
            if (norm) rec.exp.push({ ayah: v.ayah, wpos: i, norm });
        }));
        rec.pos = 0; rec.lastIdx = -1;
    }
    const setRecNote = m => { if (els.recNote) els.recNote.textContent = m || ''; };

    async function toggleRecord() {
        if (rec.on) { stopRecord(); return; }
        if (!window.MushafASR) { setRecNote('وحدة التعرّف غير متوفرة'); return; }
        if (!state.verses.length) { setRecNote('حمّل مقطعًا أولًا'); return; }
        rec.pos = 0; rec.lastIdx = -1;
        try {
            await window.MushafASR.start({
                onStatus: setRecNote,
                onActive: on => {
                    rec.on = on;
                    els.rec.classList.toggle('is-rec', on);
                    els.rec.innerHTML = on
                        ? '<i class="fas fa-stop"></i> إيقاف التسجيل'
                        : '<i class="fas fa-microphone"></i> سجّل وقوفي';
                    if (!on) clearReciting();
                },
                onWord: alignWord,
                onStop: markAutoStop,
            });
        } catch (e) {
            setRecNote('تعذّر التشغيل: ' + ((e && (e.message || e.name)) || e));
        }
    }
    function stopRecord() { try { window.MushafASR && window.MushafASR.stop(); } catch (e) {} }

    // Live "currently reciting" highlight on the passage word (toggle option).
    function highlightReciting(idx) {
        if (!els.follow || !els.follow.checked) return;
        els.passage.querySelectorAll('.wp-reciting').forEach(b => b.classList.remove('wp-reciting'));
        if (idx < 0 || idx >= rec.exp.length) return;
        const e = rec.exp[idx], b = els.passage.querySelector(`.wp-word[data-key="${e.ayah + ':' + e.wpos}"]`);
        if (b) { b.classList.add('wp-reciting'); b.scrollIntoView({ block: 'nearest', behavior: 'smooth' }); }
    }
    function clearReciting() { els.passage.querySelectorAll('.wp-reciting').forEach(b => b.classList.remove('wp-reciting')); }

    // Monotonic forward match of a recited word onto the expected sequence.
    function alignWord(w) {
        const target = _arNorm(w && w.text || '');
        if (!target) return;
        for (let k = rec.pos; k < Math.min(rec.exp.length, rec.pos + 4); k++) {
            if (_wmatch(target, rec.exp[k].norm)) {
                rec.lastIdx = k; rec.pos = k + 1;
                highlightReciting(k);
                setRecNote(`تابعتُ ${toAr(rec.pos)} / ${toAr(rec.exp.length)} كلمة`);
                return;
            }
        }
        // no match within the look-ahead window → treat as noise, keep the cursor
    }
    // A detected pause seals the last-matched word as a stop and lights it up.
    function markAutoStop() {
        if (rec.lastIdx < 0 || rec.lastIdx >= rec.exp.length) return;
        const e = rec.exp[rec.lastIdx], key = e.ayah + ':' + e.wpos;
        if (state.stops.has(key)) return;
        state.stops.add(key);
        const b = els.passage.querySelector(`.wp-word[data-key="${key.replace(/"/g, '\\"')}"]`);
        if (b) b.classList.add('wp-stopped');
        updateCount();
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
        els.resultCard.hidden = false;
        els.resultCard.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }

    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
    else init();
})();
