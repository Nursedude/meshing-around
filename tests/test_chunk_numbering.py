# send_message numbered its chunks with `message_list.index(m)`, which returns
# the position of the first element EQUAL to m — so two chunks with identical
# text both reported the earlier one's number.
#
# Observed live 2026-09-01 on a 5-chunk NOAA forecast whose 2nd and 4th chunks
# were both the overflow string "0.1-0.25in.":
#
#     Chunker1/5  Chunker2/5  Chunker3/5  Chunker2/5  Chunker5/5
#                                          ^^^ should be 4/5, and no 4/5 exists
#
# The label is cosmetic. The SAME lookup drove the send throttle, and there it
# is not: the 4th chunk resolved to index 1, so `(1+1) % 4` skipped a sleep
# that exists to avoid spamming the radio. A counter that repeats a value also
# skips one, and the skipped one was the one that did work.
#
# modules/system.py opens the radio at import (and exit()s), so send_message is
# loaded a function at a time via load_function, like mesh_bot.py.

import logging

import pytest

from conftest import load_function

SRC = "modules/system.py"

# The real captured chunk list: element 1 and element 3 are byte-identical.
FORECAST_CHUNKS = [
    "Tonight: A chance of rain shwrs. Mostly cloudy, with a low ~ 64.",
    "0.1-0.25in.",
    "Wed: A chance of rain shwrs. Mostly cloudy, with a high near 72.",
    "0.1-0.25in.",
    "Wed Night: Scattered rain shwrs. Mostly cloudy, with a low ~ 63.",
]


class _Interface:
    def __init__(self):
        self.sent = []

    def sendText(self, text=None, **kw):
        self.sent.append(text)

    def sendData(self, payload, **kw):
        self.sent.append(payload)


class _Fmt:
    red = white = purple = ""


def _run(chunks, *, nodeid=0, record_sleeps=None):
    """Drive send_message over a fixed chunk list; return (labels, iface)."""
    labels = []
    iface = _Interface()

    class _Log:
        def info(self, msg, *a, **k):
            labels.append(msg)
        debug = warning = error = lambda self, *a, **k: None

    ns = {
        "interface1": iface,
        "logger": _Log(),
        "CustomFormatter": _Fmt,
        "maxBuffer": 10_000,
        "responseDelay": 0,
        "splitDelay": 0,
        "wantAck": False,
        "messageChunker": lambda _m: list(chunks),
        "get_name_from_number": lambda *a, **k: "test-node",
        "time": type("t", (), {"sleep": staticmethod(
            lambda s: (record_sleeps.append(s) if record_sleeps is not None else None))}),
    }
    fn = load_function(SRC, "send_message", ns)
    fn("irrelevant — messageChunker is stubbed", 0, nodeid=nodeid)
    return labels, iface


def _numbers(labels):
    """The N from every 'ChunkerN/M' the send loop logged."""
    import re
    out = []
    for line in labels:
        m = re.search(r"Chunker(\d+)/(\d+)", line)
        if m:
            out.append((int(m.group(1)), int(m.group(2))))
    return out


class TestChunkNumbering:

    def test_duplicate_chunks_still_number_sequentially(self):
        """THE case: byte-identical chunks must not share a number."""
        labels, _ = _run(FORECAST_CHUNKS)
        nums = _numbers(labels)
        assert [n for n, _ in nums] == [1, 2, 3, 4, 5], \
            f"expected 1..5, got {[n for n, _ in nums]}"
        assert all(total == 5 for _, total in nums)

    def test_every_chunk_is_still_sent(self, ):
        """Numbering is a label — the payloads must be untouched."""
        _, iface = _run(FORECAST_CHUNKS)
        assert iface.sent == FORECAST_CHUNKS

    def test_all_identical_chunks_are_numbered_distinctly(self):
        """The degenerate case the old code collapsed to a single number."""
        labels, _ = _run(["same"] * 4)
        assert [n for n, _ in _numbers(labels)] == [1, 2, 3, 4]

    def test_unique_chunks_are_unaffected(self):
        """Guard the over-reach direction: the old code was right here."""
        labels, _ = _run(["a", "b", "c"])
        assert [n for n, _ in _numbers(labels)] == [1, 2, 3]


class TestThrottleIsNotSkippedByDuplicates:
    """The half that is not cosmetic."""

    def test_throttle_fires_on_the_fourth_chunk_despite_a_duplicate(self):
        sleeps = []
        _run(FORECAST_CHUNKS, record_sleeps=sleeps)
        # splitDelay=0 sleeps once per chunk; the throttle adds responseDelay+1.
        assert any(s >= 1 for s in sleeps), (
            "the 4th chunk must trigger the throttle sleep — with .index() it "
            f"resolved to position 2 and was skipped entirely; sleeps={sleeps}")

    def test_unique_chunks_throttle_identically(self):
        sleeps = []
        _run(["a", "b", "c", "d", "e"], record_sleeps=sleeps)
        assert any(s >= 1 for s in sleeps)
