"""Editor review UI for contemporary توجيه (د. أحمد صابر / @Dr_ahmed21).

Sibling of /classical-review. Not a fifth classical book: rows live in
public.tawjih (Supabase) or data/tawjih.db (tests / offline sqlite).
"""
from flask import jsonify, render_template, request

from core.blueprints import editor_bp
from core.loader import IS_SERVERLESS as _IS_SERVERLESS
from core.tawjih import (
    REVIEW_GRADES,
    TAWJIH_SOURCE,
    TawjihReviewError,
    apply_review_decision,
    get_verse_words,
    list_review_items,
    review_summary,
)
from modules.editor_auth import require_editor

_PAGE_SIZE_MAX = 50
_STATUSES = {'review', 'published', 'skipped', 'all'}


@editor_bp.route('/tawjih-review')
def tawjih_review_page():
    return render_template(
        'tawjih_review.html',
        enable_vercel_analytics=_IS_SERVERLESS,
    )


@editor_bp.route('/api/tawjih-review/summary')
@require_editor
def tawjih_review_summary():
    summary = review_summary()
    return jsonify({
        'published': summary['published'],
        'review': summary['review'],
        'skipped': summary['skipped'],
        'total': summary['total'],
        'source': summary.get('source') or TAWJIH_SOURCE,
    })


@editor_bp.route('/api/tawjih-review/items')
@require_editor
def tawjih_review_items():
    status = (request.args.get('status') or 'review').strip()
    if status not in _STATUSES:
        return jsonify({'error': 'invalid status'}), 400
    try:
        page = max(1, int(request.args.get('page', 1)))
        limit = min(_PAGE_SIZE_MAX, max(1, int(request.args.get('limit', 12))))
    except (TypeError, ValueError):
        return jsonify({'error': 'invalid pagination'}), 400
    data = list_review_items(status, page, limit)
    return jsonify({
        'items': data['items'],
        'total': data['total'],
        'page': data['page'],
        'limit': data['limit'],
        'pages': data['pages'],
    })


@editor_bp.route('/api/tawjih-review/verse/<int:surah>/<int:ayah>')
@require_editor
def tawjih_review_verse(surah, ayah):
    words, err = get_verse_words(surah, ayah)
    if err == 'invalid':
        return jsonify({'error': 'invalid verse'}), 400
    if err == 'missing' or not words:
        return jsonify({'error': 'verse not found'}), 404
    return jsonify({'surah': surah, 'ayah': ayah, 'words': words})


@editor_bp.route('/api/tawjih-review/decision', methods=['POST'])
@require_editor
def tawjih_review_decision():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify({'error': 'JSON object required'}), 400
    try:
        row_id = int(body.get('id'))
    except (TypeError, ValueError):
        return jsonify({'error': 'invalid id'}), 400
    decision = str(body.get('decision') or '').strip()
    if decision not in {'add', 'discard'}:
        return jsonify({'error': 'invalid decision'}), 400
    grade = body.get('grade')
    if grade not in (None, ''):
        grade = str(grade).strip()
        if grade not in REVIEW_GRADES:
            return jsonify({'error': 'invalid waqf grade'}), 400
    try:
        result = apply_review_decision(
            row_id,
            decision,
            surah=body.get('surah'),
            ayah=body.get('ayah'),
            wpos=body.get('wpos'),
            quote=body.get('quote'),
            grade=grade,
        )
    except TawjihReviewError as err:
        payload = jsonify({'error': err.message})
        if err.status == 404:
            return payload, 404
        if err.status == 409:
            return payload, 409
        return payload, 400
    return jsonify({
        'ok': True,
        'id': result['id'],
        'decision': result['decision'],
        'status': result['status'],
        'surah': result['surah'],
        'ayah': result['ayah'],
        'wpos': result['wpos'],
        'quote': result['quote'],
    })
