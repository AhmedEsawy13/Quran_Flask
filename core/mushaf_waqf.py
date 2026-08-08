"""Access layer for the printed-mushaf waqf database (data/mushaf_waqf.db).

Column discovery + whitelist validation (the version names are SQL
identifiers, so they must be validated before interpolation), cached
per-ayah symbol fetches, and segment-boundary lookups. No Flask dependency.

When Supabase is configured, قطر/الكويت/البحرين public reads use **published**
cloud marks only (drafts stay editor-private). Other editions stay on SQLite.
"""
import logging
import os
import sqlite3
from collections import OrderedDict
from functools import lru_cache

from core.config import MUSHAF_WAQF_DATABASE, PUBLIC_CLOUD_WAQF_EDITIONS
from core.lru import _BoundedLRU

logger = logging.getLogger(__name__)

_CLOUD_FETCH_FAILED = object()


@lru_cache(maxsize=1)
def _get_mushaf_table_columns():
    """Discover waqf table columns once for safe dynamic SQL decisions."""
    if not os.path.exists(MUSHAF_WAQF_DATABASE):
        return tuple()
    try:
        conn = sqlite3.connect(MUSHAF_WAQF_DATABASE)
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(waqf)")
        cols = cursor.fetchall()
        conn.close()
        return tuple(col[1] for col in cols)
    except Exception as e:
        logger.error(f"Error loading mushaf table columns: {e}")
        return tuple()


@lru_cache(maxsize=1)
def _get_mushaf_version_whitelist():
    """Discover allowed Mushaf version column names once.

    Returned set is used to reject any user-supplied column name, preventing
    SQL identifier injection when column names are interpolated into queries
    (SQLite does not allow parameterising column identifiers).
    """
    cols = _get_mushaf_table_columns()
    if not cols:
        return frozenset()
    # Columns 0-3: Sura, SuraName, Ayah, Word. Versions start at column 4.
    helper_columns = {
        'token_index', 'word_index', 'word_position', 'word_key', 'word_no',
        'رقم_الكلمة', 'ترتيب_الكلمة',
    }
    return frozenset(col for col in cols[4:] if col not in helper_columns)


@lru_cache(maxsize=1)
def _get_mushaf_position_column():
    """Optional disambiguation column for absolute word position/token key.

    If DB is later enriched with any of these columns, matching can be exact
    even when words repeat in the same ayah.
    """
    cols = set(_get_mushaf_table_columns())
    for candidate in (
        'word_index', 'token_index', 'word_position', 'word_key', 'word_no',
        'رقم_الكلمة', 'ترتيب_الكلمة'
    ):
        if candidate in cols:
            return candidate
    return None


def _is_valid_mushaf_version(mushaf_version):
    if not mushaf_version:
        return False
    # A configured cloud source is a first-class capability. Requiring the
    # edition to also exist as a legacy SQLite column made a valid deployment
    # silently return no marks when that local artifact was trimmed or stale.
    if mushaf_version in PUBLIC_CLOUD_WAQF_EDITIONS:
        from core import supabase_editor as sb
        if sb.is_configured():
            return True
    return mushaf_version in _get_mushaf_version_whitelist()


def _get_waqf_at_boundary(surah_number, ayah_number, end_word, versions):
    """Return waqf entries [{symbols, version}] for all versions at a segment boundary.

    The positions.db end_word equals the waqf DB word_index for the last word of
    that segment.  We try end_word first, then end_word-1 as a 1-off fallback.
    """
    result = []
    if not os.path.exists(MUSHAF_WAQF_DATABASE):
        return result
    try:
        conn = sqlite3.connect(MUSHAF_WAQF_DATABASE)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        for ver in versions:
            # This helper is SQLite-only. Cloud capability validation must not
            # authorize an identifier that is absent from this local schema.
            if ver not in _get_mushaf_version_whitelist():
                continue
            qcol = '"' + ver.replace('"', '""') + '"'
            for wi in (end_word, end_word - 1):
                cur.execute(f"""
                    SELECT {qcol} as symbol FROM waqf
                    WHERE "السورة" = ? AND "الآية" = ? AND word_index = ?
                    AND {qcol} IS NOT NULL AND {qcol} != ''
                """, (surah_number, ayah_number, wi))
                row = cur.fetchone()
                if row:
                    result.append({'symbols': row['symbol'], 'version': ver})
                    break
        conn.close()
    except Exception as e:
        logger.error(f'Error fetching waqf at boundary: {e}')
    return result


