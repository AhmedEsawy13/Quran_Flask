"""
================================================================================
🎙️  معالجة قارئ جديد من الصفر — obadx + Whisper-Tarteel (مستوى المقطع)
    
    Verse-by-verse + Waqf positions + Word-level timestamps (حتى مع التكرار)

المنهجية (مستوى obadx segment):
    1. obadx/recitation-segmenter-v2 → توقيتات مطلقة لكل مقطع وقف (دقة 99%+)
       - كل مقطع = نَفَس واحد (لا تكرار داخلي) ✓
    2. Tanzil → النص المرجعي + علامات الوقف اليونيكودية
    3. Whisper-Tarteel (chunked) → نسخ كل مقطع (حتى لو > 30s)
       - chunking بـ 28s لتجاوز حد Whisper الأقصى
    4. wav2vec2 + CTC → word-level timestamps داخل كل مقطع
       - لا توقف طويل = لا مشكلة CTC
       - التكرار الفعلي = مقاطع منفصلة = كل كلمة تُحفظ
    5. مطابقة المقاطع بالآيات (Tasmeea-style) ← النص المعروف من المصحف

المدخلات:
    - 114 ملف SSS.mp3 (سور كاملة لقارئ بحفص)

المخرَجات:
    - قاعدة مقاطع وقف بتوقيتات مطلقة (مثل obadx Ahmed Amer DB)
    - 6,236 ملف verse مقصوصة
    - word-level timestamps لكل آية (شاملة التكرارات من obadx)
    - مواضع الوقف الفعلية للقارئ

✅ يعمل على Kaggle T4 GPU (~6 ساعات للقرآن كاملاً)
   Whisper chunking + segment-level CTC = أداء أفضل مع تكرارات
================================================================================
"""

# ───────────────────────────────────────────────────────────────────────────────
# التثبيتات (في خلية أولى منفصلة)
# ───────────────────────────────────────────────────────────────────────────────
import subprocess, sys

def _pip(*packages):
    subprocess.check_call(
        [sys.executable, "-m", "pip", "install", "-q", *packages],
        stdout=subprocess.DEVNULL,
    )

try:
    import recitations_segmenter  # noqa: F401
except ImportError:
    print("📦 تثبيت recitations-segmenter...")
    _pip("recitations-segmenter")

try:
    import soundfile  # noqa: F401
except ImportError:
    _pip("soundfile", "mutagen", "pydub")

import os
import re
import json
import sqlite3
import subprocess
from pathlib import Path
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

import torch
import torchaudio
import numpy as np
import requests
from tqdm.auto import tqdm

# torchaudio ≥ 2.1 حذف list_audio_backends — نُعيد إضافتها لتوافق recitations_segmenter
if not hasattr(torchaudio, "list_audio_backends"):
    torchaudio.list_audio_backends = lambda: ["ffmpeg"]

