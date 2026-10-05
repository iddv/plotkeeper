"""View the dashboard (An offer was made 13 days ago).

Expected: The offer shows as open, not Expired
Source: "Expiry is 14 days after the offer date (default)."
"""

import re
import datetime as dt
import os
from _helpers.driver import *


def test_view_dashboard_offer_was_made_13_days_ago(monkeypatch):
    s = System(monkeypatch); a = s.setup_admin()
    a.waiter("W"); p = a.new_plot("A-1"); a.offer(p)
    s.clock.advance(days=13)
    t = a.c.get("/").text
    assert "1 open, 0 expired" in t
