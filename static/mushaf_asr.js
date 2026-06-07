/* ═══════════════════════════════════════════════════════════════════════════
   Mushaf ASR — live "recite & follow" using the streaming FastConformer Quran
   model (Muno459/fastconformer-quran-streaming) via onnxruntime-web.

   STATUS: BETA / best-effort. It loads the model from the HuggingFace CDN and
   runs entirely in the browser (mic → 80-dim log-mel → streaming ONNX with
   cache tensors → CTC greedy → BPE detokenise). The page (mushaf_memorize.js)
   feeds it the expected verses and matches the transcript to follow along.

   THINGS THAT MUST MATCH THE MODEL REPO (verify against streaming_inference_example.py):
     • ASR_CONFIG.cmvnUrl / vocabUrl / modelUrl filenames.
     • The exact CMVN constants (loaded from streaming_global_cmvn.npz) and which
       variant to use (clean_* studio vs tlog_* phone). We default to clean_*.
     • Mel params (NeMo defaults assumed: 16 kHz, n_fft 512, win 400, hop 160,
       80 mels, 0–8000 Hz, log). Adjust MEL if the repo differs.
     • ONNX input/output + cache names/shapes (documented on the model card):
         in : audio_signal[1,80,T], length[1], cache_last_channel[1,17,70,512],
              cache_last_time[1,17,512,8], cache_last_channel_len[1]
         out: logprobs[1,T',1025], encoded_lengths, cache_*_next.   blank id = 1024.
     • The tokenizer: we expect a plain vocab list (1025 lines / JSON array) where
       a leading '▁' marks a word boundary (SentencePiece). If the repo ships a
       binary .model tokenizer instead, export a vocab list and point vocabUrl at it.

   It is fully isolated: lazy-loaded, and every failure is reported via onStatus
   so it can never break the memorize page.
   ═══════════════════════════════════════════════════════════════════════════ */
