"""Shared memorization data: reciter catalog, per-reciter audio URL
resolution, word-timestamp loading, and the reciter-validated 'breathing
guide' (real, attested pause points) — used by both memorize_bp (in app.py)
and breathing_bp (modules/breathing.py, modules/waqf_research.py). Mirrors
core/mushaf_waqf.py's role of serving multiple modules from one place.
"""
import gzip
import json
import logging
import os
import re
import threading
from collections import defaultdict
from urllib.parse import parse_qs, quote, urlencode, urlsplit

from core.config import _BASE_DIR

logger = logging.getLogger(__name__)


_MEMORIZATION_DIR = os.path.join(_BASE_DIR, 'reciters', 'mahmoud_khalil_al_husary_mp3quran')
_MEMORIZATION_AUDIO_TMPL = 'https://server13.mp3quran.net/husr/{surah:03d}.mp3'

# ── YouTube-sourced reciter catalogs ────────────────────────────────────────
# Some reciters have per-surah YouTube video URLs instead of direct MP3 URLs.
# Load their catalog.json at startup so we can map surah -> YouTube URL without
# touching the disk on every request.
#
# audio_tmpl for these entries is set to the sentinel '_yt_' so the helpers
# below know to call _yt_audio_url(reciter_id, surah) instead.

def _load_audio_catalog(slug: str) -> tuple[dict, dict]:
    """Return ``(chapter_urls, chapter_offsets_ms)`` from catalog.json."""
    catalog_path = os.path.join(_BASE_DIR, 'reciters', slug, 'catalog.json')
    if not os.path.exists(catalog_path):
        return {}, {}
    try:
        with open(catalog_path, encoding='utf-8') as fh:
            cat = json.load(fh)
        audio = cat.get('audio', {}) or {}
        return (
            audio.get('chapter_urls', {}) or {},
            audio.get('chapter_offsets_ms', {}) or {},
        )
    except Exception as e:
        logger.warning(f'Could not load audio catalog for {slug}: {e}')
        return {}, {}

# Map reciter_id -> {str(surah): yt_url} for YouTube-sourced reciters.
_YT_CHAPTER_URLS: dict = {}


def _yt_audio_url(reciter_id: str, surah: int) -> str | None:
    """Return the raw YouTube watch URL for a surah.

    The frontend (mushaf_memorize.js) detects youtube.com URLs and routes them
    through the YouTube IFrame Player API instead of a native <audio> element.
    This works on every deployment including Heroku (no server-side stream
    extraction; YouTube datacenter IP blocking is irrelevant).
    """
    chapter_urls = _YT_CHAPTER_URLS.get(reciter_id, {})
    return chapter_urls.get(str(surah))


# ── Google Drive / HuggingFace catalog-based reciters (_gd_ sentinel) ───────
# Some reciters have per-surah URLs that are a mix of:
#   • HuggingFace direct MP3 links (serve immediately, no conversion needed)
#   • Google Drive "view" pages (converted to Drive's native byte-range endpoint)
# audio_tmpl = '_gd_' tells the helpers below to call _gd_audio_url() which
# converts Drive view URLs to direct-download URLs and passes other URLs through.

_GD_FILE_ID_RE = re.compile(r'/file/d/([A-Za-z0-9_-]+)(?:/|$)')


# Map reciter_id -> {str(surah): url} for _gd_ sentinel reciters.
_GD_CHAPTER_URLS: dict = {}
_GD_CHAPTER_OFFSETS: dict = {}


def _drive_download_url(raw_url: str) -> str | None:
    """Convert a public Drive sharing URL to a native range-download URL.

    ``drive.google.com/uc`` and the viewer page can return HTML or a redirect
    when used as an ``<audio>`` source.  The user-content endpoint returns the
    actual MP3 and supports byte ranges, seeking, and CORS for native media.
    """
    if not raw_url:
        return None
    parsed = urlsplit(raw_url)
    match = _GD_FILE_ID_RE.search(parsed.path)
    if match:
        file_id = match.group(1)
    else:
        query = parse_qs(parsed.query)
        file_id = (query.get('id') or query.get('fileId') or [None])[0]
    if not file_id:
        return None

    params = [('id', file_id), ('export', 'download'), ('confirm', 't')]
    resource_key = parse_qs(parsed.query).get('resourcekey', [None])[0]
    if resource_key:
        params.append(('resourcekey', resource_key))
    return 'https://drive.usercontent.google.com/download?' + urlencode(params)


