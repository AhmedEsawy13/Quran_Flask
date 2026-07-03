"""JSON asset loading: local file first, jsDelivr CDN fallback on local dev.

Kept free of any Flask dependency (module logger, project-root anchored
paths) so every feature module can load data without importing the app.
"""
import json
import logging
import os

import requests as http_requests

logger = logging.getLogger(__name__)

# Project root (parent of core/).
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# orjson is ~5-8x faster than stdlib json for large files (Rust-based).
# Fall back gracefully to stdlib if not installed.
try:
    import orjson as _orjson

    def _json_load(fh):
        """Read file handle and parse with orjson (accepts bytes or str)."""
        return _orjson.loads(fh.read())
except ImportError:
    _orjson = None  # type: ignore

    def _json_load(fh):  # type: ignore
        return json.load(fh)

# jsDelivr CDN base for large JSON assets (GitHub repo as origin)
CDN_BASE = 'https://cdn.jsdelivr.net/gh/AhmedEsawy13/Quran_Flask@main/QUL_data'

# In-process cache for CDN-fetched JSON blobs
_cdn_cache: dict = {}

# True when running on Vercel / AWS Lambda — local data files are always bundled
# so we skip the outbound CDN fetch to eliminate the cold-start latency.
IS_SERVERLESS = bool(
    os.environ.get('VERCEL') or
    os.environ.get('VERCEL_ENV') or
    os.environ.get('AWS_LAMBDA_FUNCTION_NAME')
)


def load_json_cdn_or_local(cdn_path: str, local_path: str):
    """Load JSON from local file (preferred) or CDN fallback.

    On serverless deployments (Vercel / Lambda) the data files are always
    bundled alongside the function, so we read locally and skip the CDN
    fetch entirely — it would only add latency on cold start.
    On local dev without the data files we fall back to CDN.
    """
    if cdn_path in _cdn_cache:
        return _cdn_cache[cdn_path]
    # Always prefer local file when present (zero network cost).
    abs_local = os.path.join(_ROOT, local_path)
    if os.path.exists(abs_local):
        try:
            # Open in binary mode so orjson can read raw bytes (faster);
            # stdlib json.load also accepts binary file handles in Python 3.
            with open(abs_local, 'rb') as f:
                data = _json_load(f)
            _cdn_cache[cdn_path] = data
            return data
        except Exception as e:
            logger.warning(f'Local load failed for {local_path}: {e}')
    if IS_SERVERLESS:
        logger.error(f'Local file missing on serverless deployment: {local_path}')
        return {}
    # Local dev fallback: try CDN when local file is absent.
    url = f'{CDN_BASE}/{cdn_path}'
    try:
        resp = http_requests.get(url, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        _cdn_cache[cdn_path] = data
        logger.info(f'Loaded {cdn_path} from CDN')
        return data
    except Exception as e:
        logger.error(f'CDN fetch also failed for {cdn_path}: {e}')
        return {}
