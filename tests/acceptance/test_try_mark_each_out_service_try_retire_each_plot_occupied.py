"""Try to mark each out of service, and try to retire each (A plot is Occupied, and another is Offered).

Expected: All four attempts are blocked with "Release the holder or withdraw the offer first"; statuses unchanged
Source: "Retire or put out of service while Occupied or Offered: blocked with "Release the holder or withdraw the offer first"."
"""

import re
import datetime as dt
import os
from _helpers.driver import *


def test_try_mark_each_out_service_try_retire_each_plot_occupied(monkeypatch):
    s = System(monkeypatch); a = s.setup_admin()
    po = a.new_plot("O-1"); pf = a.new_plot("F-1")
    g = a.new_gardener("Holder"); assert a.assign(po, g, "2026-05-01").status == 303
    a.waiter("Waiter"); assert a.offer(pf).status == 303
    for pid, st in ((po, "occupied"), (pf, "offered")):
        for act in ("out_of_service", "retire"):
            r = a.plot_status(pid, act)
            assert "Release the holder or withdraw the offer first" in r.msg, (act, r.msg)
            assert a.plot(pid)["status"] == st
