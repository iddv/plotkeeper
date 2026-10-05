"""Add another plot with code B-07 (A plot with code B-07 exists).

Expected: Refused with "Plot code B-07 already exists"; no plot is created
Source: "Duplicate code: "Plot code B-07 already exists"."
"""

import re
import datetime as dt
import os
from _helpers.driver import *


def test_add_another_plot_code_b_07_plot_code_b_07_exists(monkeypatch):
    s = System(monkeypatch); a = s.setup_admin()
    a.new_plot("B-07")
    r = a.add_plot("B-07")
    assert "Plot code B-07 already exists" in r.text
    assert s.q("SELECT count(*) n FROM plots")[0]["n"] == 1