# torchaudio ≥ 2.2 حذف sox_effects وأصبح torchcodec يفشل مع MP3.
# نُعوّض read_audio بنسخة تستخدم ffmpeg مباشرة عبر pipe — موثوقة على أي بيئة.
def _ffmpeg_read_audio(path: str, sampling_rate: int = 16000) -> torch.Tensor:
    cmd = [
        "ffmpeg", "-i", path,
        "-f", "f32le", "-acodec", "pcm_f32le",
        "-ac", "1", "-ar", str(sampling_rate),
        "-loglevel", "error", "pipe:1",
    ]
    result = subprocess.run(cmd, capture_output=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg فشل في فك ترميز {path}:\n{result.stderr.decode()}")
    audio = np.frombuffer(result.stdout, dtype=np.float32).copy()
    return torch.from_numpy(audio)

import recitations_segmenter.segment as _rs_seg
_rs_seg.read_audio = _ffmpeg_read_audio

# ───────────────────────────────────────────────────────────────────────────────
# 📌 الإعدادات
# ───────────────────────────────────────────────────────────────────────────────

WORK_DIR  = Path("/kaggle/working")
SURAH_DIR = WORK_DIR / "00_surahs"    # السور الكاملة (مُحمَّلة تلقائياً)
QURAN_TEXT_FILE = WORK_DIR / "quran_uthmani.json"

SEGMENTS_DB = WORK_DIR / "01_segments.db"        # قاعدة مقاطع الوقف (مثل obadx)
VERSE_DIR   = WORK_DIR / "02_verses"             # ملفات الآيات
WAQF_JSON   = WORK_DIR / "03_waqf_positions.json" 
WORDS_JSON  = WORK_DIR / "04_word_timings.json"
HF_DIR      = WORK_DIR / "05_hf_dataset"

for d in [VERSE_DIR, HF_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# النماذج
SEGMENTER_MODEL = "obadx/recitation-segmenter-v2"
WHISPER_MODEL   = "tarteel-ai/whisper-base-ar-quran"   # WER 5.75% على القرآن
WAV2VEC_MODEL   = "jonatasgrosman/wav2vec2-large-xlsr-53-arabic"

# معاملات obadx
SEG_BATCH_SIZE   = 8
SEG_MIN_SILENCE  = 30   # ms - أصغر صمت يُعتبر وقف
SEG_MIN_SPEECH   = 30   # ms - أقصر مقطع كلام مقبول
SEG_PAD          = 30   # ms - padding حول كل مقطع

SAMPLE_RATE  = 16000
DEVICE       = "cuda" if torch.cuda.is_available() else "cpu"

# ─── معلومات القارئ ───────────────────────────────────────────────────────────
RECITER_NAME    = "أحمد محمد عامر"
RECITER_NAME_EN = "Ahmed Mohamed Amer"
# مصدر الصوت: Islamway — معرّف مجموعة المصحف المرتل لأحمد عامر
ISLAMWAY_ID  = "576"    # https://quran.islamway.net/quran3/576/SSS.mp3
FALLBACK_URLS = [
    "https://server10.mp3quran.net/Aamer/",
    "https://server8.mp3quran.net/Aamer/",
]

# ─── وضع الاختبار ─────────────────────────────────────────────────────────────
TEST_MODE   = True      # True = اختبار / False = كل القرآن (114 سورة)
TEST_SURAHS = [14]      # سورة إبراهيم
SURAHS_TO_RUN = TEST_SURAHS if TEST_MODE else list(range(1, 115))

# مسارات checkpoints
INTERVALS_CACHE = WORK_DIR / "intervals_cache.json"  # obadx checkpoint
CHECKPOINTS_DIR = WORK_DIR / ".checkpoints"          # سور مكتملة


# ───────────────────────────────────────────────────────────────────────────────
# 0️⃣  تحميل السور من Islamway
# ───────────────────────────────────────────────────────────────────────────────

def download_surahs():
    """تحميل 114 سورة من Islamway مع fallback لـ MP3Quran."""
    SURAH_DIR.mkdir(parents=True, exist_ok=True)
    missing = [s for s in SURAHS_TO_RUN if not (SURAH_DIR / f"{s:03d}.mp3").exists()]
    if not missing:
        print("📁 السور موجودة بالفعل")
        return

    print(f"📥 تحميل {len(missing)} سورة من Islamway...")
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://ar.islamway.net/",
    }

    failed = []
    for s in tqdm(missing, desc="تنزيل"):
        fpath = SURAH_DIR / f"{s:03d}.mp3"
        urls = [f"https://quran.islamway.net/quran3/{ISLAMWAY_ID}/{s:03d}.mp3"] + \
               [f"{base}{s:03d}.mp3" for base in FALLBACK_URLS]

        ok = False
        for url in urls:
            try:
                r = requests.get(url, stream=True, timeout=120, headers=headers)
                if r.status_code == 200:
                    with open(fpath, "wb") as f:
                        for chunk in r.iter_content(8192):
                            f.write(chunk)
                    if fpath.stat().st_size > 50_000:
                        ok = True
                        break
                    fpath.unlink(missing_ok=True)
            except Exception:
                pass

        if not ok:
            failed.append(s)
            print(f"   ❌ سورة {s}: فشل التحميل من كل المصادر")

    if failed:
        raise RuntimeError(
            f"فشل تحميل {len(failed)} سورة: {failed[:10]}\n"
            "تحقق من اتصال الشبكة أو حمّل السور يدوياً."
        )
    print(f"   ✓ تم تحميل {len(missing)} سورة")


# ───────────────────────────────────────────────────────────────────────────────
# 1️⃣  تحميل النص المرجعي من Tanzil
# ───────────────────────────────────────────────────────────────────────────────

def download_quran_text():
    """تحميل النص العثماني الكامل بحفص (مع رموز الوقف)."""
    if QURAN_TEXT_FILE.exists():
        return
    
    print("📥 تحميل نص القرآن من API Quran Cloud...")
    url = "https://api.alquran.cloud/v1/quran/quran-uthmani"
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    
    quran = {}
    for surah in r.json()["data"]["surahs"]:
        sn = surah["number"]
        quran[sn] = {a["numberInSurah"]: a["text"] for a in surah["ayahs"]}
    
    with open(QURAN_TEXT_FILE, "w", encoding="utf-8") as f:
        json.dump(quran, f, ensure_ascii=False, indent=2)
    print(f"   ✓ {sum(len(v) for v in quran.values())} آية")


def load_quran() -> dict[int, dict[int, str]]:
    with open(QURAN_TEXT_FILE, encoding="utf-8") as f:
        return {int(k): {int(ak): av for ak, av in v.items()} 
                for k, v in json.load(f).items()}


# ───────────────────────────────────────────────────────────────────────────────
# 2️⃣  تطبيع النص العربي
# ───────────────────────────────────────────────────────────────────────────────

WAQF_SYMBOLS = {
    '\u06D6': 'صلى',  # الوصل أولى
    '\u06D7': 'قلى',  # الوقف أولى
    '\u06D8': 'م',    # الوقف اللازم
    '\u06D9': 'لا',   # الوقف الممنوع
    '\u06DA': 'ج',    # الوقف الجائز
    '\u06DB': '∴',    # التعانق
    '\u06DC': 'س',    # السكت
}


def remove_diacritics_and_waqf(text: str) -> str:
    """إزالة التشكيل ورموز الوقف (نحفظ الحروف فقط)."""
    return re.sub(r'[\u064B-\u0652\u0670\u06D6-\u06ED]', '', text)


def normalize_for_alignment(text: str) -> str:
    """تطبيع النص ليتطابق مع vocab الـ wav2vec2."""
    text = remove_diacritics_and_waqf(text)
    text = re.sub(r'[إأآٱ]', 'ا', text)
    text = re.sub(r'ى', 'ي', text)
    text = re.sub(r'ة', 'ه', text)
    text = re.sub(r'[^\u0621-\u063A\u0641-\u064A\s]', ' ', text)
    return re.sub(r'\s+', ' ', text).strip()


def normalize_for_compare(text: str) -> str:
    """تطبيع للمقارنة بين نصوص (يبقي الحروف فقط متصلة)."""
    return normalize_for_alignment(text).replace(' ', '')


def extract_waqf_in_text(aya_text: str) -> list[dict]:
    """استخراج علامات الوقف من نص الآية."""
    no_diac = re.sub(r'[\u064B-\u0652\u0670]', '', aya_text)
    positions = []
    word_idx = 0
    in_word = False
    for ch in no_diac:
        if ch in WAQF_SYMBOLS:
            positions.append({
                "after_word_index": max(0, word_idx - 1),
                "symbol_unicode": ch,
                "symbol_name": WAQF_SYMBOLS[ch],
            })
        elif ch == ' ' and in_word:
            in_word = False
        elif '\u0621' <= ch <= '\u064A':
            if not in_word:
                word_idx += 1
                in_word = True
    return positions


# ───────────────────────────────────────────────────────────────────────────────
# 3️⃣  تشغيل obadx على كل سورة
# ───────────────────────────────────────────────────────────────────────────────

def run_obadx_on_all_surahs() -> dict[int, list[dict]]:
    """
    تشغيل obadx على كل السور — يعطي توقيتات مطلقة (start, end) لكل مقطع وقف.

    Returns: {surah_no: [{"start": float, "end": float}, ...]}
    """
    # ── checkpoint: أعِد استخدام نتائج سابقة لتجنب إعادة التشغيل ──────────────
    if INTERVALS_CACHE.exists():
        print(f"⚡ تحميل intervals من cache: {INTERVALS_CACHE.name}")
        with open(INTERVALS_CACHE, encoding="utf-8") as f:
            raw = json.load(f)
        cached = {int(k): v for k, v in raw.items()}
        # أضف فقط السور التي نحتاجها ولم تُحسَب بعد
        missing_sn = [s for s in SURAHS_TO_RUN if s not in cached]
        if not missing_sn:
            return {s: cached[s] for s in SURAHS_TO_RUN if s in cached}
        print(f"   {len(missing_sn)} سورة لم تُعالَج بعد — سيُكمَل...")
    else:
        cached = {}
        missing_sn = SURAHS_TO_RUN

    from recitations_segmenter import (
        segment_recitations, clean_speech_intervals
    )
    from transformers import AutoFeatureExtractor, AutoModelForAudioFrameClassification
    # نستخدم _ffmpeg_read_audio مباشرة بدل read_audio المكسورة في المكتبة

    print(f"📦 تحميل obadx: {SEGMENTER_MODEL}")
    processor = AutoFeatureExtractor.from_pretrained(SEGMENTER_MODEL)
    model = AutoModelForAudioFrameClassification.from_pretrained(SEGMENTER_MODEL)
    dtype = torch.bfloat16 if DEVICE == "cuda" else torch.float32
    model.to(DEVICE, dtype=dtype)

    surah_files = sorted(
        fp for s in missing_sn
        if (fp := SURAH_DIR / f"{s:03d}.mp3").exists()
    )
    if not surah_files:
        print(f"❌ لا توجد ملفات في {SURAH_DIR}")
        return cached
    
    print(f"\n🔪 تشغيل obadx على {len(surah_files)} سورة...")
    
    results = {}
    for fpath in tqdm(surah_files, desc="obadx"):
        try:
            sn = int(fpath.stem)
        except ValueError:
            continue
        
        wave = _ffmpeg_read_audio(str(fpath))
        outputs = segment_recitations(
            [wave], model, processor,
            device=DEVICE, dtype=dtype, batch_size=SEG_BATCH_SIZE,
        )
        
        # تنظيف المقاطع
        cleaned = clean_speech_intervals(
            outputs[0].speech_intervals,
            outputs[0].is_complete,
            min_silence_duration_ms=SEG_MIN_SILENCE,
            min_speech_duration_ms=SEG_MIN_SPEECH,
            pad_duration_ms=SEG_PAD,
            return_seconds=True,
        )

        # speech_intervals: قائمة [start, end] بالثواني
        intervals = []
        for interval in cleaned.clean_speech_intervals:
            if hasattr(interval, 'start'):
                intervals.append({"start": float(interval.start), "end": float(interval.end)})
            else:
                # في حالة الإرجاع كـ tuple/list
                intervals.append({"start": float(interval[0]), "end": float(interval[1])})
        
        results[sn] = intervals

    # تنظيف الذاكرة
    del model, processor
    if DEVICE == "cuda":
        torch.cuda.empty_cache()

    # ── حفظ cache ─────────────────────────────────────────────────────────────
    merged = {**cached, **results}
    with open(INTERVALS_CACHE, "w", encoding="utf-8") as f:
        json.dump({str(k): v for k, v in merged.items()}, f)
    print(f"   ✓ {sum(len(v) for v in results.values()):,} مقطع وقف جديد (cache محفوظ)")
    return {s: merged[s] for s in SURAHS_TO_RUN if s in merged}


# ───────────────────────────────────────────────────────────────────────────────
# 4️⃣  Whisper-Tarteel للنسخ + wav2vec2 للمحاذاة
# ───────────────────────────────────────────────────────────────────────────────

class HybridProcessor:
    """
    Whisper-Tarteel: نسخ المقطع → نص للمطابقة بالآية
    wav2vec2: محاذاة الكلمات داخل المقطع → word timestamps
    """
    
    def __init__(self):
        from transformers import (
            WhisperForConditionalGeneration, WhisperProcessor,
            Wav2Vec2ForCTC, Wav2Vec2Processor,
        )
        
        print(f"📦 تحميل Tarteel-Whisper: {WHISPER_MODEL}")
        self.wp = WhisperProcessor.from_pretrained(WHISPER_MODEL)
        self.wm = WhisperForConditionalGeneration.from_pretrained(
            WHISPER_MODEL).to(DEVICE).eval()
        self.wm.config.forced_decoder_ids = None
        
        print(f"📦 تحميل wav2vec2: {WAV2VEC_MODEL}")
        self.w2v_proc = Wav2Vec2Processor.from_pretrained(WAV2VEC_MODEL)
        self.w2v_model = Wav2Vec2ForCTC.from_pretrained(
            WAV2VEC_MODEL).to(DEVICE).eval()
        self.vocab = self.w2v_proc.tokenizer.get_vocab()
        self.blank_id = self.vocab.get("<pad>", 0)
        self.word_sep = self.vocab.get("|", None)
    
    @torch.no_grad()
    def transcribe(self, audio: np.ndarray) -> str:
        """نسخ بـ Whisper-Tarteel (حد أقصى 30s للمدخل)."""
        if len(audio) < SAMPLE_RATE * 0.1:
            return ""
        feats = self.wp.feature_extractor(
            audio, sampling_rate=SAMPLE_RATE, return_tensors="pt"
        ).input_features.to(DEVICE)
        
        ids = self.wm.generate(feats, max_length=448)
        return self.wp.tokenizer.batch_decode(
            ids, skip_special_tokens=True)[0].strip()

    def transcribe_chunked(self, audio: np.ndarray, max_chunk_s: int = 28) -> str:
        """
        نسخ مقطع بأي طول — يُقسّم كل 28s ثم يُدمج النص.
        Whisper مقيّد بـ 30s من الصوت كمدخل؛ هذا يتجاوز القيد
        لمقاطع obadx الطويلة دون أن نفقد الكلمات في النهاية.
        كل قطعة مستقلة ← لا مشكلة في التكرار أو الصمت الداخلي.
        """
        max_samples = max_chunk_s * SAMPLE_RATE
        if len(audio) <= max_samples:
            return self.transcribe(audio)
        parts = []
        for i in range(0, len(audio), max_samples):
            chunk = audio[i : i + max_samples]
            if len(chunk) < SAMPLE_RATE * 0.5:
                break
            t = self.transcribe(chunk)
            if t:
                parts.append(t)
        return " ".join(parts)

    @torch.no_grad()
    def align_words(self, audio: np.ndarray, text: str) -> list[dict]:
        """محاذاة كلمية بـ wav2vec2 + CTC forced alignment."""
        if len(audio) < SAMPLE_RATE * 0.1:
            return []
        
        words_orig = text.split()
        text_norm = normalize_for_alignment(text)
        words_norm = text_norm.split()
        
        if not words_norm:
            return []
        
        inputs = self.w2v_proc(audio, sampling_rate=SAMPLE_RATE,
                                return_tensors="pt").to(DEVICE)
        logits = self.w2v_model(inputs.input_values).logits
        log_probs = torch.log_softmax(logits, dim=-1)[0].cpu().numpy()
        T = log_probs.shape[0]
        
        token_ids = []
        for i, w in enumerate(words_norm):
            if i > 0 and self.word_sep is not None:
                token_ids.append(self.word_sep)
            for ch in w:
                if ch in self.vocab:
                    token_ids.append(self.vocab[ch])
        
        if not token_ids or T < len(token_ids):
            return []
        
        try:
            spans = self._ctc_align(log_probs, token_ids)
        except Exception:
            return []
        
        ratio = len(audio) / T / SAMPLE_RATE
        result = []
        word_idx = 0
        cur_spans = []
        for tid, sf, ef in spans:
            if tid == self.word_sep:
                if cur_spans and word_idx < len(words_orig):
                    result.append({
                        "word": words_orig[word_idx],
                        "start": round(cur_spans[0][0] * ratio, 3),
                        "end": round(cur_spans[-1][1] * ratio, 3),
                    })
                    word_idx += 1
                cur_spans = []
            else:
                cur_spans.append((sf, ef))
        if cur_spans and word_idx < len(words_orig):
            result.append({
                "word": words_orig[word_idx],
                "start": round(cur_spans[0][0] * ratio, 3),
                "end": round(cur_spans[-1][1] * ratio, 3),
            })
        return result
    
    def _ctc_align(self, log_probs: np.ndarray, token_ids: list[int]) -> list[tuple]:
        T = log_probs.shape[0]
        ext = [self.blank_id]
        for tid in token_ids:
            ext.append(tid)
            ext.append(self.blank_id)
        L = len(ext)
        if T < L // 2 + 1:
            return []
        
        NEG = -1e10
        dp = np.full((T, L), NEG, dtype=np.float32)
        bp = np.zeros((T, L), dtype=np.int8)
        dp[0, 0] = log_probs[0, ext[0]]
        if L > 1:
            dp[0, 1] = log_probs[0, ext[1]]
        
        for t in range(1, T):
            stay = dp[t-1, :].copy()
            move1 = np.concatenate(([NEG], dp[t-1, :-1]))
            skip2 = np.full(L, NEG, dtype=np.float32)
            for s in range(2, L):
                if ext[s] != self.blank_id and ext[s] != ext[s-2]:
                    skip2[s] = dp[t-1, s-2]
            
            choices = np.stack([stay, move1, skip2])
            best_choice = np.argmax(choices, axis=0)
            best_val = np.max(choices, axis=0)
            for s in range(L):
                dp[t, s] = best_val[s] + log_probs[t, ext[s]]
                bp[t, s] = best_choice[s]
        
        s = L-1 if L >= 2 and dp[T-1, L-1] > dp[T-1, L-2] else (L-2 if L >= 2 else 0)
        path = [s]
        for t in range(T-1, 0, -1):
            choice = bp[t, s]
            if choice == 1: s -= 1
            elif choice == 2: s -= 2
            path.append(s)
        path.reverse()
        
        result = []
        cur_pos = -1
        cur_start = 0
        for t, s in enumerate(path):
            tid = ext[s]
            if s != cur_pos and tid != self.blank_id:
                if cur_pos != -1 and ext[cur_pos] != self.blank_id:
                    result.append((ext[cur_pos], cur_start, t))
                cur_pos = s
                cur_start = t
            elif tid == self.blank_id and cur_pos != -1 and ext[cur_pos] != self.blank_id:
                result.append((ext[cur_pos], cur_start, t))
                cur_pos = -1
        if cur_pos != -1 and ext[cur_pos] != self.blank_id:
            result.append((ext[cur_pos], cur_start, T))
        return result


# ───────────────────────────────────────────────────────────────────────────────
# 5️⃣  Tasmeea: مطابقة المقاطع بالآيات
# ───────────────────────────────────────────────────────────────────────────────

def build_surah_word_index(quran: dict, surah_no: int) -> tuple[str, list[tuple[int, int]]]:
    """
    بناء نص السورة الكامل + خريطة كل كلمة → (ayah, word_index_in_ayah).
    """
    if surah_no not in quran:
        return "", []
    
    full_words = []
    word_to_aya = []
    for aya_no in sorted(quran[surah_no].keys()):
        aya_text = quran[surah_no][aya_no]
        norm_words = normalize_for_alignment(aya_text).split()
        for i, _ in enumerate(norm_words):
            full_words.append(norm_words[i])
            word_to_aya.append((aya_no, i))
    
    return " ".join(full_words), word_to_aya


def _word_sim(a: str, b: str) -> float:
    """تشابه كلمتين: 1.0 تطابق تام، 0.7 بادئة 4، 0.4 بادئة 3، 0 مختلف."""
    if a == b:
        return 1.0
    if len(a) >= 4 and len(b) >= 4 and a[:4] == b[:4]:
        return 0.7
    if len(a) >= 3 and len(b) >= 3 and a[:3] == b[:3]:
        return 0.4
    return 0.0


def match_segment_to_ayat(
    transcript_norm: str,
    surah_full_norm: str,
    word_to_aya: list[tuple[int, int]],
    cursor: int,
) -> tuple[int, int, float]:
    """
    Tasmeea-style: مطابقة نسخ المقطع بنص السورة الكاملة بدءاً من cursor.

    Returns: (start_word_global, end_word_global, match_score)
    """
    if not transcript_norm.strip():
        return cursor, cursor, 0.0

    full_words = surah_full_norm.split()
    trans_words = transcript_norm.split()
    n_trans = len(trans_words)

    if n_trans == 0 or cursor >= len(full_words):
        return cursor, cursor, 0.0

    best_start = cursor
    best_score = 0.0

    # نبحث من 5 كلمات خلف cursor حتى 50 أمامه (تصحيح cursor drift)
    search_lo = max(0, cursor - 5)
    search_hi = min(len(full_words) - n_trans + 1, cursor + 51)

    for start in range(search_lo, search_hi):
        score = sum(
            _word_sim(full_words[start + i], trans_words[i])
            for i in range(n_trans)
            if start + i < len(full_words)
        ) / n_trans
        if score > best_score:
            best_score = score
            best_start = start

    return best_start, best_start + n_trans - 1, best_score


# ───────────────────────────────────────────────────────────────────────────────
# 6️⃣  المعالجة الكاملة لسورة
# ───────────────────────────────────────────────────────────────────────────────

@dataclass
class Segment:
    surah: int
    seg_idx: int                  # ترتيب المقطع داخل السورة
    start_time: float             # ثانية في ملف السورة
    end_time: float
    transcript: str               # نسخ Whisper
    matched_text: str             # النص العثماني المطابق
    start_aya: int = 0
    end_aya: int = 0
    start_word: int = 0           # في الآية
    end_word: int = 0
    match_score: float = 0.0
    words: list = field(default_factory=list)  # word timings


def process_surah(
    surah_no: int,
    intervals: list[dict],
    quran: dict,
    proc: HybridProcessor,
) -> list[Segment]:
    """معالجة سورة كاملة: مقاطع → آيات → كلمات."""
    surah_path = SURAH_DIR / f"{surah_no:03d}.mp3"
    if not surah_path.exists():
        return []
    
    # تحميل الصوت كاملاً عبر ffmpeg (torchaudio.load مكسور مع MP3 على هذه البيئة)
    audio = _ffmpeg_read_audio(str(surah_path)).numpy()
    
    # نص السورة الكامل المطبّع + خريطة الآيات
    surah_full_norm, word_to_aya = build_surah_word_index(quran, surah_no)
    if not surah_full_norm:
        return []
    
    segments = []
    cursor = 0  # موضعنا في نص السورة (تقدمي)
    
    for seg_idx, iv in enumerate(intervals):
        # استخراج المقطع الصوتي
        s_smp = int(iv["start"] * SAMPLE_RATE)
        e_smp = int(iv["end"] * SAMPLE_RATE)
        chunk = audio[s_smp:e_smp]
        
        if len(chunk) < SAMPLE_RATE * 0.2:
            continue
        
        # 1) نسخ بـ Whisper-Tarteel (مع chunking للمقاطع > 28s)
        transcript = proc.transcribe_chunked(chunk)
        trans_norm = normalize_for_alignment(transcript)
        
        # 2) مطابقة بنص السورة
        start_w, end_w, score = match_segment_to_ayat(
            trans_norm, surah_full_norm, word_to_aya, cursor
        )
        
        # نص عثماني للمقطع المطابق
        full_words = surah_full_norm.split()
        if start_w < len(full_words) and end_w < len(full_words):
            matched_norm = " ".join(full_words[start_w:end_w + 1])
            start_aya, start_word_in_aya = word_to_aya[start_w]
            end_aya, end_word_in_aya = word_to_aya[min(end_w, len(word_to_aya)-1)]
        else:
            matched_norm = trans_norm
            start_aya = end_aya = 0
            start_word_in_aya = end_word_in_aya = 0
        
        # 3) محاذاة كلمية بـ wav2vec2 على مستوى المقطع
        # كل مقطع obadx = نَفَس واحد ← لا تكرار داخلي ← CTC يعمل بشكل مثالي.
        # النص المطابق (matched_norm) معروف من المصحف، نستخدمه مباشرة.
        align_text = matched_norm if score > 0.5 else trans_norm
        words_aligned = proc.align_words(chunk, align_text)

        # تحويل التوقيتات النسبية للمقطع → مطلقة في ملف السورة
        for w in words_aligned:
            w["start_abs"] = round(iv["start"] + w["start"], 3)
            w["end_abs"] = round(iv["start"] + w["end"], 3)
        
        seg = Segment(
            surah=surah_no,
            seg_idx=seg_idx,
            start_time=iv["start"],
            end_time=iv["end"],
            transcript=transcript,
            matched_text=matched_norm,
            start_aya=start_aya,
            end_aya=end_aya,
            start_word=start_word_in_aya,
            end_word=end_word_in_aya,
            match_score=score,
            words=words_aligned,
        )
        segments.append(seg)
        
        # تقدم cursor (مع تسامح: لا نتقدم لو score منخفض)
        if score > 0.5:
            cursor = end_w + 1
    
    return segments


# ───────────────────────────────────────────────────────────────────────────────
# 7️⃣  حفظ نتائج كل سورة
# ───────────────────────────────────────────────────────────────────────────────

def init_db():
    """قاعدة بيانات على نمط obadx — تدعم الاستئناف (resume)."""
    conn = sqlite3.connect(SEGMENTS_DB)
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS segments (
        segment_index TEXT PRIMARY KEY,
        surah INTEGER,
        seg_idx INTEGER,
        start_time REAL,
        end_time REAL,
        duration_seconds REAL,
        start_aya INTEGER,
        end_aya INTEGER,
        start_word INTEGER,
        end_word INTEGER,
        transcript TEXT,
        matched_text TEXT,
        match_score REAL,
        n_words INTEGER
    );
    CREATE TABLE IF NOT EXISTS word_timings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        segment_index TEXT,
        word_idx INTEGER,
        word TEXT,
        start_abs REAL,
        end_abs REAL,
        FOREIGN KEY (segment_index) REFERENCES segments(segment_index)
    );
    """)
    conn.commit()
    return conn


def save_surah_results(conn, surah_no: int, segments: list[Segment]):
    """حفظ مقاطع سورة في القاعدة."""
    cur = conn.cursor()
    for seg in segments:
        seg_index = f"{surah_no:03d}.{seg.seg_idx:04d}"
        cur.execute("""
            INSERT INTO segments VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            seg_index, surah_no, seg.seg_idx,
            seg.start_time, seg.end_time, seg.end_time - seg.start_time,
            seg.start_aya, seg.end_aya, seg.start_word, seg.end_word,
            seg.transcript, seg.matched_text, seg.match_score,
            len(seg.words),
        ))
        for i, w in enumerate(seg.words):
            cur.execute("""
                INSERT INTO word_timings (segment_index, word_idx, word, start_abs, end_abs)
                VALUES (?, ?, ?, ?, ?)
            """, (seg_index, i, w["word"], w.get("start_abs", 0), w.get("end_abs", 0)))
    conn.commit()


