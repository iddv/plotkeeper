"""A cross-site POST without the CSRF token is refused and changes nothing.

Expected: 403 for a state-changing POST lacking _csrf, even with a valid session cookie and a foreign Origin
Source: the security review (SECURITY.md).
"""

import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from _helpers.security_helpers import Server, Client


def test_csrf_required():
    s = Server()
    try:
        c = Client(s)
        c.login("admin", s.passwords["admin"])
        st, _, _ = c.req("POST", "/plots/new", {"code": "CSRF-1", "size": "small"}, {"Origin": "http://evil.example"})
        assert st == 403
        assert "Nothing to show" in c.get("/plots?q=CSRF-1")[2]
    finally:
        s.stop()
