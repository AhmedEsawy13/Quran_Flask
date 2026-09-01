"""Build the JSON payload consumed by the /cv-waqf UI."""
from __future__ import annotations

from pipeline.cv_waqf.config import EDITIONS, classify_mark_trust
from pipeline.cv_waqf.layout_geo import estimate_layout_words, mark_roi_for_word
from pipeline.cv_waqf.marks import edition_marks_for_ayahs
from pipeline.cv_waqf.pages import ensure_page_image
from pipeline.cv_waqf.preprocess import load_bgr, preprocess_page
from pipeline.cv_waqf.run_page import detect_page

from core.waqf_glyphs import (
    GLYPH_FOR_CLASS as _GLYPH,
    SHORT_NAME as _GLYPH_SHORT,
    SYMBOL_META as _SYMBOL_META,
)

_GLYPH_NAME = {code: name for code, _glyph, name in _SYMBOL_META}


def _glyph_fields(symbol: str | None) -> dict:
    code = symbol or ''
    return {
        'glyph': _GLYPH.get(code, code),
        'name': _GLYPH_NAME.get(code, code),
        'short_name': _GLYPH_SHORT.get(code, _GLYPH_NAME.get(code, code)),
    }


def _with_db_contrast(row: dict, db: dict | None) -> dict:
    row.update(_glyph_fields(row.get('symbol')))
    if db is None:
        row['vs_db'] = 'extra'
        return row
    if db.get('symbol') == row.get('symbol'):
        row['vs_db'] = 'match'
        return row
    row['vs_db'] = 'wrong'
    row['db_symbol'] = db.get('symbol')
    row.update({
        'db_glyph': db.get('glyph') or _GLYPH.get(db.get('symbol'), db.get('symbol')),
        'db_name': db.get('name') or _GLYPH_NAME.get(db.get('symbol'), db.get('symbol')),
        'db_short_name': db.get('short_name') or _GLYPH_SHORT.get(
            db.get('symbol'), db.get('symbol'),
        ),
    })
    return row


def build_word_payload(edition: str, page: int) -> dict:
    """Return page words and their mark seats without running the classifier.

    The hand-labeling UI uses this lightweight payload to make every crop
    explicitly portable across database-local word ID namespaces.
    """
    from pipeline.cv_waqf.config import EDITIONS

    spec = EDITIONS[edition]
    img_path = ensure_page_image(spec, page)
    prepared = preprocess_page(load_bgr(img_path), spec)
    words = estimate_layout_words(spec, page, prepared)
    return {
        'edition': edition,
        'page': page,
        'words': [
            {
                'word_id': word.word_id,
                'word_key': word.word_key,
                'word_id_space': word.word_id_space,
                'surah': word.surah,
                'ayah': word.ayah,
                'text': word.text,
                'line': word.line_number,
                'word_on_line': word.word_on_line,
                'box': [word.x0, word.y0, word.x1, word.y1],
                'seat': list(mark_roi_for_word(word)),
            }
            for word in words
            if word.word_key
        ],
    }


def build_ui_payload(
    edition: str,
    page: int,
    *,
    min_conf: float | None = None,
    slug: str = '',
) -> dict:
    spec = EDITIONS[edition]
    if min_conf is None:
        min_conf = spec.review_min_conf
    auto_set = spec.auto_set_min_conf
    # Inherits EditionSpec.default_proposal_mode (hybrid for البحرين).
    # Detect at the review floor so the UI can grade 0.55–auto_set hits.
    detected = detect_page(edition, page, min_conf=min_conf, seat_prior=True)
    img_path = ensure_page_image(spec, page)
    prepared = preprocess_page(load_bgr(img_path), spec)
    words = estimate_layout_words(spec, page, prepared)
    ayah_keys = sorted({(w.surah, w.ayah) for w in words if w.surah and w.ayah})
    marks = edition_marks_for_ayahs(edition, ayah_keys, spec.script_db)
    page_ids = {w.word_id for w in words}
    by_id = {w.word_id: w for w in words}

    db_marks = []
    for (surah, ayah, word_id), symbol in sorted(marks.items()):
        if word_id not in page_ids:
            continue
        w = by_id[word_id]
        x0, y0, x1, y1 = mark_roi_for_word(w)
        db_marks.append({
            'word_id': word_id,
            'surah': surah,
            'ayah': ayah,
            'text': w.text,
            'symbol': symbol,
            **_glyph_fields(symbol),
            'line': w.line_number,
            'box': [w.x0, w.y0, w.x1, w.y1],
            'seat': [x0, y0, x1, y1],
        })

    db_by_word = {int(r['word_id']): r for r in db_marks}
    cv_marks = []
    for m in detected.get('marks') or []:
        row = dict(m)
        row['trust'] = classify_mark_trust(
            row.get('confidence') or 0.0, auto_set,
        )
        cv_marks.append(_with_db_contrast(row, db_by_word.get(int(row['word_id']))))

    trusted_marks = [m for m in cv_marks if m.get('trust') == 'auto-set']
    review_marks = [m for m in cv_marks if m.get('trust') == 'review']
    rejected_marks = []
    for m in detected.get('azhar_rejected') or []:
        row = dict(m)
        row['trust'] = 'rejected'
        row['reject_reason'] = row.get('reject_reason') or 'azhar_empty'
        rejected_marks.append(
            _with_db_contrast(row, db_by_word.get(int(row['word_id']))),
        )
    cv_ids = {int(m['word_id']) for m in cv_marks}
    missing = [
        {**db_by_word[wid], 'vs_db': 'missing'}
        for wid in sorted(set(db_by_word) - cv_ids)
    ]

    return {
        'edition': edition,
        'slug': slug,
        'page': page,
        'min_conf': min_conf,
        'review_min_conf': spec.review_min_conf,
        'auto_set_min_conf': auto_set,
        'proposal_mode': detected.get('proposal_mode'),
        'azhar_prior': detected.get('azhar_prior'),
        'image': str(img_path),
        'summary': {
            'cv': len(cv_marks),
            'trusted': len(trusted_marks),
            'review': len(review_marks),
            'rejected': len(rejected_marks),
            'db': len(db_marks),
            'match': sum(1 for m in cv_marks if m.get('vs_db') == 'match'),
            'wrong': sum(1 for m in cv_marks if m.get('vs_db') == 'wrong'),
            'extra': sum(1 for m in cv_marks if m.get('vs_db') == 'extra'),
            'missing': len(missing),
            'candidates': detected.get('candidates', 0),
            'classified': detected.get('classified', 0),
        },
        'cv_marks': cv_marks,
        'trusted_marks': trusted_marks,
        'review_marks': review_marks,
        'rejected_marks': rejected_marks,
        'db_marks': db_marks,
        'missing': missing,
        'symbols': [
            {
                'code': code,
                'glyph': glyph,
                'name': _GLYPH_NAME.get(code, ''),
                'short': _GLYPH_SHORT.get(code, ''),
            }
            for code, glyph in _GLYPH.items()
            if code != 'none'
        ],
    }