# ───────────────────────────────────────────────────────────────────────────────
# 8️⃣  بناء ملفات الآيات + المخرَجات النهائية
# ───────────────────────────────────────────────────────────────────────────────

def build_verse_files_from_db(quran: dict):
    """بناء ملفات verse-by-verse من قاعدة المقاطع."""
    print(f"\n✂️  قص ملفات الآيات...")
    
    conn = sqlite3.connect(SEGMENTS_DB)
    conn.row_factory = sqlite3.Row
    
    # نجمع كل المقاطع التي تشكّل آية
    rows = conn.execute("""
        SELECT * FROM segments WHERE start_aya > 0 ORDER BY surah, start_aya, seg_idx
    """).fetchall()
    
    # نجمع: (surah, aya) → list of segments
    aya_segments = defaultdict(list)
    for r in rows:
        aya_segments[(r["surah"], r["start_aya"])].append(dict(r))
        if r["end_aya"] != r["start_aya"]:
            aya_segments[(r["surah"], r["end_aya"])].append(dict(r))
    
    pbar = tqdm(total=len(aya_segments))
    for (sura, aya), segs in aya_segments.items():
        segs.sort(key=lambda x: x["start_time"])
        start_t = segs[0]["start_time"]
        end_t = segs[-1]["end_time"]
        duration = end_t - start_t
        if duration <= 0:
            pbar.update(1)
            continue
        
        out_dir = VERSE_DIR / f"{sura:03d}"
        out_dir.mkdir(exist_ok=True)
        out_path = out_dir / f"{sura:03d}_{aya:03d}.mp3"
        
        # -ss قبل -i يجعل ffmpeg يبحث بسرعة لكن قد يُخطئ في keyframe.
        # نضع -ss بعد -i (accurate seek) ثم -c:a libmp3lame لإعادة الترميز
        # للحصول على قص دقيق لا يعتمد على keyframes.
        cmd = [
            "ffmpeg", "-y", "-loglevel", "error",
            "-i", str(SURAH_DIR / f"{sura:03d}.mp3"),
            "-ss", f"{start_t:.3f}",
            "-t",  f"{duration:.3f}",
            "-c:a", "libmp3lame", "-q:a", "2",
            str(out_path),
        ]
        try:
            subprocess.run(cmd, capture_output=True, timeout=60)
        except Exception:
            pass
        pbar.update(1)
    pbar.close()
    
    conn.close()


