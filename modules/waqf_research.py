"""مُكْث research tools: the Quran-wide /api/waqf-research/* analytical
endpoints — solo stops, reciter-divergence stats, mandatory/certain waqf
positions, cross-verse patterns, reciter clustering, mushaf-vs-mushaf
similarity/diff, الابتداء candidates, السكتات reference, and reciter-vs-
mushaf agreement. Same breathing_bp blueprint as modules/breathing.py
(the pause guide, classical waqf books, and waqf-practice grader), split
into its own file since this family has its own cache directory and is
large enough to warrant it.
"""
import os
import sqlite3
from collections import defaultdict, Counter

from flask import jsonify, request

from core.blueprints import breathing_bp
from core.config import MUSHAF_WAQF_DATABASE, WAQF_SYMBOL_CHARS, _BASE_DIR
from core.text import _normalize_for_search
from core.mushaf_waqf import (
    get_mushaf_waqf_symbols,
    _get_mushaf_version_whitelist,
    _is_valid_mushaf_version,
)
from core.datasets import surahs_data, qpc_hafs_data_normalized
from core.loader import _json_load
from core.lru import _BoundedLRU
from core.memorization import (
    MEMORIZATION_RECITERS, _memo_reciter_installed, _build_breathing_guide,
    _WAQF_CONSENSUS_GAP_MS,
)
from modules.breathing import (
    _verse_word_texts, _mark_word_context,
    _WAQF_COMPARE_MUSHAFS, _WAQF_MATCH_MUSHAFS, QASR_MUNFASIL_RECITERS,
)

import logging
logger = logging.getLogger(__name__)


_solo_stops_index: dict | None = None


def _build_solo_stops_index():
    """Scan all 114 surahs and collect every reciter's solo stops.

    Returns {reciter_id: [{'surah', 'ayah', 'wpos', 'word', 'context', 'marks'}]}.
    Cached after first computation (data is static at runtime)."""
    global _solo_stops_index
    if _solo_stops_index is not None:
        return _solo_stops_index

    per_reciter = defaultdict(list)

    for surah in range(1, 115):
        guide = _build_breathing_guide(surah)
        for ayah_str, vdata in guide.get('verses', {}).items():
            ayah = int(ayah_str)
            vk = f"{surah}:{ayah}"
            _, words, raw_to_wpos = _verse_word_texts(vk)
            if not words:
                continue

            mushaf_marks = None
            for stop in vdata.get('stops', []):
                if not stop['solo'] or not stop.get('reciter_ids'):
                    continue
                rid = stop['reciter_ids'][0]
                wpos = stop['wpos']
                if not (0 <= wpos < len(words)):
                    continue

                if mushaf_marks is None:
                    mushaf_marks = {}
                    for ver in _WAQF_MATCH_MUSHAFS:
                        for r in get_mushaf_waqf_symbols(surah, ayah, ver):
                            ti = r.get('token_index')
                            if ti is None or not r.get('symbols') or not (0 <= ti < len(raw_to_wpos)):
                                continue
                            wp = raw_to_wpos[ti]
                            if wp is not None:
                                mushaf_marks.setdefault(wp, {})[ver] = r['symbols']

                lo, hi = max(0, wpos - 2), min(len(words), wpos + 3)
                per_reciter[rid].append({
                    'surah': surah, 'ayah': ayah, 'wpos': wpos,
                    'word': words[wpos],
                    'context': ' '.join(words[lo:hi]),
                    'marks': mushaf_marks.get(wpos, {}),
                    'has_waqf': bool(mushaf_marks.get(wpos)),
                })

    _solo_stops_index = dict(per_reciter)
    return _solo_stops_index


@breathing_bp.route('/api/waqf-research/solos', methods=['GET'])
def waqf_research_solos():
    """Solo stops (انفرادات) per reciter across the entire Quran.

    GET /api/waqf-research/solos           → summary (counts per reciter)
    GET /api/waqf-research/solos?reciter=X → full list for reciter X"""
    idx = _build_solo_stops_index()
    rid = request.args.get('reciter', '').strip()
    if rid:
        if rid not in MEMORIZATION_RECITERS:
            return jsonify({'error': 'unknown reciter'}), 400
        stops = idx.get(rid, [])
        return jsonify({
            'reciter': {'id': rid, 'name_ar': MEMORIZATION_RECITERS[rid].get('name_ar', '')},
            'count': len(stops),
            'stops': stops,
        })

    reciter_ids = sorted(rid for rid in MEMORIZATION_RECITERS if _memo_reciter_installed(rid))
    return jsonify({
        'reciters': [
            {'id': r, 'name_ar': MEMORIZATION_RECITERS[r].get('name_ar', ''),
             'solo_count': len(idx.get(r, []))}
            for r in reciter_ids
        ],
    })


_waqf_stats_cache: dict | None = None


def _build_waqf_stats():
    """Per-surah reciter-divergence stats + top consensus positions."""
    global _waqf_stats_cache
    if _waqf_stats_cache is not None:
        return _waqf_stats_cache

    surah_names = {s['number']: s['name'] for s in surahs_data} if surahs_data else {}
    surahs_out = []
    top_divergent = []
    top_consensus = []

    for surah in range(1, 115):
        guide = _build_breathing_guide(surah)
        s_cons, s_div, s_total = 0, 0, 0

        for ayah_str, vdata in guide.get('verses', {}).items():
            ayah = int(ayah_str)
            rt = vdata.get('reciters_total', 0)
            if rt < 2:
                continue
            v_cons, v_div = 0, 0
            for stop in vdata.get('stops', []):
                s_total += 1
                if stop['reciters'] == rt:
                    v_cons += 1
                else:
                    v_div += 1
            s_cons += v_cons
            s_div += v_div
            if v_div > 0:
                top_divergent.append({'surah': surah, 'ayah': ayah,
                                      'divergent': v_div, 'consensus': v_cons,
                                      'total': v_cons + v_div})
            if v_cons > 0:
                vk = f"{surah}:{ayah}"
                _, words, raw_to_wpos = _verse_word_texts(vk)
                if not words:
                    continue
                mm_by_wpos = {}
                for ver in _WAQF_COMPARE_MUSHAFS:
                    for r in get_mushaf_waqf_symbols(surah, ayah, ver):
                        ti = r.get('token_index')
                        if ti is None or not r.get('symbols') or not (0 <= ti < len(raw_to_wpos)):
                            continue
                        wp = raw_to_wpos[ti]
                        if wp is not None:
                            mm_by_wpos.setdefault(wp, {})[ver] = r['symbols']
                for stop in vdata.get('stops', []):
                    if stop['reciters'] == rt:
                        wpos = stop['wpos']
                        mm = mm_by_wpos.get(wpos, {})
                        if mm:
                            lo, hi = max(0, wpos - 2), min(len(words), wpos + 3)
                            top_consensus.append({
                                'surah': surah, 'ayah': ayah, 'wpos': wpos,
                                'word': words[wpos] if 0 <= wpos < len(words) else '',
                                'context': ' '.join(words[lo:hi]),
                                'marks': mm, 'reciters': rt,
                            })

        surahs_out.append({
            'surah': surah, 'name': surah_names.get(surah, ''),
            'consensus': s_cons, 'divergent': s_div, 'total': s_total,
        })

    top_divergent.sort(key=lambda v: v['divergent'], reverse=True)
    top_consensus.sort(key=lambda v: v['reciters'], reverse=True)

    _waqf_stats_cache = {
        'surahs': surahs_out,
        'top_divergent': top_divergent[:80],
        'top_consensus': top_consensus,
    }
    return _waqf_stats_cache


