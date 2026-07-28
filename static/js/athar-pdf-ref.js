/* ═══════════════════════════════════════════════════════════════════
   AtharPdfRef — render one page of a remote PDF into a blob: image URL.
   Used for البحرين (islamhouse scan) so production needs no local PDF
   cache — same idea as Archive.org leaf images for الأزهر / قطر / الكويت.
   ═══════════════════════════════════════════════════════════════════ */
(function (global) {
    'use strict';

    const PDFJS_VER = '4.10.38';
    const PDFJS_BASE = `https://cdn.jsdelivr.net/npm/pdfjs-dist@${PDFJS_VER}/build`;

    let pdfjsLibPromise = null;
    const docPromises = new Map();
    const blobUrls = new Map(); // cacheKey → object URL

    function ensureLib() {
        if (!pdfjsLibPromise) {
            pdfjsLibPromise = import(`${PDFJS_BASE}/pdf.min.mjs`).then((lib) => {
                lib.GlobalWorkerOptions.workerSrc = `${PDFJS_BASE}/pdf.worker.min.mjs`;
                return lib;
            });
        }
        return pdfjsLibPromise;
    }

    function stripHash(url) {
        return String(url || '').split('#')[0];
    }

    function getDoc(url) {
        const key = stripHash(url);
        if (!key) return Promise.reject(new Error('missing pdf url'));
        if (!docPromises.has(key)) {
            docPromises.set(key, ensureLib().then((lib) => (
                lib.getDocument({
                    url: key,
                    withCredentials: false,
                    // Range requests keep the first page fast on a large scan.
                    disableAutoFetch: true,
                    disableStream: false,
                }).promise
            )));
        }
        return docPromises.get(key);
    }

    function revoke(cacheKey) {
        const prev = blobUrls.get(cacheKey);
        if (prev) {
            URL.revokeObjectURL(prev);
            blobUrls.delete(cacheKey);
        }
    }

    /**
     * @param {string} url remote PDF URL (hash ignored)
     * @param {number} pdfPage 1-based PDF page index (viewer numbering)
     * @param {{ maxWidth?: number }} [opts]
     * @returns {Promise<string>} blob: object URL (JPEG)
     */
    async function renderPage(url, pdfPage, opts) {
        const maxWidth = (opts && opts.maxWidth) || 1024;
        const pageNum = Math.max(1, Math.floor(Number(pdfPage) || 1));
        const cacheKey = `${stripHash(url)}#${pageNum}@${maxWidth}`;
        if (blobUrls.has(cacheKey)) return blobUrls.get(cacheKey);

        const doc = await getDoc(url);
        if (pageNum > doc.numPages) {
            throw new Error(`pdf page ${pageNum} out of range (${doc.numPages})`);
        }
        const page = await doc.getPage(pageNum);
        const base = page.getViewport({ scale: 1 });
        const scale = Math.min(maxWidth / base.width, 2);
        const viewport = page.getViewport({ scale });
        const canvas = document.createElement('canvas');
        canvas.width = Math.ceil(viewport.width);
        canvas.height = Math.ceil(viewport.height);
        const ctx = canvas.getContext('2d', { alpha: false });
        await page.render({ canvasContext: ctx, viewport }).promise;

        const blob = await new Promise((resolve, reject) => {
            canvas.toBlob(
                (b) => (b ? resolve(b) : reject(new Error('pdf page encode failed'))),
                'image/jpeg',
                0.84,
            );
        });
        const objectUrl = URL.createObjectURL(blob);
        // Keep a small sliding cache so page flips stay snappy.
        if (blobUrls.size > 6) {
            const oldest = blobUrls.keys().next().value;
            revoke(oldest);
        }
        blobUrls.set(cacheKey, objectUrl);
        return objectUrl;
    }

    function prefetchNeighbors(url, pdfPage, opts) {
        const maxWidth = (opts && opts.maxWidth) || 1024;
        [pdfPage - 1, pdfPage + 1].forEach((n) => {
            if (n < 1) return;
            renderPage(url, n, { maxWidth }).catch(() => {});
        });
    }

    global.AtharPdfRef = { renderPage, prefetchNeighbors, stripHash };
})(window);
