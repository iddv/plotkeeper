"""Enter an 11-character password (both entries the same), then retry with a 12-character password (Fresh install on the setup page with the correct code).

Expected: The 11-character password gets a field error with the other fields kept; the 12-character password is accepted and the Admin is created and signed in
Source: "a password (min 12 characters), entered twice"
"""

import re
import datetime as dt
import os
from _helpers.driver import *


def test_enter_11_character_password_both_entries_same_retry_12(monkeypatch):
    s = System(monkeypatch)
    cl = s.client()
    r = cl.post("/setup", dict(code=s.code, garden_name="G", currency="EUR", timezone="UTC", username="boss", password="a"*11, password2="a"*11))
    assert r.status != 303 and s.q("SELECT count(*) n FROM users")[0]["n"] == 0
    assert 'class="err"' in r.body
    r = cl.post("/setup", dict(code=s.code, garden_name="G", currency="EUR", timezone="UTC", username="boss", password="a"*12, password2="a"*12))
    assert r.status == 303 and s.q("SELECT count(*) n FROM users")[0]["n"] == 1