@breathing_bp.route('/api/waqf-research/stats', methods=['GET'])
def waqf_research_stats():
    """Surah-level reciter divergence stats + consensus positions."""
    data = _build_waqf_stats()
    view = request.args.get('view', '').strip()
    if view == 'consensus':
        return jsonify({'consensus': data['top_consensus']})
    return jsonify({'surahs': data['surahs'], 'top_divergent': data['top_divergent']})


_mandatory_cache: dict | None = None


def _build_mandatory_index():
    """All م (mandatory) and لا (forbidden) waqf positions across all mushafs."""
    global _mandatory_cache
    if _mandatory_cache is not None:
        return _mandatory_cache

    versions = list(_WAQF_COMPARE_MUSHAFS)
    cols_sql = ', '.join(f'"{v}"' for v in versions)
    where_m = ' OR '.join(f'"{v}" = ?' for v in versions)

    conn = sqlite3.connect(MUSHAF_WAQF_DATABASE)
    try:
        cur = conn.cursor()
        mandatory, forbidden = [], []

        for symbol, target_list in [('م', mandatory), ('لا', forbidden)]:
            cur.execute(
                f'SELECT "السورة", "الآية", "الكلمة", token_index, {cols_sql} '
                f'FROM waqf WHERE {where_m} ORDER BY "السورة", "الآية", token_index',
                tuple(symbol for _ in versions)
            )
            for row in cur.fetchall():
                s, a, word, ti = row[0], row[1], row[2], row[3]
                marks = {}
                for i, ver in enumerate(versions):
                    val = row[4 + i]
                    if val:
                        marks[ver] = val
                vk = f"{s}:{a}"
                _, ctx = _mark_word_context(vk, ti)
                if not ctx:
                    ctx = word or ''
                all_same = len(set(marks.values())) == 1 and len(marks) == len(versions)
                target_list.append({
                    'surah': s, 'ayah': a, 'word': word or '', 'context': ctx,
                    'marks': marks, 'agreement': 'full' if all_same else 'partial',
                })

        # وقف المعانقة (ع) — embracing stop pairs.
        where_ain = ' OR '.join(f'"{v}" = ?' for v in versions)
        cur.execute(
            f'SELECT "السورة", "الآية", "الكلمة", token_index, {cols_sql} '
            f'FROM waqf WHERE {where_ain} ORDER BY "السورة", "الآية", token_index',
            tuple('ع' for _ in versions)
        )
        raw_ain = []
        for row in cur.fetchall():
            s, a, word, ti = row[0], row[1], row[2], row[3]
            marks = {}
            for i, ver in enumerate(versions):
                val = row[4 + i]
                if val:
                    marks[ver] = val
            vk = f"{s}:{a}"
            _, ctx = _mark_word_context(vk, ti)
            if not ctx:
                ctx = word or ''
            all_same = len(set(marks.values())) == 1 and len(marks) == len(versions)
            raw_ain.append({
                'surah': s, 'ayah': a, 'word': word or '', 'context': ctx,
                'marks': marks, 'agreement': 'full' if all_same else 'partial',
            })

        # Group ع marks into pairs (consecutive marks in the same verse).
        embracing = []
        i_ain = 0
        while i_ain < len(raw_ain):
            a1 = raw_ain[i_ain]
            if i_ain + 1 < len(raw_ain) and raw_ain[i_ain + 1]['surah'] == a1['surah'] and raw_ain[i_ain + 1]['ayah'] == a1['ayah']:
                a2 = raw_ain[i_ain + 1]
                vk = f"{a1['surah']}:{a1['ayah']}"
                _, words, _ = _verse_word_texts(vk)
                embracing.append({
                    'surah': a1['surah'], 'ayah': a1['ayah'],
                    'pair': [
                        {'word': a1['word'], 'context': a1['context'], 'marks': a1['marks']},
                        {'word': a2['word'], 'context': a2['context'], 'marks': a2['marks']},
                    ],
                    'agreement': 'full' if a1['agreement'] == 'full' and a2['agreement'] == 'full' else 'partial',
                })
                i_ain += 2
            else:
                embracing.append({
                    'surah': a1['surah'], 'ayah': a1['ayah'],
                    'pair': [{'word': a1['word'], 'context': a1['context'], 'marks': a1['marks']}],
                    'agreement': a1['agreement'],
                })
                i_ain += 1
    finally:
        conn.close()

    _mandatory_cache = {'mandatory': mandatory, 'forbidden': forbidden, 'embracing': embracing}
    return _mandatory_cache


@breathing_bp.route('/api/waqf-research/mandatory', methods=['GET'])
def waqf_research_mandatory():
    """All م (وقف لازم) and لا (وقف ممنوع) positions with mushaf agreement."""
    return jsonify(_build_mandatory_index())


_cross_verse_cache: dict | None = None


def _build_cross_verse_patterns():
    """Find mushaf marks where editions systematically disagree on the same word."""
    global _cross_verse_cache
    if _cross_verse_cache is not None:
        return _cross_verse_cache

    versions = list(_WAQF_COMPARE_MUSHAFS)
    cols_sql = ', '.join(f'"{v}"' for v in versions)

    conn = sqlite3.connect(MUSHAF_WAQF_DATABASE)
    try:
        cur = conn.cursor()
        cur.execute(
            f'SELECT "السورة", "الآية", "الكلمة", token_index, {cols_sql} FROM waqf '
            f'ORDER BY "السورة", "الآية", token_index'
        )
        # Track per-word-root how each mushaf marks it.
        # "Disagreement" = at least 2 mushafs give different non-empty symbols.
        disagree = []
        for row in cur.fetchall():
            s, a, word, ti = row[0], row[1], row[2], row[3]
            marks = {}
            for i, ver in enumerate(versions):
                val = row[4 + i]
                if val:
                    marks[ver] = val
            if len(marks) < 2:
                continue
            syms = set(marks.values())
            if len(syms) > 1:
                vk = f"{s}:{a}"
                _, ctx = _mark_word_context(vk, ti)
                if not ctx:
                    ctx = word or ''
                disagree.append({
                    'surah': s, 'ayah': a, 'word': word or '', 'context': ctx,
                    'marks': marks,
                })
    finally:
        conn.close()

    _cross_verse_cache = {'disagreements': disagree, 'count': len(disagree)}
    return _cross_verse_cache


@breathing_bp.route('/api/waqf-research/patterns', methods=['GET'])
def waqf_research_patterns():
    """Cross-verse mushaf disagreement patterns."""
    return jsonify(_build_cross_verse_patterns())


# ── Precomputed research caches ─────────────────────────────────────────────
# The Quran-wide analyses (clustering, similarity, agreement, ibtidaa) cost
# seconds of CPU on first request. pipeline/precompute_research.py bakes them
# to data/research_cache/*.json at build time; the builders below load the
# baked file when present and only compute as a fallback (or when the
# precompute script itself runs, signalled by RESEARCH_PRECOMPUTE=1).
_RESEARCH_CACHE_DIR = os.path.join(_BASE_DIR, 'data', 'research_cache')


