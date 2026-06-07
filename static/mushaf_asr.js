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
        modelUrl: '/static/asr_model.q8.onnx',    // INT8 streaming model (with encoder), ~132 MB
        cmvnUrl:  '/static/asr_cmvn.json',        // {clean_mean,clean_std,tlog_mean,tlog_std}
        vocabUrl: '/static/asr_vocab.json',       // 1024 SentencePiece pieces (id→piece)
        cmvnVariant: 'clean',                     // 'clean' (studio) | 'tlog' (phone)
        chunkSec: 0.5,                            // validated: 0.5 s chunks decode best (chunked attention)
        blankId: 1024,                            // logprobs has 1025 classes; 1024 = CTC blank
    };
    // NeMo AudioToMelSpectrogram defaults (slaney mel scale, hann, preemph, log).
    const MEL = { sr: 16000, nFft: 512, win: 400, hop: 160, nMels: 80, fMin: 0, fMax: 8000,
                  preemph: 0.97, logGuard: Math.pow(2, -24) };

    let session = null, cmvn = null, vocab = null;
    let audioCtx = null, micStream = null, workletNode = null, source = null;
    let cache = null, transcriptIds = [], onTranscript = null, onStatus = null, onActive = null;
    let pcmBuffer = new Float32Array(0);
    let running = false, lastTok = -1;  // lastTok dedups CTC repeats ACROSS chunks

    const status = m => { try { onStatus && onStatus(m); } catch (e) {} };
    const loadJson = async url => { const r = await fetch(url); if (!r.ok) throw new Error('fetch ' + url + ' → ' + r.status); return r.json(); };

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
    async function runChunk(pcm) {
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
        for (let t = 0; t < Tp; t++) {
            let best = 0, bv = -Infinity;
            for (let v = 0; v < V; v++) { const x = d[t * V + v]; if (x > bv) { bv = x; best = v; } }
            if (best !== ASR_CONFIG.blankId && best !== lastTok) transcriptIds.push(best);
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
            runChunk(pcmBuffer.subarray(0, need).slice());
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
        if (running) return;
        try {
            if (!window.ort) { status('تحميل محرك التعرّف…'); await new Promise((res, rej) => { const s = document.createElement('script'); s.src = ORT_URL; s.onload = res; s.onerror = rej; document.head.appendChild(s); }); }
            if (!session) {
                status('تحميل النموذج (~132MB أول مرة)…');
                window.ort.env.wasm.numThreads = 1; // no COOP/COEP needed (SharedArrayBuffer-free)
                session = await window.ort.InferenceSession.create(ASR_CONFIG.modelUrl, { executionProviders: ['wasm'] });
            }
            if (!cmvn) { status('تحميل ثوابت المعايرة…'); try { cmvn = await loadJson(ASR_CONFIG.cmvnUrl); } catch (e) { cmvn = null; } }
            if (!vocab) { status('تحميل المعجم…'); vocab = await loadJson(ASR_CONFIG.vocabUrl); }

            status('طلب إذن الميكروفون…');
            micStream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true } });
            audioCtx = new (window.AudioContext || window.webkitAudioContext)();
            source = audioCtx.createMediaStreamSource(micStream);
            const proc = audioCtx.createScriptProcessor(4096, 1, 1);
            proc.onaudioprocess = e => { if (running) pushPcm(downsample(e.inputBuffer.getChannelData(0), audioCtx.sampleRate)); };
            source.connect(proc); proc.connect(audioCtx.destination);
            workletNode = proc;

            cache = freshCache(); transcriptIds = []; pcmBuffer = new Float32Array(0); lastTok = -1;
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

    window.MushafASR = { start, stop, config: ASR_CONFIG };
})();
