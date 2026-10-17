# The dual-bridge reply dedup (_meshforge_reply_is_dup) was REMOVED
# 2026-10-17. Measured on lehua, the only bot box: 33 days of logs, 430
# commands, 99 [MC:] bridged, ZERO [chN:] second copies — the dual path it
# guarded no longer exists — and its only firing in that window dropped a
# person's `wx` retry. A suppression path with no true positive is a way to
# swallow a reply, not a safeguard. If a second bridge path returns, the cost
# is a visible duplicate reply in the bot log; re-add only with a live witness.

from conftest import parsed_source


def test_no_reply_suppression_path_remains():
    tree, source = parsed_source("mesh_bot.py")
    names = {getattr(n, "name", None) for n in tree.body}
    assert "_meshforge_reply_is_dup" not in names
    assert "MESHFORGE_REPLY_DEDUP_S" not in source
    assert "dropped duplicate reply" not in source
