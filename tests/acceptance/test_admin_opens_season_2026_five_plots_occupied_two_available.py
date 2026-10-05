"""Admin opens season 2026 (Five plots are Occupied, two Available; fees default).

Expected: Exactly five charges are created, each at its plot size's fee (40.00/60.00/80.00), and 2026 becomes current
Source: "One fee charge per active assignment is created for that season, and the season becomes the current season."
"""

import re
import datetime as dt
import os
from _helpers.driver import *


def test_admin_opens_season_2026_five_plots_occupied_two_available(monkeypatch):
    s = System(monkeypatch); a = s.setup_admin()
    sizes = ["small", "standard", "large", "standard", "small", "large", "small"]
    for i, z in enumerate(sizes):
        p = a.new_plot(f"P-{i}", z)
        if i < 5: a.assign(p, a.new_gardener(f"G{i}"), "2026-01-01")
    assert a.open_season(2026).status == 303
    ch = s.q("SELECT amount FROM ledger WHERE kind='charge' ORDER BY id")
    assert sorted(c["amount"] for c in ch) == sorted([4000, 6000, 8000, 6000, 4000])
    assert "2026" in a.c.get("/seasons").text
