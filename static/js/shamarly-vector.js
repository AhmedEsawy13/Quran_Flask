/* أثَر — الشمرلي drawn from the vector PDF (beta) in the reader's verse view.
 *
 * Every page the pipeline has built is served as a structured SVG (/api/shamarly/qvp-svg/NNN.svg:
 * line > ayah-fragment > word > path). This file cuts the words of one verse out of it and puts each one into its
 * .word-token as a small inline <svg>, so highlighting, click-to-play, waqf overlays and tajweed notes keep working on
 * the same elements the font rendering uses.
 *
 * Every word of a printed line gets the SAME vertical band (centred on the line's median ink centre) so the words keep
 * the printed relative heights exactly; only the horizontal extent is cropped to the word.
 *
 *     await window.ShamarlyVector.render(tokens, surah, ayah, pages)  -> true when the verse was drawn
 */
(function () {
    'use strict';

    const SVG_NS = 'http://www.w3.org/2000/svg';
    const BAND = 1.5;          // band height in line pitches
    const PAD = 2;             // horizontal padding around a word, page units
    const KEY = 'quranApp_shamarlyVector';
    const pageCache = new Map();
    let pagesPending = null;
    let host = null;

    function enabled() {
        try { return localStorage.getItem(KEY) === '1'; } catch (error) { return false; }
    }

    function setEnabled(on) {
        try { localStorage.setItem(KEY, on ? '1' : '0'); } catch (error) { /* private window */ }
    }

    function availablePages() {
        if (!pagesPending) {
            pagesPending = fetch('/api/shamarly/qvp-pages')
                .then((response) => (response.ok ? response.json() : { pages: [] }))
                .then((data) => new Set(Array.isArray(data.pages) ? data.pages : []))
                .catch(() => new Set());
        }
        return pagesPending;
    }

    function measuringHost() {
        if (!host) {
            host = document.createElementNS(SVG_NS, 'svg');
            host.setAttribute('aria-hidden', 'true');
            host.style.cssText = 'position:absolute;left:-99999px;top:0;width:10px;height:10px;overflow:hidden;pointer-events:none';
            document.body.appendChild(host);
        }
        return host;
    }

    function median(values) {
        const sorted = values.slice().sort((a, b) => a - b);
        const mid = sorted.length >> 1;
        return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
    }

    /** One page: word key -> {node, box, line}, the line centres, the line pitch, and the ayah-mark groups. */
    function loadPage(page) {
        let pending = pageCache.get(page);
        if (pending) return pending;
        pending = fetch(`/api/shamarly/qvp-svg/${String(page).padStart(3, '0')}.svg`)
            .then((response) => {
                if (!response.ok) throw new Error(`page ${page}: ${response.status}`);
                return response.text();
            })
            .then((text) => {
                const doc = new DOMParser().parseFromString(text, 'image/svg+xml');
                const root = document.importNode(doc.documentElement, true);
                const mount = measuringHost();
                mount.replaceChildren(root);
                const words = new Map();
                const marks = new Map();
                const centres = new Map();
                root.querySelectorAll('g.line').forEach((line) => {
                    const lineNo = Number(line.getAttribute('data-line'));
                    const ys = [];
                    line.querySelectorAll('g.word').forEach((node) => {
                        const box = node.getBBox();
                        if (!box.width || !box.height) return;
                        words.set(node.getAttribute('data-word-key'), { node, box, line: lineNo });
                        ys.push(box.y + box.height / 2);
                    });
                    line.querySelectorAll('g.ayah-mark').forEach((node) => {
                        const box = node.getBBox();
                        if (box.width && box.height) marks.set(node.getAttribute('data-ayah-key'), { node, box, line: lineNo });
                    });
                    if (ys.length) centres.set(lineNo, median(ys));
                });
                const lines = [...centres.keys()].sort((a, b) => a - b);
                const gaps = lines.slice(1).map((n, i) => (centres.get(n) - centres.get(lines[i])) / (n - lines[i]));
                const pitch = gaps.length ? median(gaps) : 45;
                // detach from the measuring host but keep the nodes alive for cloning
                const store = { words, marks, centres, pitch };
                words.forEach((entry) => { entry.paths = [...entry.node.querySelectorAll('path')].map((p) => p.cloneNode(true)); });
                marks.forEach((entry) => { entry.paths = [...entry.node.querySelectorAll('path')].map((p) => p.cloneNode(true)); });
                mount.replaceChildren();
                return store;
            });
        pageCache.set(page, pending);
        pending.catch(() => pageCache.delete(page));
        return pending;
    }

    function drawn(entry, store, hideWaqf) {
        const cy = store.centres.get(entry.line) ?? (entry.box.y + entry.box.height / 2);
        const band = store.pitch * BAND;
        const svg = document.createElementNS(SVG_NS, 'svg');
        svg.setAttribute('viewBox', `${entry.box.x - PAD} ${cy - band / 2} ${entry.box.width + 2 * PAD} ${band}`);
        svg.setAttribute('class', 'sv-word');
        svg.setAttribute('aria-hidden', 'true');
        svg.setAttribute('focusable', 'false');
        // width/height in em of the verse font: a line pitch is one --sv-line (set in CSS)
        svg.style.width = `calc(${((entry.box.width + 2 * PAD) / store.pitch).toFixed(4)} * var(--sv-line, 1.3em))`;
        svg.style.height = `calc(${BAND} * var(--sv-line, 1.3em))`;
        entry.paths.forEach((source) => {
            if (hideWaqf && source.getAttribute('data-mark-family') === 'waqf') return;
            svg.appendChild(source.cloneNode(true));
        });
        return svg;
    }

    /**
     * Replace the .word-base of each token with the word's vector drawing. tokens: the verse's .word-token elements
     * (one per word, without the ayah number). Returns false (and touches nothing) when a page is missing or the
     * word count differs from the SVG's.
     */
    async function render(tokens, surah, ayah, pages) {
        if (!enabled() || !tokens.length || !Array.isArray(pages) || !pages.length) return false;
        const available = await availablePages();
        if (!pages.every((page) => available.has(Number(page)))) return false;
        let stores;
        try {
            stores = await Promise.all(pages.map((page) => loadPage(Number(page))));
        } catch (error) {
            console.warn('Shamarly vector page unavailable', error);
            return false;
        }
        const find = (key) => {
            for (const store of stores) {
                const entry = store.words.get(key);
                if (entry) return { entry, store };
            }
            return null;
        };
        const found = tokens.map((_, index) => find(`${surah}:${ayah}:${index + 1}`));
        if (found.some((item) => !item)) return false;
        let last = null;
        for (const store of stores) if (store.marks.has(`${surah}:${ayah}`)) last = { entry: store.marks.get(`${surah}:${ayah}`), store };
        tokens.forEach((token, index) => {
            const base = token.querySelector(':scope > .word-content > .word-base');
            if (!base) return;
            const { entry, store } = found[index];
            const parts = [drawn(entry, store, true)];
            if (index === tokens.length - 1 && last) {
                const number = drawn(last.entry, last.store, false);
                number.classList.add('sv-ayah-mark');
                parts.push(number);
            }
            base.replaceChildren(...parts);
            base.dataset.khattRenderMode = 'vector';
            token.dataset.shamarlyVector = '1';
            token.dataset.shamarlyGlyph = '1';   // the font/khatt/tajweed passes leave glyph-drawn words alone
            token.style.fontFamily = '';
        });
        return true;
    }

    window.ShamarlyVector = { render, enabled, setEnabled };
})();
