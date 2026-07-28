from flask import Flask, current_app, jsonify, request
import sqlite3
import os
import logging

import gzip
from io import BytesIO


# Feature blueprints. Routes are attached to these below (one per feature area)
# so each feature can be enabled/disabled per deployment via the FEATURES env
# var — and the write-capable editor can be gated to localhost only.
#   core      — shared Quran text, search, and mushaf page-rendering (read-only)
#   reading   — main mushaf reading page + tafseer/tajweed/eerab aids
#   memorize  — repeat-verses player
#   breathing — reciter-validated waqf stops (دليل التنفس)
#   editor    — /mushaf-editor click-to-edit waqf tool (the ONLY writer)
from core.blueprints import core_bp, reading_bp, memorize_bp, breathing_bp, editor_bp

# (Flask-Compress is not installed/initialised here — the previous
# COMPRESS_* config keys had no effect and were removed. JSON gzip is
# handled inline in after_request below.)

# Auto cache-busting: hash the file contents so browsers always fetch the
# latest version after a deploy — no more manual ?v=N bumps. Keyed on mtime
# so an edited file gets a new hash (and therefore URL) immediately, even in
# a long-running process that's never restarted — a stale mtime->hash pairing
# here is what used to make static edits invisible until a hard refresh.
import hashlib as _hashlib
_static_hash_cache: dict[str, tuple[float, str]] = {}

def static_hash(filename: str) -> str:
    """Return /static/<filename>?h=<8-char content hash>."""
    path = os.path.join(current_app.static_folder, filename)
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return f'/static/{filename}?h=0'
    cached = _static_hash_cache.get(filename)
    if cached is None or cached[0] != mtime:
        with open(path, 'rb') as f:
            h = _hashlib.md5(f.read()).hexdigest()[:8]
        _static_hash_cache[filename] = (mtime, h)
    else:
        h = cached[1]
    return f'/static/{filename}?h={h}'

