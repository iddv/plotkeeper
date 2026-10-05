"""Flow F3: Manage gardeners and the waiting list.

Flow: F3 in SCOPE.md.
"""

import re
import os
from _helpers.driver import *


def test_flow_f3_manage_gardeners_waiting_list(monkeypatch):
    s = System(monkeypatch); a = s.setup_admin()
    g1 = a.new_gardener("Ann Smith", "ann@example.org")
    r = a.add_gardener("Ann S", "ann@example.org"); assert r.status != 303 and f'/gardeners/{g1}"' in r.body
    assert "Ann Smith" in a.c.get("/gardeners?q=ann@example").text
    g2 = a.new_gardener("Bob"); g3 = a.new_gardener("Cat"); g4 = a.new_gardener("Dan")
    a.wait(g1); a.wait(g2, "small", "2024-01-15"); a.wait(g3, "large"); a.wait(g4)
    assert a.waitlist_names() == ["Bob", "Ann Smith", "Cat", "Dan"]
    e = a.entry(g1); a.c.post(f"/waitlist/{e['id']}/remove", dict(reason="unreachable", note=""), referer="/waitlist")
    assert a.waitlist_names() == ["Bob", "Cat", "Dan"]
    a.open_season(2026); a.money(g1, "adjustment", "10.00", season_id=a.season_id(2026), reason="key deposit")
    a.c.post(f"/gardeners/{g1}/archive", dict(archived="1"), referer=f"/gardeners/{g1}")
    assert s.q("SELECT archived FROM gardeners WHERE id=?", g1)[0]["archived"] == 0
