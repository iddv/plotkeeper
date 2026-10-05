"""Record Declined (decline_policy = keep_place; entry at position 1 receives an offer).

Expected: The plot returns to Available and the entry is still at position 1
Source: "Whether a person who declines an offer keeps their position or goes to the end of the list."
"""

import re
import datetime as dt
import os
from _helpers.driver import *


def test_record_declined_decline_policy_keep_place_entry_position_1(monkeypatch):
    s = System(monkeypatch); a = s.setup_admin()
    g = a.waiter("P1"); a.waiter("P2")
    p = a.new_plot("A-1"); a.offer(p); a.outcome(p, "declined")
    assert a.plot(p)["status"] == "available"
    assert a.waitlist_names() == ["P1", "P2"]