def _gd_audio_offset_ms(reciter_id: str, surah: int) -> int:
    """Return the chapter's offset inside its catalog audio file.

    A Drive file may contain several consecutive surahs.  QUL timestamps are
    chapter-relative, while the native audio element seeks on the shared file,
    so callers must add this offset before returning timing data to the UI.
    """
    raw = _GD_CHAPTER_OFFSETS.get(reciter_id, {}).get(str(surah), 0)
    try:
        return max(0, int(raw or 0))
    except (TypeError, ValueError):
        return 0


def _audio_offset_ms(reciter_id: str, surah: int) -> int:
    """Return the source-file offset for any reciter/surah combination."""
    cfg = MEMORIZATION_RECITERS.get(reciter_id, {})
    if cfg.get('audio_tmpl') == '_gd_':
        return _gd_audio_offset_ms(reciter_id, surah)
    return 0


def _audio_timing_entry(reciter_id: str, surah: int, entry):
    """Copy a QUL timing entry and shift it into the source-file timeline."""
    offset_ms = _audio_offset_ms(reciter_id, surah)
    if not offset_ms or not isinstance(entry, (list, tuple)) or len(entry) < 2:
        return entry
    try:
        verse_range = list(entry[0])
        verse_range[0] += offset_ms
        verse_range[1] += offset_ms
        words = []
        for word in entry[1]:
            shifted = list(word)
            shifted[1] += offset_ms
            shifted[2] += offset_ms
            words.append(shifted)
    except (IndexError, TypeError):
        return entry
    shifted_entry = list(entry)
    shifted_entry[0] = verse_range
    shifted_entry[1] = words
    return shifted_entry


def _gd_audio_url(reciter_id: str, surah: int) -> str | None:
    """Return a playable audio URL for a catalog-based (_gd_) reciter's surah.

    HuggingFace direct-MP3 URLs are returned as-is.
    Public Google Drive files are returned through Drive's native direct
    download endpoint.  Browser-facing callers should use
    ``_gd_browser_audio_url`` so cross-site media requests go through the
    same-origin proxy.
    """
    raw = _GD_CHAPTER_URLS.get(reciter_id, {}).get(str(surah))
    if not raw:
        return None
    if 'drive.google.com' in raw or 'drive.usercontent.google.com' in raw:
        direct = _drive_download_url(raw)
        if direct:
            return direct
        # Keep the configured fallback only for malformed catalog entries.
        cfg = MEMORIZATION_RECITERS.get(reciter_id, {})
        fallback = cfg.get('fallback_tmpl')
        return fallback.format(surah=surah) if fallback else None
    return raw  # HuggingFace or other direct MP3


def _gd_browser_audio_url(reciter_id: str, surah: int) -> str | None:
    """Return the browser playback URL for a catalog-based reciter.

    Drive rejects native cross-site media requests with ``Sec-Fetch-Site:
    cross-site``.  Route Drive files through the app's same-origin streaming
    endpoint; that endpoint fetches the same original Drive file server-side.
    """
    direct = _gd_audio_url(reciter_id, surah)
    if direct and direct.startswith('https://drive.usercontent.google.com/'):
        proxy_path = '/api/audio-proxy?url=' + quote(direct, safe='')
        try:
            from flask import has_request_context, request
            if has_request_context():
                return request.url_root.rstrip('/') + proxy_path
        except (ImportError, RuntimeError):
            pass
        return proxy_path
    return direct