def _load_research_cache(name):
    if os.environ.get('RESEARCH_PRECOMPUTE'):
        return None                       # precompute run: always compute fresh
    path = os.path.join(_RESEARCH_CACHE_DIR, f'{name}.json')
    if not os.path.exists(path):
        return None
    try:
        with open(path, 'rb') as f:
            return _json_load(f)
    except Exception as e:
        logger.warning(f'research cache {name} unreadable, recomputing: {e}')
        return None


_clustering_cache: dict | None = None


def _build_reciter_clustering():
    """Cluster reciters by how similar their waqf patterns are.

    For each pair of installed reciters, compute a similarity score based on
    how often they breathe at the same word across all verses.  Returns a
    ranked list of pairs (most similar first) and per-reciter groups."""
    global _clustering_cache
    if _clustering_cache is not None:
        return _clustering_cache
    disk = _load_research_cache('clustering')
    if disk is not None:
        _clustering_cache = disk
        return disk

    reciter_ids = sorted(rid for rid in MEMORIZATION_RECITERS if _memo_reciter_installed(rid))
    # Build per-reciter breath set: all word positions where they breathe
    # (forward stop OR repeat from_wpos), keyed as "surah:ayah:wpos".
    breath_sets: dict[str, set] = {rid: set() for rid in reciter_ids}

    for surah in range(1, 115):
        guide = _build_breathing_guide(surah)
        for ayah_str, vdata in guide.get('verses', {}).items():
            for stop in vdata.get('stops', []):
                for rid in stop.get('reciter_ids', []):
                    breath_sets[rid].add(f"{surah}:{ayah_str}:{stop['wpos']}")
            for rp in vdata.get('repeats', []):
                rid = rp.get('reciter_id')
                if rid:
                    breath_sets[rid].add(f"{surah}:{ayah_str}:{rp['from_wpos']}")

    # Jaccard similarity for every pair → a full symmetric matrix.
    sim = {r: {r: 1.0 for r in reciter_ids} for r in reciter_ids}
    pairs = []
    for i, r1 in enumerate(reciter_ids):
        s1 = breath_sets[r1]
        for r2 in reciter_ids[i + 1:]:
            s2 = breath_sets[r2]
            inter = len(s1 & s2)
            union = len(s1 | s2)
            s = round(inter / union, 3) if union else 0.0
            sim[r1][r2] = sim[r2][r1] = s
            pairs.append({
                'r1': r1, 'r2': r2,
                'n1': MEMORIZATION_RECITERS[r1].get('name_ar', ''),
                'n2': MEMORIZATION_RECITERS[r2].get('name_ar', ''),
                'similarity': s, 'shared': inter, 'union': union,
            })
    pairs.sort(key=lambda p: p['similarity'], reverse=True)
    sim_values = [p['similarity'] for p in pairs]
    lo = min(sim_values) if sim_values else 0.0
    hi = max(sim_values) if sim_values else 1.0

    # Order reciters so similar ones sit next to each other (a greedy nearest-
    # neighbour chain seeded at the most "central" reciter). This turns the
    # matrix into a heat-map where clusters show up as bright blocks.
    avg_sim = {r: sum(sim[r][o] for o in reciter_ids if o != r) / max(1, len(reciter_ids) - 1)
               for r in reciter_ids}
    order = [max(reciter_ids, key=lambda r: avg_sim[r])]
    remaining = set(reciter_ids) - set(order)
    while remaining:
        last = order[-1]
        nxt = max(remaining, key=lambda r: sim[last][r])
        order.append(nxt)
        remaining.discard(nxt)

    # Clusters: union-find linking pairs whose similarity is in the top tier
    # (≥ mean + 0.5·std). Reveals the natural groupings across the whole Quran.
    mean = sum(sim_values) / len(sim_values) if sim_values else 0.0
    var = sum((x - mean) ** 2 for x in sim_values) / len(sim_values) if sim_values else 0.0
    thr = round(mean + 0.5 * (var ** 0.5), 3)
    parent = {r: r for r in reciter_ids}

    def _find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for p in pairs:
        if p['similarity'] >= thr:
            parent[_find(p['r1'])] = _find(p['r2'])
    cluster_map = defaultdict(list)
    for r in reciter_ids:
        cluster_map[_find(r)].append(r)
    clusters = []
    for members in cluster_map.values():
        # intra-cluster average similarity (cohesion)
        if len(members) > 1:
            cs = [sim[a][b] for i, a in enumerate(members) for b in members[i + 1:]]
            cohesion = round(sum(cs) / len(cs), 3)
        else:
            cohesion = 0.0
        clusters.append({
            'members': [{'id': m, 'name_ar': MEMORIZATION_RECITERS[m].get('name_ar', '')} for m in members],
            'size': len(members), 'cohesion': cohesion,
        })
    clusters.sort(key=lambda c: (-c['size'], -c['cohesion']))

    # Per-reciter nearest & farthest peer (for the "who reads like whom" summary).
    profiles = []
    for r in reciter_ids:
        others = [(o, sim[r][o]) for o in reciter_ids if o != r]
        nearest = max(others, key=lambda t: t[1])
        farthest = min(others, key=lambda t: t[1])
        profiles.append({
            'id': r, 'name_ar': MEMORIZATION_RECITERS[r].get('name_ar', ''),
            'total_breaths': len(breath_sets[r]),
            'qasr': r in QASR_MUNFASIL_RECITERS,
            'nearest': {'id': nearest[0], 'name_ar': MEMORIZATION_RECITERS[nearest[0]].get('name_ar', ''), 'similarity': nearest[1]},
            'farthest': {'id': farthest[0], 'name_ar': MEMORIZATION_RECITERS[farthest[0]].get('name_ar', ''), 'similarity': farthest[1]},
        })

    _clustering_cache = {
        'order': [{'id': r, 'name_ar': MEMORIZATION_RECITERS[r].get('name_ar', ''),
                   'qasr': r in QASR_MUNFASIL_RECITERS} for r in order],
        'matrix': {r: sim[r] for r in reciter_ids},
        'range': {'min': lo, 'max': hi},
        'pairs': pairs[:12],
        'different': list(reversed(pairs[-8:])),
        'clusters': clusters,
        'cluster_threshold': thr,
        'profiles': profiles,
    }
    return _clustering_cache


@breathing_bp.route('/api/waqf-research/clustering', methods=['GET'])
def waqf_research_clustering():
    """Reciter similarity clustering based on waqf/breath patterns."""
    return jsonify(_build_reciter_clustering())


_mushaf_sim_cache: dict | None = None


def _mushaf_sem_class(version, raw):
    """Normalise a printed mushaf's raw waqf symbol to WHAT IT TELLS THE RECITER
    TO DO, so different notations can be compared by meaning rather than glyph.

    Key subtleties: ورش's ص is صه = STOP (the opposite of حفص's صلى = prefer to
    continue); ورش's lone ر is رأس آية (verse end), not a waqf ruling; الأزهر
    writes every discretionary stop as ج; الهندي uses the IndoPak glyph set."""
    raw = (raw or '').strip()
    if not raw:
        return None
    if 'ورش' in version:
        base = raw.split(',')[0].strip()
        if base in ('ر', '۝') and 'ص' not in raw:
            return None                      # رأس آية only — not a stop ruling
        return 'STOP'                        # صه = قف هنا
    if version == 'الهندي':
        return {
            'ۙ': 'NOSTOP', 'ۚ': 'CHOICE', 'ۘ': 'MUST',
            'ۗ': 'STOP', 'ۖ': 'CONT', 'ؕ': 'ABS',
            'ؗ': 'CHOICE', 'ۜ': 'SAKTA',
        }.get(raw[0])                        # leading IndoPak glyph; rare marks → None
    base = raw.split(',')[0].strip()
    return {'م': 'MUST', 'ق': 'STOP', 'ص': 'CONT', 'ج': 'CHOICE',
            'لا': 'NOSTOP', 'ع': 'EMBRACE', 'س': 'SAKTA'}.get(base)


