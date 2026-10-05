"""Enter a fee of 0, a negative fee, a due date of 1 January 2027, and a due date of 31 December 2026 (Opening season 2026).

Expected: Zero/negative fee and the 2027 due date are field errors; 31 December 2026 is accepted
Source: "Due date outside the season year: field error."
"""

import re
import datetime as dt
import os
from _helpers.driver import *


def test_enter_fee_0_negative_fee_due_date_1_january_2027_due_date_31(monkeypatch):
    s = System(monkeypatch); a = s.setup_admin()
    for kw in (dict(small="0"), dict(small="-5.00"), dict(due="2027-01-01")):
        r = a.open_season(2026, **kw)
        assert r.status != 303 and s.q("SELECT count(*) n FROM seasons")[0]["n"] == 0, kw
    assert a.open_season(2026, due="2026-12-31").status == 303
    assert s.q("SELECT count(*) n FROM seasons")[0]["n"] == 1
