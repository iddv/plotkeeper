"""Void it again (A payment has been voided).

Expected: Refused with "Already voided"; no second reversing entry; original stays visible marked voided
Source: "Voiding an already-voided payment: "Already voided"."
"""

import re
import datetime as dt
import os
from _helpers.driver import *


def test_void_again_payment_has_been_voided(monkeypatch):
    s = System(monkeypatch); a = s.setup_admin()
    p = a.new_plot("A-1"); g = a.new_gardener("G"); a.assign(p, g, "2026-01-01"); a.open_season(2026)
    a.money(g, "payment", "20.00")
    pid = [l for l in a.ledger(g) if l["kind"] == "payment"][0]["id"]
    assert a.c.post(f"/ledger/{pid}/void", dict(reason="typo"), referer=f"/gardeners/{g}").status == 303
    r = a.c.post(f"/ledger/{pid}/void", dict(reason="typo"), referer=f"/gardeners/{g}")
    assert "Already voided" in r.msg + r.text
    assert len([l for l in a.ledger(g) if l["kind"] == "void"]) == 1
    t = a.c.get(f"/gardeners/{g}").text
    assert "voided" in t.lower()
