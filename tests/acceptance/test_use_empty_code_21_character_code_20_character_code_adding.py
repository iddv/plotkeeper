"""Use an empty code, a 21-character code, and a 20-character code (Adding a plot).

Expected: Empty and 21-character codes are refused with a field error; the 20-character code is accepted and the plot saved as Available
Source: "Code: unique, 1–20 characters."
"""

import re
import datetime as dt
import os
from _helpers.driver import *


def test_use_empty_code_21_character_code_20_character_code_adding(monkeypatch):
    s = System(monkeypatch); a = s.setup_admin()
    r = a.add_plot(""); assert r.status != 303
    r = a.add_plot("X"*21); assert r.status != 303
    assert s.q("SELECT count(*) n FROM plots")[0]["n"] == 0
    r = a.add_plot("Y"*20); assert r.status == 303
    assert a.plot(a.plot_id("Y"*20))["status"] == "available"
