# Regression pins for the self-review pass over the 2026-07-06 audit-fix
# branch (8 finder angles, verified findings). Each test names the defect it
# pins shut.

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
    def __init__(self, ok=True, status_code=200, text="", json_data=None):
        self.ok = ok
        self.status_code = status_code
        self.text = text
        self._json_data = json_data

    def json(self):
        if self._json_data is None:
            raise ValueError("no json body")
        return self._json_data


def _script_get(monkeypatch, responses):
    queue = list(responses)

    def fake_get(url, **kwargs):
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(requests, "get", fake_get)


# ---- tide: 200 with an EMPTY predictions list crashed at [0] ----

def test_tide_empty_predictions_list_is_error_not_crash(monkeypatch):
    station = ScriptedResponse(json_data={"stationList": [{"stationId": "9447130"}]})
    datagetter = ScriptedResponse(json_data={"predictions": []})
    _script_get(monkeypatch, [station, datagetter])
    assert locationdata.get_NOAAtide(47.0, -122.0) == ERROR


# ---- volcano: ignore-list continue only skipped the WORD loop ----

def test_volcano_ignore_list_actually_skips_the_alert(monkeypatch):
    alert = {
        "volcano_name_appended": "Kilauea Volcano",
        "latitude": my_settings.latitudeValue,
        "longitude": my_settings.longitudeValue,
        "alert_level": "WATCH",
        "color_code": "ORANGE",
        "cap_severity": "Severe",
        "synopsis": "eruption ongoing",
    }
    _script_get(monkeypatch, [ScriptedResponse(json_data=[alert])])
    monkeypatch.setattr(locationdata.my_settings, "ignoreUSGSEnable", True, raising=False)
    monkeypatch.setattr(locationdata.my_settings, "ignoreUSGSwords", ["kilauea"], raising=False)
    assert locationdata.get_volcano_usgs(0, 0) == NO_ALERTS


def test_volcano_non_ignored_alert_still_reported(monkeypatch):
    alert = {
        "volcano_name_appended": "Mauna Loa",
        "latitude": my_settings.latitudeValue,
        "longitude": my_settings.longitudeValue,
        "alert_level": "WATCH",
        "color_code": "ORANGE",
        "cap_severity": "Severe",
        "synopsis": "eruption ongoing",
    }
    _script_get(monkeypatch, [ScriptedResponse(json_data=[alert])])
    monkeypatch.setattr(locationdata.my_settings, "ignoreUSGSEnable", True, raising=False)
    monkeypatch.setattr(locationdata.my_settings, "ignoreUSGSwords", ["kilauea"], raising=False)
    assert "Mauna Loa" in locationdata.get_volcano_usgs(0, 0)


# ---- drap: 200 body without the X-RAY line raised UnboundLocalError ----

def test_drap_missing_xray_line_is_error_not_crash(monkeypatch):
    _script_get(monkeypatch, [ScriptedResponse(text="# some header\n1.0 2.0 3.0\n")])
    assert space.drap_xray_conditions() == ERROR


def test_drap_network_failure_is_error_not_crash(monkeypatch):
    _script_get(monkeypatch, [requests.exceptions.ConnectionError("down")])
    assert space.drap_xray_conditions() == ERROR


# ---- quake: an event without a magnitude node raised IndexError ----

def test_quake_event_without_magnitude_is_skipped_not_crash(monkeypatch):
    xml_body = (
        "<quakeml>"
        "<event><description><text>no magnitude here</text></description></event>"
        "<event><magnitude><value>3.1</value></magnitude>"
        "<description><text>5km S of Elsewhere</text></description></event>"
        "</quakeml>"
    )
    _script_get(monkeypatch, [ScriptedResponse(text=xml_body)])
    result = locationdata.checkUSGSEarthQuake(47.0, -122.0)
    assert "3.1" in result and "Elsewhere" in result


# ---- hfcond: unguarded fetch/parse crashed to the generic dispatch guard ----

def test_hfcond_network_failure_is_error_not_crash(monkeypatch):
    _script_get(monkeypatch, [requests.exceptions.ConnectionError("down")])
    assert space.hf_band_conditions() == ERROR


def test_hfcond_invalid_xml_is_error_not_crash(monkeypatch):
    _script_get(monkeypatch, [ScriptedResponse(text="<broken")])
    assert space.hf_band_conditions() == ERROR


# ---- satpass: a network failure was reported as a user-input mistake ----

def test_satpass_network_failure_is_error_not_usage_hint(monkeypatch):
    monkeypatch.setattr(space, "n2yoAPIKey", "TESTKEY")
    _script_get(monkeypatch, [requests.exceptions.ConnectionError("down")])
    result = space.getNextSatellitePass("25544", 47.0, -122.0)
    assert result == ERROR
    assert "NORAD" not in result


def test_satpass_bad_input_still_gets_usage_hint(monkeypatch):
    monkeypatch.setattr(space, "n2yoAPIKey", "TESTKEY")
    _script_get(monkeypatch, [ScriptedResponse(json_data={})])
    result = space.getNextSatellitePass("not-a-number", 47.0, -122.0)
    assert "NORAD" in result


# ---- UK fetchers: failure is never the all-clear ----

def test_wxukgov_fetch_failure_is_not_no_alerts(monkeypatch):
    _script_get(monkeypatch, [requests.exceptions.ConnectionError("down")])
    assert globalalert.get_wxUKgov() == ERROR


# ---- IPAWS: invalid main-feed XML crashed to silence ----

def test_ipaws_invalid_main_feed_xml_is_error_not_crash(monkeypatch):
    _script_get(monkeypatch, [ScriptedResponse(text="<broken")])
    assert locationdata.getIpawsAlert(47.0, -122.0) == ERROR
