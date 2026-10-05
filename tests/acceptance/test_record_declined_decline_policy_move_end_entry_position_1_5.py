"""Record Declined (decline_policy = move_to_end; entry at position 1 of 5).

Expected: The entry's join timestamp becomes the decline time and it moves to the last position
Source: ""move_to_end" sets the join timestamp to the decline time."
"""

import re
import datetime as dt
import os
from _helpers.driver import *


def test_record_declined_decline_policy_move_end_entry_position_1_5(monkeypatch):
    s = System(monkeypatch); a = s.setup_admin()
    a.set("waitlist.decline_policy", "move_to_end")
    for n in ("P1", "P2", "P3", "P4", "P5"): a.waiter(n)
    g = s.q("SELECT id FROM gardeners WHERE name='P1'")[0]["id"]
    p = a.new_plot("A-1"); a.offer(p)
    s.clock.advance(days=2)
    a.outcome(p, "declined")
    assert a.entry(g)["joined_at"].startswith("2026-05-12")
    assert a.waitlist_names() == ["P2", "P3", "P4", "P5", "P1"]
