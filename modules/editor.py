"""محرّر المصحف — the click-to-edit waqf tool (the ONLY writer).

Routes for the editor page, the spread payloads (Qatar layout right page /
QPC-v1 left page), and reading/writing a single word's waqf symbol.

When Supabase is configured (SUPABASE_URL + service role), قطر/الكويت marks
are stored as drafts in Postgres and only become public after admin publish.
Without Supabase, writes still go to local mushaf_waqf.db (laptop workflow).
"""
from __future__ import annotations

import logging
import sqlite3

from flask import jsonify, render_template, request

from core.blueprints import editor_bp
from core.config import (
    CLOUD_EDITOR_EDITIONS,
    EDITOR_EDITIONS,
    MUSHAF_WAQF_DATABASE,
    QATAR_LAYOUT_DATABASE,
    QPC_V1_LAYOUT_DATABASE,
)
from core.loader import IS_SERVERLESS as _IS_SERVERLESS
from core.db import connect as _sqlite_connect
from core.mushaf_waqf import _mushaf_waqf_cache, invalidate_cloud_waqf_cache
from core import supabase_editor as sb
from modules.breathing import _verse_waqf_cache
from modules.editor_auth import current_editor, require_admin, require_editor
from modules.layouts import (
    _build_qatar_page_payload,
    _build_qpc_v1_page_payload,
    _get_dk_layout_word_map,
    _find_mushaf_row_match_index,
    _normalize_mushaf_word_token,
    _layout_page_resolve,
)

# Side-effect: register login/logout routes on editor_bp.
import modules.editor_auth  # noqa: F401

logger = logging.getLogger(__name__)

_MAX_MUSHAF_PAGE = 604
_MAX_MUSHAF_SPREAD = 302
_EDITOR_SYMBOLS = {'', 'م', 'لا', 'ق', 'ص', 'ج', 'س', 'ع', 'ركوع'}
_EDITOR_PEER_VERSIONS = (
    'المدينة الجديد',
    'المدينة القديم',
    'الأزهر',
    'الشمرلي',
)


def _ayah_word_list_for_editor(surah_number, ayah_number):
    """Ordered list of {'word_id', 'text'} for every layout word in an ayah."""
    wmap = _get_dk_layout_word_map()
    first_id = wmap['first_id'].get((surah_number, ayah_number))
    last_id = wmap['last_id'].get((surah_number, ayah_number))
    if first_id is None or last_id is None:
        return []
    id2tok = wmap['id2tok']
    words = []
    for word_id in range(first_id, last_id + 1):
        tok = id2tok.get(word_id)
        if tok:
            words.append({'word_id': word_id, 'text': tok['text']})
    return words


def _resolve_word(global_word_id):
    """Return (surah, ayah, token_index, word_text) or None."""
    wmap = _get_dk_layout_word_map()
    tok = wmap['id2tok'].get(global_word_id)
    if not tok:
        return None
    surah_number, ayah_number = tok['surah'], tok['ayah']
    first_id = wmap['first_id'].get((surah_number, ayah_number))
    if first_id is None:
        return None
    return surah_number, ayah_number, global_word_id - first_id, tok['text']


