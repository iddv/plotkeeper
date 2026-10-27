"""The operator can mark the session and pre-session cookies Secure (PLOTKEEPER_COOKIE_SECURE).

Expected: with PLOTKEEPER_COOKIE_SECURE=true every Set-Cookie header on /login and on a
successful sign-in carries `Secure`; with it false (the default) none does.
Source: issue "Add an operator option to mark the session cookie Secure behind HTTPS"; SECURITY.md (session cookie flags).
"""

import os, sys, socket, subprocess, time, urllib.request, urllib.parse, re
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from _helpers.security_helpers import Server, REPO


def _restart(s, value):
    s.stop()
    s.env["PLOTKEEPER_COOKIE_SECURE"] = value
    s.log = open(os.path.join(s.dir, "server2.log"), "w")
    s.proc = subprocess.Popen([sys.executable, "-m", "plotkeeper"], cwd=REPO, env=s.env,
                              stdout=s.log, stderr=subprocess.STDOUT)
    for _ in range(100):
        try:
            socket.create_connection(("127.0.0.1", s.port), 0.2).close()
            break
        except OSError:
            time.sleep(0.1)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def _cookie_headers(s):
    """Set-Cookie headers from GET /login and from a sign-in POST."""
    op = urllib.request.build_opener(_NoRedirect)
    try:
        r = op.open(s.base + "/login", timeout=10)
    except urllib.error.HTTPError as e:
        r = e
    headers = r.headers.get_all("Set-Cookie") or []
    cookie = "; ".join(h.split(";")[0] for h in headers)
    body = r.read().decode()
    token = re.search(r'name="_csrf" value="([^"]*)"', body).group(1)
    data = urllib.parse.urlencode({"username": "admin", "password": s.passwords["admin"], "_csrf": token}).encode()
    req = urllib.request.Request(s.base + "/login", data=data, method="POST", headers={"Cookie": cookie})
    try:
        r2 = op.open(req, timeout=10)
    except urllib.error.HTTPError as e:
        r2 = e
    return headers, r2.headers.get_all("Set-Cookie") or []


def test_cookie_secure_option():
    s = Server()
    try:
        _restart(s, "true")
        pre, session = _cookie_headers(s)
        assert pre and session and any(h.startswith("pk_session=") for h in session)
        for h in pre + session:
            assert "Secure" in h.split("; "), f"cookie not marked Secure with PLOTKEEPER_COOKIE_SECURE=true: {h}"
        _restart(s, "false")
        pre, session = _cookie_headers(s)
        assert pre and session
        for h in pre + session:
            assert "Secure" not in h.split("; "), f"cookie marked Secure with the option off: {h}"
    finally:
        s.stop()
