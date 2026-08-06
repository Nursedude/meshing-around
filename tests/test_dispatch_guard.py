# The command dispatch in auto_response must never let a crashed handler
# turn into silence: the packet-level except in onReceive swallows the
# exception and the user gets no reply at all. The guard converts a handler
# crash into an honest "command failed" reply and a logged traceback.

import ast
import logging
import time

from conftest import load_function, parsed_source


class _FakeSettings:
    cmdBang = False
    bbs_admin_list = []


def _make_namespace(handlers):
    """Stub globals for exec'ing auto_response outside mesh_bot.py."""
    namespace = {
        # v1.9.9.9 command-lockdown global read by auto_response; the exec
        # namespace must mirror every module global the target reads.
        "blackhole_mode": False,
        "my_settings": _FakeSettings(),
        "logger": logging.getLogger("test-dispatch"),
        "time": time,
        "cmdHistory": [],
        "restrictedCommands": [],
        "restrictedResponse": "restricted",
        "isPlayingGame": lambda node_id: (False, "None"),
        "get_name_from_number": lambda *args, **kwargs: "TestNode",
        # non-lambda dict values resolve at dict build time
        "bbs_help": lambda: "bbs help",
        "bbs_list_messages": lambda: "bbs list",
        "hf_band_conditions": lambda: "hf",
    }
    namespace.update(handlers)
    return namespace


def _call_auto_response(namespace, message):
    auto_response = load_function("mesh_bot.py", "auto_response", namespace)
    return auto_response(
        message, snr=0, rssi=0, hop="Direct", pkiStatus=(False, "-"),
        message_from_id=12345, channel_number=0, deviceID=1, isDM=True,
    )


def test_crashing_handler_returns_honest_failure_not_silence():
    def boom(*args, **kwargs):
        raise RuntimeError("api fell over")

    namespace = _make_namespace({"handle_ping": boom})
    reply = _call_auto_response(namespace, "ping")
    assert isinstance(reply, str) and reply
    assert "ping" in reply and "failed" in reply.lower()


def test_crashing_handler_logs_cause(caplog):
    def boom(*args, **kwargs):
        raise ValueError("bad json from upstream")

    namespace = _make_namespace({"handle_ping": boom})
    namespace["logger"] = logging.getLogger("test-dispatch-cause")
    with caplog.at_level(logging.ERROR, logger="test-dispatch-cause"):
        _call_auto_response(namespace, "ping")
    assert any(
        "ValueError" in record.getMessage() and "bad json from upstream" in record.getMessage()
        for record in caplog.records
    )


def test_healthy_handler_reply_passes_through_unchanged():
    namespace = _make_namespace(
        {"handle_ping": lambda *args, **kwargs: "🏓PONG"}
    )
    assert _call_auto_response(namespace, "ping") == "🏓PONG"


def test_dispatch_call_is_inside_try_except_guard():
    """Structural pin: the command_handler[...]() dispatch call must sit
    inside a try whose handler catches Exception (regression guard)."""
    tree, _ = parsed_source("mesh_bot.py")
    auto_response = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "auto_response"
    )

    def dispatch_calls(node):
        for child in ast.walk(node):
            if (
                isinstance(child, ast.Call)
                and isinstance(child.func, ast.Subscript)
                and isinstance(child.func.value, ast.Name)
                and child.func.value.id == "command_handler"
            ):
                yield child

    assert list(dispatch_calls(auto_response)), "dispatch call not found"

    guarded = []
    for node in ast.walk(auto_response):
        if isinstance(node, ast.Try):
            catches_exception = any(
                handler.type is not None
                and isinstance(handler.type, ast.Name)
                and handler.type.id == "Exception"
                for handler in node.handlers
            )
            if catches_exception and any(dispatch_calls(node)):
                guarded.extend(dispatch_calls(node))
    assert guarded, "command dispatch is not wrapped in try/except Exception"