# Canonical waqf marks (display order) → glyph + meaning. ورش/الهندي use their
# own systems and are compared by MEANING, not by these symbols.
_MARK_INFO = [
    ('م',  'ۘ', 'لازم — يجب الوقف، والوصل قد يُحيل المعنى'),
    ('ق',  'ۗ', 'الوقف أولى (قلى) — يُفضّل الوقف'),
    ('ص',  'ۖ', 'الوصل أولى (صلى) — يُفضّل الوصل'),
    ('ج',  'ۚ', 'جائز — يستوي الوقف والوصل'),
    ('لا', 'ۙ', 'لا وقف — لا يُوقف عليه (وقفٌ قبيح)'),
    ('ع',  'ۛ', 'المعانقة — يقف على أحد الموضعين فقط'),
    ('س',  'ۜ', 'سكتة — وقفة يسيرة بلا تنفّس'),
]
_MARK_SET = {m for m, _, _ in _MARK_INFO}
_AR_DIGITS = str.maketrans('0123456789', '٠١٢٣٤٥٦٧٨٩')
def _to_arabic_digits(n):
    return str(n).translate(_AR_DIGITS)
_mushaf_pos_data: dict | None = None   # per-position raw/sem/verse, for the diff endpoint


def _mushaf_base_mark(raw):
    """Leading canonical mark of a raw DB value ('ر,ص' → 'ر', 'قلى'→'ق' etc.)."""
    raw = (raw or '').strip()
    if not raw:
        return ''
    return raw.split(',')[0].strip()


def _build_mushaf_similarity(force_compute=False):
    """Compare the printed mushafs' waqf systems to each other across the whole
    Quran. Two lenses: PLACEMENT (do they put a stop at the same word at all) and
    MEANING (same word AND same ruling, after normalising notation). Returns the
    matrices, the ranked closest pairs, an average-linkage dendrogram, the
    per-mark consensus among the standard prints, and a 'what makes each special'
    profile."""
    global _mushaf_sim_cache, _mushaf_pos_data
    if force_compute and _mushaf_pos_data is None:
        _mushaf_sim_cache = None          # disk cache lacks the per-position data
    if _mushaf_sim_cache is not None:
        return _mushaf_sim_cache
    if not force_compute:
        disk = _load_research_cache('mushaf_similarity')
        if disk is not None:
            _mushaf_sim_cache = disk
            return disk

    versions = sorted(_get_mushaf_version_whitelist())
    place: dict[str, set] = {v: set() for v in versions}
    sem: dict[str, dict] = {v: {} for v in versions}
    raw_by: dict[str, dict] = {v: {} for v in versions}   # pos -> raw DB symbol
    verse_of: dict = {}                                    # pos -> (surah, ayah, word)

    if os.path.exists(MUSHAF_WAQF_DATABASE):
        conn = sqlite3.connect(MUSHAF_WAQF_DATABASE)
        try:
            cols = ', '.join('"' + v.replace('"', '""') + '"' for v in versions)
            cur = conn.execute(
                f'SELECT token_index, word_index, "السورة", "الآية", "الكلمة", {cols} FROM waqf')
            col_names = [d[0] for d in cur.description]
            vi = {v: col_names.index(v) for v in versions}
            for row in cur.fetchall():
                # token_index/word_index reset every verse, so they are NOT unique
                # on their own — key each position by (surah, ayah, word_index).
                pos = (row[2], row[3], row[1])
                verse_of[pos] = (row[2], row[3], row[4])
                for v in versions:
                    raw = row[vi[v]]
                    if raw and str(raw).strip():
                        raw = str(raw).strip()
                        place[v].add(pos)
                        raw_by[v][pos] = raw
                        cls = _mushaf_sem_class(v, raw)
                        if cls:
                            sem[v][pos] = cls
        finally:
            conn.close()

    std = [v for v in versions if v not in ('ورش', 'الهندي')]   # standard Arabic-symbol prints
    _mushaf_pos_data = {'versions': versions, 'std': std, 'raw': raw_by, 'sem': sem,
                        'verse': verse_of}

    def jac(a, b):
        A, B = place[a], place[b]
        u = len(A | B)
        return round(len(A & B) / u, 3) if u else 0.0

    def meaning(a, b):
        A, B = set(sem[a]), set(sem[b])
        u = len(A | B)
        if not u:
            return 0.0
        same = sum(1 for p in (A & B) if sem[a][p] == sem[b][p])
        return round(same / u, 3)

    place_m = {a: {b: (1.0 if a == b else jac(a, b)) for b in versions} for a in versions}
    mean_m = {a: {b: (1.0 if a == b else meaning(a, b)) for b in versions} for a in versions}

    pairs = []
    for i, a in enumerate(versions):
        for b in versions[i + 1:]:
            pairs.append({'a': a, 'b': b, 'meaning': mean_m[a][b], 'place': place_m[a][b]})
    pairs.sort(key=lambda p: (p['meaning'], p['place']), reverse=True)

    # Average-linkage agglomerative clustering on the MEANING distance (1 − sim).
    dist = {(a, b): 1 - mean_m[a][b] for a in versions for b in versions}
    clusters = {v: {'type': 'leaf', 'id': v, 'name': v, 'members': [v]} for v in versions}

    def cdist(ca, cb):
        vals = [dist[(a, b)] for a in ca['members'] for b in cb['members']]
        return sum(vals) / len(vals)

    nid = 0
    while len(clusters) > 1:
        ks = list(clusters)
        best = None
        for i in range(len(ks)):
            for j in range(i + 1, len(ks)):
                d = cdist(clusters[ks[i]], clusters[ks[j]])
                if best is None or d < best[0]:
                    best = (d, ks[i], ks[j])
        d, ka, kb = best
        ca, cb = clusters.pop(ka), clusters.pop(kb)
        clusters[f'_n{nid}'] = {
            'type': 'node', 'height': round(d, 3), 'similarity': round(1 - d, 3),
            'children': [ca, cb], 'members': ca['members'] + cb['members'],
        }
        nid += 1
    tree = next(iter(clusters.values())) if clusters else None

    def leaf_order(node, out):
        if node is None:
            return
        if node['type'] == 'leaf':
            out.append(node['id'])
        else:
            for ch in node['children']:
                leaf_order(ch, out)
    order = []
    leaf_order(tree, order)

    # ── Per-mark consensus among the STANDARD prints ────────────────────────
    # Canonical mark per position for each standard print, then per position the
    # plurality mark + how many agree. Bucketed by mark → positions + agreement.
    std_mark = {v: {p: _mushaf_base_mark(r) for p, r in raw_by[v].items()
                    if _mushaf_base_mark(r) in _MARK_SET} for v in std}
    all_std_pos = set().union(*[set(std_mark[v]) for v in std]) if std else set()
    agg = {m: [0, 0.0] for m, _, _ in _MARK_INFO}
    for p in all_std_pos:
        votes = Counter(std_mark[v][p] for v in std if p in std_mark[v])
        if not votes:
            continue
        top, topn = votes.most_common(1)[0]
        agg[top][0] += 1
        agg[top][1] += topn / sum(votes.values())
    mark_consensus = []
    for m, glyph, desc in _MARK_INFO:
        npos, sa = agg[m]
        mark_consensus.append({
            'sym': m, 'glyph': glyph, 'desc': desc,
            'positions': npos,
            'agreement': round(sa / npos, 3) if npos else 0.0,
            'counts': {v: sum(1 for p in std_mark[v] if std_mark[v][p] == m) for v in std},
        })

    # ── What makes each mushaf special ──────────────────────────────────────
    profiles = []
    max_la = max((sum(1 for x in std_mark.get(v, {}).values() if x == 'لا') for v in std), default=0)
    max_q = max((sum(1 for x in std_mark.get(v, {}).values() if x == 'ق') for v in std), default=0)
    for v in versions:
        cnt = Counter()
        for p, r in raw_by[v].items():
            b = _mushaf_base_mark(r)
            cnt[b] += 1
        special = []
        system = 'standard'
        if v == 'ورش':
            system = 'warsh'
            special.append('رواية ورش — «ص» تعني صه أي «قِف» (عكس صلى عند حفص)، و«ر» رأس آية في عدّ ورش.')
            special.append('نظامٌ مختلف عن حفص؛ يضع الوقف في مواضع متقاربة لكنه يحكم عليها بحكمٍ آخر.')
        elif v == 'الهندي':
            system = 'indopak'
            special.append('النظام الباكستاني (IndoPak) برموزٍ مختلفة كليًّا (ؕ ۚ ۙ ؗ …) — لا يقارَن رمزًا برمز.')
        else:
            nb_la, nb_q, nb_s, nb_j = cnt.get('لا', 0), cnt.get('ق', 0), cnt.get('ص', 0), cnt.get('ج', 0)
            if nb_q == 0 and nb_s == 0 and nb_j > 0:
                special.append('يوحّد كل وقفٍ اختياري في علامة «ج» — لا يفرّق بين قلى (الوقف أولى) وصلى (الوصل أولى).')
            if nb_la == 0:
                special.append('أسقط علامة «لا وقف» تمامًا — لا يَسِمها في أي موضع.')
            else:
                extra = ' (أكثر المصاحف)' if nb_la == max_la and max_la > 0 else ''
                special.append(f'يحافظ على علامة «لا وقف» في {_to_arabic_digits(nb_la)} موضعًا{extra} — حيث أسقطها بعض المطبوعات.')
            if nb_q > 0 and nb_q == max_q and max_q > 0:
                special.append(f'أكثرها استعمالًا لـ«قلى» (الوقف أولى): {_to_arabic_digits(nb_q)} موضعًا.')
        # lone-dissenter positions (only among standard prints): where this print's
        # ruling differs from every other standard print that marks the same word.
        lone = 0
        if v in std_mark:
            for p, m in std_mark[v].items():
                others = [std_mark[o][p] for o in std if o != v and p in std_mark[o]]
                if others and all(o != m for o in others):
                    lone += 1
            if lone:
                special.append(f'ينفرد بحكمٍ يخالف بقيّة المصاحف القياسية في {_to_arabic_digits(lone)} موضعًا.')
        profiles.append({
            'id': v, 'system': system, 'total': len(place[v]), 'lone': lone,
            'counts': {m: cnt.get(m, 0) for m, _, _ in _MARK_INFO},
            'special': special,
        })

    _mushaf_sim_cache = {
        'mushafs': versions,
        'standard': std,
        'order': order or versions,
        'meaning_matrix': mean_m,
        'place_matrix': place_m,
        'counts': {v: len(place[v]) for v in versions},
        'pairs': pairs,
        'tree': tree,
        'marks': [m for m, _, _ in _MARK_INFO],
        'mark_consensus': mark_consensus,
        'profiles': profiles,
    }
    return _mushaf_sim_cache


