"""Return it to service, then retire it (A plot is Out of service).

Expected: Return sets it to Available; retiring from Available (or directly from Out of service) succeeds, the plot leaves the default list and its history remains viewable
Source: "Retire plot, from Available or Out of service, with a reason: the plot leaves the default list. Its history stays viewable."
"""

import re
import datetime as dt
import os
from _helpers.driver import *


def test_return_service_retire_plot_out_service(monkeypatch):
    s = System(monkeypatch); a = s.setup_admin()
    p = a.new_plot("R-1"); q = a.new_plot("R-2")
    a.plot_status(p, "out_of_service", "x"); a.plot_status(p, "return")
    assert a.plot(p)["status"] == "available"
    assert a.plot_status(p, "retire", "gone").status == 303 and a.plot(p)["status"] == "retired"
    a.plot_status(q, "out_of_service", "x")
    assert a.plot_status(q, "retire", "gone").status == 303 and a.plot(q)["status"] == "retired"
    lst = a.c.get("/plots").text
    assert "R-1" not in lst
    d = a.c.get(f"/plots/{p}").text
    assert "History" in d and "etire" in d
