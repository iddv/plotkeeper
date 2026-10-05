"""Assign.direct_with_active_entry=close_entry: direct assign succeeds; entry closes as placed.

Expected: direct assign succeeds; entry closes as placed
Source: "operator setting assign.direct_with_active_entry (repair)"
Runs with the operator setting `assign.direct_with_active_entry` = `close_entry` (environment variable ASSIGN_DIRECT_WITH_ACTIVE_ENTRY).
"""

import pytest as _pytest_setting


@_pytest_setting.fixture(autouse=True)
def _operator_setting(monkeypatch):
    monkeypatch.setenv('ASSIGN_DIRECT_WITH_ACTIVE_ENTRY', 'close_entry')


from _helpers.driver import *


def test_assign_direct_active_entry_close_entry_direct_assign(monkeypatch):
    monkeypatch.setenv("ASSIGN_DIRECT_WITH_ACTIVE_ENTRY", "close_entry")
    s = System(monkeypatch); a = s.setup_admin()
    g = a.waiter("W"); p = a.new_plot("A")
    r = a.assign(p, g, "2026-05-10")
    assert a.plot(p)["status"] == "occupied"
    assert a.entry(g)["status"] == "placed"