def _mushaf_diff(a, b, limit=200):
    """Every word where two mushafs give a DIFFERENT waqf ruling, with verse refs
    for drill-down. Grouped by the kind of disagreement (a's mark → b's mark)."""
    _build_mushaf_similarity(force_compute=True)   # ensure per-position data exists
    d = _mushaf_pos_data or {}
    raw_by, sem, verse = d.get('raw', {}), d.get('sem', {}), d.get('verse', {})
    if a not in raw_by or b not in raw_by:
        return None
    positions = set(sem.get(a, {})) | set(sem.get(b, {}))
    items, groups = [], Counter()
    same = 0
    for p in positions:
        ca, cb = sem[a].get(p), sem[b].get(p)
        if ca and cb and ca == cb:
            same += 1
            continue
        sa_, ay, word = verse.get(p, (None, None, ''))
        ra = raw_by[a].get(p, '')
        rb = raw_by[b].get(p, '')
        groups[(ra or '∅', rb or '∅')] += 1
        items.append({'surah': sa_, 'ayah': ay, 'word': word,
                      'a_sym': ra, 'b_sym': rb, 'wpos_key': p})
    items.sort(key=lambda it: ((it['surah'] or 0), (it['ayah'] or 0)))
    union = len(positions)
    return {
        'a': a, 'b': b,
        'meaning': round(same / union, 3) if union else 0.0,
        'differences': len(items),
        'shown': min(limit, len(items)),
        'capped': len(items) > limit,
        'groups': [{'a_sym': k[0], 'b_sym': k[1], 'count': n}
                   for k, n in groups.most_common()],
        'verses': [{'surah': it['surah'], 'ayah': it['ayah'], 'word': it['word'],
                    'a_sym': it['a_sym'], 'b_sym': it['b_sym']} for it in items[:limit]],
    }


@breathing_bp.route('/api/waqf-research/mushaf-similarity', methods=['GET'])
def waqf_research_mushaf_similarity():
    """How close the printed mushafs' waqf systems are to one another."""
    return jsonify(_build_mushaf_similarity())


@breathing_bp.route('/api/waqf-research/mushaf-diff', methods=['GET'])
def waqf_research_mushaf_diff():
    """Word-by-word differences between two mushafs' waqf rulings."""
    a = request.args.get('a', '')
    b = request.args.get('b', '')
    if not (_is_valid_mushaf_version(a) and _is_valid_mushaf_version(b)) or a == b:
        return jsonify({'error': 'invalid mushaf pair'}), 400
    res = _mushaf_diff(a, b)
    if res is None:
        return jsonify({'error': 'not found'}), 404
    return jsonify(res)


_ibtidaa_cache: dict | None = None


