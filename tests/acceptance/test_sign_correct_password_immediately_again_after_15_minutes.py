"""Sign in with the correct password immediately, then again after 15 minutes (A user has 5 failed sign-ins in a row).

Expected: Refused while locked; accepted after 15 minutes
Source: "Sign-in after 5 failed attempts: locked for 15 minutes (default)."
"""

import re
import datetime as dt
import os
from _helpers.driver import *


def test_sign_correct_password_immediately_again_after_15_minutes(monkeypatch):
    s = System(monkeypatch); a = s.setup_admin()
    for _ in range(5): s.login("boss", "wrong password!")
    cl, r = s.login("boss", PW)
    assert r.status != 303 or "pk_session" not in cl.cookies
    s.clock.advance(minutes=15, seconds=1)
    cl, r = s.login("boss", PW)
    assert r.status == 303 and "pk_session" in cl.cookies
