"""View the waiting list (Two entries are created with the identical backdated join timestamp).

Expected: The one created first is ranked ahead
Source: "Entries are ordered by join timestamp, ties by creation sequence."
"""

import re
import datetime as dt
import os
from _helpers.driver import *


def test_view_waiting_list_two_entries_created_identical_backdated(monkeypatch):
    s = System(monkeypatch); a = s.setup_admin()
    a.waiter("First", joined="2025-01-01"); s.clock.advance(minutes=1); a.waiter("Second", joined="2025-01-01")
    assert a.waitlist_names() == ["First", "Second"]
