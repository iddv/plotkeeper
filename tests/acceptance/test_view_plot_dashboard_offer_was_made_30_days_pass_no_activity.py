"""View the plot and dashboard (An offer was made and 30 days pass with no activity).

Expected: The plot is still Offered, the offer is flagged Expired, and the entry is not changed until a user records the outcome
Source: "Expired offers are flagged but never auto-resolved. A user records the outcome."
"""

import re
import datetime as dt
import os
from _helpers.driver import *


def test_view_plot_dashboard_offer_was_made_30_days_pass_no_activity(monkeypatch):
    s = System(monkeypatch); a = s.setup_admin()
    g = a.waiter("W"); p = a.new_plot("A-1"); a.offer(p)
    s.clock.advance(days=30)
    assert a.plot(p)["status"] == "offered"
    assert "Expired" in a.c.get("/").text
    assert a.entry(g)["status"] == "offered" and a.open_offer(p)["status"] == "open"
