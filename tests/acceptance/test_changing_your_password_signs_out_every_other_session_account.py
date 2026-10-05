"""Changing your password signs out every other session of that account.

Expected: after a password change, a session opened earlier elsewhere is redirected to the sign-in page
Source: the security review (SECURITY.md).
"""

import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from _helpers.security_helpers import Server, Client


def test_password_change_ends_other_sessions():
    s = Server()
    try:
        pw = s.passwords["admin"]
        stolen, owner = Client(s), Client(s)
        assert stolen.login("admin", pw)[0] == 303
        assert owner.login("admin", pw)[0] == 303
        assert stolen.get("/plots")[0] == 200
        st, h, _ = owner.post("/account/password", {"current": pw, "new": "Brand-new-pass-123", "new2": "Brand-new-pass-123"},
                              "/account/password")
        assert st == 303 and "Password" in h.get("Location", "")
        st, h, _ = stolen.get("/plots")
        assert st == 303 and h.get("Location", "").startswith("/login"), \
            f"old session still works after password change (status {st})"
    finally:
        s.stop()
