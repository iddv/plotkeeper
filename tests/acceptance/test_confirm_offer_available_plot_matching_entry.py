"""Confirm the offer (An Available plot and a matching entry).

Expected: The plot becomes Offered with an expiry 14 days after the offer date and the entry is marked offered
Source: "Expiry is 14 days after the offer date (default)."
"""

import re
import datetime as dt
import os
from _helpers.driver import *


def test_confirm_offer_available_plot_matching_entry(monkeypatch):
    s = System(monkeypatch); a = s.setup_admin()
    g = a.waiter("W"); p = a.new_plot("A-1")
    a.offer(p)
    assert a.plot(p)["status"] == "offered"
    o = a.open_offer(p)
    assert o["expires_on"] == "2026-05-24"
    assert a.entry(g)["status"] == "offered"
