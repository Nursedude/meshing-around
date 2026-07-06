# Honest failure modes: a failed fetch must never read as the all-clear
# ("No alerts found.") on a safety command, and every error path must log
# the cause (exception type + message, or HTTP status) so the next outage
# is diagnosable from the logs. Findings 2/3/7 of the 2026-07-06 audit —
# the June tide outage left no cause in the logs by design.

import logging

import pytest
import requests

from conftest import load_function

import modules.settings as my_settings
import modules.locationdata as locationdata
import modules.space as space
import modules.globalalert as globalalert

ERROR = my_settings.ERROR_FETCHING_DATA
NO_ALERTS = my_settings.NO_ALERTS


class ScriptedResponse:
    def __init__(self, ok=True, status_code=200, text="", json_data=None, json_error=False):
        self.ok = ok
        self.status_code = status_code
        self.text = text
        self._json_data = json_data
        self._json_error = json_error

    def json(self):
        if self._json_error:
            raise ValueError("invalid json body")
        return self._json_data


def _script_get(monkeypatch, responses):
    """Patch requests.get to pop scripted responses (an Exception raises)."""
    queue = list(responses)

    def fake_get(url, **kwargs):
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(requests, "get", fake_get)


@pytest.fixture
def propagate_logs(monkeypatch):
    # modules.log sets propagate=False; caplog needs records at the root
    monkeypatch.setattr(logging.getLogger("MeshBot System Logger"), "propagate", True)


# ---- earthquake: failure is never the all-clear ----

def test_quake_http_failure_is_not_no_alerts(monkeypatch):
    _script_get(monkeypatch, [ScriptedResponse(ok=False, status_code=503)])
    assert locationdata.checkUSGSEarthQuake(47.0, -122.0) == ERROR


def test_quake_network_failure_is_not_no_alerts_and_logs_cause(monkeypatch, propagate_logs, caplog):
    _script_get(monkeypatch, [requests.exceptions.ConnectionError("dns fail")])
    with caplog.at_level(logging.WARNING):
        assert locationdata.checkUSGSEarthQuake(47.0, -122.0) == ERROR
    assert any("ConnectionError" in r.getMessage() and "dns fail" in r.getMessage() for r in caplog.records)


def test_quake_empty_body_is_not_no_alerts(monkeypatch):
    _script_get(monkeypatch, [ScriptedResponse(text="   ")])
    assert locationdata.checkUSGSEarthQuake(47.0, -122.0) == ERROR


def test_quake_invalid_xml_is_not_no_alerts(monkeypatch):
    _script_get(monkeypatch, [ScriptedResponse(text="<broken")])
    assert locationdata.checkUSGSEarthQuake(47.0, -122.0) == ERROR


def test_quake_valid_empty_feed_is_honest_all_clear(monkeypatch):
    _script_get(monkeypatch, [ScriptedResponse(text="<quakeml></quakeml>")])
    assert locationdata.checkUSGSEarthQuake(47.0, -122.0) == NO_ALERTS


def test_quake_real_event_still_reported(monkeypatch):
    xml_body = (
        "<quakeml><event>"
        "<magnitude><value>4.2</value></magnitude>"
        "<description><text>10km N of Somewhere</text></description>"
        "</event></quakeml>"
    )
    _script_get(monkeypatch, [ScriptedResponse(text=xml_body)])
    result = locationdata.checkUSGSEarthQuake(47.0, -122.0)
    assert "4.2" in result and "Somewhere" in result


# ---- NOAA space weather scales ----

def test_noaa_scales_http_failure_is_not_no_alerts(monkeypatch):
    _script_get(monkeypatch, [ScriptedResponse(ok=False, status_code=502)])
    assert space.get_noaa_scales_summary() == ERROR


def test_noaa_scales_exception_is_error(monkeypatch):
    _script_get(monkeypatch, [requests.exceptions.ReadTimeout("slow")])
    assert space.get_noaa_scales_summary() == ERROR


# ---- NINA / UK alerts ----

