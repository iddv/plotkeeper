"""Flow F2: Manage plots.

Flow: F2 in SCOPE.md.
"""

import re
import os
from _helpers.driver import *


def test_flow_f2_manage_plots(monkeypatch):
    s = System(monkeypatch); a = s.setup_admin()
    assert a.add_plot("B-07", "small", "12.5", "near tap").status == 303
    p = a.plot_id("B-07")
    assert "Plot code B-07 already exists" in a.add_plot("B-07").text
    assert "B-07" in a.c.get("/plots?q=B-07").text
    assert a.edit_plot(p, size="large", notes="moved").status == 303 and a.plot(p)["size"] == "large"
    a.plot_status(p, "out_of_service", "flooded"); assert a.plot(p)["status"] == "out_of_service"
    a.plot_status(p, "return"); assert a.plot(p)["status"] == "available"
    q = a.new_plot("C-01"); a.assign(q, a.new_gardener("Holder"), "2026-05-01")
    assert "Release the holder or withdraw the offer first" in a.plot_status(q, "retire", "x").msg
    a.plot_status(p, "retire", "path"); assert a.plot(p)["status"] == "retired"
    assert "B-07" not in a.c.get("/plots").text
    h = a.c.get(f"/plots/{p}").text; h = h[h.find("History"):]
    for w in ("added", "Edited", "Available → Out of service", "Out of service → Available", "→ Retired"):
        assert w in h, w
