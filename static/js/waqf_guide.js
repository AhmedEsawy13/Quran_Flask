/* ═══════════════════════════════════════════════════════════════════
   Waqf Guide — compare how the installed reciters stop in a chosen verse.

   Pick / search a verse → see (A) the verse with every attested stop point,
   (B) a matrix comparing where each reciter stops (align vs انفرد), and
   (C) per-reciter how each one recited it, with their repeats.

   Endpoints:
     GET /api/surahs
     GET /api/surahs/<s>/ayahs
     GET /api/waqf/<s>/<a>   → per-reciter stops + repeats + union
   ═══════════════════════════════════════════════════════════════════ */
(function () {
    'use strict';
    const $ = id => document.getElementById(id);
    const toAr = n => String(n).replace(/[0-9]/g, d => '٠١٢٣٤٥٦٧٨٩'[d]);
    const fromAr = s => String(s).replace(/[٠-٩]/g, d => '٠١٢٣٤٥٦٧٨٩'.indexOf(d));

    // Printed-mushaf waqf symbols → meaning + style class.
    const WAQF_SYM = {
        'م':  { name: 'لازم',       cls: 'must',  desc: 'وقف لازم — يجب الوقف' },
        'لا': { name: 'لا وقف',     cls: 'no',    desc: 'لا يوقف عليه' },
        'ق':  { name: 'الوقف أولى', cls: 'pstop', desc: 'الوقف أولى (قلى)' },
        'ص':  { name: 'الوصل أولى', cls: 'pcont', desc: 'الوصل أولى (صلى)' },
        'ج':  { name: 'جائز',       cls: 'ok',    desc: 'وقف جائز' },
        'س':  { name: 'سكتة',       cls: 'sakt',  desc: 'سكتة لطيفة بلا تنفّس' },
        'ع':  { name: 'معانقة',     cls: 'muan',  desc: 'وقف المعانقة — يُوقف على أحد الموضعين فقط' },
    };
    const symMeta = s => WAQF_SYM[s] || { name: s, cls: 'ok', desc: s };

    // Breath presets (max comfortable seconds per breath).
    const BREATH = { short: 7, medium: 13, long: 20 };

    const els = {
        surah: $('wq-surah'), ayah: $('wq-ayah'), search: $('wq-search'),
        prev: $('wq-prev'), next: $('wq-next'), theme: $('wq-theme'), status: $('wq-status'),
        verseCard: $('wq-verse-card'), verseTitle: $('wq-verse-title'), verseMeta: $('wq-verse-meta'),
        verseFlow: $('wq-verse-flow'),
        recCard: $('wq-rec-card'), breathPicker: $('wq-breath-picker'),
        recSummary: $('wq-rec-summary'), recPlan: $('wq-rec-plan'),
        matrixCard: $('wq-matrix-card'), matrix: $('wq-matrix'), matrixLegend: $('wq-matrix-legend'),
        recitersCard: $('wq-reciters-card'), reciters: $('wq-reciters'),
    };

    const state = { surahs: [], surah: 2, ayah: 255, ayahCount: {}, data: null, busy: false, breathL: BREATH.medium };

    /* ── status toast ─────────────────────────────────────────── */
    let toastId = 0;
    function setStatus(msg, isErr) {
        clearTimeout(toastId);
        if (!msg) { els.status.classList.remove('wq-show'); return; }
        els.status.textContent = msg;
        els.status.classList.toggle('wq-err', !!isErr);
        els.status.classList.add('wq-show');
        if (!isErr) toastId = setTimeout(() => els.status.classList.remove('wq-show'), 1600);
    }

    /* ── theme ────────────────────────────────────────────────── */
    function initTheme() {
        const saved = localStorage.getItem('quranApp_theme');
        const dark = saved ? saved === 'dark' : window.matchMedia('(prefers-color-scheme: dark)').matches;
        applyTheme(dark);
    }
    function applyTheme(dark) {
        document.body.classList.toggle('wq-dark', dark);
        els.theme.querySelector('i').className = dark ? 'fas fa-sun' : 'fas fa-moon';
    }
    els.theme.addEventListener('click', () => {
        const dark = !document.body.classList.contains('wq-dark');
        applyTheme(dark);
        localStorage.setItem('quranApp_theme', dark ? 'dark' : 'light');
    });

    /* ── data loading ─────────────────────────────────────────── */
    async function loadSurahs() {
        const resp = await fetch('/api/surahs');
        state.surahs = await resp.json();
        els.surah.innerHTML = state.surahs.map(s => {
            const num = s.number ?? s, name = s.name ?? `سورة ${num}`;
            return `<option value="${num}">${toAr(num)}. ${name}</option>`;
        }).join('');
    }
    function surahName(num) {
        const s = state.surahs.find(x => (x.number ?? x) === num);
        return s ? (s.name ?? '') : '';
    }
    async function loadAyahOptions(surah) {
        if (!state.ayahCount[surah]) {
            const resp = await fetch(`/api/surahs/${surah}/ayahs`);
            const list = await resp.json();
            state.ayahCount[surah] = Array.isArray(list) ? list.length : 0;
        }
        const n = state.ayahCount[surah] || 0;
        els.ayah.innerHTML = Array.from({ length: n }, (_, i) =>
            `<option value="${i + 1}">${toAr(i + 1)}</option>`).join('');
    }

    async function loadVerse(surah, ayah) {
        if (state.busy) return;
        state.busy = true;
        setStatus('جارٍ التحميل…');
        try {
            const resp = await fetch(`/api/waqf/${surah}/${ayah}`);
            if (!resp.ok) throw new Error('load failed');
            state.data = await resp.json();
            state.surah = surah; state.ayah = ayah;
            els.surah.value = String(surah);
            els.ayah.value = String(ayah);
            render(state.data);
            setStatus('');
            const url = new URL(location.href);
            url.searchParams.set('surah', surah); url.searchParams.set('ayah', ayah);
            history.replaceState(null, '', url);
        } catch (e) {
            setStatus('تعذّر تحميل بيانات هذه الآية', true);
        } finally {
            state.busy = false;
            updateStepper();
        }
    }
    function updateStepper() {
        els.prev.disabled = state.ayah <= 1;
        els.next.disabled = state.ayah >= (state.ayahCount[state.surah] || Infinity);
    }

    /* ── render ───────────────────────────────────────────────── */
    /* ── segment audio (seek-and-stop in a reciter's surah mp3) ─────── */
    const audio = new Audio();
    audio.preload = 'none';
    let audioStopAt = null, playingBtn = null;
    function clearPlaying() {
        if (playingBtn) { const i = playingBtn.querySelector('i'); if (i) i.className = playingBtn.dataset.icon || 'fas fa-play'; playingBtn.classList.remove('wq-playing'); }
        playingBtn = null;
    }
    audio.addEventListener('timeupdate', () => {
        if (audioStopAt != null && audio.currentTime >= audioStopAt) { audio.pause(); audioStopAt = null; clearPlaying(); }
    });
    audio.addEventListener('ended', () => { audioStopAt = null; clearPlaying(); });
    function playSegment(url, absStart, absEnd, btn) {
        if (!url || absEnd <= absStart) return;
        if (playingBtn === btn && !audio.paused) { audio.pause(); audioStopAt = null; clearPlaying(); return; }
        clearPlaying();
        const begin = () => { try { audio.currentTime = absStart; } catch (e) {} audioStopAt = absEnd; audio.play().catch(() => {}); };
        playingBtn = btn;
        if (btn) { btn.classList.add('wq-playing'); const i = btn.querySelector('i'); if (i) { btn.dataset.icon = i.className; i.className = 'fas fa-pause'; } }
        if (audio.src !== url) { audio.src = url; audio.addEventListener('loadedmetadata', begin, { once: true }); audio.load(); }
        else begin();
    }
    // play a reciter's own segment that ENDS at one of their stop words
    function playReciterStop(d, rid, toWpos, btn) {
        const det = d.per_reciter[rid];
        if (!det || !det.audio_url) return;
        const stops = (det.stops || []).slice().sort((a, b) => a.wpos - b.wpos);
        const idx = stops.findIndex(s => s.wpos === toWpos);
        if (idx < 0) return;
        const startT = idx > 0 ? stops[idx - 1].time : 0;
        playSegment(det.audio_url, det.verse_start + startT, det.verse_start + stops[idx].time, btn);
    }

    // Classify printed-mushaf marks into breath rules.
    function waqfCategories(d) {
        const lazim = new Set(), forbidden = new Set(), saktah = new Set(), positive = new Set();
        (d.mushafs || []).forEach(m => m.marks.forEach(mk => {
            if (mk.symbol === 'م') lazim.add(mk.wpos);
            else if (mk.symbol === 'لا') forbidden.add(mk.wpos);
            else if (mk.symbol === 'س') saktah.add(mk.wpos);
            if (['م', 'ج', 'ق', 'ص', 'ع'].includes(mk.symbol)) positive.add(mk.wpos);
        }));
        forbidden.forEach(w => { if (positive.has(w)) forbidden.delete(w); }); // a real stop elsewhere wins
        return { lazim, forbidden, saktah };
    }

    function render(d) {
        clearPlaying(); audio.pause();
        renderVerse(d);
        renderRecommendation(d);
        renderMatrix(d);
        renderReciters(d);
    }

    /* ── breath recommendation ─────────────────────────────────── */
    function cumAt(d, wpos) {
        const t = d.ref_times && d.ref_times[wpos];
        return (typeof t === 'number') ? t : 0;
    }
    // Greedy plan: keep each breath ≤ L seconds, breathing only at attested
    // reciter stops — but ALWAYS stop at a وقف لازم (م, mandatory hard-cut),
    // and NEVER breathe at a سكتة (س, pause-without-breath) or a لا (no-stop).
    function recommendBreaths(d, L) {
        const cats = waqfCategories(d);
        const lastW = d.words.length - 1;
        const mandatory = [...cats.lazim].filter(w => w < lastW).sort((a, b) => a - b);
        let optional = (d.union_stops || []).map(u => u.wpos)
            .filter(w => !cats.saktah.has(w) && !cats.forbidden.has(w) && !cats.lazim.has(w))
            .sort((a, b) => a - b);

        const breaths = [];
        let prevWpos = -1, prevCum = 0;
        for (const spanEnd of [...mandatory, lastW]) {       // lazim points are hard cuts
            const opts = optional.filter(w => w > prevWpos && w < spanEnd);
            let curCum = prevCum, i = 0;
            while (i < opts.length) {
                if (cumAt(d, spanEnd) - curCum <= L) break;  // rest of span fits in one breath
                let pick = -1;
                for (let j = i; j < opts.length; j++) {
                    if (cumAt(d, opts[j]) - curCum <= L) pick = j; else break;
                }
                if (pick === -1) pick = i;                   // nothing within L → forced stop
                breaths.push(opts[pick]); curCum = cumAt(d, opts[pick]); i = pick + 1;
            }
            if (spanEnd !== lastW) breaths.push(spanEnd);    // the mandatory breath itself
            prevWpos = spanEnd; prevCum = cumAt(d, spanEnd);
        }
        return { breaths, mandatory: cats.lazim, saktah: cats.saktah };
    }
    function renderRecommendation(d) {
        const canPlan = !!d.ref_times && d.words.length > 0;
        els.recCard.hidden = !canPlan;
        if (!canPlan) return;
        const L = state.breathL;
        const { breaths, mandatory, saktah } = recommendBreaths(d, L);
        const lastW = d.words.length - 1;
        const bounds = [-1, ...breaths, lastW];
        const nBreaths = bounds.length - 1;
        const ref = d.per_reciter[d.ref_reciter];

        const label = L <= BREATH.short ? 'قصير' : L >= BREATH.long ? 'طويل' : 'متوسط';
        let summary = `بنَفَس <b>${label}</b> (~${toAr(L)}ث للنفَس) تُقرأ الآية في `
            + `<b>${toAr(nBreaths)}</b> ${nBreaths === 1 ? 'نفَس واحد' : (nBreaths === 2 ? 'نفَسين' : 'أنفاس')}`
            + ` — قِف عند المواضع المُبيّنة.`;
        if (mandatory.size) summary += ` <span class="wq-must-note">يجب الوقف عند علامة اللزوم (م).</span>`;
        if (saktah.size) summary += ` <span class="wq-sakt-note">السكتة (س) ليست موضع تنفّس.</span>`;
        els.recSummary.innerHTML = summary;

        els.recPlan.innerHTML = '';
        for (let k = 0; k < bounds.length - 1; k++) {
            const from = bounds[k] + 1, to = bounds[k + 1];
            const segDur = cumAt(d, to) - (k === 0 ? 0 : cumAt(d, bounds[k]));
            const isLast = k === bounds.length - 2;
            const endsMandatory = !isLast && mandatory.has(to);
            const line = document.createElement('div');
            line.className = 'wq-rec-line' + (segDur > L + 0.5 ? ' wq-rec-over' : '');

            const num = document.createElement('span');
            num.className = 'wq-rec-num'; num.textContent = toAr(k + 1);

            const play = document.createElement('button');
            play.className = 'wq-play'; play.type = 'button';
            play.title = 'استمع لهذا المقطع'; play.setAttribute('aria-label', 'استماع');
            play.innerHTML = '<i class="fas fa-play"></i>';
            if (ref && ref.audio_url) {
                const absStart = ref.verse_start + (from > 0 ? cumAt(d, from - 1) : 0);
                const absEnd = ref.verse_start + cumAt(d, to);
                play.addEventListener('click', () => playSegment(ref.audio_url, absStart, absEnd, play));
            } else play.disabled = true;

            const words = document.createElement('span');
            words.className = 'wq-rec-words';
            words.textContent = d.words.slice(from, to + 1).join(' ');

            const dur = document.createElement('span');
            dur.className = 'wq-rec-dur';
            dur.innerHTML = (endsMandatory ? '<span class="wq-must-badge">لازم</span> ' : '')
                + `<i class="fas fa-${isLast ? 'flag-checkered' : 'lungs'}"></i> ${toAr(segDur.toFixed(1))}ث`;

            line.append(num, play, words, dur);
            els.recPlan.appendChild(line);
        }
    }

    function stopChip(u, total) {
        const chip = document.createElement('span');
        chip.className = 'wq-chip' + (u.solo ? ' wq-chip-solo' : '');
        chip.style.setProperty('--s', (u.count / total).toFixed(2));
        const names = u.reciters.map(reciterName).join('، ');
        const dur = `~${toAr(u.avg_duration.toFixed(1))}ث`;
        if (u.solo) {
            chip.innerHTML = `<i class="fas fa-pause"></i><b>انفرد</b><span>${reciterName(u.reciters[0])}</span><span class="wq-chip-dur">${dur}</span>`;
            chip.title = `انفرد به: ${names}`;
        } else {
            chip.innerHTML = `<i class="fas fa-pause"></i><b>${toAr(u.count)}/${toAr(total)}</b><span class="wq-chip-dur">${dur}</span>`;
            chip.title = `يقف عنده: ${names} — ${dur} من بداية الآية`;
        }
        return chip;
    }

    function renderVerse(d) {
        els.verseCard.hidden = false;
        els.verseTitle.textContent = `${surahName(d.surah) ? 'سورة ' + surahName(d.surah) + ' · ' : ''}آية ${toAr(d.ayah)}`;
        const nStops = d.union_stops.length;
        els.verseMeta.textContent =
            `${toAr(d.reciters_total)} قرّاء · ${toAr(nStops)} ${nStops === 1 ? 'موضع وقف' : 'مواضع وقف'}`
            + (d.full_duration ? ` · ~${toAr(d.full_duration.toFixed(0))}ث` : '');

        const flow = els.verseFlow;
        flow.innerHTML = '';
        const uByWpos = new Map(d.union_stops.map(u => [u.wpos, u]));
        d.words.forEach((text, wpos) => {
            const w = document.createElement('span');
            w.className = 'wq-word';
            w.textContent = text;
            const u = uByWpos.get(wpos);
            if (u) w.classList.add('wq-word-stop');
            flow.appendChild(w);
            if (u) flow.appendChild(stopChip(u, d.reciters_total));
        });
    }

    function renderMatrix(d) {
        const mushafs = d.mushafs || [];
        // columns = union of reciter stops AND printed-mushaf waqf marks
        const posSet = new Set(d.union_stops.map(u => u.wpos));
        mushafs.forEach(m => m.marks.forEach(mk => posSet.add(mk.wpos)));
        const cols = [...posSet].sort((a, b) => a - b);
        els.matrixCard.hidden = cols.length === 0;
        if (!cols.length) { els.matrix.innerHTML = ''; renderMatrixLegend(d, []); return; }

        const uByWpos = new Map(d.union_stops.map(u => [u.wpos, u]));
        const markOf = (m, wpos) => { const f = m.marks.find(x => x.wpos === wpos); return f ? f.symbol : null; };
        const reciterStops = wpos => d.reciters.some(r => (d.per_reciter[r.id].stops || []).some(s => s.wpos === wpos));

        // header
        let head = '<thead><tr><th class="wq-rname">الموضع ←</th>';
        cols.forEach(wpos => {
            const u = uByWpos.get(wpos);
            const cls = u && u.solo ? ' wq-col-solo' : (!reciterStops(wpos) ? ' wq-col-mushaf-only' : '');
            head += `<th class="${cls}"><div class="wq-col-word">${d.words[wpos] || ''}</div>`
                + `<div class="wq-col-meta">كلمة ${toAr(wpos + 1)}</div></th>`;
        });
        head += '</tr></thead>';

        let body = '<tbody>';
        // printed-mushaf rows (the prescribed stops)
        mushafs.forEach(m => {
            body += `<tr class="wq-row-mushaf"><td class="wq-rname"><span class="wq-mushaf-name" data-m="${m.id}"><i class="fas fa-book-quran"></i> ${m.name}</span></td>`;
            cols.forEach(wpos => {
                const sym = markOf(m, wpos);
                if (sym) {
                    const meta = symMeta(sym);
                    body += `<td><span class="wq-wsym wq-w-${meta.cls}" title="${meta.name} — ${meta.desc}">${sym}</span></td>`;
                } else body += `<td><span class="wq-cell-empty">·</span></td>`;
            });
            body += '</tr>';
        });
        // consensus row
        body += '<tr class="wq-row-consensus"><td class="wq-rname">اتفاق القرّاء</td>';
        cols.forEach(wpos => {
            const u = uByWpos.get(wpos);
            body += `<td class="${u && u.solo ? 'wq-col-solo' : ''}">${u ? toAr(u.count) + '/' + toAr(d.reciters_total) : '<span class="wq-cell-empty">·</span>'}</td>`;
        });
        body += '</tr>';
        // one row per reciter
        d.reciters.forEach(r => {
            const det = d.per_reciter[r.id];
            const timeByWpos = new Map((det.stops || []).map(s => [s.wpos, s.time]));
            body += `<tr><td class="wq-rname">${r.name_ar}</td>`;
            cols.forEach(wpos => {
                const u = uByWpos.get(wpos);
                const solo = u && u.solo ? ' wq-col-solo' : '';
                if (timeByWpos.has(wpos)) {
                    body += `<td class="${solo}"><button class="wq-cell-stop wq-cell-play${u && u.solo ? ' wq-solo' : ''}" type="button" data-rid="${r.id}" data-wpos="${wpos}" title="استمع لمقطع ${r.name_ar} حتى هذا الموضع"><i class="fas fa-play"></i>${toAr(timeByWpos.get(wpos).toFixed(1))}</button></td>`;
                } else {
                    body += `<td class="${solo}"><span class="wq-cell-empty">·</span></td>`;
                }
            });
            body += '</tr>';
        });
        body += '</tbody>';
        els.matrix.innerHTML = head + body;

        const symsHere = [...new Set(mushafs.flatMap(m => m.marks.map(mk => mk.symbol)))];
        renderMatrixLegend(d, symsHere);
    }

    function renderMatrixLegend(d, syms) {
        if (!els.matrixLegend) return;
        const parts = (d.mushafs || []).map(m => `<span><span class="wq-lg wq-mushaf-dot" data-m="${m.id}"></span> ${m.name}</span>`);
        syms.sort((a, b) => Object.keys(WAQF_SYM).indexOf(a) - Object.keys(WAQF_SYM).indexOf(b))
            .forEach(s => { const mt = symMeta(s); parts.push(`<span><span class="wq-wsym wq-w-${mt.cls}">${s}</span> ${mt.name}</span>`); });
        els.matrixLegend.innerHTML = parts.join('');
    }

    function renderReciters(d) {
        els.recitersCard.hidden = false;
        const wrap = els.reciters;
        wrap.innerHTML = '';
        const wordText = wp => d.words[wp] || `كلمة ${toAr(wp + 1)}`;
        // all positions any printed mushaf marks as a waqf — to measure how
        // closely a reciter stops only where a mushaf prescribes.
        const mushafPos = new Set((d.mushafs || []).flatMap(m => m.marks.map(mk => mk.wpos)));

        d.reciters.forEach(r => {
            const det = d.per_reciter[r.id];
            const card = document.createElement('div');
            card.className = 'wq-reciter';

            const stopSet = new Map((det.stops || []).map(s => [s.wpos, s]));
            const soloSet = new Set(d.union_stops.filter(u => u.solo).map(u => u.wpos));
            const nStops = det.stops.length;
            const onMushaf = (det.stops || []).filter(s => mushafPos.has(s.wpos)).length;

            const head = document.createElement('div');
            head.className = 'wq-reciter-head';
            head.innerHTML = `<span class="wq-reciter-name">${r.name_ar}</span>`
                + `<span class="wq-reciter-stats"><span><b>${toAr(nStops)}</b> ${nStops === 1 ? 'وقفة' : 'وقفات'}</span>`
                + (mushafPos.size ? `<span class="wq-adhere" title="عدد وقفاته الواقعة على موضع وقف في أحد المصاحف"><i class="fas fa-book-quran"></i> موافقة المصحف <b>${toAr(onMushaf)}/${toAr(nStops)}</b></span>` : '')
                + (det.repeats.length ? `<span><b>${toAr(det.repeats.length)}</b> ${det.repeats.length === 1 ? 'إعادة' : 'إعادات'}</span>` : '')
                + `<span>~<b>${toAr(det.duration.toFixed(0))}</b>ث</span></span>`;
            card.appendChild(head);

            // segmented verse for this reciter
            const flow = document.createElement('div');
            flow.className = 'wq-reciter-flow';
            flow.dir = 'rtl';
            d.words.forEach((text, wpos) => {
                const w = document.createElement('span');
                w.className = 'wq-word';
                w.style.fontSize = '1.5rem';
                w.textContent = text;
                flow.appendChild(w);
                const s = stopSet.get(wpos);
                if (s) {
                    const chip = document.createElement('button');
                    chip.type = 'button';
                    chip.className = 'wq-mini-stop' + (soloSet.has(wpos) ? ' wq-solo' : '');
                    chip.title = `استمع لمقطع ${r.name_ar} حتى هنا`;
                    chip.innerHTML = `<i class="fas fa-play" style="margin-inline-end:3px"></i>${toAr(s.time.toFixed(1))}ث`;
                    if (det.audio_url) chip.addEventListener('click', () => playReciterStop(d, r.id, wpos, chip));
                    else chip.disabled = true;
                    flow.appendChild(chip);
                }
            });
            card.appendChild(flow);

            // repeats for this reciter
            if (det.repeats.length) {
                const reps = document.createElement('div');
                reps.className = 'wq-reciter-reps';
                det.repeats.forEach(rp => {
                    const line = document.createElement('div');
                    line.innerHTML = rp.from_wpos === rp.to_wpos
                        ? `<span class="wq-rep-tag"><i class="fas fa-rotate-left"></i> إعادة</span> كرّر «${wordText(rp.from_wpos)}»`
                        : `<span class="wq-rep-tag"><i class="fas fa-rotate-left"></i> إعادة</span> وقف عند «${wordText(rp.from_wpos)}» ثم أعاد من «${wordText(rp.to_wpos)}»`;
                    reps.appendChild(line);
                });
                card.appendChild(reps);
            }
            wrap.appendChild(card);
        });
    }

    const reciterName = id => {
        const r = (state.data && state.data.reciters || []).find(x => x.id === id);
        return r ? r.name_ar : id;
    };

    /* ── search ───────────────────────────────────────────────── */
    function parseSearch(raw) {
        const q = fromAr(raw.trim());
        // "2:255" or "2 255" or "2،255"
        let m = q.match(/(\d{1,3})\s*[:،,\s]\s*(\d{1,3})/);
        if (m) return { surah: +m[1], ayah: +m[2] };
        // "name 255" — match a surah name then a number
        m = q.match(/^(.+?)\s+(\d{1,3})\s*$/);
        if (m) {
            const s = findSurahByName(m[1]);
            if (s) return { surah: s, ayah: +m[2] };
        }
        // pure surah name → ayah 1
        const s = findSurahByName(q);
        if (s) return { surah: s, ayah: 1 };
        return null;
    }
    function findSurahByName(name) {
        const norm = t => t.replace(/[أإآ]/g, 'ا').replace(/ة/g, 'ه').replace(/\s|ال/g, '');
        const target = norm(name);
        if (!target) return null;
        const hit = state.surahs.find(s => norm(s.name || '').includes(target));
        return hit ? (hit.number ?? null) : null;
    }
    async function doSearch() {
        const parsed = parseSearch(els.search.value);
        if (!parsed) { setStatus('اكتب رقم السورة والآية، مثل ٢:٢٥٥', true); return; }
        if (parsed.surah < 1 || parsed.surah > 114) { setStatus('رقم سورة غير صحيح', true); return; }
        await loadAyahOptions(parsed.surah);
        const max = state.ayahCount[parsed.surah] || 1;
        const ayah = Math.min(Math.max(1, parsed.ayah), max);
        await loadVerse(parsed.surah, ayah);
    }

    /* ── events ───────────────────────────────────────────────── */
    els.surah.addEventListener('change', async () => {
        const s = +els.surah.value;
        await loadAyahOptions(s);
        await loadVerse(s, 1);
    });
    els.ayah.addEventListener('change', () => loadVerse(+els.surah.value, +els.ayah.value));
    els.prev.addEventListener('click', () => { if (state.ayah > 1) loadVerse(state.surah, state.ayah - 1); });
    els.next.addEventListener('click', () => loadVerse(state.surah, state.ayah + 1));
    els.search.addEventListener('keydown', e => { if (e.key === 'Enter') doSearch(); });
    if (els.breathPicker) els.breathPicker.addEventListener('click', e => {
        const btn = e.target.closest('.wq-breath-btn');
        if (!btn) return;
        state.breathL = parseInt(btn.dataset.l, 10) || BREATH.medium;
        els.breathPicker.querySelectorAll('.wq-breath-btn').forEach(b => b.classList.toggle('wq-on', b === btn));
        if (state.data) renderRecommendation(state.data);
    });
    // matrix cell → play that reciter's segment up to the clicked stop
    if (els.matrix) els.matrix.addEventListener('click', e => {
        const cell = e.target.closest('.wq-cell-play');
        if (!cell || !state.data) return;
        playReciterStop(state.data, cell.dataset.rid, parseInt(cell.dataset.wpos, 10), cell);
    });

    /* ── init ─────────────────────────────────────────────────── */
    async function init() {
        initTheme();
        try {
            await loadSurahs();
            const p = new URLSearchParams(location.search);
            const surah = Math.min(Math.max(1, parseInt(p.get('surah'), 10) || 2), 114);
            await loadAyahOptions(surah);
            const ayah = Math.min(Math.max(1, parseInt(p.get('ayah'), 10) || (surah === 2 ? 255 : 1)),
                state.ayahCount[surah] || 1);
            await loadVerse(surah, ayah);
        } catch (e) {
            setStatus('تعذّر تهيئة الصفحة', true);
        }
    }
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
    else init();
})();
