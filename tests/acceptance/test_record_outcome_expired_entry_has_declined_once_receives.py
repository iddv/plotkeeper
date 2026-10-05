"""Record the outcome as expired (An entry has declined once; it receives a second offer which expires).

Expected: This counts as the second decline and the entry is removed with reason "declined twice"
Source: "Recording "expired" is treated like a decline."
"""

import re
import datetime as dt
import os
from _helpers.driver import *


def test_record_outcome_expired_entry_has_declined_once_receives(monkeypatch):
    s = System(monkeypatch); a = s.setup_admin()
    g = a.waiter("P1")
    p = a.new_plot("A-1"); a.offer(p); a.outcome(p, "declined")
    a.offer(p); s.clock.advance(days=20); a.outcome(p, "expired")
    e = a.entry(g)
    assert e["status"] == "removed" and "declined twice" in (e["close_reason"] or "")
