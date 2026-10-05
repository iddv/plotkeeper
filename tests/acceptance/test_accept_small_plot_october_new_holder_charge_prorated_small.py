"""Accept a small plot in October (new_holder_charge = prorated; small fee set to 60.50 for the season).

Expected: Charge is 15.13 (15.125 rounded half-up)
Source: "The result is rounded half-up to the cent."
"""

import re
import datetime as dt
import os
from _helpers.driver import *


def test_accept_small_plot_october_new_holder_charge_prorated_small(monkeypatch):
    s = System(monkeypatch, now=utc(2026, 10, 5)); a = s.setup_admin()
    a.open_season(2026, small="60.50"); a.set("fees.new_holder_charge", "prorated")
    g = a.waiter("Oct", "small"); p = a.new_plot("A-1", "small"); a.offer(p); a.outcome(p, "accepted", "2026-10-05")
    assert [l["amount"] for l in a.ledger(g) if l["kind"] == "charge"] == [1513]
