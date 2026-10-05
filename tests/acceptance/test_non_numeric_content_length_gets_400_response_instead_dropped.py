"""A non-numeric Content-Length gets a 400 response instead of a dropped connection.

Expected: the server answers HTTP 400
Source: the security review (SECURITY.md).
"""

import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from _helpers.security_helpers import Server, raw


def test_bad_content_length_is_400():
    s = Server(demo=False)
    try:
        out = raw(s.port, b"POST /login HTTP/1.1\r\nHost: x\r\nContent-Length: abc\r\nConnection: close\r\n\r\n")
        assert out.startswith(b"HTTP/1.") and out.split(b" ")[1] == b"400", f"got {out[:60]!r}"
    finally:
        s.stop()
