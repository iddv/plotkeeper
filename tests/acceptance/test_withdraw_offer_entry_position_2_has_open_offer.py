"""Withdraw the offer (An entry at position 2 has an open offer).

Expected: The entry is active again at its original position and the plot is Available
Source: "Withdraw offer: the entry is restored to its place."
"""

import re
import datetime as dt
import os
from _helpers.driver import *


def test_withdraw_offer_entry_position_2_has_open_offer(monkeypatch):
    s = System(monkeypatch); a = s.setup_admin()
    a.waiter("P1", "large"); g = a.waiter("P2"); a.waiter("P3")
    p = a.new_plot("A-1"); a.offer(p)
    assert a.entry(g)["status"] == "offered"
    a.outcome(p, "withdrawn")
    assert a.entry(g)["status"] == "active" and a.plot(p)["status"] == "available"
    assert a.waitlist_names() == ["P1", "P2", "P3"]
