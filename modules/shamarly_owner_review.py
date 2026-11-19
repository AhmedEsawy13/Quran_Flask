"""«ملكية كلمات الشمرلي»: reviewers judge which PDF outlines ShemrlyMushaf gave each doubtful word.

ShemrlyMushaf exports the cards (scripts/owner_review.py export -> data/shamarly-owner/<set>/data.json +
cards/*.jpg, committed): each is a word on its line, its owned ink red, then the rest faded, with the line's
ownership at export time. A decision is right / wrong (+ reasons) / the word's mark belongs to the previous or
the next word / not sure, plus a note. It is saved in ``waqf_mark_review_decisions`` under «الشمرلي · ملكية»
(page_number = page, word_id = the book-global word index, decision ok|wrong, our_mark = the ownership digest,
correct_mark = JSON {v, r, n, set, m}): in the cloud when configured, otherwise in an ignored local SQLite store.
The line editor reads the card's whole line (lines/<id>.json) and saves outline moves with the verdict:
m = {outline id: word index on the line, or "up" / "down" for the line above / below}. ShemrlyMushaf pulls them
back into its word_check_verdicts and, when asked, applies the moves (scripts/owner_review.py sync).
"""
from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
from pathlib import Path

from flask import abort, jsonify, render_template, request, send_from_directory

from core import supabase_editor as sb
from core.blueprints import editor_bp
from core.config import SHAMARLY_OWNER_CARDS_DIR, SHAMARLY_OWNER_LOCAL_STORE
from modules.editor_auth import current_editor, require_editor

logger = logging.getLogger(__name__)

EDITION = 'الشمرلي · ملكية'
VERDICTS = ('right', 'wrong', 'prev', 'next', 'unsure')
REASONS = ('missing_letter', 'missing_mark', 'extra_letter', 'extra_mark', 'waqf')
_SET_NAME = re.compile(r'^shamarly-owner[\w-]*$')
_CARD_NAME = re.compile(r'^[\w-]{1,48}\.jpg$')
NOTE_MAX = 500


def _root() -> Path:
    return Path(SHAMARLY_OWNER_CARDS_DIR)


def _store() -> str:
    return SHAMARLY_OWNER_LOCAL_STORE


def available_sets() -> list[str]:
    root = _root()
    if not root.is_dir():
        return []
    return sorted(p.name for p in root.iterdir() if _SET_NAME.match(p.name) and (p / 'data.json').is_file())


def _load_set(name: str) -> dict | None:
    if not _SET_NAME.match(name or ''):
        return None
    path = _root() / name / 'data.json'
    return json.loads(path.read_text(encoding='utf-8')) if path.is_file() else None


# --- decision store -----------------------------------------------------------------------------------------

def _local(write: bool = False) -> sqlite3.Connection | None:
    path = _store()
    if not write and not os.path.isfile(path):
        return None
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("""CREATE TABLE IF NOT EXISTS waqf_mark_review_decisions (
        edition TEXT NOT NULL, page_number INTEGER NOT NULL, word_id INTEGER NOT NULL, decision TEXT NOT NULL,
        our_mark TEXT, correct_mark TEXT, surah INTEGER, ayah INTEGER, word_text TEXT, updated_by TEXT,
        updated_at TEXT, PRIMARY KEY (edition, page_number, word_id))""")
    return conn


def load_decisions() -> dict[tuple[int, int], dict]:
    if sb.is_configured():
        rows = sb.list_mark_review_decisions_all(EDITION)
    else:
        conn = _local()
        if conn is None:
            return {}
        try:
            rows = [dict(r) for r in conn.execute(
                'SELECT * FROM waqf_mark_review_decisions WHERE edition = ?', (EDITION,))]
        finally:
            conn.close()
    return {(int(r['page_number']), int(r['word_id'])): r for r in rows}


def parse(row: dict | None) -> dict | None:
    """The reviewer's verdict of a stored row: {v, r, n, set} or None."""
    if not row:
        return None
    try:
        v = json.loads(row.get('correct_mark') or '')
    except ValueError:
        return None
    return v if isinstance(v, dict) and v.get('v') in VERDICTS else None


def load_line(set_name: str, card: dict) -> dict | None:
    path = _root() / set_name / 'lines' / f"{card['id']}.json"
    return json.loads(path.read_text(encoding='utf-8')) if path.is_file() else None


