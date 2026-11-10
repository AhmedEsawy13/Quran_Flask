/* أثَر — التحقق من التجويد (Quran Lab TajweedFormer, runs in the browser).
 *
 * The «تلاوة» button of the reader: the learner recites the selected verse, the SDK follows the recitation word by word
 * on the device, and the words that "may need another look" are marked on the verse. Never a ruling or a grade, and the
 * licence notice sits where results appear. Settings (preset, word level) come from the portal, not from this file.
 *
 * Skill and rules: https://portal.quranlab.ai/skills/quranlab-sdk/SKILL.md. The SDK is vendored under
 * static/vendor/tajweedformer-2.0.1 and resolved through the import map of templates/index.html. The web key is
 * public by design (meta «quranlab-key») and works only from the origins registered for it on the portal.
 */
import { TajweedFormer } from '@quran-lab/tajweedformer';
import { QuranLab } from '@quran-lab/tajweedformer/platform';
import { enableSharing } from '@quran-lab/tajweedformer/consent';

const NOTICE = 'قد يخطئ التقييم الآلي للتجويد، ولا يغني عن معلّم مؤهَّل.';
const DIGITS = '٠١٢٣٤٥٦٧٨٩';
const ar = (n) => String(n).replace(/[0-9]/g, (d) => DIGITS[d]);

const $ = (id) => document.getElementById(id);
const button = $('tajweed-check-button');
const panel = $('tajweed-check-panel');
const statusLine = $('tajweed-check-status');
const detail = $('tajweed-check-detail');
const key = (document.querySelector('meta[name="quranlab-key"]') || {}).content || '';

let ql = null;
let sharing = null;
let tf = null;
let session = null; // { stream, ctx, node, mic, surah, ayah }
let busy = false;

function say(text, tone) {
    panel.hidden = false;
    statusLine.textContent = text;
    statusLine.dataset.tone = tone || '';
}

function tokens() {
    return [...document.querySelectorAll('#quran-text .word-token')];
}

function clearMarks() {
    tokens().forEach((token) => token.classList.remove('tj-flag', 'tj-open'));
    detail.replaceChildren();
}

async function platform() {
    if (ql) return ql;
    ql = await QuranLab.configure({ key, appVersion: 'athar-web' });
    if (ql.stopped) {
        const reason = ql.stopped;
        ql = null;
        throw Object.assign(new Error('platform refused the key'), { code: reason });
    }
    ql.startRefresh();
    try {
        sharing = enableSharing(ql, { lang: 'ar' });
        const settings = document.querySelector('quranlab-sharing-settings');
        if (settings) settings.controller = sharing;
    } catch (error) {
        console.warn('Sharing is not available', error);
    }
    return ql;
}

async function startTake() {
    clearMarks();
    const surah = Number($('surah-select').value);
    const ayah = Number($('ayah-select').value);
    if (!surah || !ayah) return;
    say('جارٍ التجهيز…');
    try {
        const platformClient = await platform();
        const ctx = new AudioContext();
        if (!tf) {
            say('يُحمَّل نموذج التجويد مرة واحدة (نحو ٥٧ ميغابايت)…');
            tf = await TajweedFormer.load({
                platform: platformClient,
                sampleRate: Math.min(48000, Math.max(8000, ctx.sampleRate)),
                onProgress: (p) => say(`يُحمَّل النموذج ${ar(Math.round((100 * p.loaded) / p.total))}٪${p.cached ? ' (محفوظ)' : ''}`),
            });
        }
        const mic = await navigator.mediaDevices.getUserMedia({
            audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: false },
        });
        await ctx.audioWorklet.addModule('/static/js/tajweed-worklet.js');
        const node = new AudioWorkletNode(ctx, 'tajweed-capture');
        const stream = tf.createStream({});
        node.port.onmessage = (event) => stream.pushAudio(event.data);
        ctx.createMediaStreamSource(mic).connect(node);
        session = { stream, ctx, node, mic, surah, ayah };
        button.classList.add('is-recording');
        button.querySelector('span').textContent = 'إنهاء';
        say('أنا أسمعك… اقرأ الآية ثم اضغط «إنهاء».', 'live');
    } catch (error) {
        fail(error);
    }
}