def export_outputs(quran: dict):
    """تصدير JSON للوقفات + word timings + Hugging Face dataset."""
    print(f"\n📤 تصدير المخرَجات...")
    
    conn = sqlite3.connect(SEGMENTS_DB)
    conn.row_factory = sqlite3.Row
    
    # 1. مواضع الوقف الفعلية للقارئ (من المقاطع)
    waqf_positions = []
    for r in conn.execute("SELECT * FROM segments WHERE end_word IS NOT NULL ORDER BY segment_index"):
        # كل مقطع ينتهي بوقف. الكلمة الأخيرة هي موضع الوقف
        waqf_positions.append({
            "surah": r["surah"],
            "ayah": r["end_aya"],
            "after_word_in_ayah": r["end_word"],
            "time_seconds": r["end_time"],
            "segment_index": r["segment_index"],
        })
    
    # نضيف علامات الوقف من النص المرجعي للمقارنة
    waqf_in_text = []
    for sn, ayas in quran.items():
        for an, atext in ayas.items():
            for w in extract_waqf_in_text(atext):
                w["surah"] = sn
                w["ayah"] = an
                waqf_in_text.append(w)
    
    with open(WAQF_JSON, "w", encoding="utf-8") as f:
        json.dump({
            "waqf_actual_from_audio": waqf_positions,
            "waqf_marks_from_text": waqf_in_text,
            "summary": {
                "total_waqf_in_audio": len(waqf_positions),
                "total_waqf_marks_in_text": len(waqf_in_text),
            }
        }, f, ensure_ascii=False, indent=2)
    
    # 2. Word timings — يشمل التكرارات: كل كلمة من كل مقطع obadx مُحتفظ بها
    all_words = []
    for r in conn.execute("""
        SELECT s.surah, s.start_aya as ayah, s.start_word,
               w.segment_index, w.word, w.start_abs, w.end_abs, w.word_idx
        FROM word_timings w JOIN segments s ON w.segment_index = s.segment_index
        WHERE s.match_score > 0.3 ORDER BY s.surah, s.start_time, w.word_idx
    """):
        all_words.append(dict(r))
    
    with open(WORDS_JSON, "w", encoding="utf-8") as f:
        json.dump(all_words, f, ensure_ascii=False, indent=2)
    
    # 3. Hugging Face Dataset
    from datasets import Dataset, Audio
    
    rows = []
    aya_data = defaultdict(lambda: {"segments": [], "words": []})
    
    for r in conn.execute("SELECT * FROM segments WHERE start_aya > 0"):
        aya_data[(r["surah"], r["start_aya"])]["segments"].append(dict(r))
    
    for r in conn.execute("""
        SELECT s.surah, s.start_aya, w.* FROM word_timings w 
        JOIN segments s ON w.segment_index = s.segment_index
        WHERE s.start_aya > 0
    """):
        aya_data[(r["surah"], r["start_aya"])]["words"].append(dict(r))
    
    for (sura, aya), data in aya_data.items():
        audio_path = VERSE_DIR / f"{sura:03d}" / f"{sura:03d}_{aya:03d}.mp3"
        if not audio_path.exists():
            continue
        
        segs = sorted(data["segments"], key=lambda x: x["start_time"])
        words = sorted(data["words"], key=lambda x: x["start_abs"])
        offset = segs[0]["start_time"]
        
        rows.append({
            "audio": str(audio_path),
            "surah": sura,
            "ayah": aya,
            "uthmani_text": quran.get(sura, {}).get(aya, ""),
            "n_words": len(words),
            "duration": round(segs[-1]["end_time"] - offset, 3),
            # word_timings: يشمل كل كلمة من كل مقطع obadx (التكرارات مُضمَّنة)
            # segment_index يُتيح تمييز التكرار عن التلاوة الأصلية
            "word_timings": json.dumps([{
                "word": w["word"],
                "start": round(w["start_abs"] - offset, 3),
                "end": round(w["end_abs"] - offset, 3),
                "segment": w["segment_index"],
            } for w in words], ensure_ascii=False),
            "n_segments_for_ayah": len(segs),
            "reciter": RECITER_NAME_EN,
        })
    
    if not rows:
        print("   ⚠️ لا توجد آيات — تحقق من نتائج المطابقة أعلاه")
        conn.close()
        return

    ds = Dataset.from_list(rows)
    ds = ds.cast_column("audio", Audio(sampling_rate=SAMPLE_RATE))
    ds.save_to_disk(str(HF_DIR))
    
    conn.close()
    
    print(f"\n📊 الإحصاءات النهائية:")
    print(f"   ✅ مواضع وقف من الصوت:  {len(waqf_positions):,}")
    print(f"   ✅ مواضع وقف من النص:   {len(waqf_in_text):,}")
    print(f"   ✅ كلمات بتوقيتات:      {len(all_words):,}")
    print(f"   ✅ آيات في HF Dataset:  {len(rows):,}")


