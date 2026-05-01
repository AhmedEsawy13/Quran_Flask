"""
============================================================================
🎙️  مصحف الشيخ أحمد محمد عامر — Verse-by-verse + Word-level timestamps
    
    النهج الصحيح:
    ✅ القص من ملف السورة الكامل (الحفاظ على التلاوة الطبيعية)
    ✅ استخدام نطاق زمني (start_time أول مقطع → end_time آخر مقطع للآية)
    ✅ المحاذاة الكلمية بنموذج Tarteel-Whisper + wav2vec2
    ✅ التحقق المتبادل بين النموذجين

تطبيق على Kaggle (T4 GPU 16GB)
============================================================================
"""

# ────────────────────────────────────────────────────────────────────────────
# التثبيتات (أضفها كأول خلية في الـ Notebook)
# ────────────────────────────────────────────────────────────────────────────
"""
!pip install -q transformers torchaudio pydub tqdm requests soundfile librosa
!pip install -q stable-ts whisper-timestamped
!apt-get -qq install -y ffmpeg
"""

import io
import os
import re
import json
import sqlite3
import requests
from pathlib import Path
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from typing import Optional

import pandas as pd
import torch
import torchaudio
import numpy as np
from tqdm.auto import tqdm
from pydub import AudioSegment

# ────────────────────────────────────────────────────────────────────────────
# 📌 الإعدادات
# ────────────────────────────────────────────────────────────────────────────

DB_PATH = "/kaggle/working/ahmed_mohamed_amer_5_0_positions.db"
WORK_DIR = Path("/kaggle/working")
HF_TOKEN = None     # ضع token هنا إذا كان الـ dataset خاصاً

SURAH_DIR = WORK_DIR / "01_surahs_full"      # السور الكاملة من Islamway
VERSE_DIR = WORK_DIR / "02_verses"            # 6236 ملف آية (مقصوصة من السور)
JSON_OUT = WORK_DIR / "03_word_alignments.json"
HF_DIR = WORK_DIR / "04_hf_dataset"

for d in [SURAH_DIR, VERSE_DIR, HF_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# نموذجان متكاملان:
WHISPER_MODEL = "tarteel-ai/whisper-base-ar-quran"  # للنسخ والتحقق (WER 5.75%)
WAV2VEC_MODEL = "jonatasgrosman/wav2vec2-large-xlsr-53-arabic"  # للمحاذاة

# ✅ مصدر الصوت: Islamway (مطابق لقاعدة obadx — تطابق المدد مؤكد)
# نمط الرابط: https://quran.islamway.net/quran3/576/SSS.mp3
# 576 = معرّف مجموعة "المصحف المرتل - أحمد محمد عامر" على Islamway
ISLAMWAY_BASE = "https://quran.islamway.net/quran3/576/"

# مصادر بديلة كـ fallback لو فشل التحميل من Islamway
FALLBACK_URLS = [
    "https://server10.mp3quran.net/Aamer/",  # MP3Quran - الخادم الصحيح
    "https://server8.mp3quran.net/Aamer/",
]

SAMPLE_RATE = 16000
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"

# هامش زمني (padding) قبل وبعد كل آية لاتقاط التنفس (بالثواني)
LEFT_PAD = 0.0     # عادة لا نحتاج لأن obadx ضبط البدايات بدقة
RIGHT_PAD = 0.0    # نحافظ على القرار الأصلي للنموذج


# ────────────────────────────────────────────────────────────────────────────
# 1️⃣ تحميل السور الكاملة (مرة واحدة فقط)
# ────────────────────────────────────────────────────────────────────────────

def download_full_surahs():
    """
    تحميل ١١٤ سورة كاملة من Islamway (المصدر المطابق لقاعدة obadx).
    
    المصدر الأساسي: https://quran.islamway.net/quran3/576/SSS.mp3
    عند الفشل: نجرّب fallback URLs من MP3Quran
    
    لماذا Islamway؟
      - مدد ملفاته تطابق التوقيتات في قاعدة obadx بدقة (تأكدنا تجريبياً)
      - يبدو أنه المصدر الأصلي الذي بنى عليه obadx قاعدته
      - استخدام أي مصدر آخر قد يسبب انزياحاً زمنياً يفسد المحاذاة
    """
    print("📥 تحميل السور الكاملة من Islamway...")
    missing = [s for s in range(1, 115) if not (SURAH_DIR / f"{s:03d}.mp3").exists()]
    if not missing:
        print("   ✓ كل السور موجودة")
        return
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://ar.islamway.net/",
    }
    
    failed = []
    for s in tqdm(missing, desc="تنزيل"):
        fpath = SURAH_DIR / f"{s:03d}.mp3"
        urls_to_try = [f"{ISLAMWAY_BASE}{s:03d}.mp3"] + \
                      [f"{base}{s:03d}.mp3" for base in FALLBACK_URLS]
        
        success = False
        last_err = None
        for url in urls_to_try:
            try:
                r = requests.get(url, stream=True, timeout=120, headers=headers)
                if r.status_code == 200:
                    with open(fpath, "wb") as f:
                        for chunk in r.iter_content(8192):
                            f.write(chunk)
                    # تحقق من حجم الملف (ليس صفحة خطأ)
                    if fpath.stat().st_size > 50_000:  # > 50KB
                        success = True
                        break
                    else:
                        fpath.unlink()
                        last_err = f"ملف صغير جداً ({fpath.stat().st_size} bytes)"
                else:
                    last_err = f"HTTP {r.status_code}"
            except Exception as e:
                last_err = str(e)
        
        if not success:
            failed.append((s, last_err))
            print(f"   ❌ سورة {s}: {last_err}")
    
    if failed:
        print(f"\n⚠️  فشل تحميل {len(failed)} سورة. حاول لاحقاً أو نزّلها يدوياً.")
        return False
    
    print(f"   ✓ تم تحميل {len(missing)} سورة بنجاح")
    return True