def test_nina_fetch_failure_is_not_no_alerts(monkeypatch):
    monkeypatch.setattr(globalalert, "myRegionalKeysDE", ["071"])
    _script_get(monkeypatch, [requests.exceptions.ConnectionError("NXDOMAIN")])
    assert globalalert.get_nina_alerts() == ERROR


def test_govuk_fetch_failure_returns_sentinel_not_none(monkeypatch):
    _script_get(monkeypatch, [requests.exceptions.ConnectionError("down")])
    result = globalalert.get_govUK_alerts(51.5, -0.1)
    assert result == ERROR  # None would be silently dropped by send_message


# ---- volcano: shape errors are failures, empty list is the all-clear ----

def test_volcano_invalid_json_is_error(monkeypatch):
    _script_get(monkeypatch, [ScriptedResponse(json_error=True)])
    assert locationdata.get_volcano_usgs(47.0, -122.0) == ERROR


def test_volcano_unexpected_shape_is_error(monkeypatch):
    _script_get(monkeypatch, [ScriptedResponse(json_data={"error": "teapot"})])
    assert locationdata.get_volcano_usgs(47.0, -122.0) == ERROR


def test_volcano_empty_list_is_honest_all_clear(monkeypatch):
    _script_get(monkeypatch, [ScriptedResponse(json_data=[])])
    assert locationdata.get_volcano_usgs(47.0, -122.0) == NO_ALERTS


# ---- tide: the June 2026 outage shape, now diagnosable ----

def test_tide_200_with_error_body_is_error_not_crash(monkeypatch, propagate_logs, caplog):
    station = ScriptedResponse(json_data={"stationList": [{"stationId": "9447130"}]})
    datagetter = ScriptedResponse(json_data={"error": {"message": "No data was found"}})
    _script_get(monkeypatch, [station, datagetter])
    with caplog.at_level(logging.ERROR):
        assert locationdata.get_NOAAtide(47.0, -122.0) == ERROR
    assert any("predictions" in r.getMessage() for r in caplog.records)


def test_tide_network_failure_logs_cause(monkeypatch, propagate_logs, caplog):
    _script_get(monkeypatch, [requests.exceptions.ReadTimeout("read timed out")])
    with caplog.at_level(logging.ERROR):
        assert locationdata.get_NOAAtide(47.0, -122.0) == ERROR
    assert any("ReadTimeout" in r.getMessage() for r in caplog.records)


def test_tide_http_failure_logs_status(monkeypatch, propagate_logs, caplog):
    _script_get(monkeypatch, [ScriptedResponse(ok=False, status_code=504)])
    with caplog.at_level(logging.ERROR):
        assert locationdata.get_NOAAtide(47.0, -122.0) == ERROR
    assert any("504" in r.getMessage() for r in caplog.records)


# ---- NOAA weather: malformed JSON shapes are errors, not silent crashes ----

def test_weather_points_missing_forecast_key_is_error(monkeypatch):
    _script_get(monkeypatch, [ScriptedResponse(json_data={"title": "Not Found"})])
    assert locationdata.get_NOAAweather(47.0, -122.0) == ERROR


def test_weather_forecast_missing_periods_is_error(monkeypatch):
    points = ScriptedResponse(json_data={"properties": {"forecast": "https://api.weather.gov/x/forecast"}})
    forecast = ScriptedResponse(json_data={"properties": {}})
    _script_get(monkeypatch, [points, forecast])
    assert locationdata.get_NOAAweather(47.0, -122.0) == ERROR


# ---- mwx: missing config is named, not the all-clear ----

def test_mwx_unset_coastal_zone_names_the_config_gap():
    class _Settings:
        myCoastalZone = None
        NO_ALERTS = NO_ALERTS

    namespace = {
        "my_settings": _Settings(),
        "logger": logging.getLogger("test-mwx"),
    }
    handler = load_function("mesh_bot.py", "handle_mwx", namespace)
    reply = handler(1, 1, "mwx")
    assert reply != NO_ALERTS
    assert "config" in reply.lower()
