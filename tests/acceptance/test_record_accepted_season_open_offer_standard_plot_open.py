"""Record Accepted (A season is open; an offer of a standard plot is open).

Expected: An assignment starts on the chosen date, entry closes as placed, plot becomes Occupied, and a fee charge is created
Source: "Accepted: an assignment starts on the chosen date, the entry closes as "placed", the plot becomes Occupied, and a fee charge is created if a season is open."
"""

import re
import datetime as dt
import os
from _helpers.driver import *


def test_record_accepted_season_open_offer_standard_plot_open(monkeypatch):
    s = System(monkeypatch); a = s.setup_admin()
    a.open_season(2026)
    g = a.waiter("P1"); p = a.new_plot("A-1"); a.offer(p)
    a.outcome(p, "accepted", "2026-05-12")
    asg = s.q("SELECT * FROM assignments WHERE plot_id=?", p)[0]
    assert asg["start_date"] == "2026-05-12" and asg["gardener_id"] == g
    assert a.entry(g)["status"] == "placed" and a.plot(p)["status"] == "occupied"
    ch = [l for l in a.ledger(g) if l["kind"] == "charge"]
    assert len(ch) == 1 and ch[0]["amount"] == 6000
