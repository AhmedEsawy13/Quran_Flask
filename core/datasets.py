"""Raw Quranic source datasets, loaded once at import (local-first, CDN
fallback). These are the UNNORMALISED sources — waqf extraction and the
per-source normalised variants are built on top of these in app.py.
"""
from core.loader import load_json_cdn_or_local as _load

# Local files live under data/quran_text/
digital_khatt_data = _load(
    'Digital_Khatt_Aya_Space.json', 'data/quran_text/Digital_Khatt_Aya_Space.json'
)
qpc_hafs_data = _load(
    'QPC Hafs.json', 'data/quran_text/QPC Hafs.json'
)
indopak_nastaleeq_data = _load(
    'Indopak Nastaleeq_Waqf.json', 'data/quran_text/Indopak Nastaleeq_Waqf.json'
)
indopak_nastaleeq_2_data = _load(
    'indopak-nastaleeq 2.json', 'data/quran_text/indopak-nastaleeq 2.json'
)
transliteration_data = _load(
    'Transliteration.json', 'data/quran_text/Transliteration.json'
)
surahs_data = _load('surahs.json', 'data/quran_text/surahs.json')
if not isinstance(surahs_data, list):
    surahs_data = []
