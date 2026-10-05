"""Offer to next in line (Waiting list in order: 1 prefers large, 2 prefers small, 3 prefers any; a standard plot is Available).

Expected: Entry 3 (any) is proposed, skipping 1 and 2
Source: "Size matching: a plot is offered to the earliest entry whose preference equals the plot's size or is "any"."
"""

import re
import datetime as dt
import os
from _helpers.driver import *


def test_offer_next_line_waiting_list_order_1_prefers_large_2_prefers(monkeypatch):
    s = System(monkeypatch); a = s.setup_admin()
    a.waiter("Large1", "large"); a.waiter("Small2", "small"); a.waiter("Any3", "any")
    p = a.new_plot("S-1", "standard")
    t = a.offer_preview(p).text
    assert "Any3" in t and "Large1" not in t and "Small2" not in t
