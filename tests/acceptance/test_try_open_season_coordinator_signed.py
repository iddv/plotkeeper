"""Try to open a season (A Coordinator is signed in).

Expected: Refused by the server
Source: "Coordinators cannot manage accounts or settings, and cannot open a season."
"""

import re
import datetime as dt
import os
from _helpers.driver import *


def test_try_open_season_coordinator_signed(monkeypatch):
    import plotkeeper.core as CC
    s = System(monkeypatch); a = s.setup_admin()
    a.c.post("/users", dict(username="coord", role="coordinator"))
    c = s.db(); c.execute("UPDATE users SET pw_hash=?, must_change=0 WHERE username='coord'", (CC.hash_password(PW),)); c.commit(); c.close()
    cl, r = s.login("coord", PW)
    r = cl.post("/seasons/new", dict(step="confirm", year="2026", due_date="2026-03-31", fee_small="40.00", fee_standard="60.00", fee_large="80.00"))
    assert r.status == 403 and s.q("SELECT count(*) n FROM seasons")[0]["n"] == 0
