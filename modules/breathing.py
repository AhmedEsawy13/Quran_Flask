"""Pause guide (مُكْث): reciter-validated waqf positions, printed-mushaf
waqf lookup, the four classical waqf books' graded citations, and the
تدريب الوقف practice grader (including ASR-based tajweed checking). The
Quran-wide analytical /api/waqf-research/* family lives in
modules/waqf_research.py — a separate file, same breathing_bp blueprint.
"""
import json
import logging
import os
import sqlite3
from collections import defaultdict
from functools import lru_cache

from flask import jsonify, render_template, request

from core.blueprints import breathing_bp
from core.config import (
    RECITER_GUIDE_CONFIG, CLASSICAL_WAQF_DATABASE,
    QURAN_PHONEMES_JSON,
)
from core.mushaf_waqf import (
    _get_mushaf_version_whitelist,
    _is_valid_mushaf_version,
    _get_waqf_at_boundary,
    get_mushaf_waqf_symbols,
    _fetch_single_mushaf_waqf,
)
from core.db import connect as _sqlite_connect
from core.datasets import qpc_hafs_data_normalized
from core.loader import IS_SERVERLESS as _IS_SERVERLESS
from core.memorization import (
    MEMORIZATION_RECITERS, _memo_reciter_installed, _load_memorization_word_ts, _segment_phrases, _forward_waqf_stops,
    _has_arabic_letter, _gd_audio_url, _yt_audio_url,
    _WAQF_CONSENSUS_GAP_MS,
)

logger = logging.getLogger(__name__)


@lru_cache(maxsize=2048)
def _get_positions_segments(surah_number, ayah_number, reciter=None):
    """Return (segments, has_db) for a single ayah from the reciter's positions.db.

    Each segment: {start_word, end_word, text, is_repeat}
    has_db=False means no positions.db exists for this reciter (guide unavailable).
    has_db=True with empty segments means the ayah has no segmentation data.
    """
    cfg = RECITER_GUIDE_CONFIG.get(reciter or '', {})
    db_path = cfg.get('db')
    # No fallback to another reciter's DB — missing config means guide is unavailable.
    if not db_path or not os.path.exists(db_path):
        return [], False
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("""
            SELECT start_word, end_word, uthmani_text
            FROM positions
            WHERE start_sura = ? AND start_aya = ?
              AND end_sura   = ? AND end_aya   = ?
              AND has_quran  = 1
            ORDER BY CAST(segment_index AS REAL)
        """, (surah_number, ayah_number, surah_number, ayah_number))
        rows = cur.fetchall()
        conn.close()

        segments = []
        high_water = 0  # furthest end_word reached so far
        for start_w, end_w, text in rows:
            start_w = int(start_w)
            end_w   = int(end_w)
            # A segment is a repeat only when it does NOT advance past the furthest
            # word already covered.  If end_w > high_water the reciter has moved to a
            # new stopping point even if start_w backed up into covered territory.
            is_repeat = end_w <= high_water
            segments.append({
                'start_word': start_w,
                'end_word':   end_w,
                'text':       text or '',
                'is_repeat':  is_repeat,
            })
            if end_w > high_water:
                high_water = end_w
        return segments, True
    except Exception as e:
        logger.error(f'Error reading positions.db for reciter {reciter!r}: {e}')
        return [], True



@breathing_bp.route('/api/recitation-guide/<int:surah_number>/<int:ayah_number>', methods=['GET'])
def get_recitation_guide(surah_number, ayah_number):
    """Return segmented recitation guide for a reciter, powered by their positions.db.

    Query params:
      reciter — the reciter key (e.g. 'Mahmoud Khalil al-Husary (Muallim)')

    Returns:
      {reciter, has_positions_db, segments: [{start_word, end_word, text, waqf: [{symbols}]}]}
    """
    if not (1 <= surah_number <= 114) or ayah_number < 1:
        return jsonify({'error': 'invalid parameters'}), 400

    reciter = request.args.get('reciter', '').strip()
    cfg = RECITER_GUIDE_CONFIG.get(reciter, {})
    # الحصري column was dropped from mushaf_waqf.db (commit 703521b); fall back
    # to المدينة الجديد so unconfigured reciters still get a guide overlay.
    waqf_col = cfg.get('waqf_col', 'المدينة الجديد')
    valid_versions = [waqf_col] if _is_valid_mushaf_version(waqf_col) else []

    pos_segs, has_db = _get_positions_segments(surah_number, ayah_number, reciter)

    if not has_db:
        return jsonify({'reciter': reciter, 'has_positions_db': False, 'segments': []})

    result_segments = []
    for seg in pos_segs:
        waqf_entries = _get_waqf_at_boundary(
            surah_number, ayah_number, seg['end_word'], valid_versions
        ) if valid_versions else []
        # Strip version label — the guide is per-reciter, not per-mushaf
        for e in waqf_entries:
            e.pop('version', None)
        result_segments.append({
            'start_word': seg['start_word'],
            'end_word':   seg['end_word'],
            'text':       seg['text'],
            'is_repeat':  seg['is_repeat'],
            'waqf':       waqf_entries,
        })
    return jsonify({'reciter': reciter, 'has_positions_db': True, 'segments': result_segments})


