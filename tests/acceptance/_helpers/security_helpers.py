"""Helpers for the security probes: start a real Plotkeeper server on 127.0.0.1 with demo data."""
import os as _os
# These helpers find the repository from their own location. They live in
# tests/acceptance/_helpers/; paths are computed as if they sat one level below
# the repository root.
_HERE = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))), '_helpers', 'security_helpers.py')
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
import http.cookiejar

REPO = os.path.dirname(os.path.dirname(os.path.abspath(_HERE)))


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


class Server:
    def __init__(self, demo=True):
        self.dir = tempfile.mkdtemp(prefix="pksec-")
        self.port = free_port()
        self.env = dict(os.environ, PLOTKEEPER_DATA_DIR=self.dir, PLOTKEEPER_PORT=str(self.port),
                        PLOTKEEPER_HOST="127.0.0.1", PLOTKEEPER_CONFIG=os.path.join(self.dir, "none.conf"))
        self.passwords = {}
        if demo:
            out = subprocess.run([sys.executable, "-m", "plotkeeper", "demo"], cwd=REPO, env=self.env,
                                 capture_output=True, text=True, timeout=60).stdout
            for user, pw in re.findall(r"^\s+(admin|coordinator)\s+(\S+)$", out, re.M):
                self.passwords[user] = pw
        self.log = open(os.path.join(self.dir, "server.log"), "w")
        self.proc = subprocess.Popen([sys.executable, "-m", "plotkeeper"], cwd=REPO, env=self.env,
                                     stdout=self.log, stderr=subprocess.STDOUT)
        for _ in range(100):
            try:
                socket.create_connection(("127.0.0.1", self.port), 0.2).close()
                break
            except OSError:
                time.sleep(0.1)
        self.base = f"http://127.0.0.1:{self.port}"

    def stop(self):
        self.proc.kill()
        self.proc.wait()
        self.log.close()

    def rss_kib(self):
        with open(f"/proc/{self.proc.pid}/status") as fh:
            return int(re.search(r"VmRSS:\s+(\d+)", fh.read()).group(1))

    def alive(self):
        try:
            return urllib.request.urlopen(self.base + "/health", timeout=3).status == 200
        except Exception:
            return False


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


class Client:
    def __init__(self, server):
        self.s = server
        self.jar = http.cookiejar.CookieJar()
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar), NoRedirect)

    def req(self, method, path, data=None, headers=None):
        body = urllib.parse.urlencode(data).encode() if data is not None else None
        r = urllib.request.Request(self.s.base + path, data=body, method=method, headers=headers or {})
        try:
            resp = self.op.open(r, timeout=10)
        except urllib.error.HTTPError as e:
            resp = e
        return resp.status, dict(resp.headers), resp.read().decode("utf-8", "replace")

    def get(self, path):
        return self.req("GET", path)

    def csrf(self, path):
        _, _, body = self.get(path)
        m = re.search(r'name="_csrf" value="([^"]*)"', body)
        return m.group(1) if m else ""

    def post(self, path, data, form_page=None):
        data = dict(data)
        data.setdefault("_csrf", self.csrf(form_page or path))
        return self.req("POST", path, data)

    def login(self, user, pw):
        return self.post("/login", {"username": user, "password": pw}, "/login")


def raw(port, data, timeout=5.0, read=True):
    s = socket.create_connection(("127.0.0.1", port), timeout)
    s.sendall(data)
    out = b""
    if read:
        try:
            while True:
                chunk = s.recv(65536)
                if not chunk:
                    break
                out += chunk
        except socket.timeout:
            pass
    s.close()
    return out