# Compression and security improvements
def after_request(response):
    """Add security headers and compression to all responses"""
    # Security headers
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Content-Security-Policy'] = (
        "default-src 'self'; "
        # cdn.jsdelivr.net + blob: → onnxruntime-web (recitation ASR); wasm needs 'unsafe-eval'/'wasm-unsafe-eval'.
        "script-src 'self' 'unsafe-inline' 'unsafe-eval' 'wasm-unsafe-eval' blob: https://unpkg.com https://cdnjs.cloudflare.com https://cdn.jsdelivr.net https://vercel.live https://va.vercel-scripts.com https://www.youtube.com; "
        # pdf.js worker (Bahrain remote scan) loads from jsDelivr.
        "worker-src 'self' blob: https://cdn.jsdelivr.net; "
        # archive.org / tafsir.app → mushaf-editor printed-edition reference panel.
        "frame-src 'self' https://www.youtube.com https://www.youtube-nocookie.com https://archive.org https://*.archive.org https://tafsir.app https://*.tafsir.app; "
        "style-src 'self' 'unsafe-inline' https://unpkg.com https://cdnjs.cloudflare.com https://fonts.googleapis.com; "
        "font-src 'self' https://cdnjs.cloudflare.com https://fonts.gstatic.com; "
        # archive.org leaf JPGs + blob: URLs from AtharPdfRef (Bahrain PDF.js pages).
        "img-src 'self' data: blob: https://archive.org https://*.archive.org; "
        # *.mp3quran.net → the memorize/reciter audio (server7/8/10/13/…).
        # *.googlevideo.com → YouTube audio streams (IFrame Player API).
        # drive.usercontent.google.com → Google Drive direct-download MP3s (_gd_ reciters).
        # huggingface.co → HuggingFace direct MP3s (_gd_ reciters).
        "media-src 'self' https://audio.qurancdn.com https://audio-cdn.tarteel.ai https://everyayah.com https://*.mp3quran.net https://download.tvquran.com https://download.quranicaudio.com https://*.googlevideo.com https://drive.usercontent.google.com https://huggingface.co https://*.huggingface.co; "
        # huggingface.co (+ LFS redirect hosts) → ASR model fallback when /static can't serve the 132MB file.
        # d1.islamhouse.com → Bahrain printed mushaf PDF fetched by pdf.js.
        "connect-src 'self' https://cdn.jsdelivr.net https://huggingface.co https://*.huggingface.co https://*.hf.co https://cdn-lfs.huggingface.co https://api.quran.com https://vercel.live https://vitals.vercel-insights.com https://vercel-vitals.com https://www.youtube.com https://www.googleapis.com https://d1.islamhouse.com https://*.islamhouse.com;"
    )

    # CDN / Cloudflare-friendly caching.
    # Static URLs are content-hashed via static_hash (?h=…) so long TTL is safe.
    path = request.path or ''
    if path.startswith('/static/') and response.status_code == 200:
        response.headers['Cache-Control'] = 'public, max-age=31536000, immutable'
    elif (
        path.startswith('/mushaf-editor')
        or path.startswith('/layout-studio')
        or path.startswith('/azhar-layout')
        or path.startswith('/font-lab')
    ):
        response.headers['Cache-Control'] = 'no-store, max-age=0'

    # Cache control for API responses.
    if request.path.startswith('/api/'):
        # Waqf overlays can be adjusted at runtime and are sensitive to
        # matching logic updates. Avoid stale browser cache for these requests.
        # /api/mushaf-editor/* is a live editing tool (spread/progress reads
        # reflect edits made seconds earlier via /api/mushaf-editor/waqf) — a
        # 1-hour cache made just-saved marks appear to "not save" on reload.
        if (request.args.get('mushaf_version')
                or request.path.startswith('/api/mushaf-editor/')
                or request.path.startswith('/api/azhar-layout/')
                or request.path.startswith('/api/layout-studio/')
                or request.path.startswith('/api/classical-review/')):
            response.headers['Cache-Control'] = 'no-store, max-age=0'
        elif request.path.startswith('/api/waqf-research/'):
            # Heavy Quran-wide analyses are cached SERVER-side (instant after the
            # first build), so don't pin them in the browser for an hour — a
            # redeploy that changes the computation must show up immediately
            # instead of serving a stale aggregate.
            response.headers['Cache-Control'] = 'no-store, max-age=0'
        elif response.status_code >= 400:
            # Never cache error responses: a transient 404/500/503 (e.g. during a
            # deploy, or the breathing guide's 503) must not be pinned in the
            # browser/CDN for an hour and shadow the endpoint once it recovers.
            response.headers['Cache-Control'] = 'no-store, max-age=0'
        else:
            response.headers['Cache-Control'] = 'public, max-age=3600'
    
    # GZIP compression for JSON responses - check early to avoid unnecessary processing.
    # Skip if the response is already encoded (e.g. by a downstream middleware) so we
    # don't double-encode (gzip(gzip(...)) — broken clients).
    if (response.status_code == 200 and
        not response.direct_passthrough and
        not response.headers.get('Content-Encoding') and
        response.content_type and 'application/json' in response.content_type and
        'gzip' in request.headers.get('Accept-Encoding', '').lower()):

        response_data = response.get_data()
        # Only compress if response is large enough
        if len(response_data) > 500:
            gzip_buffer = BytesIO()
            with gzip.GzipFile(mode='wb', fileobj=gzip_buffer, compresslevel=6) as gzip_file:
                gzip_file.write(response_data)
            
            compressed = gzip_buffer.getvalue()
            response.set_data(compressed)
            response.headers['Content-Encoding'] = 'gzip'
            response.headers['Content-Length'] = str(len(compressed))
            response.headers['Vary'] = 'Accept-Encoding'
    
    return response

# Error handlers
def not_found(error):
    return jsonify({"error": "Resource not found"}), 404

def internal_error(error):
    current_app.logger.error(f"Internal server error: {error}")
    return jsonify({"error": "Internal server error"}), 500

from core.config import (
    DATABASE, MUSHAF_WAQF_DATABASE,  # noqa: F401 — tests reach this via app.MUSHAF_WAQF_DATABASE
    _BASE_DIR,  # noqa: F401 — pipeline/build_classical_waqf.py reaches this via app._BASE_DIR
)
from core.text import (
    _normalize_for_search,  # noqa: F401 — tests/pipeline reach this via app._normalize_for_search
)


