"""تثبيت — Circular Segmented Repetition memorization player. Page-by-page
visual memorization on the Digital Khatt layout with synced reciter audio,
segmented into repeatable phrases (acoustic silence gaps, or mushaf-waqf
boundaries snapped to the nearest real pause).
"""
import logging
import os
import sqlite3
from collections import defaultdict

from flask import jsonify, render_template, request

from core.blueprints import memorize_bp
from core.config import _BASE_DIR
from core.datasets import normalize_source, get_quran_text_data_by_source
from core.loader import IS_SERVERLESS as _IS_SERVERLESS
from core.memorization import (
    MEMORIZATION_RECITERS, _memo_reciter_cfg, _memo_reciter_installed,
    _load_memorization_word_ts, _memorization_lock, _segment_phrases,
    _build_breathing_guide, _yt_audio_url, _gd_audio_url,
    _WAQF_CONSENSUS_GAP_MS, _DEFAULT_MEMO_RECITER,
)

logger = logging.getLogger(__name__)


@memorize_bp.route('/memorize')
def memorize():
    """Page-by-page visual memorization on the Digital Khatt (Madinah) mushaf
    layout, with synced Husary audio. See templates/mushaf_memorize.html."""
    return render_template('mushaf_memorize.html', enable_vercel_analytics=_IS_SERVERLESS)


# ── Memorization mode (Circular Segmented Repetition) ───────────────────────────
# Uses the per-surah Husary timestamps (mahmoud_khalil_al_husary_mp3quran). Word
# timestamps are surah-absolute (one MP3 per surah), so any [start,end] range —
# a single word, a natural phrase, a verse, or a cumulative run of verses — maps
# to a direct seek in the surah audio. Phrases are derived from the silence gaps
# in the alignment itself, i.e. where the reciter actually paused.


# Husary mushaf-waqf phrase boundaries (sub-verse segments). Used by the
# 'waqf' segmentation mode, snapped to real pauses in the mp3quran audio.
_MEMORIZATION_WAQF_DB = os.path.join(_BASE_DIR, 'reciters', 'husary',
                                     'mahmoud_khalil_al_husari_0_1_positions.db')
_memorization_waqf_bounds = None
def _load_waqf_boundaries():
    """Lazy-load per-verse mushaf-waqf phrase boundaries (0-based start_word)
    from the Husary positions DB. Returns {verse_key: [start_word, ...]}."""
    global _memorization_waqf_bounds
    if _memorization_waqf_bounds is not None:
        return _memorization_waqf_bounds
    with _memorization_lock:
        if _memorization_waqf_bounds is None:
            bounds = defaultdict(list)
            try:
                con = sqlite3.connect(_MEMORIZATION_WAQF_DB)
                for s, a, w in con.execute(
                    "SELECT start_sura, start_aya, start_word FROM positions "
                    "WHERE index_type='sura' AND start_sura IS NOT NULL "
                    "AND start_aya IS NOT NULL AND start_word IS NOT NULL"
                ):
                    bounds[f"{int(s)}:{int(a)}"].append(int(w))
                con.close()
                bounds = {vk: sorted(set(v)) for vk, v in bounds.items()}
            except sqlite3.Error as e:
                logger.error(f"Waqf boundaries load failed: {e}")
                bounds = {}
            _memorization_waqf_bounds = bounds
    return _memorization_waqf_bounds


def _waqf_aligned_phrases(words, boundaries, snap_floor, snap_window=3):
    """Phrases from mushaf-waqf word boundaries, each snapped to the nearest
    real silence (>= snap_floor ms) within +/- snap_window words so audio cuts
    land on a pause when one is close. If no pause is nearby, the cut stays at
    the waqf boundary (honouring the mark even mid-flow). This absorbs the small
    word-index offsets between the waqf DB and the mp3quran source."""
    n = len(words)
    if not words:
        return []
    starts = [w[1] for w in words]
    ends = [w[2] for w in words]
    cuts = {0}
    for b in boundaries:
        if b <= 0 or b >= n:
            continue
        best_pos, best_gap = b, -1
        lo, hi = max(1, b - snap_window), min(n - 1, b + snap_window)
        for pos in range(lo, hi + 1):
            g = starts[pos] - ends[pos - 1]
            if g >= snap_floor and g > best_gap:
                best_gap, best_pos = g, pos
        cuts.add(best_pos if best_gap >= snap_floor else b)
    cut_list = sorted(cuts)
    phrases = []
    for i, cp in enumerate(cut_list):
        end_pos = (cut_list[i + 1] - 1) if i + 1 < len(cut_list) else n - 1
        if end_pos < cp:
            continue
        phrases.append({'start': words[cp][1], 'end': words[end_pos][2],
                        'first_word': words[cp][0], 'last_word': words[end_pos][0]})
    return phrases


@memorize_bp.route('/api/memorization/<int:surah_number>/breathing', methods=['GET'])
def get_memorization_breathing(surah_number):
    """Validated 'breathing guide' for a surah: per verse, word positions where
    at least one installed reciter actually pauses, with consensus count and
    average cumulative duration — so a user with a shorter or longer breath can
    pick a real, attested stopping point instead of guessing where to pause."""
    if not (1 <= surah_number <= 114):
        return jsonify({"error": "Invalid surah number."}), 400
    try:
        data = _build_breathing_guide(surah_number)
    except Exception as e:
        logger.error(f"Breathing guide failed for surah {surah_number}: {e}")
        return jsonify({"error": "Breathing guide unavailable"}), 503
    if not data['verses']:
        return jsonify({"error": "No memorization data for this surah."}), 404
    return jsonify(data)




