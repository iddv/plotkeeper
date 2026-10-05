"""Fees.prorate_from=start_date: charge counts from the start-date month (Dec, 1 month = 5.00).

Expected: charge counts from the start-date month (Dec, 1 month = 5.00)
Source: "operator setting fees.prorate_from (repair)"
Runs with the operator setting `fees.prorate_from` = `start_date` (environment variable FEES_PRORATE_FROM).
"""

import pytest as _pytest_setting


@_pytest_setting.fixture(autouse=True)
def _operator_setting(monkeypatch):
    monkeypatch.setenv('FEES_PRORATE_FROM', 'start_date')


from _helpers.driver import *


def test_fees_prorate_start_date_charge_counts_start_date_month_dec_1(monkeypatch):
    monkeypatch.setenv("FEES_PRORATE_FROM", "start_date")
    s = System(monkeypatch, now=utc(2026, 10, 5)); a = s.setup_admin()
    a.open_season(2026); a.set("fees.new_holder_charge", "prorated")
    g = a.waiter("X"); p = a.new_plot("A", "standard"); a.offer(p)
    assert a.outcome(p, "accepted", "2026-12-01").status == 303
    assert [l["amount"] for l in a.ledger(g) if l["kind"] == "charge"] == [500]
