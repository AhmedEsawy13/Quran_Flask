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

    const els = {
        surah: $('wq-surah'), ayah: $('wq-ayah'), search: $('wq-search'),
        prev: $('wq-prev'), next: $('wq-next'), theme: $('wq-theme'), status: $('wq-status'),
        verseCard: $('wq-verse-card'), verseTitle: $('wq-verse-title'), verseMeta: $('wq-verse-meta'),
        verseFlow: $('wq-verse-flow'),
        matrixCard: $('wq-matrix-card'), matrix: $('wq-matrix'),
        recitersCard: $('wq-reciters-card'), reciters: $('wq-reciters'),
    };

    const state = { surahs: [], surah: 2, ayah: 255, ayahCount: {}, data: null, busy: false };

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
    function render(d) {
        renderVerse(d);
        renderMatrix(d);
        renderReciters(d);
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
        els.matrixCard.hidden = d.union_stops.length === 0;
        if (!d.union_stops.length) { els.matrix.innerHTML = ''; return; }
        const stops = d.union_stops;
        // header: reciter col + one col per union stop
        let head = '<thead><tr><th class="wq-rname">القارئ</th>';
        stops.forEach(u => {
            const solo = u.solo ? ' wq-col-solo' : '';
            head += `<th class="${solo}"><div class="wq-col-word${solo}">${d.words[u.wpos] || ''}</div>`
                + `<div class="wq-col-meta">كلمة ${toAr(u.wpos + 1)}</div></th>`;
        });
        head += '</tr></thead>';

        // consensus row
        let body = '<tbody>';
        body += '<tr class="wq-row-consensus"><td class="wq-rname">الاتفاق</td>';
        stops.forEach(u => {
            body += `<td class="${u.solo ? 'wq-col-solo' : ''}">${toAr(u.count)}/${toAr(d.reciters_total)}</td>`;
        });
        body += '</tr>';

        // one row per reciter
        d.reciters.forEach(r => {
            const det = d.per_reciter[r.id];
            const timeByWpos = new Map((det.stops || []).map(s => [s.wpos, s.time]));
            body += `<tr><td class="wq-rname">${r.name_ar}</td>`;
            stops.forEach(u => {
                const solo = u.solo ? ' wq-col-solo' : '';
                if (timeByWpos.has(u.wpos)) {
                    const t = timeByWpos.get(u.wpos);
                    body += `<td class="${solo}"><span class="wq-cell-stop${u.solo ? ' wq-solo' : ''}"><i class="fas fa-pause"></i>${toAr(t.toFixed(1))}</span></td>`;
                } else {
                    body += `<td class="${solo}"><span class="wq-cell-empty">·</span></td>`;
                }
            });
            body += '</tr>';
        });
        body += '</tbody>';
        els.matrix.innerHTML = head + body;
    }

    function renderReciters(d) {
        els.recitersCard.hidden = false;
        const wrap = els.reciters;
        wrap.innerHTML = '';
        const wordText = wp => d.words[wp] || `كلمة ${toAr(wp + 1)}`;

        d.reciters.forEach(r => {
            const det = d.per_reciter[r.id];
            const card = document.createElement('div');
            card.className = 'wq-reciter';

            const stopSet = new Map((det.stops || []).map(s => [s.wpos, s]));
            const soloSet = new Set(d.union_stops.filter(u => u.solo).map(u => u.wpos));
            const nStops = det.stops.length;

            const head = document.createElement('div');
            head.className = 'wq-reciter-head';
            head.innerHTML = `<span class="wq-reciter-name">${r.name_ar}</span>`
                + `<span class="wq-reciter-stats"><span><b>${toAr(nStops)}</b> ${nStops === 1 ? 'وقفة' : 'وقفات'}</span>`
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
                    const chip = document.createElement('span');
                    chip.className = 'wq-mini-stop' + (soloSet.has(wpos) ? ' wq-solo' : '');
                    chip.innerHTML = `<i class="fas fa-pause" style="margin-inline-end:3px"></i>${toAr(s.time.toFixed(1))}ث`;
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
