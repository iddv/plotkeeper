"""A payments-ledger export for a range with no payments is a CSV with headers only.

Expected: exactly one line (the header)
Source: ""Empty result: a CSV with headers only.""
"""

from _helpers.driver import *


def test_payments_ledger_export_range_no_payments_csv_headers_only(monkeypatch):
    s = System(monkeypatch); a = s.setup_admin()
    body = a.c.get("/export/payments.csv?from=2026-06-01&to=2026-06-30").body
    assert len(body.strip().splitlines()) == 1, body
