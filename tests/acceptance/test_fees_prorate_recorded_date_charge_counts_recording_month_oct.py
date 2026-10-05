"""Fees.prorate_from=recorded_date: charge counts from the recording month (Oct, 3 months = 15.00).

Expected: charge counts from the recording month (Oct, 3 months = 15.00)
Source: "operator setting fees.prorate_from (repair)"
Runs with the operator setting `fees.prorate_from` = `recorded_date` (environment variable FEES_PRORATE_FROM).
"""

import pytest as _pytest_setting


@_pytest_setting.fixture(autouse=True)
def _operator_setting(monkeypatch):
    monkeypatch.setenv('FEES_PRORATE_FROM', 'recorded_date')


from _helpers.driver import *


def test_fees_prorate_recorded_date_charge_counts_recording_month_oct(monkeypatch):
    monkeypatch.setenv("FEES_PRORATE_FROM", "recorded_date")
    s = System(monkeypatch, now=utc(2026, 10, 5)); a = s.setup_admin()
    a.open_season(2026); a.set("fees.new_holder_charge", "prorated")
    g = a.waiter("X"); p = a.new_plot("A", "standard"); a.offer(p)
    assert a.outcome(p, "accepted", "2026-12-01").status == 303
    assert [l["amount"] for l in a.ledger(g) if l["kind"] == "charge"] == [1500]
