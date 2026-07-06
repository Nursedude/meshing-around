# small TTL cache for external API fetch functions — channel-spam shield
#
# Repeated identical commands on a busy channel (wx spam, tide spam) each hit
# the upstream API directly; NOAA/NWS document rate expectations. A short TTL
# reuses a fresh successful answer without changing what users see.
#
# Honesty rules:
#   - failures (ERROR_FETCHING_DATA / NO_DATA_NOGPS / None / empty) are NEVER
#     cached, so a user retry can succeed the moment the API recovers
#   - only successful results are stored, so the cache can never convert an
#     error into a valid-looking answer
#   - time.monotonic, not wall clock (NTP steps must not stretch a TTL)

import functools
import threading
import time

from modules.settings import ERROR_FETCHING_DATA, NO_DATA_NOGPS

DEFAULT_TTL_SECONDS = 90
MAX_ENTRIES = 64

_all_caches = []


def _cacheable(result):
    if result is None:
        return False
    if isinstance(result, str) and (result.strip() == "" or result in (ERROR_FETCHING_DATA, NO_DATA_NOGPS)):
        return False
    return True


def ttl_cache(ttl_seconds=DEFAULT_TTL_SECONDS):
    """Cache a fetch function's successful results for a short window."""

    def decorator(fn):
        entries = {}
        lock = threading.Lock()
        _all_caches.append(entries)

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            try:
                key = (args, tuple(sorted(kwargs.items())))
                hash(key)
            except TypeError:
                return fn(*args, **kwargs)  # unhashable args: skip caching
            now = time.monotonic()
            with lock:
                hit = entries.get(key)
                if hit is not None and now - hit[0] < ttl_seconds:
                    return hit[1]
            result = fn(*args, **kwargs)
            if _cacheable(result):
                with lock:
                    if len(entries) >= MAX_ENTRIES and key not in entries:
                        oldest = min(entries, key=lambda k: entries[k][0])
                        del entries[oldest]
                    entries[key] = (time.monotonic(), result)
            return result

        wrapper.cache_clear = entries.clear
        return wrapper

    return decorator


def clear_all_caches():
    for entries in _all_caches:
        entries.clear()
