"""Accept an offer in October, and another in January (new_holder_charge = prorated; standard fee 60.00; a season is current).

Expected: October charge is 15.00 (3 months); January charge is the full 60.00
Source: "Remaining months count the acceptance month through December."
"""

import re
import datetime as dt
import os
from _helpers.driver import *


def test_accept_offer_october_another_january_new_holder_charge(monkeypatch):
    s = System(monkeypatch, now=utc(2026, 1, 10)); a = s.setup_admin()
    a.open_season(2026); a.set("fees.new_holder_charge", "prorated")
    g1 = a.waiter("Jan"); p1 = a.new_plot("A-1"); a.offer(p1); a.outcome(p1, "accepted", "2026-01-10")
    s.clock.set(utc(2026, 10, 5))
    g2 = a.waiter("Oct"); p2 = a.new_plot("A-2"); a.offer(p2); a.outcome(p2, "accepted", "2026-10-05")
    assert [l["amount"] for l in a.ledger(g1) if l["kind"] == "charge"] == [6000]
    assert [l["amount"] for l in a.ledger(g2) if l["kind"] == "charge"] == [1500]
