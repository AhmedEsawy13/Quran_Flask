/* ═══════════════════════════════════════════════════════════════════════════
   Mushaf Zipformer ASR — streaming PHONEME recognition for Quran recitation
   using Muno459/zipformer_p-quran (Zipformer2 streaming CTC) via onnxruntime-web.

   Runs in the browser: mic → 80-bin Kaldi/Povey fbank → streaming Zipformer2
   (98 cache tensors carried across 61-frame steps, advance 48) → CTC greedy →
   phonemes. Validated end-to-end in Python at ~96% phoneme match on al-Fatiha.

   Assets (served from /static/asr, gitignored — local until prod hosting):
     • quran_phoneme_zipformer.int8.onnx  (73 MB)
     • zipformer_meta.json      {T:61, shift:48, blank:250, states:[…98]}
     • zipformer_phonemes.json  model-id(0..249) → phoneme symbol (id+1 shift)
   KEY gotchas (see memory zipformer-quran-asr): CTC blank = id 250 (NOT the
   <blank>:0 in phoneme_units.json); model id M ↔ phoneme at units id M+1 —
   both baked into zipformer_phonemes.json. Fbank matches lhotse to 5e-5.

   Emits a running phoneme string (onPhonemes) and silence/pause events
   (onSilence) — id-250 runs are the model's native non-speech, used for وقف.
   The passage→word alignment (phoneme DP) lives in the page glue.
   ═══════════════════════════════════════════════════════════════════════════ */