def _sqlite_edition_marks_map(edition: str, ayah_keys: list[tuple[int, int]]) -> dict[tuple[int, int, int], str]:
    """Map (surah, ayah, token_index) → symbol from local mushaf_waqf.db."""
    if not ayah_keys or edition not in EDITOR_EDITIONS:
        return {}
    quoted = f'"{edition}"'
    out: dict[tuple[int, int, int], str] = {}
    conn = _sqlite_connect(MUSHAF_WAQF_DATABASE)
    try:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        for surah, ayah in ayah_keys:
            cur.execute(
                f'SELECT "الكلمة" AS word, token_index, word_index, {quoted} AS symbol '
                'FROM waqf WHERE "السورة" = ? AND "الآية" = ? '
                f'AND {quoted} IS NOT NULL AND {quoted} != "" ORDER BY rowid ASC',
                (surah, ayah),
            )
            rows = [dict(r) for r in cur.fetchall()]
            if not rows:
                continue
            words = _ayah_word_list_for_editor(surah, ayah)
            if not words:
                continue
            search_start = 0
            for row in rows:
                matched = _find_mushaf_row_match_index(words, {
                    'clean_token': row.get('word') or '',
                    'word_index': row.get('word_index'),
                    'token_index': None,
                }, search_start)
                if matched is None:
                    ti = row.get('token_index')
                    try:
                        ti = int(ti) - 1 if ti is not None else None
                    except (TypeError, ValueError):
                        ti = None
                    if ti is None or not (0 <= ti < len(words)):
                        continue
                    matched = ti
                search_start = matched + 1
                symbol = (row.get('symbol') or '').strip()
                if symbol:
                    out[(surah, ayah, matched)] = symbol
    finally:
        conn.close()
    return out


def _overlay_cloud_marks_on_pages(pages: list[dict | None], edition: str) -> None:
    """Apply cloud edition marks onto one or more page payloads (one network round-trip).

    Preference: draft → published → local SQLite (only if cloud returned nothing,
    e.g. before migrate). Page build should pass *peer* versions only when cloud
    is on, so we don't also hit Supabase once-per-ayah during layout.
    """
    if not sb.is_configured():
        return
    page_words: list[tuple[dict, list]] = []
    ayah_keys: set[tuple[int, int]] = set()
    for page in pages:
        if not page:
            continue
        words = []
        for line in page.get('lines') or []:
            for w in line.get('words') or []:
                if w.get('surah') and w.get('ayah') is not None:
                    words.append(w)
                    ayah_keys.add((int(w['surah']), int(w['ayah'])))
        if words:
            page_words.append((page, words))
    if not page_words:
        return
    keys = sorted(ayah_keys)

    try:
        draft_rows, published_rows = sb.fetch_draft_and_published_for_ayahs(
            edition=edition, ayah_keys=keys,
        )
    except sb.SupabaseEditorError as e:
        logger.error('cloud mark overlay failed: %s', e)
        return
    except Exception as e:
        logger.error('cloud mark overlay failed: %s', e)
        return

    def _index(rows):
        return {
            (int(r['surah']), int(r['ayah']), int(r['token_index'])): (r.get('symbol') or '').strip()
            for r in rows
        }

    drafts = _index(draft_rows)
    published = _index(published_rows)
    # Skip expensive SQLite rematch when cloud already has the live baseline.
    sqlite_marks = (
        {} if (drafts or published)
        else _sqlite_edition_marks_map(edition, keys)
    )

    wmap = _get_dk_layout_word_map()
    for _page, words in page_words:
        for w in words:
            surah, ayah = int(w['surah']), int(w['ayah'])
            first_id = wmap['first_id'].get((surah, ayah))
            if first_id is None:
                continue
            token_index = int(w['word_index']) - first_id
            key = (surah, ayah, token_index)
            if key in drafts:
                symbol = drafts[key]
                from_cloud = True
            elif key in published:
                symbol = published[key]
                from_cloud = True
            elif key in sqlite_marks:
                symbol = sqlite_marks[key]
                from_cloud = False
            else:
                continue

            entries = w.get('waqf_symbols')
            if not isinstance(entries, list):
                entries = []
            w['waqf_symbols'] = [e for e in entries if e.get('version') != edition]
            if symbol:
                w['waqf_symbols'].append({'symbols': symbol, 'version': edition})
            elif from_cloud and key in drafts:
                pass


def _overlay_cloud_marks_on_page(page: dict | None, edition: str, status: str = 'draft') -> None:
    """Back-compat wrapper."""
    _overlay_cloud_marks_on_pages([page], edition)