# ── Memorization reciters ────────────────────────────────────────────────
# Each reciter needs a QUL `word_timestamps.json.gz` (from
# Wider-Community/quranic-universal-audio — the same format as Husary above) in
# its `dir`, plus a per-surah audio URL template. Reciters whose data file is
# present are offered in the UI; the rest are ignored until imported.
# To add one: drop <reciter>/word_timestamps.json.gz under reciters/ and add an
# entry here with its mp3 URL (see scripts/import_qul_reciters.py).
MEMORIZATION_RECITERS = {
    'husary': {
        'name_ar': 'محمود خليل الحصري', 'name_en': 'Mahmoud Khalil al-Husary',
        'dir': _MEMORIZATION_DIR,
        'audio_tmpl': _MEMORIZATION_AUDIO_TMPL,
    },
    'ahmed_amer': {
        'name_ar': 'أحمد محمد عامر', 'name_en': 'Ahmed Mohamed Amer',
        'dir': os.path.join(_BASE_DIR, 'reciters', 'ahmed_amer_tvquran'),
        'audio_tmpl': 'https://download.tvquran.com/download/recitations/197/143/{surah:03d}.mp3',
    },
    'minshawi': {
        'name_ar': 'محمد صديق المنشاوي', 'name_en': 'Mohamed Siddiq al-Minshawi',
        'dir': os.path.join(_BASE_DIR, 'reciters', 'mohammed_siddiq_al_minshawi_mp3quran'),
        'audio_tmpl': 'https://server10.mp3quran.net/minsh/{surah:03d}.mp3',
    },
    'abdulbasit': {
        'name_ar': 'عبد الباسط عبد الصمد', 'name_en': 'AbdulBaset AbdulSamad',
        'dir': os.path.join(_BASE_DIR, 'reciters', 'abdulbasit_abdulsamad_tarteel'),
        # Timestamps are aligned to the Tarteel CDN murattal recording (not the
        # mp3quran one), so the audio source must match for accurate seeking.
        'audio_tmpl': 'https://audio-cdn.tarteel.ai/quran/surah/abdulBasit/murattal/mp3/{surah:03d}.mp3',
    },
    'afasy': {
        'name_ar': 'مشاري راشد العفاسي', 'name_en': 'Mishary Rashid al-Afasy',
        'dir': os.path.join(_BASE_DIR, 'reciters', 'afasy_qul'),
        'audio_tmpl': 'https://server8.mp3quran.net/afs/{surah:03d}.mp3',
    },
    'banna': {
        'name_ar': 'محمود علي البنا', 'name_en': 'Mahmoud Ali Al-Banna',
        'dir': os.path.join(_BASE_DIR, 'reciters', 'mahmoud_ali_al_banna_qdc'),
        # QUL v1.1.0 timestamps were aligned to these QuranicAudio per-surah files,
        # so use the same source (CBR 128 → accurate seeking, supports HTTP range).
        'audio_tmpl': 'https://download.quranicaudio.com/quran/mahmood_ali_albana/{surah:03d}.mp3',
    },
    'maher': {
        'name_ar': 'ماهر المعيقلي', 'name_en': 'Maher Al-Muaiqly',
        'dir': os.path.join(_BASE_DIR, 'reciters', 'maher_al_muaiqly_qdc'),
        'audio_tmpl': 'https://download.quranicaudio.com/quran/maher_almu3aiqly/year1440/{surah:03d}.mp3',
    },
    'sufi': {
        'name_ar': 'عبد الرشيد صوفي', 'name_en': 'Abdur-Rashid Sufi',
        'dir': os.path.join(_BASE_DIR, 'reciters', 'abdur_rashid_sufi_qdc'),
        'audio_tmpl': 'https://download.quranicaudio.com/quran/abdurrashid_sufi/{surah:03d}.mp3',
    },
    'maasaraawi': {
        'name_ar': 'أحمد عيسى المعصراوي', 'name_en': 'Ahmed Issa Al-Maasaraawi',
        'dir': os.path.join(_BASE_DIR, 'reciters', 'ahmed_issa_al_maasaraawi_mp3quran'),
        'audio_tmpl': 'https://server16.mp3quran.net/a_maasaraawi/Rewayat-Hafs-A-n-Assem/{surah:03d}.mp3',
    },
    'abdulhakam': {
        'name_ar': 'محمود عبدالحكم', 'name_en': 'Mahmoud Abdul Hakam',
        'dir': os.path.join(_BASE_DIR, 'reciters', 'mahmoud_abdul_hakam_mp3quran'),
        'audio_tmpl': 'https://server16.mp3quran.net/m_abdelhakam/Rewayat-Hafs-A-n-Assem/{surah:03d}.mp3',
    },
    'burhaji': {
        'name_ar': 'محمد برهجي', 'name_en': 'Mohammed Burhaji',
        'dir': os.path.join(_BASE_DIR, 'reciters', 'mohammed_burhaji_yt'),
        'audio_tmpl': '_yt_',  # per-surah YouTube videos; resolved via _yt_audio_url()
    },
    'shaheen': {
        'name_ar': 'أحمد خليل شاهين', 'name_en': 'Ahmed Khalil Shaheen',
        'dir': os.path.join(_BASE_DIR, 'reciters', 'ahmed_shaheen_mp3quran'),
        'audio_tmpl': 'https://server16.mp3quran.net/shaheen/Rewayat-Hafs-A-n-Assem/{surah:03d}.mp3',
    },
    'huthaifi': {
        'name_ar': 'علي بن عبد الرحمن الحذيفي', 'name_en': 'Ali Al-Huthaifi',
        'dir': os.path.join(_BASE_DIR, 'reciters', 'ali_al_huthaifi_mp3quran'),
        'audio_tmpl': 'https://server9.mp3quran.net/hthfi/{surah:03d}.mp3',
    },
    'akhdar': {
        'name_ar': 'إبراهيم الأخضر', 'name_en': 'Ibrahim Al-Akhdar',
        'dir': os.path.join(_BASE_DIR, 'reciters', 'ibrahim_al_akhdar_drive'),
        # Per-surah catalog of public Google Drive files. Several files contain
        # multiple consecutive surahs; chapter_offsets_ms shifts QUL timings
        # into the shared file timeline.
        'audio_tmpl': '_gd_',
        'fallback_tmpl': 'https://server6.mp3quran.net/akdr/{surah:03d}.mp3',
    },
    'ayyub': {
        'name_ar': 'محمد أيوب', 'name_en': 'Mohammed Ayyub',
        'dir': os.path.join(_BASE_DIR, 'reciters', 'mohammed_ayyub_drive'),
        # Public Google Drive files; some files contain multiple surahs.
        'audio_tmpl': '_gd_',
        'fallback_tmpl': 'https://server8.mp3quran.net/ayyub/{surah:03d}.mp3',
    },
    'mustafa_ismail': {
        'name_ar': 'مصطفى إسماعيل', 'name_en': 'Mustafa Ismail',
        'dir': os.path.join(_BASE_DIR, 'reciters', 'mustafa_ismail_mp3quran'),
        'audio_tmpl': 'https://server8.mp3quran.net/mustafa/{surah:03d}.mp3',
    },
    # Abdullah Al-Buaijan (عبد الله البعيجان) is in QUL v1.1.0 but its audio is a
    # 2025 YouTube recording: surahs 3–114 are only YouTube video URLs (no
    # streamable per-surah MP3), so the timestamps can't drive seek-based playback
    # here. Excluded until an aligned per-surah MP3 source exists.
}

