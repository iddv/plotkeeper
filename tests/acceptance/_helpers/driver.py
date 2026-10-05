"""Thin helpers over Plotkeeper's real HTTP interface (App.handle, in process).

Time: the build's single time source is plotkeeper.core.utcnow(); Clock replaces it
(the only clock hook the build has)."""
import os as _os
# These helpers find the repository from their own location. They live in
# tests/acceptance/_helpers/; paths are computed as if they sat one level below
# the repository root.
_HERE = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))), '_helpers', 'driver.py')
import datetime as dt
import html
import os
import re
import sqlite3
import sys
import tempfile
from urllib.parse import urlencode, urlparse, parse_qs, unquote_plus

REPO = os.path.dirname(os.path.dirname(os.path.abspath(_HERE)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from plotkeeper import core as C, store  # noqa: E402
from plotkeeper.web import App  # noqa: E402

PW = "correct horse battery"


class Clock:
    def __init__(self, start):
        self.t = start

    def __call__(self):
        return self.t

    def set(self, t):
        self.t = t

    def advance(self, **kw):
        self.t = self.t + dt.timedelta(**kw)


def utc(y, m, d, hh=12, mm=0):
    return dt.datetime(y, m, d, hh, mm, tzinfo=dt.timezone.utc)


def text(h):
    h = re.sub(r"(?s)<(style|script)[^>]*>.*?</\1>", " ", h)
    return html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", h)))


class Resp:
    def __init__(self, r):
        self.status = r.status
        self.headers = r.headers
        self.body = r.body if isinstance(r.body, str) else r.body.decode("utf-8", "replace")
        self.location = next((v for k, v in r.headers if k == "Location"), None)

    @property
    def text(self):
        return text(self.body)

    @property
    def msg(self):
        """ok/err message carried on a redirect."""
        if not self.location:
            return ""
        q = parse_qs(urlparse(self.location).query)
        return (q.get("err") or q.get("ok") or [""])[0]

    def id(self):
        m = re.search(r"/(\d+)(?:[/?]|$)", self.location or "")
        return int(m.group(1)) if m else None


class Client:
    def __init__(self, app):
        self.app, self.cookies, self.last_path = app, {}, "/"

    def _req(self, method, path, body=b"", referer=None):
        h = {}
        if self.cookies:
            h["Cookie"] = "; ".join(f"{k}={v}" for k, v in self.cookies.items())
        if referer:
            h["Referer"] = "http://127.0.0.1:8080" + referer
        r = self.app.handle(method, path, h, body)
        loc = next((v for k, v in r.headers if k == "Location"), "") or ""
        if loc.startswith("/login") and getattr(self, "creds", None) and path != "/login":
            self.cookies.pop("pk_session", None)
            self._req("POST", "/login", urlencode(dict(username=self.creds[0], password=self.creds[1],
                                                          _csrf=self.cookies.get("pk_pre", ""))).encode())
            if method == "POST":
                q = parse_qs(body.decode(), keep_blank_values=True)
                q = {k: v[0] for k, v in q.items()}
                q["_csrf"] = self.csrf()
                body = urlencode(q).encode()
            r = self.app.handle(method, path, dict(h, Cookie="; ".join(f"{k}={v}" for k, v in self.cookies.items())), body)
        for k, v in r.headers:
            if k == "Set-Cookie":
                n, _, val = v.split(";")[0].partition("=")
                self.cookies[n] = val
        return Resp(r)

    def get(self, path):
        r = self._req("GET", path)
        self.last_path = path
        return r

    def follow(self, r):
        while r.location:
            loc = urlparse(r.location)
            r = self.get(loc.path + ("?" + loc.query if loc.query else ""))
        return r

    def csrf(self):
        r = self._req("GET", "/account/password" if "pk_session" in self.cookies else "/login")
        m = re.search(r'name="_csrf" value="([^"]*)"', r.body)
        if m:
            return m.group(1)
        return self.cookies.get("pk_pre", "")

    def post(self, path, data=None, referer=None, csrf=None):
        data = dict(data or {})
        if "_csrf" not in data:
            if not self.cookies:
                self._req("GET", "/login")
            data["_csrf"] = csrf if csrf is not None else self.csrf()
        return self._req("POST", path, urlencode(data).encode(), referer or self.last_path)


class System:
    """A fresh install in a temp dir, plus a clock."""

    def __init__(self, monkeypatch=None, now=None, tz="UTC"):
        self.dir = tempfile.mkdtemp(prefix="pkv_")
        self.path = store.db_path(self.dir)
        self.clock = Clock(now or utc(2026, 5, 10))
        if monkeypatch is not None:
            monkeypatch.setattr(C, "utcnow", self.clock)
        else:
            C.utcnow = self.clock
        conn = store.connect(self.path)
        conn.execute("PRAGMA journal_mode=WAL")
        store.migrate(conn, self.dir, log=lambda *_: None)
        self.code = C.new_setup_code(conn)
        conn.close()
        self.app = App(self.path, "test-secret", "UTC")
        self.tz = tz

    def db(self):
        c = sqlite3.connect(self.path)
        c.row_factory = sqlite3.Row
        return c

    def q(self, sql, *a):
        c = self.db()
        try:
            return [dict(r) for r in c.execute(sql, a).fetchall()]
        finally:
            c.close()

    def client(self):
        return Client(self.app)

    def setup_admin(self, username="boss", password=PW):
        cl = self.client()
        r = cl.post("/setup", dict(code=self.code, garden_name="Test Garden", currency="EUR", timezone=self.tz,
                                   username=username, password=password, password2=password))
        assert r.status == 303, r.text[:500]
        cl.creds = (username, password)
        return Admin(cl, self)

    def login(self, username, password):
        cl = self.client()
        r = cl.post("/login", dict(username=username, password=password))
        return cl, r


class Admin:
    """A signed-in user with flow helpers (all through HTTP)."""

    def __init__(self, cl, sysm):
        self.c, self.s = cl, sysm

    # -- plots
    def add_plot(self, code, size="standard", area="", notes=""):
        r = self.c.post("/plots/new", dict(code=code, size=size, area=area, notes=notes))
        return r

    def plot_id(self, code):
        rows = self.s.q("SELECT id FROM plots WHERE code=?", code)
        return rows[0]["id"] if rows else None

    def plot(self, pid):
        return self.s.q("SELECT * FROM plots WHERE id=?", pid)[0]

    def new_plot(self, code, size="standard"):
        r = self.add_plot(code, size)
        assert r.status == 303, r.text[:400]
        return self.plot_id(code)

    def plot_status(self, pid, action, reason="r"):
        p = self.plot(pid)
        return self.c.post(f"/plots/{pid}/status", dict(version=p["version"], action=action, reason=reason),
                           referer=f"/plots/{pid}")

    def edit_plot(self, pid, version=None, **kw):
        p = self.plot(pid)
        d = dict(code=p["code"], size=p["size"], area=p["area"] or "", notes=p["notes"] or "",
                 version=p["version"] if version is None else version)
        d.update(kw)
        return self.c.post(f"/plots/{pid}/edit", d, referer=f"/plots/{pid}/edit")

    # -- gardeners
    def add_gardener(self, name, email="", phone="", allow_duplicate=None, **kw):
        d = dict(name=name, email=email, phone=phone, address="", notes="")
        if allow_duplicate:
            d["allow_duplicate"] = "1"
        d.update(kw)
        return self.c.post("/gardeners/new", d)

    def new_gardener(self, name, email=None):
        r = self.add_gardener(name, email or f"{name.lower().replace(' ', '.')}@x.org")
        assert r.status == 303, r.text[:400]
        return r.id()

    def wait(self, gid, pref="any", joined=""):
        return self.c.post("/waitlist/new", dict(gardener_id=gid, preference=pref, joined=joined),
                           referer="/waitlist")

    def waiter(self, name, pref="any", joined=""):
        gid = self.new_gardener(name)
        r = self.wait(gid, pref, joined)
        assert r.status == 303 and "err=" not in (r.location or ""), (r.location, r.text[:300])
        return gid

    def entry(self, gid):
        rows = self.s.q("SELECT * FROM waitlist WHERE gardener_id=? ORDER BY id DESC", gid)
        return rows[0] if rows else None

    def waitlist_names(self):
        r = self.c.get("/export/waitlist.csv")
        lines = r.body.strip().splitlines()[1:]
        return [ln.split(",")[1] for ln in lines]

    # -- offers
    def offer_preview(self, pid):
        return self.c.get(f"/plots/{pid}/offer")

    def offer(self, pid, entry_id=None):
        r = self.offer_preview(pid)
        m = re.search(r'name="entry_id" value="(\d+)"', r.body)
        v = re.search(r'name="version" value="(\d+)"', r.body)
        if entry_id is None:
            assert m, r.text[:600]
            entry_id = m.group(1)
        return self.c.post(f"/plots/{pid}/offer", dict(version=v.group(1) if v else self.plot(pid)["version"],
                                                        entry_id=entry_id), referer=f"/plots/{pid}")

    def open_offer(self, pid):
        rows = self.s.q("SELECT * FROM offers WHERE plot_id=? ORDER BY id DESC", pid)
        return rows[0] if rows else None

    def outcome(self, pid, outcome, start_date=""):
        o = self.open_offer(pid)
        return self.c.post(f"/offers/{o['id']}/outcome", dict(outcome=outcome, start_date=start_date),
                           referer=f"/plots/{pid}")

    def release(self, pid, end_date, reason="gave up"):
        return self.c.post(f"/plots/{pid}/release", dict(version=self.plot(pid)["version"], end_date=end_date,
                                                          reason=reason), referer=f"/plots/{pid}")

    def assign(self, pid, gid, start_date, reason="accessibility need"):
        return self.c.post(f"/plots/{pid}/assign", dict(version=self.plot(pid)["version"], gardener_id=gid,
                                                         start_date=start_date, reason=reason),
                           referer=f"/plots/{pid}/assign")

    # -- seasons / money
    def open_season(self, year, due=None, small="40.00", standard="60.00", large="80.00"):
        return self.c.post("/seasons/new", dict(step="confirm", year=year, due_date=due or f"{year}-03-31",
                                                fee_small=small, fee_standard=standard, fee_large=large),
                           referer="/seasons/new")

    def season_id(self, year):
        rows = self.s.q("SELECT id FROM seasons WHERE year=?", year)
        return rows[0]["id"] if rows else None

    def money(self, gid, kind, amount, season_id=None, date="", method="cash", reason="r", token=None,
              reference=""):
        r = self.c.get(f"/gardeners/{gid}/money?kind={kind}")
        if token is None:
            m = re.search(r'name="token" value="([^"]*)"', r.body)
            token = m.group(1) if m else ""
        if season_id is None:
            m = re.search(r'name="season_id"[^>]*>.*?<option value="(\d+)"[^>]*selected', r.body, re.S)
            season_id = m.group(1) if m else ""
        if not date:
            date = self.s.clock().date().isoformat()
        return self.c.post(f"/gardeners/{gid}/money", dict(kind=kind, amount=amount, season_id=season_id,
                                                            date=date, method=method, reason=reason,
                                                            reference=reference, token=token),
                           referer=f"/gardeners/{gid}/money?kind={kind}")

    def ledger(self, gid):
        return self.s.q("SELECT * FROM ledger WHERE gardener_id=? ORDER BY id", gid)

    def settings(self, **changes):
        r = self.c.get("/settings")
        vals = dict(re.findall(r'name="([a-z_.]+)" type="[^"]*" value="([^"]*)"', r.body))
        for sel_name, body in re.findall(r'<select[^>]*name="([a-z_.]+)"[^>]*>(.*?)</select>', r.body, re.S):
            m = re.search(r'<option value="([^"]*)"[^>]*selected', body)
            vals[sel_name] = m.group(1) if m else ""
        vals.pop("_csrf", None)
        vals.update({k.replace("__", "."): v for k, v in changes.items()})
        return self.c.post("/settings", vals, referer="/settings")

    def set(self, key, value):
        r = self.settings(**{key.replace(".", "__"): value})
        assert r.status == 303, r.text[:500]
        return r
