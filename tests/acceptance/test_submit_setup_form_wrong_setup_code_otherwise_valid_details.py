"""Submit the setup form with a wrong setup code and otherwise valid details (Fresh install with no accounts; the operator is on the setup page).

Expected: The error "Invalid setup code" is shown and no account or garden settings are created
Source: "Wrong or used setup code: "Invalid setup code", and nothing is created."
"""

import re
import datetime as dt
import os
from _helpers.driver import *


def test_submit_setup_form_wrong_setup_code_otherwise_valid_details(monkeypatch):
    s = System(monkeypatch)
    cl = s.client()
    r = cl.post("/setup", dict(code="WRONG-CODE", garden_name="G", currency="EUR", timezone="UTC", username="boss", password=PW, password2=PW))
    assert "Invalid setup code" in r.text
    assert s.q("SELECT count(*) n FROM users")[0]["n"] == 0
