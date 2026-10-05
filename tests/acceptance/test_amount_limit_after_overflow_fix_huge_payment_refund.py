"""Amount limit after the overflow fix: huge payment/refund/adjustment/fee amounts are field errors, never 500.

Expected: no 500 anywhere; oversize amounts saved nowhere; normal large amounts still saved
Source: ""Validation: every form shows field-level errors in plain words and keeps the entered values.""
"""

from _helpers.driver import *


def test_amount_limit_after_overflow_fix_huge_payment_refund(monkeypatch):
    s = System(monkeypatch); a = s.setup_admin()
    p = a.new_plot("A"); g = a.new_gardener("H"); a.assign(p, g, "2026-01-01"); a.open_season(2026)
    a.set("payments.overpayment", "credit")
    for kind, amt in (("payment", "99999999999999999999.00"), ("payment", "100000000.01"),
                      ("refund", "99999999999999999999"), ("adjustment", "-99999999999999999999.00"),
                      ("adjustment", "99999999999999999999")):
        r = a.money(g, kind, amt, reason="x")
        assert r.status not in (303, 500), (kind, amt, r.status)
    assert [l["kind"] for l in a.ledger(g)] == ["charge"]
    assert a.money(g, "payment", "999999.99").status == 303
    assert a.open_season(2027, due="2027-03-31", small="99999999999999999999.00").status not in (303, 500)
    assert a.settings(fee__small="99999999999999999999.00").status not in (303, 500)
    body = a.c.get("/export/payments.csv?from=2026-05-01&to=2026-05-31").body
    assert "TOTAL" in body and "999999.99" in body
