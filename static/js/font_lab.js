/* ═══════════════════════════════════════════════════════════════════
   Font Lab — toggle / step OpenType features on Quran fonts.
   Catalog: window.AtharFontLabCatalog (font_lab_catalog.js)
   ═══════════════════════════════════════════════════════════════════ */
(function () {
    'use strict';

    const CAT = window.AtharFontLabCatalog;
    if (!CAT) {
        console.error('AtharFontLabCatalog missing');
        return;
    }

    const STORAGE_KEY = 'athar_font_lab_v2';
    const $ = (id) => document.getElementById(id);

    const els = {
        page: $('fl-page'),
        font: $('fl-font'),
        size: $('fl-size'),
        leading: $('fl-leading'),
        split: $('fl-split'),
        reset: $('fl-reset'),
        copy: $('fl-copy'),
        fontNote: $('fl-font-note'),
        cssValue: $('fl-css-value'),
        features: $('fl-features'),
        samples: $('fl-samples'),
        custom: $('fl-custom'),
        customPreview: $('fl-custom-preview'),
        toast: $('fl-toast'),
        board: $('fl-board'),
    };

    const state = {
        fontId: CAT.FONTS[0]?.id || 'digital_khatt',
        // tag -> integer value (0 = off, 1..N = font-feature-settings value)
        features: Object.create(null),
        size: 34,
        leading: 2,
        split: false,
        custom: '',
    };

    let toastTimer = 0;

    function currentFont() {
        return CAT.FONTS.find((f) => f.id === state.fontId) || CAT.FONTS[0];
    }

    function supportedSet(font) {
        return new Set(font.supportedTags || []);
    }

    function featureDef(tag) {
        return CAT.FEATURES.find((f) => f.tag === tag);
    }

    function featureMax(feat, font) {
        const fromFont = font.featureMax && font.featureMax[feat.tag];
        if (Number.isFinite(fromFont) && fromFont > 0) return fromFont;
        const fromFeat = Number(feat.max);
        return Number.isFinite(fromFeat) && fromFeat > 0 ? fromFeat : 1;
    }

    function normalizeFeaturesObject(raw) {
        const out = Object.create(null);
        if (!raw || typeof raw !== 'object') return out;
        Object.keys(raw).forEach((tag) => {
            const v = raw[tag];
            if (v === true) out[tag] = 1;
            else if (typeof v === 'number' && v > 0) out[tag] = Math.floor(v);
        });
        return out;
    }

    function buildFeatureSettings(font) {
        const ok = supportedSet(font);
        const parts = [];
        Object.keys(state.features)
            .sort()
            .forEach((tag) => {
                if (!ok.has(tag)) return;
                const value = Number(state.features[tag]) || 0;
                if (value <= 0) return;
                const feat = featureDef(tag);
                const max = feat ? featureMax(feat, font) : value;
                const clamped = Math.min(max, Math.max(1, value));
                parts.push(`'${tag}' ${clamped}`);
            });
        return parts.length ? parts.join(', ') : 'normal';
    }

    function showToast(msg) {
        if (!els.toast) return;
        els.toast.textContent = msg;
        els.toast.hidden = false;
        clearTimeout(toastTimer);
        toastTimer = setTimeout(() => {
            els.toast.hidden = true;
        }, 1600);
    }

    function persist() {
        try {
            localStorage.setItem(STORAGE_KEY, JSON.stringify({
                fontId: state.fontId,
                features: state.features,
                size: state.size,
                leading: state.leading,
                split: state.split,
                custom: state.custom,
            }));
        } catch (_) { /* ignore quota */ }
    }

    function restore() {
        try {
            const raw = localStorage.getItem(STORAGE_KEY)
                || localStorage.getItem('athar_font_lab_v1');
            if (!raw) return;
            const data = JSON.parse(raw);
            if (data.fontId && CAT.FONTS.some((f) => f.id === data.fontId)) {
                state.fontId = data.fontId;
            }
            state.features = normalizeFeaturesObject(data.features);
            if (Number.isFinite(data.size)) state.size = data.size;
            if (Number.isFinite(data.leading)) state.leading = data.leading;
            if (typeof data.split === 'boolean') state.split = data.split;
            if (typeof data.custom === 'string') state.custom = data.custom;
        } catch (_) { /* ignore */ }
    }

    function fillFontSelect() {
        els.font.innerHTML = '';
        CAT.FONTS.forEach((font) => {
            const opt = document.createElement('option');
            opt.value = font.id;
            opt.textContent = font.labelAr;
            els.font.appendChild(opt);
        });
        els.font.value = state.fontId;
    }

    function renderFeaturePanel() {
        const font = currentFont();
        const ok = supportedSet(font);
        const byGroup = new Map(CAT.GROUPS.map((g) => [g.id, []]));
        CAT.FEATURES.forEach((feat) => {
            if (!byGroup.has(feat.group)) byGroup.set(feat.group, []);
            byGroup.get(feat.group).push(feat);
        });

        const frag = document.createDocumentFragment();
        const title = document.createElement('h2');
        title.textContent = 'الخصائص';
        frag.appendChild(title);

        const tip = document.createElement('p');
        tip.className = 'fl-features-tip';
        tip.textContent = 'للبدائل المتدرجة (cv01/cv02): ارفع الرقم لتجربة شكل كاف/ميم آخر — 0 = إيقاف.';
        frag.appendChild(tip);

        CAT.GROUPS.forEach((group) => {
            const feats = byGroup.get(group.id) || [];
            if (!feats.length) return;
            const fieldset = document.createElement('fieldset');
            fieldset.className = 'fl-feature-group';
            const legend = document.createElement('legend');
            legend.textContent = group.labelAr;
            fieldset.appendChild(legend);
            const list = document.createElement('div');
            list.className = 'fl-feature-list';

            feats.forEach((feat) => {
                const supported = ok.has(feat.tag);
                const max = featureMax(feat, font);
                const value = supported ? (Number(state.features[feat.tag]) || 0) : 0;
                const row = document.createElement('div');
                row.className = 'fl-feature' + (supported ? '' : ' is-unsupported')
                    + (max > 1 ? ' is-stepped' : '');

                if (max > 1) {
                    const lab = document.createElement('label');
                    lab.className = 'fl-feature-label';
                    lab.htmlFor = `fl-feat-${feat.tag}`;
                    lab.innerHTML = `${feat.labelAr} <span class="fl-feature-tag">${feat.tag}</span>`;

                    const stepper = document.createElement('div');
                    stepper.className = 'fl-stepper';
                    const dec = document.createElement('button');
                    dec.type = 'button';
                    dec.className = 'fl-step-btn';
                    dec.dataset.tag = feat.tag;
                    dec.dataset.delta = '-1';
                    dec.textContent = '−';
                    dec.disabled = !supported || value <= 0;
                    dec.setAttribute('aria-label', `إنقاص ${feat.tag}`);

                    const input = document.createElement('input');
                    input.type = 'number';
                    input.id = `fl-feat-${feat.tag}`;
                    input.className = 'fl-step-input';
                    input.dataset.tag = feat.tag;
                    input.min = '0';
                    input.max = String(max);
                    input.value = String(value);
                    input.disabled = !supported;
                    input.setAttribute('aria-label', `قيمة ${feat.tag}`);

                    const inc = document.createElement('button');
                    inc.type = 'button';
                    inc.className = 'fl-step-btn';
                    inc.dataset.tag = feat.tag;
                    inc.dataset.delta = '1';
                    inc.textContent = '+';
                    inc.disabled = !supported || value >= max;
                    inc.setAttribute('aria-label', `زيادة ${feat.tag}`);

                    const range = document.createElement('span');
                    range.className = 'fl-step-range';
                    range.textContent = `0–${max}`;

                    stepper.appendChild(dec);
                    stepper.appendChild(input);
                    stepper.appendChild(inc);
                    stepper.appendChild(range);

                    const meta = document.createElement('span');
                    meta.className = 'fl-feature-meta';
                    meta.textContent = supported
                        ? (feat.noteAr || '')
                        : 'غير معرّف لهذا الخط';

                    row.appendChild(lab);
                    row.appendChild(stepper);
                    row.appendChild(meta);
                } else {
                    const lab = document.createElement('label');
                    lab.className = 'fl-feature-toggle';
                    const input = document.createElement('input');
                    input.type = 'checkbox';
                    input.dataset.tag = feat.tag;
                    input.checked = value > 0 && supported;
                    input.disabled = !supported;
                    const name = document.createElement('span');
                    name.className = 'fl-feature-label';
                    name.innerHTML = `${feat.labelAr} <span class="fl-feature-tag">${feat.tag}</span>`;
                    lab.appendChild(input);
                    lab.appendChild(name);

                    const meta = document.createElement('span');
                    meta.className = 'fl-feature-meta';
                    meta.textContent = supported
                        ? (feat.noteAr || '')
                        : 'غير معرّف لهذا الخط';

                    row.appendChild(lab);
                    row.appendChild(meta);
                }

                list.appendChild(row);
            });

            fieldset.appendChild(list);
            frag.appendChild(fieldset);
        });

        els.features.innerHTML = '';
        els.features.appendChild(frag);
    }

    function renderSamples() {
        const font = currentFont();
        els.samples.innerHTML = '';
        CAT.SAMPLES.forEach((sample) => {
            const card = document.createElement('article');
            card.className = 'fl-sample';
            card.dataset.sampleId = sample.id;

            const head = document.createElement('div');
            head.className = 'fl-sample-head';
            const title = document.createElement('h3');
            title.className = 'fl-sample-title';
            title.textContent = sample.labelAr;
            const hints = document.createElement('div');
            hints.className = 'fl-sample-hints';
            (sample.tagsHint || []).forEach((tag) => {
                const chip = document.createElement('span');
                chip.textContent = tag;
                hints.appendChild(chip);
            });
            head.appendChild(title);
            head.appendChild(hints);
            card.appendChild(head);

            if (sample.noteAr) {
                const note = document.createElement('p');
                note.className = 'fl-sample-note';
                note.textContent = sample.noteAr;
                card.appendChild(note);
            }

            if (state.split) {
                const compare = document.createElement('div');
                compare.className = 'fl-sample-compare';
                [
                    { off: true, label: 'بدون خصائص' },
                    { off: false, label: 'مع الخصائص' },
                ].forEach((pane) => {
                    const wrap = document.createElement('div');
                    wrap.className = 'fl-sample-pane' + (pane.off ? ' is-off' : '');
                    const lab = document.createElement('div');
                    lab.className = 'fl-sample-pane-label';
                    lab.textContent = pane.label;
                    const preview = document.createElement('div');
                    preview.className = 'fl-sample-preview';
                    preview.dir = 'rtl';
                    preview.textContent = sample.text;
                    preview.style.fontFamily = `'${font.family}', serif`;
                    wrap.appendChild(lab);
                    wrap.appendChild(preview);
                    compare.appendChild(wrap);
                });
                card.appendChild(compare);
            } else {
                const preview = document.createElement('div');
                preview.className = 'fl-sample-preview';
                preview.dir = 'rtl';
                preview.textContent = sample.text;
                preview.style.fontFamily = `'${font.family}', serif`;
                card.appendChild(preview);
            }

            els.samples.appendChild(card);
        });
    }

    function applyPreviewStyles() {
        const font = currentFont();
        const ffs = buildFeatureSettings(font);
        els.page.style.setProperty('--fl-font-size', `${state.size}px`);
        els.page.style.setProperty('--fl-line-height', String(state.leading));
        els.page.style.setProperty('--fl-features', ffs === 'normal' ? 'normal' : ffs);
        els.cssValue.textContent = ffs;

        els.page.classList.toggle('fl-colr-on', !!(font.colrPalette));
        els.board.classList.toggle('fl-split', state.split);

        if (els.fontNote) {
            const bits = [];
            if (font.noteAr) bits.push(font.noteAr);
            if (font.fileHint) bits.push(`الملف: ${font.fileHint}`);
            els.fontNote.textContent = bits.join(' · ');
            els.fontNote.hidden = !bits.length;
        }

        if (els.customPreview) {
            els.customPreview.style.fontFamily = `'${font.family}', serif`;
            els.customPreview.textContent = state.custom || '…';
        }

        els.samples.querySelectorAll('.fl-sample-preview').forEach((node) => {
            node.style.fontFamily = `'${font.family}', serif`;
        });
    }

    function setFeatureValue(tag, next) {
        const font = currentFont();
        const feat = featureDef(tag);
        if (!feat) return;
        if (!supportedSet(font).has(tag)) return;
        const max = featureMax(feat, font);
        const value = Math.min(max, Math.max(0, Math.floor(Number(next) || 0)));
        if (value <= 0) delete state.features[tag];
        else state.features[tag] = value;
        renderFeaturePanel();
        applyPreviewStyles();
        persist();
    }

    function refreshAll() {
        renderFeaturePanel();
        renderSamples();
        applyPreviewStyles();
        persist();
    }

    function resetFeatures() {
        state.features = Object.create(null);
        refreshAll();
        showToast('أُعيد الضبط');
    }

    async function copyCss() {
        const value = els.cssValue.textContent || 'normal';
        const snippet = `font-feature-settings: ${value};`;
        try {
            await navigator.clipboard.writeText(snippet);
            showToast('نُسخ إلى الحافظة');
        } catch (_) {
            showToast(snippet);
        }
    }

    function bind() {
        els.font.addEventListener('change', () => {
            state.fontId = els.font.value;
            refreshAll();
        });
        els.size.addEventListener('input', () => {
            state.size = Number(els.size.value) || 34;
            applyPreviewStyles();
            persist();
        });
        els.leading.addEventListener('input', () => {
            state.leading = (Number(els.leading.value) || 200) / 100;
            applyPreviewStyles();
            persist();
        });
        els.split.addEventListener('change', () => {
            state.split = els.split.value === 'on';
            renderSamples();
            applyPreviewStyles();
            persist();
        });
        els.reset.addEventListener('click', resetFeatures);
        els.copy.addEventListener('click', copyCss);
        els.custom.addEventListener('input', () => {
            state.custom = els.custom.value;
            applyPreviewStyles();
            persist();
        });

        els.features.addEventListener('change', (ev) => {
            const input = ev.target;
            if (!(input instanceof HTMLInputElement)) return;
            const tag = input.dataset.tag;
            if (!tag) return;
            if (input.type === 'checkbox') {
                setFeatureValue(tag, input.checked ? 1 : 0);
            } else if (input.type === 'number') {
                setFeatureValue(tag, input.value);
            }
        });

        els.features.addEventListener('click', (ev) => {
            const btn = ev.target.closest('.fl-step-btn');
            if (!btn || !els.features.contains(btn)) return;
            const tag = btn.dataset.tag;
            const delta = Number(btn.dataset.delta) || 0;
            if (!tag || !delta) return;
            const cur = Number(state.features[tag]) || 0;
            setFeatureValue(tag, cur + delta);
        });
    }

    function syncControlsFromState() {
        els.font.value = state.fontId;
        els.size.value = String(state.size);
        els.leading.value = String(Math.round(state.leading * 100));
        els.split.value = state.split ? 'on' : 'off';
        els.custom.value = state.custom;
    }

    restore();
    fillFontSelect();
    syncControlsFromState();
    bind();
    refreshAll();
})();
