"""View the waiting list (Entries A (joined today) and B (added later but backdated to last year) are on the list).

Expected: B is shown before A, ordered by join date, with days waiting reflecting the backdated date
Source: "Entries are ordered by join timestamp, ties by creation sequence."
"""

import re
import datetime as dt
import os
from _helpers.driver import *


def test_view_waiting_list_entries_joined_today_b_added_later_but(monkeypatch):
    s = System(monkeypatch); a = s.setup_admin()
    a.waiter("Alpha"); a.waiter("Beta", joined="2025-05-10")
    assert a.waitlist_names() == ["Beta", "Alpha"]
    t = a.c.get("/waitlist").text
    assert t.find("Beta") < t.find("Alpha") and "365" in t