def _get_or_set_word_waqf_sqlite(global_word_id, edition, symbol):
    """Legacy local SQLite path (used when Supabase is not configured)."""
    if edition not in EDITOR_EDITIONS:
        return None

    resolved = _resolve_word(global_word_id)
    if not resolved:
        return None
    surah_number, ayah_number, target_index, _text = resolved

    words = _ayah_word_list_for_editor(surah_number, ayah_number)
    if not (0 <= target_index < len(words)):
        return None

    quoted_col = f'"{edition}"'
    conn = _sqlite_connect(MUSHAF_WAQF_DATABASE)
    try:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            f'SELECT rowid, "الكلمة" AS word, token_index, word_index, {quoted_col} AS current '
            'FROM waqf WHERE "السورة" = ? AND "الآية" = ? ORDER BY rowid ASC',
            (surah_number, ayah_number)
        )
        rows = [dict(r) for r in cur.fetchall()]

        matched_row = None
        search_start = 0
        for row in rows:
            idx = _find_mushaf_row_match_index(words, row, search_start)
            if idx == target_index:
                matched_row = row
                break
            if idx is not None:
                search_start = idx + 1

        if symbol is None:
            return matched_row['current'] if matched_row else None

        clean_symbol = (symbol or '').strip() or None

        if matched_row is not None:
            cur.execute(f'UPDATE waqf SET {quoted_col} = ? WHERE rowid = ?', (clean_symbol, matched_row['rowid']))
            conn.commit()
            _mushaf_waqf_cache.pop((surah_number, ayah_number, edition), None)
            _verse_waqf_cache.pop((surah_number, ayah_number), None)
            return clean_symbol

        if clean_symbol is None:
            return None

        word_index_hint = 1 + sum(
            1 for w in words[:target_index] if _normalize_mushaf_word_token(w['text'])
        )
        used_token_indexes = {r['token_index'] for r in rows if r.get('token_index') is not None}
        token_index = target_index + 1
        while token_index in used_token_indexes:
            token_index += 1

        cur.execute(
            f'INSERT INTO waqf ("السورة","الآية","الكلمة",token_index,word_index,{quoted_col}) '
            'VALUES (?, ?, ?, ?, ?, ?)',
            (surah_number, ayah_number, words[target_index]['text'], token_index, word_index_hint, clean_symbol)
        )
        conn.commit()
        _mushaf_waqf_cache.pop((surah_number, ayah_number, edition), None)
        _verse_waqf_cache.pop((surah_number, ayah_number), None)
        return clean_symbol
    finally:
        conn.close()


def _get_or_set_word_waqf_cloud(global_word_id, edition, symbol, user: dict | None):
    """Read/write draft mark in Supabase. symbol=None → read only."""
    resolved = _resolve_word(global_word_id)
    if not resolved:
        return None
    surah, ayah, token_index, word_text = resolved
    actor_id = user['id'] if user else None
    actor_name = user['name'] if user else None

    if symbol is None:
        row = sb.get_mark(
            edition=edition, surah=surah, ayah=ayah,
            token_index=token_index, status='draft',
        )
        return (row.get('symbol') if row else None) or None

    clean = (symbol or '').strip()
    old_row = sb.get_mark(
        edition=edition, surah=surah, ayah=ayah,
        token_index=token_index, status='draft',
    )
    old_symbol = (old_row.get('symbol') if old_row else '') or ''

    if not clean:
        # Keep an empty draft as a deletion tombstone. Deleting the draft row
        # would expose the published mark again and pending_publish_diff()
        # would have nothing to promote, making published marks impossible to
        # clear through the editor.
        sb.upsert_mark(
            edition=edition, surah=surah, ayah=ayah,
            token_index=token_index, status='draft', symbol='',
            word_text=word_text, updated_by=actor_id,
        )
        sb.append_audit(
            actor_id=actor_id, actor_name=actor_name,
            action='clear_mark', edition=edition,
            surah=surah, ayah=ayah, token_index=token_index,
            word_id=global_word_id, old_symbol=old_symbol, new_symbol='',
        )
        invalidate_cloud_waqf_cache(edition, surah, ayah)
        return None

    sb.upsert_mark(
        edition=edition, surah=surah, ayah=ayah, token_index=token_index,
        status='draft', symbol=clean, word_text=word_text, updated_by=actor_id,
    )
    sb.append_audit(
        actor_id=actor_id, actor_name=actor_name,
        action='set_mark', edition=edition,
        surah=surah, ayah=ayah, token_index=token_index,
        word_id=global_word_id, old_symbol=old_symbol, new_symbol=clean,
    )
    invalidate_cloud_waqf_cache(edition, surah, ayah)
    return clean


