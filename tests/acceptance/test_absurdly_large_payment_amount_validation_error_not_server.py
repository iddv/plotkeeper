"""An absurdly large payment amount is a validation error, not a server crash.

Expected: field error (400/200 form with error), nothing saved; not HTTP 500
Source: ""Validation: every form shows field-level errors in plain words and keeps the entered values.""
"""

from _helpers.driver import *


def test_absurdly_large_payment_amount_validation_error_not_server(monkeypatch):
    s = System(monkeypatch); a = s.setup_admin()
    p = a.new_plot("A"); g = a.new_gardener("H"); a.assign(p, g, "2026-01-01"); a.open_season(2026)
    a.set("payments.overpayment", "credit")
    r = a.money(g, "payment", "99999999999999999999.00")
    assert r.status != 500, r.text[-200:]
    assert [l["kind"] for l in a.ledger(g)] == ["charge"]