(function () {
    'use strict';

    const ORT_URL = 'https://cdn.jsdelivr.net/npm/onnxruntime-web@1.19.2/dist/ort.min.js';
    const CFG = {
        modelUrls: ['/static/asr/quran_phoneme_zipformer.int8.onnx'],
        metaUrl:  '/static/asr/zipformer_meta.json',
        phonUrl:  '/static/asr/zipformer_phonemes.json',
        silenceSec: 0.45,          // id-250 (non-speech) run ≥ this after phonemes = a stop
    };
    // Kaldi/lhotse fbank params (validated vs training front-end).
    const SR = 16000, FLEN = 400, FSHIFT = 160, NFFT = 512, NMEL = 80;
    const LOW = 20.0, HIGH = 7600.0, PREEMPH = 0.97, FLOOR = 1e-10;

    let session = null, meta = null, phon = null;
    let audioCtx = null, micStream = null, workletNode = null, source = null;
    let onPhonemes = null, onSilence = null, onStatus = null, onActive = null;
    let running = false;

    const status = m => { try { onStatus && onStatus(m); } catch (e) {} };
    const loadJson = async u => { const r = await fetch(u); if (!r.ok) throw new Error('fetch ' + u + ' ' + r.status); return r.json(); };

    /* ── fbank (kaldi Povey, snip_edges=false) — matches lhotse to ~5e-5 ────── */
    const POVEY = new Float64Array(FLEN);
    for (let i = 0; i < FLEN; i++) POVEY[i] = Math.pow(0.5 - 0.5 * Math.cos(2 * Math.PI * i / (FLEN - 1)), 0.85);
    const mel = f => 1127.0 * Math.log(1.0 + f / 700.0);
    const FB = (() => {
        const nb = NFFT / 2 + 1, mlo = mel(LOW), mhi = mel(HIGH), pts = [];
        for (let i = 0; i < NMEL + 2; i++) pts.push(mlo + (mhi - mlo) * i / (NMEL + 1));
        const fb = Array.from({ length: NMEL }, () => new Float64Array(nb));
        for (let b = 0; b < NMEL; b++) {
            const l = pts[b], c = pts[b + 1], r = pts[b + 2];
            for (let k = 0; k < nb; k++) {
                const m = mel(k * SR / NFFT);
                fb[b][k] = (m > l && m <= c) ? (m - l) / (c - l) : (m > c && m < r) ? (r - m) / (r - c) : 0;
            }
        }
        return fb;
    })();
    function fftPower(frame) {
        const re = new Float64Array(NFFT), im = new Float64Array(NFFT);
        re.set(frame);
        for (let i = 1, j = 0; i < NFFT; i++) {
            let bit = NFFT >> 1;
            for (; j & bit; bit >>= 1) j ^= bit;
            j ^= bit;
            if (i < j) { const tr = re[i]; re[i] = re[j]; re[j] = tr; const ti = im[i]; im[i] = im[j]; im[j] = ti; }
        }
        for (let len = 2; len <= NFFT; len <<= 1) {
            const ang = -2 * Math.PI / len, wr = Math.cos(ang), wi = Math.sin(ang);
            for (let i = 0; i < NFFT; i += len) {
                let cwr = 1, cwi = 0;
                for (let k = 0; k < len / 2; k++) {
                    const a = i + k, b = i + k + len / 2;
                    const vr = re[b] * cwr - im[b] * cwi, vi = re[b] * cwi + im[b] * cwr;
                    re[b] = re[a] - vr; im[b] = im[a] - vi; re[a] += vr; im[a] += vi;
                    const nr = cwr * wr - cwi * wi; cwi = cwr * wi + cwi * wr; cwr = nr;
                }
            }
        }
        const nb = NFFT / 2 + 1, P = new Float64Array(nb);
        for (let k = 0; k < nb; k++) P[k] = re[k] * re[k] + im[k] * im[k];
        return P;
    }
    const reflect = (s, n) => { while (s < 0 || s >= n) s = s < 0 ? -s - 1 : 2 * n - s - 1; return s; };
    // one fbank frame m over raw buffer x (length n); returns Float32Array(80)
    function fbankFrame(x, n, m) {
        const buf = new Float64Array(FLEN);
        const start = m * FSHIFT + (FSHIFT >> 1) - (FLEN >> 1);
        for (let j = 0; j < FLEN; j++) buf[j] = x[reflect(start + j, n)];
        let mean = 0; for (let j = 0; j < FLEN; j++) mean += buf[j]; mean /= FLEN;
        for (let j = 0; j < FLEN; j++) buf[j] -= mean;
        for (let j = FLEN - 1; j >= 1; j--) buf[j] -= PREEMPH * buf[j - 1];
        buf[0] -= PREEMPH * buf[0];
        for (let j = 0; j < FLEN; j++) buf[j] *= POVEY[j];
        const P = fftPower(buf), row = new Float32Array(NMEL);
        for (let b = 0; b < NMEL; b++) { let e = 0; const w = FB[b]; for (let k = 0; k < P.length; k++) e += P[k] * w[k]; row[b] = Math.log(Math.max(e, FLOOR)); }
        return row;
    }
    const numFrames = n => Math.floor((n + FSHIFT / 2) / FSHIFT);

    /* ── streaming decoder ────────────────────────────────────────────────── */
    function freshStates() {
        const ort = window.ort, st = {};
        for (const s of meta.states) {
            const size = s.shape.reduce((a, b) => a * b, 1);
            st[s.name] = new ort.Tensor(s.int64 ? 'int64' : 'float32',
                s.int64 ? new BigInt64Array(size) : new Float32Array(size), s.shape);
        }
        return st;
    }
    // Run ONE model step on a [61,80] feature block; returns argmax id array.
    async function step(states, featBlock) {
        const ort = window.ort;
        const T = meta.T, x = new Float32Array(T * NMEL);
        for (let t = 0; t < T; t++) x.set(featBlock[t], t * NMEL);
        const feed = { x: new ort.Tensor('float32', x, [1, T, NMEL]) };
        for (const s of meta.states) feed[s.name] = states[s.name];
        const out = await session.run(feed);
        for (const s of meta.states) states[s.name] = out['new_' + s.name];  // new_X → X
        const lp = out.log_probs, [, Tp, V] = lp.dims, d = lp.data, ids = [];
        for (let t = 0; t < Tp; t++) {
            let best = 0, bv = -Infinity;
            for (let v = 0; v < V; v++) { const z = d[t * V + v]; if (z > bv) { bv = z; best = v; } }
            ids.push(best);
        }
        return ids;
    }
    // CTC-collapse a flat id stream (already across steps) → phoneme string.
    // blank = meta.blank (250). Repeats collapsed at the raw-frame level upstream.
    function idsToPhonemes(ids) {
        let s = '';
        for (const id of ids) if (id !== meta.blank) s += (phon[id] || '');
        return s;
    }

    /* ── OFFLINE: transcribe a whole Float32 PCM clip (for validation) ─────── */
    async function transcribe(samples) {
        await ensureLoaded();
        const n = samples.length, nf = numFrames(n);
        const feats = [];
        for (let m = 0; m < nf; m++) feats.push(fbankFrame(samples, n, m));
        const st = freshStates();
        const T = meta.T, shift = meta.shift;
        let raw = [], cur = 0;
        while (cur + T <= feats.length) {
            const block = feats.slice(cur, cur + T);
            const ids = await step(st, block);
            raw.push(...ids);
            cur += shift;
        }
        // collapse consecutive repeats, then drop blank
        const coll = [];
        for (let i = 0; i < raw.length; i++) if (i === 0 || raw[i] !== raw[i - 1]) coll.push(raw[i]);
        return { ids: coll, phonemes: idsToPhonemes(coll) };
    }

    /* ── asset loading (Cache-Storage-persisted model) ────────────────────── */
    const MODEL_CACHE = 'mushaf-zipformer-v1';
    async function fetchModelBytes() {
        const cache = window.caches ? await caches.open(MODEL_CACHE).catch(() => null) : null;
        let lastErr;
        for (const url of CFG.modelUrls) {
            try {
                if (cache) { const hit = await cache.match(url); if (hit) { status('تحميل النموذج من الذاكرة…'); return new Uint8Array(await hit.arrayBuffer()); } }
                const r = await fetch(url); if (!r.ok) throw new Error('HTTP ' + r.status);
                const total = +(r.headers.get('content-length') || 0);
                const reader = r.body && total ? r.body.getReader() : null;
                let bytes;
                if (reader) {
                    const chunks = []; let got = 0, last = -1;
                    for (;;) { const { done, value } = await reader.read(); if (done) break; chunks.push(value); got += value.length; const p = (got * 100 / total) | 0; if (p !== last) { last = p; status(`تنزيل النموذج ${p}% (${(total / 1048576) | 0}MB)`); } }
                    bytes = new Uint8Array(got); let o = 0; for (const c of chunks) { bytes.set(c, o); o += c.length; }
                } else bytes = new Uint8Array(await r.arrayBuffer());
                if (cache) { try { await cache.put(url, new Response(bytes)); } catch (e) {} }
                return bytes;
            } catch (e) { lastErr = e; }
        }
        throw lastErr || new Error('model fetch failed');
    }
    async function ensureLoaded() {
        if (!window.ort) { status('تحميل محرك التعرّف…'); await new Promise((res, rej) => { const s = document.createElement('script'); s.src = ORT_URL; s.onload = res; s.onerror = rej; document.head.appendChild(s); }); }
        if (!meta) meta = await loadJson(CFG.metaUrl);
        if (!phon) phon = await loadJson(CFG.phonUrl);
        if (!session) {
            window.ort.env.wasm.numThreads = 1;
            window.ort.env.wasm.wasmPaths = 'https://cdn.jsdelivr.net/npm/onnxruntime-web@1.19.2/dist/';
            const bytes = await fetchModelBytes();
            status('تهيئة النموذج…');
            session = await window.ort.InferenceSession.create(bytes, { executionProviders: ['wasm'] });
        }
    }

    /* ── LIVE streaming from the mic ──────────────────────────────────────── */
    let pcm = new Float32Array(0), frames = [], fc = 0, states = null;
    let silentSec = 0, sawPhoneme = false, busy = false, phonemeStr = '';
    function downsample(buf, inRate) {
        if (inRate === SR) return buf;
        const ratio = inRate / SR, n = Math.floor(buf.length / ratio), out = new Float32Array(n);
        for (let i = 0; i < n; i++) out[i] = buf[Math.floor(i * ratio)];
        return out;
    }
    function pushPcm(chunk) {
        const merged = new Float32Array(pcm.length + chunk.length);
        merged.set(pcm); merged.set(chunk, pcm.length); pcm = merged;
        drain();
    }
    async function drain() {
        if (busy || !session) return;
        busy = true;
        try {
            // compute any fbank frames whose full window is now available
            const T = meta.T, shift = meta.shift;
            let avail = numFrames(pcm.length);
            // a frame m needs raw up to m*FSHIFT + (FSHIFT/2)+(FLEN/2); keep it simple: only
            // compute frames whose end index < pcm.length so no right-edge reflection mid-stream
            while (frames.length < avail && (frames.length * FSHIFT + (FSHIFT >> 1) + (FLEN >> 1)) < pcm.length) {
                frames.push(fbankFrame(pcm, pcm.length, frames.length));
            }
            while (frames.length >= fc + T) {
                const block = frames.slice(fc, fc + T);
                const ids = await step(states, block);
                fc += shift;
                const frameDur = shift / SR / (ids.length || 1);
                for (const id of ids) {
                    if (id === meta.blank) {
                        silentSec += frameDur;
                        if (sawPhoneme && silentSec >= CFG.silenceSec) { try { onSilence && onSilence({ atSec: fc * FSHIFT / SR }); } catch (e) {} sawPhoneme = false; }
                    } else {
                        silentSec = 0; sawPhoneme = true;
                        const sym = phon[id] || '';
                        if (sym) { phonemeStr += sym; try { onPhonemes && onPhonemes(phonemeStr, id); } catch (e) {} }
                    }
                }
            }
        } catch (e) { /* keep the stream alive */ }
        finally { busy = false; }
    }

    async function start(opts) {
        onPhonemes = opts.onPhonemes; onSilence = opts.onSilence; onStatus = opts.onStatus; onActive = opts.onActive;
        if (running) return;
        try {
            await ensureLoaded();
            status('طلب إذن الميكروفون…');
            micStream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true } });
            audioCtx = new (window.AudioContext || window.webkitAudioContext)();
            source = audioCtx.createMediaStreamSource(micStream);
            const onPcm = ch => { if (running && ch) pushPcm(downsample(ch, audioCtx.sampleRate)); };
            let usedWorklet = false;
            if (audioCtx.audioWorklet) {
                try {
                    const code = "class P extends AudioWorkletProcessor{process(i){const c=i[0]&&i[0][0];if(c)this.port.postMessage(new Float32Array(c));return true}}registerProcessor('zf-mic',P)";
                    const url = URL.createObjectURL(new Blob([code], { type: 'application/javascript' }));
                    await audioCtx.audioWorklet.addModule(url); URL.revokeObjectURL(url);
                    const node = new AudioWorkletNode(audioCtx, 'zf-mic');
                    node.port.onmessage = e => onPcm(e.data);
                    source.connect(node); node.connect(audioCtx.destination);
                    workletNode = node; usedWorklet = true;
                } catch (e) {}
            }
            if (!usedWorklet) {
                const proc = audioCtx.createScriptProcessor(4096, 1, 1);
                proc.onaudioprocess = e => onPcm(e.inputBuffer.getChannelData(0));
                source.connect(proc); proc.connect(audioCtx.destination); workletNode = proc;
            }
            pcm = new Float32Array(0); frames = []; fc = 0; states = freshStates();
            silentSec = 0; sawPhoneme = false; busy = false; phonemeStr = '';
            running = true; onActive && onActive(true);
            status('🎙️ استمع… ابدأ التلاوة');
        } catch (e) { stop(); throw e; }
    }
    function stop() {
        running = false;
        try { workletNode && workletNode.disconnect(); } catch (e) {}
        try { source && source.disconnect(); } catch (e) {}
        try { micStream && micStream.getTracks().forEach(t => t.stop()); } catch (e) {}
        try { audioCtx && audioCtx.close(); } catch (e) {}
        workletNode = source = micStream = audioCtx = null;
        onActive && onActive(false);
        status('توقّف الاستماع.');
    }

    window.MushafZipformer = { start, stop, transcribe, config: CFG };
})();