def _build_ibtidaa_index():
    """الابتداء — empirically-attested 'back-up and re-read' points.

    When a reciter pauses after a word and then RESUMES from an earlier word
    (rather than continuing forward), they are demonstrating ابتداء بما قبله:
    stopping on that word was improper enough (وقف قبيح / breaks the meaning) that
    they restart from before it. We harvest every such back-up across the Quran
    from the reciters' own audio (the `repeats` already computed by the breathing
    guide) and aggregate by position. Spots where SEVERAL reciters independently
    back up are the strongest evidence that الابتداء should be from before — a
    purely attested signal, never an invented rule."""
    global _ibtidaa_cache
    if _ibtidaa_cache is not None:
        return _ibtidaa_cache
    disk = _load_research_cache('ibtidaa')
    if disk is not None:
        _ibtidaa_cache = disk
        return disk

    surah_names = {s['number']: s['name'] for s in surahs_data} if surahs_data else {}
    # key (surah, ayah, from_wpos, to_wpos) -> set of reciter ids
    agg: dict[tuple, set] = defaultdict(set)

    for surah in range(1, 115):
        guide = _build_breathing_guide(surah)
        for ayah_str, vdata in guide.get('verses', {}).items():
            ayah = int(ayah_str)
            for rp in vdata.get('repeats', []):
                rid = rp.get('reciter_id')
                frm, to = rp.get('from_wpos'), rp.get('to_wpos')
                if rid is None or frm is None or to is None or to > frm:
                    continue
                agg[(surah, ayah, frm, to)].add(rid)

    items = []
    for (surah, ayah, frm, to), rids in agg.items():
        vk = f"{surah}:{ayah}"
        _, words, raw_to_wpos = _verse_word_texts(vk)
        if not words or not (0 <= to <= frm < len(words)):
            continue
        lo, hi = max(0, to - 1), min(len(words), frm + 2)
        # Is there ANY printed mushaf that marks a waqf on the word they paused
        # at? token_index is in the raw-split basis (counts ornaments), so map it
        # through raw_to_wpos before comparing to the recited-word position frm.
        stop_marked = False
        for ver in _WAQF_MATCH_MUSHAFS:
            for r in get_mushaf_waqf_symbols(surah, ayah, ver):
                ti = r.get('token_index')
                if ti is None or not r.get('symbols') or not (0 <= ti < len(raw_to_wpos)):
                    continue
                if raw_to_wpos[ti] == frm:
                    stop_marked = True
                    break
            if stop_marked:
                break
        items.append({
            'surah': surah, 'ayah': ayah,
            'name': surah_names.get(surah, ''),
            'stop_word': words[frm],
            'resume_word': words[to],
            'back_distance': frm - to,
            'context': ' '.join(words[lo:hi]),
            'reciters': sorted(MEMORIZATION_RECITERS[r].get('name_ar', r) for r in rids),
            'count': len(rids),
            'stop_marked': stop_marked,
        })

    # Multi-reciter back-ups first (strongest ابتداء-بما-قبله evidence), then by
    # how far back they go, then mushaf order.
    items.sort(key=lambda x: (-x['count'], -x['back_distance'], x['surah'], x['ayah']))
    multi = sum(1 for x in items if x['count'] >= 2)
    _ibtidaa_cache = {'count': len(items), 'multi_reciter': multi, 'items': items}
    return _ibtidaa_cache


@breathing_bp.route('/api/waqf-research/ibtidaa', methods=['GET'])
def waqf_research_ibtidaa():
    """الابتداء: attested 'back-up and re-read' points harvested from reciter audio."""
    return jsonify(_build_ibtidaa_index())


# السكتات (obligatory brief pauses-without-breath) in Hafs ʿan ʿAsim. Unlike a
# waqf these are FIXED, well-established positions — not derived from audio — so
# they are a curated reference. The four السكتات الواجبة come from the
# Shāṭibiyyah; «مَالِيَهۡ هَلَكَ» is the fifth, read by Hafs with two valid wajh
# (السكت with iẓhār, or idghām). Each carries the riwāyah's reason for the sakta.
HAFS_SAKTAT = [
    {
        'surah': 18, 'ayah': 1, 'wpos': 10, 'on_word': 'عِوَجَا',
        'next': {'surah': 18, 'ayah': 2, 'wpos': 0}, 'next_word': 'قَيِّمٗا',
        'category': 'واجبة', 'cross_verse': True,
        'reason': 'لئلّا يُتوهَّم أنّ «قَيِّمٗا» صفةٌ لـ«عِوَجَا»؛ فالسكتة تُبيّن أنّ '
                  'الكلام تمّ عند نفي العِوَج، و«قَيِّمٗا» حالٌ مستأنفة.',
    },
    {
        'surah': 36, 'ayah': 52, 'wpos': 5, 'on_word': 'مَّرۡقَدِنَا',
        'next': {'surah': 36, 'ayah': 52, 'wpos': 6}, 'next_word': 'هَٰذَا',
        'category': 'واجبة', 'cross_verse': False,
        'reason': 'للفصل بين كلام الكفّار «مَن بَعَثَنَا مِن مَّرۡقَدِنَا» وجواب '
                  'الملائكة والمؤمنين «هَٰذَا مَا وَعَدَ ٱلرَّحۡمَٰنُ».',
    },
    {
        'surah': 75, 'ayah': 27, 'wpos': 1, 'on_word': 'مَنۡ',
        'next': {'surah': 75, 'ayah': 27, 'wpos': 2}, 'next_word': 'رَاقٖ',
        'category': 'واجبة', 'cross_verse': False,
        'reason': 'لإظهار النون ومنع إدغامها في الراء؛ إذ لو وُصِلت لأُدغمت «مَن رَاقٍ» '
                  'فالتبس بيان الكلمتين.',
    },
    {
        'surah': 83, 'ayah': 14, 'wpos': 1, 'on_word': 'بَلۡ',
        'next': {'surah': 83, 'ayah': 14, 'wpos': 2}, 'next_word': 'رَانَ',
        'category': 'واجبة', 'cross_verse': False,
        'reason': 'لإظهار اللام ومنع إدغامها في الراء «بَلۡ رَانَ»، حفاظًا على بيان «بَلۡ».',
    },
    {
        'surah': 69, 'ayah': 28, 'wpos': 3, 'on_word': 'مَالِيَهۡ',
        'next': {'surah': 69, 'ayah': 29, 'wpos': 0}, 'next_word': 'هَلَكَ',
        'category': 'جائزة', 'cross_verse': True,
        'reason': 'بإظهار هاء السكت ومنع إدغامها في الهاء بعدها. وفيها لحفص وجهان: '
                  'السكت (مع الإظهار) والإدغام، وكلاهما صحيح.',
    },
]


@breathing_bp.route('/api/waqf-research/saktat', methods=['GET'])
def waqf_research_saktat():
    """السكتات: the fixed obligatory (and one optional) saktat in Hafs ʿan ʿAsim,
    each with the verse context and the riwāyah's reason for the pause."""
    surah_names = {s['number']: s['name'] for s in surahs_data} if surahs_data else {}
    out = []
    for sk in HAFS_SAKTAT:
        vk = f"{sk['surah']}:{sk['ayah']}"
        _, words, _ = _verse_word_texts(vk)
        lo, hi = max(0, sk['wpos'] - 2), min(len(words), sk['wpos'] + 2)
        context = ' '.join(words[lo:hi]) if words else ''
        out.append({**sk, 'name': surah_names.get(sk['surah'], ''), 'context': context})
    return jsonify({
        'count': len(out),
        'obligatory': sum(1 for x in out if x['category'] == 'واجبة'),
        'saktat': out,
    })


_mushaf_agreement_cache: dict | None = None


