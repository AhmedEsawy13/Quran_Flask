/* Reader: the «إعدادات» button of narrow screens. Opens/closes the secondary controls (mushaf, reciter, repeat, range,
 * bookmarks), remembers the choice, and shows the current mushaf and reciter on the button so a closed panel still
 * says what is selected. Wide screens ignore it (the button is hidden and the controls are always shown). */
(function () {
    'use strict';
    const KEY = 'quranApp_settingsOpen';
    function init() {
        const button = document.getElementById('reader-settings-toggle');
        const section = button && button.closest('.reader-primary');
        if (!button || !section) return;
        const summary = document.getElementById('reader-settings-summary');
        const label = (id) => {
            const select = document.getElementById(id);
            const option = select && select.selectedOptions && select.selectedOptions[0];
            return option ? option.textContent.trim() : '';
        };
        const refresh = () => {
            if (!summary) return;
            const mushaf = label('quran-text-select').replace(/^مصحف\s*/, '');
            const reciter = label('reciter-select');
            summary.textContent = [mushaf, reciter].filter(Boolean).join(' · ');
        };
        const set = (open) => {
            section.classList.toggle('settings-open', open);
            button.setAttribute('aria-expanded', String(open));
            try { localStorage.setItem(KEY, open ? '1' : '0'); } catch (error) { /* private window */ }
        };
        let open = false;
        try { open = localStorage.getItem(KEY) === '1'; } catch (error) { /* ignore */ }
        set(open);
        button.addEventListener('click', () => set(!section.classList.contains('settings-open')));
        ['quran-text-select', 'reciter-select'].forEach((id) => {
            const select = document.getElementById(id);
            if (select) select.addEventListener('change', refresh);
        });
        // the reciter list fills after load; refresh when it does
        const reciter = document.getElementById('reciter-select');
        if (reciter) new MutationObserver(refresh).observe(reciter, { childList: true });
        refresh();
    }
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
    else init();
})();
