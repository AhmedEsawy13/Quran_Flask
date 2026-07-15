/* أثَر — shared, framework-free UI behavior.
 * Keeps async states, status messages, disclosures, and popovers consistent
 * across pages without coupling their page-specific rendering logic.
 */
(function () {
    'use strict';

    function setBusy(element, busy) {
        if (!element) return;
        if (busy) element.setAttribute('aria-busy', 'true');
        else element.removeAttribute('aria-busy');
        element.classList.toggle('athar-is-busy', !!busy);
    }

    function renderState(container, kind, message) {
        if (!container) return null;
        container.replaceChildren();
        const state = document.createElement('div');
        state.className = `athar-state athar-state-${kind || 'empty'}`;
        state.setAttribute('role', kind === 'error' ? 'alert' : 'status');

        if (kind === 'loading') {
            const spinner = document.createElement('span');
            spinner.className = 'athar-state-spinner';
            spinner.setAttribute('aria-hidden', 'true');
            state.appendChild(spinner);
        }
        const label = document.createElement('span');
        label.textContent = message || '';
        state.appendChild(label);
        container.appendChild(state);
        return state;
    }

    function setDisclosure(trigger, panel, open) {
        if (!trigger || !panel) return false;
        const expanded = open === undefined ? panel.hidden : !!open;
        panel.hidden = !expanded;
        trigger.setAttribute('aria-expanded', String(expanded));
        trigger.classList.toggle('athar-is-open', expanded);
        return expanded;
    }

    function fitPopover(panel, gutter) {
        if (!panel || panel.hidden) return;
        panel.style.transform = '';
        const edge = Number.isFinite(gutter) ? gutter : 12;
        const rect = panel.getBoundingClientRect();
        const viewportWidth = document.documentElement.clientWidth;
        let shift = 0;
        if (rect.left < edge) shift = edge - rect.left;
        else if (rect.right > viewportWidth - edge) shift = viewportWidth - edge - rect.right;
        if (shift) panel.style.transform = `translateX(${Math.round(shift)}px)`;
    }

    function createPopoverGroup() {
        const entries = [];

        function register(trigger, panel) {
            if (!trigger || !panel || entries.some(entry => entry.panel === panel)) return;
            entries.push({ trigger, panel });
        }

        function close(except) {
            entries.forEach(({ trigger, panel }) => {
                if (panel === except) return;
                setDisclosure(trigger, panel, false);
            });
        }

        function toggle(trigger, panel) {
            if (!trigger || !panel) return false;
            const opening = panel.hidden;
            close(opening ? panel : null);
            const expanded = setDisclosure(trigger, panel, opening);
            if (expanded) fitPopover(panel);
            return expanded;
        }

        return Object.freeze({ register, close, toggle });
    }

    function createStatus(element, options) {
        const config = Object.assign({
            visibleClass: 'athar-status-visible',
            errorClass: 'athar-status-error',
            defaultDuration: 1800,
        }, options || {});
        let timer = 0;

        function clear() {
            window.clearTimeout(timer);
            timer = 0;
            if (!element) return;
            element.hidden = true;
            element.textContent = '';
            element.classList.remove(config.visibleClass, config.errorClass);
        }

        function show(message, showOptions) {
            if (!element || !message) { clear(); return; }
            const opts = Object.assign({ error: false, duration: config.defaultDuration }, showOptions || {});
            window.clearTimeout(timer);
            element.textContent = message;
            element.hidden = false;
            element.classList.toggle(config.errorClass, !!opts.error);
            element.classList.add(config.visibleClass);
            if (opts.duration > 0) timer = window.setTimeout(clear, opts.duration);
        }

        clear();
        return Object.freeze({ clear, show });
    }

    window.AtharUi = Object.freeze({
        createPopoverGroup,
        createStatus,
        fitPopover,
        renderState,
        setBusy,
        setDisclosure,
    });
})();
