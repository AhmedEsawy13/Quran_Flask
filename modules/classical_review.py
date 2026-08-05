"""Local-only scholarly review UI for classical waqf books."""
import os
import sqlite3

from flask import jsonify, render_template, request

from core.blueprints import editor_bp
from core.classical_review import (
    book_decision, decisions, manar_review_queue, muktafa_source_context,
    quote_matches_position, review_row_ids, save_book_decision, save_decision,
    source_accuracy, REVIEW_GRADE_LABELS, REVIEW_GRADE_OPTIONS,
)
from core.config import CLASSICAL_REVIEW_DATABASE, CLASSICAL_WAQF_DATABASE
from core.loader import IS_SERVERLESS as _IS_SERVERLESS
from modules.breathing import _verse_word_texts

_SOURCES = {'muktafa', 'manar'}
_PAGE_SIZE_MAX = 50


def _valid_source(source):
    return source in _SOURCES


def _row(row_id, source):
    if not _valid_source(source) or row_id not in review_row_ids(source):
        return None
    conn = sqlite3.connect(CLASSICAL_WAQF_DATABASE)
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute(
            'SELECT * FROM classical WHERE id=? AND source=?', (row_id, source)).fetchone()
    finally:
        conn.close()


@editor_bp.route('/classical-review')
def classical_review_page():
    return render_template('classical_review.html', enable_vercel_analytics=_IS_SERVERLESS)


@editor_bp.route('/api/classical-review/<source>/summary')
def classical_review_summary(source):
    if not _valid_source(source):
        return jsonify({'error': 'unsupported review source'}), 404
    return jsonify(source_accuracy(source))