# Populate catalog URL/offset maps at startup.
for _rid, _rcfg in MEMORIZATION_RECITERS.items():
    _slug = os.path.basename(_rcfg['dir'])
    if _rcfg.get('audio_tmpl') == '_yt_':
        _YT_CHAPTER_URLS[_rid], _ = _load_audio_catalog(_slug)
    elif _rcfg.get('audio_tmpl') == '_gd_':
        (_GD_CHAPTER_URLS[_rid],
         _GD_CHAPTER_OFFSETS[_rid]) = _load_audio_catalog(_slug)

_DEFAULT_MEMO_RECITER = 'husary'

def _memo_reciter_cfg(reciter_id):
    return MEMORIZATION_RECITERS.get(reciter_id) or MEMORIZATION_RECITERS[_DEFAULT_MEMO_RECITER]

def _memo_reciter_installed(reciter_id):
    cfg = MEMORIZATION_RECITERS.get(reciter_id)
    if not cfg:
        return False
    tmpl = cfg.get('audio_tmpl')
    if not tmpl:
        return False
    # YouTube-sourced reciters only need chapter URLs to be loaded; yt-dlp is no
    # longer required because audio plays client-side via the IFrame Player API.
    if tmpl == '_yt_':
        if not _YT_CHAPTER_URLS.get(reciter_id):
            return False
    # Catalog-based (Drive/HF) reciters need their chapter URLs loaded.
    if tmpl == '_gd_':
        if not _GD_CHAPTER_URLS.get(reciter_id):
            return False
    return bool(os.path.exists(os.path.join(cfg['dir'], 'word_timestamps.json.gz')))
