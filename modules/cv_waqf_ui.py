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
from core.loader import IS_SERVERLESS as _IS_SERVERLESS

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
)
_BY_ID = {e['id']: e for e in _UI_EDITIONS}


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
    out = ARTIFACT_CACHE / f'{slug}_p{page:03d}_{min_conf:.2f}.json'
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


def _hand_dir(slug: str) -> Path:
    return HAND_ROOT / slug


def _labels_path(slug: str) -> Path:
    return _hand_dir(slug) / 'labels.jsonl'


def _load_labels(slug: str, page: int | None = None) -> list[dict]:
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
        if page is not None and int(row.get('page') or -1) != page:
            continue
        out.append(row)
    return out


def _rewrite_labels(slug: str, rows: list[dict]) -> None:
    path = _labels_path(slug)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    with tmp.open('w', encoding='utf-8') as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + '\n')
    tmp.replace(path)


def _save_crop_png(slug: str, label: dict) -> Path:
    """Crop the page JPEG to a 48×48 training PNG for this label."""
    from pipeline.cv_waqf.config import CROP_SIZE, EDITIONS
    from pipeline.cv_waqf.pages import ensure_page_image

    edition = label['edition']
    page = int(label['page'])
    box = [int(v) for v in label['box']]
    x0, y0, x1, y1 = box
    if x1 < x0:
        x0, x1 = x1, x0
    if y1 < y0:
        y0, y1 = y1, y0

    try:
        import cv2
        import numpy as np
    except ImportError:
        # Fall back to subprocess with CV venv for the crop write.
        return _save_crop_via_subprocess(slug, label)

    spec = EDITIONS[edition]
    img_path = ensure_page_image(spec, page)
    bgr = cv2.imread(str(img_path), cv2.IMREAD_COLOR)
    if bgr is None:
        raise RuntimeError(f'cannot read {img_path}')
    h, w = bgr.shape[:2]
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(w, x1), min(h, y1)
    patch = bgr[y0:y1, x0:x1]
    if patch.size == 0:
        raise RuntimeError('empty crop')
    gray = cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY)
    ph, pw = gray.shape[:2]
    side = max(ph, pw, 1)
    canvas = np.full((side, side), 255, dtype=np.uint8)
    oy = (side - ph) // 2
    ox = (side - pw) // 2
    canvas[oy:oy + ph, ox:ox + pw] = gray
    crop = cv2.resize(canvas, (CROP_SIZE, CROP_SIZE), interpolation=cv2.INTER_AREA)

    sym = label['symbol']
    folder = _hand_dir(slug) / CLASS_DIR.get(sym, sym)
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / f"{label['id']}.png"
    cv2.imwrite(str(dest), crop)
    return dest


def _save_crop_via_subprocess(slug: str, label: dict) -> Path:
    out = _hand_dir(slug) / CLASS_DIR.get(label['symbol'], label['symbol'])
    out.mkdir(parents=True, exist_ok=True)
    dest = out / f"{label['id']}.png"
    payload = json.dumps({'slug': slug, 'label': label, 'dest': str(dest)}, ensure_ascii=False)
    code = (
        'import json,sys,cv2,numpy as np\n'
        'from pathlib import Path\n'
        'from pipeline.cv_waqf.config import CROP_SIZE, EDITIONS\n'
        'from pipeline.cv_waqf.pages import ensure_page_image\n'
        f'd=json.loads({payload!r})\n'
        'lab=d["label"]; dest=Path(d["dest"])\n'
        'spec=EDITIONS[lab["edition"]]\n'
        'img=cv2.imread(str(ensure_page_image(spec,int(lab["page"]))))\n'
        'x0,y0,x1,y1=[int(v) for v in lab["box"]]\n'
        'if x1<x0: x0,x1=x1,x0\n'
        'if y1<y0: y0,y1=y1,y0\n'
        'h,w=img.shape[:2]\n'
        'x0,y0=max(0,x0),max(0,y0); x1,y1=min(w,x1),min(h,y1)\n'
        'gray=cv2.cvtColor(img[y0:y1,x0:x1], cv2.COLOR_BGR2GRAY)\n'
        'ph,pw=gray.shape[:2]; side=max(ph,pw,1)\n'
        'canvas=np.full((side,side),255,np.uint8)\n'
        'canvas[(side-ph)//2:(side-ph)//2+ph,(side-pw)//2:(side-pw)//2+pw]=gray\n'
        'crop=cv2.resize(canvas,(CROP_SIZE,CROP_SIZE),interpolation=cv2.INTER_AREA)\n'
        'dest.parent.mkdir(parents=True, exist_ok=True)\n'
        'cv2.imwrite(str(dest), crop)\n'
    )
    env = os.environ.copy()
    env['PYTHONPATH'] = str(ROOT)
    proc = subprocess.run(
        [_resolve_cv_python(), '-c', code],
        cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=60,
    )
    if proc.returncode != 0 or not dest.is_file():
        raise RuntimeError((proc.stderr or proc.stdout or 'crop failed')[-500:])
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
        logger.exception('cv-waqf image %s p%s', slug, page_number)
        return jsonify({'error': str(exc)}), 404
    return send_file(path, mimetype='image/jpeg', max_age=3600, conditional=True)


