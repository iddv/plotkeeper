"""Resubmit the same form (same token) (A payment form has been submitted once).

Expected: Only one payment entry exists
Source: "Each payment form carries a one-time token, so a resubmitted form saves once."
"""

import re
import datetime as dt
import os
from _helpers.driver import *


def test_resubmit_same_form_same_token_payment_form_has_been(monkeypatch):
    s = System(monkeypatch); a = s.setup_admin()
    p = a.new_plot("A-1"); g = a.new_gardener("G"); a.assign(p, g, "2026-01-01"); a.open_season(2026)
    a.money(g, "payment", "10.00", token="tok-123")
    r = a.money(g, "payment", "10.00", token="tok-123")
    assert len([l for l in a.ledger(g) if l["kind"] == "payment"]) == 1
