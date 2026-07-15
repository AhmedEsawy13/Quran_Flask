/* أثَر — small shared JSON transport.
 * Converts every non-2xx response and malformed JSON payload into a real
 * exception with status/data attached, so pages cannot accidentally render an
 * API error object as successful content.
 */
(function () {
    'use strict';

    async function json(url, options) {
        const response = await fetch(url, options);
        let data = null;
        try {
            data = await response.json();
        } catch (cause) {
            const error = new Error(response.ok ? 'Invalid JSON response' : `HTTP ${response.status}`);
            error.status = response.status;
            error.cause = cause;
            throw error;
        }
        if (!response.ok) {
            const error = new Error((data && data.error) || `HTTP ${response.status}`);
            error.status = response.status;
            error.data = data;
            throw error;
        }
        return data;
    }

    window.AtharApi = Object.freeze({ json });
})();
