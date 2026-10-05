"""Open the plot detail page (A plot is edited (size and notes changed)).

Expected: The dated history shows the change
Source: "Changes are written to the plot's history."
"""

import re
import datetime as dt
import os
from _helpers.driver import *


def test_open_plot_detail_page_plot_edited_size_notes_changed(monkeypatch):
    s = System(monkeypatch); a = s.setup_admin()
    p = a.new_plot("E-1")
    s.clock.advance(days=1)
    assert a.edit_plot(p, size="large", notes="raised beds").status == 303
    d = a.c.get(f"/plots/{p}").text
    h = d[d.find("History"):]
    assert "2026-05-11" in h and "size" in h