_memorization_word_ts = {}      # reciter_id -> word-timestamps dict (cached)
_memorization_lock = threading.Lock()


def _load_memorization_word_ts(reciter_id=_DEFAULT_MEMO_RECITER):
    """Lazy-load + cache a reciter's surah-absolute word timestamps."""
    if reciter_id in _memorization_word_ts:
        return _memorization_word_ts[reciter_id]
    with _memorization_lock:
        if reciter_id not in _memorization_word_ts:
            cfg = _memo_reciter_cfg(reciter_id)
            path = os.path.join(cfg['dir'], 'word_timestamps.json.gz')
            with gzip.open(path, 'rt', encoding='utf-8') as fh:
                _memorization_word_ts[reciter_id] = json.load(fh)
    return _memorization_word_ts[reciter_id]


def _segment_phrases(words, gap_ms):
    """Split a verse's word list into phrases at silence gaps >= gap_ms.

    `words` is the source's [[word_index, start_ms, end_ms], ...]. A run of words
    spoken without a meaningful pause becomes one phrase. Returns a list of
    {start, end, first_word, last_word} in milliseconds. Repeated-phrase verses
    (where word_index resets) simply yield extra phrases for the repeated audio,
    which is faithful to what is actually recited."""
    phrases = []
    if not words:
        return phrases
    run_start = words[0][1]
    run_first = words[0][0]
    prev_end = words[0][2]
    prev_idx = words[0][0]
    for idx, s, e in words[1:]:
        if s - prev_end >= gap_ms:
            phrases.append({'start': run_start, 'end': prev_end,
                            'first_word': run_first, 'last_word': prev_idx})
            run_start = s
            run_first = idx
        prev_end = e
        prev_idx = idx
    phrases.append({'start': run_start, 'end': prev_end,
                    'first_word': run_first, 'last_word': prev_idx})
    return phrases




_memorization_breathing_cache = {}


def _forward_waqf_stops(words, gap_ms):
    """Split a reciter's verse pauses into genuine FORWARD waqfs vs. 'pause
    then go back to repeat' artifacts.

    A pause after a phrase is a real waqf only if recitation then continues
    FORWARD. If the next phrase resumes at or before the word we paused on
    (first_word <= last_word), the reciter stopped to re-recite (a correction /
    repeat), not to breathe at a stopping point — so it isn't a waqf. Those
    repeats are returned separately so the UI can show "this reciter repeated
    from word X" instead of mistaking it for a stop.

    Returns (stops, repeats):
      stops   = {word_idx: end_ms_from_verse_start}  (1-based word_idx)
      repeats = [(paused_after_word_idx, resumed_at_word_idx), ...]  (1-based)"""
    stops, repeats = {}, []
    if not words:
        return stops, repeats
    phrases = _segment_phrases(words, gap_ms)
    vstart = words[0][1]
    for i in range(len(phrases) - 1):
        cur, nxt = phrases[i], phrases[i + 1]
        if nxt['first_word'] <= cur['last_word']:
            repeats.append((cur['last_word'], nxt['first_word']))
            continue  # reciter went back to repeat — not a forward waqf
        w = cur['last_word']
        dur = cur['end'] - vstart
        if w not in stops or dur < stops[w]:
            stops[w] = dur
    return stops, repeats