@breathing_bp.route('/api/pause-match/<int:surah_number>/<int:ayah_number>', methods=['GET'])
def get_pause_match(surah_number, ayah_number):
    """Return how well a reciter's pause positions match each mushaf's waqf marks.

    Query params:
      reciter — the reciter key

    Returns:
      {
        has_data: bool,
        pause_count: int,
        matches: { version: {matched, total, score} }
      }
    """
    if not (1 <= surah_number <= 114) or ayah_number < 1:
        return jsonify({'error': 'invalid parameters'}), 400

    reciter = request.args.get('reciter', '').strip()
    pos_segs, has_db = _get_positions_segments(surah_number, ayah_number, reciter)

    if not has_db or not pos_segs:
        return jsonify({'has_data': False, 'pause_count': 0, 'matches': {}})

    versions = sorted(_get_mushaf_version_whitelist())

    # ── Filter out repeated segments ─────────────────────────────────────────
    # Repeated segments (reciter backs up and re-reads) are not real pauses.
    pause_segs = [seg for seg in pos_segs if not seg.get('is_repeat')]

    if not pause_segs:
        return jsonify({'has_data': False, 'pause_count': 0, 'matches': {}})

    # ── Identify the verse-end stop ──────────────────────────────────────────
    # The last non-repeat segment always ends at رأس الآية.
    verse_end_word = pause_segs[-1]['end_word']

    # Symbols that explicitly PROHIBIT stopping (verse-end precision check only).
    # U+06D9 (ۙ) = IndoPak glyph for "لا" = لا يجوز الوقف.
    def _is_prohibited_stop(symbols_str):
        # Exact-match only — substring 'in' would falsely flag arbitrary
        # composite waqf strings that happen to contain the letters ل-ا.
        sym = (symbols_str or '').strip()
        return sym == 'لا' or sym == '\u06D9'

    # Symbols that should NOT count as coverage targets — only hard prohibitions.
    # ص (صلى) is treated like ج (جائز): stopping is permissible, so it IS a target.
    def _is_not_coverage_mark(symbols_str):
        sym = (symbols_str or '').strip()
        if not sym:
            return True
        return _is_prohibited_stop(sym)

    # ── Discretionary stops only ─────────────────────────────────────────────
    # Exclude the verse-end stop (رأس الآية): every reciter stops there and it is
    # trivially valid in every mushaf, so counting it inflates "صحة وقفاته". This
    # also handles the back-up-and-repeat case (e.g. Suwaid at 12:27, who stops at
    # فكذبت then re-reads from it to the verse end) — the resumed run terminates at
    # رأس الآية and must not be counted as a second discretionary waqf.
    # (reciter-compare already drops the verse-end for the same reason.)
    mid_pause_segs = [seg for seg in pause_segs if seg['end_word'] != verse_end_word]
    pause_count = len(mid_pause_segs)

    # Coverage still credits every real stop (including the verse-end) so a mark on
    # the final word can be matched.
    pause_end_words = {seg['end_word'] for seg in pause_segs}

    matches = {}
    for ver in versions:
        # ── Precision: how many of the reciter's discretionary stops are valid ─
        matched = 0
        for seg in mid_pause_segs:
            waqf_entries = _get_waqf_at_boundary(
                surah_number, ayah_number, seg['end_word'], [ver]
            )
            # ص (صلى) is treated like ج (جائز) — any permissible mark counts.
            valid_entries = [
                e for e in waqf_entries
                if not _is_prohibited_stop(e.get('symbols', ''))
            ]
            if valid_entries:
                matched += 1

        # ── Coverage: how many of the mushaf's marks the reciter stopped at ──
        # Exclude only hard prohibition marks (لا / ۙ).
        # ص (صلى) is treated like ج — it IS a mark the reciter is expected to cover.
        mushaf_rows = _fetch_single_mushaf_waqf(surah_number, ayah_number, ver)
        mark_positions = {
            r['word_index'] for r in mushaf_rows
            if r.get('word_index') and not _is_not_coverage_mark(r.get('symbols', ''))
        }
        # A mark at word_index wi is covered when a pause falls at end_word=wi or wi+1
        # (matching the ±1 fallback logic in _get_waqf_at_boundary)
        marks_covered = sum(
            1 for wi in mark_positions
            if wi in pause_end_words or (wi + 1) in pause_end_words
        )
        mushaf_marks = len(mark_positions)
        coverage_score = round(marks_covered / mushaf_marks * 100) if mushaf_marks > 0 else 100

        matches[ver] = {
            'matched': matched,
            'total': pause_count,
            # No discretionary stops → precision is vacuously satisfied (100%);
            # the frontend renders this case as "no optional stops".
            'score': round(matched / pause_count * 100) if pause_count > 0 else 100,
            'mushaf_marks': mushaf_marks,
            'marks_covered': marks_covered,
            'coverage_score': coverage_score,
        }

    return jsonify({'has_data': True, 'pause_count': pause_count, 'matches': matches})