import modules.editor  # noqa: F401 — attaches editor routes to editor_bp
import modules.azhar_layout  # noqa: F401 — /azhar-layout aliases → layout studio
import modules.layout_studio  # noqa: F401 — /layout-studio + /api/layout-studio/*
import modules.font_lab  # noqa: F401 — /font-lab OpenType playground
from modules.layouts import (  # noqa: F401 — importing also registers layout routes
    _find_mushaf_row_match_index,
    _normalize_mushaf_word_token,
)
import modules.breathing        # noqa: F401 — attaches breathing routes to breathing_bp
import modules.classical_review  # noqa: F401 — local-only book review routes on editor_bp
import modules.waqf_research    # noqa: F401 — attaches waqf-research routes to breathing_bp
from modules.breathing import _verse_word_texts, _mark_word_context  # noqa: F401 — tests reach these via app.<name>
from modules.waqf_research import (  # noqa: F401 — tests/pipeline reach these via app.<name>
    _RESEARCH_CACHE_DIR, _build_reciter_clustering, _build_mushaf_similarity,
    _build_mushaf_agreement_index, _build_ibtidaa_index,
)
import modules.reading          # noqa: F401 — attaches reading routes to reading_bp
import modules.memorize         # noqa: F401 — attaches memorize routes to memorize_bp
import modules.quran_api        # noqa: F401 — attaches core_bp routes to core_bp
import modules.seo              # noqa: F401 — /robots.txt /sitemap.xml /llms.txt
from core.datasets import (
    qpc_hafs_data_normalized,  # noqa: F401 — pipeline/build_classical_waqf.py reaches this via app.<name>
    surahs_data,  # noqa: F401 — pipeline/build_classical_waqf.py reaches this via app.surahs_data
)




# Ensure word_name.db has an index on (surah_number, ayah_number) for fast per-ayah
# lookups. Creates the index if missing; safe to call on every startup.
try:
    _wn_conn = sqlite3.connect(DATABASE)
    _wn_conn.execute(
        'CREATE INDEX IF NOT EXISTS idx_verses_surah_ayah ON verses(surah_number, ayah_number)'
    )
    _wn_conn.commit()
    _wn_conn.close()
except sqlite3.Error as _wn_err:
    logging.warning(f'Could not create word_name index: {_wn_err}')


# Database helper functions (moved to core.db so feature blueprints can share
# the per-request connection without importing the main app module).
from core.db import close_connection




# ---------------------------------------------------------------------------
ALL_BLUEPRINTS = {
    'core': core_bp,
    'reading': reading_bp,
    'memorize': memorize_bp,
    'breathing': breathing_bp,
    'editor': editor_bp,
}
_DEFAULT_FEATURES = {'core', 'reading', 'memorize', 'breathing'}


def enabled_features():
    """Resolve the feature set for this process from the environment."""
    raw = os.environ.get('FEATURES', '').strip()
    feats = {f.strip() for f in raw.split(',') if f.strip()} if raw else set(_DEFAULT_FEATURES)
    feats.add('core')  # shared foundation is always required
    if os.environ.get('ENABLE_EDITOR', '').strip().lower() in {'1', 'true', 'yes', 'on'}:
        feats.add('editor')
    else:
        feats.discard('editor')  # never expose the writer unless explicitly enabled
    return feats


def register_blueprints(flask_app, features=None):
    features = set(features) if features is not None else enabled_features()
    features.add('core')
    for name, bp in ALL_BLUEPRINTS.items():
        # Idempotent when configuration is applied to the same app twice.
        if name in features and name not in flask_app.blueprints:
            flask_app.register_blueprint(bp)
    flask_app.logger.info(f"Enabled features: {sorted(features)}")
    return flask_app


def create_app(features=None):
    """Build an isolated Flask application with the selected feature modules."""
    flask_app = Flask(__name__, static_folder='static')
    # Always notice template edits, even when debug mode is disabled.
    flask_app.config['TEMPLATES_AUTO_RELOAD'] = True
    if not flask_app.debug:
        logging.basicConfig(level=logging.INFO)
        flask_app.logger.setLevel(logging.INFO)
    flask_app.add_template_global(static_hash)

    # Heroku + Cloudflare terminate TLS and forward the real client via
    # X-Forwarded-*. Without ProxyFix, request.is_secure / url_for(_external)
    # see http and wrong hosts behind the proxy.
    from werkzeug.middleware.proxy_fix import ProxyFix
    flask_app.wsgi_app = ProxyFix(
        flask_app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1,
    )

    from modules.seo import public_absolute, public_base_url

    @flask_app.context_processor
    def inject_seo():
        return {
            'public_base_url': public_base_url(),
            'public_absolute': public_absolute,
        }

    flask_app.after_request(after_request)
    flask_app.register_error_handler(404, not_found)
    flask_app.register_error_handler(500, internal_error)
    flask_app.teardown_appcontext(close_connection)
    return register_blueprints(flask_app, features)


# Configure the default module-level app (used by `gunicorn app:app`).
app = create_app()


if __name__ == '__main__':
    os.environ.setdefault('ENABLE_EDITOR', '1')
    register_blueprints(app, enabled_features())
    app.run(debug=os.getenv('FLASK_ENV') == 'development', port=5001)
