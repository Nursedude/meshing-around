# NWS documents that requests without a User-Agent may be denied, and a
# requests.get without timeout= stalls the single packet-processing path on a
# hung socket. Behavioral tests drive each fetch function with a recording
# fake and assert the identifying UA + timeout reach the wire; an AST sweep
# pins the no-timeout class shut for the touched modules.

import ast

import pytest
import requests

from conftest import REPO_ROOT, parsed_source

import modules.settings as my_settings
import modules.locationdata as locationdata
import modules.space as space
import modules.wx_meteo as wx_meteo
import modules.dxspot as dxspot


class _FakeResponse:
    ok = False
    status_code = 503
    text = ""

    def json(self):
        raise ValueError("no body")

    def raise_for_status(self):
        raise requests.exceptions.HTTPError("503")


class _Recorder:
    def __init__(self):
        self.calls = []

    def __call__(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return _FakeResponse()


@pytest.fixture
def recorder(monkeypatch):
    rec = _Recorder()
    monkeypatch.setattr(requests, "get", rec)
    return rec


NOAA_FAMILY_CALLS = [
    (locationdata, lambda: locationdata.get_NOAAtide(47.0, -122.0)),
    (locationdata, lambda: locationdata.get_NOAAweather(47.0, -122.0)),
    (locationdata, lambda: locationdata.getWeatherAlertsNOAA(47.0, -122.0)),
    (locationdata, lambda: locationdata.getActiveWeatherAlertsDetailNOAA(47.0, -122.0)),
    (locationdata, lambda: locationdata.getIpawsAlert(47.0, -122.0)),
    (locationdata, lambda: locationdata.checkUSGSEarthQuake(47.0, -122.0)),
    (locationdata, lambda: locationdata.get_volcano_usgs(47.0, -122.0)),
    (locationdata, lambda: locationdata.get_flood_noaa(47.0, -122.0, uid="TESTGAUGE")),
    (locationdata, lambda: locationdata.get_nws_marine("https://api.weather.gov/products/types/CWF/locations/PZZ100")),
    (space, lambda: space.drap_xray_conditions()),
    (space, lambda: space.get_noaa_scales_summary()),
]


@pytest.mark.parametrize(
    "call", [c for _, c in NOAA_FAMILY_CALLS],
    ids=[f"{m.__name__}:{i}" for i, (m, _) in enumerate(NOAA_FAMILY_CALLS)],
)
def test_noaa_family_calls_send_identifying_user_agent_and_timeout(recorder, call):
    call()
    assert recorder.calls, "function made no request"
    for url, kwargs in recorder.calls:
        headers = kwargs.get("headers") or {}
        assert headers.get("User-Agent") == my_settings.API_USER_AGENT, url
        assert kwargs.get("timeout"), url


def test_flood_noaa_keeps_accept_header(recorder):
    locationdata.get_flood_noaa(47.0, -122.0, uid="TESTGAUGE")
    _, kwargs = recorder.calls[0]
    assert kwargs["headers"]["accept"] == "application/json"


def test_open_meteo_fetch_has_timeout(recorder):
    result = wx_meteo.get_wx_meteo(47.0, -122.0)
    assert result == my_settings.ERROR_FETCHING_DATA
    _, kwargs = recorder.calls[0]
    assert kwargs.get("timeout")


def test_open_meteo_flood_fetch_has_timeout(recorder):
    result = wx_meteo.get_flood_openmeteo(47.0, -122.0)
    assert result == my_settings.ERROR_FETCHING_DATA
    _, kwargs = recorder.calls[0]
    assert kwargs.get("timeout")


def test_spothole_fetch_has_timeout(recorder):
    dxspot.get_spothole_spots()
    assert recorder.calls
    _, kwargs = recorder.calls[0]
    assert kwargs.get("timeout")


# ---- class pin: no requests call without timeout in the touched modules ----

SWEPT_MODULES = [
    "modules/locationdata.py",
    "modules/space.py",
    "modules/wx_meteo.py",
    "modules/dxspot.py",
    "modules/globalalert.py",
]


@pytest.mark.parametrize("relative_path", SWEPT_MODULES)
def test_every_requests_call_carries_timeout(relative_path):
    tree, _ = parsed_source(relative_path)
    missing = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (
            isinstance(func, ast.Attribute)
            and isinstance(func.value, ast.Name)
            and func.value.id == "requests"
            and func.attr in ("get", "post")
        ):
            continue
        if not any(kw.arg == "timeout" for kw in node.keywords):
            missing.append(f"{relative_path}:{node.lineno}")
    assert not missing, f"requests call(s) without timeout=: {missing}"
