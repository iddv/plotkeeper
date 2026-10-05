"""Seasons.current_rule=most_recently_opened: after opening 2026 then 2025, 2025 is current.

Expected: after opening 2026 then 2025, 2025 is current
Source: "operator setting seasons.current_rule (repair)"
Runs with the operator setting `seasons.current_rule` = `most_recently_opened` (environment variable SEASONS_CURRENT_RULE).
"""

import pytest as _pytest_setting


@_pytest_setting.fixture(autouse=True)
def _operator_setting(monkeypatch):
    monkeypatch.setenv('SEASONS_CURRENT_RULE', 'most_recently_opened')


from _helpers.driver import *


def test_seasons_current_rule_most_recently_opened_after_opening_2026(monkeypatch):
    monkeypatch.setenv("SEASONS_CURRENT_RULE", "most_recently_opened")
    s = System(monkeypatch); a = s.setup_admin()
    assert a.open_season(2026).status == 303
    assert a.open_season(2025, due="2025-03-31").status == 303
    t = a.c.get("/seasons").text
    assert "2025 (current)" in t, t[-400:]
    d = a.c.get("/dues").text
    assert "2025" in d[d.find("Dues"):][:400]