def _get_or_set_word_waqf(global_word_id, edition, symbol, user=None):
    """Compatibility wrapper for seed scripts: cloud when configured, else SQLite."""
    if edition in CLOUD_EDITOR_EDITIONS and sb.is_configured():
        return _get_or_set_word_waqf_cloud(global_word_id, edition, symbol, user)
    return _get_or_set_word_waqf_sqlite(global_word_id, edition, symbol)


@editor_bp.route('/mushaf-editor')
def mushaf_editor_page():
    return render_template('mushaf_editor.html', enable_vercel_analytics=_IS_SERVERLESS)


@editor_bp.route('/api/mushaf-editor/spread/<int:spread_number>', methods=['GET'])
@require_editor
def get_mushaf_editor_spread(spread_number):
    """Two facing pages carrying the selected edition's marks + peer hints."""
    edition = (request.args.get('edition') or '').strip()
    if edition not in EDITOR_EDITIONS:
        return jsonify({'error': 'invalid edition'}), 400
    if not (1 <= spread_number <= _MAX_MUSHAF_SPREAD):
        return jsonify({'error': f'spread_number must be between 1 and {_MAX_MUSHAF_SPREAD}'}), 400
    try:
        right_page = spread_number * 2 - 1
        left_page = right_page + 1
        # When cloud is on, load peers from SQLite only — edition marks come from
        # one batched Supabase overlay (avoids per-ayah HTTP during page build).
        if edition in CLOUD_EDITOR_EDITIONS and sb.is_configured():
            versions = list(_EDITOR_PEER_VERSIONS)
        else:
            versions = [edition]
            for peer in _EDITOR_PEER_VERSIONS:
                if peer not in versions:
                    versions.append(peer)
        build_page = _build_qatar_page_payload if edition == 'قطر' else _build_qpc_v1_page_payload
        right = build_page(right_page, mushaf_version=versions)
        left = build_page(left_page, mushaf_version=versions) if left_page <= _MAX_MUSHAF_PAGE else None
        if edition == 'الكويت':
            for page in (right, left):
                if page:
                    page['font_name'] = 'Al Shamiya'
        if edition in CLOUD_EDITOR_EDITIONS and sb.is_configured():
            _overlay_cloud_marks_on_pages([right, left], edition)
        return jsonify({
            'spread_number': spread_number,
            'edition': edition,
            'right': right,
            'left': left,
            'max_spread': _MAX_MUSHAF_SPREAD,
            'peer_versions': list(_EDITOR_PEER_VERSIONS),
            'cloud': sb.is_configured(),
        })
    except Exception as e:
        logger.error(f"Error fetching mushaf-editor spread {spread_number}: {e}")
        return jsonify({'error': str(e)}), 500


