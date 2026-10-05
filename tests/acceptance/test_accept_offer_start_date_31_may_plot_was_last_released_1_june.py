"""Accept an offer for it with start date 31 May (A plot was last released on 1 June).

Expected: Field error; nothing changes
Source: "Start date before the plot's last release date: field error."
"""

import re
import datetime as dt
import os
from _helpers.driver import *


def test_accept_offer_start_date_31_may_plot_was_last_released_1_june(monkeypatch):
    s = System(monkeypatch); a = s.setup_admin()
    p = a.new_plot("A-1"); g0 = a.new_gardener("Old")
    a.assign(p, g0, "2026-01-01"); a.release(p, "2026-06-01")
    s.clock.set(utc(2026, 6, 5))
    g = a.waiter("P1"); a.offer(p)
    r = a.outcome(p, "accepted", "2026-05-31")
    assert a.plot(p)["status"] == "offered" and a.entry(g)["status"] == "offered"
    assert s.q("SELECT count(*) n FROM assignments WHERE gardener_id=?", g)[0]["n"] == 0
