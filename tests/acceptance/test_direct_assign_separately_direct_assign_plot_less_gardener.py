"""Direct assign, and separately direct assign to a plot-less gardener without a reason (An Admin, an Available plot, and a gardener who already holds a plot).

Expected: Both are refused; with a reason and a plot-less gardener it succeeds and appears in the audit trail
Source: "Direct assign is Admin only, with a required reason such as an accessibility need. It assigns an Available plot to any gardener without a plot"
"""

import re
import datetime as dt
import os
from _helpers.driver import *


def test_direct_assign_separately_direct_assign_plot_less_gardener(monkeypatch):
    s = System(monkeypatch); a = s.setup_admin()
    p = a.new_plot("A-1"); q = a.new_plot("B-1")
    h = a.new_gardener("Holder"); a.assign(q, h, "2026-05-01")
    a.assign(p, h, "2026-05-10")
    assert a.plot(p)["status"] == "available"
    g = a.new_gardener("Free")
    a.assign(p, g, "2026-05-10", reason="")
    assert a.plot(p)["status"] == "available"
    assert a.assign(p, g, "2026-05-10", reason="wheelchair access").status == 303
    assert a.plot(p)["status"] == "occupied"
    assert s.q("SELECT count(*) n FROM audit WHERE action LIKE '%assign%'")[0]["n"] >= 1
