"""Try to offer it, return it to service or direct assign it (A plot is Retired).

Expected: All are refused and the plot stays Retired
Source: "Validation before saving: required fields, uniqueness, allowed state transitions"
"""

import re
import datetime as dt
import os
from _helpers.driver import *


def test_try_offer_return_service_direct_assign_plot_retired(monkeypatch):
    s = System(monkeypatch); a = s.setup_admin()
    p = a.new_plot("R-1"); a.waiter("W")
    a.plot_status(p, "retire", "gone")
    a.plot_status(p, "return")
    a.offer_preview(p)
    w = s.q("SELECT id FROM waitlist")[0]["id"]
    a.c.post(f"/plots/{p}/offer", dict(version=a.plot(p)["version"], entry_id=w), referer=f"/plots/{p}")
    a.assign(p, a.new_gardener("Z"), "2026-05-10")
    assert a.plot(p)["status"] == "retired"
    assert s.q("SELECT count(*) n FROM offers")[0]["n"] == 0 and s.q("SELECT count(*) n FROM assignments")[0]["n"] == 0