def _validate_db():
    """
    التحقق من أن قاعدة البيانات موجودة وتحتوي على جدول positions.
    ترفع RuntimeError برسالة واضحة إذا لم تكن القاعدة جاهزة.
    """
    db = Path(DB_PATH)
    if not db.exists() or db.stat().st_size == 0:
        raise RuntimeError(
            f"❌ قاعدة البيانات غير موجودة أو فارغة: {DB_PATH}\n"
            "   شغّل أولاً: fetch_waqf_positions.py --moshaf 5.0\n"
            "   ثم انسخ الملف الناتج إلى /kaggle/working/"
        )
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='positions'")
    if not cur.fetchone():
        conn.close()
        raise RuntimeError(
            f"❌ جدول 'positions' غير موجود في: {DB_PATH}\n"
            "   القاعدة موجودة لكنها فارغة أو من مصدر مختلف.\n"
            "   شغّل: fetch_waqf_positions.py --moshaf 5.0 لتوليدها من جديد."
        )
    conn.close()


def verify_audio_durations():
    """
    التحقق من تطابق مدد ملفات الصوت مع المتوقع من قاعدة obadx.

    المقارنة الصحيحة: timestamp_end لآخر مقطع في السورة (= نهاية التلاوة الفعلية)
    مقابل طول ملف الصوت الكامل.
    الفرق المسموح به >=2 ث (يغطي الصمت في نهاية الملف بعد آخر آية).

    ملاحظة: SUM(duration_seconds) != طول السورة لأن مدد المقاطع لا تشمل
    فترات التنفس بين الوقفات — لذا كان الفحص السابق يُظهر "mismatches" وهمية.
    """
    print("\n🔍 التحقق من تطابق المدد بين الملفات الصوتية وقاعدة obadx...")

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # هل توجد أعمدة timestamp_start/timestamp_end في القاعدة؟
    cols = {row[1] for row in cur.execute("PRAGMA table_info(positions)").fetchall()}
    has_ts = "timestamp_start" in cols and "timestamp_end" in cols

    if has_ts:
        # نأخذ آخر قيمة timestamp_end لكل سورة (= نهاية التلاوة الحقيقية)
        cur.execute("""
            SELECT CAST(substr(segment_index, 1, 3) AS INTEGER) as sura,
                   MAX(timestamp_end) as last_end
            FROM positions
            WHERE timestamp_end IS NOT NULL
            GROUP BY sura
        """)
        expected = {row[0]: row[1] for row in cur.fetchall()}
    else:
        # fallback: حساب تراكمي — أقل دقة لأنه يستثني فترات التنفس
        print("   ℹ️  عمود timestamp_end غير موجود — أعد توليد القاعدة بـ fetch_waqf_positions.py")
        print("   ℹ️  سيُستخدم SUM(duration_seconds) كـ fallback (يُظهر فروقاً وهمية بسبب فترات التنفس)")
        cur.execute("""
            SELECT CAST(substr(segment_index, 1, 3) AS INTEGER) as sura,
                   SUM(duration_seconds) as total
            FROM positions GROUP BY sura
        """)
        expected = {row[0]: row[1] for row in cur.fetchall()}

    conn.close()
    
    # نفصل بين نوعين:
    #   too_short: الملف أقصر من آخر timestamp → قد يُقطع ذيل آخر آية
    #   too_long:  الملف أطول → صمت بعد نهاية التلاوة، لا أثر على القص
    too_short = []
    too_long_info = []
    TOLERANCE = 3.0   # ثوانٍ — يغطي صمت النهاية ودقة التشفير

    for sura in sorted(expected.keys()):
        fpath = SURAH_DIR / f"{sura:03d}.mp3"
        if not fpath.exists():
            continue
        try:
            audio = AudioSegment.from_mp3(str(fpath))
            actual_dur = len(audio) / 1000.0
            exp_dur = expected[sura]
            diff = actual_dur - exp_dur   # موجب = ملف أطول، سالب = ملف أقصر

            if diff < -TOLERANCE:
                # الملف أقصر من آخر timestamp — خطر حقيقي
                too_short.append((sura, exp_dur, actual_dur, -diff))
            elif diff > TOLERANCE:
                # الملف أطول — صمت زائد، لا خطر
                too_long_info.append((sura, exp_dur, actual_dur, diff))
        except Exception as e:
            print(f"   ⚠️ سورة {sura}: تعذر قراءة الملف ({e})")

    if too_long_info:
        print(f"   ℹ️  {len(too_long_info)} سورة أطول من آخر timestamp (صمت زائد في النهاية — لا أثر على القص)")

    if too_short:
        print(f"\n⚠️  {len(too_short)} سورة أقصر من آخر timestamp (ذيل آخر آية قد يُقطع):")
        for sura, exp, act, diff in too_short[:10]:
            print(f"      سورة {sura}: آخر timestamp {exp:.1f}ث، طول الملف {act:.1f}ث (نقص {diff:.1f}ث)")
        if len(too_short) > 10:
            print(f"      ... و {len(too_short)-10} أخرى")
        print("   💡 القص مقيّد بـ min(sura_total_ms) — الآيات الأخيرة قد تُقص بشكل طفيف")
    else:
        n = len(expected) - len([s for s in expected if not (SURAH_DIR / f"{s:03d}.mp3").exists()])
        print(f"   ✅ كل {n} سورة موجودة بطول كافٍ (لا مشكلة في القص)")

    return too_short


