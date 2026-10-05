"""Flow F7: Dues overview, totals and exports.

Flow: F7 in SCOPE.md.
"""

import re
import os
from _helpers.driver import *


def test_flow_f7_dues_overview_totals_exports(monkeypatch):
    import csv, io
    s = System(monkeypatch); a = s.setup_admin()
    a.set("payments.overpayment", "credit")
    gs = []
    for i, z in enumerate(["small", "standard", "large", "small"]):
        p = a.new_plot(f"P{i}", z); g = a.new_gardener(f"Name{i}"); a.assign(p, g, "2026-01-01"); gs.append(g)
    a.waiter("Waiting One")
    a.open_season(2026, due="2026-12-31"); sid = a.season_id(2026)
    a.money(gs[0], "payment", "40.00"); a.money(gs[1], "payment", "20.00"); a.money(gs[2], "payment", "90.00", method="card")
    t = a.c.get(f"/dues?season={sid}").text
    for n, st in (("Name0", "Paid"), ("Name1", "Partly paid"), ("Name2", "In credit"), ("Name3", "Unpaid")):
        assert st in t[t.find(n):][:150], n
    bal = s.q("SELECT sum(amount) b FROM ledger")[0]["b"]
    d = list(csv.reader(io.StringIO(a.c.get(f"/export/dues.csv?season={sid}").body)))
    bi = [h.lower() for h in d[0]].index("balance")
    assert sum(round(float(r[bi]) * 100) for r in d[1:] if r[bi]) == bal
    pay = a.c.get("/export/payments.csv?from=2026-05-01&to=2026-05-31").body
    assert "150.00" in pay
    pl = a.c.get("/export/plots.csv").body.strip().splitlines(); assert len(pl) == 5
    wl = a.c.get("/export/waitlist.csv").body.strip().splitlines(); assert len(wl) == 2 and "Waiting One" in wl[1]
