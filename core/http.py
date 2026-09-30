"""HTTP plumbing shared by every deployment shape.

Static-asset hashing, the security/caching/compression ``after_request`` hook,
and the JSON error handlers. ``install(app)`` wires all of it onto a Flask app;
``app.create_app`` calls it, so feature blueprints never touch any of this.
"""
import gzip
import hashlib as _hashlib
import os
from io import BytesIO

from flask import current_app, jsonify, request

from core.errors import AppError
from core.http_cache import api_success_cache_class, is_editor_private_path

# Auto cache-busting: hash the file contents so browsers always fetch the
# latest version after a deploy — no more manual ?v=N bumps. Keyed on mtime
# so an edited file gets a new hash (and therefore URL) immediately, even in
# a long-running process that's never restarted — a stale mtime->hash pairing
# here is what used to make static edits invisible until a hard refresh.
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
        "frame-src 'self' https://www.youtube.com https://www.youtube-nocookie.com https://drive.google.com https://docs.google.com https://archive.org https://*.archive.org https://tafsir.app https://*.tafsir.app; "
        "style-src 'self' 'unsafe-inline' https://unpkg.com https://cdnjs.cloudflare.com https://fonts.googleapis.com; "
        "font-src 'self' https://cdnjs.cloudflare.com https://fonts.gstatic.com; "
        # archive.org leaf JPGs + blob: URLs from AtharPdfRef (Bahrain PDF.js pages).
        "img-src 'self' data: blob: https://archive.org https://*.archive.org https://pbs.twimg.com https://lh3.googleusercontent.com https://*.googleusercontent.com; "
        # *.mp3quran.net → the memorize/reciter audio (server7/8/10/13/…).
        # *.googlevideo.com → YouTube audio streams (IFrame Player API).
        # drive.usercontent.google.com → Google Drive direct-download MP3s (_gd_ reciters).
        # huggingface.co → HuggingFace direct MP3s (_gd_ reciters).
        "media-src 'self' https://audio.qurancdn.com https://audio-cdn.tarteel.ai https://everyayah.com https://*.mp3quran.net https://download.tvquran.com https://download.quranicaudio.com https://*.googlevideo.com https://drive.usercontent.google.com https://huggingface.co https://*.huggingface.co https://video.twimg.com; "
        # huggingface.co (+ LFS redirect hosts) → ASR model fallback when /static can't serve the 132MB file.
        # d1.islamhouse.com → Bahrain printed mushaf PDF fetched by pdf.js.
        "connect-src 'self' https://cdn.jsdelivr.net https://huggingface.co https://*.huggingface.co https://*.hf.co https://cdn-lfs.huggingface.co https://api.quran.com https://vercel.live https://vitals.vercel-insights.com https://vercel-vitals.com https://www.youtube.com https://www.googleapis.com https://d1.islamhouse.com https://*.islamhouse.com;"
    )

    # CDN / Cloudflare-friendly caching.
    # Static URLs are content-hashed via static_hash (?h=…) so long TTL is safe.
    path = request.path or ''
    if path.startswith('/static/') and response.status_code == 200:
        response.headers['Cache-Control'] = 'public, max-age=31536000, immutable'
    elif is_editor_private_path(path, request.blueprint):
        response.headers['Cache-Control'] = 'no-store, max-age=0'

    # Cache control for API responses.
    if request.path.startswith('/api/'):
        # Waqf overlays can be adjusted at runtime and are sensitive to
        # matching logic updates. Avoid stale browser cache for these requests.
        # /api/mushaf-editor/* is a live editing tool (spread/progress reads
        # reflect edits made seconds earlier via /api/mushaf-editor/waqf) — a
        # 1-hour cache made just-saved marks appear to "not save" on reload.
        if path.startswith('/api/tawjih/media/'):
            # Proxied X videos are immutable per tweet; allow a day of CDN cache.
            if response.status_code >= 400:
                response.headers['Cache-Control'] = 'no-store, max-age=0'
            else:
                response.headers['Cache-Control'] = 'public, max-age=86400'
        elif (api_success_cache_class(path, request.blueprint) == 'no-store'
                or request.args.get('mushaf_version')):
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
    original = getattr(error, 'original_exception', None) or error
    current_app.logger.error(
        'Unhandled request failure on %s', request.path,
        exc_info=(type(original), original, original.__traceback__),
    )
    return jsonify({"error": "Internal server error"}), 500


def application_error(error: AppError):
    """Render an expected failure without exposing its chained internals."""
    log = current_app.logger.warning if error.status_code < 500 else current_app.logger.error
    log(
        'Request failed [%s] on %s: %s',
        error.code,
        request.path,
        error.public_message,
        exc_info=(type(error), error, error.__traceback__) if error.status_code >= 500 else None,
    )
    return jsonify(error.response_payload()), error.status_code


def install(flask_app):
    """Register the template global, response hook, and error handlers."""
    flask_app.add_template_global(static_hash)
    flask_app.after_request(after_request)
    flask_app.register_error_handler(AppError, application_error)
    flask_app.register_error_handler(404, not_found)
    flask_app.register_error_handler(500, internal_error)
