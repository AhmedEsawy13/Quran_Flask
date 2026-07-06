/* ═══════════════════════════════════════════════════════════════════════════
   Mushaf ASR — live "recite & follow" using the streaming FastConformer Quran
   model (Muno459/fastconformer-quran-streaming) via onnxruntime-web.

   Runs entirely in the browser: mic → 80-dim log-mel (NeMo: slaney mel, hann,
   pre-emphasis 0.97, log) → CMVN (clean_mean/clean_std) → streaming ONNX with
   cache tensors → CTC greedy → SentencePiece detokenise. The page
   (mushaf_memorize.js) feeds it the expected verses and matches the transcript
   to follow along. VALIDATED end-to-end in Python against a real ayah at
   chunkSec=0.5 (it decoded «بسم الله الرحمن الرحيم» correctly).

   Local assets (served from /static, exported from the files you downloaded):
     • asr_model.q8.onnx  — model_streaming_with_encoder.q8.onnx (INT8, 132 MB)
     • asr_cmvn.json      — from streaming_global_cmvn.npz (clean_ and tlog_)
     • asr_vocab.json     — 1024 SentencePiece pieces (tokenizer.model exported)
   ONNX: in audio_signal[1,80,T],length,cache_last_channel[1,17,70,512],
   cache_last_time[1,17,512,8],cache_last_channel_len; out logprobs[1,T',1025]
   (blank=1024) + cache_*_next. Use cmvnVariant 'tlog' for phone-mic audio if
   'clean' underperforms.

   Fully isolated: lazy-loaded, every failure reported via onStatus so it can
   never break the memorize page.
   ═══════════════════════════════════════════════════════════════════════════ */