# ────────────────────────────────────────────────────────────────────────────
# 2️⃣ قراءة قاعدة obadx — نأخذ النطاقات الزمنية فقط
# ────────────────────────────────────────────────────────────────────────────

@dataclass
class VerseSpan:
    """نطاق زمني لآية كاملة في ملف السورة الأصلي."""
    surah: int
    aya: int
    start_time: float          # بداية أول مقطع لهذه الآية في ملف السورة
    end_time: float            # نهاية آخر مقطع لهذه الآية في ملف السورة
    uthmani_text: str
    imlaey_text: str
    n_segments: int            # كم مقطع شكّل هذه الآية (للإحصاء فقط)
    avg_match_ratio: float     # متوسط دقة المطابقة في القاعدة
    
    @property
    def duration(self) -> float:
        return self.end_time - self.start_time


def build_verse_spans() -> list[VerseSpan]:
    """
    قراءة القاعدة وحساب نطاق زمني واحد لكل آية.

    الأولوية: استخدام timestamp_start / timestamp_end الحقيقيين من قاعدة obadx
    (الوقت المطلق للمقطع داخل ملف السورة الكامل).
    fallback: حساب تراكمي من duration_seconds فقط إذا لم تتوفر الأعمدة
    (يُفقد فترات التنفس بين الوقفات).
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    # اكتشف ما إذا كانت أعمدة الـ timestamps موجودة
    cols = {row[1] for row in conn.execute("PRAGMA table_info(positions)").fetchall()}
    has_ts = "timestamp_start" in cols and "timestamp_end" in cols

    if has_ts:
        rows = conn.execute("""
            SELECT segment_index, start_sura, start_aya, end_sura, end_aya,
                   uthmani_text, imlaey_text, duration_seconds, match_ratio,
                   has_quran, has_bismillah,
                   timestamp_start, timestamp_end
            FROM positions ORDER BY segment_index
        """).fetchall()
    else:
        rows = conn.execute("""
            SELECT segment_index, start_sura, start_aya, end_sura, end_aya,
                   uthmani_text, imlaey_text, duration_seconds, match_ratio,
                   has_quran, has_bismillah
            FROM positions ORDER BY segment_index
        """).fetchall()
    conn.close()

    # بناء dict المقاطع لكل سورة
    by_surah_segs = defaultdict(list)
    for r in rows:
        sura = int(r["segment_index"].split(".")[0])
        by_surah_segs[sura].append(dict(r))

    for sura in by_surah_segs:
        by_surah_segs[sura].sort(key=lambda x: x["segment_index"])
        if has_ts:
            # استخدام التوقيتات الحقيقية — تحتوي على فترات التنفس
            for seg in by_surah_segs[sura]:
                seg["abs_start"] = seg["timestamp_start"] or 0.0
                seg["abs_end"]   = seg["timestamp_end"]   or (seg["abs_start"] + seg["duration_seconds"])
        else:
            # fallback تراكمي (يفقد فترات التنفس)
            t = 0.0
            for seg in by_surah_segs[sura]:
                seg["abs_start"] = t
                seg["abs_end"] = t + seg["duration_seconds"]
                t = seg["abs_end"]
    
    # تجميع لآيات
    verse_buckets = defaultdict(list)  # (surah, aya) -> [segments]
    
    for sura, segs in by_surah_segs.items():
        for seg in segs:
            # البسملة كـ "آية 0" خاصة لنحفظها منفصلة
            if seg["has_bismillah"]:
                verse_buckets[(sura, 0)].append(seg)
                continue
            
            # تجاهل غير القرآني
            if not seg["has_quran"]:
                continue
            
            # السورة الفاتحة - الاستعاذة (segment_index 001.0000) لها has_quran=0
            # ولا تدخل هنا
            
            sa = seg["start_aya"]
            if sa is None:
                continue
            
            # مقطع يعبر عدة آيات (نادر: مقطع واحد فقط)
            ea = seg["end_aya"] if seg["end_aya"] else sa
            if int(sa) != int(ea):
                # نوزّعه: نضعه على آية البداية
                # في الحالة الواقعية: مقطع 037.0166 يعبر آيتين 151-152
                # القرار الأنسب: نضعه مع آية البداية ونلاحظ ذلك
                verse_buckets[(sura, int(sa))].append(seg)
            else:
                verse_buckets[(sura, int(sa))].append(seg)
    
    # بناء VerseSpan لكل آية
    verses = []
    for (sura, aya), segs in verse_buckets.items():
        segs.sort(key=lambda x: x["abs_start"])
        
        # استخراج النص (نأخذ من أول مقطع غير فارغ، أو ندمج لو لزم)
        uth_texts = [s["uthmani_text"] for s in segs if s["uthmani_text"]]
        iml_texts = [s["imlaey_text"] for s in segs if s["imlaey_text"]]
        
        # في حالة عدة مقاطع لنفس الآية، النصوص قد تتكرر أو تكمل بعضها
        # للسلامة: نأخذ الأطول (يحوي عادة الآية كاملة)
        uthmani = max(uth_texts, key=len) if uth_texts else ""
        imlaey = max(iml_texts, key=len) if iml_texts else ""
        
        match_ratios = [s["match_ratio"] for s in segs if s["match_ratio"] is not None]
        avg_match = sum(match_ratios) / len(match_ratios) if match_ratios else 0.0
        
        verses.append(VerseSpan(
            surah=sura,
            aya=aya,
            start_time=segs[0]["abs_start"],
            end_time=segs[-1]["abs_end"],
            uthmani_text=uthmani,
            imlaey_text=imlaey,
            n_segments=len(segs),
            avg_match_ratio=avg_match,
        ))
    
    verses.sort(key=lambda v: (v.surah, v.aya))
    return verses


# ────────────────────────────────────────────────────────────────────────────
# 3️⃣ القص من ملف السورة الأصلي (✅ تلاوة طبيعية)
# ────────────────────────────────────────────────────────────────────────────

def cut_verses_from_surahs(verses: list[VerseSpan], fmt="mp3", bitrate="128k"):
    """
    قص ملفات الآيات من ملف السورة الكامل.
    
    المهم: نقص نطاقاً زمنياً واحداً [start_time, end_time] من السورة،
    وليس تجميع المقاطع المنفصلة. هذا يحفظ:
      - التنفس الطبيعي للقارئ
      - الصمت الفني بين الكلمات
      - الإيقاع الطبيعي للترتيل
    """
    print(f"\n✂️  قص {len(verses):,} آية من السور الكاملة...")
    
    # نجمع الآيات بالسورة لتحميل كل سورة مرة واحدة
    by_surah = defaultdict(list)
    for v in verses:
        by_surah[v.surah].append(v)
    
    skipped = 0
    for sura in tqdm(sorted(by_surah.keys()), desc="السور"):
        surah_audio_path = SURAH_DIR / f"{sura:03d}.mp3"
        if not surah_audio_path.exists():
            print(f"   ⚠️ ملف السورة {sura} غير موجود")
            skipped += len(by_surah[sura])
            continue
        
        # تحميل السورة الكاملة في الذاكرة (مرة واحدة فقط)
        audio = AudioSegment.from_mp3(str(surah_audio_path))
        sura_total_ms = len(audio)
        
        out_dir = VERSE_DIR / f"{sura:03d}"
        out_dir.mkdir(exist_ok=True)
        
        for v in by_surah[sura]:
            # القص الزمني المباشر من الملف الكامل
            start_ms = max(0, int((v.start_time - LEFT_PAD) * 1000))
            end_ms = min(sura_total_ms, int((v.end_time + RIGHT_PAD) * 1000))
            
            chunk = audio[start_ms:end_ms]
            
            # تسمية واضحة: SSS_AAA.mp3 (آية ٠٠٠ = البسملة)
            out_path = out_dir / f"{sura:03d}_{v.aya:03d}.{fmt}"
            chunk.export(str(out_path), format=fmt, bitrate=bitrate)
    
    if skipped:
        print(f"   ⚠️ تم تخطي {skipped} آية بسبب ملفات سور مفقودة")
    
    print(f"   ✓ المخرجات: {VERSE_DIR}")


# ────────────────────────────────────────────────────────────────────────────
# 4️⃣ نظام المحاذاة الكلمية (Tarteel-Whisper + wav2vec2)
# ────────────────────────────────────────────────────────────────────────────

class HybridAligner:
    """
    محاذاة كلمية هجينة:
      - wav2vec2 العربي → forced alignment على مستوى الحرف ثم تجميع للكلمات
      - Tarteel-Whisper → التحقق من النص (verification check)
    
    لماذا الهجين؟
      - wav2vec2 + CTC أفضل في المحاذاة الزمنية الدقيقة
      - Whisper-Tarteel ممتاز في النسخ النصي (للتحقق فقط)
      - النص نفسه نحن نعرفه مسبقاً من قاعدة obadx، فلا نحتاج Whisper للنسخ
    """
    
    def __init__(self):
        from transformers import (
            Wav2Vec2ForCTC, Wav2Vec2Processor,
            WhisperForConditionalGeneration, WhisperProcessor,
        )
        
        print(f"📦 تحميل wav2vec2 (للمحاذاة): {WAV2VEC_MODEL}")
        self.w2v_proc = Wav2Vec2Processor.from_pretrained(WAV2VEC_MODEL)
        self.w2v_model = Wav2Vec2ForCTC.from_pretrained(WAV2VEC_MODEL).to(DEVICE).eval()
        self.vocab = self.w2v_proc.tokenizer.get_vocab()
        self.blank_id = self.vocab.get("<pad>", 0)
        self.word_sep = self.vocab.get("|", None)
        
        print(f"📦 تحميل Tarteel-Whisper (للتحقق): {WHISPER_MODEL}")
        self.whisper_proc = WhisperProcessor.from_pretrained(WHISPER_MODEL)
        self.whisper_model = WhisperForConditionalGeneration.from_pretrained(
            WHISPER_MODEL).to(DEVICE).eval()
        self.whisper_model.config.forced_decoder_ids = None
    
    @staticmethod
    def normalize_for_w2v(text: str) -> str:
        """تطبيع النص ليتطابق مع vocab الخاص بـ wav2vec2 العربي."""
        text = re.sub(r'[\u064B-\u0652\u0670\u06D6-\u06ED]', '', text)  # تشكيل
        text = re.sub(r'[إأآٱ]', 'ا', text)
        text = re.sub(r'ى', 'ي', text)
        text = re.sub(r'ة', 'ه', text)
        text = re.sub(r'[^\u0621-\u063A\u0641-\u064A\s]', ' ', text)
        return re.sub(r'\s+', ' ', text).strip()
    
    @staticmethod
    def normalize_for_compare(text: str) -> str:
        """تطبيع للمقارنة بين النصوص (Whisper output vs reference)."""
        text = re.sub(r'[\u064B-\u0652\u0670\u06D6-\u06ED]', '', text)
        text = re.sub(r'[إأآٱ]', 'ا', text)
        text = re.sub(r'ى', 'ي', text)
        text = re.sub(r'ة', 'ه', text)
        text = re.sub(r'[^\u0621-\u063A\u0641-\u064A\s]', '', text)
        return re.sub(r'\s+', ' ', text).strip()
    
    @torch.no_grad()
    def transcribe_with_whisper(self, audio: np.ndarray) -> str:
        """نسخ بـ Tarteel-Whisper (للتحقق فقط)."""
        feats = self.whisper_proc.feature_extractor(
            audio, sampling_rate=SAMPLE_RATE, return_tensors="pt"
        ).input_features.to(DEVICE)
        
        ids = self.whisper_model.generate(feats, max_length=448)
        text = self.whisper_proc.tokenizer.batch_decode(
            ids, skip_special_tokens=True)[0]
        return text.strip()
    
    @torch.no_grad()
    def align_words(self, audio: np.ndarray, text: str) -> list[dict]:
        """
        محاذاة الكلمات بـ wav2vec2 + CTC forced alignment.
        النص معروف، لذا نستخدم CTC لمحاذاته بدقة.
        """
        if len(audio) < SAMPLE_RATE * 0.1:
            return []
        
        words_orig = text.split()
        text_norm = self.normalize_for_w2v(text)
        words_norm = text_norm.split()
        
        if not words_norm:
            return []
        
        # CTC inference
        inputs = self.w2v_proc(audio, sampling_rate=SAMPLE_RATE,
                                return_tensors="pt").to(DEVICE)
        logits = self.w2v_model(inputs.input_values).logits
        log_probs = torch.log_softmax(logits, dim=-1)[0].cpu().numpy()
        T = log_probs.shape[0]
        
        # تحويل النص إلى ids (مع | بين الكلمات)
        token_ids = []
        for i, w in enumerate(words_norm):
            if i > 0 and self.word_sep is not None:
                token_ids.append(self.word_sep)
            for ch in w:
                if ch in self.vocab:
                    token_ids.append(self.vocab[ch])
        
        if not token_ids or T < len(token_ids):
            return []
        
        # CTC Forced Alignment
        try:
            spans = self._ctc_force_align(log_probs, token_ids)
        except Exception:
            return []
        
        if not spans:
            return []
        
        # تجميع الـ spans حسب الكلمات
        ratio = len(audio) / T / SAMPLE_RATE
        
        result = []
        word_idx = 0
        cur_word_spans = []
        
        for tid, start_f, end_f in spans:
            if tid == self.word_sep:
                if cur_word_spans and word_idx < len(words_orig):
                    result.append({
                        "word": words_orig[word_idx],
                        "start": round(cur_word_spans[0][0] * ratio, 3),
                        "end": round(cur_word_spans[-1][1] * ratio, 3),
                    })
                    word_idx += 1
                cur_word_spans = []
            else:
                cur_word_spans.append((start_f, end_f))
        
        # آخر كلمة
        if cur_word_spans and word_idx < len(words_orig):
            result.append({
                "word": words_orig[word_idx],
                "start": round(cur_word_spans[0][0] * ratio, 3),
                "end": round(cur_word_spans[-1][1] * ratio, 3),
            })
        
        return result
    
    def _ctc_force_align(self, log_probs: np.ndarray, 
                         token_ids: list[int]) -> list[tuple]:
        """
        Viterbi CTC forced alignment.
        Returns: [(token_id, start_frame, end_frame), ...]
        """
        T, V = log_probs.shape
        N = len(token_ids)
        
        # توسيع التوكنز بـ blank بينها
        ext = [self.blank_id]
        for tid in token_ids:
            ext.append(tid)
            ext.append(self.blank_id)
        L = len(ext)
        
        if T < L // 2 + 1:
            return []
        
        NEG = -1e10
        dp = np.full((T, L), NEG, dtype=np.float32)
        bp = np.zeros((T, L), dtype=np.int8)  # 0=stay, 1=move 1, 2=skip 1
        
        dp[0, 0] = log_probs[0, ext[0]]
        if L > 1:
            dp[0, 1] = log_probs[0, ext[1]]
        
        for t in range(1, T):
            # النسخة المتجهة
            stay = dp[t-1, :].copy()
            move1 = np.concatenate(([NEG], dp[t-1, :-1]))
            
            # skip 2 (لتخطي blank بين توكنين مختلفين)
            skip2 = np.full(L, NEG, dtype=np.float32)
            for s in range(2, L):
                if (ext[s] != self.blank_id 
                    and ext[s] != ext[s-2]):
                    skip2[s] = dp[t-1, s-2]
            
            choices = np.stack([stay, move1, skip2])
            best_choice = np.argmax(choices, axis=0)
            best_val = np.max(choices, axis=0)
            
            for s in range(L):
                dp[t, s] = best_val[s] + log_probs[t, ext[s]]
                bp[t, s] = best_choice[s]
        
        # backtrack
        if L >= 2 and dp[T-1, L-1] > dp[T-1, L-2]:
            s = L - 1
        else:
            s = L - 2 if L >= 2 else 0
        
        path = [(t, s) for t in [T-1]]
        for t in range(T-1, 0, -1):
            choice = bp[t, s]
            if choice == 1:
                s -= 1
            elif choice == 2:
                s -= 2
            path.append((t-1, s))
        path.reverse()
        
        # استخراج spans لكل توكن غير-blank
        result = []
        cur_pos = -1
        cur_start = 0
        for t, s in path:
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


# ────────────────────────────────────────────────────────────────────────────
# 5️⃣ المحاذاة لكل آية + التحقق المتبادل
# ────────────────────────────────────────────────────────────────────────────

def align_all_verses(verses: list[VerseSpan]) -> list[dict]:
    """محاذاة كل آية مع التحقق بـ Tarteel-Whisper."""
    print(f"\n🔤 محاذاة {len(verses):,} آية...")
    aligner = HybridAligner()
    results = []
    
    for v in tqdm(verses, desc="المحاذاة"):
        audio_path = VERSE_DIR / f"{v.surah:03d}" / f"{v.surah:03d}_{v.aya:03d}.mp3"
        if not audio_path.exists():
            continue
        
        # تحميل المقطع بـ 16kHz mono
        wav, sr = torchaudio.load(str(audio_path))
        if sr != SAMPLE_RATE:
            wav = torchaudio.functional.resample(wav, sr, SAMPLE_RATE)
        if wav.shape[0] > 1:
            wav = wav.mean(dim=0, keepdim=True)
        audio_np = wav.squeeze().numpy()
        
        # 1) المحاذاة الكلمية (تستخدم النص العثماني المعروف)
        # نستخدم imlaey لأنه أقرب للنطق الفعلي
        words = aligner.align_words(audio_np, v.imlaey_text)
        
        # 2) التحقق بـ Tarteel-Whisper (لاكتشاف الآيات المشكوك فيها)
        whisper_text = ""
        match_score = 0.0
        try:
            whisper_text = aligner.transcribe_with_whisper(audio_np)
            ref_norm = aligner.normalize_for_compare(v.imlaey_text)
            hyp_norm = aligner.normalize_for_compare(whisper_text)
            # نسبة تطابق بسيطة: نسبة الكلمات المشتركة
            ref_words = set(ref_norm.split())
            hyp_words = set(hyp_norm.split())
            if ref_words:
                match_score = len(ref_words & hyp_words) / len(ref_words)
        except Exception:
            pass
        
        # علامات جودة
        n_expected = len(v.imlaey_text.split())
        n_aligned = len(words)
        alignment_ratio = n_aligned / n_expected if n_expected else 0
        
        # تحديد الجودة
        quality = "high"
        if alignment_ratio < 0.85 or match_score < 0.80:
            quality = "needs_review"
        if alignment_ratio < 0.5 or match_score < 0.5:
            quality = "low"
        
        results.append({
            "surah": v.surah,
            "aya": v.aya,
            "audio_file": f"02_verses/{v.surah:03d}/{v.surah:03d}_{v.aya:03d}.mp3",
            "duration": round(v.duration, 3),
            "uthmani_text": v.uthmani_text,
            "imlaey_text": v.imlaey_text,
            "words": words,
            
            # حقول التحقق والجودة
            "n_words_expected": n_expected,
            "n_words_aligned": n_aligned,
            "alignment_ratio": round(alignment_ratio, 3),
            "whisper_transcript": whisper_text,
            "whisper_match_score": round(match_score, 3),
            "quality": quality,
            
            # من قاعدة obadx
            "obadx_avg_match_ratio": round(v.avg_match_ratio, 3),
            "obadx_n_segments": v.n_segments,
        })
    
    # حفظ JSON
    with open(JSON_OUT, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    
    # تقرير الجودة
    high = sum(1 for r in results if r["quality"] == "high")
    review = sum(1 for r in results if r["quality"] == "needs_review")
    low = sum(1 for r in results if r["quality"] == "low")
    print(f"\n📊 تقرير الجودة:")
    print(f"   ✅ آيات بجودة عالية:        {high:,} ({high/len(results)*100:.1f}%)")
    print(f"   ⚠️  آيات تحتاج مراجعة:      {review:,} ({review/len(results)*100:.1f}%)")
    print(f"   ❌ آيات بجودة منخفضة:       {low:,} ({low/len(results)*100:.1f}%)")
    
    return results


# ────────────────────────────────────────────────────────────────────────────
# 6️⃣ بناء Hugging Face Dataset
# ────────────────────────────────────────────────────────────────────────────

def build_hf_dataset(results: list[dict]):
    """تحويل النتائج لـ HF Dataset (جاهز للنشر أو التدريب)."""
    from datasets import Dataset, Audio
    
    print("\n🤗 بناء Hugging Face Dataset...")
    rows = []
    for r in results:
        audio_full = WORK_DIR / r["audio_file"]
        if not audio_full.exists():
            continue
        rows.append({
            "audio": str(audio_full),
            "surah": r["surah"],
            "aya": r["aya"],
            "uthmani_text": r["uthmani_text"],
            "imlaey_text": r["imlaey_text"],
            "duration": r["duration"],
            "word_timings": json.dumps(r["words"], ensure_ascii=False),
            "n_words": r["n_words_expected"],
            "quality": r["quality"],
            "alignment_ratio": r["alignment_ratio"],
            "whisper_match_score": r["whisper_match_score"],
            "reciter_ar": "أحمد محمد عامر",
            "reciter_en": "Ahmed Mohamed Amer",
            "narration": "حفص عن عاصم",
        })
    
    ds = Dataset.from_list(rows)
    ds = ds.cast_column("audio", Audio(sampling_rate=SAMPLE_RATE))
    ds.save_to_disk(str(HF_DIR))
    print(f"   ✓ HF Dataset: {HF_DIR} ({len(ds):,} صف)")
    
    # للنشر:
    # from huggingface_hub import login
    # login(token="hf_...")
    # ds.push_to_hub("YOUR_USERNAME/ahmed-amer-quran-aligned")
    
    return ds


# ────────────────────────────────────────────────────────────────────────────
# 7️⃣ التشغيل
# ────────────────────────────────────────────────────────────────────────────

def main():
    print("═" * 70)
    print("🎙️  مصحف الشيخ أحمد محمد عامر — verse-by-verse + word timestamps")
    print("═" * 70)

    # 0. التحقق من وجود قاعدة البيانات قبل أي خطوة أخرى
    _validate_db()

    # 1. تحميل السور (~600MB) من Islamway
    download_full_surahs()
    
    # 1.5. التحقق من تطابق مدد الملفات مع قاعدة obadx
    # الآن يستخدم timestamp_end الحقيقي (يشمل فترات التنفس) — لا mismatches وهمية
    mismatches = verify_audio_durations()
    if mismatches and len(mismatches) > 5:
        print("\n❗ تحذير: عدة سور أقصر من توقيتاتها — القص قد يفقد ذيل آخر آية في تلك السور.")
        print("   التنفيذ متابع — القص مقيّد بطول الملف الفعلي (لا كسر).")
    
    # 2. قراءة القاعدة وحساب نطاقات الآيات
    print("\n📚 قراءة قاعدة obadx وبناء نطاقات الآيات...")
    verses = build_verse_spans()
    
    # إحصاءات سريعة
    n_with_bismillah = sum(1 for v in verses if v.aya == 0)
    n_quran = sum(1 for v in verses if v.aya > 0)
    total_dur = sum(v.duration for v in verses) / 3600
    print(f"   الآيات القرآنية:    {n_quran:,}")
    print(f"   البسملات المنفصلة:  {n_with_bismillah}")
    print(f"   إجمالي المدة:        {total_dur:.2f} ساعة")
    
    # 3. القص من ملف السورة الكامل (✅ التلاوة الطبيعية)
    cut_verses_from_surahs(verses)
    
    # 4. المحاذاة الكلمية + التحقق
    results = align_all_verses(verses)
    
    # 5. HF Dataset
    ds = build_hf_dataset(results)
    
    print("\n" + "═" * 70)
    print("🎉 المخرَجات النهائية:")
    print(f"   📁 السور الكاملة:        {SURAH_DIR}")
    print(f"   📁 ملفات الآيات:          {VERSE_DIR}")
    print(f"   📄 توقيتات الكلمات:       {JSON_OUT}")
    print(f"   🤗 HF Dataset:           {HF_DIR}")
    print("═" * 70)


if __name__ == "__main__":
    main()


# ════════════════════════════════════════════════════════════════════════════
# 📋 مثال على المخرَج JSON النهائي
# ════════════════════════════════════════════════════════════════════════════
"""
{
  "surah": 1,
  "aya": 1,
  "audio_file": "02_verses/001/001_001.mp3",
  "duration": 4.380,
  "uthmani_text": "بِسْمِ ٱللَّهِ ٱلرَّحْمَـٰنِ ٱلرَّحِيمِ",
  "imlaey_text": "بِسْمِ اللَّهِ الرَّحْمَٰنِ الرَّحِيمِ",
  "words": [
    {"word": "بِسْمِ",       "start": 0.10, "end": 0.62},
    {"word": "اللَّهِ",      "start": 0.62, "end": 1.18},
    {"word": "الرَّحْمَٰنِ", "start": 1.40, "end": 2.91},
    {"word": "الرَّحِيمِ",   "start": 2.95, "end": 4.32}
  ],
  "n_words_expected": 4,
  "n_words_aligned": 4,
  "alignment_ratio": 1.0,
  "whisper_transcript": "بسم الله الرحمن الرحيم",
  "whisper_match_score": 1.0,
  "quality": "high",
  "obadx_avg_match_ratio": 1.0,
  "obadx_n_segments": 1
}
"""