@breathing_bp.route('/api/reciter-compare/<int:surah_number>/<int:ayah_number>', methods=['GET'])
def get_reciter_compare(surah_number, ayah_number):
    """Compare pause positions of one reciter against every other reciter with positions data.

    Returns for each other reciter:
      a_to_b: fraction of subject's mid-pauses that land within ±1 of other's pauses
      b_to_a: fraction of other's mid-pauses that land within ±1 of subject's pauses
    Verse-end stop is excluded (every reciter stops there — trivially 100%).
    """
    if not (1 <= surah_number <= 114) or ayah_number < 1:
        return jsonify({'error': 'invalid parameters'}), 400

    reciter = request.args.get('reciter', '').strip()
    subject_segs, has_db = _get_positions_segments(surah_number, ayah_number, reciter)
    if not has_db or not subject_segs:
        return jsonify({'has_data': False, 'comparisons': {}})

    subject_pauses = [s for s in subject_segs if not s.get('is_repeat')]
    if not subject_pauses:
        return jsonify({'has_data': False, 'comparisons': {}})

    verse_end_word = subject_pauses[-1]['end_word']
    # Mid-pause segments only (exclude رأس الآية — every reciter stops there)
    subject_mid_segs = [s for s in subject_pauses if s['end_word'] != verse_end_word]

    def _match_positions(a_list, b_list):
        """1-to-1 match of each position in a_list to a position in b_list within
        ±1 word. Each b-position can satisfy only ONE a-position, so adjacent
        stops can't be double-counted. Exact matches are claimed first (globally)
        so a ±1 neighbour never steals a b-position an exact match needs.
        Returns (matched_count, set_of_matched_a_positions)."""
        b_sorted = sorted(b_list)
        b_used = [False] * len(b_sorted)
        matched_a = set()
        a_sorted = sorted(a_list)
        remaining = []
        for w in a_sorted:  # pass 1: exact
            j = next((i for i, bw in enumerate(b_sorted) if not b_used[i] and bw == w), None)
            if j is not None:
                b_used[j] = True
                matched_a.add(w)
            else:
                remaining.append(w)
        for w in remaining:  # pass 2: ±1
            j = next((i for i, bw in enumerate(b_sorted) if not b_used[i] and abs(bw - w) <= 1), None)
            if j is not None:
                b_used[j] = True
                matched_a.add(w)
        return len(matched_a), matched_a

    comparisons = {}
    # Accumulate every other reciter's mid-verse pause positions so we can tell
    # which of the subject's stops are his alone (انفرد القارئ بهذا الوقف).
    other_mid_positions = set()
    other_reciter_count = 0
    for other_reciter, cfg in RECITER_GUIDE_CONFIG.items():
        if other_reciter == reciter:
            continue
        other_segs, other_has_db = _get_positions_segments(surah_number, ayah_number, other_reciter)
        if not other_has_db or not other_segs:
            continue
        other_pauses = [s for s in other_segs if not s.get('is_repeat')]
        if not other_pauses:
            continue
        other_verse_end = other_pauses[-1]['end_word']

        # Work with full segment objects so diff can show segment text
        a_segs = [s for s in subject_pauses if s['end_word'] != verse_end_word]
        b_segs = [s for s in other_pauses  if s['end_word'] != other_verse_end]
        a_list = [s['end_word'] for s in a_segs]
        b_list = [s['end_word'] for s in b_segs]
        a_total, b_total = len(a_list), len(b_list)

        other_reciter_count += 1
        other_mid_positions.update(b_list)

        a_matched, a_matched_set = _match_positions(a_list, b_list)
        b_matched, b_matched_set = _match_positions(b_list, a_list)
        # Empty side → fraction is vacuously 1.0 (nothing to disagree on); the
        # similarity below collapses to 0 via the harmonic mean, and the frontend
        # labels one-sided cases as "can't evaluate".
        a_frac = (a_matched / a_total) if a_total else 1.0
        b_frac = (b_matched / b_total) if b_total else 1.0

        # Unmatched segments for the diff view — same greedy matching as the score,
        # so the diff list length always agrees with (total - matched).
        only_in_a = [
            {'word_index': s['end_word'], 'start_word': s['start_word'], 'text': (s.get('text') or '').split('\xa0')[0].strip()}
            for s in a_segs
            if s['end_word'] not in a_matched_set
        ]
        only_in_b = [
            {'word_index': s['end_word'], 'start_word': s['start_word'], 'text': (s.get('text') or '').split('\xa0')[0].strip()}
            for s in b_segs
            if s['end_word'] not in b_matched_set
        ]

        comparisons[other_reciter] = {
            'a_to_b_score':   round(a_frac * 100),
            'a_to_b_matched': a_matched,
            'a_to_b_total':   a_total,
            'b_to_a_score':   round(b_frac * 100),
            'b_to_a_matched': b_matched,
            'b_to_a_total':   b_total,
            # Combined similarity: harmonic mean (F1) of the two directions.
            # Only meaningful when both reciters have mid-verse stops.
            'comparable': a_total > 0 and b_total > 0,
            'similarity': round(
                2 * a_frac * b_frac / (a_frac + b_frac) * 100
                if (a_frac + b_frac) > 0 else 0
            ),
            'diff': {'only_in_a': only_in_a, 'only_in_b': only_in_b},
        }

    # ── Solo waqfs ───────────────────────────────────────────────────────────
    # Positions where the subject stopped but NO other reciter did (within ±1).
    # Only clean stop-and-continue waqfs qualify: mid-verse, the segment itself did
    # not back up, and the reciter resumed forward from the stop (no repetition).
    unique_pauses = []
    if other_reciter_count > 0:
        high_water = 0
        for k, seg in enumerate(subject_pauses):
            end_w = seg['end_word']
            backed_up = seg['start_word'] < high_water
            if end_w > high_water:
                high_water = end_w
            if end_w == verse_end_word or backed_up:
                continue
            nxt = subject_pauses[k + 1] if k + 1 < len(subject_pauses) else None
            if nxt is None or nxt['start_word'] < end_w:
                continue  # reciter backed up after this stop → it was repeated
            if not any((end_w + d) in other_mid_positions for d in (-1, 0, 1)):
                unique_pauses.append(end_w)

    return jsonify({
        'has_data': bool(comparisons),
        'subject_mid_count': len(subject_mid_segs),
        'other_reciter_count': other_reciter_count,
        'unique_pauses': unique_pauses,
        'comparisons': comparisons,
    })


def _verse_word_texts(verse_key):
    """Per-word text for a verse, aligned to the QUL/reciter word indices
    (words[i] = recited word i+1).

    Uses the qpc_hafs (Uthmanic) text. `text.split()` also yields NON-word
    tokens — the trailing ayah number and ornaments such as the rub‑el‑hizb ۞ —
    which the reciters do NOT count as words, so they must be dropped or the
    reciter stops shift out of alignment with the mushaf marks (e.g. 2:26).

    Returns (text, words, raw_to_wpos) where raw_to_wpos[i] maps a raw split
    index (the basis the printed-mushaf waqf DB token_index uses, which DOES
    count ornaments) to the stripped word index, or None for a dropped token."""
    td = qpc_hafs_data_normalized.get(verse_key)
    text = (td.get('text', '') if isinstance(td, dict) else '') or ''
    words, raw_to_wpos = [], []
    for tok in text.split():
        if _has_arabic_letter(tok):
            raw_to_wpos.append(len(words))
            words.append(tok)
        else:
            raw_to_wpos.append(None)
    return text, words, raw_to_wpos


def _mark_word_context(verse_key, token_index, span=2):
    """Map a printed-mushaf 1-based DB token_index to the recited-word position
    and a small surrounding context snippet, the way the per-verse comparison
    view does it.

    The waqf DB's token_index is 1-based and COUNTS ornaments (rub‑el‑hizb, the
    ayah-end marker), whereas `_verse_word_texts` drops those — so the index must
    be mapped through raw_to_wpos rather than used directly as a word index, or
    the context lands a word or two past the actual mark. Returns (wpos, context)
    where wpos is the 0-based recited-word index (or None if it can't be mapped).
    """
    _, words, raw_to_wpos = _verse_word_texts(verse_key)
    if not words:
        return None, ''
    wpos = None
    if token_index is not None and 0 <= token_index - 1 < len(raw_to_wpos):
        wpos = raw_to_wpos[token_index - 1]
    if wpos is None:
        # Token mapped to a dropped ornament or fell out of range — clamp the
        # raw index into the recited-word range so context is still sensible.
        ti0 = (token_index - 1) if token_index else 0
        wpos = min(max(ti0, 0), len(words) - 1)
    lo, hi = max(0, wpos - span), min(len(words), wpos + span + 1)
    return wpos, ' '.join(words[lo:hi])


