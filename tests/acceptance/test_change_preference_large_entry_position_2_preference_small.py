"""Change the preference to "large" (An entry is at position 2 with preference "small").

Expected: The entry stays at position 2
Source: "Change the preference, which keeps the position."
"""

import re
import datetime as dt
import os
from _helpers.driver import *


def test_change_preference_large_entry_position_2_preference_small(monkeypatch):
    s = System(monkeypatch); a = s.setup_admin()
    a.waiter("P1"); g = a.waiter("P2", "small"); a.waiter("P3")
    e = a.entry(g)
    a.c.post(f"/waitlist/{e['id']}/preference", dict(preference="large"), referer="/waitlist")
    assert a.entry(g)["preference"] == "large"
    assert a.waitlist_names() == ["P1", "P2", "P3"]
