"""Offer plot B to next in line (The first matching entry already has an open offer on plot A; plot B of the same size is Available).

Expected: The next matching entry is proposed, not the one already holding an open offer
Source: "One open offer per plot and per entry."
"""

import re
import datetime as dt
import os
from _helpers.driver import *


def test_offer_plot_b_next_line_first_matching_entry_already_has_open(monkeypatch):
    s = System(monkeypatch); a = s.setup_admin()
    a.waiter("First"); a.waiter("Second")
    pa = a.new_plot("A-1"); pb = a.new_plot("B-1")
    assert a.offer(pa).status == 303
    t = a.offer_preview(pb).text
    assert "Second" in t and "First" not in t
