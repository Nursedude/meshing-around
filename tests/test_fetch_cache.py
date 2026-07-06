# The TTL fetch cache is a channel-spam shield: repeated identical commands
# reuse a fresh successful answer instead of hammering the API. Honesty
# rules under test: failures are NEVER cached (a retry can succeed the
# moment the API recovers) and the cache never converts an error into a
# valid-looking answer.

import pytest
import requests

import modules.fetch_cache as fetch_cache
from modules.fetch_cache import ttl_cache
import modules.settings as my_settings
import modules.locationdata as locationdata
import modules.space as space


# ---- unit behavior ----

def test_success_is_cached_within_ttl():
    calls = []

    @ttl_cache(ttl_seconds=60)
    def fetch(x):
        calls.append(x)
        return f"data-{x}"

    assert fetch(1) == "data-1"
    assert fetch(1) == "data-1"
    assert calls == [1]


def test_distinct_args_are_distinct_entries():
    calls = []

    @ttl_cache(ttl_seconds=60)
    def fetch(x):
        calls.append(x)
        return f"data-{x}"

    fetch(1)
    fetch(2)
    assert calls == [1, 2]


def test_expired_entry_refetches(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(fetch_cache.time, "monotonic", lambda: clock[0])
    calls = []

    @ttl_cache(ttl_seconds=30)
    def fetch():
        calls.append(1)
        return "data"

    fetch()
    clock[0] += 31
    fetch()
    assert len(calls) == 2


def test_error_sentinels_are_never_cached():
    results = iter([my_settings.ERROR_FETCHING_DATA, my_settings.NO_DATA_NOGPS, None, "", "recovered"])
    calls = []

    @ttl_cache(ttl_seconds=60)
    def fetch():
        calls.append(1)
        return next(results)

    for _ in range(4):
        fetch()
    assert fetch() == "recovered"
    assert len(calls) == 5
    assert fetch() == "recovered"  # now cached
    assert len(calls) == 5


def test_tuple_results_are_cacheable():
    calls = []

    @ttl_cache(ttl_seconds=60)
    def fetch():
        calls.append(1)
        return ("alerts", 2)

    assert fetch() == ("alerts", 2)
    assert fetch() == ("alerts", 2)
    assert calls == [1]


def test_entry_count_is_bounded():
    @ttl_cache(ttl_seconds=3600)
    def fetch(x):
        return f"data-{x}"

    for i in range(fetch_cache.MAX_ENTRIES + 10):
        fetch(i)
    # implementation detail via closure: the registry holds the entries dict
    assert len(fetch_cache._all_caches[-1]) <= fetch_cache.MAX_ENTRIES


def test_unhashable_args_bypass_cache():
    calls = []

    @ttl_cache(ttl_seconds=60)
    def fetch(x):
        calls.append(1)
        return "data"

    fetch(["a", "list"])
    fetch(["a", "list"])
    assert len(calls) == 2


def test_clear_all_caches_resets():
    calls = []

    @ttl_cache(ttl_seconds=3600)
    def fetch():
        calls.append(1)
        return "data"

    fetch()
    fetch_cache.clear_all_caches()
    fetch()
    assert len(calls) == 2


# ---- wiring: the NOAA-family fetchers actually shield the APIs ----

class _CountingOk:
    def __init__(self, text):
        self.count = 0
        self._text = text

    def __call__(self, url, **kwargs):
        self.count += 1
        resp = requests.Response()
        resp.status_code = 200
        resp._content = self._text.encode()
        return resp


def test_quake_repeat_command_hits_network_once(monkeypatch):
    counting = _CountingOk("<quakeml></quakeml>")
    monkeypatch.setattr(requests, "get", counting)
    first = locationdata.checkUSGSEarthQuake(47.0, -122.0)
    second = locationdata.checkUSGSEarthQuake(47.0, -122.0)
    assert first == second == my_settings.NO_ALERTS
    assert counting.count == 1


def test_quake_failure_is_retried_not_cached(monkeypatch):
    attempts = []

    def flaky_get(url, **kwargs):
        attempts.append(1)
        raise requests.exceptions.ConnectionError("down")

    monkeypatch.setattr(requests, "get", flaky_get)
    locationdata.checkUSGSEarthQuake(47.0, -122.0)
    locationdata.checkUSGSEarthQuake(47.0, -122.0)
    assert len(attempts) == 2


def test_noaa_family_fetchers_are_cache_wrapped():
    wrapped = [
        locationdata.get_NOAAtide,
        locationdata.get_NOAAweather,
        locationdata.getWeatherAlertsNOAA,
        locationdata.getActiveWeatherAlertsDetailNOAA,
        locationdata.getIpawsAlert,
        locationdata.get_flood_noaa,
        locationdata.get_volcano_usgs,
        locationdata.get_nws_marine,
        locationdata.checkUSGSEarthQuake,
        space.hf_band_conditions,
        space.solar_conditions,
        space.drap_xray_conditions,
        space.get_noaa_scales_summary,
    ]
    for fn in wrapped:
        assert hasattr(fn, "cache_clear"), f"{fn.__name__} is not ttl_cache-wrapped"
