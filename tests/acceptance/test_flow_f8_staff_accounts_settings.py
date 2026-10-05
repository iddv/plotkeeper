"""Flow F8: Staff accounts and settings.

Flow: F8 in SCOPE.md.
"""

import re
import os
from _helpers.driver import *


def test_flow_f8_staff_accounts_settings(monkeypatch):
    s = System(monkeypatch); a = s.setup_admin()
    r = a.c.follow(a.c.post("/users", dict(username="coord", role="coordinator")))
    pw = re.search(r"Temporary password for coord : (\S+)", r.text).group(1)
    cl, r = s.login("coord", pw)
    assert r.location == "/account/password"
    assert cl.get("/plots").location == "/account/password"
    r = cl.post("/account/password", dict(current=pw, new="new password 123", new2="new password 123"))
    assert s.q("SELECT must_change FROM users WHERE username='coord'")[0]["must_change"] == 0, r.text[-300:]
    assert cl.get("/settings").status == 403
    assert cl.post("/settings", dict(garden_name="Hacked")).status == 403
    p = a.new_plot("A"); g = a.new_gardener("G"); a.assign(p, g, "2026-01-01"); a.open_season(2026)
    r = cl.post(f"/gardeners/{g}/money", dict(kind="adjustment", amount="-60.00", season_id=a.season_id(2026), date="2026-05-10", reason="x", token="zz"))
    assert [l["kind"] for l in a.ledger(g)] == ["charge"]
    uid = s.q("SELECT id FROM users WHERE username='boss'")[0]["id"]
    a.c.post(f"/users/{uid}/active", dict(active="0"), referer="/users")
    assert s.q("SELECT active FROM users WHERE id=?", uid)[0]["active"] == 1
    a.set("offers.expiry_days", "21")
    assert "offers.expiry_days" in a.c.get("/audit").text
