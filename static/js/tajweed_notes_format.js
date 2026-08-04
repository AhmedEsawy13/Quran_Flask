/* Shared formatter for بيان التجويد companion notes.
 *
 * Invariant: every word of the source appears in the output (1:1).
 * Units are contiguous slices of the normalized text — we only choose
 * cut points for readability. We never delete, rewrite, or drop phrases.
 *
 * Quran quotes stay inline ({…} / ﴿…﴾ → highlighted). Badges are additive.
 */
(function (root) {
    'use strict';

    const RULE_LABELS = [
        ['مد لازم كلمي مثقل', 'مد لازم'],
        ['مد لازم حرفي مثقل', 'مد لازم'],
        ['مد لازم حرفي مخفف', 'مد لازم'],
        ['مد لازم', 'مد لازم'],
        ['مد منفصل', 'مد منفصل'],
        ['مد متصل', 'مد متصل'],
        ['مد عارض للسكون', 'مد عارض'],
        ['مد عارض', 'مد عارض'],
        ['مد عوض', 'مد عوض'],
        ['مد بدل', 'مد بدل'],
        ['مد لين', 'مد لين'],
        ['مد طبيعي', 'مد طبيعي'],
        ['مد تمكين', 'مد طبيعي'],
        ['صلة كبرى', 'صلة'],
        ['صلة صغرى', 'صلة'],
        ['صلة قصيرة', 'صلة'],
        ['صلة طويلة', 'صلة'],
        ['مد صلة', 'صلة'],
        ['إخفاء حقيقي', 'إخفاء'],
        ['إخفاء شفوي', 'إخفاء شفوي'],
        ['إدغام بغنة', 'إدغام بغنة'],
        ['إدغام بغير غنة', 'إدغام بلا غنة'],
        ['إدغام تماثل', 'إدغام تماثل'],
        ['إدغام مثلين', 'إدغام تماثل'],
        ['إدغام تجانس', 'إدغام'],
        ['إظهار حلقي', 'إظهار'],
        ['إظهار شفوي', 'إظهار شفوي'],
        ['إقلاب', 'إقلاب'],
        ['قلقلة', 'قلقلة'],
        ['مقلقلة', 'قلقلة'],
        ['مفخم', 'تفخيم'],
        ['غنة', 'غنة'],
        ['تفخيم', 'تفخيم'],
        ['مفخمة', 'تفخيم'],
        ['ترقيق', 'ترقيق'],
        ['مرققة', 'ترقيق'],
        ['رقيقة', 'ترقيق'],
        ['قمرية', 'لام قمرية'],
        ['شمسية', 'لام شمسية'],
        ['روم', 'روم'],
        ['إشمام', 'إشمام'],
    ];

    const LETTER_NAME = 'الباء|الراء|الدال|التاء|النون|الميم|الهاء|اللام|الجيم|القاف|الياء|الواو|الألف|جيم|دال|باء|قاف|راء|نون|ميم|فاء|واو|عين|ثاء|كاف|شين|تاء';
    const BRIDGE_RE = new RegExp(
        `^(عن|على|أو على|مع|مع لام|مع اللام|فصل|ويراعي فصل|ثم|ف|و|وفي|وفى|كذا|ومثلها|ومثله|وكذا|مع\\s+(?:${LETTER_NAME}))$`
    );
    // Lead-in that belongs with the *next* quote (kept on that unit by cutting before it).
    const TRAILING_LEAD_RE = new RegExp(
        `(?:^|\\s)(والوقف\\s+على|(?:و)?عند\\s+(?:ال)?وقف\\s+على|(?:وفي\\s+)?(?:ال)?وقف\\s+على|ويراعي\\s+فصل|مع\\s+(?:${LETTER_NAME})|مع\\s+اللام|مع\\s+لام|أو\\s+على|(?:و)?الياء\\s+في|(?:و)?لام(?:\\s+اسم\\s+الجلالة)?(?:\\s+من)?|(?:أما\\s+)?راء|وفي باء|ودال|(?:و)?(?:الباء|الراء|الدال|التاء|النون|الميم|الهاء|اللام|الجيم|القاف|الياء|الواو|الألف)\\s+(?:من|في|فى|على)|فصل|وفِي|وفى|وفي|عن|على|مع)\\s*$`,
        'u'
    );
    const MA3_TAIL_RE = new RegExp(`مع(?:\\s+(?:${LETTER_NAME}))?\\s*$`);
    const RELATIONAL_RULE_RE = /^(إقلاب|إدغام|إخفاء|إظهار|قلب|تماثل)/;
    const QUOTE_RE = /\{([^{}]{1,160})\}|﴿([^﴾]{1,160})﴾/g;
    const SECTION_RE = /^(هذا\s*:|بسم الله|وصلى الله|كتبه|أَحْكَام)/;
    // New ruling often starts after a period + و/وفي/في…
    const PERIOD_NEXT_RE = /^([\s\S]*?[.؟])(\s+)((?:وفي|وفى|في|فى|و)[\s\S]*)$/u;

    function stripMarks(s) {
        return String(s || '').replace(/[\u064B-\u065F\u0670\u06D6-\u06ED]/g, '');
    }

    function escapeHtml(s) {
        return String(s || '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    function ruleBadge(text) {
        const t = stripMarks(String(text || ''));
        for (const [needle, label] of RULE_LABELS) {
            if (t.includes(stripMarks(needle))) return label;
        }
        return '';
    }

    function normBridge(between) {
        return stripMarks(String(between || '')).replace(/\s+/g, ' ').trim();
    }

    function hasRulingContent(between) {
        const b = String(between || '').trim();
        if (!b) return false;
        const bridge = normBridge(b);
        if (!bridge) return false;
        if (BRIDGE_RE.test(bridge)) return false;
        // Whole span is only a lead-in for the next quote.
        const leadOnly = (' ' + bridge).match(TRAILING_LEAD_RE);
        if (leadOnly && leadOnly.index <= 1) return false;
        // Incomplete tail that must stay with the next quote.
        const incompleteTail = /(?:^|\s)(?:من|في|فى|على|عن)\s*$/.test(bridge)
            || /(?:مفخمة|مرققة|مقلقلة)\s+من\s*$/.test(bridge);
        if (incompleteTail && !/[.؟]/.test(b)) return false;
        if (ruleBadge(b)) return true;
        if (/[.؟]/.test(b)) return true;
        if (b.length >= 10) return true;
        return false;
    }

    /** Soft-join harvest wraps; keep real paragraph breaks. No word deletion. */
    function normalizeSource(raw) {
        let t = String(raw || '').replace(/<br\s*\/?>/gi, '\n').replace(/\u00a0/g, ' ');
        let prev;
        do {
            prev = t;
            t = t.replace(/\{([^{}\n]*)\n+([^{}]*)\}/g, '{$1 $2}');
            t = t.replace(/﴿([^﴾\n]*)\n+([^﴾]*)﴾/g, '﴿$1 $2﴾');
        } while (t !== prev);

        const lines = t.split(/\n/);
        const joined = [];
        for (let line of lines) {
            line = line.replace(/[ \t]+/g, ' ').trim();
            if (!line) {
                if (joined.length && joined[joined.length - 1] !== '') joined.push('');
                continue;
            }
            const prevLine = joined.length ? joined[joined.length - 1] : '';
            if (prevLine && prevLine !== '' && !/[.؟]$/.test(prevLine) && !SECTION_RE.test(line)) {
                joined[joined.length - 1] = `${prevLine} ${line}`;
            } else {
                joined.push(line);
            }
        }
        return joined.join('\n').replace(/\n{3,}/g, '\n\n').trim();
    }

    function findQuotes(text) {
        const out = [];
        QUOTE_RE.lastIndex = 0;
        let m;
        while ((m = QUOTE_RE.exec(text))) {
            out.push({
                index: m.index,
                end: QUOTE_RE.lastIndex,
                text: (m[1] || m[2] || '').trim(),
                ornate: !!m[2],
            });
        }
        return out;
    }

    /**
     * Choose cut offsets that partition `block` into contiguous slices.
     * Concatenating all unit texts (ignoring only edge whitespace trim for
     * display) reconstructs the full source — nothing is deleted.
     */
    function findCutOffsets(block) {
        const quotes = findQuotes(block);
        const cuts = [];
        if (quotes.length < 2) return cuts;

        for (let i = 0; i < quotes.length - 1; i++) {
            const next = quotes[i + 1];
            const between = block.slice(quotes[i].end, next.index);
            if (!hasRulingContent(between)) continue;

            const afterNext = block.slice(
                next.end,
                quotes[i + 2] ? quotes[i + 2].index : block.length
            );
            const afterNextHead = normBridge(afterNext);
            const betweenNorm = normBridge(between);

            // Relational pair: «… مع باء {Y} إقلاب»
            if (MA3_TAIL_RE.test(betweenNorm) && RELATIONAL_RULE_RE.test(afterNextHead)) {
                const periodSplit = between.match(PERIOD_NEXT_RE);
                if (periodSplit && MA3_TAIL_RE.test(normBridge(periodSplit[3]))) {
                    // Cut after the finished sentence; keep whitespace with the next unit.
                    cuts.push(quotes[i].end + periodSplit[1].length);
                }
                // else: do not cut inside the pair
                continue;
            }

            const periodSplit = between.match(PERIOD_NEXT_RE);
            if (periodSplit && periodSplit[3].trim()) {
                cuts.push(quotes[i].end + periodSplit[1].length);
                continue;
            }

            const lead = between.match(TRAILING_LEAD_RE);
            if (lead) {
                const beforeLead = between.slice(0, lead.index).trim();
                if (beforeLead) {
                    cuts.push(quotes[i].end + lead.index);
                    continue;
                }
            }

            // Default: cut at the start of the next quote (between stays with previous).
            cuts.push(next.index);
        }
        return cuts;
    }

    function splitUnits(block) {
        const text = String(block || '');
        if (!text.trim()) return [];

        const quotes = findQuotes(text);
        if (!quotes.length) {
            return [{ text: text.trim(), kind: 'prose', start: 0, end: text.length }];
        }

        const cuts = findCutOffsets(text).filter((c, i, arr) => c > 0 && c < text.length && arr.indexOf(c) === i);
        cuts.sort((a, b) => a - b);

        const units = [];
        let cursor = 0;
        for (const cut of cuts) {
            if (cut <= cursor) continue;
            const slice = text.slice(cursor, cut);
            // Preserve all characters; only trim for empty-check / display edges.
            const trimmed = slice.replace(/^\s+/, '').replace(/\s+$/, '');
            if (trimmed) {
                units.push({ text: trimmed, kind: 'rule', start: cursor, end: cut });
            }
            cursor = cut;
        }
        const tail = text.slice(cursor);
        const tailTrim = tail.replace(/^\s+/, '').replace(/\s+$/, '');
        if (tailTrim) {
            units.push({ text: tailTrim, kind: 'rule', start: cursor, end: text.length });
        }
        return units;
    }

    /** Arabic word tokens for fidelity checks / tests. */
    function arabicWords(s) {
        return String(s || '').match(/[\u0600-\u06FF]+/g) || [];
    }

    /** True if formatted units keep every source Arabic word (order-preserving multiset). */
    function isLossless(source, units) {
        const src = arabicWords(source);
        const out = [];
        for (const u of units) out.push(...arabicWords(u.text));
        if (src.length !== out.length) return false;
        for (let i = 0; i < src.length; i++) {
            if (src[i] !== out[i]) return false;
        }
        return true;
    }

    function decorateInline(unitText) {
        return escapeHtml(unitText)
            .replace(/﴿([^﴾]{1,160})﴾/g, '<span class="tj-quran" dir="rtl">﴿$1﴾</span>')
            .replace(/\{([^{}]{1,160})\}/g, '<span class="tj-quran" dir="rtl">$1</span>');
    }

    function formatHtml(raw) {
        const normalized = normalizeSource(raw);
        if (!normalized) return '';

        const blocks = normalized.split(/\n+/).map(s => s.trim()).filter(Boolean);
        const out = [];
        let openList = false;

        const closeList = () => {
            if (openList) {
                out.push('</ul>');
                openList = false;
            }
        };

        for (const block of blocks) {
            let units = splitUnits(block);

            // Safety: if a cut would lose words, fall back to one intact unit.
            if (!isLossless(block, units)) {
                units = [{ text: block.trim(), kind: findQuotes(block).length ? 'rule' : 'prose' }];
            }

            const ruleUnits = units.filter(u => findQuotes(u.text).length);
            const proseUnits = units.filter(u => !findQuotes(u.text).length);

            if (ruleUnits.length) {
                if (!openList) {
                    out.push('<ul class="tj-rule-list">');
                    openList = true;
                }
                for (const unit of ruleUnits) {
                    let text = unit.text;
                    let digression = '';
                    // Split digression visually only — both parts still rendered.
                    const dig = text.match(/^(.{12,200}?[.؟])\s+((?:وينبغى|وينبغي|هذا\s*:|ومعرفة|فالترتيل|وعدم خلط).+)$/u);
                    if (dig && dig[2].length > 60) {
                        text = dig[1].trim();
                        digression = dig[2].trim();
                    }

                    const badge = ruleBadge(text);
                    const badgeHtml = badge
                        ? `<span class="tj-badge">${escapeHtml(badge)}</span>`
                        : '';
                    out.push(
                        `<li class="tj-rule">`
                        + `<div class="tj-rule-main"><p class="tj-rule-note">${decorateInline(text)}</p></div>`
                        + badgeHtml
                        + `</li>`
                    );
                    if (digression) {
                        closeList();
                        out.push(`<p class="tj-note-prose">${escapeHtml(digression)}</p>`);
                    }
                }
            }

            for (const unit of proseUnits) {
                const t = String(unit.text || '').trim();
                if (!t) continue;
                closeList();
                out.push(`<p class="tj-note-prose">${decorateInline(t)}</p>`);
            }
        }

        closeList();
        return out.join('');
    }

    root.AtharTajweedNotes = {
        formatHtml,
        normalizeSource,
        splitUnits,
        findCutOffsets,
        isLossless,
        arabicWords,
        parseRuleItems(block) {
            return splitUnits(block)
                .filter(u => findQuotes(u.text).length)
                .map(u => ({
                    quotes: findQuotes(u.text),
                    note: u.text,
                    digression: '',
                }));
        },
    };
}(window));
