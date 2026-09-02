# A node with no GPS fix does not reliably send `None` — it sends a FILL
# VALUE that passes an `is not None` check and lands inside the valid
# latitude/longitude domain.
#
# Live case, 2026-09-01: node !47115e4f ("wh6gxz-POE") reported
# (0.2097152, 0.2097152) — latitude_i == longitude_i == 2**21 in Meshtastic's
# 1e-7-degree integers, an uninitialised register. get_node_location returned
# it, so `wx`/`wxa` asked api.weather.gov about a point in the Gulf of Guinea,
# got HTTP 404, and the bot answered "error fetching data" for every request
# from that node. The configured fallback location answered 200 the whole
# time and was never reached, because the node "had" a position.
#
# The coordinates below are REAL captures, not invented vectors — the whole
# defect is that a fill value is indistinguishable from a measurement.
#
# modules/system.py opens the radio interface at import time (and exit()s on
# failure), so it is loaded the same way mesh_bot.py is: one function at a
# time via load_function against stub globals.

import logging

import pytest

from conftest import load_function, parsed_source

SRC = "modules/system.py"


def _module_constant(name):
    """Read a module-level literal constant straight from the source.

    load_function extracts only the function body, so a constant it closes
    over has to come from somewhere. Taking it from the AST rather than
    retyping the number keeps ONE source of truth: if the guard's box size
    changes, these tests follow it instead of silently pinning a stale value.
    """
    import ast
    tree, _ = parsed_source(SRC)
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == name for t in node.targets
        ):
            return ast.literal_eval(node.value)
    raise AssertionError(f"{name} not found in {SRC}")


NULL_ISLAND_DEG = _module_constant("NULL_ISLAND_DEG")


def _plausible():
    ns = {"NULL_ISLAND_DEG": NULL_ISLAND_DEG}
    return load_function(SRC, "position_is_plausible", ns)


class _Iface:
    def __init__(self, nodes):
        self.nodes = nodes


def _get_node_location(position, *, lat=19.6227, lon=-155.0374, logger=None):
    """get_node_location bound to a one-node interface holding `position`."""
    ns = {
        "latitudeValue": lat,
        "longitudeValue": lon,
        "fuzz_config_location": False,
        "fuzzItAll": False,
        "logger": logger or logging.getLogger("test.system"),
        "interface1": _Iface({"a": {"num": 1192426575, "position": position}}),
    }
    ns["NULL_ISLAND_DEG"] = NULL_ISLAND_DEG
    ns["position_is_plausible"] = _plausible()
    fn = load_function(SRC, "get_node_location", ns)
    return fn(1192426575, 1)


class TestPositionIsPlausible:

    def test_the_live_2_21_fill_value_is_refused(self):
        """THE case. 2**21 * 1e-7 on both axes, straight off the radio."""
        assert _plausible()(0.2097152, 0.2097152) is False

    def test_null_island_is_refused(self):
        p = _plausible()
        assert p(0, 0) is False
        assert p(0.0, 0.0) is False
        assert p(0.1, -0.2) is False

    def test_latitude_equal_to_longitude_is_a_fill_pattern(self):
        """Two independent GPS axes do not agree to full float precision."""
        assert _plausible()(45.123456, 45.123456) is False

    def test_out_of_range_is_refused(self):
        p = _plausible()
        assert p(91.0, 10.0) is False
        assert p(-90.5, 10.0) is False
        assert p(10.0, 180.5) is False
        assert p(10.0, -181.0) is False

    def test_non_numeric_and_nan_are_refused(self):
        p = _plausible()
        assert p(None, None) is False
        assert p("nineteen", -155.0) is False
        assert p(float("nan"), -155.0) is False
        assert p(19.6, float("nan")) is False

    def test_real_fixes_are_accepted(self):
        """The guard must not eat working positions — live fleet coordinates
        that api.weather.gov answers 200 for."""
        p = _plausible()
        assert p(19.6227, -155.0374) is True          # bot config location
        assert p(19.4248704, -155.2154624) is True    # wh6gxz-fox
        assert p(19.5035136, -155.3989632) is True    # VOLCANO-QTH-HAP
        assert p(-33.86, 151.21) is True              # southern hemisphere
        assert p(64.1, -21.9) is True                 # far north

    def test_just_outside_the_null_island_box_is_accepted(self):
        """Uses the module's own constant, so the boundary cannot drift."""
        p = _plausible()
        assert p(NULL_ISLAND_DEG + 0.01, 20.0) is True
        assert p(20.0, NULL_ISLAND_DEG + 0.01) is True


class TestGetNodeLocationFallsBackOnAFillValue:
    """The end the user feels: a bad position must not beat the config."""

    def test_fill_value_falls_back_to_config_location(self, caplog):
        log = logging.getLogger("test.system.fill")
        with caplog.at_level(logging.WARNING, logger=log.name):
            got = _get_node_location(
                {"latitude": 0.2097152, "longitude": 0.2097152}, logger=log)
        assert got == [19.6227, -155.0374], "the bogus fix must not win"
        assert any("Implausible position" in r.message for r in caplog.records), \
            "a refusal with no witness is invisible to the next operator"

    def test_a_real_fix_is_still_returned(self):
        got = _get_node_location(
            {"latitude": 19.4248704, "longitude": -155.2154624})
        assert got == [19.4248704, -155.2154624]

    def test_absent_position_still_falls_back(self):
        assert _get_node_location(None) == [19.6227, -155.0374]
        assert _get_node_location({"latitude": None, "longitude": None}) \
            == [19.6227, -155.0374]

    def test_null_island_falls_back(self):
        assert _get_node_location({"latitude": 0.0, "longitude": 0.0}) \
            == [19.6227, -155.0374]