# Cross-reciter consensus waqf detection (the /waqf comparison page and the
# memorization breathing guide) doesn't use a duration threshold at all: ANY
# nonzero forward gap counts as that reciter's phrase break. Empirically,
# gap==0 is the overwhelming default (~95% of reciter/word pairs across a
# 300-verse sample), so even a 10-40ms gap reflects a real, if brief, pause —
# and a verse-by-verse sweep showed gap_ms=1 reproduces the old 250ms+rescue
# results almost exactly (2/315 verses differed, each gaining one extra solo
# stop at a plausible phrase boundary). Consensus COUNT across reciters is
# what signals a genuine waqf, not how long any one of them paused.
_WAQF_CONSENSUS_GAP_MS = 1


def _build_breathing_guide(surah_number):
    """Per-verse 'breathing guide': word positions where at least one of the
    installed reciters makes a real FORWARD pause (a waqf), with how many
    reciters pause there, WHICH reciters do, and the average cumulative
    duration (seconds from verse start) to that point.

    These are real, attested reciter stops — never algorithmically invented,
    and 'pause-to-repeat' artifacts are filtered out (see _forward_waqf_stops)
    — so a memorizer can pick the latest one within their own breath capacity
    and stop there, the way a professional reciter would. Stops only one
    reciter makes (انفرد) are flagged so the user knows they're uncommon."""
    reciter_ids = tuple(sorted(rid for rid in MEMORIZATION_RECITERS if _memo_reciter_installed(rid)))
    cache_key = (surah_number, reciter_ids)
    if cache_key in _memorization_breathing_cache:
        return _memorization_breathing_cache[cache_key]

    per_reciter_ts = {}
    for rid in reciter_ids:
        try:
            per_reciter_ts[rid] = _load_memorization_word_ts(rid)
        except Exception as e:
            logger.error(f"Breathing guide: failed to load {rid}: {e}")

    verses = {}
    ayah = 1
    while True:
        vk = f"{surah_number}:{ayah}"
        present = [(rid, wts[vk]) for rid, wts in per_reciter_ts.items() if vk in wts]
        if not present:
            break
        raw = {}
        verse_durs = []
        for rid, entry in present:
            words = entry[1]
            if not words:
                continue
            verse_durs.append((words[-1][2] - words[0][1]) / 1000.0)
            stops_r, repeats_r = _forward_waqf_stops(words, _WAQF_CONSENSUS_GAP_MS)
            raw[rid] = {'stops': stops_r, 'repeats': repeats_r}

        word_reciters = defaultdict(list)   # word_idx -> [reciter_id, ...] (who pauses)
        word_durs = defaultdict(list)       # word_idx -> [cumulative seconds, ...]
        repeats = []                        # [{reciter_id, from_wpos, to_wpos}]
        for rid, info in raw.items():
            for w, dur_ms in info['stops'].items():
                word_reciters[w].append(rid)
                word_durs[w].append(dur_ms / 1000.0)
            for frm, to in info['repeats']:
                repeats.append({'reciter_id': rid, 'from_wpos': frm - 1, 'to_wpos': to - 1})

        stops = []
        for word_idx in sorted(word_reciters):
            who = word_reciters[word_idx]
            durs = word_durs[word_idx]
            stops.append({
                'wpos': word_idx - 1,
                'duration': round(sum(durs) / len(durs), 2),
                'reciters': len(who),
                'reciter_ids': who,
                'solo': len(who) == 1,   # انفرد — only this one reciter pauses here
            })
        verses[ayah] = {
            'full_duration': round(sum(verse_durs) / len(verse_durs), 2) if verse_durs else None,
            'reciters_total': len(verse_durs),
            'stops': stops,
            'repeats': repeats,
        }
        ayah += 1

    result = {
        'surah_number': surah_number,
        'reciters': [
            {'id': rid, 'name_ar': MEMORIZATION_RECITERS[rid].get('name_ar', '')}
            for rid in reciter_ids
        ],
        'verses': verses,
    }
    _memorization_breathing_cache[cache_key] = result
    return result

_ARABIC_INDIC_DIGITS = set('٠١٢٣٤٥٦٧٨٩')


def _has_arabic_letter(tok):
    """True if a token contains an actual Arabic letter (so it is a recited
    word, not an ornament like the rub‑el‑hizb ۞, a sajda ۩, or an ayah number)."""
    return any(0x0621 <= ord(ch) <= 0x064A or 0x0671 <= ord(ch) <= 0x06D3 for ch in tok)
