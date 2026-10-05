"""Both confirm at nearly the same time (Two users each open the same Available plot and click offer).

Expected: Only one offer is created; the second gets a "changed"/"just offered" message and nothing changes
Source: "The second of two simultaneous actions fails with a "changed since you opened it" message and changes nothing."
"""

import re
import datetime as dt
import os
from _helpers.driver import *


def test_both_confirm_nearly_same_time_two_users_each_open_same(monkeypatch):
    s = System(monkeypatch); a = s.setup_admin()
    a.waiter("W1"); a.waiter("W2"); p = a.new_plot("A-1")
    r1 = a.offer_preview(p); r2 = a.offer_preview(p)
    import re
    v = re.search(r'name="version" value="(\d+)"', r1.body).group(1)
    e1 = re.search(r'name="entry_id" value="(\d+)"', r1.body).group(1)
    x = a.c.post(f"/plots/{p}/offer", dict(version=v, entry_id=e1), referer=f"/plots/{p}")
    y = a.c.post(f"/plots/{p}/offer", dict(version=v, entry_id=e1), referer=f"/plots/{p}")
    assert s.q("SELECT count(*) n FROM offers")[0]["n"] == 1
    assert "changed" in y.msg or "just offered" in y.msg