def _build_verse_waqf_detail(surah, ayah):
    """Full per-reciter waqf detail for ONE verse, for the comparison page.

    Returns the verse text/words plus, for every installed reciter, their own
    forward-waqf stops (with each reciter's cumulative time) and repeats, and a
    union view (which reciters align at each stop, and which stops are solo)."""
    reciter_ids = sorted(rid for rid in MEMORIZATION_RECITERS if _memo_reciter_installed(rid))
    vk = f"{surah}:{ayah}"
    text, words, raw_to_wpos = _verse_word_texts(vk)

    raw = {}
    verse_durs = []
    for rid in reciter_ids:
        try:
            wts = _load_memorization_word_ts(rid)
        except Exception:
            continue
        if vk not in wts:
            continue
        w = wts[vk][1]
        if not w:
            continue
        full = (w[-1][2] - w[0][1]) / 1000.0
        verse_durs.append(full)
        stops, repeats = _forward_waqf_stops(w, _WAQF_CONSENSUS_GAP_MS)
        raw[rid] = {'w': w, 'stops': stops, 'repeats': repeats, 'full': full}

    per_reciter = {}
    union = defaultdict(lambda: {'reciters': [], 'durs': []})
    for rid, info in raw.items():
        w, stops, repeats = info['w'], info['stops'], info['repeats']
        cfg = MEMORIZATION_RECITERS[rid]
        vstart = w[0][1]
        # The reciter's actual recited phrases IN ORDER (incl. back-ups where
        # they paused then re-read). Lets the UI render each phrase — repeats
        # included — as its own card, faithfully and in recitation order.
        phrases = [
            {'first_wpos': ph['first_word'] - 1, 'last_wpos': ph['last_word'] - 1,
             'start': round((ph['start'] - vstart) / 1000.0, 2),
             'end': round((ph['end'] - vstart) / 1000.0, 2)}
            for ph in _segment_phrases(w, _WAQF_CONSENSUS_GAP_MS)
        ]
        per_reciter[rid] = {
            'name_ar': cfg.get('name_ar', ''),
            'stops': [{'wpos': k - 1, 'time': round(v / 1000.0, 2)} for k, v in sorted(stops.items())],
            'repeats': [{'from_wpos': f - 1, 'to_wpos': t - 1} for f, t in repeats],
            'phrases': phrases,
            'duration': round(info['full'], 2),
            # absolute seek info for in-page segment playback.
            # _yt_ reciters return their per-surah YouTube watch URL; the waqf
            # guide player routes youtube.com URLs through the IFrame adapter
            # (same as the memorize page) instead of a native <audio> element.
            # Catalog-based reciters (_gd_) use direct MP3/Drive-download URLs
            # which native <audio> can stream fine.
            'audio_url': (_gd_audio_url(rid, surah)
                          if cfg.get('audio_tmpl') == '_gd_'
                          else (_yt_audio_url(rid, surah)
                                if cfg.get('audio_tmpl') == '_yt_'
                                else (cfg['audio_tmpl'].format(surah=surah)
                                      if cfg.get('audio_tmpl') else None))),
            'verse_start': round(w[0][1] / 1000.0, 3),
        }
        for k, v in stops.items():
            union[k - 1]['reciters'].append(rid)
            union[k - 1]['durs'].append(v / 1000.0)

    union_stops = []
    for wpos in sorted(union):
        u = union[wpos]
        union_stops.append({
            'wpos': wpos,
            'reciters': u['reciters'],
            'count': len(u['reciters']),
            'solo': len(u['reciters']) == 1,
            'avg_duration': round(sum(u['durs']) / len(u['durs']), 2),
        })

    # Reference timeline: a single reciter's cumulative time at EVERY word, so
    # the breath recommendation can size any chosen segment consistently (the
    # per-stop averages mix different reciters). Pick the cleanest reciter —
    # fewest repeats, then pace closest to the group average.
    ref_times, ref_full, ref_reciter = _reference_timeline(per_reciter, words, vk, verse_durs)

    # Mushaf waqf marks (المدينة / الأزهر / الشمرلي): the *prescribed* stops, so
    # we can compare how closely the reciters follow each printed mushaf.
    mushafs = []
    for ver in _WAQF_COMPARE_MUSHAFS:
        marks = []
        for r in get_mushaf_waqf_symbols(surah, ayah, ver):
            ti = r.get('token_index')   # 0-based in the raw-split basis (counts ornaments)
            if ti is None or not r.get('symbols') or not (0 <= ti < len(raw_to_wpos)):
                continue
            wpos = raw_to_wpos[ti]
            if wpos is not None:
                marks.append({'wpos': wpos, 'symbol': r['symbols']})
        if marks:
            mushafs.append({'id': ver, 'name': ver, 'marks': marks})

    # Build a broad mushaf-mark lookup (wpos -> {mushaf_id: symbol}) across EVERY
    # printed mushaf we have, so a reciter's solo stop can be validated against
    # any edition's printed waqf — not just the three shown in the matrix.
    mushaf_mark_by_wpos = {}
    for ver in _WAQF_MATCH_MUSHAFS:
        for r in get_mushaf_waqf_symbols(surah, ayah, ver):
            ti = r.get('token_index')
            if ti is None or not r.get('symbols') or not (0 <= ti < len(raw_to_wpos)):
                continue
            wpos = raw_to_wpos[ti]
            if wpos is None:
                continue
            mushaf_mark_by_wpos.setdefault(wpos, {})[ver] = r['symbols']

    # Enrich per_reciter with derived fields used by the waqf guide UI:
    #  solo_stops_detail – this reciter's mid-verse stops that NO other reciter
    #                      made (انفرد), each tagged with any printed mushaf that
    #                      prescribes a waqf there (validates the lone stop).
    #  qasr_munfasil     – known Hafs bi-qasr al-munfasil reciters (config), whose
    #                      shorter disconnected madd makes their pace faster.
    for rid, det in per_reciter.items():
        solo_detail = []
        for s in det.get('stops', []):
            wpos = s['wpos']
            u = next((u for u in union_stops if u['wpos'] == wpos), None)
            if u and u['solo']:
                mm = [{'mushaf': mid, 'symbol': sym}
                      for mid, sym in mushaf_mark_by_wpos.get(wpos, {}).items()]
                solo_detail.append({
                    'wpos': wpos,
                    'time': s['time'],
                    'word': words[wpos] if 0 <= wpos < len(words) else '',
                    'mushaf_matches': mm,
                })
        det['solo_stops_detail'] = solo_detail
        det['qasr_munfasil'] = rid in QASR_MUNFASIL_RECITERS

    return {
        'surah': surah,
        'ayah': ayah,
        'verse_key': vk,
        'text': text,
        'words': words,
        'reciters_total': len(per_reciter),
        'full_duration': round(sum(verse_durs) / len(verse_durs), 2) if verse_durs else None,
        'ref_times': ref_times,
        'ref_full': ref_full,
        'ref_reciter': ref_reciter,
        'reciters': [
            {'id': rid, 'name_ar': MEMORIZATION_RECITERS[rid].get('name_ar', '')}
            for rid in reciter_ids if rid in per_reciter
        ],
        'per_reciter': per_reciter,
        'union_stops': union_stops,
        'mushafs': mushafs,
    }


