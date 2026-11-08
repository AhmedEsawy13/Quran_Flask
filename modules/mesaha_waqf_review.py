"""In-app review of the Mesaha waqf signs read from the page scans (pipeline/paw_split/mesaha_waqf.py).

The cards are built on the machine that holds the scans (mesaha_waqf_review.py ->
data/mesaha-waqf/<set>/data.json + cards/*.jpg, committed). Each decision is the sign actually printed on
the word ('' = none), saved like every other review decision in ``waqf_mark_review_decisions``
under «المساحة · فحص» (word_id = the Mesaha word_index): in the cloud when it is configured,
otherwise in the local review store. One decision per word, whichever card set showed it.
"""
from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path

from flask import abort, jsonify, render_template, request, send_from_directory

from core import supabase_editor as sb
from core.blueprints import editor_bp
from core.config import MESAHA_WAQF_CARDS_DIR, MUSHAF_WAQF_DATABASE, SHAMARLY_WAQF_CARDS_DIR
from core.db import connect as _sqlite_connect
from modules import waqf_mark_review as wmr
from modules.editor_auth import current_editor, require_editor

logger = logging.getLogger(__name__)

DECISION_EDITION = 'المساحة · فحص'
SIGNS = frozenset({'ص', 'ق', 'ج', 'م', 'لا', 'س', 'ع'})
GROUPS = ('A', 'S', 'B', 'N', 'C')          # S = the random sample of A
_SET_NAME = re.compile(r'^(mesaha|shamarly)-waqf[\w-]*$')
_CARD_NAME = re.compile(r'^[\w-]{1,48}\.jpg$')
DEFAULT_SET = 'mesaha-waqf-all'      # every reviewed page; the pilot sets stay for reference


def _sets_root() -> Path:
    return Path(MESAHA_WAQF_CARDS_DIR)


def _family(name: str) -> str:
    return 'shamarly' if (name or '').startswith('shamarly') else 'mesaha'


def _family_root(family: str) -> Path:
    return Path(SHAMARLY_WAQF_CARDS_DIR) if family == 'shamarly' else _sets_root()


def _set_dir(name: str) -> Path:
    return _family_root(_family(name)) / name


def available_sets(family: str = 'mesaha') -> list[str]:
    """The card sets on this server: the Mesaha ones by default, or the Shamarly ones (family='shamarly')."""
    root = _family_root(family)
    if not root.is_dir():
        return []
    return sorted(p.name for p in root.iterdir()
                  if _SET_NAME.match(p.name) and _family(p.name) == family and (p / 'data.json').is_file())


def set_edition(data: dict) -> str:
    """The decision store a card set writes to: «المساحة · فحص» for the 1924 print unless the set names
    another (the 1952 print's cards keep their own decisions on the same words)."""
    return str(data.get('decision_edition') or DECISION_EDITION)


def card_edition(data: dict, card: dict) -> str:
    """A set can hold cards of several prints («decision_edition_by_print»): each saves under «<print> · فحص»."""
    if data.get('decision_edition_by_print') and card.get('print'):
        return f"{card['print']} · فحص"
    return set_edition(data)


def set_decisions(data: dict) -> dict[str, dict]:
    """{card id: decision row} for every decided card of the set."""
    out, cache = {}, {}
    for c in data['cards']:
        ed = card_edition(data, c)
        if ed not in cache:
            cache[ed] = load_decisions(ed)
        row = cache[ed].get((int(c['page']), int(c['word_index'])))
        if row:
            out[c['id']] = row
    return out


def _load_set(name: str) -> dict | None:
    if not _SET_NAME.match(name or ''):
        return None
    path = _set_dir(name) / 'data.json'
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding='utf-8'))


def _in_group(data: dict, card: dict, group: str) -> bool:
    if group == 'S':
        return card['id'] in set(data.get('a_sample') or [])
    return card['group'] == group


# --- decision store: the cloud table when configured, the local review store otherwise ---

def _cloud() -> bool:
    return sb.is_configured()


