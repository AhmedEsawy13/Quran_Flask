"""Application factory.

``create_app(features)`` builds an isolated Flask app with the selected feature
blueprints; ``app`` is the default instance served by ``gunicorn app:app``.

    core      — shared Quran text, search, audio, mushaf pages, SEO (always on)
    reading   — المصحف: reader + tafseer / tajweed / i'rab aids
    memorize  — تثبيت: the Circular Segmented Repetition player
    breathing — مُكْث + تدريب: multi-reciter waqf, classical books, practice
    editor    — write-capable editor and internal review tools (ENABLE_EDITOR)

Routes live in ``modules/``; HTTP plumbing (security headers, caching, error
handlers) lives in ``core/http.py``. See README.md → Architecture.
"""
import logging
import os

from flask import Flask
from werkzeug.middleware.proxy_fix import ProxyFix

from core import http
from core.blueprints import breathing_bp, core_bp, editor_bp, memorize_bp, reading_bp
from core.db import close_connection
from modules import load_routes

ALL_BLUEPRINTS = {
    'core': core_bp,
    'reading': reading_bp,
    'memorize': memorize_bp,
    'breathing': breathing_bp,
    'editor': editor_bp,
}
_DEFAULT_FEATURES = {'core', 'reading', 'memorize', 'breathing'}


def _truthy_env(name: str) -> bool:
    return os.environ.get(name, '').strip().lower() in {'1', 'true', 'yes', 'on'}


def _editor_enabled() -> bool:
    """Enable the writer locally, or only on an explicitly marked dyno."""
    if not _truthy_env('ENABLE_EDITOR'):
        return False
    # Heroku sets DYNO on every process. Public dynos must fail closed if an
    # old ENABLE_EDITOR value remains configured; an editor-capable dyno must
    # opt in explicitly with EDITOR_DEPLOYMENT=1.
    return not os.environ.get('DYNO') or _truthy_env('EDITOR_DEPLOYMENT')


def enabled_features():
    """Resolve the feature set for this process from the environment."""
    raw = os.environ.get('FEATURES', '').strip()
    feats = {f.strip() for f in raw.split(',') if f.strip()} if raw else set(_DEFAULT_FEATURES)
    feats.add('core')  # shared foundation is always required
    if _editor_enabled():
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
    load_routes()  # attach routes to the blueprints (idempotent)
    flask_app = Flask(__name__, static_folder='static')
    # Pick up template edits live in development; skip the per-render mtime
    # check on hosted dynos, where templates never change under a running slug.
    flask_app.config['TEMPLATES_AUTO_RELOAD'] = not os.environ.get('DYNO')
    if not flask_app.debug:
        logging.basicConfig(level=logging.INFO)
        flask_app.logger.setLevel(logging.INFO)

    # Heroku + Cloudflare terminate TLS and forward the real client via
    # X-Forwarded-*. Without ProxyFix, request.is_secure / url_for(_external)
    # see http and wrong hosts behind the proxy.
    flask_app.wsgi_app = ProxyFix(
        flask_app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1,
    )

    from modules.seo import public_absolute, public_base_url

    @flask_app.context_processor
    def inject_seo():
        return {
            'public_base_url': public_base_url(),
            'public_absolute': public_absolute,
            'editor_enabled': 'editor' in flask_app.blueprints,
        }

    http.install(flask_app)
    flask_app.teardown_appcontext(close_connection)
    return register_blueprints(flask_app, features)


# The default instance served by `gunicorn app:app`.
app = create_app()


if __name__ == '__main__':
    os.environ.setdefault('ENABLE_EDITOR', '1')  # local runs get the editor
    register_blueprints(app, enabled_features())
    app.run(debug=os.getenv('FLASK_ENV') == 'development', port=5001)
