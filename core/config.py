"""Application configuration: database paths, layout constants, and the
character sets / regexes used for waqf extraction and search normalisation.

Pure data only — no Flask app dependency — so every feature blueprint can
import these without pulling in the whole app. Paths are anchored to the
project root (this module lives one level down, in core/).
"""
import os
import re

# Project root (parent of this core/ package). All data/reciters paths hang
# off this so the constants resolve identically no matter who imports them.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_BASE_DIR = _ROOT  # kept under the original name for callers that reference it

DATABASE = os.path.join(_ROOT, 'data', 'word_name.db')
WAQF_DATABASE = os.path.join(_ROOT, 'data', 'waqf_symbols.db')
MUSHAF_WAQF_DATABASE = os.path.join(_ROOT, 'data', 'mushaf_waqf.db')
# مصاحف being adjusted from the Madinah v1 layout via /mushaf-editor.
EDITOR_EDITIONS = {'قطر', 'الكويت'}
# Per-reciter guide config: positions.db path + default waqf column from mushaf_waqf DB.
# Add a new entry here whenever a reciter has segmentation data.
RECITER_GUIDE_CONFIG = {
    'Mahmoud Khalil al-Husary (Mujawwad)': {
        'db':       os.path.join(_BASE_DIR, 'reciters', 'husary', 'mahmoud_khalil_al_husari_0_2_positions.db'),
        'waqf_col': 'المدينة الجديد',
    },
    'Mahmoud Khalil al-Husary (Muallim)': {
        'db':       os.path.join(_BASE_DIR, 'reciters', 'husary', 'positions.db'),
        'waqf_col': 'المدينة الجديد',
    },
    'Mahmoud Khalil al-Husary (Murattal)': {
        'db':       os.path.join(_BASE_DIR, 'reciters', 'husary', 'mahmoud_khalil_al_husari_0_1_positions.db'),
        'waqf_col': 'المدينة الجديد',
    },
    'Ibrahim Al-Akhdar': {
        'db':       os.path.join(_BASE_DIR, 'reciters', 'ibrahim-al-akhdar', 'positions.db'),
        'waqf_col': 'المدينة الجديد',
    },
    'Ayman Rushdi Suwaid': {
        'db':       os.path.join(_BASE_DIR, 'reciters', 'ayman-suwaid', 'positions.db'),
        'waqf_col': 'المدينة الجديد',
    },
    'Mahmoud Ali Al-Banna': {
        'db':       os.path.join(_BASE_DIR, 'reciters', 'mahmoud-ali-al-banna', 'positions.db'),
        'waqf_col': 'المدينة الجديد',
    },
    'Mustafa Ismaeel': {
        'db':       os.path.join(_BASE_DIR, 'reciters', 'mustafa-ismaeel', 'positions.db'),
        'waqf_col': 'المدينة الجديد',
    },
    'AbdulBaset AbdulSamad (Mujawwad)': {
        'db':       os.path.join(_BASE_DIR, 'reciters', 'abdul-basit-abdus-samad', 'mujawwad_positions.db'),
        'waqf_col': 'المدينة الجديد',
    },
    'AbdulBaset AbdulSamad (Murattal)': {
        'db':       os.path.join(_BASE_DIR, 'reciters', 'abdul-basit-abdus-samad', 'murattal_positions.db'),
        'waqf_col': 'المدينة الجديد',
    },
    'Mohamed al-Minshawi (Murattal)': {
        'db':       os.path.join(_BASE_DIR, 'reciters', 'mohammed-siddiq-al-minshawi', 'positions.db'),
        'waqf_col': 'المدينة الجديد',
    },
}
# Keep for backwards compat with any legacy code that may reference it
HUSARY_POSITIONS_DB = RECITER_GUIDE_CONFIG['Mahmoud Khalil al-Husary (Muallim)']['db']
# "New Madinah" source now uses the QPC v4 (1441/tajweed) 15-line layout — same
# 1..83668 word numbering as the older digital-khatt layout but with the proper
# QPC v4 line breaks. (Schema has no total_advance/x_offset columns.)
DIGITAL_KHATT_LAYOUT_DATABASE = os.path.join(_ROOT, 'data', 'qpc-v4-15-lines.db')
QPC_V1_LAYOUT_DATABASE = os.path.join(_ROOT, 'data', 'qpc-v1-15-lines.db')
# مصحف قطر's own 15-line layout (same 1..83668 word numbering, different line
# breaks than the Old Madina 1405 print). Used only by the mushaf-editor.
QATAR_LAYOUT_DATABASE = os.path.join(_ROOT, 'data', 'mushaf-qatar-layout.db')
# Local tajweed-coloring data, built offline by pipeline/build_tajweed_local.py
# from cpfair/quran-tajweed (CC-BY 4.0). Replaces the quran.com network call.
TAJWEED_DATABASE = os.path.join(_BASE_DIR, 'data', 'tajweed_local.db')
# Classical وقف-وابتدا literature aligned to QPC word positions — built by
# pipeline/build_muktafa.py from the OpenITI edition of الداني's المكتفى.
CLASSICAL_WAQF_DATABASE = os.path.join(_BASE_DIR, 'data', 'classical_waqf.db')

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