def load_decisions(edition: str = DECISION_EDITION) -> dict[tuple[int, int], dict]:
    if _cloud():
        rows = sb.list_mark_review_decisions_all(edition)
    else:
        if not os.path.isfile(wmr.MARK_REVIEW_STORE_DATABASE):
            return {}
        conn = _sqlite_connect(wmr.MARK_REVIEW_STORE_DATABASE, readonly=True)
        try:
            if not wmr._local_table_exists(conn, 'waqf_mark_review_decisions'):
                return {}
            cur = conn.execute(
                'SELECT page_number, word_id, decision, our_mark, correct_mark, updated_at '
                'FROM waqf_mark_review_decisions WHERE edition = ?', (edition,))
            cols = [c[0] for c in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        finally:
            conn.close()
    return {(int(r['page_number']), int(r['word_id'])): r for r in rows}


def _row(card: dict, mark: str, edition: str = DECISION_EDITION) -> dict:
    s, a = (int(x) for x in card['key'].split(':')[:2]) if card.get('key') else (None, None)
    model = card.get('model') or ''
    return {'edition': edition, 'page_number': int(card['page']), 'word_id': int(card['word_index']),
            'decision': 'ok' if mark == model else 'wrong', 'our_mark': model, 'correct_mark': mark,
            'surah': s, 'ayah': a, 'word_text': card.get('text') or ''}


def save_decisions(rows: list[dict]) -> None:
    if not rows:
        return
    if _cloud():
        user = current_editor()
        sb.upsert_mark_review_decisions_batch(rows, updated_by=user['id'] if user else None)
        return
    for r in rows:
        wmr._save_decision_local(r['edition'], r['page_number'], r['word_id'], r['decision'], r['our_mark'],
                                 r['correct_mark'], r['surah'], r['ayah'], r['word_text'])


def delete_decision(card: dict, edition: str = DECISION_EDITION) -> None:
    if _cloud():
        sb.delete_mark_review_decision(edition=edition, page_number=int(card['page']),
                                       word_id=int(card['word_index']))
    else:
        wmr._delete_decision_local(edition, int(card['page']), int(card['word_index']))


def _decision_view(row: dict | None) -> dict | None:
    return {'mark': row.get('correct_mark') or '', 'at': row.get('updated_at')} if row else None


# --- routes ---

def _body_set() -> tuple[dict, dict | None]:
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return {}, None
    return body, _load_set(str(body.get('set') or ''))


@editor_bp.route('/mushaf-editor/mesaha-waqf')
def mesaha_waqf_review_page():
    return render_template('mesaha_waqf_review.html', family='mesaha', title='وقوف المساحة',
                           path='/mushaf-editor/mesaha-waqf',
                           description='مراجعة علامات الوقف التي قرأها النموذج من صفحات مصحف المساحة، وتُحفظ القرارات في السحابة.')


@editor_bp.route('/mushaf-editor/shamarly-waqf')
def shamarly_waqf_review_page():
    return render_template('mesaha_waqf_review.html', family='shamarly', title='علامات الشمرلي الناقصة',
                           path='/mushaf-editor/shamarly-waqf',
                           description='علامات وقف في صفحات الشمرلي لم يجدها المُنشئ فلا تُخفى: حدّد المطبوع منها، وتُحفظ القرارات في السحابة.')


@editor_bp.route('/api/mushaf-editor/mesaha-waqf', methods=['GET'])
@require_editor
def mesaha_waqf_cards():
    requested = request.args.get('set') or ''
    family = _family(requested) if requested else ('shamarly' if request.args.get('family') == 'shamarly' else 'mesaha')
    sets = available_sets(family)
    name = requested or (DEFAULT_SET if DEFAULT_SET in sets else (sets[0] if sets else ''))
    data = _load_set(name)
    if data is None:
        what = 'الشمرلي' if family == 'shamarly' else 'المساحة'
        return jsonify({'error': 'no_set', 'sets': sets,
                        'message': f'لا توجد بطاقات {what} على هذا الخادم — تُبنى على الجهاز الذي فيه صور الصفحات.'}), 404
    try:
        decisions = set_decisions(data)
    except sb.SupabaseEditorError as exc:
        logger.error('mesaha waqf decisions read failed: %s', exc)
        return jsonify({'error': 'cloud unavailable'}), 503
    for c in data['cards']:
        c['decision'] = _decision_view(decisions.get(c['id']))
    return jsonify({'set': name, 'sets': sets, 'store': 'cloud' if _cloud() else 'local',
                    'pages': data.get('pages', []), 'a_sample': data.get('a_sample', []), 'cards': data['cards'],
                    'note': data.get('note') or '', 'title': data.get('title') or '',
                    'groups': data.get('groups') or {}})


@editor_bp.route('/api/mushaf-editor/mesaha-waqf/card', methods=['GET'])
@require_editor
def mesaha_waqf_card_image():
    name, f = request.args.get('set') or '', request.args.get('f') or ''
    if not _SET_NAME.match(name) or not _CARD_NAME.match(f):
        abort(404)
    return send_from_directory(_set_dir(name) / 'cards', f, max_age=3600)


@editor_bp.route('/api/mushaf-editor/mesaha-waqf/decision', methods=['POST', 'DELETE'])
@require_editor
def mesaha_waqf_decision():
    """POST {set, id, mark} ('' = no sign printed); DELETE {set, id} undoes."""
    body, data = _body_set()
    if data is None:
        return jsonify({'error': 'unknown set'}), 404
    card = next((c for c in data['cards'] if c['id'] == body.get('id')), None)
    if card is None:
        return jsonify({'error': 'unknown card'}), 404
    try:
        if request.method == 'DELETE':
            delete_decision(card, card_edition(data, card))
            return jsonify({'ok': True, 'decision': None})
        mark = str(body.get('mark') or '').strip()
        if mark and mark not in SIGNS:
            return jsonify({'error': 'invalid mark'}), 400
        save_decisions([_row(card, mark, card_edition(data, card))])
    except sb.SupabaseEditorError as exc:
        logger.error('mesaha waqf decision failed: %s', exc)
        return jsonify({'error': 'cloud write failed'}), 503
    return jsonify({'ok': True, 'decision': {'mark': mark}})


@editor_bp.route('/api/mushaf-editor/mesaha-waqf/accept', methods=['POST'])
@require_editor
def mesaha_waqf_accept():
    """POST {set, group}: every undecided card of the group takes the model's reading ('' when none)."""
    body, data = _body_set()
    if data is None:
        return jsonify({'error': 'unknown set'}), 404
    if data.get('no_accept'):
        return jsonify({'error': 'bulk accept is off for this set'}), 400
    group = str(body.get('group') or '')
    if group not in (data.get('groups') or {k: 1 for k in GROUPS}):
        return jsonify({'error': 'invalid group'}), 400
    try:
        decided = set_decisions(data)
        rows = [_row(c, c.get('model') or '', card_edition(data, c)) for c in data['cards']
                if _in_group(data, c, group) and c['id'] not in decided]
        save_decisions(rows)
    except sb.SupabaseEditorError as exc:
        logger.error('mesaha waqf accept failed: %s', exc)
        return jsonify({'error': 'cloud write failed'}), 503
    return jsonify({'ok': True, 'accepted': len(rows)})


@editor_bp.route('/api/mushaf-editor/mesaha-waqf/import', methods=['POST'])
@require_editor
def mesaha_waqf_import():
    """POST {set, decisions: {card id: mark}} — the JSON exported by the earlier static review page."""
    body, data = _body_set()
    if data is None:
        return jsonify({'error': 'unknown set'}), 404
    given = body.get('decisions')
    if not isinstance(given, dict):
        return jsonify({'error': 'decisions object required'}), 400
    cards = {c['id']: c for c in data['cards']}
    rows, skipped = [], 0
    for cid, mark in given.items():
        mark = '' if mark is None else str(mark).strip()
        if cid not in cards or (mark and mark not in SIGNS):
            skipped += 1
            continue
        rows.append(_row(cards[cid], mark))
    try:
        save_decisions(rows)
    except sb.SupabaseEditorError as exc:
        logger.error('mesaha waqf import failed: %s', exc)
        return jsonify({'error': 'cloud write failed'}), 503
    return jsonify({'ok': True, 'imported': len(rows), 'skipped': skipped})


# --- applying the reviewed Shamarly cards to the local «الشمرلي» column ---

def _apply_gate(data: dict | None) -> tuple[bool, str]:
    """(allowed, why not). The column is a tracked SQLite file: only a writable local copy changes, and where a
    cloud editor is configured only an admin may do it."""
    if data is None or _family(data.get('set') or '') != 'shamarly':
        return False, 'not a Shamarly card set'
    if sb.is_configured():
        user = current_editor()
        if not user or user.get('role') != 'admin':
            return False, 'admin required'
    if not os.access(MUSHAF_WAQF_DATABASE, os.W_OK):
        return False, 'the waqf database is read-only on this server — apply on the machine that holds it'
    return True, ''


def _shamarly_plan(name: str, data: dict) -> dict:
    from pipeline import apply_shamarly_review as asr
    return asr.build_plan(data, set_decisions(data), MUSHAF_WAQF_DATABASE)


def _plan_view(plan: dict) -> dict:
    return {'valid': plan['valid'], 'plan_digest': plan['content_digest'], 'summary': plan['summary'],
            'validation': plan['validation'], 'changes': plan['changes']}


@editor_bp.route('/api/mushaf-editor/shamarly-waqf/apply-plan', methods=['GET'])
@require_editor
def shamarly_waqf_apply_plan():
    """What applying the reviewed (أ) cards would change in the column; writes nothing."""
    name = request.args.get('set') or ''
    data = _load_set(name)
    if data is None or _family(name) != 'shamarly':
        return jsonify({'error': 'unknown set'}), 404
    data['set'] = name
    allowed, why = _apply_gate(data)
    try:
        plan = _shamarly_plan(name, data)
    except sb.SupabaseEditorError as exc:
        logger.error('shamarly waqf plan failed: %s', exc)
        return jsonify({'error': 'cloud unavailable'}), 503
    return jsonify({'can_apply': allowed, 'reason': why, 'plan': _plan_view(plan)})


@editor_bp.route('/api/mushaf-editor/shamarly-waqf/apply', methods=['POST'])
@require_editor
def shamarly_waqf_apply():
    """POST {set, plan_digest}: apply the plan the reviewer saw, if nothing changed since."""
    body = request.get_json(silent=True) or {}
    name = str(body.get('set') or '')
    data = _load_set(name)
    if data is None or _family(name) != 'shamarly':
        return jsonify({'error': 'unknown set'}), 404
    data['set'] = name
    allowed, why = _apply_gate(data)
    if not allowed:
        return jsonify({'error': why}), 403
    from pipeline import apply_shamarly_review as asr
    from pipeline.sync_published_waqf import SyncError
    try:
        plan = _shamarly_plan(name, data)
        if plan['content_digest'] != body.get('plan_digest'):
            return jsonify({'error': 'stale', 'message': 'القرارات أو العمود تغيّرت بعد المعاينة — أعد المعاينة.'}), 409
        if not plan['valid']:
            return jsonify({'error': 'invalid plan', 'validation': plan['validation']}), 400
        if not plan['changes']:
            return jsonify({'ok': True, 'applied': 0})
        result = asr.apply(plan, MUSHAF_WAQF_DATABASE)
    except sb.SupabaseEditorError as exc:
        logger.error('shamarly waqf apply failed: %s', exc)
        return jsonify({'error': 'cloud unavailable'}), 503
    except SyncError as exc:
        return jsonify({'error': 'apply refused', 'message': str(exc)}), 409
    return jsonify({'ok': True, 'applied': result['changes_applied'], 'backup': result.get('backup'),
                    'research_caches_stale': True})
