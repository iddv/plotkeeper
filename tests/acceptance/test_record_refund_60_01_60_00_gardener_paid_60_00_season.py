"""Record a refund of 60.01, then 60.00 (A gardener paid 60.00 for the season).

Expected: 60.01 refused with "Refund cannot exceed 60.00 paid"; 60.00 saved as a negative entry
Source: "Refund greater than net paid for the season: "Refund cannot exceed 60.00 paid"."
"""

import re
import datetime as dt
import os
from _helpers.driver import *


def test_record_refund_60_01_60_00_gardener_paid_60_00_season(monkeypatch):
    s = System(monkeypatch); a = s.setup_admin()
    p = a.new_plot("A-1"); g = a.new_gardener("G"); a.assign(p, g, "2026-01-01"); a.open_season(2026)
    a.money(g, "payment", "60.00")
    r = a.money(g, "refund", "60.01", reason="moved away")
    assert "Refund cannot exceed 60.00 paid" in r.text
    assert a.money(g, "refund", "60.00", reason="moved away").status == 303
    rf = [l for l in a.ledger(g) if l["kind"] == "refund"]
    assert len(rf) == 1 and abs(rf[0]["amount"]) == 6000
