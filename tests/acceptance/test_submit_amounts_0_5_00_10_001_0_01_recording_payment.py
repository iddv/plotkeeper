"""Submit amounts 0, -5.00, 10.001 and 0.01 (Recording a payment).

Expected: The first three are field errors and nothing is saved; 0.01 is saved
Source: "Amount zero, negative or more than 2 decimals: field error."
"""

import re
import datetime as dt
import os
from _helpers.driver import *


def test_submit_amounts_0_5_00_10_001_0_01_recording_payment(monkeypatch):
    s = System(monkeypatch); a = s.setup_admin()
    p = a.new_plot("A-1"); g = a.new_gardener("G"); a.assign(p, g, "2026-01-01"); a.open_season(2026)
    for amt in ("0", "-5.00", "10.001"):
        r = a.money(g, "payment", amt)
        assert r.status != 303, amt
    assert [l["kind"] for l in a.ledger(g)] == ["charge"]
    assert a.money(g, "payment", "0.01").status == 303
    assert [l["amount"] for l in a.ledger(g) if l["kind"] == "payment"] == [-1]