# Printed mushafs whose waqf marks we compare the reciters against (matrix view).
# ورش (North-African Warsh print) is included too — note its ص = صه = STOP, the
# opposite of the Hafs صلى; the agreement analysis handles that per-mushaf.
_WAQF_COMPARE_MUSHAFS = ('المدينة الجديد', 'المدينة القديم', 'الأزهر', 'الشمرلي', 'قطر', 'الكويت', 'ورش')
# Broader set used only to validate a reciter's *solo* stop against any printed
# waqf (e.g. "انفرد القارئ، لكنه يوافق علامة الأزهر").
_WAQF_MATCH_MUSHAFS = ('المدينة الجديد', 'المدينة القديم', 'الأزهر', 'الشمرلي', 'ورش', 'الهندي', 'قطر', 'الكويت')
# Reciters known to recite Hafs bi-qasr al-munfasil (short disconnected madd) —
# their pace is legitimately faster, surfaced as a badge so the timing reads
# correctly. Keyed by MEMORIZATION_RECITERS id.
QASR_MUNFASIL_RECITERS = {'banna', 'ahmed_amer', 'maasaraawi', 'burhaji', 'shaheen', 'mustafa_ismail'}


def _reference_timeline(per_reciter, words, vk, verse_durs):
    """Cumulative seconds to the end of each word for one representative
    reciter, used to size breath segments consistently. Returns
    (ref_times[wpos], ref_full_seconds, reciter_id)."""
    if not per_reciter or not words:
        return None, None, None
    avg = (sum(verse_durs) / len(verse_durs)) if verse_durs else 0
    # rank: fewest repeats first, then closest pace to the average
    ranked = sorted(
        per_reciter.keys(),
        key=lambda rid: (len(per_reciter[rid]['repeats']), abs(per_reciter[rid]['duration'] - avg)),
    )
    ref_rid = ranked[0]
    try:
        w = _load_memorization_word_ts(ref_rid)[vk][1]
    except Exception:
        return None, None, None
    vstart = w[0][1]
    times = [None] * len(words)
    for idx, _s, e in w:                       # first (forward) occurrence per word
        i = idx - 1
        if 0 <= i < len(times) and times[i] is None:
            times[i] = round((e - vstart) / 1000.0, 2)
    # fill any gaps (shouldn't happen) by carrying the previous value forward
    last = 0.0
    for i in range(len(times)):
        if times[i] is None:
            times[i] = last
        else:
            last = times[i]
    return times, times[-1] if times else None, ref_rid


@breathing_bp.route('/api/waqf/<int:surah>/<int:ayah>', methods=['GET'])
def get_verse_waqf(surah, ayah):
    """Per-verse reciter-waqf comparison: how each installed reciter stops in
    this verse, who aligns vs. who is alone (انفرد), and where they repeat."""
    if not (1 <= surah <= 114) or ayah < 1:
        return jsonify({"error": "Invalid verse."}), 400
    try:
        data = _build_verse_waqf_detail(surah, ayah)
    except Exception as e:
        logger.error(f"Waqf detail failed for {surah}:{ayah}: {e}")
        return jsonify({"error": "Waqf data unavailable"}), 503
    if not data['per_reciter']:
        return jsonify({"error": "No data for this verse."}), 404
    return jsonify(data)


_CLASSICAL_SOURCES = {
    'muktafa': {
        'name': 'الداني',
        'title': 'المكتفى في الوقف والابتدا',
        'author': 'أبو عمرو عثمان بن سعيد الداني (ت 444هـ)',
        'edition': 'تحقيق محيي الدين عبد الرحمن رمضان، دار عمار، ط1 1422هـ/2001م',
        'via': 'OpenITI (Shamela 0026461)',
    },
    'manar': {
        'name': 'الأشموني',
        'title': 'منار الهدى في بيان الوقف والابتدا',
        'author': 'أحمد بن محمد بن عبد الكريم الأشموني (ق 11هـ)',
        'edition': 'ضبط شريف أبو العلا العدوي، دار الكتب العلمية',
        'via': 'OpenITI (Shamela 0006496)',
    },
    'nahhas': {
        'name': 'النحاس',
        'title': 'القطع والائتناف',
        'author': 'أبو جعفر أحمد بن محمد النحاس (ت 338هـ)',
        'edition': 'تحقيق عبد الرحمن بن إبراهيم المطرودي، دار عالم الكتب، ط1 1413هـ/1992م',
        'via': 'OpenITI (Shamela 0020966)',
    },
    'anbari': {
        'name': 'ابن الأنباري',
        'title': 'إيضاح الوقف والابتداء',
        'author': 'أبو بكر محمد بن القاسم الأنباري (ت 328هـ)',
        'edition': 'تحقيق محيي الدين عبد الرحمن رمضان، مجمع اللغة العربية بدمشق',
        'via': 'OpenITI (Shamela 0014255)',
    },
}


@breathing_bp.route('/api/classical-waqf/<int:surah>/<int:ayah>', methods=['GET'])
def classical_waqf(surah, ayah):
    """Classical graded stops (الداني's المكتفى + الأشموني's منار الهدى) for one
    verse, aligned to recited-word positions by pipeline/build_classical_waqf.py.
    Only high-confidence alignments are returned — comparative citations the
    books quote from elsewhere stay in the DB flagged conf=0."""
    if not (1 <= surah <= 114) or ayah < 1:
        return jsonify({'error': 'invalid verse'}), 400
    entries = []
    if os.path.exists(CLASSICAL_WAQF_DATABASE):
        conn = sqlite3.connect(CLASSICAL_WAQF_DATABASE)
        try:
            conn.row_factory = sqlite3.Row
            for r in conn.execute(
                    'SELECT source, wpos, stop_word, quote, grade, grade_raw, note, reported_from '
                    'FROM classical WHERE surah=? AND ayah=? AND conf=1 '
                    'ORDER BY wpos, source, seq', (surah, ayah)):
                entries.append({
                    'source': r['source'],
                    'wpos': r['wpos'], 'stop_word': r['stop_word'],
                    'quote': r['quote'], 'grade': r['grade'],
                    'grade_raw': r['grade_raw'], 'note': r['note'] or '',
                    # When set, this grade is the book RELAYING a named
                    # scholar's ruling («وقال ابن الأنباري: {…} تام»), not
                    # necessarily the book's own author's settled view —
                    # must not be displayed as a flat "SOURCE: grade".
                    'reported_from': r['reported_from'],
                })
        finally:
            conn.close()
    return jsonify({'surah': surah, 'ayah': ayah, 'sources': _CLASSICAL_SOURCES,
                    'count': len(entries), 'entries': entries})


