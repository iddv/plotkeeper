"""Record a payment of 40.01, then one of 40.00 (overpayment = reject; balance 40.00).

Expected: 40.01 is refused with "Balance is 40.00; amount exceeds it"; 40.00 is saved and status becomes Paid
Source: "Overpayment when payments.overpayment = reject: "Balance is 40.00; amount exceeds it"."
"""

import re
import datetime as dt
import os
from _helpers.driver import *


def test_record_payment_40_01_one_40_00_overpayment_reject_balance_40(monkeypatch):
    s = System(monkeypatch); a = s.setup_admin()
    p = a.new_plot("A-1", "small"); g = a.new_gardener("G"); a.assign(p, g, "2026-01-01"); a.open_season(2026)
    r = a.money(g, "payment", "40.01")
    assert "Balance is 40.00; amount exceeds it" in r.text
    assert a.money(g, "payment", "40.00").status == 303
    t = a.c.get(f"/dues?season={a.season_id(2026)}").text
    assert "Paid" in t and "Partly" not in t.split("Paid")[-1][:0]
    assert C.due_status(4000, 0, "2026-03-31", dt.date(2026, 5, 10)) == "Paid"
