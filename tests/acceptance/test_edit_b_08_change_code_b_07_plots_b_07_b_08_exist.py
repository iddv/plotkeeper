"""Edit B-08 and change its code to B-07 (Plots B-07 and B-08 exist).

Expected: Refused as a duplicate code; B-08 keeps its code
Source: "A code change is rechecked for uniqueness."
"""

import re
import datetime as dt
import os
from _helpers.driver import *


def test_edit_b_08_change_code_b_07_plots_b_07_b_08_exist(monkeypatch):
    s = System(monkeypatch); a = s.setup_admin()
    a.new_plot("B-07"); p8 = a.new_plot("B-08")
    r = a.edit_plot(p8, code="B-07")
    assert "already exists" in r.text
    assert a.plot(p8)["code"] == "B-08"