@editor_bp.route('/cv-waqf/crops')
@editor_bp.route('/cv-waqf/crops/')
@editor_bp.route('/cv-waqf/crops/<slug>')
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
    index = root / slug / 'index.html'
    if not index.is_file():
        abort(404)
    return send_file(index, mimetype='text/html')


@editor_bp.route('/cv-waqf/crops/<slug>/<path:filename>')
def cv_waqf_crops_asset(slug: str, filename: str):
    from flask import abort, send_from_directory

    folder = ROOT / 'data' / 'cv' / 'crops_labeled' / slug
    if not folder.is_dir():
        abort(404)
    return send_from_directory(folder, filename)


@editor_bp.route('/api/cv-waqf/page/<int:page_number>', methods=['GET'])
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
        min_conf = float(request.args.get('min_conf') or 0.55)
    except (TypeError, ValueError):
        min_conf = 0.55
    min_conf = max(0.2, min(0.95, min_conf))

    try:
        payload = _build_payload(edition, page_number, min_conf, meta['slug'])
    except Exception as exc:  # noqa: BLE001
        logger.exception('cv-waqf page %s %s', edition, page_number)
        return jsonify({
            'error': str(exc),
            'hint': (
                'Create the CV venv and train once:\n'
                '  python3 -m venv .venv-cv\n'
                '  .venv-cv/bin/pip install -r requirements-cv.txt\n'
                '  PYTHONPATH=. .venv-cv/bin/python -m pipeline.cv_waqf train'
            ),
        }), 500

    payload['min_page'] = meta['min_page']
    payload['max_page'] = meta['max_page']
    payload['slug'] = meta['slug']
    payload['image_url'] = (
        f"/api/cv-waqf/image/{meta['slug']}/{page_number}.jpg"
    )
    return jsonify(payload)


@editor_bp.route('/api/cv-waqf/labels', methods=['GET'])
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
    return jsonify({
        'edition': edition,
        'slug': meta['slug'],
        'page': page,
        'labels': labels,
        'count': len(labels),
    })


@editor_bp.route('/api/cv-waqf/labels', methods=['POST'])
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
        'created_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
    }
    try:
        # Ensure page image exists before cropping.
        _ensure_image(edition, page)
        crop_path = _save_crop_png(meta['slug'], label)
        label['crop'] = str(crop_path.relative_to(ROOT))
    except Exception as exc:  # noqa: BLE001
        logger.exception('save hand crop failed')
        return jsonify({'error': str(exc)}), 500

    path = _labels_path(meta['slug'])
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a', encoding='utf-8') as fh:
        fh.write(json.dumps(label, ensure_ascii=False) + '\n')

    _refresh_hand_gallery(meta['slug'])
    return jsonify({'ok': True, 'label': label})


@editor_bp.route('/api/cv-waqf/labels/<label_id>', methods=['DELETE'])
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
    _refresh_hand_gallery(slug)
    return jsonify({'ok': True, 'deleted': label_id})


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
def cv_waqf_labels_gallery_index():
    from flask import redirect

    for preferred in ('shamarly', 'bahrain'):
        if (_hand_dir(preferred) / 'index.html').is_file():
            return redirect(f'/cv-waqf/labels/{preferred}')
    return jsonify({
        'error': 'no hand labels yet',
        'hint': 'Open /cv-waqf, draw a box on a mark, pick its symbol.',
    }), 404


@editor_bp.route('/cv-waqf/labels/<slug>')
def cv_waqf_labels_gallery(slug: str):
    from flask import abort

    index = _hand_dir(slug) / 'index.html'
    if not index.is_file():
        _refresh_hand_gallery(slug)
    if not index.is_file():
        abort(404)
    return send_file(index, mimetype='text/html')


@editor_bp.route('/cv-waqf/labels-assets/<slug>/<path:filename>')
def cv_waqf_labels_assets(slug: str, filename: str):
    from flask import abort, send_from_directory

    folder = _hand_dir(slug)
    if not folder.is_dir():
        abort(404)
    return send_from_directory(folder, filename)
