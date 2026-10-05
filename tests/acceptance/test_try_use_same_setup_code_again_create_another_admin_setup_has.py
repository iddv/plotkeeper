"""Try to use the same setup code again to create another Admin (Setup has already been completed successfully with the printed setup code).

Expected: Refused with "Invalid setup code"; no second account is created
Source: "creates the Admin, invalidates the setup code and signs the operator in"
"""

import re
import datetime as dt
import os
from _helpers.driver import *


def test_try_use_same_setup_code_again_create_another_admin_setup_has(monkeypatch):
    s = System(monkeypatch)
    s.setup_admin()
    cl = s.client()
    r = cl.post("/setup", dict(code=s.code, garden_name="G", currency="EUR", timezone="UTC", username="boss2", password=PW, password2=PW))
    r = cl.follow(r) if r.location else r
    assert s.q("SELECT count(*) n FROM users")[0]["n"] == 1
