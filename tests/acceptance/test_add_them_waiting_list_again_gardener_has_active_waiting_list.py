"""Add them to the waiting list again (A gardener has an active waiting-list entry at position 3).

Expected: Refused with a message saying they are already on the list at position 3
Source: "Each gardener has at most one active entry."
"""

import re
import datetime as dt
import os
from _helpers.driver import *


def test_add_them_waiting_list_again_gardener_has_active_waiting_list(monkeypatch):
    s = System(monkeypatch); a = s.setup_admin()
    a.waiter("A1"); a.waiter("A2"); g = a.waiter("A3")
    r = a.wait(g, "small")
    assert "position 3" in (r.msg + r.text)
    assert s.q("SELECT count(*) n FROM waitlist")[0]["n"] == 3
