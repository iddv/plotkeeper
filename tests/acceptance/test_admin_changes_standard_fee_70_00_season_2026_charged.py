"""Admin changes the standard fee to 70.00 (Season 2026 charged a standard holder 60.00).

Expected: The existing charge stays 60.00
Source: "The fee is fixed on the charge when it is created, so later fee changes don't alter existing charges."
"""

import re
import datetime as dt
import os
from _helpers.driver import *


def test_admin_changes_standard_fee_70_00_season_2026_charged(monkeypatch):
    s = System(monkeypatch); a = s.setup_admin()
    p = a.new_plot("A-1"); g = a.new_gardener("G"); a.assign(p, g, "2026-01-01")
    a.open_season(2026)
    a.set("fee.standard", "70.00")
    ch = [l for l in a.ledger(g) if l["kind"] == "charge"]
    assert len(ch) == 1 and ch[0]["amount"] == 6000