@editor_bp.route('/api/classical-review/<source>/items')
def classical_review_items(source):
    if not _valid_source(source):
        return jsonify({'error': 'unsupported review source'}), 404
    status = (request.args.get('status') or 'pending').strip()
    alignment = (request.args.get('alignment') or 'all').strip()
    if status not in {'pending', 'approve', 'reject', 'all'}:
        return jsonify({'error': 'invalid status'}), 400
    if alignment not in {'all', 'matched', 'unmatched'}:
        return jsonify({'error': 'invalid alignment'}), 400
    try:
        page = max(1, int(request.args.get('page', 1)))
        limit = min(_PAGE_SIZE_MAX, max(1, int(request.args.get('limit', 12))))
        surah = int(request.args['surah']) if request.args.get('surah') else None
    except (TypeError, ValueError):
        return jsonify({'error': 'invalid pagination or surah'}), 400
    if surah is not None and not 1 <= surah <= 114:
        return jsonify({'error': 'invalid surah'}), 400

    conn = sqlite3.connect(CLASSICAL_WAQF_DATABASE)
    conn.row_factory = sqlite3.Row
    try:
        params = [source]
        if source == 'muktafa':
            query = "SELECT * FROM classical WHERE source=? AND conf=0"
        else:
            ids = sorted(review_row_ids(source))
            if not ids:
                query = 'SELECT * FROM classical WHERE 0'
            else:
                query = f'SELECT * FROM classical WHERE source=? AND id IN ({",".join("?" * len(ids))})'
                params.extend(ids)
        if alignment == 'matched':
            query += ' AND ayah IS NOT NULL AND wpos IS NOT NULL'
        elif alignment == 'unmatched':
            query += ' AND (ayah IS NULL OR wpos IS NULL)'
        if surah is not None:
            query += ' AND surah=?'
            params.append(surah)
        rows = conn.execute(query + ' ORDER BY seq,id', params).fetchall()
    finally:
        conn.close()

    saved = decisions(source)
    if status != 'all':
        rows = [row for row in rows if (
            saved.get(row['id'], {}).get('decision', 'pending') == status)]
    total = len(rows)
    rows = rows[(page - 1) * limit:page * limit]
    items = []
    for row in rows:
        decision = saved.get(row['id']) or {'decision': 'pending', 'reviewer_note': ''}
        effective_ayah = decision.get('corrected_ayah') or row['ayah']
        effective_wpos = (decision.get('corrected_wpos')
                          if decision.get('corrected_wpos') is not None else row['wpos'])
        effective_grade = decision.get('corrected_grade') or row['grade']
        effective_grade_raw = (
            REVIEW_GRADE_LABELS.get(effective_grade, row['grade_raw'])
            if decision.get('corrected_grade') else row['grade_raw']
        )
        words = []
        if effective_ayah is not None:
            try:
                _, words, _ = _verse_word_texts(f'{row["surah"]}:{effective_ayah}')
            except Exception:
                words = []
        if source == 'muktafa':
            evidence = muktafa_source_context(row)
        else:
            queued = manar_review_queue().get(row['id'], {})
            evidence = {
                'locator': f'سورة {row["surah"]} · فحص التتبّع الآلي',
                'context': queued.get('source_context', ''),
            }
        items.append({
            'id': row['id'], 'surah': row['surah'], 'ayah': row['ayah'],
            'wpos': row['wpos'], 'effective_ayah': effective_ayah,
            'effective_wpos': effective_wpos, 'stop_word': row['stop_word'],
            'quote': row['quote'], 'grade': row['grade'],
            'effective_grade': effective_grade,
            'grade_raw': row['grade_raw'],
            'effective_grade_raw': effective_grade_raw,
            'grade_options': REVIEW_GRADE_OPTIONS,
            'note': row['note'] or '',
            'reported_from': row['reported_from'], 'seq': row['seq'],
            'alignment': 'matched' if row['ayah'] is not None and row['wpos'] is not None else 'unmatched',
            'verse_words': words, 'source_locator': evidence['locator'],
            'source_context': evidence['context'], 'review': decision,
        })
    return jsonify({'items': items, 'total': total, 'page': page, 'limit': limit,
                    'pages': max(1, (total + limit - 1) // limit)})


@editor_bp.route('/api/classical-review/<source>/verse/<int:surah>/<int:ayah>')
def classical_review_verse(source, surah, ayah):
    if not _valid_source(source):
        return jsonify({'error': 'unsupported review source'}), 404
    if not 1 <= surah <= 114 or ayah < 1:
        return jsonify({'error': 'invalid verse'}), 400
    try:
        _, words, _ = _verse_word_texts(f'{surah}:{ayah}')
    except Exception:
        words = []
    if not words:
        return jsonify({'error': 'verse not found'}), 404
    return jsonify({'surah': surah, 'ayah': ayah, 'words': words})


@editor_bp.route('/api/classical-review/<source>/decision', methods=['POST'])
def classical_review_decision(source):
    if not _valid_source(source):
        return jsonify({'error': 'unsupported review source'}), 404
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify({'error': 'JSON object required'}), 400
    try:
        row_id = int(body.get('row_id'))
    except (TypeError, ValueError):
        return jsonify({'error': 'invalid row_id'}), 400
    decision = str(body.get('decision') or '').strip()
    if decision not in {'approve', 'reject', 'pending'}:
        return jsonify({'error': 'invalid decision'}), 400
    row = _row(row_id, source)
    if row is None:
        return jsonify({'error': 'review row not found'}), 404
    note = str(body.get('note') or '').strip()[:2000]

    corrected = (None, None, None)
    corrected_grade = None
    if decision == 'approve':
        try:
            ayah = int(body['ayah']) if body.get('ayah') not in (None, '') else row['ayah']
            wpos = int(body['wpos']) if body.get('wpos') not in (None, '') else row['wpos']
        except (TypeError, ValueError):
            return jsonify({'error': 'invalid ayah or word position'}), 400
        if ayah is None or wpos is None:
            return jsonify({'error': 'approval requires a verified ayah and word position'}), 409
        if not quote_matches_position(row['surah'], ayah, wpos, row['quote']):
            return jsonify({'error': 'the quoted phrase does not end at that Qur’an word'}), 409
        if ayah != row['ayah'] or wpos != row['wpos']:
            corrected = (row['surah'], ayah, wpos)
        corrected_grade = str(body.get('grade') or row['grade']).strip()
        if corrected_grade not in REVIEW_GRADE_LABELS:
            return jsonify({'error': 'invalid waqf grade'}), 400
    save_decision(row_id, decision, note, corrected, source,
                  corrected_grade=corrected_grade)
    return jsonify({
        'ok': True, 'row_id': row_id, 'decision': decision,
        'grade': corrected_grade,
    })


@editor_bp.route('/api/classical-review/<source>/book-decision', methods=['POST'])
def classical_review_book_decision(source):
    if not _valid_source(source):
        return jsonify({'error': 'unsupported review source'}), 404
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify({'error': 'JSON object required'}), 400
    decision = str(body.get('decision') or '').strip()
    if decision not in {'add', 'reject', 'pending'}:
        return jsonify({'error': 'invalid book decision'}), 400
    summary = source_accuracy(source)
    if decision == 'add' and summary['review']['pending']:
        return jsonify({
            'error': 'all uncertain rows must be approved or rejected first',
            'pending': summary['review']['pending'],
        }), 409
    note = str(body.get('note') or '').strip()[:4000]
    save_book_decision(decision, note, source)
    return jsonify({'ok': True, 'book': book_decision(source)})


@editor_bp.route('/api/classical-review/<source>/export')
def classical_review_export(source):
    if not _valid_source(source):
        return jsonify({'error': 'unsupported review source'}), 404
    return jsonify({
        'source': source, 'summary': source_accuracy(source),
        'book': book_decision(source),
        'decisions': list(decisions(source).values()),
    })
