"""Submit a name with neither email nor phone (Adding a gardener).

Expected: Field error; no gardener is created
Source: "No contact details: field error."
"""

import re
import datetime as dt
import os
from _helpers.driver import *


def test_submit_name_neither_email_nor_phone_adding_gardener(monkeypatch):
    s = System(monkeypatch); a = s.setup_admin()
    r = a.add_gardener("Nobody")
    assert r.status != 303 and s.q("SELECT count(*) n FROM gardeners")[0]["n"] == 0
