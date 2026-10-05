"""View the Dues page and export season dues CSV (Charged 60.00; payments of 20.00 (Partly paid) and later a ledger with charges, payments, a void, a refund and an adjustment across several gardeners).

Expected: Each balance = charges + adjustments − payments + voids + refunds; season totals equal the sum of gardener balances and match the CSV
Source: "Season totals always equal the sum of the gardener balances."
"""

import re
import datetime as dt
import os
from _helpers.driver import *


def test_view_dues_page_export_season_dues_csv_charged_60_00_payments(monkeypatch):
    s = System(monkeypatch); a = s.setup_admin()
    a.set("payments.overpayment", "credit")
    gs = []
    for i, z in enumerate(["small", "standard", "large", "standard"]):
        p = a.new_plot(f"P-{i}", z); g = a.new_gardener(f"Name{i}"); a.assign(p, g, "2026-01-01"); gs.append(g)
    a.open_season(2026, due="2026-12-31"); sid = a.season_id(2026)
    a.money(gs[1], "payment", "20.00")
    a.money(gs[0], "payment", "40.00"); a.money(gs[0], "payment", "5.00")
    a.money(gs[2], "payment", "80.00"); a.money(gs[2], "refund", "10.00", reason="x")
    pid = [l for l in a.ledger(gs[3]) if l["kind"] == "charge"]
    a.money(gs[3], "payment", "30.00"); vid = [l for l in a.ledger(gs[3]) if l["kind"] == "payment"][0]["id"]
    a.c.post(f"/ledger/{vid}/void", dict(reason="typo"), referer=f"/gardeners/{gs[3]}")
    a.money(gs[3], "adjustment", "-10.00", reason="disc")
    bal = s.q("SELECT sum(amount) b FROM ledger WHERE season_id=?", sid)[0]["b"]
    t = a.c.get(f"/dues?season={sid}").text
    row = t[t.find("Name1"):][:200]
    assert "Partly paid" in row
    csv = a.c.get(f"/export/dues.csv?season={sid}").body
    assert "%d.%02d" % (bal // 100, bal % 100) in t
    total = 0
    import csv as _csv, io
    rows = list(_csv.reader(io.StringIO(csv)))
    bi = [h.lower() for h in rows[0]].index("balance")
    for r_ in rows[1:]:
        if r_[bi]: total += round(float(r_[bi]) * 100)
    assert total == bal
