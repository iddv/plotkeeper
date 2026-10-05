"""A negative Content-Length is rejected with 400 before the body is read, so memory stays bounded.

Expected: the server answers 400 at once (or closes the connection) and its memory does not grow with the bytes sent
Source: the security review (SECURITY.md).
"""

import os, socket, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from _helpers.security_helpers import Server


def test_negative_content_length_is_rejected_without_reading_body():
    s = Server(demo=False)
    try:
        before = s.rss_kib()
        so = socket.create_connection(("127.0.0.1", s.port), 5)
        so.sendall(b"POST /login HTTP/1.1\r\nHost: x\r\nContent-Length: -1\r\n\r\n")
        chunk = b"a" * 65536
        try:
            for _ in range(1200):  # ~75 MiB
                so.sendall(chunk)
        except OSError:
            pass  # a correct server may close the connection
        time.sleep(1)
        grown = s.rss_kib() - before
        so.close()
        assert grown < 30 * 1024, f"server memory grew by {grown // 1024} MiB while reading a body with Content-Length: -1"
    finally:
        s.stop()
