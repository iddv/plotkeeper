"""Flow F5: Open a season and charge fees.

Flow: F5 in SCOPE.md.
"""

import re
import os
from _helpers.driver import *


def test_flow_f5_open_season_charge_fees(monkeypatch):
    s = System(monkeypatch, now=utc(2026, 1, 5)); a = s.setup_admin()
    for i, z in enumerate(["small", "standard", "large"]):
        a.assign(a.new_plot(f"P{i}", z), a.new_gardener(f"G{i}"), "2026-01-01")
    t = a.c.get("/seasons/new").body
    assert "40.00" in t and "60.00" in t and "80.00" in t
    r = a.c.post("/seasons/new", dict(year="2026", due_date="2026-03-31", fee_small="40.00", fee_standard="60.00", fee_large="80.00"), referer="/seasons/new")
    assert "3" in r.text
    assert a.open_season(2026).status == 303
    assert sorted(x["amount"] for x in s.q("SELECT amount FROM ledger WHERE kind='charge'")) == [4000, 6000, 8000]
    assert "already exists" in a.open_season(2026).text
    assert s.q("SELECT count(*) n FROM ledger WHERE kind='charge'")[0]["n"] == 3
    s.clock.set(utc(2026, 7, 1))
    g = a.waiter("Mid"); p = a.new_plot("M", "standard"); a.offer(p); a.outcome(p, "accepted", "2026-07-01")
    assert [l["amount"] for l in a.ledger(g) if l["kind"] == "charge"] == [6000]
    a.set("fees.new_holder_charge", "prorated")
    g = a.waiter("Mid2"); p = a.new_plot("M2", "standard"); a.offer(p); a.outcome(p, "accepted", "2026-07-01")
    assert [l["amount"] for l in a.ledger(g) if l["kind"] == "charge"] == [3000]