@editor_bp.route('/api/mushaf-editor/waqf', methods=['POST'])
@require_editor
def set_mushaf_editor_waqf():
    """Set or clear the waqf mark for one word in one edition."""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({'error': 'JSON object required'}), 400
    try:
        word_id = int(data.get('word_id'))
    except (TypeError, ValueError):
        return jsonify({'error': 'invalid word_id'}), 400
    edition = data.get('edition') or ''
    if not isinstance(edition, str):
        return jsonify({'error': 'invalid edition'}), 400
    edition = edition.strip()
    if edition not in EDITOR_EDITIONS:
        return jsonify({'error': 'invalid edition'}), 400
    symbol = data.get('symbol')
    symbol = '' if symbol is None else str(symbol).strip()
    if symbol not in _EDITOR_SYMBOLS:
        return jsonify({'error': 'invalid symbol'}), 400

    user = current_editor()
    try:
        if edition in CLOUD_EDITOR_EDITIONS and sb.is_configured():
            result = _get_or_set_word_waqf_cloud(word_id, edition, symbol, user)
        else:
            result = _get_or_set_word_waqf_sqlite(word_id, edition, symbol)
    except sb.SupabaseEditorError as e:
        logger.error('cloud waqf write failed: %s', e)
        return jsonify({'error': 'cloud write failed'}), 503

    if result is None and symbol:
        return jsonify({'error': 'word not found'}), 404
    return jsonify({'word_id': word_id, 'edition': edition, 'symbol': result or ''})


