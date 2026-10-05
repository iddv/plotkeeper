"""Release the plot (release_with_balance = block; holder owes 30.00 for 2026).

Expected: Blocked with "Gardener owes 30.00 for 2026; record payment or adjustment first"; under allow, the release succeeds and the 30.00 charge remains on the gardener
Source: "Release with an outstanding balance when plots.release_with_balance = block: "Gardener owes 30.00 for 2026; record payment or adjustment first"."
"""

import re
import datetime as dt
import os
from _helpers.driver import *


def test_release_plot_release_balance_block_holder_owes_30_00_2026(monkeypatch):
    s = System(monkeypatch); a = s.setup_admin()
    p = a.new_plot("A-1"); g = a.new_gardener("H"); a.assign(p, g, "2026-01-01")
    a.open_season(2026); sid = a.season_id(2026)
    a.money(g, "payment", "30.00", season_id=sid)
    a.set("plots.release_with_balance", "block")
    r = a.release(p, "2026-05-10")
    assert "owes 30.00 for 2026; record payment or adjustment first" in r.msg
    assert a.plot(p)["status"] == "occupied"
    a.set("plots.release_with_balance", "allow")
    assert a.release(p, "2026-05-10").status == 303 and a.plot(p)["status"] == "available"
    assert len([l for l in a.ledger(g) if l["kind"] == "charge"]) == 1
