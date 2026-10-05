"""Assign.direct_with_active_entry=refused: direct assign refused; plot stays Available, entry stays active.

Expected: direct assign refused; plot stays Available, entry stays active
Source: "operator setting assign.direct_with_active_entry (repair)"
Runs with the operator setting `assign.direct_with_active_entry` = `refused` (environment variable ASSIGN_DIRECT_WITH_ACTIVE_ENTRY).
"""

import pytest as _pytest_setting


@_pytest_setting.fixture(autouse=True)
def _operator_setting(monkeypatch):
    monkeypatch.setenv('ASSIGN_DIRECT_WITH_ACTIVE_ENTRY', 'refused')


from _helpers.driver import *


def test_assign_direct_active_entry_refused_direct_assign_refused(monkeypatch):
    monkeypatch.setenv("ASSIGN_DIRECT_WITH_ACTIVE_ENTRY", "refused")
    s = System(monkeypatch); a = s.setup_admin()
    g = a.waiter("W"); p = a.new_plot("A")
    r = a.assign(p, g, "2026-05-10")
    assert a.plot(p)["status"] == "available"
    assert a.entry(g)["status"] == "active"
    assert s.q("SELECT count(*) n FROM assignments")[0]["n"] == 0