@editor_bp.route('/api/mushaf-editor/progress', methods=['GET', 'POST'])
@require_editor
def mushaf_editor_progress():
    """Track which pages have been manually reviewed for each edition."""
    if request.method == 'GET':
        edition = (request.args.get('edition') or '').strip()
        body = None
    else:
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return jsonify({'error': 'JSON object required'}), 400
        edition = body.get('edition', '')
        if not isinstance(edition, str):
            return jsonify({'error': 'invalid edition'}), 400
        edition = (edition or '').strip()

    if edition not in EDITOR_EDITIONS:
        return jsonify({'error': 'invalid edition'}), 400

    user = current_editor()

    if edition in CLOUD_EDITOR_EDITIONS and sb.is_configured():
        try:
            if request.method == 'GET':
                pages = sb.list_reviewed_pages(edition)
                return jsonify({'edition': edition, 'reviewed_pages': pages})
            try:
                page_number = int(body.get('page_number'))
            except (TypeError, ValueError):
                return jsonify({'error': 'invalid page_number'}), 400
            if not (1 <= page_number <= _MAX_MUSHAF_PAGE):
                return jsonify({'error': f'page_number must be between 1 and {_MAX_MUSHAF_PAGE}'}), 400
            reviewed = bool(body.get('reviewed'))
            sb.upsert_progress(
                edition=edition, page_number=page_number, reviewed=reviewed,
                updated_by=user['id'] if user else None,
            )
            sb.append_audit(
                actor_id=user['id'] if user else None,
                actor_name=user['name'] if user else None,
                action='review_page', edition=edition, page_number=page_number,
                meta={'reviewed': reviewed},
            )
            return jsonify({
                'ok': True, 'page_number': page_number,
                'edition': edition, 'reviewed': reviewed,
            })
        except sb.SupabaseEditorError as e:
            logger.error('cloud progress failed: %s', e)
            return jsonify({'error': 'cloud progress failed'}), 503

    conn = _sqlite_connect(MUSHAF_WAQF_DATABASE)
    try:
        cur = conn.cursor()
        if request.method == 'GET':
            cur.execute(
                'SELECT page_number FROM mushaf_editor_progress WHERE edition = ? AND reviewed = 1',
                (edition,)
            )
            pages = sorted(row[0] for row in cur.fetchall())
            return jsonify({'edition': edition, 'reviewed_pages': pages})

        try:
            page_number = int(body.get('page_number'))
        except (TypeError, ValueError):
            return jsonify({'error': 'invalid page_number'}), 400
        if not (1 <= page_number <= _MAX_MUSHAF_PAGE):
            return jsonify({'error': f'page_number must be between 1 and {_MAX_MUSHAF_PAGE}'}), 400
        reviewed = 1 if body.get('reviewed') else 0
        cur.execute(
            'INSERT INTO mushaf_editor_progress (page_number, edition, reviewed, updated_at) '
            'VALUES (?, ?, ?, datetime("now")) '
            'ON CONFLICT(page_number, edition) DO UPDATE SET reviewed = excluded.reviewed, updated_at = excluded.updated_at',
            (page_number, edition, reviewed)
        )
        conn.commit()
        return jsonify({'ok': True, 'page_number': page_number, 'edition': edition, 'reviewed': bool(reviewed)})
    except Exception as e:
        logger.error(f"Error in mushaf-editor progress: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@editor_bp.route('/api/mushaf-editor/pending', methods=['GET'])
@require_editor
def editor_pending_changes():
    """List draft marks that differ from published for the selected edition."""
    edition = (request.args.get('edition') or '').strip()
    if edition not in CLOUD_EDITOR_EDITIONS:
        return jsonify({'error': 'invalid edition'}), 400
    if not sb.is_configured():
        return jsonify({'edition': edition, 'changes': [], 'pages': [], 'count': 0})
    try:
        changes = sb.pending_publish_diff(edition)
    except sb.SupabaseEditorError as e:
        logger.error('pending diff failed: %s', e)
        return jsonify({'error': 'pending unavailable'}), 503

    layout_db = QPC_V1_LAYOUT_DATABASE if edition == 'الكويت' else QATAR_LAYOUT_DATABASE
    wmap = _get_dk_layout_word_map()
    pages_acc: dict[int, dict] = {}
    for ch in changes:
        surah, ayah, ti = int(ch['surah']), int(ch['ayah']), int(ch['token_index'])
        page_number = _layout_page_resolve(layout_db, surah, ayah)
        ch['page_number'] = page_number
        first_id = wmap['first_id'].get((surah, ayah))
        ch['word_id'] = (first_id + ti) if first_id is not None else None
        if page_number is None:
            continue
        bucket = pages_acc.get(page_number)
        if bucket is None:
            bucket = {
                'page_number': page_number,
                'count': 0,
                'surah': surah,
                'ayah': ayah,
            }
            pages_acc[page_number] = bucket
        bucket['count'] += 1
        # Keep the first (ayah-order) locus as a jump hint for the page chip.
        if (surah, ayah) < (bucket['surah'], bucket['ayah']):
            bucket['surah'], bucket['ayah'] = surah, ayah

    pages = sorted(pages_acc.values(), key=lambda p: p['page_number'])
    return jsonify({
        'edition': edition,
        'changes': changes,
        'pages': pages,
        'count': len(changes),
        'page_count': len(pages),
    })


@editor_bp.route('/api/mushaf-editor/publish', methods=['POST'])
@require_admin
def publish_editor_edition():
    """Promote all draft marks for an edition to published (public readers)."""
    data = request.get_json(silent=True) or {}
    edition = (data.get('edition') or '').strip()
    if edition not in CLOUD_EDITOR_EDITIONS:
        return jsonify({'error': 'invalid edition'}), 400
    user = current_editor()
    try:
        pending = sb.pending_publish_diff(edition)
        count = sb.publish_edition(
            edition,
            actor_id=user['id'] if user else None,
            actor_name=user['name'] if user else None,
        )
        invalidate_cloud_waqf_cache(edition)
        return jsonify({
            'ok': True,
            'edition': edition,
            'published': count,
            'pending_before': len(pending),
        })
    except sb.SupabaseEditorError as e:
        logger.error('publish failed: %s', e)
        return jsonify({'error': 'publish failed'}), 503


@editor_bp.route('/api/mushaf-editor/audit', methods=['GET'])
@require_editor
def editor_audit_feed():
    edition = (request.args.get('edition') or '').strip() or None
    if edition and edition not in EDITOR_EDITIONS:
        return jsonify({'error': 'invalid edition'}), 400
    if not sb.is_configured():
        return jsonify({'items': []})
    try:
        items = sb.recent_audit(edition=edition, limit=40)
        return jsonify({'items': items})
    except sb.SupabaseEditorError as e:
        logger.error('audit feed failed: %s', e)
        return jsonify({'error': 'audit unavailable'}), 503