# ───────────────────────────────────────────────────────────────────────────────
# 9️⃣  التشغيل
# ───────────────────────────────────────────────────────────────────────────────

def main():
    print("═" * 70)
    print(f"🎙️  معالجة: {RECITER_NAME_EN}")
    print("═" * 70)

    # 0. تحميل السور من Islamway
    download_surahs()

    # 1. النص المرجعي
    download_quran_text()
    quran = load_quran()
    
    # 2. obadx على كل السور (يعطي توقيتات مطلقة)
    intervals_per_surah = run_obadx_on_all_surahs()
    if not intervals_per_surah:
        return
    
    # 3. تشغيل Whisper-Tarteel + wav2vec2
    proc = HybridProcessor()
    
    # 4. قاعدة البيانات (تدعم الاستئناف)
    CHECKPOINTS_DIR.mkdir(parents=True, exist_ok=True)
    conn = init_db()

    # 5. معالجة كل سورة
    print(f"\n🔤 معالجة المقاطع (نسخ + مطابقة + محاذاة كلمية)...")
    surahs_to_process = sorted(intervals_per_surah.keys())

    for sn in tqdm(surahs_to_process, desc="السور"):
        done_flag = CHECKPOINTS_DIR / f"{sn:03d}.done"
        if done_flag.exists():
            print(f"   ⏭️  سورة {sn}: مكتملة مسبقاً")
            continue
        try:
            segs = process_surah(sn, intervals_per_surah[sn], quran, proc)
            save_surah_results(conn, sn, segs)
            done_flag.touch()   # ✅ علّم على السورة لتجنب إعادة المعالجة
        except Exception as e:
            print(f"   ⚠️ سورة {sn}: {e}")

    conn.close()
    
    # 6. قص الآيات
    build_verse_files_from_db(quran)

    # 7. التصدير
    export_outputs(quran)
    
    print(f"\n✅ اكتمل!")
    print(f"   📁 verses:       {VERSE_DIR}")
    print(f"   🗄️  segments DB:  {SEGMENTS_DB}")
    print(f"   📄 waqf:         {WAQF_JSON}")
    print(f"   📄 words:        {WORDS_JSON}")
    print(f"   🤗 dataset:      {HF_DIR}")


if __name__ == "__main__":
    main()


# ════════════════════════════════════════════════════════════════════════════
# 📋 مخطط البيانات النهائية
# ════════════════════════════════════════════════════════════════════════════
"""
1) قاعدة segments.db (مثل obadx بالضبط):
   - segment_index: 002.0001
   - start_time, end_time: توقيتات مطلقة في ملف السورة
   - start_aya, end_aya, start_word, end_word: الموضع في النص
   - transcript: نسخ Whisper
   - matched_text: النص العثماني المطابق
   - match_score: ثقة المطابقة (0-1)

2) word_timings table:
   - لكل كلمة: word, start_abs, end_abs (في ملف السورة)

3) waqf_positions.json:
   - waqf_actual_from_audio: أين وقف القارئ فعلاً (من obadx)
   - waqf_marks_from_text: أين توجد علامات وقف (من Tanzil)
   → بمقارنتهما تكتشف اختيارات وقف القارئ

4) HF Dataset جاهز للنشر/التدريب:
   - audio (16kHz)، النص، توقيتات الكلمات نسبية للآية
"""