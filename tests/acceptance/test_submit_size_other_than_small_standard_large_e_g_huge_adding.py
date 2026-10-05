"""Submit a size other than small, standard or large (e.g. "huge") (Adding a plot).

Expected: Refused with a field error; no plot is created
Source: "Sizes: small, standard, large."
"""

import re
import datetime as dt
import os
from _helpers.driver import *


def test_submit_size_other_than_small_standard_large_e_g_huge_adding(monkeypatch):
    s = System(monkeypatch); a = s.setup_admin()
    r = a.add_plot("H-1", size="huge")
    assert r.status != 303 and s.q("SELECT count(*) n FROM plots")[0]["n"] == 0
