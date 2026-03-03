"""
bm2_cache — B-tree backed cache for deserialized .bm2 data.

Uses LMDB (Lightning Memory-mapped Database) for storage and orjson for
serialization.  This gives us:

  - B-tree indexed lookups by key (filename or path)
  - Memory-mapped reads — after the first access, the OS page cache keeps
    the data hot.  Subsequent reads are essentially memcpy, no file I/O.
  - orjson serialization — 10-50x faster than stdlib json or pickle for
    large nested dicts (~5-10MB BMDProject structures).
  - Single file on disk (well, two: data.mdb + lock.mdb), no external
    server process.
  - Concurrent readers, single writer — perfect for our use case where
    the web server reads frequently and writes only on first process.

The cache lives at sessions/_bm2_cache/ (next to per-chemical session
dirs).  It's shared across all sessions because the same .bm2 file might
be referenced from multiple chemicals.

Two data types are stored:

  - BMDProject JSON:  key = "json:{bm2_path}"
    The full deserialized BMDProject dict from Java export.  This is the
    expensive one (~5-10MB, requires JVM on first export).

  - Category lookup:  key = "cat:{bm2_path}"
    Dict mapping (experiment_prefix, endpoint_name) → BMD info.  The
    tuple keys are converted to pipe-separated strings for orjson
    compatibility ("prefix|endpoint" → value).

Typical usage:

    import bm2_cache

    # Try cache first
    bm2_json = bm2_cache.get_json("/path/to/file.bm2")
    if bm2_json is None:
        bm2_json = ... # expensive Java export
        bm2_cache.put_json("/path/to/file.bm2", bm2_json)

    # Category lookup (with tuple-key conversion)
    cat = bm2_cache.get_categories("/path/to/file.bm2")
    if cat is None:
        cat = ... # expensive Java CLI
        bm2_cache.put_categories("/path/to/file.bm2", cat)
"""

# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------

import logging
from pathlib import Path

import lmdb
import orjson

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

logger = logging.getLogger(__name__)

# LMDB environment lives alongside the session directories.
# The map_size is a virtual address space reservation, not actual disk usage —
# LMDB uses sparse files on Linux, so a 1 GB reservation costs nothing until
# data is actually written.
_CACHE_DIR = Path(__file__).parent / "sessions" / "_bm2_cache"
_MAP_SIZE = 1 * 1024 ** 3   # 1 GB virtual reservation

# Key prefixes for the two data types stored in the cache.
# Using prefixes lets us store both in a single LMDB database without
# collisions (e.g., "json:/path/to/file.bm2" vs "cat:/path/to/file.bm2").
_PREFIX_JSON = "json:"
_PREFIX_CAT = "cat:"

# Separator for converting tuple keys in category lookups to flat strings.
# Pipe is safe — experiment prefixes and endpoint names don't contain it.
_CAT_KEY_SEP = "|"

# ---------------------------------------------------------------------------
# LMDB environment (lazy singleton)
# ---------------------------------------------------------------------------
# Opened on first access and kept alive for the process lifetime.
# LMDB handles concurrency internally — multiple threads can read
# simultaneously, writes are serialized via the B-tree's copy-on-write.

_env: lmdb.Environment | None = None


def _get_env() -> lmdb.Environment:
    """
    Return the global LMDB environment, creating it on first call.

    The environment is opened in read-write mode so both get and put
    operations work.  On Linux, LMDB uses flock-based locking, so
    multiple processes can share the same database safely (though our
    single-process uvicorn server doesn't need this).
    """
    global _env
    if _env is None:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _env = lmdb.open(
            str(_CACHE_DIR),
            map_size=_MAP_SIZE,
            # Max readers — default is 126, fine for our use case
            max_readers=64,
            # No sub-databases — we use key prefixes instead
            max_dbs=0,
        )
        logger.info("LMDB cache opened at %s", _CACHE_DIR)
    return _env


# ---------------------------------------------------------------------------
# Public API — BMDProject JSON
# ---------------------------------------------------------------------------


