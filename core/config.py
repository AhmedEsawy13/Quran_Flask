"""Application configuration: database paths, layout constants, and the
character sets / regexes used for waqf extraction and search normalisation.

Pure data only — no Flask app dependency — so every feature blueprint can
import these without pulling in the whole app. Paths are anchored to the
project root (this module lives one level down, in core/).
"""
import os
import re

from core.edition_capabilities import editions_with

# Project root (parent of this core/ package). All data/reciters paths hang
# off this so the constants resolve identically no matter who imports them.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_BASE_DIR = _ROOT  # kept under the original name for callers that reference it

DATABASE = os.path.join(_ROOT, 'data', 'word_name.db')
WAQF_DATABASE = os.path.join(_ROOT, 'data', 'waqf_symbols.db')
MUSHAF_WAQF_DATABASE = os.path.join(_ROOT, 'data', 'mushaf_waqf.db')
# Bahouth-derived verse topics + contiguous context spans for تثبيت.
VERSE_TOPICS_DATABASE = os.path.join(_ROOT, 'data', 'verse_topics.db')
# مصاحف being adjusted via /mushaf-editor.
# قطر: own layout + KATypical. الكويت: Madinah 1405 (qpc_v1) + Al Shamiya.
# البحرين: Layout Studio project (seeded from Madinah 1421) + Digital Khatt.
EDITOR_EDITIONS = editions_with('editor_enabled')
# Editions whose drafts/published marks live in Supabase when configured.
CLOUD_EDITOR_EDITIONS = editions_with('cloud_draft_enabled')
PUBLISHABLE_EDITOR_EDITIONS = editions_with('publish_enabled')
PUBLIC_CLOUD_WAQF_EDITIONS = editions_with('public_read_enabled')
# Madinah 1441 uses the QPC v4 (tajweed) 15-line layout. Madinah 1421 uses the
# original Digital Khatt / QPC v2 layout supplied by the project. Both share
# the same 1..83668 word numbering and Digital Khatt webfont; only their line
# breaks differ. (Neither schema has total_advance/x_offset columns.)
DIGITAL_KHATT_LAYOUT_DATABASE = os.path.join(_ROOT, 'data', 'qpc-v4-15-lines.db')
QPC_V2_LAYOUT_DATABASE = os.path.join(_ROOT, 'data', 'digital-khatt-15-lines.db')
QPC_V1_LAYOUT_DATABASE = os.path.join(_ROOT, 'data', 'qpc-v1-15-lines.db')
# مصحف قطر's own 15-line layout (same 1..83668 word numbering, different line
# breaks than the Old Madina 1405 print). Used only by the mushaf-editor.
QATAR_LAYOUT_DATABASE = os.path.join(_ROOT, 'data', 'mushaf-qatar-layout.db')
# Layout Studio working copy for مصحف البحرين. Seeded from QPC V2 but kept
# separate so line edits/undo never mutate the shared Madinah 1421 source.
BAHRAIN_LAYOUT_DATABASE = os.path.join(_ROOT, 'data', 'mushaf-bahrain-layout.db')
# Printed مصحف البحرين scan (islamhouse PDF). Mushaf page N → PDF index N+4.
BAHRAIN_REF_PDF = os.path.join(_ROOT, 'data', 'refs', 'ar-mushaf-albahrains.pdf')
BAHRAIN_REF_CACHE = os.path.join(_ROOT, 'data', 'refs', 'bahrain_cache')
BAHRAIN_REF_PDF_OFFSET = 4  # 0-based PDF page = mushaf_page + offset
BAHRAIN_REF_PDF_URL = (
    'https://d1.islamhouse.com/data/ar/ih_books/single_02/ar-mushaf-albahrains.pdf'
)
# 1342H / 1924 Egyptian Survey Authority mushaf.  The Internet Archive item
# contains 850 scanned leaves; Quran pages are the printed/PDF pages 2..827.
# The Layout Studio project is generated offline by
# pipeline/import_mesaha_layout.py from Archive's DjVu OCR anchors.
MESAHA_LAYOUT_DATABASE = os.path.join(_ROOT, 'data', 'mushaf-mesaha-layout.db')
MESAHA_ARCHIVE_ID = 'mushafElMesaha46796794669_201703'
MESAHA_LAYOUT_MIN_PAGE = 2
MESAHA_LAYOUT_MAX_PAGE = 827
# مصحف الأزهر page geometry — seeded from الشمرلي (Shemrly word_index), edited
# via /azhar-layout (ENABLE_EDITOR). Rendered with Amiri Quran + الأزهر waqf.
AZHAR_LAYOUT_DATABASE = os.path.join(_ROOT, 'data', 'mushaf-azhar-layout.db')
SHAMARLY_LAYOUT_DATABASE = os.path.join(_ROOT, 'data', 'mushaf_layout_inferred.db')
QURAN_SCRIPT_DATABASE = os.path.join(_ROOT, 'data', 'quran_script.db')
AZHAR_LAYOUT_MIN_PAGE = 2
AZHAR_LAYOUT_MAX_PAGE = 525

