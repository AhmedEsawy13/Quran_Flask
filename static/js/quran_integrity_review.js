(() => {
    const reportEndpoint = '/api/quran-integrity/report';
    const body = document.body;
    const findingsList = document.getElementById('qir-findings-list');
    const resultCount = document.getElementById('qir-result-count');
    const searchInput = document.getElementById('qir-search-input');
    const details = document.getElementById('qir-details');
    const detailsTitle = document.getElementById('qir-details-title');
    const detailsSummary = document.getElementById('qir-details-summary');
    const detailsActions = document.getElementById('qir-details-actions');
    const detailsContent = document.getElementById('qir-details-content');
    const closeDetails = document.getElementById('qir-close-details');
    const filterButtons = [...document.querySelectorAll('[data-qir-filter]')];

    const labels = {
        reference_text_word_count: 'مرجع MCP · اختلاف عدد الكلمات',
        'json_sources.digital_khatt': 'Digital Khatt · النص الخام',
        'json_sources.qpc_hafs': 'QPC Hafs · النص الخام',
        'json_sources.indopak': 'Indopak · النص الخام',
        'json_sources.tanzil_uthmani': 'Tanzil Uthmani · النص الخام',
        'databases.quran_script': 'quran_script.db · الكلمات والمعرّفات',
        'databases.word_name': 'word_name.db · معاني الكلمات',
        'databases.waqf_symbols': 'waqf_symbols.db · علامات الوقف',
        'databases.mushaf_waqf': 'mushaf_waqf.db · مواضع الوقف',
        'databases.classical_waqf': 'classical_waqf.db · الوقف التراثي',
        'layouts.bahrain': 'Bahrain · مخطط الصفحات',
        'layouts.shamarly': 'Shemrly · مخطط الصفحات',
        'layouts.azhar': 'Azhar · مخطط الصفحات',
        word_meanings: 'معاني الكلمات · مقارنة MCP والمحلي',
    };

    const groupLabels = {
        reference: 'المرجع',
        json_sources: 'مصادر النص',
        databases: 'قواعد البيانات',
        layouts: 'مخططات الصفحات',
        word_meanings: 'معاني الكلمات',
    };

    const reviewUrls = {
        'layouts.shamarly': '/waqf-mark-review',
        'layouts.azhar': '/azhar-waqf-review',
    };

    const number = (value) => Number(value || 0).toLocaleString('ar-EG');
    const esc = (value) => String(value ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');

    const state = {
        report: null,
        filter: 'all',
        query: '',
        selected: null,
    };

    function sectionFor(key) {
        if (!state.report) return {};
        if (key === 'reference_text_word_count') return state.report.reference || {};
        if (key === 'word_meanings') return state.report.word_meanings || {};
        const [group, source] = key.split('.');
        return (state.report[group] && state.report[group][source]) || {};
    }

    function groupFor(key) {
        if (key === 'reference_text_word_count') return 'reference';
        return key.split('.')[0];
    }

    function metricsFor(key, section) {
        if (key === 'reference_text_word_count') {
            return [
                { value: section.word_count_discrepancy_count, label: 'اختلافات' },
                { value: section.word_count, label: 'كلمات MCP' },
                { value: section.text_token_count, label: 'كلمات النص' },
            ];
        }
        if (key === 'word_meanings') {
            const coverage = section.coverage || {};
            const words = section.word_level || {};
            return [
                { value: section.verse_level?.finding_count, label: 'فروق آيات' },
                { value: section.phrase_level?.group_count, label: 'عبارات مجمعة' },
                { value: words.meaning_difference_count, label: 'فروق كلمات' },
                { value: coverage.mcp_cached_word_count, label: 'كلمات MCP محملة' },
            ];
        }
        if (groupFor(key) === 'json_sources') {
            return [
                { value: section.word_mismatch_count, label: 'اختلاف كلمات' },
                { value: section.tokenization_variance_count, label: 'اختلاف تقطيع' },
                { value: section.normalization_variance_count, label: 'فروق تطبيع' },
            ];
        }
        if (key === 'databases.quran_script') {
            return [
                { value: section.verse_word_mismatch_count, label: 'آيات مختلفة' },
                { value: section.id_order_violation_count, label: 'خرق ترتيب ID' },
                { value: section.waqf_orphan_count, label: 'وقف يتيم' },
                { value: section.content_row_count, label: 'كلمات فعلية' },
            ];
        }
        if (groupFor(key) === 'databases') {
            return [
                { value: section.invalid_count ?? section.orphan_count, label: 'صفوف تحتاج فحصًا' },
                { value: section.row_count, label: 'إجمالي الصفوف' },
            ];
        }
        return [
            { value: section.missing_id_count, label: 'IDs مفقودة' },
            { value: section.unknown_ayah_endpoint_count, label: 'نهايات مجهولة' },
            { value: section.ordering_error_count, label: 'أخطاء ترتيب' },
            { value: section.cross_surah_line_count, label: 'أسطر عابرة للسور' },
            { value: section.empty_ayah_line_count, label: 'أسطر آيات فارغة' },
        ];
    }

    function summaryFor(key, section) {
        if (key === 'reference_text_word_count') {
            const discrepancy = (section.word_count_discrepancies || [])[0] || {};
            return `الآية ${discrepancy.verse_key || '—'}: المرجع يذكر ${number(discrepancy.mcp_word_count)} كلمة، بينما يقسم النص إلى ${number(discrepancy.text_token_count)}.`;
        }
        if (key === 'word_meanings') {
            if (section.status === 'not_harvested') {
                return 'لم تُحمّل مقارنة معاني الكلمات بعد. شغّل أداة الحصاد ثم أعد تحميل الصفحة.';
            }
            if (section.status === 'harvesting') {
                const coverage = section.coverage || {};
                return `الحصاد جارٍ: تم تحميل ${number(coverage.mcp_cached_word_count)} من ${number(coverage.mcp_word_count)} كلمة MCP.`;
            }
            if (section.status === 'not_compared') {
                const coverage = section.coverage || {};
                return `اكتمل الحصاد (${number(coverage.mcp_cached_word_count)} كلمة)، لكن المقارنة لم تُشغّل بعد.`;
            }
            const words = section.word_level || {};
            const sourceNote = section.mcp_source?.runtime_active
                ? 'المصدر الحالي هو MCP الرسمي. '
                : '';
            const unavailable = words.meaning_unavailable_count || 0;
            const unavailableNote = unavailable
                ? ` ${number(unavailable)} مواضع بلا معنى متاح.`
                : '';
            return sourceNote + `${number(section.verse_level?.finding_count)} فروق على مستوى الآية، `
                + `${number(section.phrase_level?.group_count)} عبارات مجمعة، و`
                + `${number(words.meaning_difference_count)} فروق نصية على مستوى الكلمة.`
                + unavailableNote;
        }
        if (groupFor(key) === 'json_sources') {
            return `${number(section.word_mismatch_count)} اختلافات غير محسومة، مع ${number(section.tokenization_variance_count)} حالات تقطيع مختلفة وفروق تطبيع عرضية.`;
        }
        if (key === 'databases.quran_script') {
            return `${number(section.content_row_count)} كلمة فعلية مقابل ${number(section.reference_content_word_count)} في المرجع، مع فروق في النص والترتيب والوقف.`;
        }
        if (key === 'databases.word_name') {
            return `${number(section.orphan_count)} صفًا لم يُطابق كلمة مرجعية مباشرة؛ قد تكون بعض الصفوف عبارات مجمّعة وتحتاج قرارًا بشريًا.`;
        }
        if (groupFor(key) === 'databases') {
            return `${number(section.invalid_count)} صفًا لا يحل إلى موضع كلمة مرجعي صالح.`;
        }
        return `${number(section.missing_id_count)} IDs مفقودة، و${number(section.cross_surah_line_count)} أسطر تحتوي سورة غير السورة المعلنة.`;
    }

    function sampleGroups(key, section) {
        const groups = [];
        const add = (label, values, limit = 25) => {
            if (Array.isArray(values) && values.length) {
                groups.push({ label, values: values.slice(0, limit), total: values.length });
            }
        };

        if (key === 'reference_text_word_count') {
            add('اختلافات عدد الكلمات', section.word_count_discrepancies, 20);
        } else if (key === 'word_meanings') {
            add('أخطاء الحصاد', section.errors, 20);
            add('فروق مستوى الآية', section.verse_level?.findings, 30);
            add('عبارات تحتاج مراجعة', section.phrase_level?.findings, 40);
            add('فروق معنى على مستوى الكلمة', section.word_level?.findings, 40);
        } else if (groupFor(key) === 'json_sources') {
            add('اختلافات الكلمات', section.word_mismatches, 20);
            add('اختلافات التقطيع', section.tokenization_variances, 20);
            add('أمثلة فروق التطبيع', section.normalization_variances, 12);
        } else if (key === 'databases.quran_script') {
            add('اختلافات كلمات الآيات', section.verse_word_mismatches, 20);
            add('خرق ترتيب المعرّف', section.id_order_violations, 20);
            add('مواضع كلمات مفقودة', section.missing_word_positions, 20);
            add('صفوف وقف يتيمة', section.waqf_orphans, 20);
            add('مفاتيح كلمات مشوهة', section.malformed_word_keys, 20);
        } else if (key === 'databases.word_name') {
            add('صفوف المعاني اليتيمة', section.orphan_rows, 40);
        } else if (groupFor(key) === 'databases') {
            add('الصفوف غير الصالحة', section.invalid_rows, 40);
        } else {
            add('IDs مفقودة', section.missing_ids, 80);
            add('نهايات آيات مجهولة', section.unknown_ayah_endpoints, 30);
            add('أخطاء ترتيب', section.ordering_errors, 30);
            add('ترتيب غير محسوم', section.unresolved_order, 30);
            add('أسطر عابرة للسور', section.cross_surah_lines, 30);
            add('أسطر آيات فارغة', section.empty_ayah_lines, 30);
            add('اختلاف نص السطر', section.line_text_mismatches, 10);
            add('أخطاء الامتداد', section.span_errors, 20);
        }
        return groups;
    }

    function renderMetric(metric) {
        return `<span class="qir-metric"><b>${number(metric.value)}</b><span>${esc(metric.label)}</span></span>`;
    }

    function renderCard(key) {
        const section = sectionFor(key);
        const label = labels[key] || key;
        const group = groupFor(key);
        const metrics = metricsFor(key, section)
            .filter((metric) => metric.value !== undefined && metric.value !== null)
            .map(renderMetric)
            .join('');
        const selected = state.selected === key ? ' is-selected' : '';
        const review = reviewUrls[key]
            ? `<a class="qir-button qir-button-small" href="${reviewUrls[key]}">فتح صفحة المراجعة</a>`
            : '';
        return `<article class="qir-finding${selected}" data-qir-key="${esc(key)}">`
            + `<div class="qir-finding-head"><div class="qir-finding-title">`
            + `<h3>${esc(label)}</h3><code>${esc(key)}</code></div>`
            + `<span class="qir-group">${esc(groupLabels[group] || group)}</span></div>`
            + `<div class="qir-metrics">${metrics}</div>`
            + `<p class="qir-finding-summary">${esc(summaryFor(key, section))}</p>`
            + `<div class="qir-finding-actions">`
            + `<button class="qir-button qir-button-primary qir-button-small" type="button" data-qir-details="${esc(key)}">عرض التفاصيل</button>`
            + review
            + `</div></article>`;
    }

    function matches(key) {
        const group = groupFor(key);
        if (state.filter !== 'all' && state.filter !== group) return false;
        if (!state.query) return true;
        const section = sectionFor(key);
        return `${key} ${labels[key] || ''} ${JSON.stringify(section)}`.toLowerCase()
            .includes(state.query.toLowerCase());
    }

    function renderCards() {
        if (!state.report) return;
        const allKeys = [...(state.report.failures || []), 'word_meanings'];
        const keys = allKeys.filter(matches);
        resultCount.textContent = `عرض ${number(keys.length)} من ${number(allKeys.length)} بندًا`;
        findingsList.innerHTML = keys.length
            ? keys.map(renderCard).join('')
            : '<div class="qir-empty">لا توجد بنود مطابقة للبحث.</div>';
    }

    function renderDetails(key) {
        const section = sectionFor(key);
        const label = labels[key] || key;
        const groups = sampleGroups(key, section);
        state.selected = key;
        details.hidden = false;
        detailsTitle.textContent = label;
        detailsSummary.textContent = summaryFor(key, section);
        detailsActions.innerHTML = (reviewUrls[key]
            ? `<a class="qir-button qir-button-primary qir-button-small" href="${reviewUrls[key]}">انتقل إلى صفحة المراجعة</a>`
            : '')
            + `<a class="qir-button qir-button-small" href="${reportEndpoint}" target="_blank" rel="noopener">افتح التقرير الخام</a>`;
        detailsContent.innerHTML = groups.length
            ? groups.map((group) => (
                `<details class="qir-sample" open>`
                + `<summary>${esc(group.label)} <span>(${number(group.total)} إجماليًا، تُعرض عينة)</span></summary>`
                + `<pre>${esc(JSON.stringify(group.values, null, 2))}</pre>`
                + `</details>`
            )).join('')
            : '<p class="qir-empty">لا توجد عينات مسجلة لهذا البند.</p>';
        renderCards();
        details.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }

    function updateOverview() {
        const report = state.report;
        if (!report) return;
        const reference = report.reference || {};
        const set = (id, value) => {
            const element = document.getElementById(id);
            if (element) element.textContent = number(value);
        };
        const status = document.getElementById('qir-status');
        if (status) status.textContent = report.status || 'unknown';
        set('qir-failure-count', report.failure_count);
        set('qir-verse-count', reference.verse_count);
        set('qir-word-count', reference.word_count);
        set('qir-text-token-count', reference.text_token_count);
    }

    async function loadReport() {
        try {
            const response = await fetch(reportEndpoint, {
                headers: { Accept: 'application/json' },
                cache: 'no-store',
            });
            const payload = await response.json();
            if (!response.ok) throw new Error(payload.error || 'تعذّر تحميل التقرير');
            state.report = payload;
            updateOverview();
            renderCards();
        } catch (error) {
            resultCount.textContent = error.message;
            findingsList.innerHTML = `<div class="qir-empty">${esc(error.message)}</div>`;
        }
    }

    filterButtons.forEach((button) => {
        button.addEventListener('click', () => {
            state.filter = button.dataset.qirFilter || 'all';
            filterButtons.forEach((item) => {
                const active = item === button;
                item.classList.toggle('is-active', active);
                item.setAttribute('aria-pressed', active ? 'true' : 'false');
            });
            renderCards();
        });
    });

    searchInput?.addEventListener('input', () => {
        state.query = searchInput.value.trim();
        renderCards();
    });

    findingsList?.addEventListener('click', (event) => {
        const button = event.target.closest('[data-qir-details]');
        if (button) renderDetails(button.dataset.qirDetails);
    });

    closeDetails?.addEventListener('click', () => {
        details.hidden = true;
        state.selected = null;
        renderCards();
    });

    loadReport();
})();
