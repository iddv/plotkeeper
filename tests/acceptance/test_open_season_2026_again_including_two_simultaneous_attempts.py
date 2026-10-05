"""Open season 2026 again, including two simultaneous attempts (Season 2026 exists).

Expected: Refused with "Season 2026 already exists"; no assignment gets a second 2026 charge
Source: "Running it twice or concurrently never creates a second charge for the same assignment and season."
"""

import re
import datetime as dt
import os
from _helpers.driver import *


def test_open_season_2026_again_including_two_simultaneous_attempts(monkeypatch):
    import threading
    s = System(monkeypatch); a = s.setup_admin()
    p = a.new_plot("A-1"); a.assign(p, a.new_gardener("G"), "2026-01-01")
    a.open_season(2026)
    r = a.open_season(2026)
    assert "Season 2026 already exists" in r.text + r.msg
    s2 = System(monkeypatch); b = s2.setup_admin(); q = b.new_plot("A-1"); b.assign(q, b.new_gardener("G"), "2026-01-01")
    c2 = s2.client(); c2.cookies = dict(b.c.cookies)
    th = [threading.Thread(target=b.open_season, args=(2026,)) for _ in range(2)]
    [t.start() for t in th]; [t.join() for t in th]
    assert s2.q("SELECT count(*) n FROM ledger WHERE kind='charge'")[0]["n"] == 1
    assert s.q("SELECT count(*) n FROM ledger WHERE kind='charge'")[0]["n"] == 1
