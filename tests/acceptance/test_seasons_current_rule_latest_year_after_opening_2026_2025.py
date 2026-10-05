"""Seasons.current_rule=latest_year: after opening 2026 then 2025, 2026 is current.

Expected: after opening 2026 then 2025, 2026 is current
Source: "operator setting seasons.current_rule (repair)"
Runs with the operator setting `seasons.current_rule` = `latest_year` (environment variable SEASONS_CURRENT_RULE).
"""

import pytest as _pytest_setting


@_pytest_setting.fixture(autouse=True)
def _operator_setting(monkeypatch):
    monkeypatch.setenv('SEASONS_CURRENT_RULE', 'latest_year')


from _helpers.driver import *


def test_seasons_current_rule_latest_year_after_opening_2026_2025(monkeypatch):
    monkeypatch.setenv("SEASONS_CURRENT_RULE", "latest_year")
    s = System(monkeypatch); a = s.setup_admin()
    assert a.open_season(2026).status == 303
    assert a.open_season(2025, due="2025-03-31").status == 303
    t = a.c.get("/seasons").text
    assert "2026 (current)" in t, t[-400:]
    d = a.c.get("/dues").text
    assert "2026" in d[d.find("Dues"):][:400]
