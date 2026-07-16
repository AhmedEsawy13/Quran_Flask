/* أثَر — shared Mushaf contracts.
 *
 * Keeps source routing, repeated mushaf-version queries, printed-waqf glyph
 * normalization, page-line DOM, and latest-request guards consistent across
 * the Reading, Memorization, Practice, and Editor surfaces. Page-specific
 * typography and interaction hooks deliberately stay in their owning modules.
 */
(function () {
    'use strict';

    const SOURCE_API = Object.freeze({
        digital_khatt: '/api/digital-khatt',
        qpc_v1: '/api/qpc-v1',
        shamarly: '/api/shamarly',
    });
    const EMBEDDED_WAQF_RE = /[ۖ-ۜ]/g;
    const WAQF_GLYPH_MAP = Object.freeze({
        'م': 'ۘ', 'قلى': 'ۗ', 'قلي': 'ۗ', 'ق': 'ۗ',
        'صلى': 'ۖ', 'صلي': 'ۖ', 'ص': 'ۖ', 'ج': 'ۚ',
        'لا': 'ۙ', 'س': 'ۜ', 'ع': 'ۛ',
        'ۘ': 'ۘ', 'ۗ': 'ۗ', 'ۖ': 'ۖ', 'ۚ': 'ۚ', 'ۙ': 'ۙ', 'ۛ': 'ۛ', 'ۜ': 'ۜ',
        'ؕ': 'ؕ', 'ؗ': 'ؗ', 'ؔ': 'ؔ', '۪': '۪', '۫': '۫', '۬': '۬',
    });

    function stripEmbeddedWaqf(text) {
        return String(text || '').replace(EMBEDDED_WAQF_RE, '');
    }

    function isWarshVersion(version) {
        return /ورش|warsh/i.test(String(version || ''));
    }

    function isHindiVersion(version) {
        return /الهندي|hindi|indopak/i.test(String(version || ''));
    }

    function normalizeWarshWaqfText(raw) {
        if (!raw || !String(raw).trim()) return '';
        const out = [];
        String(raw).split(/[،,]/).map(token => token.trim()).filter(Boolean).forEach(token => {
            if (token === 'ص' || token === 'ۖ') out.push('ۖ');
            else if (token === 'ر' || token === '۝') out.push('۝');
        });
        return out.join('');
    }

    function normalizeNonWarshWaqfText(raw) {
        return String(raw || '').split(/[،,]/)
            .map(token => token.replace(/\s+/g, '').trim())
            .filter(Boolean)
            .map(token => WAQF_GLYPH_MAP[token] || token)
            .join('');
    }

    function getWaqfDisplayData(rawValue, version) {
        const raw = String(rawValue || '').trim();
        if (!raw) return null;
        if (isWarshVersion(version)) {
            const text = normalizeWarshWaqfText(raw);
            return text ? { text, extraClass: 'waqf-warsh', title: raw } : null;
        }
        const text = normalizeNonWarshWaqfText(raw);
        if (!text || /^[↺▶]+$/.test(text)) return null;
        return { text, extraClass: '', title: raw };
    }

    function displaySymbols(text, version) {
        const isHindi = isHindiVersion(version);
        return [...String(text || '')].filter(char => {
            if (!char.trim()) return false;
            if (!isHindi) return true;
            const codepoint = char.codePointAt(0);
            return char !== '۟' && char !== 'ۜ' && !(codepoint >= 0xE000 && codepoint <= 0xF8FF);
        });
    }

    // Some sources emit a standalone combining-waqf token between words. Attach
    // it to the preceding token so every renderer treats the mark as belonging
    // to the word it annotates. The final token is preserved because it can be
    // a verse-end ornament rather than a waqf-only separator.
    function mergeWaqfOnlyTokens(rawTokens) {
        const isWaqfOnly = value => {
            if (!value) return false;
            return String(value).replace(
                /[\u0610-\u061F\u064B-\u065F\u0670\u06D6-\u06ED\u08D0-\u08FF\uF500-\uF6FF\uFE70-\uFEFF]/g,
                ''
            ).trim() === '';
        };
        const output = [];
        (Array.isArray(rawTokens) ? rawTokens : []).forEach((token, index, source) => {
            if (isWaqfOnly(token) && index < source.length - 1 && output.length) {
                output[output.length - 1] += token;
            } else output.push(token);
        });
        return output;
    }

    // Align backend waqf records to rendered token positions. Prefer explicit
    // one-based word indexes, then token indexes, and finally normalized text
    // matching for older datasets that expose neither stable coordinate.
    function indexWaqfEntries(waqfEntries, words) {
        const map = new Map();
        if (!Array.isArray(waqfEntries)) return map;
        const tokens = Array.isArray(words) ? words : [];
        const getWordText = value => {
            if (typeof value === 'string') return value;
            return value && typeof value === 'object'
                ? (value.text_original || value.text || value.word || '') : '';
        };
        const normalize = value => String(value || '')
            .replace(/\s+/g, '')
            .replace(/[\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06ED\u08D0-\u08FF]/g, '');
        const append = (index, entry) => {
            if (!Number.isInteger(index) || !entry || !entry.symbols) return;
            if (!map.has(index)) map.set(index, []);
            map.get(index).push({ symbols: entry.symbols, version: entry.version || '' });
        };

        const hasWordIndexes = tokens.length && waqfEntries.some(entry => {
            const position = Number(entry && entry.word_index);
            return Number.isInteger(position) && position > 0;
        });
        if (hasWordIndexes) {
            const wordToToken = new Map();
            let wordPosition = 0;
            tokens.forEach((token, tokenIndex) => {
                if (!normalize(getWordText(token))) return;
                wordPosition += 1;
                if (!wordToToken.has(wordPosition)) wordToToken.set(wordPosition, tokenIndex);
            });
            waqfEntries.forEach(entry => {
                const position = Number(entry && entry.word_index);
                if (Number.isInteger(position) && position > 0) append(wordToToken.get(position), entry);
            });
            if (map.size) return map;
        }

        if (waqfEntries.some(entry => entry && Number.isInteger(entry.token_index))) {
            waqfEntries.forEach(entry => append(entry && entry.token_index, entry));
            if (map.size) return map;
        }

        let searchStart = 0;
        waqfEntries.forEach(entry => {
            if (!entry || !entry.symbols) return;
            const target = normalize(entry.clean_token || entry.original_token || entry.word || '');
            if (!target) return;
            let found = -1;
            for (let index = searchStart; index < tokens.length; index += 1) {
                if (normalize(getWordText(tokens[index])) === target) { found = index; break; }
            }
            if (found < 0) {
                for (let index = 0; index < tokens.length; index += 1) {
                    if (normalize(getWordText(tokens[index])) === target) { found = index; break; }
                }
            }
            if (found >= 0) {
                append(found, entry);
                searchStart = found + 1;
            }
        });
        return map;
    }

    // Render a flat, wrapping word run. Consumers own the word's inner content
    // and interactions through hooks; this helper owns stable span/separator/
    // replaceChildren assembly and returns the live word elements for playback.
    function renderWordRun(container, words, options) {
        if (!container) throw new Error('word container is required');
        const config = Object.assign({
            wordClass: '', separator: ' ', classForWord: null,
            textForWord: context => context.raw,
            renderWord: null, decorateWord: null,
        }, options || {});
        const fragment = document.createDocumentFragment();
        const elements = [];
        (Array.isArray(words) ? words : []).forEach((word, index) => {
            const raw = typeof word === 'string' ? word : String(word && word.text || '');
            const context = { word, index, raw };
            const element = document.createElement('span');
            element.className = typeof config.classForWord === 'function'
                ? (config.classForWord(context) || '') : config.wordClass;
            if (typeof config.renderWord === 'function') config.renderWord(element, context);
            else element.textContent = config.textForWord(context);
            if (typeof config.decorateWord === 'function') config.decorateWord(element, context);
            if (index && config.separator) fragment.appendChild(document.createTextNode(config.separator));
            fragment.appendChild(element);
            elements.push(element);
        });
        container.replaceChildren(fragment);
        return elements;
    }

    function appendWaqfEntries(container, entriesOrText, options) {
        if (!container || !entriesOrText) return null;
        const config = Object.assign({
            fallbackVersion: '',
            stackClass: 'waqf-stack',
            symbolClass: 'waqf-symbol',
            stackPosition: 'append',
            classFor: null,
            titleFor: null,
        }, options || {});
        const entries = Array.isArray(entriesOrText)
            ? entriesOrText
            : [{ symbols: entriesOrText, version: config.fallbackVersion }];
        let stack = container.querySelector(`:scope > .${config.stackClass}`);

        entries.forEach(entryValue => {
            const entry = entryValue && typeof entryValue === 'object'
                ? entryValue : { symbols: entryValue, version: config.fallbackVersion };
            const version = entry.version || config.fallbackVersion || '';
            const data = getWaqfDisplayData(entry.symbols, version);
            if (!data) return;
            const symbols = displaySymbols(data.text, version);
            if (!symbols.length) return;

            if (!stack) {
                stack = document.createElement('span');
                stack.className = config.stackClass;
                if (config.stackPosition === 'prepend') container.prepend(stack);
                else container.appendChild(stack);
            }

            const extraClass = typeof config.classFor === 'function'
                ? config.classFor(version, data, entry) : '';
            symbols.forEach(symbol => {
                const span = document.createElement('span');
                span.className = [config.symbolClass, extraClass, data.extraClass].filter(Boolean).join(' ');
                if (version) span.dataset.version = version;
                span.textContent = symbol;
                span.title = typeof config.titleFor === 'function'
                    ? (config.titleFor(symbol, version, data, entry) || '')
                    : (version ? `مصحف: ${version}` : data.title);

                if (version === 'الهندي') {
                    let group = stack.querySelector(':scope > .waqf-hindi-group');
                    if (!group) {
                        group = document.createElement('span');
                        group.className = 'waqf-hindi-group';
                        stack.appendChild(group);
                    }
                    group.appendChild(span);
                } else stack.appendChild(span);
            });
        });
        return stack;
    }

    function buildQuery(options) {
        const config = options || {};
        const params = new URLSearchParams();
        (Array.isArray(config.versions) ? config.versions : []).filter(Boolean)
            .forEach(version => params.append('mushaf_version', version));
        if (config.source) params.set('source', config.source);
        Object.entries(config.params || {}).forEach(([key, value]) => {
            if (value == null || value === '') return;
            if (Array.isArray(value)) value.forEach(item => params.append(key, item));
            else params.set(key, value);
        });
        const query = params.toString();
        return query ? `?${query}` : '';
    }

    function sourceApiBase(source) {
        return SOURCE_API[source] || SOURCE_API.digital_khatt;
    }

    function createPageClient(options) {
        const config = options || {};
        const getSource = typeof config.getSource === 'function' ? config.getSource : () => 'digital_khatt';
        const getVersions = typeof config.getVersions === 'function' ? config.getVersions : () => [];
        const query = () => buildQuery({ versions: getVersions() });
        return Object.freeze({
            byAyah: (surah, ayah) => window.AtharApi.json(`${sourceApiBase(getSource())}/page-by-ayah/${surah}/${ayah}${query()}`),
            byNumber: page => window.AtharApi.json(`${sourceApiBase(getSource())}/page/${page}${query()}`),
        });
    }

    function maxAyahOnPage(page, surah) {
        let maximum = 0;
        (page && page.lines || []).forEach(line => {
            (line.words || []).forEach(word => {
                if (Number(word.surah) === Number(surah) && Number(word.ayah) > maximum) {
                    maximum = Number(word.ayah);
                }
            });
        });
        return maximum;
    }

    async function loadPageRange(options) {
        const config = options || {};
        const client = config.client;
        const surah = Number(config.surah);
        const fromAyah = Number(config.fromAyah);
        const toAyah = Number(config.toAyah);
        const maxPages = Math.max(1, Number(config.maxPages) || 8);
        const isCurrent = typeof config.isCurrent === 'function' ? config.isCurrent : () => true;
        if (!client || !surah || !fromAyah || !toAyah) throw new Error('invalid page range');

        let page = await client.byAyah(surah, fromAyah);
        if (!isCurrent()) return null;
        if (!page || !Array.isArray(page.lines)) return [];
        const pages = [page];
        while (pages.length < maxPages && maxAyahOnPage(page, surah) < toAyah) {
            const nextPage = Number(page.page_number) + 1;
            if (!nextPage) break;
            try {
                page = await client.byNumber(nextPage);
            } catch (error) {
                break;
            }
            if (!isCurrent()) return null;
            if (!page || !Array.isArray(page.lines)) break;
            pages.push(page);
        }
        return pages;
    }

    function verseEdges(position, options) {
        const config = options || {};
        const minSurah = Number(config.minSurah) || 1;
        const maxSurah = Number(config.maxSurah) || 114;
        const surah = Number(position && position.surah) || minSurah;
        const ayah = Number(position && position.ayah) || 1;
        const ayahCount = Number(config.ayahCount) || 0;
        return {
            atStart: surah <= minSurah && ayah <= 1,
            atEnd: surah >= maxSurah && ayahCount > 0 && ayah >= ayahCount,
        };
    }

    async function stepVerse(position, delta, options) {
        const direction = Math.sign(Number(delta));
        if (!direction) return null;
        const config = options || {};
        const minSurah = Number(config.minSurah) || 1;
        const maxSurah = Number(config.maxSurah) || 114;
        const getAyahCount = config.getAyahCount;
        if (typeof getAyahCount !== 'function') throw new Error('getAyahCount is required');
        const surah = Math.min(maxSurah, Math.max(minSurah, Number(position && position.surah) || minSurah));
        const ayah = Math.max(1, Number(position && position.ayah) || 1);
        const currentCount = Number(await getAyahCount(surah)) || 0;

        if (direction > 0) {
            if (ayah < currentCount) return { surah, ayah: ayah + 1 };
            return surah < maxSurah ? { surah: surah + 1, ayah: 1 } : null;
        }
        if (ayah > 1) return { surah, ayah: ayah - 1 };
        if (surah <= minSurah) return null;
        const previousSurah = surah - 1;
        const previousCount = Number(await getAyahCount(previousSurah)) || 1;
        return { surah: previousSurah, ayah: previousCount };
    }

    function lineKind(line) {
        const type = line && line.line_type;
        if (type === 'surah_name') return 'surah';
        if (type === 'basmallah') {
            const isFatihaOpening = (line.words || []).some(word =>
                Number(word.surah) === 1 && Number(word.ayah) === 1);
            if (!isFatihaOpening) return 'basmala';
        }
        return 'content';
    }

    function sliceLinesForAyahRange(lines, surah, fromAyah, toAyah) {
        const source = Array.isArray(lines) ? lines : [];
        const touches = line => (line.words || []).some(word =>
            Number(word.surah) === Number(surah)
            && Number(word.ayah) >= Number(fromAyah)
            && Number(word.ayah) <= Number(toAyah));
        let start = source.findIndex(touches);
        if (start < 0) return [];
        let end = start;
        for (let index = source.length - 1; index >= start; index -= 1) {
            if (touches(source[index])) { end = index; break; }
        }
        while (start > 0 && lineKind(source[start - 1]) !== 'content') start -= 1;
        return source.slice(start, end + 1);
    }

    function renderMushafLines(container, lines, options) {
        if (!container) throw new Error('line container is required');
        const config = Object.assign({
            lineClass: '',
            centeredClass: '',
            contentClass: '',
            surahClass: '',
            basmalaClass: '',
            wordClass: '',
            wrapContent: true,
            wrapSpecial: true,
            separator: ' ',
            countWord: () => true,
            classForWord: null,
            textForWord: context => context.raw,
            textForSpecial: context => context.line.display_text || (context.kind === 'basmala'
                ? 'بِسْمِ اللَّهِ الرَّحْمَٰنِ الرَّحِيمِ' : ''),
            identityKey: context => context.verseKey,
            decorateWord: null,
            decorateLine: null,
            decorateSpecial: null,
        }, options || {});
        const positions = new Map();
        const fragment = document.createDocumentFragment();
        const renderedLines = [];

        (Array.isArray(lines) ? lines : []).forEach((line, lineIndex) => {
            const kind = lineKind(line);
            let root;
            if (kind !== 'content') {
                const special = document.createElement('div');
                special.className = kind === 'surah' ? config.surahClass : config.basmalaClass;
                const specialContext = { line, lineIndex, kind };
                special.textContent = config.textForSpecial(specialContext);
                if (typeof config.decorateSpecial === 'function') config.decorateSpecial(special, specialContext);
                if (config.wrapSpecial) {
                    root = document.createElement('div');
                    root.className = config.lineClass;
                    root.appendChild(special);
                } else root = special;
            } else {
                root = document.createElement('div');
                root.className = [config.lineClass, line.is_centered ? config.centeredClass : ''].filter(Boolean).join(' ');
                const content = config.wrapContent ? document.createElement('div') : root;
                if (config.wrapContent) {
                    content.className = config.contentClass;
                    root.appendChild(content);
                }
                const words = line.words || [];
                let appended = 0;
                words.forEach((word, wordIndex) => {
                    const raw = String(word && word.text || '');
                    const baseContext = { line, lineIndex, word, wordIndex, raw };
                    const counted = word && word.surah != null && word.ayah != null
                        && config.countWord(baseContext) !== false;
                    const verseKey = counted ? `${word.surah}:${word.ayah}` : '';
                    const position = counted ? (positions.get(verseKey) || 0) : null;
                    if (counted) positions.set(verseKey, position + 1);
                    const context = Object.assign(baseContext, { counted, verseKey, position, kind });
                    const wordElement = document.createElement('span');
                    wordElement.className = typeof config.classForWord === 'function'
                        ? (config.classForWord(context) || '') : config.wordClass;
                    wordElement.textContent = config.textForWord(context);
                    if (counted) {
                        const identity = config.identityKey(context);
                        if (identity != null && identity !== '') {
                            wordElement.dataset.key = String(identity);
                            wordElement.dataset.wpos = String(position);
                        }
                    }
                    if (typeof config.decorateWord === 'function') config.decorateWord(wordElement, context);
                    if (appended && config.separator) content.appendChild(document.createTextNode(config.separator));
                    content.appendChild(wordElement);
                    appended += 1;
                });
                if (!words.length) content.textContent = line.display_text || '';
                if (typeof config.decorateLine === 'function') config.decorateLine(root, { line, lineIndex, kind, content });
            }
            fragment.appendChild(root);
            renderedLines.push(root);
        });
        container.replaceChildren(fragment);
        return { positions, lines: renderedLines };
    }

    function createRequestGate() {
        let generation = 0;
        return Object.freeze({
            next: () => ++generation,
            cancel: () => { generation += 1; },
            isCurrent: token => token === generation,
        });
    }

    window.AtharMushaf = Object.freeze({
        appendWaqfEntries,
        buildQuery,
        createPageClient,
        createRequestGate,
        displaySymbols,
        getWaqfDisplayData,
        indexWaqfEntries,
        isHindiVersion,
        isWarshVersion,
        lineKind,
        loadPageRange,
        maxAyahOnPage,
        normalizeNonWarshWaqfText,
        normalizeWarshWaqfText,
        mergeWaqfOnlyTokens,
        renderMushafLines,
        renderWordRun,
        sliceLinesForAyahRange,
        sourceApiBase,
        stepVerse,
        stripEmbeddedWaqf,
        verseEdges,
    });
})();
