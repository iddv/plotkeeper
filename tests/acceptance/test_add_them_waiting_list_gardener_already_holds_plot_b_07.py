"""Add them to the waiting list (A gardener already holds plot B-07).

Expected: Refused with a message saying they already hold plot B-07
Source: "Gardener already holds a plot or already has an active entry: "Already holds plot X / already on the list at position N"."
"""

import re
import datetime as dt
import os
from _helpers.driver import *


def test_add_them_waiting_list_gardener_already_holds_plot_b_07(monkeypatch):
    s = System(monkeypatch); a = s.setup_admin()
    p = a.new_plot("B-07"); g = a.new_gardener("H"); a.assign(p, g, "2026-05-01")
    r = a.wait(g)
    assert "B-07" in (r.msg + r.text)
    assert s.q("SELECT count(*) n FROM waitlist")[0]["n"] == 0