(function () {
    'use strict';

    const ORT_URL = 'https://cdn.jsdelivr.net/npm/onnxruntime-web@1.19.2/dist/ort.min.js';
    const HF = 'https://huggingface.co/Muno459/fastconformer-quran-streaming/resolve/main';
    const ASR_CONFIG = {
        modelUrl: `${HF}/model.q8.onnx`,          // INT8, ~132 MB
        cmvnUrl:  `${HF}/streaming_global_cmvn.npz`,
        vocabUrl: `${HF}/vocab.txt`,              // fallback handled below
        cmvnVariant: 'clean',                     // 'clean' (studio) | 'tlog' (phone)
        chunkSec: 1.0,
        blankId: 1024,
    };
    const MEL = { sr: 16000, nFft: 512, win: 400, hop: 160, nMels: 80, fMin: 0, fMax: 8000 };

    let session = null, cmvn = null, vocab = null;
    let audioCtx = null, micStream = null, workletNode = null, source = null;
    let cache = null, transcriptIds = [], onTranscript = null, onStatus = null, onActive = null;
    let pcmBuffer = new Float32Array(0);
    let running = false;

    const status = m => { try { onStatus && onStatus(m); } catch (e) {} };

    /* ── tiny .npy / .npz reader (for the CMVN constants) ─────────────────── */
    async function loadNpz(url) {
        const buf = new Uint8Array(await (await fetch(url)).arrayBuffer());
        // .npz is a ZIP of .npy entries. Minimal local-file-header walk (stored or
        // deflate). We only need the float arrays named like clean_mean / clean_istd.
        const out = {};
        let i = 0;
        const dv = new DataView(buf.buffer);
        while (i + 4 <= buf.length && dv.getUint32(i, true) === 0x04034b50) {
            const method = dv.getUint16(i + 8, true);
            const nameLen = dv.getUint16(i + 26, true), extraLen = dv.getUint16(i + 28, true);
            let comp = dv.getUint32(i + 18, true), uncomp = dv.getUint32(i + 22, true);
            const name = new TextDecoder().decode(buf.subarray(i + 30, i + 30 + nameLen)).replace(/\.npy$/, '');
            const dataStart = i + 30 + nameLen + extraLen;
            let raw = buf.subarray(dataStart, dataStart + comp);
            if (method === 8) { // deflate — use DecompressionStream if available
                raw = new Uint8Array(await new Response(new Blob([raw]).stream().pipeThrough(new DecompressionStream('deflate-raw'))).arrayBuffer());
            }
            out[name] = parseNpy(raw);
            i = dataStart + comp;
            if (comp === 0 && uncomp === 0) break; // streamed sizes in data descriptor — bail
        }
        return out;
    }
    function parseNpy(u8) {
        const hlen = new DataView(u8.buffer, u8.byteOffset + 8, 2).getUint16(0, true);
        const header = new TextDecoder().decode(u8.subarray(10, 10 + hlen));
        const dtype = (header.match(/'descr':\s*'([^']+)'/) || [])[1] || '<f4';
        const body = u8.subarray(10 + hlen);
        if (dtype.includes('f4')) return new Float32Array(body.buffer, body.byteOffset, body.byteLength / 4);
        if (dtype.includes('f8')) return Float32Array.from(new Float64Array(body.buffer, body.byteOffset, body.byteLength / 8));
        throw new Error('unsupported npy dtype ' + dtype);
    }

    async function loadVocab(url) {
        const r = await fetch(url);
        if (!r.ok) throw new Error('vocab not found at ' + url + ' — export a vocab list from the model repo and set ASR_CONFIG.vocabUrl');
        const txt = await r.text();
        return txt.trim().startsWith('[') ? JSON.parse(txt) : txt.split('\n').map(s => s.replace(/\r$/, ''));
    }

    /* ── mel filterbank ───────────────────────────────────────────────────── */
    const hz2mel = f => 1127 * Math.log(1 + f / 700);
    const mel2hz = m => 700 * (Math.exp(m / 1127) - 1);
    function melFilters() {
        const { nFft, nMels, fMin, fMax, sr } = MEL;
        const nBins = nFft / 2 + 1;
        const mlo = hz2mel(fMin), mhi = hz2mel(fMax);
        const pts = Array.from({ length: nMels + 2 }, (_, i) => mel2hz(mlo + (mhi - mlo) * i / (nMels + 1)));
        const bin = pts.map(h => Math.floor((nFft + 1) * h / sr));
        const fb = Array.from({ length: nMels }, () => new Float32Array(nBins));
        for (let m = 1; m <= nMels; m++) for (let k = bin[m - 1]; k < bin[m + 1]; k++) {
            if (k < 0 || k >= nBins) continue;
            fb[m - 1][k] = k < bin[m]
                ? (k - bin[m - 1]) / (bin[m] - bin[m - 1] || 1)
                : (bin[m + 1] - k) / (bin[m + 1] - bin[m] || 1);
        }
        return fb;
    }
    const _fb = melFilters();
    const _ham = Array.from({ length: MEL.win }, (_, i) => 0.54 - 0.46 * Math.cos(2 * Math.PI * i / (MEL.win - 1)));

    // naive DFT magnitude (win is small, ~400 — fine for ~1s chunks at 10ms hop)
    function frameMel(frame) {
        const { nFft, win } = MEL, nBins = nFft / 2 + 1;
        const re = new Float32Array(nBins), im = new Float32Array(nBins);
        for (let k = 0; k < nBins; k++) {
            let sr2 = 0, si = 0;
            for (let n = 0; n < win; n++) { const a = -2 * Math.PI * k * n / nFft, x = frame[n] * _ham[n]; sr2 += x * Math.cos(a); si += x * Math.sin(a); }
            re[k] = sr2; im[k] = si;
        }
        const out = new Float32Array(MEL.nMels);
        for (let m = 0; m < MEL.nMels; m++) {
            let s = 0; const f = _fb[m];
            for (let k = 0; k < nBins; k++) { const p = re[k] * re[k] + im[k] * im[k]; s += p * f[k]; }
            out[m] = Math.log(s + 1e-6);
        }
        return out;
    }
    function pcmToMel(pcm) {
        const { win, hop, nMels } = MEL;
        const nFrames = Math.max(0, 1 + Math.floor((pcm.length - win) / hop));
        const T = nFrames, feat = new Float32Array(nMels * T);  // [nMels, T]
        const mean = cmvn && cmvn[ASR_CONFIG.cmvnVariant + '_mean'];
        const istd = cmvn && cmvn[ASR_CONFIG.cmvnVariant + '_istd'];
        for (let t = 0; t < T; t++) {
            const mel = frameMel(pcm.subarray(t * hop, t * hop + win));
            for (let m = 0; m < nMels; m++) {
                let v = mel[m];
                if (mean && istd) v = (v - mean[m]) * istd[m];
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
        let prev = -1;
        for (let t = 0; t < Tp; t++) {
            let best = 0, bv = -Infinity;
            for (let v = 0; v < V; v++) { const x = d[t * V + v]; if (x > bv) { bv = x; best = v; } }
            if (best !== ASR_CONFIG.blankId && best !== prev) transcriptIds.push(best);
            prev = best;
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
        if (pcmBuffer.length >= need) {
            const slice = pcmBuffer.subarray(0, need);
            runChunk(slice.slice());
            pcmBuffer = pcmBuffer.subarray(need - MEL.win).slice(); // keep window overlap
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
                window.ort.env.wasm.numThreads = Math.min(4, (navigator.hardwareConcurrency || 2));
                session = await window.ort.InferenceSession.create(ASR_CONFIG.modelUrl, { executionProviders: ['wasm'] });
            }
            if (!cmvn) { status('تحميل ثوابت المعايرة…'); try { cmvn = await loadNpz(ASR_CONFIG.cmvnUrl); } catch (e) { cmvn = null; } }
            if (!vocab) { status('تحميل المعجم…'); vocab = await loadVocab(ASR_CONFIG.vocabUrl); }

            status('طلب إذن الميكروفون…');
            micStream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true } });
            audioCtx = new (window.AudioContext || window.webkitAudioContext)();
            source = audioCtx.createMediaStreamSource(micStream);
            const proc = audioCtx.createScriptProcessor(4096, 1, 1);
            proc.onaudioprocess = e => { if (running) pushPcm(downsample(e.inputBuffer.getChannelData(0), audioCtx.sampleRate)); };
            source.connect(proc); proc.connect(audioCtx.destination);
            workletNode = proc;

            cache = freshCache(); transcriptIds = []; pcmBuffer = new Float32Array(0);
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
