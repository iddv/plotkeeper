"""View the dashboard (Setup has just been completed).

Expected: It shows zero plots, an empty waiting list and no season
Source: "The operator sees the dashboard with zero plots, an empty waiting list and no season."
"""

import re
import datetime as dt
import os
from _helpers.driver import *


def test_view_dashboard_setup_has_just_been_completed(monkeypatch):
    s = System(monkeypatch)
    a = s.setup_admin()
    t = a.c.get("/").text
    assert "No plots yet" in t and "Nobody is waiting" in t and "No season yet" in t
