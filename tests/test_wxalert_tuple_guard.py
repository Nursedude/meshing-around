# handle_wxalert indexed [0] into whatever the alert fetch returned. Only the
# success path of getWeatherAlertsNOAA returns a tuple; sentinel strings and
# the wxalert detail path return plain strings, so users received a single
# character: literal "e" on fetch failure, "W" for a Winter Storm Warning.
# Upstream issue SpudGunMan/meshing-around#324.

from conftest import load_function

ERROR_FETCHING_DATA = "error fetching data"
NO_ALERTS = "No alerts found."


class _FakeSettings:
    use_meteo_wxApi = False
    NO_ALERTS = NO_ALERTS
    ERROR_FETCHING_DATA = ERROR_FETCHING_DATA


def _handle_wxalert(summary_result=None, detail_result=None):
    namespace = {
        "my_settings": _FakeSettings(),
        "get_node_location": lambda node_id, device_id: [47.0, -122.0],
        "getWeatherAlertsNOAA": lambda lat, lon: summary_result,
        "getActiveWeatherAlertsDetailNOAA": lambda lat, lon: detail_result,
    }
    return load_function("mesh_bot.py", "handle_wxalert", namespace)


def test_wxa_fetch_failure_returns_full_sentinel_not_first_char():
    handler = _handle_wxalert(summary_result=ERROR_FETCHING_DATA)
    assert handler(1, 1, "wxa") == ERROR_FETCHING_DATA


def test_wxa_success_tuple_unpacks_to_alert_text():
    handler = _handle_wxalert(summary_result=("Flood Watch\nWind Advisory", 2))
    assert handler(1, 1, "wxa") == "Flood Watch\nWind Advisory"


def test_wxa_no_alerts_passes_through():
    handler = _handle_wxalert(summary_result=NO_ALERTS)
    assert handler(1, 1, "wxa") == NO_ALERTS


def test_wxalert_detail_string_not_truncated_to_first_letter():
    detail = "Winter Storm Warning until noon. Heavy snow expected."
    handler = _handle_wxalert(detail_result=detail)
    assert handler(1, 1, "wxalert") == detail


def test_wxalert_detail_fetch_failure_returns_full_sentinel():
    handler = _handle_wxalert(detail_result=ERROR_FETCHING_DATA)
    assert handler(1, 1, "wxalert") == ERROR_FETCHING_DATA