def get_mushaf_waqf_symbols(surah_number, ayah_number, mushaf_version):
    """Fetch waqf symbols from Excel-source DB for one or more Mushaf versions.

    mushaf_version may be a string (single version) or a list of strings.
    Each returned entry gains a 'version' field identifying its source.
    """
    if isinstance(mushaf_version, (list, tuple)):
        versions = [v for v in mushaf_version if _is_valid_mushaf_version(v)]
    else:
        versions = [mushaf_version] if _is_valid_mushaf_version(mushaf_version) else []

    if not versions:
        return []

    all_rows = []
    for ver in versions:
        # Cloud editions can resolve without a local mushaf_waqf.db when Supabase
        # is configured; SQLite editions still need the file.
        if ver not in PUBLIC_CLOUD_WAQF_EDITIONS and not os.path.exists(MUSHAF_WAQF_DATABASE):
            continue
        rows = _fetch_single_mushaf_waqf(surah_number, ayah_number, ver)
        for r in rows:
            r['version'] = ver
        all_rows.extend(rows)
    return all_rows


# In-process cache for mushaf waqf DB lookups.
# Callers mutate the returned dicts (adding a 'version' key) so we always
# return a list of fresh dict copies, keeping the cached originals clean.
# Bounded — ~6236 ayahs × ~10 versions = ~62K possible keys.
_mushaf_waqf_cache: _BoundedLRU = _BoundedLRU(maxsize=8192)


def invalidate_cloud_waqf_cache(edition=None, surah=None, ayah=None):
    """Drop cached public mushaf waqf rows after draft writes or publish."""
    with _mushaf_waqf_cache._lock:
        if edition is None and surah is None and ayah is None:
            OrderedDict.clear(_mushaf_waqf_cache)
            return
        drop = []
        for key in list(OrderedDict.keys(_mushaf_waqf_cache)):
            s, a, ver = key
            if edition is not None and ver != edition:
                continue
            if surah is not None and s != surah:
                continue
            if ayah is not None and a != ayah:
                continue
            drop.append(key)
        for key in drop:
            OrderedDict.pop(_mushaf_waqf_cache, key, None)


def _fetch_published_cloud_waqf(surah_number, ayah_number, mushaf_version):
    """Published marks from Supabase for a cloud-editor edition."""
    from core import supabase_editor as sb

    if not sb.is_configured():
        return None  # signal: fall through to SQLite
    try:
        rows = sb.fetch_marks(
            edition=mushaf_version,
            status='published',
            surah=surah_number,
            ayah=ayah_number,
        )
    except sb.SupabaseEditorError as e:
        logger.error('cloud published waqf fetch failed: %s', e)
        # Do not fall through to SQLite, but also do not cache this transient
        # outage as a permanently empty ayah.
        return _CLOUD_FETCH_FAILED
    return _cloud_rows_to_mushaf_rows(rows)


def _cloud_rows_to_mushaf_rows(rows) -> list[dict]:
    result = []
    for row in rows:
        symbol = (row.get('symbol') or '').strip()
        if not symbol:
            continue
        ti = row.get('token_index')
        try:
            ti = int(ti) if ti is not None else None
        except (TypeError, ValueError):
            ti = None
        result.append({
            'clean_token': row.get('word_text') or '',
            'symbols': symbol,
            'token_index': ti,  # already 0-based in cloud schema
            'word_index': None,
            'word_position': None,
            'index_space': 'ayah-token-0based',
        })
    return result