(function () {
    'use strict';

    const ORT_URL = 'https://cdn.jsdelivr.net/npm/onnxruntime-web@1.19.2/dist/ort.min.js';
    const ASR_CONFIG = {
        // Tried in order. Local /static is fast in dev; on a host that can't serve
        // the 132 MB file (e.g. Vercel's Python lambda) it falls back to the HF CDN.
        modelUrls: [
            '/static/asr/asr_model.q8.onnx',
            'https://huggingface.co/Muno459/fastconformer-quran-streaming/resolve/main/model_streaming_with_encoder.q8.onnx',
        ],
        cmvnUrl:  '/static/asr/asr_cmvn.json',
        vocabUrl: '/static/asr/asr_vocab.json',
        cmvnVariant: 'tlog',                      // 'tlog' (phone/real-world, default) | 'clean' (studio)
        chunkSec: 0.5,                            // validated: 0.5 s chunks decode best (chunked attention)
        blankId: 1024,                            // logprobs has 1025 classes; 1024 = CTC blank
        silenceSec: 0.55,                         // a QUIET pause of ≥ this long after a word = a STOP (وقف)
        // Adaptive silence (librosa top_db style): a chunk is "silent" when its
        // RMS drops far below a DECAYING recent peak — independent of mic gain,
        // unlike a fixed absolute threshold. Tune silenceRatio if over/under-firing.
        silenceRatio: 0.1,                        // quiet when chunk RMS < 10% of recent peak (~ −20 dB)
        silenceFloor: 0.006,                      // absolute RMS below which it's silence regardless of peak
        peakDecay: 0.94,                          // per-chunk decay of the recent-peak reference (~2 s memory)
    };
    // NeMo AudioToMelSpectrogram defaults (slaney mel scale, hann, preemph, log).
    const MEL = { sr: 16000, nFft: 512, win: 400, hop: 160, nMels: 80, fMin: 0, fMax: 8000,
                  preemph: 0.97, logGuard: Math.pow(2, -24) };

    let session = null, cmvn = null, vocab = null;
    let audioCtx = null, micStream = null, workletNode = null, source = null;
    let cache = null, transcriptIds = [], onTranscript = null, onStatus = null, onActive = null;
    let onWord = null, onStop = null;              // Phase-2: word-level follow + stop (وقف) events
    let pcmBuffer = new Float32Array(0);
    let running = false, lastTok = -1;  // lastTok dedups CTC repeats ACROSS chunks
    // Word segmentation + pause tracking, threaded through the CTC frame stream.
    let words = [];                     // [{ text, startSec, endSec }] closed words, in order
    let curWord = null;                 // word currently being built from sub-word pieces
    let clockSec = 0;                   // audio timeline cursor (start of the next chunk)
    let blankSec = 0;                   // length of the current run of consecutive blank frames
    let peakRms = 0;                    // decaying recent-peak audio level (adaptive silence reference)

    const status = m => { try { onStatus && onStatus(m); } catch (e) {} };
    const loadJson = async url => { const r = await fetch(url); if (!r.ok) throw new Error('fetch ' + url + ' → ' + r.status); return r.json(); };

    /* ── model bytes: Cache-Storage-persisted + streamed progress ──────────── */
    const MODEL_CACHE = 'mushaf-asr-model-v1';
    async function readWithProgress(resp, label) {
        const total = +(resp.headers.get('content-length') || 0);
        if (!resp.body || !total) return new Uint8Array(await resp.arrayBuffer());
        const reader = resp.body.getReader();
        const chunks = []; let got = 0, lastPct = -1;
        for (;;) {
            const { done, value } = await reader.read();
            if (done) break;
            chunks.push(value); got += value.length;
            const pct = Math.floor(got * 100 / total);
            if (pct !== lastPct) { lastPct = pct; status(`${label} ${pct}% (${(total / 1048576) | 0}MB)`); }
        }
        const out = new Uint8Array(got); let off = 0;
        for (const c of chunks) { out.set(c, off); off += c.length; }
        return out;
    }
    // Try each URL; serve from Cache Storage if present, else download once and
    // persist so later sessions (and offline use) start instantly.
    async function fetchModelBytes() {
        let lastErr = null;
        const cache = window.caches ? await caches.open(MODEL_CACHE).catch(() => null) : null;
        for (const url of ASR_CONFIG.modelUrls) {
            try {
                if (cache) {
                    const hit = await cache.match(url);
                    if (hit) { status('تحميل النموذج من الذاكرة…'); return new Uint8Array(await hit.arrayBuffer()); }
                }
                const resp = await fetch(url);
                if (!resp.ok) throw new Error('HTTP ' + resp.status);
                const bytes = await readWithProgress(resp.clone(), 'تنزيل النموذج');
                if (cache) { try { await cache.put(url, new Response(bytes)); } catch (e) {} }
                return bytes;
            } catch (e) { lastErr = e; }
        }
        throw lastErr || new Error('model fetch failed');
    }

    /* ── mel filterbank — librosa/NeMo "slaney" mel scale + slaney norm ────── */
    const SF = 200 / 3, MIN_LOG_HZ = 1000, MIN_LOG_MEL = MIN_LOG_HZ / SF, LOGSTEP = Math.log(6.4) / 27;
    const hz2mel = hz => hz < MIN_LOG_HZ ? hz / SF : MIN_LOG_MEL + Math.log(hz / MIN_LOG_HZ) / LOGSTEP;
    const mel2hz = m => m < MIN_LOG_MEL ? m * SF : MIN_LOG_HZ * Math.exp(LOGSTEP * (m - MIN_LOG_MEL));
    function melFilters() {
        const { nFft, nMels, fMin, fMax, sr } = MEL;
        const nBins = nFft / 2 + 1;
        const fftFreqs = Array.from({ length: nBins }, (_, k) => k * sr / nFft);
        const mlo = hz2mel(fMin), mhi = hz2mel(fMax);
        const melPts = Array.from({ length: nMels + 2 }, (_, i) => mel2hz(mlo + (mhi - mlo) * i / (nMels + 1)));
        const fb = Array.from({ length: nMels }, () => new Float32Array(nBins));
        for (let m = 0; m < nMels; m++) {
            const lo = melPts[m], ctr = melPts[m + 1], hi = melPts[m + 2];
            const enorm = 2 / (hi - lo);  // slaney normalisation
            for (let k = 0; k < nBins; k++) {
                const f = fftFreqs[k];
                const lower = (f - lo) / (ctr - lo), upper = (hi - f) / (hi - ctr);
                const w = Math.max(0, Math.min(lower, upper));
                fb[m][k] = w * enorm;
            }
        }
        return fb;
    }
    const _fb = melFilters();
    const _hann = Array.from({ length: MEL.win }, (_, i) => 0.5 - 0.5 * Math.cos(2 * Math.PI * i / (MEL.win - 1)));

    // naive DFT power spectrum (win ~400 — fine for ~1 s chunks at 10 ms hop)
    function frameMel(frame) {
        const { nFft, win, logGuard } = MEL, nBins = nFft / 2 + 1;
        const w = new Float32Array(nFft);  // pre-emphasised, windowed, zero-padded to nFft
        for (let n = 0; n < win; n++) {
            const pe = n > 0 ? frame[n] - MEL.preemph * frame[n - 1] : frame[n] * (1 - MEL.preemph);
            w[n] = pe * _hann[n];
        }
        const out = new Float32Array(MEL.nMels);
        const re = new Float32Array(nBins), im = new Float32Array(nBins);
        for (let k = 0; k < nBins; k++) {
            let sr2 = 0, si = 0;
            for (let n = 0; n < win; n++) { const a = -2 * Math.PI * k * n / nFft; sr2 += w[n] * Math.cos(a); si += w[n] * Math.sin(a); }
            re[k] = sr2; im[k] = si;
        }
        for (let m = 0; m < MEL.nMels; m++) {
            let s = 0; const f = _fb[m];
            for (let k = 0; k < nBins; k++) s += (re[k] * re[k] + im[k] * im[k]) * f[k]; // power spectrum
            out[m] = Math.log(s + logGuard);
        }
        return out;
    }
    function pcmToMel(pcm) {
        const { win, hop, nMels } = MEL;
        const T = Math.max(0, 1 + Math.floor((pcm.length - win) / hop));
        const feat = new Float32Array(nMels * T);  // [nMels, T]
        const mean = cmvn && cmvn[ASR_CONFIG.cmvnVariant + '_mean'];
        const std = cmvn && cmvn[ASR_CONFIG.cmvnVariant + '_std'];
        for (let t = 0; t < T; t++) {
            const mel = frameMel(pcm.subarray(t * hop, t * hop + win));
            for (let m = 0; m < nMels; m++) {
                let v = mel[m];
                if (mean && std) v = (v - mean[m]) / std[m];
                feat[m * T + t] = v;
            }
        }
        return { feat, T };
    }

    /* ── streaming inference ──────────────────────────────────────────────── */
    function freshCache() {
        const ort = window.ort;
        return {
            cache_last_channel: new ort.Tensor('float32', new Float32Array(1 * 17 * 70 * 512), [1, 17, 70, 512]),
            cache_last_time: new ort.Tensor('float32', new Float32Array(1 * 17 * 512 * 8), [1, 17, 512, 8]),
            cache_last_channel_len: new ort.Tensor('int64', new BigInt64Array([0n]), [1]),
        };
    }
    // Close the word being built at `endSec` and report it. Never touches blankSec.
    function closeWord(endSec) {
        if (!curWord) return;
        curWord.endSec = endSec;
        words.push(curWord);
        const idx = words.length - 1, w = curWord;
        curWord = null;
        try { onWord && onWord(w, idx); } catch (e) {}
    }
    // A pause long enough to count as a وقف: seal the current word and fire a stop.
    function fireStop(atSec) {
        const idx = words.length;                // the index this word will occupy
        closeWord(atSec);
        try { onStop && onStop({ wordIndex: idx, word: words[idx], atSec }); } catch (e) {}
        blankSec = 0;                            // don't re-fire within the same silence
    }
    async function runChunk(pcm, chunkStartSec) {
        const ort = window.ort;
        const { feat, T } = pcmToMel(pcm);
        if (T < 4) return;
        const input = {
            audio_signal: new ort.Tensor('float32', feat, [1, MEL.nMels, T]),
            length: new ort.Tensor('int64', new BigInt64Array([BigInt(T)]), [1]),
            cache_last_channel: cache.cache_last_channel,
            cache_last_time: cache.cache_last_time,
            cache_last_channel_len: cache.cache_last_channel_len,
        };
        const out = await session.run(input);
        cache = {
            cache_last_channel: out.cache_last_channel_next,
            cache_last_time: out.cache_last_time_next,
            cache_last_channel_len: out.cache_last_channel_next_len,
        };
        const lp = out.logprobs;                 // [1, T', 1025]
        const [, Tp, V] = lp.dims, d = lp.data;
        const frameDur = (pcm.length / MEL.sr) / Tp;   // seconds per output frame
        // A وقف is a QUIET pause. The CTC emits blank frames even mid-recitation
        // (between/inside voiced words), so a blank-run alone gives false stops —
        // gate the pause timer on audio energy dropping below a recent-peak-
        // relative threshold (adaptive to mic gain; see ASR_CONFIG above).
        let sumSq = 0; for (let i = 0; i < pcm.length; i++) sumSq += pcm[i] * pcm[i];
        const chunkRms = Math.sqrt(sumSq / Math.max(1, pcm.length));
        peakRms = Math.max(chunkRms, peakRms * ASR_CONFIG.peakDecay);
        const quiet = chunkRms < Math.max(ASR_CONFIG.silenceFloor, peakRms * ASR_CONFIG.silenceRatio);
        for (let t = 0; t < Tp; t++) {
            let best = 0, bv = -Infinity;
            for (let v = 0; v < V; v++) { const x = d[t * V + v]; if (x > bv) { bv = x; best = v; } }
            const tSec = chunkStartSec + t * frameDur;
            if (best === ASR_CONFIG.blankId) {
                if (quiet) {                         // silence → accumulate toward a stop
                    blankSec += frameDur;
                    if (curWord && blankSec >= ASR_CONFIG.silenceSec) fireStop(tSec);
                } else {
                    blankSec = 0;                    // voice present → not a وقف
                }
            } else {
                if (best !== lastTok) {
                    transcriptIds.push(best);
                    const piece = vocab ? (vocab[best] || '') : '';
                    if (piece.startsWith('▁') || !curWord) { // '▁' marks a word boundary
                        if (curWord) closeWord(tSec);
                        curWord = { text: piece.replace(/▁/g, ''), startSec: tSec, endSec: tSec };
                    } else {
                        curWord.text += piece;               // continuation of the same word
                    }
                }
                blankSec = 0;
            }
            lastTok = best;
        }
        emit();
    }
    function emit() {
        if (!vocab) return;
        let s = '';
        for (const id of transcriptIds) { const piece = vocab[id] || ''; s += piece.replace(/▁/g, ' '); }
        try { onTranscript && onTranscript(s.trim()); } catch (e) {}
    }

    /* ── mic capture (downsample to 16 kHz) ───────────────────────────────── */
    function pushPcm(chunk) {
        const merged = new Float32Array(pcmBuffer.length + chunk.length);
        merged.set(pcmBuffer); merged.set(chunk, pcmBuffer.length);
        pcmBuffer = merged;
        const need = Math.round(MEL.sr * ASR_CONFIG.chunkSec);
        const ov = MEL.win - MEL.hop;            // small overlap so boundary frames aren't lost
        if (pcmBuffer.length >= need) {
            runChunk(pcmBuffer.subarray(0, need).slice(), clockSec);
            clockSec += (need - ov) / MEL.sr;    // advance the timeline by the NEW audio consumed
            pcmBuffer = pcmBuffer.subarray(need - ov).slice();
        }
    }
    function downsample(buf, inRate) {
        if (inRate === MEL.sr) return buf;
        const ratio = inRate / MEL.sr, n = Math.floor(buf.length / ratio), out = new Float32Array(n);
        for (let i = 0; i < n; i++) out[i] = buf[Math.floor(i * ratio)];
        return out;
    }

    async function start(opts) {
        onTranscript = opts.onTranscript; onStatus = opts.onStatus; onActive = opts.onActive;
        onWord = opts.onWord; onStop = opts.onStop;
        if (running) return;
        try {
            if (!window.ort) { status('تحميل محرك التعرّف…'); await new Promise((res, rej) => { const s = document.createElement('script'); s.src = ORT_URL; s.onload = res; s.onerror = rej; document.head.appendChild(s); }); }
            if (!session) {
                window.ort.env.wasm.numThreads = 1; // no COOP/COEP needed (SharedArrayBuffer-free)
                window.ort.env.wasm.wasmPaths = 'https://cdn.jsdelivr.net/npm/onnxruntime-web@1.19.2/dist/';
                const modelBytes = await fetchModelBytes();   // cached after first run
                status('تهيئة النموذج…');
                session = await window.ort.InferenceSession.create(modelBytes, { executionProviders: ['wasm'] });
            }
            if (!cmvn) { status('تحميل ثوابت المعايرة…'); try { cmvn = await loadJson(ASR_CONFIG.cmvnUrl); } catch (e) { cmvn = null; } }
            if (!vocab) { status('تحميل المعجم…'); vocab = await loadJson(ASR_CONFIG.vocabUrl); }

            status('طلب إذن الميكروفون…');
            micStream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true } });
            audioCtx = new (window.AudioContext || window.webkitAudioContext)();
            source = audioCtx.createMediaStreamSource(micStream);
            const onPcm = ch => { if (running && ch) pushPcm(downsample(ch, audioCtx.sampleRate)); };

            // Prefer the modern AudioWorklet (off the main thread); fall back to the
            // deprecated ScriptProcessor on browsers without worklet support.
            let usedWorklet = false;
            if (audioCtx.audioWorklet) {
                try {
                    const code = "class P extends AudioWorkletProcessor{process(i){const c=i[0]&&i[0][0];if(c)this.port.postMessage(new Float32Array(c));return true}}registerProcessor('mz-mic',P)";
                    const url = URL.createObjectURL(new Blob([code], { type: 'application/javascript' }));
                    await audioCtx.audioWorklet.addModule(url);
                    URL.revokeObjectURL(url);
                    const node = new AudioWorkletNode(audioCtx, 'mz-mic');
                    node.port.onmessage = e => onPcm(e.data);
                    source.connect(node); node.connect(audioCtx.destination); // process() writes no output → silent
                    workletNode = node; usedWorklet = true;
                } catch (e) { /* fall through to ScriptProcessor */ }
            }
            if (!usedWorklet) {
                const proc = audioCtx.createScriptProcessor(4096, 1, 1);
                proc.onaudioprocess = e => onPcm(e.inputBuffer.getChannelData(0));
                source.connect(proc); proc.connect(audioCtx.destination);
                workletNode = proc;
            }

            cache = freshCache(); transcriptIds = []; pcmBuffer = new Float32Array(0); lastTok = -1;
            words = []; curWord = null; clockSec = 0; blankSec = 0; peakRms = 0;
            running = true; onActive && onActive(true);
            status('🎙️ استمع… ابدأ التلاوة');
        } catch (e) {
            stop();
            throw e;
        }
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

    window.MushafASR = { start, stop, config: ASR_CONFIG, getWords: () => words.slice() };
})();
