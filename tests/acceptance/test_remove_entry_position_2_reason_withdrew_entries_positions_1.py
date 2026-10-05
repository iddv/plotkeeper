"""Remove the entry at position 2 with reason "withdrew" (Entries at positions 1–4).

Expected: The entry closes (still visible on the gardener), former positions 3 and 4 become 2 and 3
Source: "Remove from the list, with a reason (withdrew, unreachable, other); the entry closes and later entries move up."
"""

import re
import datetime as dt
import os
from _helpers.driver import *


def test_remove_entry_position_2_reason_withdrew_entries_positions_1(monkeypatch):
    s = System(monkeypatch); a = s.setup_admin()
    gs = [a.waiter(n) for n in ("P1", "P2", "P3", "P4")]
    e = a.entry(gs[1])
    r = a.c.post(f"/waitlist/{e['id']}/remove", dict(reason="withdrew", note=""), referer="/waitlist")
    assert a.entry(gs[1])["status"] == "removed"
    assert a.waitlist_names() == ["P1", "P3", "P4"]
    assert "withdrew" in a.c.get(f"/gardeners/{gs[1]}").text.lower()