# Per-mushaf waqf-mark systems (directive + display glyph). Most follow the Hafs
# Sajāwandī set. ورش (the North-African Warsh print) uses ص = صه = STOP — the
# OPPOSITE of the Hafs صلى — and الأزهر marks every discretionary stop with ج
# (no قلى/صلى), so the columns differ per mushaf. dir: 'stop' ⇒ the reciter
# agrees by stopping; 'nostop' ⇒ agrees by continuing; 'choice' (ج, جائز) ⇒ no
# right/wrong — we instead measure his STOP-RATE, which reveals whether he
# treats the جائز like قلى (often stops) or like صلى (usually connects).
_JAIZ_MARK = {'sym': 'ج', 'dir': 'choice', 'name': 'جائز', 'glyph': 'ۚ'}
_HAFS_AGREE_MARKS = [
    {'sym': 'م',  'dir': 'stop',   'name': 'لازم',   'glyph': 'ۘ'},
    {'sym': 'ق',  'dir': 'stop',   'name': 'قلى',    'glyph': 'ۗ'},
    {'sym': 'ص',  'dir': 'nostop', 'name': 'صلى',    'glyph': 'ۖ'},
    {'sym': 'لا', 'dir': 'nostop', 'name': 'لا وقف', 'glyph': 'ۙ'},
    _JAIZ_MARK,
]
MUSHAF_AGREE_MARKS = {
    'المدينة الجديد': _HAFS_AGREE_MARKS,
    'المدينة القديم': _HAFS_AGREE_MARKS,
    'الشمرلي': _HAFS_AGREE_MARKS,
    'قطر':     _HAFS_AGREE_MARKS,
    'الكويت':  _HAFS_AGREE_MARKS,
    'الأزهر': [
        {'sym': 'م',  'dir': 'stop',   'name': 'لازم',   'glyph': 'ۘ'},
        {'sym': 'لا', 'dir': 'nostop', 'name': 'لا وقف', 'glyph': 'ۙ'},
        _JAIZ_MARK,
    ],
    'ورش': [
        {'sym': 'ص', 'dir': 'stop', 'name': 'صه', 'glyph': 'ۖ'},
    ],
}
_AGREE_CASE_CAP = 400   # max disagreement verses stored per (mushaf, reciter, mark)


def _agree_canonical_mark(ver, sym):
    """Map a raw DB symbol to this mushaf's canonical mark sym, or None to skip."""
    sym = (sym or '').strip()
    if ver == 'ورش':
        # ر = رأس آية (verse-end marker in the Warsh riwāyah), not a waqf
        # directive — skip it (and the 'ر,ص' verse-end cells). Only صه counts.
        if 'ر' in sym:
            return None
        return 'ص' if 'ص' in sym else None
    if sym == 'ج':
        return 'ج'
    return sym if sym in ('م', 'ق', 'ص', 'لا') else None


def _build_mushaf_agreement_index():
    """اتفاق القرّاء مع المصاحف — how each reciter's actual stopping behaviour
    agrees with each printed mushaf's waqf marks, Quran-wide.

    Directive is PER MUSHAF (see MUSHAF_AGREE_MARKS): a reciter "agrees" at a mark
    when his behaviour matches that mark's directive. Tallied per mark type, not
    blended, because م/ق are honoured almost universally while ص is where reciters
    genuinely differ and لا surfaces rare violations. Also records, per cell, the
    verses where the reciter DISAGREED (خالف العلامة) for drill-down, capped.

    "Stops here" uses the breathing guide's per-reciter forward stops at
    _WAQF_CONSENSUS_GAP_MS = 1 ms (same as the reciter cards)."""
    global _mushaf_agreement_cache
    if _mushaf_agreement_cache is not None:
        return _mushaf_agreement_cache
    disk = _load_research_cache('mushaf_agreement')
    if disk is not None:
        _mushaf_agreement_cache = disk
        return disk

    versions = list(_WAQF_COMPARE_MUSHAFS)
    reciter_ids = sorted(rid for rid in MEMORIZATION_RECITERS if _memo_reciter_installed(rid))
    cfg_of = {v: MUSHAF_AGREE_MARKS.get(v, _HAFS_AGREE_MARKS) for v in versions}
    dir_of = {v: {m['sym']: m['dir'] for m in cfg_of[v]} for v in versions}

    # [ver][rid][sym] = [agree, total]; cases[ver][rid][sym] = [vk, ...]
    agree = {v: {r: {m['sym']: [0, 0] for m in cfg_of[v]} for r in reciter_ids} for v in versions}
    cases = {v: {r: {m['sym']: [] for m in cfg_of[v]} for r in reciter_ids} for v in versions}
    jaiz = {v: 0 for v in versions}

    for surah in range(1, 115):
        guide = _build_breathing_guide(surah)
        present = [r['id'] for r in guide.get('reciters', [])]
        for ayah_str, vdata in guide.get('verses', {}).items():
            ayah = int(ayah_str)
            stoppers = defaultdict(set)   # wpos → reciters who forward-stop there
            for st in vdata.get('stops', []):
                for rid in st.get('reciter_ids', []):
                    stoppers[st['wpos']].add(rid)
            vk = f"{surah}:{ayah}"
            _, words, raw_to_wpos = _verse_word_texts(vk)
            if not words:
                continue
            for ver in versions:
                for r in get_mushaf_waqf_symbols(surah, ayah, ver):
                    ti = r.get('token_index')
                    if ti is None or not (0 <= ti < len(raw_to_wpos)):
                        continue
                    wp = raw_to_wpos[ti]
                    if wp is None:
                        continue
                    csym = _agree_canonical_mark(ver, r.get('symbols'))
                    if csym is None or csym not in dir_of[ver]:
                        continue
                    directive = dir_of[ver][csym]
                    here = stoppers.get(wp, ())
                    if csym == 'ج':
                        jaiz[ver] += 1
                    if directive == 'choice':
                        # ج: no right/wrong — cell[0] counts how often he STOPS
                        # (his stop-rate), and the cases list his stop choices.
                        for rid in present:
                            cell = agree[ver][rid][csym]
                            cell[1] += 1
                            if rid in here:
                                cell[0] += 1
                                lst = cases[ver][rid][csym]
                                if len(lst) < _AGREE_CASE_CAP and (not lst or lst[-1] != vk):
                                    lst.append(vk)
                        continue
                    want_stop = directive == 'stop'
                    for rid in present:
                        cell = agree[ver][rid][csym]
                        cell[1] += 1
                        if (rid in here) == want_stop:
                            cell[0] += 1
                        else:
                            lst = cases[ver][rid][csym]
                            # de-dup consecutive (a verse with >1 same-type mark)
                            if len(lst) < _AGREE_CASE_CAP and (not lst or lst[-1] != vk):
                                lst.append(vk)

    _mushaf_agreement_cache = {
        'mushafs': versions,
        'mark_config': {v: cfg_of[v] for v in versions},
        'gap_ms': _WAQF_CONSENSUS_GAP_MS,
        'reciters': [{'id': r, 'name_ar': MEMORIZATION_RECITERS[r].get('name_ar', r),
                      'qasr': r in QASR_MUNFASIL_RECITERS} for r in reciter_ids],
        'agreement': agree,
        'jaiz': jaiz,
        '_cases': cases,
    }
    return _mushaf_agreement_cache


@breathing_bp.route('/api/waqf-research/mushaf-agreement', methods=['GET'])
def waqf_research_mushaf_agreement():
    """اتفاق القرّاء مع المصاحف: per-reciter, per-mushaf agreement by mark type."""
    data = _build_mushaf_agreement_index()
    return jsonify({k: v for k, v in data.items() if k != '_cases'})


