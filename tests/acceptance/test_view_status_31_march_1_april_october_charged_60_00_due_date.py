"""View status on 31 March, then on 1 April and in October (Charged 60.00 with due date 31 March; nothing paid; no activity for months).

Expected: Unpaid on 31 March; Overdue from 1 April onward without any action
Source: "Unpaid: balance = charged, on or before the due date."
"""

import re
import datetime as dt
import os
from _helpers.driver import *


def test_view_status_31_march_1_april_october_charged_60_00_due_date(monkeypatch):
    s = System(monkeypatch, now=utc(2026, 3, 1)); a = s.setup_admin()
    p = a.new_plot("A-1"); g = a.new_gardener("Gina"); a.assign(p, g, "2026-01-01"); a.open_season(2026)
    sid = a.season_id(2026)
    def st():
        t = a.c.get(f"/dues?season={sid}").text
        return t[t.find("Gina"):][:200]
    s.clock.set(utc(2026, 3, 31, 20)); assert "Unpaid" in st() and "Overdue" not in st()
    s.clock.set(utc(2026, 4, 1, 8)); assert "Overdue" in st()
    s.clock.set(utc(2026, 10, 5)); assert "Overdue" in st()
