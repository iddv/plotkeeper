"""Try to offer the plot to the next in line, and an Admin tries to direct assign it (A plot is Out of service and a matching person is on the waiting list).

Expected: Both are refused; only Available plots can be offered or directly assigned
Source: "Only Available plots can be offered or directly assigned."
"""

import re
import datetime as dt
import os
from _helpers.driver import *


def test_try_offer_plot_next_line_admin_tries_direct_assign_plot_out(monkeypatch):
    s = System(monkeypatch); a = s.setup_admin()
    p = a.new_plot("S-1"); a.waiter("W")
    a.plot_status(p, "out_of_service", "broken fence")
    assert a.plot(p)["status"] == "out_of_service"
    r = a.offer_preview(p); assert 'name="entry_id"' not in r.body
    r = a.c.post(f"/plots/{p}/offer", dict(version=a.plot(p)["version"], entry_id=a.entry(s.q("SELECT gardener_id FROM waitlist")[0]["gardener_id"])["id"]), referer=f"/plots/{p}")
    g2 = a.new_gardener("Other")
    r2 = a.assign(p, g2, "2026-05-10")
    assert a.plot(p)["status"] == "out_of_service"
    assert s.q("SELECT count(*) n FROM offers")[0]["n"] == 0
    assert s.q("SELECT count(*) n FROM assignments")[0]["n"] == 0