# Local tajweed-coloring data, built offline by pipeline/build_tajweed_local.py
# from cpfair/quran-tajweed (CC-BY 4.0). Replaces the quran.com network call.
TAJWEED_DATABASE = os.path.join(_BASE_DIR, 'data', 'tajweed_local.db')
# Per-ayah Arabic tajweed *explanations* (prose), harvested offline from
# Tafsir Center MCP (mcp.tafsir.net). Companion to coloring — not spans.
TAJWEED_NOTES_DATABASE = os.path.join(_BASE_DIR, 'data', 'tajweed_notes_local.db')
# أسباب النزول (sparse), harvested offline from Tafsir MCP
# (nuzool + wahidi_asbab).
ASBAB_DATABASE = os.path.join(_BASE_DIR, 'data', 'asbab_local.db')
# Classical وقف-وابتدا literature aligned to QPC word positions — built by
# pipeline/build_muktafa.py from the OpenITI edition of الداني's المكتفى.
CLASSICAL_WAQF_DATABASE = os.path.join(_BASE_DIR, 'data', 'classical_waqf.db')
# Contemporary توجيه (د. أحمد صابر) aligned to QPC word positions.
# Live rows live in Supabase `public.tawjih`. This sqlite file is an optional
# test/offline fallback only — never mixed into classical_waqf.db.
TAWJIH_DATABASE = os.path.join(_BASE_DIR, 'data', 'tawjih.db')
# Local-only scholarly review decisions for classical-book candidates. This is
# written only by the ENABLE_EDITOR-gated reviewer and never by public routes.
CLASSICAL_REVIEW_DATABASE = os.path.join(_BASE_DIR, 'data', 'classical_review.db')
# Local tafseer data (5 Arabic tafsirs), built offline by
# pipeline/build_tafseer_local.py from QUL (qul.tarteel.ai) SQLite exports.
# Replaces the former per-request quran.com/quranenc.com network calls.
TAFSEER_LOCAL_DATABASE = os.path.join(_BASE_DIR, 'data', 'tafseer_local.db')

# Per-ayah Quran phonemes (surah:ayah → aya_phonemes_list) for the zipformer
# phoneme-ASR reference (تدريب recite-follow). Source: ReciteQuran ordered set.
QURAN_PHONEMES_JSON = os.path.join(_BASE_DIR, 'data', 'quran_phonemes_by_ayah.json')

# المتشابهات (repeated-phrase) corpus — curated shared word-runs across the
# whole Quran, word positions 1-based inclusive over the same QPC Hafs
# tokenization as core.datasets.qpc_hafs_data_normalized. Source: "Mutashabihat
# ul Quran" dataset. phrases.json: {phrase_id: {source, ayah: {verse_key:
# [[from,to],...]}, count, ayahs, surahs}}. phrase_verses.json: {verse_key:
# [phrase_id,...]} — reverse index for fast per-verse lookup.
MUTASHABIHAT_PHRASES_JSON = os.path.join(_BASE_DIR, 'data', 'mutashabihat', 'phrases.json')
MUTASHABIHAT_PHRASE_VERSES_JSON = os.path.join(_BASE_DIR, 'data', 'mutashabihat', 'phrase_verses.json')

MAX_AYAH_NUMBER = 286  # Al-Baqarah, the longest surah
SHEMRLY_CODEPOINT_BASE = 0xFB50  # Shemrly fonts index glyphs from U+FB51 (base + 1)

# True waqf stop symbols only (ayah/sajda/rubu markers are handled separately).
WAQF_SYMBOL_CHARS = set([
    'ۖ', 'ۗ', 'ۘ', 'ۙ', 'ۚ', 'ۛ', 'ۜ'
])
INDOPAK_EXTRA_WAQF_SYMBOL_CHARS = set([
    '۟', '۠', 'ۡ', 'ۢ', 'ۤ', 'ۥ', 'ۦ',
    '۪', '۫', '۬', 'ۭ',
    'ؕ', 'ؔ', 'ؗ'
])
# Markers like Sajda, Rubu, and verse-end that are NOT waqf.
# (U+06EC was previously listed here too, but it is also in
# INDOPAK_EXTRA_WAQF_SYMBOL_CHARS — the JS legend treats it as a Hindi waqf, so
# the duplicate caused U+06EC to be silently dropped from waqf extraction.)
NON_WAQF_SPECIFIC_CHARS = set([
    '۩', '۞', '۝'
])
ARABIC_INDIC_DIGIT_PATTERN = re.compile(r'^[٠-٩]+$')
# ࣰ-ࣿ: Arabic Extended-A tanween/diacritic variants (e.g. ࣰ
# "open fathatan") used by the Digital Khatt source text but not by the waqf
# DB's "الكلمة" column — without stripping these, _normalize_mushaf_word_token
# leaves a stray mark on the Digital Khatt token, the hint-based match in
# _find_mushaf_row_match_index fails, and the fallback scan can land on an
# earlier word with the same consonant skeleton (e.g. surah 2:138's repeated
# "صبغة"), displacing the waqf mark onto the wrong word.
# ـ: tatweel and ͏: combining grapheme joiner are zero-width/
# formatting characters that appear in some Digital Khatt tokens (e.g. around
# the decomposed hamza in "الْـٰأخِر") but never in the waqf DB's
# "الكلمة" column — stripped here so normalization can match across both.
ARABIC_DIACRITICS_STRIP_PATTERN = re.compile(r'[ـً-ٰٟۖ-ࣰۭ-ࣿ͏]')

# Broader pattern used for search normalisation: strip diacritics, tatweel,
# ayah-end markers, and Quranic annotation marks so user queries like "الله"
# match the fully-vocalised text "ٱللَّهِ" in the Quranic JSON sources.
_SEARCH_STRIP_PATTERN = re.compile(
    r'[ؐ-ًؚ-ٰٟۖ-ۭـ۝ࣰ-ࣿ﮲-﯁ ]'
)
_SEARCH_LETTER_FOLD = {
    'ٱ': 'ا', 'أ': 'ا', 'إ': 'ا', 'آ': 'ا', 'ى': 'ي', 'ئ': 'ي',
    'ؤ': 'و', 'ة': 'ه', 'ي': 'ي', 'ك': 'ك',
}
