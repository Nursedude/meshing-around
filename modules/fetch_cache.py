# small TTL cache for external API fetch functions — channel-spam shield
#
# Repeated identical commands on a busy channel (wx spam, tide spam) each hit
# the upstream API directly; NOAA/NWS document rate expectations. A short TTL
# reuses a fresh successful answer without changing what users see.
#
# Honesty rules:
#   - failures (ERROR_FETCHING_DATA / NO_DATA_NOGPS / None / empty) are NEVER
#     cached, so a user retry can succeed the moment the API recovers
#   - NO_ALERTS is NEVER cached: an all-clear on a safety command must always
#     reflect live upstream state, never a stale answer from before a warning
#   - only successful results are stored, so the cache can never convert an
#     error into a valid-looking answer
#   - time.monotonic, not wall clock (NTP steps must not stretch a TTL)
#
# Known limitation: no single-flight — two threads missing the same key at the
# same instant both fetch. Rare here (one packet thread + slow schedulers) and
# harmless: last writer wins with a fresh result.

import functools
import threading
import time

from modules.settings import ERROR_FETCHING_DATA, NO_DATA_NOGPS, NO_ALERTS

DEFAULT_TTL_SECONDS = 90
MAX_ENTRIES = 64

_all_caches = []


def _cacheable(result):
    if result is None:
        return False
    if isinstance(result, str) and (
        result.strip() == "" or result in (ERROR_FETCHING_DATA, NO_DATA_NOGPS, NO_ALERTS)
    ):
        return False
    return True


def _make_key(args, kwargs):
    # str-normalize so float and str forms of the same query share an entry
    # (commands pass str(lat), schedulers pass floats — same upstream request)
    return (
        tuple(str(a) for a in args),
        tuple((k, str(v)) for k, v in sorted(kwargs.items())),
    )


def ttl_cache(ttl_seconds=DEFAULT_TTL_SECONDS):
    """Cache a fetch function's successful results for a short window."""

    def decorator(fn):
        entries = {}
        lock = threading.Lock()
        _all_caches.append(entries)

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            key = _make_key(args, kwargs)
            now = time.monotonic()
            with lock:
                hit = entries.get(key)
                if hit is not None and now - hit[0] < ttl_seconds:
                    return hit[1]
            result = fn(*args, **kwargs)
            if _cacheable(result):
                with lock:
                    # drop expired entries first; evict oldest only if still full
                    for stale in [k for k, (ts, _) in entries.items() if now - ts >= ttl_seconds]:
                        del entries[stale]
                    if len(entries) >= MAX_ENTRIES and key not in entries:
                        oldest = min(entries, key=lambda k: entries[k][0])
                        del entries[oldest]
                    entries[key] = (now, result)
            return result

        wrapper.cache_clear = entries.clear
        return wrapper

    return decorator


def clear_all_caches():
    for entries in _all_caches:
        entries.clear()