def check_moves(line: dict | None, moves: dict) -> dict[str, int | str]:
    """The moves that change something, validated against the exported line: known outlines, a word of the line
    (or up / down), and no word left without ink."""
    if not moves:
        return {}
    if line is None:
        raise ValueError('this card has no line')
    owners = {o: (ws or [None])[0] for o, ws in line['owners'].items()}
    ids = {c['id'] for c in line['components']}
    words = {int(w['word_index']) for w in line['words']}
    out: dict[str, int | str] = {}
    for outline, to in moves.items():
        if outline not in ids:
            raise ValueError(f'unknown outline {outline}')
        if to in ('up', 'down') and (line.get('neighbours') or {}).get(to) is False:
            raise ValueError(f'no words on the line {"above" if to == "up" else "below"}')
        if to not in ('up', 'down'):
            try:
                to = int(to)
            except (TypeError, ValueError):
                raise ValueError(f'bad target for {outline}') from None
            if to not in words:
                raise ValueError(f'word {to} is not on this line')
        if to != owners.get(outline):
            out[outline] = to
    after = {o: out.get(o, w) for o, w in owners.items()}
    holes = {c['id'] for c in line['components'] if c.get('hole_of')}
    bare = [w for w in words if not any(v == w and o not in holes for o, v in after.items())
            and any(v == w for v in owners.values())]
    if bare:
        raise ValueError(f'word {bare[0]} would have no ink')
    return out


def make_row(set_name: str, card: dict, verdict: str, reasons: list[str], note: str,
             moves: dict | None = None) -> dict:
    if verdict not in VERDICTS:
        raise ValueError('invalid verdict')
    reasons = [r for r in REASONS if r in reasons] if verdict == 'wrong' else []
    value = {'v': verdict, 'r': reasons, 'n': (note or '').strip()[:NOTE_MAX], 'set': set_name}
    if moves:
        value['m'] = moves
    return {'edition': EDITION, 'page_number': int(card['page']), 'word_id': int(card['word_index']),
            'decision': 'ok' if verdict == 'right' else 'wrong', 'our_mark': card.get('owners_digest') or '',
            'correct_mark': json.dumps(value, ensure_ascii=False), 'word_text': card.get('text') or ''}


def save(row: dict) -> None:
    user = current_editor()
    if sb.is_configured():
        actor = user['id'] if user else None
        sb.upsert_mark_review_decision(updated_by=actor, surah=None, ayah=None, **{
            k: row[k] for k in ('edition', 'page_number', 'word_id', 'decision', 'our_mark', 'correct_mark',
                                'word_text')})
        sb.append_audit(actor_id=actor, actor_name=(user or {}).get('name'), action='mark_review_decision',
                        edition=EDITION, page_number=row['page_number'], word_id=row['word_id'],
                        old_symbol=row['our_mark'], new_symbol=json.loads(row['correct_mark'])['v'],
                        meta={'decision': row['decision'], 'word_text': row['word_text'], 'tool': 'shamarly-owner'})
        return
    conn = _local(write=True)
    try:
        conn.execute(
            'INSERT INTO waqf_mark_review_decisions (edition, page_number, word_id, decision, our_mark, correct_mark,'
            ' word_text, updated_by, updated_at) VALUES (?,?,?,?,?,?,?,?,datetime("now")) '
            'ON CONFLICT(edition, page_number, word_id) DO UPDATE SET decision=excluded.decision, '
            'our_mark=excluded.our_mark, correct_mark=excluded.correct_mark, word_text=excluded.word_text, '
            'updated_by=excluded.updated_by, updated_at=excluded.updated_at',
            (row['edition'], row['page_number'], row['word_id'], row['decision'], row['our_mark'],
             row['correct_mark'], row['word_text'], (user or {}).get('id') or 'local'))
        conn.commit()
    finally:
        conn.close()


def delete(card: dict) -> None:
    page, wi = int(card['page']), int(card['word_index'])
    if sb.is_configured():
        sb.delete_mark_review_decision(edition=EDITION, page_number=page, word_id=wi)
        return
    conn = _local()
    if conn is None:
        return
    try:
        conn.execute('DELETE FROM waqf_mark_review_decisions WHERE edition=? AND page_number=? AND word_id=?',
                     (EDITION, page, wi))
        conn.commit()
    finally:
        conn.close()


def _view(set_name: str, card: dict, row: dict | None) -> dict | None:
    v = parse(row)
    if v is None:
        return None
    return {'verdict': v['v'], 'reasons': v.get('r') or [], 'note': v.get('n') or '', 'moves': v.get('m') or {},
            'at': row.get('updated_at'),
            'other_set': v.get('set') != set_name,
            'stale': bool(row.get('our_mark')) and row.get('our_mark') != card.get('owners_digest')}


