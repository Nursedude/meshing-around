# _meshforge_reply_is_dup exists for ONE shape: the same MeshCore command
# reaching the bot via two bridge paths ([MC:who] and [chN:who]) seconds
# apart. An UNTAGGED message is a direct RF packet — the radio already drops
# repeated packet ids — so a second identical one is a person asking again
# (lehua 2026-10-17 07:56: `wx` → NOAA 500 → `wx` 21 s later, swallowed).

from conftest import load_function


def _guard(monkeypatch, window=None):
    if window is None:
        monkeypatch.delenv("MESHFORGE_REPLY_DEDUP_S", raising=False)
    else:
        monkeypatch.setenv("MESHFORGE_REPLY_DEDUP_S", str(window))
    return load_function("mesh_bot.py", "_meshforge_reply_is_dup", {})


def test_untagged_retry_from_the_same_node_is_answered(monkeypatch):
    dup = _guard(monkeypatch)
    assert dup("wx", "wx", 1, 1488149505) is False
    assert dup("wx", "wx", 1, 1488149505) is False


def test_dual_bridged_copy_is_still_answered_once(monkeypatch):
    dup = _guard(monkeypatch)
    assert dup("[MC:p4] wx", "wx", 1, 848429840) is False
    assert dup("[ch0:p4] wx", "wx", 1, 848429840) is True


def test_two_bridged_senders_are_never_collapsed(monkeypatch):
    dup = _guard(monkeypatch)
    assert dup("[MC:p4] wx", "wx", 1, 848429840) is False
    assert dup("[MC:kona] wx", "wx", 1, 848429840) is False


def test_window_zero_disables(monkeypatch):
    dup = _guard(monkeypatch, window=0)
    assert dup("[MC:p4] wx", "wx", 1, 1) is False
    assert dup("[ch0:p4] wx", "wx", 1, 1) is False