@memorize_bp.route('/api/memorization/<int:surah_number>', methods=['GET'])
def get_memorization(surah_number):
    """Per-surah memorization data: audio URL + per-verse timing and phrases.

    All times are returned in SECONDS (audio.currentTime units).
      ?gap=<ms>  silence threshold (default 250): a break in 'acoustic' mode,
                 the snap floor in 'waqf' mode.
      ?mode=acoustic|waqf  acoustic = split at the reciter's pauses (default);
                 waqf = split at mushaf-waqf marks, snapped to nearby pauses."""
    if not (1 <= surah_number <= 114):
        return jsonify({"error": "Invalid surah number."}), 400
    mode = (request.args.get('mode', 'acoustic') or 'acoustic').lower()
    if mode not in ('acoustic', 'waqf'):
        mode = 'acoustic'
    # 250ms default: validated against the Husary waqf DB
    # (mahmoud_khalil_al_husari_0_1_positions.db). At 250ms the silence-gap
    # split matches that DB's phrase boundaries on the verses where Husary
    # actually pauses (e.g. the 319ms micro-pause before "يَعْلَمُ" in Ayat
    # al-Kursi → 7 phrases like the DB), while still NOT cutting at the ~65% of
    # DB boundaries that are meaning-only stops with no audible pause here.
    gap_ms = request.args.get('gap', 250, type=int)
    if gap_ms < 0 or gap_ms > 5000:
        gap_ms = 250

    reciter_id = (request.args.get('reciter', _DEFAULT_MEMO_RECITER) or _DEFAULT_MEMO_RECITER)
    if not _memo_reciter_installed(reciter_id):
        reciter_id = _DEFAULT_MEMO_RECITER
    reciter_cfg = _memo_reciter_cfg(reciter_id)

    try:
        word_ts = _load_memorization_word_ts(reciter_id)
    except Exception as e:
        logger.error(f"Memorization data load failed for {reciter_id}: {e}")
        return jsonify({"error": "Memorization data unavailable"}), 503

    waqf_bounds = _load_waqf_boundaries() if mode == 'waqf' else {}
    font_type = normalize_source(request.args.get('font_type', 'qpc_hafs') or 'qpc_hafs')
    text_data = get_quran_text_data_by_source(font_type)

    verses = []
    ayah = 1
    while True:
        vk = f"{surah_number}:{ayah}"
        if vk not in word_ts:
            break
        entry = word_ts[vk]
        verse_range, words = entry[0], entry[1]
        if mode == 'waqf':
            phrases = _waqf_aligned_phrases(words, waqf_bounds.get(vk, []), gap_ms)
            if not phrases:                       # verse missing from waqf DB
                phrases = _segment_phrases(words, _WAQF_CONSENSUS_GAP_MS)
        else:
            # Acoustic mode: use the same consensus gap (1 ms) as the مكث guide
            # so phrase boundaries match exactly what مكث shows — any forward
            # pause in the reciter's audio is a real stop point.
            phrases = _segment_phrases(words, _WAQF_CONSENSUS_GAP_MS)
        text = ''
        td = text_data.get(vk) if isinstance(text_data, dict) else None
        if isinstance(td, dict):
            text = td.get('text', '') or ''
        verses.append({
            'ayah': ayah,
            'verse_key': vk,
            'start': round(verse_range[0] / 1000.0, 3),
            'end': round(verse_range[1] / 1000.0, 3),
            'text': text,
            'phrases': [
                {'start': round(p['start'] / 1000.0, 3),
                 'end': round(p['end'] / 1000.0, 3)}
                for p in phrases
            ],
            'words': [
                [w[0] - 1, round(w[1] / 1000.0, 3), round(w[2] / 1000.0, 3)]
                for w in words
            ],
        })
        ayah += 1

    if not verses:
        return jsonify({"error": "No memorization data for this surah."}), 404

    tmpl = reciter_cfg.get('audio_tmpl', '')
    if tmpl == '_yt_':
        audio_url = _yt_audio_url(reciter_id, surah_number)
    elif tmpl == '_gd_':
        audio_url = _gd_audio_url(reciter_id, surah_number)
    else:
        audio_url = tmpl.format(surah=surah_number) if tmpl else None

    return jsonify({
        'surah_number': surah_number,
        'reciter': reciter_cfg.get('name_en', 'Mahmoud Khalil al-Husary'),
        'reciter_id': reciter_id,
        'reciter_name_ar': reciter_cfg.get('name_ar', ''),
        'audio_url': audio_url,
        'gap_ms': gap_ms,
        'mode': mode,
        'verses': verses,
    })


@memorize_bp.route('/api/memorization-reciters', methods=['GET'])
def get_memorization_reciters():
    """List the memorization reciters whose timestamp data is installed."""
    out = []
    for rid, cfg in MEMORIZATION_RECITERS.items():
        if _memo_reciter_installed(rid):
            out.append({'id': rid, 'name_ar': cfg.get('name_ar', ''), 'name_en': cfg.get('name_en', '')})
    return jsonify(out)