def get_json(bm2_path: str) -> dict | None:
    """
    Look up a cached BMDProject dict by .bm2 file path.

    Returns the deserialized dict if found, None if not cached.
    The lookup is a B-tree traversal + memcpy (microseconds for warm cache).
    Deserialization via orjson adds ~10ms for a typical 5 MB structure.

    Args:
        bm2_path: Absolute path to the .bm2 file (used as cache key).

    Returns:
        The BMDProject dict, or None if not in cache.
    """
    key = (_PREFIX_JSON + bm2_path).encode("utf-8")
    try:
        env = _get_env()
        with env.begin(write=False) as txn:
            data = txn.get(key)
            if data is None:
                return None
            return orjson.loads(data)
    except Exception as e:
        logger.warning("LMDB read failed for %s: %s", bm2_path, e)
        return None


def put_json(bm2_path: str, bm2_json: dict) -> None:
    """
    Store a BMDProject dict in the cache, keyed by .bm2 file path.

    Serialization via orjson produces compact bytes (~30% smaller than
    stdlib json).  The B-tree insert is O(log n) and writes are
    copy-on-write (no risk of corruption on crash).

    Args:
        bm2_path: Absolute path to the .bm2 file.
        bm2_json: The full deserialized BMDProject dict.
    """
    key = (_PREFIX_JSON + bm2_path).encode("utf-8")
    try:
        env = _get_env()
        value = orjson.dumps(bm2_json)
        with env.begin(write=True) as txn:
            txn.put(key, value)
    except Exception as e:
        # Cache write failure is non-fatal — we just lose the fast path
        # for next time and fall back to the full Java export pipeline.
        logger.warning("LMDB write failed for %s: %s", bm2_path, e)


# ---------------------------------------------------------------------------
# Public API — category analysis lookup
# ---------------------------------------------------------------------------
# The category lookup maps (experiment_prefix, endpoint_name) → BMD info.
# orjson only supports string dict keys, so we convert the tuple keys to
# pipe-separated strings for storage and back on retrieval.


def get_categories(bm2_path: str) -> dict[tuple[str, str], dict] | None:
    """
    Look up a cached category analysis lookup dict by .bm2 file path.

    Returns the dict with tuple keys restored, or None if not cached.

    Args:
        bm2_path: Absolute path to the .bm2 file.

    Returns:
        Dict mapping (prefix, endpoint) → BMD info dict, or None.
    """
    key = (_PREFIX_CAT + bm2_path).encode("utf-8")
    try:
        env = _get_env()
        with env.begin(write=False) as txn:
            data = txn.get(key)
            if data is None:
                return None
            flat = orjson.loads(data)
            # Restore tuple keys from pipe-separated strings
            return {
                tuple(k.split(_CAT_KEY_SEP, 1)): v
                for k, v in flat.items()
            }
    except Exception as e:
        logger.warning("LMDB category read failed for %s: %s", bm2_path, e)
        return None


def put_categories(
    bm2_path: str,
    category_lookup: dict[tuple[str, str], dict],
) -> None:
    """
    Store a category analysis lookup dict in the cache.

    Tuple keys are flattened to pipe-separated strings for orjson
    compatibility.

    Args:
        bm2_path: Absolute path to the .bm2 file.
        category_lookup: Dict mapping (prefix, endpoint) → BMD info.
    """
    key = (_PREFIX_CAT + bm2_path).encode("utf-8")
    try:
        # Flatten tuple keys to strings: ("prefix", "endpoint") → "prefix|endpoint"
        flat = {
            f"{k[0]}{_CAT_KEY_SEP}{k[1]}": v
            for k, v in category_lookup.items()
        }
        env = _get_env()
        value = orjson.dumps(flat)
        with env.begin(write=True) as txn:
            txn.put(key, value)
    except Exception as e:
        logger.warning("LMDB category write failed for %s: %s", bm2_path, e)


# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------


def stats() -> dict:
    """
    Return LMDB environment statistics for debugging.

    Includes B-tree depth, number of entries, page usage, etc.
    """
    try:
        env = _get_env()
        with env.begin(write=False) as txn:
            st = txn.stat()
            info = env.info()
            return {
                "entries": st["entries"],
                "btree_depth": st["depth"],
                "pages_used": st["leaf_pages"] + st["branch_pages"]
                              + st["overflow_pages"],
                "page_size": st["psize"],
                "map_size_mb": info["map_size"] / (1024 ** 2),
                "last_txn_id": info["last_txnid"],
            }
    except Exception as e:
        return {"error": str(e)}
