/* ReciteQuran 1.0.2-style per-word semi-global DTW for تدريب تسميع.
   Port of Iam-Muslim/ReciteQuran QuranDictationMatcher + DictationSequencer:
   free-start, first-valid endpoint (consume trailing madd on tie), short-word
   threshold, waqf/sukoon trailing deletions are not "incomplete", lookahead
   capped so a وقف is not skipped. */
(function (global) {
    'use strict';

    const CFG = {
        defaultMaxPathCost: 0.30,
        shortWordPathCost: 0.25,
        mediumWordPathCost: 0.28,
        maxSkipWords: 1,
        acousticConfusionCost: 0.25,
        standardInsertionCost: 0.75,
        standardDeletionCost: 1.0,
    };

    const FATHA = 0x064E, DAMMA = 0x064F, KASRA = 0x0650;
    const ALIF = 0x0627, WAW = 0x0648, YAA = 0x064A;
    const SMALL_WAW = 0x06E5, SMALL_YAA = 0x06E6;
    const MADD = new Set([ALIF, WAW, YAA, SMALL_WAW, SMALL_YAA]);

    function isZeroCostMarker(code) {
        return code === 0x0686 || code === 0x06DC || code === 0x0619 ||
            code === 0x06EA || code === 0x0640;
    }
    function isHamzaVariant(code) {
        return code === 0x0621 || code === 0x0622 || code === 0x0623 ||
            code === 0x0625 || code === 0x0672;
    }
    function isTashkeel(code) {
        return code === FATHA || code === DAMMA || code === KASRA;
    }
    function isEquivalentGlyph(a, b) {
        if (a === b) return true;
        if (a > b) { const t = a; a = b; b = t; }
        if (a === 0x0645 && b === 0x06FE) return true;
        if (a === 0x0646 && b === 0x06BA) return true;
        if (a === 0x0648 && b === 0x06E5) return true;
        if (a === 0x064A && b === 0x06E6) return true;
        if (isHamzaVariant(a) && isHamzaVariant(b)) return true;
        if (a === 0x0629 && b === 0x0647) return true;
        if (a === 0x062A && b === 0x0629) return true;
        return false;
    }
    function isAcousticConfusion(a, b) {
        if (a > b) { const t = a; a = b; b = t; }
        if (a === ALIF && b === FATHA) return true;
        if (a === WAW && b === DAMMA) return true;
        if (a === DAMMA && b === SMALL_WAW) return true;
        if (a === YAA && b === KASRA) return true;
        if (a === KASRA && b === SMALL_YAA) return true;
        if (a === 0x062A && b === 0x0637) return true;
        if (a === 0x062C && b === 0x0632) return true;
        if (a === 0x062E && b === 0x063A) return true;
        if (a === 0x062F && b === 0x0636) return true;
        if (a === 0x0630 && (b === 0x0632 || b === 0x0638)) return true;
        if (a === 0x0633 && b === 0x0635) return true;
        if (a === 0x0642 && b === 0x0643) return true;
        return false;
    }
    function substitutionCost(a, b, confusion) {
        if (a === b || isEquivalentGlyph(a, b)) return 0;
        if (isAcousticConfusion(a, b)) return confusion;
        if (isTashkeel(a) || isTashkeel(b)) return 1;
        return 1;
    }
    function deletionCost(ref, idx, standard, confusion) {
        if (idx < 0 || idx >= ref.length) return standard;
        const code = ref.charCodeAt(idx);
        if (isZeroCostMarker(code)) return 0;
        if (isHamzaVariant(code)) return confusion;
        if (idx > 0 && code === ref.charCodeAt(idx - 1)) return confusion;
        return standard;
    }
    function insertionCost(asr, idx, standard, confusion) {
        if (idx < 0 || idx >= asr.length) return standard;
        const code = asr.charCodeAt(idx);
        if (isZeroCostMarker(code)) return 0;
        if (idx > 0 && code === asr.charCodeAt(idx - 1) && MADD.has(code)) return confusion;
        return standard;
    }
    function effectiveLen(ref) {
        let n = 0;
        for (let j = 0; j < ref.length; j++) {
            const code = ref.charCodeAt(j);
            if (isZeroCostMarker(code)) continue;
            if (j > 0 && code === ref.charCodeAt(j - 1) && MADD.has(code)) continue;
            n += 1;
        }
        return Math.max(1, n);
    }

    function matchWord(asrText, ref, config) {
        const cfg = Object.assign({}, CFG, config || {});
        const m = asrText.length, n = ref.length;
        if (!m || n <= 0) return null;
        const stride = n + 1;
        const dp = new Float64Array((m + 1) * stride);
        const bt = new Uint8Array((m + 1) * stride);
        dp[0] = 0;
        for (let j = 1; j <= n; j++) {
            dp[j] = dp[j - 1] + deletionCost(ref, j - 1, cfg.standardDeletionCost, cfg.acousticConfusionCost);
            bt[j] = 1;
        }
        for (let i = 1; i <= m; i++) {
            dp[i * stride] = 0;
            bt[i * stride] = 2;
        }
        for (let i = 1; i <= m; i++) {
            const aCode = asrText.charCodeAt(i - 1);
            const row = i * stride, prev = (i - 1) * stride;
            const ins = insertionCost(asrText, i - 1, cfg.standardInsertionCost, cfg.acousticConfusionCost);
            for (let j = 1; j <= n; j++) {
                const rCode = ref.charCodeAt(j - 1);
                const sub = dp[prev + j - 1] + substitutionCost(aCode, rCode, cfg.acousticConfusionCost);
                const del = dp[row + j - 1] + deletionCost(ref, j - 1, cfg.standardDeletionCost, cfg.acousticConfusionCost);
                const insC = dp[prev + j] + ins;
                if (sub < del && sub <= insC) { dp[row + j] = sub; bt[row + j] = 0; }
                else if (del <= insC) { dp[row + j] = del; bt[row + j] = 1; }
                else { dp[row + j] = insC; bt[row + j] = 2; }
            }
        }
        const effN = effectiveLen(ref);
        let threshold = cfg.defaultMaxPathCost;
        if (effN <= 3) threshold = Math.min(threshold, cfg.shortWordPathCost);
        else if (effN <= 7) threshold = Math.min(threshold, cfg.mediumWordPathCost);

        // First-valid endpoint (minimum i at the best cost). ReciteQuran 1.0.2
        // then absorbs trailing madd/shaddah repeats so leftover letters do not
        // bleed into the next word — without skipping ahead to a later copy of
        // the same word (لله in البسملة vs الحمد).
        let bestI = -1, bestCost = Infinity;
        for (let i = 1; i <= m; i++) {
            const norm = dp[i * stride + n] / effN;
            if (norm <= threshold && (bestI < 0 || norm < bestCost - 1e-9)) {
                bestI = i;
                bestCost = norm;
            }
        }
        if (bestI > 0) {
            const last = ref.charCodeAt(n - 1);
            while (bestI < m) {
                const next = asrText.charCodeAt(bestI);
                const same = next === last || (MADD.has(last) && MADD.has(next)) ||
                    isTashkeel(next) || isZeroCostMarker(next);
                if (!same) break;
                const norm = dp[(bestI + 1) * stride + n] / effN;
                if (norm > threshold) break;
                bestI += 1;
            }
        }

        let isPartial = false;
        if (bestI > 0 && bestI === m) {
            let curJ = n, curI = bestI, missingCore = false;
            while (curJ > 0 && curI === bestI && bt[curI * stride + curJ] === 1) {
                const rCode = ref.charCodeAt(curJ - 1);
                const repeated = curJ > 1 && rCode === ref.charCodeAt(curJ - 2);
                if (!isTashkeel(rCode) && !isZeroCostMarker(rCode) && !repeated) {
                    missingCore = true;
                    break;
                }
                curJ -= 1;
            }
            isPartial = missingCore;
        } else if (bestI < 0) {
            const minJ = n > 2 ? 2 : 1;
            const startI = Math.max(1, m - 2);
            outer: for (let i = startI; i <= m; i++) {
                for (let j = minJ; j < n; j++) {
                    if (dp[i * stride + j] / j <= threshold) { isPartial = true; break outer; }
                }
            }
        }
        if (isPartial) return { pathCost: 0, tokensConsumed: 0, cleanAsr: '', isPartial: true };
        if (bestI < 0) return null;
        return {
            pathCost: bestCost,
            tokensConsumed: bestI,
            cleanAsr: asrText.slice(0, bestI),
            isPartial: false,
        };
    }

    function createSequencer(entries, options) {
        const opts = Object.assign({ maxSkipWords: CFG.maxSkipWords, isTajweed: true }, options || {});
        const words = (entries || []).map(e => String(e.ph || '').replace(/ /g, ''));
        let asr = '';
        let anchor = 0;
        let cursor = 0;
        const green = new Set();
        const red = new Set();

        function emit(kind, index, extra) {
            const entry = entries[index];
            if (!entry) return;
            if (kind === 'green') { green.add(index); red.delete(index); }
            if (kind === 'red') { if (green.has(index)) return; red.add(index); }
            if (opts.onCommit) opts.onCommit(kind, entry, extra || {});
        }

        function process(asrText) {
            asr = String(asrText || '');
            if (asr.length < anchor) { anchor = 0; cursor = 0; }
            const skipCap = opts.maxSkipWords;
            let guard = 0;
            while (anchor < asr.length && cursor < words.length && guard++ < words.length + 4) {
                const unconsumed = asr.slice(anchor);
                let matched = false, waiting = false;
                for (let skip = 0; skip <= skipCap && cursor + skip < words.length; skip++) {
                    const start = cursor + skip;
                    const result = matchWord(unconsumed, words[start], opts);
                    if (!result) continue;
                    if (result.isPartial) {
                        if (skip === 0) waiting = true;
                        break;
                    }
                    if (result.tokensConsumed <= 0) continue;
                    for (let s = 0; s < skip; s++) emit('red', cursor + s);
                    emit('green', start, { score: Math.max(0, 1 - result.pathCost), asr: result.cleanAsr });
                    anchor += result.tokensConsumed;
                    cursor = start + 1;
                    matched = true;
                    break;
                }
                if (!matched) break;
                if (waiting) break;
            }
            return { cursor, anchor, green, red };
        }

        function onSilence() {
            if (cursor >= words.length) return entries[cursor - 1] || null;
            const unconsumed = asr.slice(anchor);
            const result = unconsumed ? matchWord(unconsumed, words[cursor], opts) : null;
            if (result && !result.isPartial && result.tokensConsumed > 0) {
                emit('green', cursor, { score: Math.max(0, 1 - result.pathCost), asr: result.cleanAsr, waqf: true });
                anchor += result.tokensConsumed;
                cursor += 1;
                return entries[cursor - 1];
            }
            if (result && result.isPartial) {
                emit('green', cursor, { score: 0.7, asr: unconsumed, waqf: true });
                cursor += 1;
                anchor = asr.length;
                return entries[cursor - 1];
            }
            if (cursor > 0) return entries[cursor - 1];
            return null;
        }

        function reset() {
            asr = '';
            anchor = 0;
            cursor = 0;
            green.clear();
            red.clear();
        }

        return { process, onSilence, reset, matchWord, config: CFG };
    }

    const api = { CFG, matchWord, createSequencer, effectiveLen };
    global.AtharPhonemeDtw = api;
    if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis);