@breathing_bp.route('/waqf')
def waqf_guide():
    return render_template('waqf_guide.html', enable_vercel_analytics=_IS_SERVERLESS)


# ── تدريب الوقف (waqf practice + grading) ──────────────────────────────────────
# Grade WHERE a memoriser chose to stop against the printed mushaf marks and the
# classical rulings (الداني + الأشموني). No audio/ASR — the learner marks their
# own stops; this scores them and explains each one. The stop verdicts, best
# (most encouraging) first:
_PRACTICE_RANK = {'excellent': 5, 'good': 4, 'ok': 3, 'unmarked': 2, 'caution': 1, 'error': 0}
# «ok» verdicts are PERMITTED-but-not-endorsed (ص صلى = continuing is better,
# س sakta) — they tolerate a stop but do NOT rescue a spot another authority
# forbids. Only strong verdicts (excellent/good) are real endorsements.
_STRONG = ('excellent', 'good')
# Printed-mushaf symbol → (verdict, label) for stopping THERE.
_MARK_STOP_VERDICT = {
    'م':  ('excellent', 'وقف لازم'),
    'ق':  ('good',      'الوقف أولى (قلى)'),
    'ص':  ('ok',        'الوصل أولى (صلى)'),
    'ج':  ('good',      'وقف جائز'),
    'لا': ('error',     'لا وقف — لا يُوقف عليه'),
    'ع':  ('good',      'وقف المعانقة'),
    'س':  ('ok',        'سكتة — بلا تنفّس'),
}
# Classical grade → (verdict, label).
_CLASSICAL_STOP_VERDICT = {
    'تام':  ('excellent', 'وقف تام'),
    'كاف':  ('good',      'وقف كافٍ'),
    'حسن':  ('ok',        'وقف حسن'),
    'جائز': ('good',      'وقف جائز'),
    'صالح': ('ok',        'وقف صالح'),
    'قبيح': ('error',     'وقف قبيح'),
    'لا':   ('error',     'ليس بوقف'),
}
_CLASSICAL_NAME = {'muktafa': 'الداني', 'manar': 'الأشموني', 'nahhas': 'النحاس',
                   'anbari': 'ابن الأنباري'}


def _mushaf_marks_by_wpos(surah, ayah, mushaf, raw_to_wpos):
    """{wpos: canonical_symbol} for one printed mushaf at one verse. Takes the
    verse's raw_to_wpos so the caller's _verse_word_texts result is reused."""
    out = {}
    for r in get_mushaf_waqf_symbols(surah, ayah, mushaf):
        ti = r.get('token_index')
        if ti is None or not r.get('symbols') or not (0 <= ti < len(raw_to_wpos)):
            continue
        wpos = raw_to_wpos[ti]
        if wpos is not None:
            out[wpos] = str(r['symbols']).split(',')[0].strip()
    return out


def _classical_grades_for_range(surah, from_ayah, to_ayah):
    """{(ayah, wpos): [{'source','name','grade'}]} for a verse range in ONE
    query/connection (the practice grader walks a whole passage)."""
    out = defaultdict(list)
    if os.path.exists(CLASSICAL_WAQF_DATABASE):
        conn = _sqlite_connect(CLASSICAL_WAQF_DATABASE)
        try:
            conn.row_factory = sqlite3.Row
            for r in conn.execute(
                    'SELECT ayah, source, wpos, grade FROM classical '
                    'WHERE surah=? AND ayah BETWEEN ? AND ? AND conf=1 AND wpos IS NOT NULL',
                    (surah, from_ayah, to_ayah)):
                out[(r['ayah'], r['wpos'])].append({
                    'source': r['source'],
                    'name': _CLASSICAL_NAME.get(r['source'], r['source']),
                    'grade': r['grade']})
        finally:
            conn.close()
    return out


def _grade_one_stop(mushaf_sym, classical, is_verse_end):
    """Classify a stop at a word given its rulings. Returns (verdict, label,
    sources[]). رأس آية is always a permitted stop (سنة). The chosen mushaf's
    «لا» forbids outright. Otherwise: a real endorsement (تام/كاف/م/ق…) stands;
    a forbid (قبيح/ليس بوقف) with only weak toleration (ص/سكتة) is a خلاف
    (caution), and with none is an error."""
    sources, verdicts = [], []
    if mushaf_sym in _MARK_STOP_VERDICT:
        v, lbl = _MARK_STOP_VERDICT[mushaf_sym]
        sources.append({'kind': 'mushaf', 'label': lbl, 'verdict': v})
        verdicts.append(v)
    for c in classical:
        v, lbl = _CLASSICAL_STOP_VERDICT.get(c['grade'], ('ok', c['grade']))
        sources.append({'kind': 'classical', 'name': c['name'], 'label': lbl, 'verdict': v})
        verdicts.append(v)
    if is_verse_end:
        verdicts.append('good')
        if not sources:
            sources.append({'kind': 'verse_end', 'label': 'رأس آية', 'verdict': 'good'})
    if mushaf_sym == 'لا' and not is_verse_end:
        return 'error', 'لا وقف — لا يُوقف عليه', sources

    strong = [v for v in verdicts if v in _STRONG]
    weak = [v for v in verdicts if v == 'ok']
    has_error = 'error' in verdicts
    if strong:
        return max(strong, key=lambda v: _PRACTICE_RANK[v]), None, sources
    if has_error:
        if weak:
            return 'caution', 'موضع خلاف — أجازه بعضهم ومنعه آخرون', sources
        return 'error', None, sources
    if weak:
        return 'ok', None, sources
    return 'unmarked', 'ليس موضعَ وقفٍ منصوصًا عليه', sources


