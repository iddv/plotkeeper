"""Submit two password entries that differ (Fresh install on the setup page).

Expected: A field error is shown, the other entered values (garden name, currency, time zone, username) are kept, and nothing is created
Source: "Password too short or the two entries differ: field error, other fields kept."
"""

import re
import datetime as dt
import os
from _helpers.driver import *


def test_submit_two_password_entries_differ_fresh_install_setup_page(monkeypatch):
    s = System(monkeypatch)
    cl = s.client()
    r = cl.post("/setup", dict(code=s.code, garden_name="My Garden", currency="GBP", timezone="Europe/London", username="bossy", password=PW, password2=PW+"x"))
    assert 'class="err"' in r.body
    for v in ("My Garden", "GBP", "Europe/London", "bossy"):
        assert f'value="{v}"' in r.body, v
    assert s.q("SELECT count(*) n FROM users")[0]["n"] == 0
