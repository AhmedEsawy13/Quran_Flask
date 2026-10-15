"""In-editor review of a whole-book CV audit (``book-audit`` + ``book-review``).

The queue is ``artifacts/cv-waqf/<id>-audit/queue.json`` on the machine that ran
the audit, so this page works on the local cloud server (:5002), not on Vercel.
For the cloud editions (قطر/الكويت/البحرين) each decision writes the word's mark as a
Supabase draft (the same path as a click in /mushaf-editor, so it shows in the publish
diff) and records the decision in ``waqf_mark_review_decisions`` so every reviewer sees it.

الشمرلي and المدينة القديم keep their marks in the local mushaf_waqf.db only, so they are
REVIEW-ONLY here: the decision is recorded (under ``<edition> · فحص``, apart from the
Shamarly phone checklist, which keys the same table by its own word numbering) and
nothing is written; the agreed changes are applied to the local column afterwards.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from flask import abort, jsonify, render_template, request, send_from_directory

from core import supabase_editor as sb
from core.blueprints import editor_bp
from core.config import CLOUD_EDITOR_EDITIONS
from modules.editor import _EDITOR_SYMBOLS, _get_or_set_word_waqf_cloud
from modules.editor_auth import current_editor, require_editor
from modules.layouts import _get_dk_layout_word_map

logger = logging.getLogger(__name__)

REVIEW_ONLY_EDITIONS = frozenset({'الشمرلي', 'المدينة القديم'})
REVIEW_EDITIONS = CLOUD_EDITOR_EDITIONS | REVIEW_ONLY_EDITIONS
ACTIONABLE_TABS = {'shift', 'shift_unsure', 'add', 'maybe', 'differs', 'missed'}
_CROP_NAME = re.compile(r'^[\w.-]+\.(?:jpg|png)$')


def _audit_dir(edition: str) -> Path | None:
    from pipeline.cv_waqf.config import ARTIFACTS_ROOT, EDITIONS
    spec = EDITIONS.get(edition)
    return ARTIFACTS_ROOT / f'{spec.id}-audit' if spec else None


def _load_queue(edition: str) -> dict | None:
    d = _audit_dir(edition)
    path = d / 'queue.json' if d else None
    if not path or not path.is_file():
        return None
    return json.loads(path.read_text(encoding='utf-8'))


def _split(key: str) -> tuple[int, int, int]:
    s, a, w = (int(x) for x in key.split(':'))
    return s, a, w


def _decision_edition(edition: str) -> str:
    return f'{edition} · فحص' if edition in REVIEW_ONLY_EDITIONS else edition


def _review_word_id(edition: str, key: str) -> int | None:
    """Decision key for a card's word: the QPC layout id for the cloud editions; for the
    review-only prints (their own script and word counts) a plain surah/ayah/word code."""
    if edition in REVIEW_ONLY_EDITIONS:
        s, a, w = _split(key)
        return s * 1_000_000 + a * 1_000 + w
    return _layout_word_id(key)


def _layout_word_id(key: str) -> int | None:
    """Audit word_key (surah:ayah:layout position) → global QPC layout id."""
    s, a, w = _split(key)
    first = _get_dk_layout_word_map()['first_id'].get((s, a))
    return None if first is None else first + w - 1


def targets(item: dict, choice: str, symbol: str = '') -> dict[str, str]:
    """{word_key: mark} the cloud should hold after a decision.

    image — the scan is right; db — the DB was right (also what undo restores);
    set — the reviewer's own sign on the card's word.
    """
    tab, key, db, cv = item['tab'], item['word_key'], item.get('db') or '', item.get('cv') or ''
    moved = tab in ('shift', 'shift_unsure') and item.get('from_key')
    if choice == 'db':
        return {key: '', item['from_key']: db} if moved else {key: db if tab in ('differs', 'missed') else ''}
    if choice == 'set':
        return {key: symbol}
    if moved:
        return {item['from_key']: '', key: db}
    return {key: '' if tab == 'missed' else cv}


def _cloud_marks(edition: str, keys: list[str]) -> dict[str, str]:
    """{word_key: mark} from the cloud, draft over published."""
    ayahs = sorted({_split(k)[:2] for k in keys})
    if not ayahs:
        return {}
    draft, published = sb.fetch_draft_and_published_for_ayahs(edition=edition, ayah_keys=ayahs)
    merged: dict[tuple[int, int, int], str] = {}
    for rows in (published, draft):
        for r in rows:
            merged[(int(r['surah']), int(r['ayah']), int(r['token_index']))] = (r.get('symbol') or '').strip()
    out = {}
    for k in keys:
        s, a, w = _split(k)
        out[k] = merged.get((s, a, w - 1), '')
    return out


def _local_marks(queue: dict, keys) -> dict[str, str]:
    """{word_key: mark} as the local column has it (what a review-only print shows)."""
    out = {}
    for i in queue['items']:
        out.setdefault(i['word_key'], '')
        out.update({k: v for k, v in targets(i, 'db').items() if v})
    return {k: out.get(k, '') for k in keys}


def _cloud_guard(edition: str):
    if edition not in REVIEW_EDITIONS:
        return jsonify({'error': 'invalid edition'}), 400
    if not sb.is_configured():
        return jsonify({
            'error': 'cloud_not_configured',
            'message': 'هذه المراجعة تُحفظ في السحابة فقط؛ افتحها من خادم متصل بالسحابة (Heroku، أو المنفذ 5002 محليًا).',
        }), 409
    return None


def _item_for(queue: dict, word_key: str, tab: str) -> dict | None:
    return next((i for i in queue['items'] if i['word_key'] == word_key and i['tab'] == tab), None)


@editor_bp.route('/mushaf-editor/book-audit')
def audit_review_page():
    return render_template('mushaf_audit.html')


@editor_bp.route('/api/mushaf-editor/book-audit', methods=['GET'])
@require_editor
def audit_review_queue():
    edition = (request.args.get('edition') or '').strip()
    refused = _cloud_guard(edition)
    if refused:
        return refused
    queue = _load_queue(edition)
    if queue is None:
        return jsonify({'error': 'no_audit', 'message': 'لا يوجد فحص لهذا المصحف على هذا الجهاز.'}), 404
    try:
        decisions = {(int(d['page_number']), int(d['word_id'])): d
                     for d in sb.list_mark_review_decisions(_decision_edition(edition))}
        keys = {i['word_key'] for i in queue['items']} | {i['from_key'] for i in queue['items'] if i.get('from_key')}
        review_only = edition in REVIEW_ONLY_EDITIONS
        cloud = _local_marks(queue, keys) if review_only else _cloud_marks(edition, sorted(keys))
    except sb.SupabaseEditorError as exc:
        logger.error('audit queue cloud read failed: %s', exc)
        return jsonify({'error': 'cloud unavailable'}), 503
    queue['review_only'] = review_only
    for i in queue['items']:
        i['word_id'] = _review_word_id(edition, i['word_key'])
        i['actionable'] = i['tab'] in ACTIONABLE_TABS
        i['cloud'] = cloud.get(i['word_key'], '')
        i['from_cloud'] = cloud.get(i['from_key'], '') if i.get('from_key') else None
        d = decisions.get((int(i['page']), i['word_id'] or -1))
        i['decision'] = ({'decision': d['decision'], 'mark': d.get('correct_mark') or '', 'at': d.get('updated_at')}
                         if d else None)
    return jsonify(queue)


@editor_bp.route('/api/mushaf-editor/book-audit/crop', methods=['GET'])
@require_editor
def audit_review_crop():
    edition = (request.args.get('edition') or '').strip()
    name = request.args.get('f') or ''
    d = _audit_dir(edition) if edition in REVIEW_EDITIONS else None
    if not d or not _CROP_NAME.match(name):
        abort(404)
    return send_from_directory(d / 'crops', name, max_age=3600)


@editor_bp.route('/api/mushaf-editor/book-audit/decision', methods=['POST', 'DELETE'])
@require_editor
def audit_review_decision():
    """POST {edition, tab, word_key, choice: image|db|set, symbol?}; DELETE {edition, tab, word_key} undoes."""
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify({'error': 'JSON object required'}), 400
    edition = (body.get('edition') or '').strip()
    refused = _cloud_guard(edition)
    if refused:
        return refused
    queue = _load_queue(edition)
    item = _item_for(queue, str(body.get('word_key') or ''), str(body.get('tab') or '')) if queue else None
    if not item or item['tab'] not in ACTIONABLE_TABS:
        return jsonify({'error': 'unknown card'}), 404
    undo = request.method == 'DELETE'
    choice = 'db' if undo else (body.get('choice') or '')
    symbol = str(body.get('symbol') or '').strip()
    if choice not in ('image', 'db', 'set') or (choice == 'set' and symbol not in _EDITOR_SYMBOLS):
        return jsonify({'error': 'invalid choice'}), 400

    want = targets(item, choice, symbol)
    review_only = edition in REVIEW_ONLY_EDITIONS
    word_id = _review_word_id(edition, item['word_key'])
    ids = {k: _review_word_id(edition, k) for k in want}
    if word_id is None or None in ids.values():
        return jsonify({'error': 'word not found'}), 404
    user = current_editor()
    try:
        if not review_only:              # review-only prints: the decision is the record
            now = _cloud_marks(edition, list(want))
            for key, mark in want.items():
                if now.get(key, '') != mark:
                    _get_or_set_word_waqf_cloud(ids[key], edition, mark, user)
        # «ok» whenever the result is the DB's own state (✕ on an add card, or its sign re-picked).
        decision = 'ok' if want == targets(item, 'db') else 'wrong'
        if undo:
            sb.delete_mark_review_decision(edition=_decision_edition(edition), page_number=int(item['page']),
                                           word_id=word_id)
        else:
            s, a, _w = _split(item['word_key'])
            sb.upsert_mark_review_decision(
                edition=_decision_edition(edition), page_number=int(item['page']), word_id=word_id,
                decision=decision,
                our_mark=item.get('db') or '', correct_mark=want[item['word_key']],
                surah=s, ayah=a, word_text=item.get('text') or '',
                updated_by=user['id'] if user else None,
            )
        after = _local_marks(queue, list(want)) if review_only else _cloud_marks(edition, list(want))
    except sb.SupabaseEditorError as exc:
        logger.error('audit decision failed: %s', exc)
        return jsonify({'error': 'cloud write failed'}), 503
    return jsonify({'ok': True, 'marks': after,
                    'decision': None if undo else {'decision': decision, 'mark': want[item['word_key']]}})