def _grade_waqf_practice(surah, from_ayah, to_ayah, mushaf, stops):
    stop_set = {(s['ayah'], s['wpos']) for s in stops}
    graded, broken_lazim, ideal = [], [], []
    counts = {'excellent': 0, 'good': 0, 'ok': 0, 'unmarked': 0, 'caution': 0, 'error': 0}

    classical_all = _classical_grades_for_range(surah, from_ayah, to_ayah)
    for ayah in range(from_ayah, to_ayah + 1):
        vk = f'{surah}:{ayah}'
        if vk not in qpc_hafs_data_normalized:
            continue
        _, words, raw_to_wpos = _verse_word_texts(vk)
        if not words:
            continue
        last = len(words) - 1
        marks = _mushaf_marks_by_wpos(surah, ayah, mushaf, raw_to_wpos)

        for wpos in range(len(words)):
            here = (ayah, wpos)
            sym = marks.get(wpos, '')
            cls = classical_all.get((ayah, wpos), [])
            is_end = wpos == last
            if here in stop_set:
                verdict, label, sources = _grade_one_stop(sym, cls, is_end)
                counts[verdict] += 1
                graded.append({'ayah': ayah, 'wpos': wpos, 'word': words[wpos],
                               'verdict': verdict, 'label': label, 'sources': sources})
            else:
                # مواضع فاتها: broken لازم (error) and ideal تام the learner ran past.
                if sym == 'م':
                    broken_lazim.append({'ayah': ayah, 'wpos': wpos, 'word': words[wpos]})
                elif not is_end and (sym in ('ق',) or any(c['grade'] == 'تام' for c in cls)):
                    ideal.append({'ayah': ayah, 'wpos': wpos, 'word': words[wpos]})

    errors = counts['error'] + len(broken_lazim)
    score = max(0, 100 - errors * 15 - counts['caution'] * 7 - counts['unmarked'] * 4)
    return {
        'surah': surah, 'from_ayah': from_ayah, 'to_ayah': to_ayah, 'mushaf': mushaf,
        'score': score,
        'summary': {'good': counts['excellent'] + counts['good'] + counts['ok'],
                    'notes': counts['unmarked'] + counts['caution'], 'errors': errors},
        'counts': counts,
        'stops': graded,
        'broken_lazim': broken_lazim,
        'ideal': ideal[:12],
    }


@breathing_bp.route('/api/waqf-practice/passage/<int:surah>/<int:from_ayah>/<int:to_ayah>')
def waqf_practice_passage(surah, from_ayah, to_ayah):
    """Word lists for a range, for the practice UI to render as tappable words."""
    if not (1 <= surah <= 114) or from_ayah < 1 or to_ayah < from_ayah:
        return jsonify({'error': 'invalid range'}), 400
    if to_ayah - from_ayah > 20:
        return jsonify({'error': 'range too large (max 21 verses)'}), 400
    verses = []
    for ayah in range(from_ayah, to_ayah + 1):
        vk = f'{surah}:{ayah}'
        if vk not in qpc_hafs_data_normalized:
            break
        _, words, _ = _verse_word_texts(vk)
        if words:
            verses.append({'ayah': ayah, 'words': words})
    return jsonify({'surah': surah, 'verses': verses})


# ── phoneme reference (zipformer recite-follow) ────────────────────────────
_QURAN_PHONEMES = None
_PH_KEEP = set('ءابتثجحخدذرزسشصضطظعغفقكلمنهوي')

def _load_quran_phonemes():
    """Lazy-load surah:ayah → {aya_phonemes_list} (ReciteQuran ordered set)."""
    global _QURAN_PHONEMES
    if _QURAN_PHONEMES is None:
        try:
            with open(QURAN_PHONEMES_JSON, encoding='utf-8') as fh:
                _QURAN_PHONEMES = json.load(fh)
        except Exception:
            _QURAN_PHONEMES = {}
    return _QURAN_PHONEMES

def _ph_skel(s):
    """Consonant skeleton (drop vowels/diacritics/alef, collapse repeats) for
    aligning phoneme entries to words regardless of orthography."""
    out = []
    for c in (s or '').replace('ٱ', 'ا').replace('أ', 'ا').replace('إ', 'ا').replace('آ', 'ا').replace('ة', 'ه').replace('ى', 'ي'):
        if c in _PH_KEEP and (not out or out[-1] != c):
            out.append(c)
    return ''.join(out)

def _edit_dist(a, b):
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i in range(1, len(a) + 1):
        cur = [i] + [0] * len(b)
        for j in range(1, len(b) + 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (a[i - 1] != b[j - 1]))
        prev = cur
    return prev[len(b)]

def _align_entries_to_words(entries, words):
    """DP-tile N phoneme entries over M words (each entry → a contiguous word
    group; idghaam/waṣl merges two words into one entry). Returns, per entry,
    the index of the LAST word it covers — where a stop after it is attributed."""
    N, M = len(entries), len(words)
    if N == 0 or M == 0:
        return []
    if N == M:
        return list(range(N))
    es = [_ph_skel(e) for e in entries]
    ws = [_ph_skel(w) for w in words]
    INF = float('inf')
    dp = [[INF] * (M + 1) for _ in range(N + 1)]
    bk = [[0] * (M + 1) for _ in range(N + 1)]
    dp[0][0] = 0
    for i in range(1, N + 1):
        for j in range(i, M - (N - i) + 1):          # each entry ≥ 1 word
            for a in range(i - 1, j):
                c = dp[i - 1][a] + _edit_dist(es[i - 1], ''.join(ws[a:j]))
                if c < dp[i][j]:
                    dp[i][j] = c
                    bk[i][j] = a
    res = [0] * N
    j = M
    for i in range(N, 0, -1):
        res[i - 1] = j - 1
        j = bk[i][j]
    return res


@breathing_bp.route('/api/waqf-practice/phonemes/<int:surah>/<int:from_ayah>/<int:to_ayah>')
def waqf_practice_phonemes(surah, from_ayah, to_ayah):
    """Reference phoneme entries for a range, each tagged with the (ayah, wpos)
    of the word it ends on — the zipformer glue DP-aligns the recited phoneme
    stream to these to follow position and attribute stops."""
    if not (1 <= surah <= 114) or from_ayah < 1 or to_ayah < from_ayah or to_ayah - from_ayah > 20:
        return jsonify({'error': 'invalid range'}), 400
    ph = _load_quran_phonemes()
    entries = []
    for ayah in range(from_ayah, to_ayah + 1):
        vk = f'{surah}:{ayah}'
        if vk not in qpc_hafs_data_normalized:
            break
        _, words, _ = _verse_word_texts(vk)
        rec = ph.get(vk)
        if not words or not rec:
            continue
        plist = rec.get('aya_phonemes_list') or []
        ends = _align_entries_to_words(plist, words)
        for i, p in enumerate(plist):
            entries.append({'ph': p, 'ayah': ayah, 'wpos': ends[i] if i < len(ends) else len(words) - 1})
    return jsonify({'surah': surah, 'entries': entries})


# ── tajweed error detection (obadx/quran-transcript) ───────────────────────
_QT_MOSHAF = None

