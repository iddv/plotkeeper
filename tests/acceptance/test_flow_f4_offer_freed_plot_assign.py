"""Flow F4: Offer a freed plot and assign it.

Flow: F4 in SCOPE.md.
"""

import re
import os
from _helpers.driver import *


def test_flow_f4_offer_freed_plot_assign(monkeypatch):
    s = System(monkeypatch); a = s.setup_admin()
    a.open_season(2026)
    p = a.new_plot("S-1", "small"); h = a.new_gardener("Holder"); a.assign(p, h, "2026-01-01")
    a.waiter("Large", "large"); g = a.waiter("Small", "small"); g2 = a.waiter("Any", "any")
    assert a.release(p, "2026-05-10", "moved").status == 303 and a.plot(p)["status"] == "available"
    t = a.offer_preview(p).text
    assert "Small" in t and "small@x.org" in t
    import re
    r1 = a.offer_preview(p)
    v = re.search(r'name="version" value="(\d+)"', r1.body).group(1); eid = re.search(r'name="entry_id" value="(\d+)"', r1.body).group(1)
    assert a.c.post(f"/plots/{p}/offer", dict(version=v, entry_id=eid), referer=f"/plots/{p}").status == 303
    y = a.c.post(f"/plots/{p}/offer", dict(version=v, entry_id=eid), referer=f"/plots/{p}")
    assert s.q("SELECT count(*) n FROM offers")[0]["n"] == 1
    a.outcome(p, "declined"); assert a.plot(p)["status"] == "available" and a.waitlist_names()[1] == "Small"
    a.offer(p); a.outcome(p, "accepted", "2026-05-11")
    assert a.plot(p)["status"] == "occupied"
    assert [l["amount"] for l in a.ledger(g) if l["kind"] == "charge"] == [4000]