# --- routes -------------------------------------------------------------------------------------------------

@editor_bp.route('/mushaf-editor/shamarly-owner')
def shamarly_owner_review_page():
    return render_template('shamarly_owner_review.html')


@editor_bp.route('/api/mushaf-editor/shamarly-owner', methods=['GET'])
@require_editor
def shamarly_owner_cards():
    sets = available_sets()
    name = request.args.get('set') or (sets[-1] if sets else '')
    data = _load_set(name)
    if data is None:
        return jsonify({'error': 'no_set', 'sets': sets,
                        'message': 'لا توجد بطاقات ملكية على هذا الخادم — تُصدَّر من مشروع ShemrlyMushaf.'}), 404
    try:
        decisions = load_decisions()
    except sb.SupabaseEditorError as exc:
        logger.error('shamarly owner decisions read failed: %s', exc)
        return jsonify({'error': 'cloud unavailable'}), 503
    cards = []
    for c in data['cards']:
        cards.append({k: c.get(k) for k in ('id', 'page', 'line', 'word_index', 'text', 'prev', 'next', 'why')}
                     | {'has_line': (_root() / name / 'lines' / f"{c['id']}.json").is_file(), 'decision': _view(name, c, decisions.get((int(c['page']), int(c['word_index']))))})
    return jsonify({'set': name, 'sets': sets, 'store': 'cloud' if sb.is_configured() else 'local',
                    'title': data.get('title') or '', 'note': data.get('note') or '', 'cards': cards})


@editor_bp.route('/api/mushaf-editor/shamarly-owner/card', methods=['GET'])
@require_editor
def shamarly_owner_card_image():
    name, f = request.args.get('set') or '', request.args.get('f') or ''
    if not _SET_NAME.match(name) or not _CARD_NAME.match(f):
        abort(404)
    return send_from_directory(_root() / name / 'cards', f, max_age=3600)


@editor_bp.route('/api/mushaf-editor/shamarly-owner/line', methods=['GET'])
@require_editor
def shamarly_owner_line():
    """?set&id: the card's whole line as exported (outlines, word cells, owners by word index)."""
    name = request.args.get('set') or ''
    data = _load_set(name)
    card = next((c for c in (data or {}).get('cards', []) if c['id'] == request.args.get('id')), None)
    line = load_line(name, card) if card else None
    if line is None:
        return jsonify({'error': 'no line'}), 404
    return jsonify(line | {'word_index': card['word_index']})


@editor_bp.route('/api/mushaf-editor/shamarly-owner/decision', methods=['POST', 'DELETE'])
@require_editor
def shamarly_owner_decision():
    """POST {set, id, verdict: right|wrong|prev|next|unsure, reasons: [...], note, moves: {outline: wi|up|down}};
    DELETE {set, id} undoes. Moves made in the line editor are kept with the verdict (empty moves clear them)."""
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify({'error': 'json body required'}), 400
    name = str(body.get('set') or '')
    data = _load_set(name)
    if data is None:
        return jsonify({'error': 'unknown set'}), 404
    card = next((c for c in data['cards'] if c['id'] == body.get('id')), None)
    if card is None:
        return jsonify({'error': 'unknown card'}), 404
    try:
        if request.method == 'DELETE':
            delete(card)
            return jsonify({'ok': True, 'decision': None})
        reasons = [str(r) for r in (body.get('reasons') or []) if isinstance(r, str)]
        moves = body.get('moves')
        if moves is not None and not isinstance(moves, dict):
            return jsonify({'error': 'moves must be an object'}), 400
        try:
            if moves is None:                    # a verdict alone keeps the moves saved earlier
                moves = (parse(load_decisions().get((int(card['page']), int(card['word_index'])))) or {}).get('m') or {}
            moves = check_moves(load_line(name, card), moves)
            row = make_row(name, card, str(body.get('verdict') or ''), reasons, str(body.get('note') or ''), moves)
        except ValueError as exc:
            return jsonify({'error': 'invalid', 'message': str(exc)}), 400
        save(row)
    except sb.SupabaseEditorError as exc:
        logger.error('shamarly owner decision failed: %s', exc)
        return jsonify({'error': 'cloud write failed'}), 503
    return jsonify({'ok': True, 'decision': _view(name, card, row)})
