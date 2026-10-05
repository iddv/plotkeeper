"""Try to archive each (A gardener with no plot and no entry has a balance of -5.00 (in credit), and another has +10.00 owing).

Expected: Both are blocked with the reason; only a zero balance allows archiving
Source: "Archive a gardener who has no plot, no active entry and a zero balance."
"""

import re
import datetime as dt
import os
from _helpers.driver import *


def test_try_archive_each_gardener_no_plot_no_entry_has_balance_5_00(monkeypatch):
    s = System(monkeypatch); a = s.setup_admin()
    a.open_season(2026)
    g1 = a.new_gardener("Credit"); g2 = a.new_gardener("Owes")
    sid = a.season_id(2026)
    assert a.money(g1, "adjustment", "-5.00", season_id=sid, reason="waiver").status == 303
    assert a.money(g2, "adjustment", "10.00", season_id=sid, reason="fee").status == 303
    for g in (g1, g2):
        r = a.c.post(f"/gardeners/{g}/archive", dict(archived="1"), referer=f"/gardeners/{g}")
        assert s.q("SELECT archived FROM gardeners WHERE id=?", g)[0]["archived"] == 0, g