def _qt_moshaf():
    """Standard Ḥafṣ moshaf attributes (madd lengths matching the reference
    phonetization). Lazy so quran_transcript is only imported on demand."""
    global _QT_MOSHAF
    if _QT_MOSHAF is None:
        import quran_transcript as qt
        _QT_MOSHAF = qt.MoshafAttributes(
            rewaya='hafs', madd_monfasel_len=4, madd_mottasel_len=4,
            madd_mottasel_waqf=4, madd_aared_len=4)
    return _QT_MOSHAF


def _split_predicted_by_verse(predicted, verse_refs):
    """Split the full recited phoneme string into per-verse segments by char-level
    alignment (Needleman-Wunsch) to the concatenated reference — precise at the
    verse boundaries where a per-entry skeleton split leaks a letter."""
    ref = ''.join(r for _, r in verse_refs)
    vtag = []
    for vi, (_, r) in enumerate(verse_refs):
        vtag.extend([vi] * len(r))
    m, n = len(predicted), len(ref)
    if not m or not n:
        return [''] * len(verse_refs)
    prev = list(range(n + 1))
    back = [[0] * (n + 1) for _ in range(m + 1)]   # 0=diag 1=up(del pred) 2=left(ins ref)
    for j in range(n + 1):
        back[0][j] = 2
    for i in range(1, m + 1):
        cur = [i] + [0] * n
        back[i][0] = 1
        pi = predicted[i - 1]
        for j in range(1, n + 1):
            diag = prev[j - 1] + (0 if pi == ref[j - 1] else 1)
            up = prev[j] + 1
            left = cur[j - 1] + 1
            best = diag; b = 0
            if up < best:
                best = up; b = 1
            if left < best:
                best = left; b = 2
            cur[j] = best; back[i][j] = b
        prev = cur
    # backtrace: assign each predicted char to the verse of its aligned ref char
    segs = [''] * len(verse_refs)
    i, j = m, n
    while i > 0 or j > 0:
        b = back[i][j]
        if i > 0 and (j == 0 or b == 1):        # predicted char with no ref → nearest verse
            vi = vtag[j - 1] if j > 0 else 0
            segs[vi] = predicted[i - 1] + segs[vi]
            i -= 1
        elif j > 0 and (i == 0 or b == 2):      # ref char, no predicted
            j -= 1
        else:
            segs[vtag[j - 1]] = predicted[i - 1] + segs[vtag[j - 1]]
            i -= 1; j -= 1
    return segs


@breathing_bp.route('/api/waqf-practice/tajweed', methods=['POST'])
def waqf_practice_tajweed():
    """Detect tajweed/pronunciation errors: split the recited phoneme stream per
    verse, phonetize each reference (quran_transcript) and diff against it —
    returning rule-named errors (Madd length, Qalqalah, Ghonnah, wrong letter…)
    mapped to the word (wpos) they occur on."""
    try:
        import quran_transcript as qt
    except Exception:
        return jsonify({'available': False, 'errors': []})
    data = request.get_json(silent=True) or {}
    surah = int(data.get('surah') or 0)
    from_ayah = int(data.get('from_ayah') or 0)
    to_ayah = int(data.get('to_ayah') or 0)
    predicted = (data.get('phonemes') or '').strip()
    if not (1 <= surah <= 114) or from_ayah < 1 or to_ayah < from_ayah or to_ayah - from_ayah > 20:
        return jsonify({'error': 'invalid range'}), 400
    if not predicted:
        return jsonify({'available': True, 'errors': []})
    moshaf = _qt_moshaf()

    def rule_names(rules):
        out = []
        for r in (rules or []):
            nm = getattr(r, 'name', None)
            out.append(getattr(nm, 'ar', None) or getattr(nm, 'en', None) or str(nm))
        return out

    # phonetize each verse's reference, then split the recited stream to match
    verse_refs = []                              # (ayah, ut, ref_out)
    for ayah in range(from_ayah, to_ayah + 1):
        try:
            ut = qt.Aya(surah, ayah).get().uthmani
            ref = qt.quran_phonetizer(ut, moshaf)
        except Exception:
            continue
        verse_refs.append((ayah, ut, ref))
    if not verse_refs:
        return jsonify({'available': True, 'errors': []})
    segs = _split_predicted_by_verse(predicted, [(a, r.phonemes) for a, _, r in verse_refs])

    errors = []
    for (ayah, ut, ref), pred in zip(verse_refs, segs):
        pred = (pred or '').strip()
        if not pred:
            continue
        try:
            errs = qt.explain_error(ut, ref.phonemes, pred, ref.mappings)
        except Exception:
            continue
        nwords = ut.count(' ') + 1
        for e in errs:
            try:
                wpos = min(ut[:e.uthmani_pos[0]].count(' '), nwords - 1)
            except Exception:
                wpos = 0
            rules = rule_names(getattr(e, 'ref_tajweed_rules', None)) or \
                rule_names(getattr(e, 'missing_tajweed_rules', None)) or \
                rule_names(getattr(e, 'replaced_tajweed_rules', None))
            errors.append({
                'ayah': ayah, 'wpos': wpos,
                'type': e.error_type, 'op': e.speech_error_type,
                'expected': e.expected_ph, 'got': e.preditected_ph,
                'exp_len': e.expected_len, 'got_len': e.predicted_len,
                'rules': rules,
            })
    return jsonify({'available': True, 'errors': errors})


@breathing_bp.route('/api/waqf-practice/grade', methods=['POST'])
def waqf_practice_grade():
    """Grade the learner's chosen stops against the mushaf + classical rulings."""
    data = request.get_json(silent=True) or {}
    try:
        surah = int(data.get('surah'))
        from_ayah = int(data.get('from_ayah'))
        to_ayah = int(data.get('to_ayah'))
    except (TypeError, ValueError):
        return jsonify({'error': 'surah/from_ayah/to_ayah required'}), 400
    if not (1 <= surah <= 114) or from_ayah < 1 or to_ayah < from_ayah or to_ayah - from_ayah > 20:
        return jsonify({'error': 'invalid range'}), 400
    mushaf = data.get('mushaf') or 'المدينة الجديد'
    if not _is_valid_mushaf_version(mushaf):
        mushaf = 'المدينة الجديد'
    stops = []
    for s in (data.get('stops') or []):
        try:
            stops.append({'ayah': int(s['ayah']), 'wpos': int(s['wpos'])})
        except (TypeError, ValueError, KeyError):
            continue
    return jsonify(_grade_waqf_practice(surah, from_ayah, to_ayah, mushaf, stops))


@breathing_bp.route('/waqf-practice')
def waqf_practice_page():
    return render_template('waqf_practice.html', enable_vercel_analytics=_IS_SERVERLESS)


