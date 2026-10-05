"""Flow F6: Record payments, refunds and adjustments.

Flow: F6 in SCOPE.md.
"""

import re
import os
from _helpers.driver import *


def test_flow_f6_record_payments_refunds_adjustments(monkeypatch):
    s = System(monkeypatch); a = s.setup_admin()
    p = a.new_plot("A", "standard"); g = a.new_gardener("Payer"); a.assign(p, g, "2026-01-01"); a.open_season(2026, due="2026-12-31")
    assert "Balance is 60.00; amount exceeds it" in a.money(g, "payment", "70.00").text
    assert a.money(g, "payment", "60.00", method="bank_transfer", token="T1").status == 303
    a.money(g, "payment", "60.00", method="bank_transfer", token="T1")
    assert len([l for l in a.ledger(g) if l["kind"] == "payment"]) == 1
    pid = [l for l in a.ledger(g) if l["kind"] == "payment"][0]["id"]
    a.c.post(f"/ledger/{pid}/void", dict(reason="wrong person"), referer=f"/gardeners/{g}")
    a.money(g, "payment", "50.00")
    assert "Refund cannot exceed 50.00 paid" in a.money(g, "refund", "50.01", reason="x").text
    a.money(g, "refund", "5.00", reason="returned")
    a.money(g, "adjustment", "-10.00", reason="discount")
    kinds = [l["kind"] for l in a.ledger(g)]
    assert kinds == ["charge", "payment", "void", "payment", "refund", "adjustment"]
    assert sum(l["amount"] for l in a.ledger(g)) == 500
    t = a.c.get(f"/gardeners/{g}").text
    assert "5.00" in t and "voided" in t.lower()