async function finishTake() {
    const current = session;
    session = null;
    button.classList.remove('is-recording');
    button.querySelector('span').textContent = 'تلاوة';
    say('جارٍ التحليل…');
    try {
        current.node.disconnect();
        current.mic.getTracks().forEach((track) => track.stop());
        await current.ctx.close();
        current.stream.finish();
        const result = await tf.score(current.stream.heads(), current.surah, current.ayah);
        current.stream.free();
        showResult(result);
        if (sharing && typeof sharing.sessionCompleted === 'function') sharing.sessionCompleted();
    } catch (error) {
        fail(error);
    }
}

function showResult(result) {
    const words = Array.isArray(result.words) ? result.words : [];
    const marks = tokens();
    const flagged = words.filter((word) => word.flagged);
    if (words.length === marks.length) {
        words.forEach((word, index) => {
            if (!word.flagged) return;
            const token = marks[index];
            token.classList.add('tj-flag');
            token.tabIndex = 0;
            token.addEventListener('click', () => explain(word, token));
            token.addEventListener('keydown', (event) => { if (event.key === 'Enter' || event.key === ' ') explain(word, token); });
        });
    }
    say(flagged.length
        ? `${ar(flagged.length)} من ${ar(words.length)} كلمة قد تحتاج إلى إعادة. اضغط على الكلمة المظلّلة لترى السبب.`
        : 'لم تُرصد كلمات تحتاج إلى مراجعة في هذه المحاولة.', flagged.length ? 'notes' : 'ok');
}

function explain(word, token) {
    tokens().forEach((other) => other.classList.remove('tj-open'));
    token.classList.add('tj-open');
    const best = word.best || {};
    const line = document.createElement('p');
    const edit = best.expectedUnit && best.alternativeUnit
        ? `المتوقَّع «${best.expectedUnit}» والمسموع أقرب إلى «${best.alternativeUnit}».`
        : 'قد تحتاج هذه الكلمة إلى إعادة.';
    line.textContent = `هذه الكلمة قد تحتاج إلى إعادة. ${edit}`;
    const maddRows = (Array.isArray(word.issues && word.issues.madd) ? word.issues.madd : []).filter((m) => m && m.flagged);
    detail.replaceChildren(line);
    maddRows.forEach((m) => {
        const row = document.createElement('p');
        row.textContent = `المدّ: سُمع ${ar(m.displayCount ?? m.count)} حركات، والمتوقَّع بين ${ar(m.allowedLo)} و${ar(m.allowedHi)}.`;
        detail.appendChild(row);
    });
}

function fail(error) {
    console.warn('Tajweed check', error);
    cleanupSession();
    const code = error && error.code;
    if (error && error.name === 'NotAllowedError') say('لم يُسمح باستخدام الميكروفون. فعّله من إعدادات المتصفح ثم أعد المحاولة.', 'error');
    else if (code) say('تعذّر تفعيل التحقق من التجويد على هذا الموقع بعد (مفتاح Quran Lab غير مفعَّل لهذا العنوان).', 'error');
    else say('تعذّر بدء التحقق من التجويد. تأكد من الاتصال بالإنترنت ثم أعد المحاولة.', 'error');
}

function cleanupSession() {
    if (session) {
        try { session.node.disconnect(); } catch (error) { /* already gone */ }
        try { session.mic.getTracks().forEach((track) => track.stop()); } catch (error) { /* already gone */ }
        try { session.ctx.close(); } catch (error) { /* already gone */ }
        try { session.stream.free(); } catch (error) { /* already gone */ }
        session = null;
    }
    button.classList.remove('is-recording');
    button.querySelector('span').textContent = 'تلاوة';
}

function init() {
    if (!button || !panel) return;
    if (!key) { button.hidden = true; return; }      // no key configured: the feature is off
    $('tajweed-check-notice').textContent = NOTICE;
    button.addEventListener('click', async () => {
        if (busy) return;
        busy = true;
        try {
            if (session) await finishTake();
            else await startTake();
        } finally {
            busy = false;
        }
    });
    // a new verse clears the marks of the old one (and drops a take that was still running)
    ['surah-select', 'ayah-select'].forEach((id) => $(id).addEventListener('change', () => {
        cleanupSession();
        clearMarks();
        panel.hidden = true;
    }));
}

init();
