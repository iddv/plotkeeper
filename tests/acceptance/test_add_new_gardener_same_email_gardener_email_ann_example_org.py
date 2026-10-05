"""Add a new gardener with the same email (A gardener with email ann@example.org exists).

Expected: A likely-duplicate warning is shown with the option to open the existing record
Source: "The system warns about a likely duplicate (same email or phone) and lets the user open the existing record instead."
"""

import re
import datetime as dt
import os
from _helpers.driver import *


def test_add_new_gardener_same_email_gardener_email_ann_example_org(monkeypatch):
    s = System(monkeypatch); a = s.setup_admin()
    g = a.new_gardener("Ann", "ann@example.org")
    r = a.add_gardener("Annie", "ann@example.org")
    assert r.status != 303
    assert f'/gardeners/{g}"' in r.body and "already exists" in r.text
    assert s.q("SELECT count(*) n FROM gardeners")[0]["n"] == 1
