"""In-app review of the Mesaha waqf signs read from the page scans (pipeline/paw_split/mesaha_waqf.py).

The cards are built on the machine that holds the scans (mesaha_waqf_review.py ->
artifacts/cv-waqf/<set>/data.json + cards/*.jpg). Each decision is the sign actually printed on
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
from core.db import connect as _sqlite_connect
from modules import waqf_mark_review as wmr
from modules.editor_auth import current_editor, require_editor

logger = logging.getLogger(__name__)

DECISION_EDITION = 'المساحة · فحص'
SIGNS = frozenset({'ص', 'ق', 'ج', 'م', 'لا', 'س', 'ع'})
GROUPS = ('A', 'S', 'B', 'N', 'C')          # S = the random sample of A
_SET_NAME = re.compile(r'^mesaha-waqf[\w-]*$')
_CARD_NAME = re.compile(r'^\d{3}-\d+\.jpg$')
DEFAULT_SET = 'mesaha-waqf-pilot'


def _sets_root() -> Path:
    from pipeline.cv_waqf.config import ARTIFACTS_ROOT
    return ARTIFACTS_ROOT


def available_sets() -> list[str]:
    root = _sets_root()
    if not root.is_dir():
        return []
    return sorted(p.name for p in root.iterdir() if _SET_NAME.match(p.name) and (p / 'data.json').is_file())


def _load_set(name: str) -> dict | None:
    if not _SET_NAME.match(name or ''):
        return None
    path = _sets_root() / name / 'data.json'
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


def load_decisions() -> dict[tuple[int, int], dict]:
    if _cloud():
        rows = sb.list_mark_review_decisions_all(DECISION_EDITION)
    else:
        if not os.path.isfile(wmr.MARK_REVIEW_STORE_DATABASE):
            return {}
        conn = _sqlite_connect(wmr.MARK_REVIEW_STORE_DATABASE, readonly=True)
        try:
            if not wmr._local_table_exists(conn, 'waqf_mark_review_decisions'):
                return {}
            cur = conn.execute(
                'SELECT page_number, word_id, decision, our_mark, correct_mark, updated_at '
                'FROM waqf_mark_review_decisions WHERE edition = ?', (DECISION_EDITION,))
            cols = [c[0] for c in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        finally:
            conn.close()
    return {(int(r['page_number']), int(r['word_id'])): r for r in rows}


def _row(card: dict, mark: str) -> dict:
    s, a = (int(x) for x in card['key'].split(':')[:2]) if card.get('key') else (None, None)
    model = card.get('model') or ''
    return {'edition': DECISION_EDITION, 'page_number': int(card['page']), 'word_id': int(card['word_index']),
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


def delete_decision(card: dict) -> None:
    if _cloud():
        sb.delete_mark_review_decision(edition=DECISION_EDITION, page_number=int(card['page']),
                                       word_id=int(card['word_index']))
    else:
        wmr._delete_decision_local(DECISION_EDITION, int(card['page']), int(card['word_index']))


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
    return render_template('mesaha_waqf_review.html')


@editor_bp.route('/api/mushaf-editor/mesaha-waqf', methods=['GET'])
@require_editor
def mesaha_waqf_cards():
    sets = available_sets()
    name = request.args.get('set') or (DEFAULT_SET if DEFAULT_SET in sets else (sets[0] if sets else ''))
    data = _load_set(name)
    if data is None:
        return jsonify({'error': 'no_set', 'sets': sets,
                        'message': 'لا توجد بطاقات المساحة على هذا الخادم — تُبنى على الجهاز الذي فيه صور الصفحات.'}), 404
    try:
        decisions = load_decisions()
    except sb.SupabaseEditorError as exc:
        logger.error('mesaha waqf decisions read failed: %s', exc)
        return jsonify({'error': 'cloud unavailable'}), 503
    for c in data['cards']:
        c['decision'] = _decision_view(decisions.get((int(c['page']), int(c['word_index']))))
    return jsonify({'set': name, 'sets': sets, 'store': 'cloud' if _cloud() else 'local',
                    'pages': data.get('pages', []), 'a_sample': data.get('a_sample', []), 'cards': data['cards']})


@editor_bp.route('/api/mushaf-editor/mesaha-waqf/card', methods=['GET'])
@require_editor
def mesaha_waqf_card_image():
    name, f = request.args.get('set') or '', request.args.get('f') or ''
    if not _SET_NAME.match(name) or not _CARD_NAME.match(f):
        abort(404)
    return send_from_directory(_sets_root() / name / 'cards', f, max_age=3600)


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
            delete_decision(card)
            return jsonify({'ok': True, 'decision': None})
        mark = str(body.get('mark') or '').strip()
        if mark and mark not in SIGNS:
            return jsonify({'error': 'invalid mark'}), 400
        save_decisions([_row(card, mark)])
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
    group = str(body.get('group') or '')
    if group not in GROUPS:
        return jsonify({'error': 'invalid group'}), 400
    try:
        decided = load_decisions()
        rows = [_row(c, c.get('model') or '') for c in data['cards']
                if _in_group(data, c, group) and (int(c['page']), int(c['word_index'])) not in decided]
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
