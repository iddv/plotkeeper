"""View the waiting list (An entry has declined exactly once).

Expected: The entry is still active (removal happens only after 2 declines)
Source: "After 2 declines (default), the entry is removed with reason "declined twice"."
"""

import re
import datetime as dt
import os
from _helpers.driver import *


def test_view_waiting_list_entry_has_declined_exactly_once(monkeypatch):
    s = System(monkeypatch); a = s.setup_admin()
    g = a.waiter("P1")
    p = a.new_plot("A-1"); a.offer(p); a.outcome(p, "declined")
    assert a.entry(g)["status"] == "active" and a.waitlist_names() == ["P1"]
