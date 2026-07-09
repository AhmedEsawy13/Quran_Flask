from flask import Flask, jsonify, request
import sqlite3
import os
import logging

import gzip
from io import BytesIO


app = Flask(__name__, static_folder='static')

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

# Configure logging
if not app.debug:
    logging.basicConfig(level=logging.INFO)
    app.logger.setLevel(logging.INFO)

# Auto cache-busting: hash the file contents so browsers always fetch the
# latest version after a deploy — no more manual ?v=N bumps.
import hashlib as _hashlib
_static_hash_cache: dict[str, str] = {}

@app.template_global()
def static_hash(filename: str) -> str:
    """Return /static/<filename>?h=<8-char content hash>."""
    h = _static_hash_cache.get(filename)
    if h is None:
        path = os.path.join(app.static_folder, filename)
        try:
            with open(path, 'rb') as f:
                h = _hashlib.md5(f.read()).hexdigest()[:8]
        except OSError:
            h = '0'
        _static_hash_cache[filename] = h
    return f'/static/{filename}?h={h}'

# Compression and security improvements
@app.after_request
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
        "worker-src 'self' blob:; "
        "frame-src 'self' https://www.youtube.com https://www.youtube-nocookie.com; "
        "style-src 'self' 'unsafe-inline' https://unpkg.com https://cdnjs.cloudflare.com https://fonts.googleapis.com; "
        "font-src 'self' https://cdnjs.cloudflare.com https://fonts.gstatic.com; "
        "img-src 'self' data:; "
        # *.mp3quran.net → the memorize/reciter audio (server7/8/10/13/…).
        # *.googlevideo.com → YouTube audio streams (IFrame Player API).
        # drive.usercontent.google.com → Google Drive direct-download MP3s (_gd_ reciters).
        # huggingface.co → HuggingFace direct MP3s (_gd_ reciters).
        "media-src 'self' https://audio.qurancdn.com https://audio-cdn.tarteel.ai https://everyayah.com https://*.mp3quran.net https://download.tvquran.com https://download.quranicaudio.com https://*.googlevideo.com https://drive.usercontent.google.com https://huggingface.co https://*.huggingface.co; "
        # huggingface.co (+ LFS redirect hosts) → ASR model fallback when /static can't serve the 132MB file.
        "connect-src 'self' https://cdn.jsdelivr.net https://huggingface.co https://*.huggingface.co https://*.hf.co https://cdn-lfs.huggingface.co https://api.quran.com https://vercel.live https://vitals.vercel-insights.com https://vercel-vitals.com https://www.youtube.com https://www.googleapis.com;"
    )
    
    # Cache control for API responses.
    if request.path.startswith('/api/'):
        # Waqf overlays can be adjusted at runtime and are sensitive to
        # matching logic updates. Avoid stale browser cache for these requests.
        # /api/mushaf-editor/* is a live editing tool (spread/progress reads
        # reflect edits made seconds earlier via /api/mushaf-editor/waqf) — a
        # 1-hour cache made just-saved marks appear to "not save" on reload.
        if request.args.get('mushaf_version') or request.path.startswith('/api/mushaf-editor/'):
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
@app.errorhandler(404)
def not_found(error):
    return jsonify({"error": "Resource not found"}), 404

@app.errorhandler(500)
def internal_error(error):
    app.logger.error(f"Internal server error: {error}")
    return jsonify({"error": "Internal server error"}), 500

from core.config import (
    DATABASE, MUSHAF_WAQF_DATABASE,  # noqa: F401 — tests reach this via app.MUSHAF_WAQF_DATABASE
    _BASE_DIR,  # noqa: F401 — pipeline/build_classical_waqf.py reaches this via app._BASE_DIR
)
from core.text import (
    _normalize_for_search,  # noqa: F401 — tests/pipeline reach this via app._normalize_for_search
)


import modules.editor  # noqa: F401 — attaches editor routes to editor_bp
from modules.layouts import (  # noqa: F401 — importing also registers layout routes
    _find_mushaf_row_match_index,
    _normalize_mushaf_word_token,
)
import modules.breathing        # noqa: F401 — attaches breathing routes to breathing_bp
import modules.waqf_research    # noqa: F401 — attaches waqf-research routes to breathing_bp
from modules.breathing import _verse_word_texts, _mark_word_context  # noqa: F401 — tests reach these via app.<name>
from modules.waqf_research import (  # noqa: F401 — tests/pipeline reach these via app.<name>
    _RESEARCH_CACHE_DIR, _build_reciter_clustering, _build_mushaf_similarity,
    _build_mushaf_agreement_index, _build_ibtidaa_index,
)
import modules.reading          # noqa: F401 — attaches reading routes to reading_bp
import modules.memorize         # noqa: F401 — attaches memorize routes to memorize_bp
import modules.quran_api        # noqa: F401 — attaches core_bp routes to core_bp
from core.datasets import (
    qpc_hafs_data_normalized,  # noqa: F401 — pipeline/build_classical_waqf.py reaches this via app.<name>
    surahs_data,  # noqa: F401 — pipeline/build_classical_waqf.py reaches this via app.surahs_data
)



# Load audio data — CDN first, local fallback
# Local files now live under data/word_timestamps/






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
    app.logger.warning(f'Could not create word_name index: {_wn_err}')


# Database helper functions (moved to core.db so feature blueprints can share
# the per-request connection without importing the main app module).
from core.db import close_connection
app.teardown_appcontext(close_connection)




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
    if os.environ.get('ENABLE_EDITOR'):
        feats.add('editor')
    else:
        feats.discard('editor')  # never expose the writer unless explicitly enabled
    return feats


def register_blueprints(flask_app, features=None):
    features = features if features is not None else enabled_features()
    for name, bp in ALL_BLUEPRINTS.items():
        # Idempotent: skip blueprints already mounted (create_app may be called
        # after the module-level registration below).
        if name in features and name not in flask_app.blueprints:
            flask_app.register_blueprint(bp)
    flask_app.logger.info(f"Enabled features: {sorted(features)}")
    return flask_app


def create_app(features=None):
    """Return the configured application, mounting the selected features.

    Exposed for WSGI entrypoints / future per-feature deployments. The module
    also configures the shared ``app`` object at import for ``gunicorn app:app``.
    """
    return register_blueprints(app, features)


# Configure the default module-level app (used by `gunicorn app:app`).
register_blueprints(app)


if __name__ == '__main__':
    os.environ.setdefault('ENABLE_EDITOR', '1')
    register_blueprints(app)
    app.run(debug=os.getenv('FLASK_ENV') == 'development', port=5001)
