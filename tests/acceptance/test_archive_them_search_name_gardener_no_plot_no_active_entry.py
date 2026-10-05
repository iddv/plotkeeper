"""Archive them, then search by name (A gardener with no plot, no active entry and zero balance).

Expected: They no longer appear in the default gardener list but are found by search
Source: "They leave the default list but stay searchable."
"""

import re
import datetime as dt
import os
from _helpers.driver import *


def test_archive_them_search_name_gardener_no_plot_no_active_entry(monkeypatch):
    s = System(monkeypatch); a = s.setup_admin()
    g = a.new_gardener("Zelda Quiet"); a.new_gardener("Other Person")
    a.c.post(f"/gardeners/{g}/archive", dict(archived="1"), referer=f"/gardeners/{g}")
    assert s.q("SELECT archived FROM gardeners WHERE id=?", g)[0]["archived"] == 1
    assert "Zelda" not in a.c.get("/gardeners").text
    assert "Zelda" in a.c.get("/gardeners?q=Zelda").text