@breathing_bp.route('/api/waqf-research/mushaf-agreement/cases', methods=['GET'])
def waqf_research_mushaf_agreement_cases():
    """The verses where a reciter خالف a mushaf's waqf mark (drill-down).
    Params: mushaf, reciter, mark (one of م/ق/ص/لا)."""
    data = _build_mushaf_agreement_index()
    ver = request.args.get('mushaf', '')
    rid = request.args.get('reciter', '')
    mark = request.args.get('mark', '')
    try:
        vks = data['_cases'][ver][rid][mark]
    except KeyError:
        return jsonify({'error': 'unknown mushaf/reciter/mark'}), 400
    cell = data['agreement'][ver][rid][mark]
    directive = next((m['dir'] for m in data['mark_config'][ver] if m['sym'] == mark), None)
    # ج (choice): the recorded cases are his STOP choices (cell[0]); for the
    # other marks they are disagreements (total − agreed).
    total = cell[0] if directive == 'choice' else cell[1] - cell[0]
    surah_names = {s['number']: s['name'] for s in surahs_data} if surahs_data else {}
    verses = []
    for vk in vks:
        s, a = vk.split(':')
        verses.append({'surah': int(s), 'ayah': int(a), 'name': surah_names.get(int(s), '')})
    return jsonify({
        'mushaf': ver, 'reciter': rid, 'mark': mark,
        'directive': directive,
        'disagreed': total, 'shown': len(verses), 'capped': total > len(verses),
        'verses': verses,
    })


_waqf_research_cache: _BoundedLRU = _BoundedLRU(maxsize=256)


def _before_word_marks(s, a, i, words, marks_by_wpos):
    """Resolve waqf marks for the word preceding position *i*.

    When i > 0, uses the same verse's marks map.  When i == 0, loads the
    last word of the previous ayah (same surah) so cross-verse boundaries
    are covered — essential for interrogatives at verse start."""
    if i > 0:
        bw = words[i - 1]
        bmarks = marks_by_wpos.get(i - 1, {})
        bwsym = ''.join(c for c in bw if c in WAQF_SYMBOL_CHARS)
        return bw, bmarks, bwsym

    if a <= 1:
        return '', {}, ''

    prev_vk = f"{s}:{a - 1}"
    _, prev_words, prev_r2w = _verse_word_texts(prev_vk)
    if not prev_words:
        return '', {}, ''

    prev_marks = {}
    for ver in _WAQF_MATCH_MUSHAFS:
        for r in get_mushaf_waqf_symbols(s, a - 1, ver):
            ti = r.get('token_index')
            if ti is None or not r.get('symbols') or not (0 <= ti < len(prev_r2w)):
                continue
            wp = prev_r2w[ti]
            if wp is not None:
                prev_marks.setdefault(wp, {})[ver] = r['symbols']

    last_i = len(prev_words) - 1
    bw = prev_words[last_i]
    return bw, prev_marks.get(last_i, {}), ''.join(c for c in bw if c in WAQF_SYMBOL_CHARS)


@breathing_bp.route('/api/waqf-research', methods=['GET'])
def waqf_research():
    """Research tool: every verse where a given word occurs, with the exact
    vocalised form, the printed Madinah waqf symbol embedded on it, and a small
    context snippet. Diacritic-insensitive match (so كَلَّا and كُلّاً both come
    back) but each occurrence keeps its exact form, plus a form breakdown, so the
    researcher can isolate the particle they want. Reciter waqf + the full mushaf
    comparison are shown by clicking through to the verse."""
    word = request.args.get('word', '').strip()
    if not word:
        return jsonify({'error': "query parameter 'word' is required"}), 400
    # exact=1: pre-select the form matching the (vocalised) query, so a preset
    # like كَلَّا lands on the 33 particle occurrences, not كُلّاً.
    exact = request.args.get('exact') in ('1', 'true', 'yes')
    # mode=before: show waqf marks on the word BEFORE the searched word
    # (useful for studying waqf before interrogatives like هل/كيف).
    before = request.args.get('mode') == 'before'
    nt = _normalize_for_search(word)
    if not nt:
        return jsonify({'word': word, 'normalized': '', 'count': 0, 'forms': [], 'occurrences': [], 'active_form': None})

    cache_key = (nt, exact, before)
    cached = _waqf_research_cache.get(cache_key)
    if cached is not None:
        return jsonify(cached)

    def _form_key(token):
        """Coarse form: drop waqf symbols and fold alef/hamza variants, but KEEP
        harakat — so كَلَّا/كَلَّآ/كَلَّاۖ collapse to one form while كُلّٗا (each)
        stays distinct from كَلَّا (the particle)."""
        # drop: waqf symbols, tatweel, maddah, both sukun glyphs (ْ / ۡ); keep the
        # short vowels (fatha/damma/kasra/shadda) that carry the meaning.
        drop = set(WAQF_SYMBOL_CHARS) | {'ـ', 'ٓ', 'ْ', 'ۡ', 'ۤ'}
        out = ''.join(c for c in token if c not in drop)
        for a in ('آ', 'أ', 'إ', 'ٱ'):
            out = out.replace(a, 'ا')
        return out

    occ = []
    forms = Counter()
    for vk in qpc_hafs_data_normalized:
        text, words, raw_to_wpos = _verse_word_texts(vk)
        if not words or nt not in _normalize_for_search(text):
            continue  # quick reject — most verses don't contain the word
        s, a = vk.split(':')
        s, a = int(s), int(a)
        marks_by_wpos = None  # built lazily — only for verses that actually match
        for i, w in enumerate(words):
            if _normalize_for_search(w) != nt:
                continue
            if marks_by_wpos is None:
                marks_by_wpos = {}
                for ver in _WAQF_MATCH_MUSHAFS:
                    for r in get_mushaf_waqf_symbols(s, a, ver):
                        ti = r.get('token_index')
                        if ti is None or not r.get('symbols') or not (0 <= ti < len(raw_to_wpos)):
                            continue
                        wp = raw_to_wpos[ti]
                        if wp is not None:
                            marks_by_wpos.setdefault(wp, {})[ver] = r['symbols']
            fk = _form_key(w)
            if before:
                bw, bmarks, bwsym = _before_word_marks(
                    s, a, i, words, marks_by_wpos)
                marks, wsym = bmarks, bwsym
                lo, hi = max(0, i - 2), min(len(words), i + 2)
                ctx = ' '.join(words[lo:hi])
                if i == 0 and bw:
                    ctx = bw + ' ۞ ' + ctx
            else:
                wsym = ''.join(c for c in w if c in WAQF_SYMBOL_CHARS)
                marks = marks_by_wpos.get(i, {})
                lo, hi = max(0, i - 1), min(len(words), i + 3)
                ctx = ' '.join(words[lo:hi])
            occ.append({
                'surah': s, 'ayah': a, 'wpos': i,
                'word': w, 'form': fk, 'waqf': wsym,
                'marks': marks, 'has_waqf': bool(marks or wsym),
                'context': ctx,
            })
            forms[fk] += 1

    # For a preset (exact=1) default to the dominant form — which for these
    # particles is the waqf-relevant one (كَلَّا not كُلّاً، نَعَم not نِعْمَ).
    active_form = forms.most_common(1)[0][0] if (exact and forms) else None
    result = {
        'word': word,
        'normalized': nt,
        'count': len(occ),
        'forms': [{'word': w, 'count': c} for w, c in forms.most_common()],
        'occurrences': occ,
        'active_form': active_form,
    }
    _waqf_research_cache[cache_key] = result
    return jsonify(result)

