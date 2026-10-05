"""Offer to next in line (Only entries preferring large exist; a small plot is Available).

Expected: Message "No one on the waiting list matches a small plot"; nothing changes
Source: "No matching entry: "No one on the waiting list matches a small plot"."
"""

import re
import datetime as dt
import os
from _helpers.driver import *


def test_offer_next_line_only_entries_preferring_large_exist_small(monkeypatch):
    s = System(monkeypatch); a = s.setup_admin()
    a.waiter("L1", "large"); p = a.new_plot("S-1", "small")
    r = a.offer_preview(p); t = r.text + r.msg
    assert "No one on the waiting list matches a small plot" in t
    assert a.plot(p)["status"] == "available"
