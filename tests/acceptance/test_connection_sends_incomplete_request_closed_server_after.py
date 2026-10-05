"""A connection that sends an incomplete request is closed by the server after a short timeout.

Expected: an idle half-sent request is dropped within 15 seconds, so idle sockets cannot pin threads forever
Source: the security review (SECURITY.md).
"""

import os, socket, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from _helpers.security_helpers import Server


def test_idle_partial_request_is_timed_out():
    s = Server(demo=False)
    try:
        so = socket.create_connection(("127.0.0.1", s.port), 5)
        so.sendall(b"GET / HTTP/1.1\r\nHost: x\r\n")  # never finish the headers
        so.settimeout(20)
        t = time.time()
        try:
            data = so.recv(1024)
        except socket.timeout:
            data = None
        waited = time.time() - t
        so.close()
        assert data is not None and waited < 16, f"server kept the half-sent request open for {waited:.0f}s"
    finally:
        s.stop()
