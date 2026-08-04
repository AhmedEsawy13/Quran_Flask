"""Build the JSON payload consumed by the /cv-waqf UI."""
from __future__ import annotations

from pipeline.cv_waqf.layout_geo import estimate_layout_words, mark_roi_for_word
from pipeline.cv_waqf.marks import edition_marks_for_ayahs
from pipeline.cv_waqf.pages import ensure_page_image
from pipeline.cv_waqf.preprocess import load_bgr, preprocess_page
from pipeline.cv_waqf.run_page import detect_page

_GLYPH = {
    'م': 'ۘ', 'ق': 'ۗ', 'ص': 'ۖ', 'ج': 'ۚ',
    'لا': 'ۙ', 'ع': 'ۛ', 'س': 'ۜ',
}


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
    min_conf: float = 0.7,
    slug: str = '',
) -> dict:
    from pipeline.cv_waqf.config import EDITIONS

    spec = EDITIONS[edition]
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
            'glyph': _GLYPH.get(symbol, symbol),
            'line': w.line_number,
            'box': [w.x0, w.y0, w.x1, w.y1],
            'seat': [x0, y0, x1, y1],
        })

    db_by_word = {int(r['word_id']): r for r in db_marks}
    cv_marks = []
    for m in detected.get('marks') or []:
        row = dict(m)
        row['glyph'] = _GLYPH.get(row.get('symbol'), row.get('symbol'))
        db = db_by_word.get(int(row['word_id']))
        if db is None:
            row['vs_db'] = 'extra'
        elif db['symbol'] == row.get('symbol'):
            row['vs_db'] = 'match'
        else:
            row['vs_db'] = 'wrong'
            row['db_symbol'] = db['symbol']
        cv_marks.append(row)

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
        'image': str(img_path),
        'summary': {
            'cv': len(cv_marks),
            'db': len(db_marks),
            'match': sum(1 for m in cv_marks if m.get('vs_db') == 'match'),
            'wrong': sum(1 for m in cv_marks if m.get('vs_db') == 'wrong'),
            'extra': sum(1 for m in cv_marks if m.get('vs_db') == 'extra'),
            'missing': len(missing),
            'candidates': detected.get('candidates', 0),
            'classified': detected.get('classified', 0),
        },
        'cv_marks': cv_marks,
        'db_marks': db_marks,
        'missing': missing,
        'symbols': [{'code': c, 'glyph': g} for c, g in _GLYPH.items()],
    }
