"""Local UI to inspect OpenCV waqf detections on printed mushaf pages.

Editor-only (ENABLE_EDITOR). Heavy detection runs in ``.venv-cv`` so the
Flask process does not need OpenCV installed.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from pathlib import Path

from flask import jsonify, render_template, request, send_file

from core.blueprints import editor_bp
from core.config import _ROOT
from core.errors import NotFoundError, PersistenceError
from core.loader import IS_SERVERLESS as _IS_SERVERLESS
from modules.editor_auth import require_editor

logger = logging.getLogger(__name__)

ROOT = Path(_ROOT)
CV_VENV_PYTHON = ROOT / '.venv-cv' / 'bin' / 'python'
ARTIFACT_CACHE = ROOT / 'artifacts' / 'cv-waqf' / 'ui-cache'

_UI_EDITIONS = (
    {
        'id': 'الشمرلي',
        'label': 'مصحف الشمرلي',
        'slug': 'shamarly',
        'min_page': 2,
        'max_page': 522,
    },
    {
        'id': 'البحرين',
        'label': 'مصحف البحرين',
        'slug': 'bahrain',
        'min_page': 1,
        'max_page': 604,
    },
    {
        'id': 'المساحة',
        'label': 'مصحف المساحة الأميرية',
        'slug': 'mesaha',
        'min_page': 2,
        'max_page': 827,
    },
)
_BY_ID = {e['id']: e for e in _UI_EDITIONS}
_BY_SLUG = {e['slug']: e for e in _UI_EDITIONS}


def _resolve_cv_python() -> str:
    if CV_VENV_PYTHON.is_file():
        return str(CV_VENV_PYTHON)
    return sys.executable


def _build_payload(edition: str, page: int, min_conf: float, slug: str) -> dict:
    """Prefer in-process OpenCV; fall back to the CV venv subprocess."""
    try:
        import cv2  # noqa: F401
        from pipeline.cv_waqf.ui_payload import build_ui_payload
        return build_ui_payload(edition, page, min_conf=min_conf, slug=slug)
    except Exception:
        logger.info('Building CV UI payload via subprocess')

    ARTIFACT_CACHE.mkdir(parents=True, exist_ok=True)
    from pipeline.cv_waqf.config import (
        resolve_auto_set_min_conf,
        resolve_proposal_mode,
    )
    mode = resolve_proposal_mode(edition)
    auto = resolve_auto_set_min_conf(edition)
    out = ARTIFACT_CACHE / (
        f'{slug}_p{page:03d}_{min_conf:.2f}_{mode}_auto{auto:.2f}.json'
    )
    py = _resolve_cv_python()
    code = (
        'import json,sys\n'
        'from pipeline.cv_waqf.ui_payload import build_ui_payload\n'
        f'payload=build_ui_payload({edition!r},{page},min_conf={min_conf},slug={slug!r})\n'
        f'open({str(out)!r},"w",encoding="utf-8").write('
        'json.dumps(payload,ensure_ascii=False))\n'
    )
    env = os.environ.copy()
    env['PYTHONPATH'] = str(ROOT)
    proc = subprocess.run(
        [py, '-c', code],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or '').strip()[-1000:]
        raise RuntimeError(detail or f'cv payload exit {proc.returncode}')
    if not out.is_file():
        raise RuntimeError('cv payload produced no JSON')
    return json.loads(out.read_text(encoding='utf-8'))


def _build_word_payload(edition: str, page: int, slug: str) -> dict:
    """Build word/seat geometry without loading or running the ONNX model."""
    try:
        import cv2  # noqa: F401
        from pipeline.cv_waqf.ui_payload import build_word_payload
        return build_word_payload(edition, page)
    except Exception:
        logger.info('Building CV word payload via subprocess')

    ARTIFACT_CACHE.mkdir(parents=True, exist_ok=True)
    out = ARTIFACT_CACHE / f'{slug}_p{page:03d}_words.json'
    py = _resolve_cv_python()
    code = (
        'import json\n'
        'from pipeline.cv_waqf.ui_payload import build_word_payload\n'
        f'payload=build_word_payload({edition!r},{page})\n'
        f'open({str(out)!r},"w",encoding="utf-8").write('
        'json.dumps(payload,ensure_ascii=False))\n'
    )
    env = os.environ.copy()
    env['PYTHONPATH'] = str(ROOT)
    proc = subprocess.run(
        [py, '-c', code],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if proc.returncode == 0 and out.is_file():
        return json.loads(out.read_text(encoding='utf-8'))

    # CI / production Flask has no OpenCV — still serve layout words so the
    # labeling UI and cache-header tests can run without requirements-cv.
    logger.warning(
        'CV word geometry unavailable (%s); using layout-only fallback',
        (proc.stderr or proc.stdout or 'no cv2').strip()[-200:],
    )
    return _build_logical_word_payload(edition, page)


def _build_logical_word_payload(edition: str, page: int) -> dict:
    """Word keys + approximate seats from the layout DB (no OpenCV)."""
    from pipeline.cv_waqf.config import EDITIONS, IMG_WIDTH
    from pipeline.cv_waqf.layout_geo import estimate_layout_words, mark_roi_for_word
    from pipeline.cv_waqf.preprocess import synthetic_prepared_page

    spec = EDITIONS[edition]
    prepared = synthetic_prepared_page(
        spec, width=IMG_WIDTH, height=int(IMG_WIDTH * 1.5),
    )
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
        'geometry': 'layout-only',
    }


def _ensure_image(edition: str, page: int) -> Path:
    from pipeline.cv_waqf.config import EDITIONS
    from pipeline.cv_waqf.pages import ensure_page_image, page_image_path

    spec = EDITIONS[edition]
    cached = page_image_path(spec, page)
    if cached.is_file() and cached.stat().st_size > 0:
        return cached
    try:
        return Path(ensure_page_image(spec, page))
    except Exception:
        if edition == 'البحرين':
            from modules.editor import _bahrain_ref_jpeg
            path = _bahrain_ref_jpeg(page, width=1024)
            if path:
                return Path(path)
        raise


_GLYPH_META = (
    ('م', 'ۘ', 'لازم'),
    ('لا', 'ۙ', 'لا وقف'),
    ('ق', 'ۗ', 'الوقف أولى'),
    ('ص', 'ۖ', 'الوصل أولى'),
    ('ج', 'ۚ', 'جائز'),
    ('س', 'ۜ', 'سكتة'),
    ('ع', 'ۛ', 'معانقة'),
)

ALLOWED_LABEL_SYMBOLS = frozenset(c for c, _g, _n in _GLYPH_META) | {'none'}
CLASS_DIR = {
    'م': 'm', 'ق': 'q', 'ص': 's', 'ج': 'j',
    'لا': 'la', 'ع': 'a', 'س': 'sakta', 'none': 'none',
}
HAND_ROOT = ROOT / 'data' / 'cv' / 'crops_hand'
STORAGE_BUCKET = 'cv-waqf-hand'
_ANCHOR_FIELDS = (
    'word_key', 'local_word_id', 'word_id_space', 'surah', 'ayah',
    'word_position', 'line_number', 'word_text', 'attachment_status',
)


def _hand_dir(slug: str) -> Path:
    return HAND_ROOT / slug


def _labels_path(slug: str) -> Path:
    return _hand_dir(slug) / 'labels.jsonl'


def _cloud_ready() -> bool:
    try:
        from core import supabase_editor as sb
        return sb.is_configured()
    except Exception:  # noqa: BLE001
        return False


def _load_local_labels(slug: str, page: int | None = None) -> list[dict]:
    path = _labels_path(slug)
    if not path.is_file():
        return []
    out = []
    for line in path.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        try:
            row_page = int(row.get('page') or -1)
        except (TypeError, ValueError):
            continue
        if page is not None and row_page != page:
            continue
        out.append(row)
    return out


def _fetch_cloud_labels(slug: str, page: int | None = None) -> list[dict]:
    """Read hand labels from Supabase (service role). Empty if unset/unavailable."""
    if not _cloud_ready():
        return []
    try:
        from core import supabase_editor as sb
        params: dict[str, str] = {
            'slug': f'eq.{slug}',
            'select': (
                'id,edition,slug,page,symbol,box,crop_path,created_at,'
                + ','.join(_ANCHOR_FIELDS)
            ),
            'order': 'created_at.asc',
        }
        if page is not None:
            params['page'] = f'eq.{int(page)}'
        try:
            rows = sb._request('GET', 'cv_waqf_hand_labels', params=params) or []
        except Exception:
            # Backward-compatible until the additive anchor migration runs.
            params['select'] = (
                'id,edition,slug,page,symbol,box,crop_path,created_at'
            )
            rows = sb._request('GET', 'cv_waqf_hand_labels', params=params) or []
    except Exception as exc:  # noqa: BLE001
        logger.warning('cv_waqf cloud labels fetch failed: %s', exc)
        return []
    out = []
    for row in rows:
        try:
            normalized = {
                'id': row['id'],
                'edition': row['edition'],
                'slug': row['slug'],
                'page': int(row['page']),
                'symbol': row['symbol'],
                'box': row['box'],
                'crop': row.get('crop_path') or row.get('crop'),
                'created_at': row.get('created_at'),
                'source': 'supabase',
            }
            for field in _ANCHOR_FIELDS:
                if row.get(field) is not None:
                    normalized[field] = row[field]
        except (KeyError, TypeError, ValueError):
            logger.warning('Ignoring malformed cv_waqf cloud label: %r', row)
            continue
        out.append(normalized)
    return out


def _merge_labels(local: list[dict], remote: list[dict]) -> list[dict]:
    by_id: dict[str, dict] = {}
    for row in remote + local:
        rid = row.get('id')
        if not rid:
            continue
        prev = by_id.get(rid)
        if prev is None:
            by_id[rid] = row
            continue
        a = str(prev.get('created_at') or '')
        b = str(row.get('created_at') or '')
        by_id[rid] = row if b >= a else prev
    def sort_key(row: dict) -> tuple[int, str]:
        try:
            page = int(row.get('page') or 0)
        except (TypeError, ValueError):
            page = 0
        return page, str(row.get('id') or '')

    return sorted(by_id.values(), key=sort_key)


def _load_labels(slug: str, page: int | None = None) -> list[dict]:
    """Local jsonl + Supabase rows (cloud wins for same id when newer)."""
    return _merge_labels(
        _load_local_labels(slug, page=page),
        _fetch_cloud_labels(slug, page=page),
    )


def _rewrite_labels(slug: str, rows: list[dict]) -> None:
    path = _labels_path(slug)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    with tmp.open('w', encoding='utf-8') as fh:
        for row in rows:
            clean = {k: v for k, v in row.items() if k != 'source'}
            fh.write(json.dumps(clean, ensure_ascii=False) + '\n')
    tmp.replace(path)


def _cloud_upsert_label(label: dict) -> None:
    if not _cloud_ready():
        return
    try:
        from core import supabase_editor as sb
        payload = {
            'id': label['id'],
            'edition': label['edition'],
            'slug': label['slug'],
            'page': int(label['page']),
            'symbol': label['symbol'],
            'box': label['box'],
            'crop_path': label.get('crop') or label.get('crop_path'),
            'created_at': label.get('created_at'),
        }
        payload.update({
            field: label.get(field)
            for field in _ANCHOR_FIELDS
            if label.get(field) is not None
        })
        try:
            sb._request(
                'POST', 'cv_waqf_hand_labels', json_body=payload,
                prefer='resolution=merge-duplicates,return=minimal',
            )
        except Exception:
            # Preserve crop sync on older installations; readiness will flag
            # the missing migration separately once schema version 1 is set.
            legacy = {k: v for k, v in payload.items() if k not in _ANCHOR_FIELDS}
            sb._request(
                'POST', 'cv_waqf_hand_labels', json_body=legacy,
                prefer='resolution=merge-duplicates,return=minimal',
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning('cv_waqf cloud upsert failed: %s', exc)


def _cloud_delete_label(label_id: str, crop_rel: str | None = None) -> None:
    if not _cloud_ready():
        return
    try:
        from core import supabase_editor as sb
        import requests
        sb._request(
            'DELETE',
            'cv_waqf_hand_labels',
            params={'id': f'eq.{label_id}'},
        )
        if crop_rel:
            url = f"{sb._base()}/storage/v1/object/{STORAGE_BUCKET}/{crop_rel.lstrip('/')}"
            requests.delete(
                url,
                headers={
                    'apikey': sb._key(),
                    'Authorization': f'Bearer {sb._key()}',
                },
                timeout=30,
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning('cv_waqf cloud delete failed: %s', exc)


def _cloud_upload_bytes(object_path: str, data: bytes, content_type: str) -> None:
    if not _cloud_ready():
        return
    try:
        from core import supabase_editor as sb
        import requests
        url = (
            f"{sb._base()}/storage/v1/object/{STORAGE_BUCKET}/"
            f"{object_path.lstrip('/')}"
        )
        resp = requests.post(
            url,
            headers={
                'apikey': sb._key(),
                'Authorization': f'Bearer {sb._key()}',
                'Content-Type': content_type,
                'x-upsert': 'true',
            },
            data=data,
            timeout=60,
        )
        if resp.status_code not in (200, 201):
            logger.warning(
                'cv_waqf cloud upload %s failed: %s %s',
                object_path, resp.status_code, resp.text[:200],
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning('cv_waqf cloud upload failed: %s', exc)


def _cloud_download_bytes(object_path: str) -> bytes | None:
    if not _cloud_ready():
        return None
    try:
        from core import supabase_editor as sb
        import requests
        url = (
            f"{sb._base()}/storage/v1/object/{STORAGE_BUCKET}/"
            f"{object_path.lstrip('/')}"
        )
        resp = requests.get(
            url,
            headers={
                'apikey': sb._key(),
                'Authorization': f'Bearer {sb._key()}',
            },
            timeout=60,
        )
        if resp.status_code != 200:
            return None
        return resp.content
    except Exception as exc:  # noqa: BLE001
        logger.warning('cv_waqf cloud download failed: %s', exc)
        return None


def _save_crop_png(slug: str, label: dict) -> Path:
    """Crop the page JPEG to a 48×48 training PNG (Pillow only — no OpenCV)."""
    crop_size = 48
    try:
        from pipeline.cv_waqf.config import CROP_SIZE
        crop_size = int(CROP_SIZE)
    except Exception:  # noqa: BLE001
        pass

    edition = label['edition']
    page = int(label['page'])
    box = [int(v) for v in label['box']]
    x0, y0, x1, y1 = box
    if x1 < x0:
        x0, x1 = x1, x0
    if y1 < y0:
        y0, y1 = y1, y0

    img_path = _ensure_image(edition, page)
    sym = label['symbol']
    folder = _hand_dir(slug) / CLASS_DIR.get(sym, sym)
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / f"{label['id']}.png"
    return _save_crop_pillow(img_path, dest, (x0, y0, x1, y1), crop_size)


def _save_crop_pillow(
    img_path: Path,
    dest: Path,
    box: tuple[int, int, int, int],
    crop_size: int,
) -> Path:
    try:
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError(
            'Pillow is required to save waqf crops. '
            'Run: pip install pillow'
        ) from exc

    x0, y0, x1, y1 = box
    with Image.open(img_path) as im:
        im = im.convert('L')
        w, h = im.size
        x0, y0 = max(0, x0), max(0, y0)
        x1, y1 = min(w, x1), min(h, y1)
        if x1 - x0 < 2 or y1 - y0 < 2:
            raise RuntimeError('empty crop')
        patch = im.crop((x0, y0, x1, y1))
    pw, ph = patch.size
    side = max(pw, ph, 1)
    canvas = Image.new('L', (side, side), 255)
    canvas.paste(patch, ((side - pw) // 2, (side - ph) // 2))
    resample = getattr(getattr(Image, 'Resampling', Image), 'LANCZOS', Image.BICUBIC)
    canvas = canvas.resize((crop_size, crop_size), resample)
    dest.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(dest, format='PNG')
    return dest


@editor_bp.route('/cv-waqf')
def cv_waqf_page():
    return render_template(
        'cv_waqf.html',
        enable_vercel_analytics=_IS_SERVERLESS,
        editions=_UI_EDITIONS,
        symbols=[
            {'code': c, 'glyph': g, 'name': n}
            for c, g, n in _GLYPH_META
        ],
        default_edition='الشمرلي',
        min_page=2,
        max_page=522,
    )


@editor_bp.route('/api/cv-waqf/image/<slug>/<int:page_number>.jpg', methods=['GET'])
@require_editor
def cv_waqf_image(slug: str, page_number: int):
    edition = next((e['id'] for e in _UI_EDITIONS if e['slug'] == slug), None)
    if not edition:
        return jsonify({'error': 'unknown edition'}), 404
    meta = _BY_ID[edition]
    if not (meta['min_page'] <= page_number <= meta['max_page']):
        return jsonify({'error': 'page out of range'}), 400
    try:
        path = _ensure_image(edition, page_number)
    except Exception as exc:  # noqa: BLE001
        raise NotFoundError('صورة الصفحة غير متاحة') from exc
    return send_file(path, mimetype='image/jpeg', max_age=3600, conditional=True)


@editor_bp.route('/cv-waqf/crops')
@editor_bp.route('/cv-waqf/crops/')
@editor_bp.route('/cv-waqf/crops/<slug>')
@require_editor
def cv_waqf_crops_gallery(slug: str | None = None):
    """Browse labeled crop galleries produced by sample-crops."""
    from flask import abort, redirect

    root = ROOT / 'data' / 'cv' / 'crops_labeled'
    if slug is None:
        # Prefer shamarly, then bahrain, else first available.
        for preferred in ('shamarly', 'bahrain'):
            idx = root / preferred / 'index.html'
            if idx.is_file():
                return redirect(f'/cv-waqf/crops/{preferred}')
        if root.is_dir():
            for child in sorted(root.iterdir()):
                if (child / 'index.html').is_file():
                    return redirect(f'/cv-waqf/crops/{child.name}')
        return jsonify({
            'error': 'no labeled crops yet',
            'hint': (
                'PYTHONPATH=. .venv-cv/bin/python -m pipeline.cv_waqf '
                'sample-crops --edition الشمرلي --pages 40 --clear'
            ),
        }), 404
    if slug not in _BY_SLUG:
        abort(404)
    index = root / slug / 'index.html'
    if not index.is_file():
        abort(404)
    return send_file(index, mimetype='text/html')


@editor_bp.route('/cv-waqf/crops/<slug>/<path:filename>')
@require_editor
def cv_waqf_crops_asset(slug: str, filename: str):
    from flask import abort, send_from_directory

    if slug not in _BY_SLUG:
        abort(404)
    folder = ROOT / 'data' / 'cv' / 'crops_labeled' / slug
    if not folder.is_dir():
        abort(404)
    return send_from_directory(folder, filename)


@editor_bp.route('/api/cv-waqf/page/<int:page_number>', methods=['GET'])
@require_editor
def cv_waqf_page_data(page_number: int):
    edition = (request.args.get('edition') or 'الشمرلي').strip()
    meta = _BY_ID.get(edition)
    if not meta:
        return jsonify({'error': 'unsupported edition', 'editions': list(_BY_ID)}), 400
    if not (meta['min_page'] <= page_number <= meta['max_page']):
        return jsonify({
            'error': f'page must be {meta["min_page"]}..{meta["max_page"]}',
        }), 400
    try:
        raw_conf = request.args.get('min_conf')
        if raw_conf:
            min_conf = float(raw_conf)
        else:
            from pipeline.cv_waqf.config import EDITIONS
            spec = EDITIONS.get(edition)
            min_conf = spec.review_min_conf if spec else 0.55
    except (TypeError, ValueError):
        min_conf = 0.55
    min_conf = max(0.2, min(0.95, min_conf))

    try:
        payload = _build_payload(edition, page_number, min_conf, meta['slug'])
    except Exception as exc:  # noqa: BLE001
        raise PersistenceError(
            'تعذّر تحليل صفحة المصحف',
            public_fields={'hint': (
                'Create the CV venv and train once:\n'
                '  python3 -m venv .venv-cv\n'
                '  .venv-cv/bin/pip install -r requirements-cv.txt\n'
                '  PYTHONPATH=. .venv-cv/bin/python -m pipeline.cv_waqf train'
            )},
        ) from exc

    payload['min_page'] = meta['min_page']
    payload['max_page'] = meta['max_page']
    payload['slug'] = meta['slug']
    payload['image_url'] = (
        f"/api/cv-waqf/image/{meta['slug']}/{page_number}.jpg"
    )
    return jsonify(payload)


@editor_bp.route('/api/cv-waqf/labels', methods=['GET'])
@require_editor
def cv_waqf_labels_list():
    edition = (request.args.get('edition') or 'الشمرلي').strip()
    meta = _BY_ID.get(edition)
    if not meta:
        return jsonify({'error': 'unsupported edition'}), 400
    try:
        page = int(request.args.get('page') or 0)
    except (TypeError, ValueError):
        return jsonify({'error': 'invalid page'}), 400
    if not (meta['min_page'] <= page <= meta['max_page']):
        return jsonify({'error': 'page out of range'}), 400
    labels = _load_labels(meta['slug'], page=page)
    try:
        word_payload = _build_word_payload(edition, page, meta['slug'])
    except Exception as exc:  # noqa: BLE001
        raise PersistenceError('تعذّر تحميل كلمات الصفحة') from exc
    return jsonify({
        'edition': edition,
        'slug': meta['slug'],
        'page': page,
        'labels': labels,
        'words': word_payload.get('words') or [],
        'count': len(labels),
        'cloud': _cloud_ready(),
    })


@editor_bp.route('/api/cv-waqf/review-queue', methods=['GET'])
@require_editor
def cv_waqf_review_queue():
    """Return the deterministic calibration queue with live label counts."""
    edition = (request.args.get('edition') or 'البحرين').strip()
    meta = _BY_ID.get(edition)
    if not meta:
        return jsonify({'error': 'unsupported edition'}), 400
    try:
        from pipeline.cv_waqf.review_queue import build_review_queue
        queue = build_review_queue(edition)
    except Exception as exc:  # noqa: BLE001
        raise PersistenceError('تعذّر تحميل قائمة المراجعة') from exc
    counts: dict[int, int] = {}
    for label in _load_labels(meta['slug']):
        try:
            page = int(label.get('page'))
        except (TypeError, ValueError):
            continue
        counts[page] = counts.get(page, 0) + 1
    for item in queue['pages']:
        item['label_count'] = counts.get(item['page'], 0)
    queue['total_labels'] = sum(item['label_count'] for item in queue['pages'])
    return jsonify(queue)


@editor_bp.route('/api/cv-waqf/labels', methods=['POST'])
@require_editor
def cv_waqf_labels_create():
    import time
    import uuid

    body = request.get_json(silent=True) or {}
    edition = (body.get('edition') or '').strip()
    meta = _BY_ID.get(edition)
    if not meta:
        return jsonify({'error': 'unsupported edition'}), 400
    try:
        page = int(body.get('page'))
        box = [int(v) for v in body.get('box')]
    except (TypeError, ValueError):
        return jsonify({'error': 'invalid page/box'}), 400
    if len(box) != 4:
        return jsonify({'error': 'box must be [x0,y0,x1,y1]'}), 400
    if not (meta['min_page'] <= page <= meta['max_page']):
        return jsonify({'error': 'page out of range'}), 400
    symbol = (body.get('symbol') or '').strip()
    if symbol not in ALLOWED_LABEL_SYMBOLS:
        return jsonify({'error': f'bad symbol {symbol!r}'}), 400

    word_key = str(body.get('word_key') or '').strip()
    if not word_key:
        return jsonify({'error': 'word_key is required'}), 400
    try:
        words = _build_word_payload(edition, page, meta['slug']).get('words') or []
    except Exception as exc:  # noqa: BLE001
        raise PersistenceError('تعذّر تحميل مواضع كلمات الصفحة') from exc
    word = next((row for row in words if row.get('word_key') == word_key), None)
    if word is None:
        return jsonify({'error': 'word_key is not on this page'}), 400

    x0, y0, x1, y1 = box
    if abs(x1 - x0) < 4 or abs(y1 - y0) < 4:
        return jsonify({'error': 'box too small'}), 400

    label = {
        'id': f'{meta["slug"]}-p{page:03d}-{uuid.uuid4().hex[:10]}',
        'edition': edition,
        'slug': meta['slug'],
        'page': page,
        'symbol': symbol,
        'box': [min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)],
        'word_key': word_key,
        'local_word_id': int(word['word_id']),
        'word_id_space': str(word['word_id_space']),
        'surah': int(word['surah']),
        'ayah': int(word['ayah']),
        'word_position': int(word_key.rsplit(':', 1)[-1]),
        'line_number': int(word['line']),
        'word_text': str(word.get('text') or ''),
        'attachment_status': 'reviewer-confirmed',
        'created_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
    }
    try:
        # Ensure page image exists before cropping.
        _ensure_image(edition, page)
        crop_path = _save_crop_png(meta['slug'], label)
        label['crop'] = str(crop_path.relative_to(ROOT))
    except Exception as exc:  # noqa: BLE001
        raise PersistenceError('تعذّر حفظ عينة علامة الوقف') from exc

    path = _labels_path(meta['slug'])
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a', encoding='utf-8') as fh:
        fh.write(json.dumps(label, ensure_ascii=False) + '\n')

    # Mirror to Supabase (best-effort — never fail the save if cloud is slow).
    try:
        crop_bytes = (ROOT / label['crop']).read_bytes()
        _cloud_upload_bytes(label['crop'], crop_bytes, 'image/png')
        _cloud_upsert_label(label)
        # Upload only this machine's jsonl as-is (no full remote merge on save).
        _cloud_upload_bytes(
            f"data/cv/crops_hand/{meta['slug']}/labels.jsonl",
            path.read_bytes(),
            'application/json',
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning('cv_waqf cloud mirror after create failed: %s', exc)

    try:
        _refresh_hand_gallery(meta['slug'])
    except Exception as exc:  # noqa: BLE001
        logger.warning('cv_waqf gallery refresh failed: %s', exc)

    return jsonify({'ok': True, 'label': label, 'cloud': _cloud_ready()})


@editor_bp.route('/api/cv-waqf/labels/<label_id>', methods=['DELETE'])
@require_editor
def cv_waqf_labels_delete(label_id: str):
    # Find which slug owns this id (prefix).
    slug = None
    for ed in _UI_EDITIONS:
        if label_id.startswith(ed['slug'] + '-'):
            slug = ed['slug']
            break
    if not slug:
        # Search all.
        for ed in _UI_EDITIONS:
            rows = _load_labels(ed['slug'])
            if any(r.get('id') == label_id for r in rows):
                slug = ed['slug']
                break
    if not slug:
        return jsonify({'error': 'not found'}), 404

    rows = _load_labels(slug)
    kept = [r for r in rows if r.get('id') != label_id]
    if len(kept) == len(rows):
        return jsonify({'error': 'not found'}), 404
    removed = next(r for r in rows if r.get('id') == label_id)
    _rewrite_labels(slug, kept)
    crop_rel = removed.get('crop')
    if crop_rel:
        crop_path = ROOT / crop_rel
        if crop_path.is_file():
            try:
                crop_path.unlink()
            except OSError:
                pass
    _cloud_delete_label(label_id, crop_rel)
    try:
        labels_path = _labels_path(slug)
        payload = labels_path.read_bytes() if labels_path.is_file() else b''
        _cloud_upload_bytes(
            f'data/cv/crops_hand/{slug}/labels.jsonl',
            payload,
            'application/json',
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning('cv_waqf cloud labels.jsonl refresh failed: %s', exc)
    _refresh_hand_gallery(slug)
    return jsonify({'ok': True, 'deleted': label_id, 'cloud': _cloud_ready()})


def _refresh_hand_gallery(slug: str) -> None:
    """Write a simple HTML gallery of hand-labeled crops."""
    import html as html_lib

    root = _hand_dir(slug)
    root.mkdir(parents=True, exist_ok=True)
    labels = _load_labels(slug)
    counts: dict[str, int] = {}
    for lab in labels:
        counts[lab['symbol']] = counts.get(lab['symbol'], 0) + 1
    parts = [
        '<!DOCTYPE html><html lang="ar" dir="rtl"><head><meta charset="utf-8">',
        f'<title>تسميات يدوية · {html_lib.escape(slug)}</title>',
        '<style>',
        'body{font-family:system-ui,sans-serif;background:#f3ebe0;margin:16px;color:#1c1915}',
        '.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(120px,1fr));gap:8px}',
        '.card{background:#fff;border:1px solid #ddd;border-radius:8px;padding:6px;text-align:center}',
        'img{width:72px;height:72px;object-fit:contain;background:#eee}',
        '</style></head><body>',
        f'<h1>تسميات يدوية · {html_lib.escape(slug)}</h1>',
        f'<p>{html_lib.escape(str(counts))} · المجموع {len(labels)}</p>',
        '<p><a href="/cv-waqf">← الرجوع للتسمية</a></p><div class="grid">',
    ]
    for lab in reversed(labels):
        crop = lab.get('crop') or ''
        # crop is relative to ROOT like data/cv/crops_hand/shamarly/j/xxx.png
        rel = Path(crop).name
        folder = CLASS_DIR.get(lab['symbol'], lab['symbol'])
        src = f'/cv-waqf/labels-assets/{slug}/{folder}/{rel}'
        parts.append(
            f'<div class="card"><div>{html_lib.escape(lab["symbol"])}</div>'
            f'<img src="{html_lib.escape(src)}" alt="">'
            f'<div style="font-size:.7rem">p{lab["page"]}</div></div>'
        )
    parts.append('</div></body></html>')
    (root / 'index.html').write_text('\n'.join(parts), encoding='utf-8')


@editor_bp.route('/cv-waqf/labels')
@editor_bp.route('/cv-waqf/labels/')
@require_editor
def cv_waqf_labels_gallery_index():
    from flask import redirect

    for preferred in ('shamarly', 'bahrain'):
        if _load_labels(preferred) or (_hand_dir(preferred) / 'index.html').is_file():
            _refresh_hand_gallery(preferred)
            return redirect(f'/cv-waqf/labels/{preferred}')
    return jsonify({
        'error': 'no hand labels yet',
        'hint': 'Open /cv-waqf, draw a box on a mark, pick its symbol.',
        'cloud': _cloud_ready(),
    }), 404


@editor_bp.route('/cv-waqf/labels/<slug>')
@require_editor
def cv_waqf_labels_gallery(slug: str):
    from flask import abort

    if slug not in _BY_SLUG:
        abort(404)
    _refresh_hand_gallery(slug)
    index = _hand_dir(slug) / 'index.html'
    if not index.is_file():
        abort(404)
    return send_file(index, mimetype='text/html')


@editor_bp.route('/cv-waqf/labels-assets/<slug>/<path:filename>')
@require_editor
def cv_waqf_labels_assets(slug: str, filename: str):
    from flask import abort, send_from_directory

    if slug not in _BY_SLUG:
        abort(404)
    folder = _hand_dir(slug)
    local = folder / filename
    if not local.is_file():
        # Hydrate from Supabase Storage when working on a fresh machine / cloud.
        object_path = f'data/cv/crops_hand/{slug}/{filename}'
        data = _cloud_download_bytes(object_path)
        if data:
            local.parent.mkdir(parents=True, exist_ok=True)
            local.write_bytes(data)
    if not folder.is_dir() or not local.is_file():
        abort(404)
    return send_from_directory(folder, filename)
