"""Record Accepted (No season has ever been opened; an offer is open).

Expected: The plot becomes Occupied and no fee charge is created
Source: "a fee charge is created if a season is open"
"""

import re
import datetime as dt
import os
from _helpers.driver import *


def test_record_accepted_no_season_has_ever_been_opened_offer_open(monkeypatch):
    s = System(monkeypatch); a = s.setup_admin()
    g = a.waiter("P1"); p = a.new_plot("A-1"); a.offer(p)
    a.outcome(p, "accepted", "2026-05-10")
    assert a.plot(p)["status"] == "occupied" and a.ledger(g) == []
