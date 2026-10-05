"""Offers.valid_on_expiry_date=true: on the expiry date the offer is not yet Expired.

Expected: on the expiry date the offer is not yet Expired
Source: "operator setting offers.valid_on_expiry_date (repair)"
Runs with the operator setting `offers.valid_on_expiry_date` = `true` (environment variable OFFERS_VALID_ON_EXPIRY_DATE).
"""

import pytest as _pytest_setting


@_pytest_setting.fixture(autouse=True)
def _operator_setting(monkeypatch):
    monkeypatch.setenv('OFFERS_VALID_ON_EXPIRY_DATE', 'true')


from _helpers.driver import *


def test_offers_valid_expiry_date_true_expiry_date_offer_not_yet(monkeypatch):
    monkeypatch.setenv("OFFERS_VALID_ON_EXPIRY_DATE", "true")
    s = System(monkeypatch); a = s.setup_admin()
    a.waiter("W"); p = a.new_plot("A"); a.offer(p)
    assert a.open_offer(p)["expires_on"] == "2026-05-24"
    s.clock.set(utc(2026, 5, 24, 10))
    t = a.c.get("/").text
    assert "0 expired" in t, t[:600]
    s.clock.set(utc(2026, 5, 25, 10))
    assert "1 expired" in a.c.get("/").text
