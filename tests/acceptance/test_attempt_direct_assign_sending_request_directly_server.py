"""Attempt a direct assign by sending the request directly to the server (A Coordinator is signed in).

Expected: Refused by the server
Source: "The server enforces roles, not only the UI."
"""

import re
import datetime as dt
import os
from _helpers.driver import *


def test_attempt_direct_assign_sending_request_directly_server(monkeypatch):
    s = System(monkeypatch); a = s.setup_admin()
    a.c.post("/users", dict(username="coord", role="coordinator"))
    pw = re.search(r"temporary password[^A-Za-z0-9_-]*([A-Za-z0-9_-]{8,})", a.c.get("/users").text)
    import plotkeeper.core as CC
    p = a.new_plot("A-1"); g = a.new_gardener("G")
    c = s.db(); c.execute("UPDATE users SET pw_hash=?, must_change=0 WHERE username='coord'", (CC.hash_password(PW),)); c.commit(); c.close()
    cl, r = s.login("coord", PW)
    r = cl.post(f"/plots/{p}/assign", dict(version=a.plot(p)["version"], gardener_id=g, start_date="2026-05-10", reason="x"))
    assert r.status == 403
    assert a.plot(p)["status"] == "available"