def prefetch_cloud_published_for_ayahs(ayah_keys, mushaf_versions) -> None:
    """Batch-fill the in-process cache for cloud editions on a page of ayahs.

    Without this, public/layout builds call Supabase once per ayah (~0.2s each).
    """
    from core import supabase_editor as sb

    if not ayah_keys or not sb.is_configured():
        return
    versions = mushaf_versions if isinstance(mushaf_versions, (list, tuple)) else [mushaf_versions]
    cloud_versions = [v for v in versions if v in PUBLIC_CLOUD_WAQF_EDITIONS]
    if not cloud_versions:
        return

    unique_keys = sorted({(int(s), int(a)) for s, a in ayah_keys})
    for ver in cloud_versions:
        missing = []
        for surah, ayah in unique_keys:
            if _mushaf_waqf_cache.get((surah, ayah, ver)) is None:
                missing.append((surah, ayah))
        if not missing:
            continue
        try:
            rows = sb.fetch_marks_for_ayahs(
                edition=ver, status='published', ayah_keys=missing,
            )
        except sb.SupabaseEditorError as e:
            logger.error('cloud published batch fetch failed: %s', e)
            continue

        by_ayah: dict[tuple[int, int], list] = {key: [] for key in missing}
        for row in rows:
            key = (int(row['surah']), int(row['ayah']))
            if key in by_ayah:
                by_ayah[key].append(row)
        for key, ayah_rows in by_ayah.items():
            _mushaf_waqf_cache[(*key, ver)] = _cloud_rows_to_mushaf_rows(ayah_rows)


def _fetch_single_mushaf_waqf(surah_number, ayah_number, mushaf_version):
    """Internal: fetch for exactly one validated version, with in-process caching."""
    if not _is_valid_mushaf_version(mushaf_version):
        return []

    cache_key = (surah_number, ayah_number, mushaf_version)
    cached = _mushaf_waqf_cache.get(cache_key)
    if cached is not None:
        return [dict(r) for r in cached]

    # Cloud-editor editions: published Postgres only when Supabase is configured.
    if mushaf_version in PUBLIC_CLOUD_WAQF_EDITIONS:
        cloud = _fetch_published_cloud_waqf(surah_number, ayah_number, mushaf_version)
        if cloud is _CLOUD_FETCH_FAILED:
            return []
        if cloud is not None:
            _mushaf_waqf_cache[cache_key] = cloud
            return [dict(r) for r in cloud]

    # The remaining path interpolates a SQLite column identifier. Keep its
    # authorization boundary strictly tied to columns actually present in the
    # local schema, even though cloud validation above is capability-based.
    if mushaf_version not in _get_mushaf_version_whitelist():
        return []

    try:
        conn = sqlite3.connect(MUSHAF_WAQF_DATABASE)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Column name is validated against the SQLite whitelist above, so interpolation
        # is safe here (SQLite doesn't support parameterised identifiers).
        quoted_col = '"' + mushaf_version.replace('"', '""') + '"'
        cols = set(_get_mushaf_table_columns())

        token_expr = 'NULL as token_index'
        if 'token_index' in cols:
            token_expr = 'CAST("token_index" AS INTEGER) as token_index'
        else:
            pos_col = _get_mushaf_position_column()
            if pos_col and pos_col != 'word_index':
                quoted_pos_col = '"' + pos_col.replace('"', '""') + '"'
                token_expr = f'CAST({quoted_pos_col} AS INTEGER) as token_index'

        word_expr = 'NULL as word_index'
        if 'word_index' in cols:
            word_expr = 'CAST("word_index" AS INTEGER) as word_index'
        else:
            pos_col = _get_mushaf_position_column()
            if pos_col == 'word_index':
                word_expr = 'CAST("word_index" AS INTEGER) as word_index'

        query = f'''
            SELECT "الكلمة" as word, {quoted_col} as symbol, {token_expr}, {word_expr}
            FROM waqf
            WHERE "السورة" = ? AND "الآية" = ?
            AND {quoted_col} IS NOT NULL AND {quoted_col} != ''
            ORDER BY rowid ASC
        '''

        cursor.execute(query, (surah_number, ayah_number))
        rows = cursor.fetchall()
        conn.close()

        result = [
            {
                'clean_token': row['word'],
                'symbols': row['symbol'],
                # DB stores 1-based word position; convert to 0-based for the JS
                # word array so map.set(token_index, ...) aligns with words[i].
                'token_index': (row['token_index'] - 1) if row['token_index'] is not None else None,
                # Despite its legacy column name, this is a 1-based content
                # word position inside one ayah, never a layout/global ID.
                'word_index': row['word_index'],
                'word_position': row['word_index'],
                'index_space': 'ayah-content-word-1based',
            }
            for row in rows
        ]
        _mushaf_waqf_cache[cache_key] = result
        return [dict(r) for r in result]
    except Exception as e:
        logger.error(f"Error reading mushaf waqf: {e}")
        return []
