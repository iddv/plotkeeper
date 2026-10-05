"""HTTP layer: routing, sessions, CSRF, role checks and HTML pages (stdlib only)."""
import csv
import datetime as dt
import hashlib
import hmac
import html
import io
import json
import logging
import re
import secrets
import traceback
from http.cookies import SimpleCookie
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlencode, urlparse

from . import core as C
from .store import connect

log = logging.getLogger("plotkeeper")
e = lambda s: html.escape("" if s is None else str(s), quote=True)  # noqa: E731
money = C.fmt_money


class Response:
    def __init__(self, body="", status=200, ctype="text/html; charset=utf-8", headers=None):
        self.body = body.encode() if isinstance(body, str) else body
        self.status, self.headers = status, [("Content-Type", ctype)] + (headers or [])


def redirect(url, ok=None, err=None):
    if ok or err:
        url += ("&" if "?" in url else "?") + urlencode({"ok": ok} if ok else {"err": err})
    return Response("", 303, headers=[("Location", url)])


class Request:
    def __init__(self, app, method, path, query, form, cookies):
        self.app, self.method, self.path, self.query, self.form, self.cookies = app, method, path, query, form, cookies
        self.conn, self.user, self.params, self.set_cookies = None, None, (), []

    def q(self, k, default=""):
        return self.query.get(k, [default])[0]

    def f(self, k, default=""):
        return self.form.get(k, [default])[0]

    @property
    def csrf(self):
        return self.user["csrf"] if self.user else self.cookies.get("pk_pre", "")

    @property
    def is_admin(self):
        return bool(self.user) and self.user["role"] == "admin"


ROUTES = []


def route(method, pattern, role="any"):
    """role: None = public, 'any' = signed-in staff, 'admin' = Admin only."""
    def deco(fn):
        ROUTES.append((method, re.compile("^" + pattern + "$"), fn, role))
        return fn
    return deco


# ------------------------------------------------------------------ HTML helpers

CSS = """
*{box-sizing:border-box}body{font:15px/1.45 system-ui,sans-serif;margin:0;color:#1d2a1d;background:#f6f8f4}
header{background:#2f5d34;color:#fff;padding:.5rem 1rem;display:flex;gap:1rem;align-items:center;flex-wrap:wrap}
header a{color:#fff;text-decoration:none;margin-right:.6rem}header .g{font-weight:700;margin-right:1.2rem}
header .r{margin-left:auto}main{max-width:1150px;margin:1rem auto;padding:0 1rem}
table{border-collapse:collapse;width:100%;background:#fff;margin:.5rem 0 1rem}
th,td{border-bottom:1px solid #dde4d9;padding:.35rem .5rem;text-align:left;vertical-align:top}
th{background:#e8eee4}td.n,th.n{text-align:right;font-variant-numeric:tabular-nums}
.card{background:#fff;border:1px solid #dde4d9;border-radius:6px;padding:.8rem 1rem;margin:.6rem 0}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:.8rem}
label{display:block;margin:.4rem 0 .1rem;font-weight:600}input,select,textarea{font:inherit;padding:.3rem;
border:1px solid #9aa79a;border-radius:4px;max-width:100%}textarea{width:100%}
.err{color:#a01818;font-size:.9em}.msg{padding:.5rem .8rem;border-radius:4px;margin:.5rem 0}
.ok{background:#dff0d8}.bad{background:#f8d7da}button,.btn{background:#2f5d34;color:#fff;border:0;
border-radius:4px;padding:.35rem .8rem;font:inherit;cursor:pointer;text-decoration:none;display:inline-block}
button.sec,.btn.sec{background:#6c7a6c}button.warn{background:#a04018}form.inline{display:inline}
.tag{display:inline-block;padding:0 .4rem;border-radius:3px;background:#e8eee4;font-size:.85em}
.Overdue,.expired{background:#f8d7da}.Paid{background:#dff0d8}.In.credit{background:#d9e8f8}
.hint{color:#5b6b5b;font-style:italic}.row{display:flex;gap:1rem;flex-wrap:wrap;align-items:flex-end}
.muted{color:#6c7a6c}s{color:#888}
"""


def layout(req, title, body):
    nav = ""
    if req.user:
        links = [("/", "Dashboard"), ("/plots", "Plots"), ("/gardeners", "Gardeners"),
                 ("/waitlist", "Waiting list"), ("/dues", "Dues"), ("/seasons", "Seasons")]
        if req.is_admin:
            links += [("/users", "Users"), ("/settings", "Settings"), ("/audit", "Audit log")]
        nav = "".join(f'<a href="{u}">{t}</a>' for u, t in links)
        nav += (f'<span class="r">{e(req.user["username"])} ({req.user["role"]}) · '
                f'<a href="/account/password">Password</a>'
                f'<form class="inline" method="post" action="/logout">{csrf_field(req)}'
                f'<button class="sec">Sign out</button></form></span>')
    garden = C.get_setting(req.conn, "garden_name") if req.conn else "Plotkeeper"
    flash = ""
    if req.q("ok"):
        flash += f'<div class="msg ok">{e(req.q("ok"))}</div>'
    if req.q("err"):
        flash += f'<div class="msg bad">{e(req.q("err"))}</div>'
    return Response(f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{e(title)} · Plotkeeper</title>
<style>{CSS}</style></head><body><header><span class="g">🌱 {e(garden)}</span>{nav}</header>
<main><h1>{e(title)}</h1>{flash}{body}</main></body></html>""")


def csrf_field(req):
    return f'<input type="hidden" name="_csrf" value="{e(req.csrf)}">'


def error_box(msg):
    return f'<div class="msg bad">{e(msg)}</div>' if msg else ""


def inp(name, label, vals, errs, type="text", **attrs):
    extra = " ".join(f'{k.rstrip("_")}="{e(v)}"' for k, v in attrs.items())
    v = "" if type == "password" else vals.get(name, "")
    err = f'<div class="err">{e(errs[name])}</div>' if name in errs else ""
    return f'<label for="{name}">{e(label)}</label><input id="{name}" name="{name}" type="{type}" value="{e(v)}" {extra}>{err}'


def sel(name, label, options, vals, errs, blank=None):
    cur = str(vals.get(name, ""))
    opts = (f'<option value="">{e(blank)}</option>' if blank is not None else "")
    for o in options:
        val, text = (o, o) if not isinstance(o, tuple) else o
        opts += f'<option value="{e(val)}"{" selected" if str(val) == cur else ""}>{e(text)}</option>'
    err = f'<div class="err">{e(errs[name])}</div>' if name in errs else ""
    lab = f'<label for="{name}">{e(label)}</label>' if label else ""
    return f'{lab}<select id="{name}" name="{name}">{opts}</select>{err}'


def area(name, label, vals, errs):
    err = f'<div class="err">{e(errs[name])}</div>' if name in errs else ""
    return f'<label for="{name}">{e(label)}</label><textarea id="{name}" name="{name}" rows="3">{e(vals.get(name, ""))}</textarea>{err}'


def form(req, action, inner, button="Save", cls=""):
    return (f'<form method="post" action="{action}" class="{cls}">{csrf_field(req)}{inner}'
            f'<p><button>{e(button)}</button></p></form>')


def button_form(req, action, label, fields="", cls=""):
    return (f'<form class="inline" method="post" action="{action}">{csrf_field(req)}{fields}'
            f'<button class="{cls}">{e(label)}</button></form>')


def table(headers, rows, numeric=()):
    th = "".join(f'<th class="{"n" if i in numeric else ""}">{h}</th>' for i, h in enumerate(headers))
    body = "".join("<tr>" + "".join(f'<td class="{"n" if i in numeric else ""}">{c}</td>'
                                    for i, c in enumerate(r)) + "</tr>" for r in rows)
    if not rows:
        body = f'<tr><td colspan="{len(headers)}" class="hint">Nothing to show.</td></tr>'
    return f"<table><tr>{th}</tr>{body}</table>"


def cur(req):
    return e(C.get_setting(req.conn, "currency"))


def size_opts():
    return [(s, s.capitalize()) for s in C.SIZES]


def plot_status_tag(s):
    return f'<span class="tag">{C.status_label(s)}</span>'


def form_vals(req):
    return {k: v[0] for k, v in req.form.items()}


# ------------------------------------------------------------------ setup & auth

@route("GET", "/setup", None)
def setup_page(req, vals=None, errs=None, msg=None):
    if C.has_users(req.conn):
        return redirect("/login")
    vals = vals or {"currency": "EUR", "timezone": req.app.default_tz}
    errs = errs or {}
    body = error_box(msg) + '<div class="card"><p>Enter the setup code printed in the terminal where Plotkeeper started.</p>' + form(
        req, "/setup",
        inp("code", "Setup code", vals, errs, required="required", autocomplete="off") +
        inp("garden_name", "Garden name", vals, errs, required="required") +
        inp("currency", "Currency code", vals, errs, maxlength="3") +
        inp("timezone", "Time zone", vals, errs) +
        inp("username", "Admin username", vals, errs, required="required") +
        inp("password", "Password (at least 12 characters)", vals, errs, type="password") +
        inp("password2", "Password again", vals, errs, type="password"), "Create Admin") + "</div>"
    return layout(req, "Set up Plotkeeper", body)


@route("POST", "/setup", None)
def setup_post(req):
    v = form_vals(req)
    try:
        uid = C.setup(req.conn, v.get("code"), v.get("garden_name"), v.get("currency"), v.get("timezone"),
                      v.get("username"), v.get("password"), v.get("password2"))
    except C.FieldErrors as x:
        return setup_page(req, v, x.errors)
    except C.DomainError as x:
        return setup_page(req, v, {}, str(x))
    req.app.login(req, uid)
    return redirect("/", ok="Welcome! Your garden is set up.")


@route("GET", "/login", None)
def login_page(req, msg=None, username=""):
    if not C.has_users(req.conn):
        return redirect("/setup")
    body = error_box(msg) + '<div class="card">' + form(
        req, "/login", inp("username", "Username", {"username": username}, {}, autofocus="autofocus") +
        inp("password", "Password", {}, {}, type="password"), "Sign in") + "</div>"
    return layout(req, "Sign in", body)


@route("POST", "/login", None)
def login_post(req):
    try:
        u = C.authenticate(req.conn, req.f("username"), req.f("password"))
    except C.DomainError as x:
        return login_page(req, str(x), req.f("username"))
    req.app.login(req, u["id"])
    return redirect("/account/password" if u["must_change"] else "/")


@route("POST", "/logout")
def logout(req):
    C.end_session(req.conn, req.user["token"])
    req.set_cookies.append("pk_session=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax")
    return redirect("/login")


@route("GET", "/account/password")
def password_page(req, errs=None):
    note = ('<div class="msg bad">You must choose a new password before continuing.</div>'
            if req.user["must_change"] else "")
    errs = errs or {}
    return layout(req, "Change password", note + '<div class="card">' + form(
        req, "/account/password",
        inp("current", "Current (or temporary) password", {}, errs, type="password") +
        inp("new", "New password (at least 12 characters)", {}, errs, type="password") +
        inp("new2", "New password again", {}, errs, type="password"), "Change password") + "</div>")


@route("POST", "/account/password")
def password_post(req):
    try:
        C.change_password(req.conn, req.user["id"], req.f("current"), req.f("new"), req.f("new2"),
                           keep_token=req.user["token"])
    except C.FieldErrors as x:
        return password_page(req, x.errors)
    return redirect("/", ok="Password changed")


# ------------------------------------------------------------------ dashboard

@route("GET", "/")
def dashboard(req):
    conn = req.conn
    counts = C.plot_counts(conn)
    wl = C.waiting_list(conn)
    offers = C.open_offers(conn)
    season = C.current_season(conn)
    total = sum(v for k, v in counts.items() if k != "retired")
    plots_card = (f'<div class="card"><h3>Plots</h3>' +
                  ("".join(f'<div><a href="/plots?status={k}">{C.status_label(k)}</a>: {v}</div>'
                           for k, v in counts.items()) if total or counts["retired"] else
                   '<p class="hint">No plots yet. <a href="/plots/new">Add the first plot</a>.</p>') + "</div>")
    wl_card = (f'<div class="card"><h3>Waiting list</h3><p><a href="/waitlist">{len(wl)} waiting</a></p>' +
               ("" if wl else '<p class="hint">Nobody is waiting. <a href="/gardeners/new">Add a gardener</a>, '
                              'then add them to the list.</p>') + "</div>")
    off_rows = "".join(f'<div class="{"expired" if o["expired"] else ""}"><a href="/plots/{o["plot_id"]}">'
                       f'{e(o["code"])}</a> → {e(o["name"])} — '
                       f'{"<b>Expired</b> " if o["expired"] else "expires "}{o["expires_on"]}</div>' for o in offers)
    off_card = (f'<div class="card"><h3>Offers</h3><p>{len(offers)} open, '
                f'{sum(1 for o in offers if o["expired"])} expired</p>{off_rows}</div>')
    if season:
        t = C.season_totals(conn, season["id"])
        money_card = (f'<div class="card"><h3>Fees {season["year"]}</h3>'
                      f'<p>Charged {cur(req)} {money(t["charged"])}<br>Paid {money(t["paid"])}<br>'
                      f'<b>Owed {money(t["outstanding"])}</b></p>' +
                      "".join(f'<div><a href="/dues?status={e(k)}">{k}</a>: {v}</div>' for k, v in t["counts"].items())
                      + "</div>")
    else:
        money_card = ('<div class="card"><h3>Fees</h3><p class="hint">No season yet. ' +
                      ('<a href="/seasons/new">Open the first season</a>.' if req.is_admin else
                       "An Admin can open one.") + "</p></div>")
    return layout(req, "Dashboard", f'<div class="cards">{plots_card}{wl_card}{off_card}{money_card}</div>')


# ------------------------------------------------------------------ plots

@route("GET", "/plots")
def plots_page(req):
    conn = req.conn
    status, size, q = req.q("status"), req.q("size"), req.q("q").strip()
    rows = C.list_plots(conn, status, size, q, include_retired=bool(req.q("retired")))
    counts = C.plot_counts(conn)
    filt = (f'<form method="get" class="row"><div>{sel("status", "Status", [(s, C.status_label(s)) for s in C.PLOT_STATUSES], {"status": status}, {}, "All (not retired)")}</div>'
            f'<div>{sel("size", "Size", size_opts(), {"size": size}, {}, "All")}</div>'
            f'<div>{inp("q", "Code or holder", {"q": q}, {})}</div><div><button>Filter</button> '
            f'<a class="btn sec" href="/plots">Clear</a> <a class="btn" href="/plots/new">Add plot</a></div></form>')
    summary = " · ".join(f'{C.status_label(k)}: {v}' for k, v in counts.items())
    trs = [(f'<a href="/plots/{p["id"]}">{e(p["code"])}</a>', p["size"], e(p["area"] or ""),
            plot_status_tag(p["status"]),
            f'<a href="/gardeners/{p["holder_id"]}">{e(p["holder"])}</a>' if p["holder"] else "",
            e(p["start_date"] or "")) for p in rows]
    hint = '' if counts and sum(counts.values()) else '<p class="hint">No plots yet — add the first one.</p>'
    return layout(req, "Plots", filt + f'<p class="muted">{summary}</p>' + hint +
                  table(["Code", "Size", "Area m²", "Status", "Holder", "Since"], trs) +
                  '<p><a href="/plots?retired=1">Include retired plots</a> · <a href="/export/plots.csv">Export plot register (CSV)</a></p>')


def plot_form(req, action, vals, errs, msg=None, title="Add plot"):
    inner = (inp("code", "Code (e.g. B-07)", vals, errs, maxlength="20", required="required") +
             sel("size", "Size", size_opts(), vals, errs, "Choose…") +
             inp("area", "Area in m² (optional)", vals, errs) + area("notes", "Notes", vals, errs) +
             (f'<input type="hidden" name="version" value="{e(vals.get("version"))}">' if vals.get("version") else ""))
    return layout(req, title, error_box(msg) + '<div class="card">' + form(req, action, inner) + "</div>")


@route("GET", "/plots/new")
def plot_new(req):
    return plot_form(req, "/plots/new", {}, {})


@route("POST", "/plots/new")
def plot_new_post(req):
    v = form_vals(req)
    try:
        pid = C.add_plot(req.conn, req.user, v)
    except C.FieldErrors as x:
        return plot_form(req, "/plots/new", v, x.errors)
    return redirect(f"/plots/{pid}", ok="Plot added")


@route("GET", r"/plots/(\d+)/edit")
def plot_edit(req):
    p = C.get_plot(req.conn, int(req.params[0]))
    v = {k: ("" if p[k] is None else p[k]) for k in ("code", "size", "area", "notes", "version")}
    return plot_form(req, f"/plots/{p['id']}/edit", v, {}, title=f"Edit plot {p['code']}")


@route("POST", r"/plots/(\d+)/edit")
def plot_edit_post(req):
    pid, v = int(req.params[0]), form_vals(req)
    try:
        C.edit_plot(req.conn, req.user, pid, v.get("version"), v)
    except C.FieldErrors as x:
        return plot_form(req, f"/plots/{pid}/edit", v, x.errors, title="Edit plot")
    except C.DomainError as x:
        return plot_form(req, f"/plots/{pid}/edit", v, {}, str(x), title="Edit plot")
    return redirect(f"/plots/{pid}", ok="Plot saved")


@route("POST", r"/plots/(\d+)/status")
def plot_status_post(req):
    pid = int(req.params[0])
    try:
        C.change_plot_status(req.conn, req.user, pid, req.f("version"), req.f("action"), req.f("reason"))
    except C.FieldErrors as x:
        return redirect(f"/plots/{pid}", err=" ".join(x.errors.values()))
    return redirect(f"/plots/{pid}", ok="Plot status changed")


@route("GET", r"/plots/(\d+)")
def plot_detail(req):
    conn = req.conn
    p = C.get_plot(conn, int(req.params[0]))
    pid, ver = p["id"], f'<input type="hidden" name="version" value="{p["version"]}">'
    a = C.current_assignment(conn, pid=pid)
    o = C.open_offer_for_plot(conn, pid)
    season = C.current_season(conn)
    t = C.today(conn).isoformat()
    info = (f'<div class="card"><p><b>Size:</b> {p["size"]} · <b>Area:</b> {e(p["area"] or "—")} m² · '
            f'<b>Status:</b> {plot_status_tag(p["status"])} {e(p["status_reason"])}</p>'
            f'<p><b>Notes:</b> {e(p["notes"]) or "—"}</p><a class="btn sec" href="/plots/{pid}/edit">Edit</a></div>')
    actions = ""
    if a:
        fee = ""
        if season:
            f = C.season_figures(conn, a["gardener_id"], season["id"])
            st = C.due_status(f["charged"], f["balance"], season["due_date"], C.today(conn)) if (f["charged"] or f["paid"]) else "Not charged"
            fee = f' · Fees {season["year"]}: <span class="tag {e(st)}">{e(st)}</span> balance {money(f["balance"])}'
        actions += (f'<div class="card"><h3>Holder</h3><p><a href="/gardeners/{a["gardener_id"]}">{e(a["name"])}</a> '
                    f'since {a["start_date"]}{fee}</p>' +
                    form(req, f"/plots/{pid}/release", ver + '<div class="row"><div>' +
                         inp("end_date", "End date", {"end_date": t}, {}, type="date") + "</div><div>" +
                         sel("reason", "Reason", C.RELEASE_REASONS, {}, {}, "Choose…") + "</div></div>",
                         "Release") + "</div>")
    if o:
        expired = C.offer_is_expired(conn, o["expires_on"])
        actions += (f'<div class="card {"expired" if expired else ""}"><h3>Open offer</h3>'
                    f'<p>Offered to <a href="/gardeners/{o["gardener_id"]}">{e(o["name"])}</a> '
                    f'({e(o["email"])} {e(o["phone"])}) on {o["offered_on"]}; '
                    f'{"<b>Expired</b> " if expired else "expires "}{o["expires_on"]}</p>' +
                    form(req, f"/offers/{o['id']}/outcome",
                         '<input type="hidden" name="outcome" value="accepted">' +
                         inp("start_date", "Start date", {"start_date": t}, {}, type="date"), "Accepted") +
                    button_form(req, f"/offers/{o['id']}/outcome", "Declined",
                                '<input type="hidden" name="outcome" value="declined">', "warn") + " " +
                    button_form(req, f"/offers/{o['id']}/outcome", "Expired (no answer)",
                                '<input type="hidden" name="outcome" value="expired">', "warn") + " " +
                    button_form(req, f"/offers/{o['id']}/outcome", "Withdraw offer",
                                '<input type="hidden" name="outcome" value="withdrawn">', "sec") + "</div>")
    if p["status"] == "available":
        actions += (f'<div class="card"><h3>Find a holder</h3><a class="btn" href="/plots/{pid}/offer">'
                    f'Offer to next in line</a> ' +
                    (f'<a class="btn sec" href="/plots/{pid}/assign">Direct assign (Admin)</a>' if req.is_admin else "") +
                    "</div>")
    st_forms = ""
    reason = '<input name="reason" placeholder="Reason" required>'
    if p["status"] == "available":
        st_forms += button_form(req, f"/plots/{pid}/status", "Mark out of service",
                                ver + '<input type="hidden" name="action" value="out_of_service">' + reason, "sec") + " "
    if p["status"] == "out_of_service":
        st_forms += button_form(req, f"/plots/{pid}/status", "Return to service",
                                ver + '<input type="hidden" name="action" value="return">') + " "
    if p["status"] in ("available", "out_of_service", "occupied", "offered"):
        st_forms += button_form(req, f"/plots/{pid}/status", "Retire plot",
                                ver + '<input type="hidden" name="action" value="retire">' + reason, "warn")
    if st_forms:
        actions += f'<div class="card"><h3>Service status</h3>{st_forms}</div>'
    hist = conn.execute("SELECT a.*, u.username FROM audit a LEFT JOIN users u ON u.id=a.user_id "
                        "WHERE a.plot_id=? ORDER BY a.id DESC", (pid,)).fetchall()
    holders = conn.execute("SELECT a.*, g.name FROM assignments a JOIN gardeners g ON g.id=a.gardener_id "
                           "WHERE a.plot_id=? ORDER BY a.start_date DESC, a.id DESC", (pid,)).fetchall()
    body = (info + actions + "<h2>Holders</h2>" +
            table(["Holder", "From", "To", "Reason", "How"],
                  [(f'<a href="/gardeners/{h["gardener_id"]}">{e(h["name"])}</a>', h["start_date"],
                    h["end_date"] or "current", e(h["end_reason"] or ""), e(h["via"] + (": " + h["note"] if h["note"] else "")))
                   for h in holders]) +
            "<h2>History</h2>" + table(["When", "Who", "What"],
                                        [(C.local_ts(conn, h["at"]), e(h["username"] or "system"), e(h["summary"]))
                                         for h in hist]))
    return layout(req, f"Plot {p['code']}", body)


@route("POST", r"/plots/(\d+)/release")
def plot_release(req):
    pid = int(req.params[0])
    try:
        C.release_plot(req.conn, req.user, pid, req.f("version"), req.f("end_date"), req.f("reason"))
    except C.FieldErrors as x:
        return redirect(f"/plots/{pid}", err=" ".join(x.errors.values()))
    return redirect(f"/plots/{pid}", ok="Plot released and now Available")


@route("GET", r"/plots/(\d+)/offer")
def offer_preview(req):
    pid = int(req.params[0])
    try:
        p, en = C.preview_offer(req.conn, pid)
    except C.DomainError as x:
        return redirect(f"/plots/{pid}", err=str(x))
    days = C.get_setting(req.conn, "offers.expiry_days")
    body = (f'<div class="card"><p>Next in line for <b>{e(p["code"])}</b> ({p["size"]}):</p>'
            f'<p><b><a href="/gardeners/{en["gardener_id"]}">{e(en["name"])}</a></b> — position '
            f'{C.entry_position(req.conn, en["id"])}, preference {en["preference"]}, joined '
            f'{C.local_ts(req.conn, en["joined_at"], False)}</p><p>Email: {e(en["email"]) or "—"} · '
            f'Phone: {e(en["phone"]) or "—"}</p><p>The offer will expire in {e(days)} days. '
            f'Contact the person yourself after confirming.</p>' +
            form(req, f"/plots/{pid}/offer", f'<input type="hidden" name="version" value="{p["version"]}">'
                 f'<input type="hidden" name="entry_id" value="{en["id"]}">', "Confirm offer") +
            f'<a href="/plots/{pid}">Cancel</a></div>')
    return layout(req, f"Offer plot {p['code']}", body)


@route("POST", r"/plots/(\d+)/offer")
def offer_post(req):
    pid = int(req.params[0])
    C.make_offer(req.conn, req.user, pid, req.f("version"), req.f("entry_id"))
    return redirect(f"/plots/{pid}", ok="Offer recorded. Contact the person now.")


@route("POST", r"/offers/(\d+)/outcome")
def offer_outcome(req):
    o = C.get_offer(req.conn, int(req.params[0]))
    try:
        C.resolve_offer(req.conn, req.user, o["id"], req.f("outcome"), req.f("start_date") or None)
    except C.FieldErrors as x:
        return redirect(f"/plots/{o['plot_id']}", err=" ".join(x.errors.values()))
    return redirect(f"/plots/{o['plot_id']}", ok=f"Offer recorded as {req.f('outcome')}")


@route("GET", r"/plots/(\d+)/assign", "admin")
def assign_page(req, vals=None, errs=None, msg=None):
    p = C.get_plot(req.conn, int(req.params[0]))
    gs = req.conn.execute("SELECT g.id, g.name, g.email FROM gardeners g WHERE g.archived=0 AND NOT EXISTS "
                          "(SELECT 1 FROM assignments a WHERE a.gardener_id=g.id AND a.end_date IS NULL) "
                          "ORDER BY g.name COLLATE NOCASE").fetchall()
    vals = vals or {"start_date": C.today(req.conn).isoformat(), "version": p["version"]}
    errs = errs or {}
    inner = (sel("gardener_id", "Gardener (without a plot)", [(g["id"], f'{g["name"]} {g["email"]}') for g in gs],
                 vals, errs, "Choose…") + inp("start_date", "Start date", vals, errs, type="date") +
             inp("reason", "Reason for bypassing the waiting list", vals, errs, size="60") +
             f'<input type="hidden" name="version" value="{e(vals.get("version"))}">')
    return layout(req, f"Direct assign {p['code']}", error_box(msg) + '<div class="card">' +
                  form(req, f"/plots/{p['id']}/assign", inner, "Assign") + "</div>")


@route("POST", r"/plots/(\d+)/assign", "admin")
def assign_post(req):
    pid, v = int(req.params[0]), form_vals(req)
    try:
        C.direct_assign(req.conn, req.user, pid, v.get("version"), int(v["gardener_id"]) if v.get("gardener_id", "").isdigit() else None,
                        v.get("start_date"), v.get("reason"))
    except C.FieldErrors as x:
        return assign_page(req, v, x.errors)
    except C.DomainError as x:
        return assign_page(req, v, {}, str(x))
    return redirect(f"/plots/{pid}", ok="Plot assigned")


# ------------------------------------------------------------------ gardeners

@route("GET", "/gardeners")
def gardeners_page(req):
    q = req.q("q").strip()
    rows = C.list_gardeners(req.conn, q, bool(req.q("archived")))
    trs = [(f'<a href="/gardeners/{g["id"]}">{e(g["name"])}</a>' + (' <span class="tag">archived</span>' if g["archived"] else ""),
            e(g["email"]), e(g["phone"]),
            f'<a href="/plots/{g["plot_id"]}">{e(g["plot_code"])}</a>' if g["plot_code"] else "") for g in rows]
    top = (f'<form method="get" class="row"><div>{inp("q", "Name, email or phone", {"q": q}, {})}</div>'
           f'<div><button>Search</button> <a class="btn" href="/gardeners/new">Add gardener</a></div></form>')
    return layout(req, "Gardeners", top + table(["Name", "Email", "Phone", "Plot"], trs) +
                  '<p><a href="/gardeners?archived=1">Include archived</a></p>')


def gardener_form(req, action, vals, errs, msg=None, title="Add gardener", dups=None):
    warn = ""
    if dups:
        warn = ('<div class="msg bad">A gardener with the same email or phone already exists: ' +
                ", ".join(f'<a href="/gardeners/{d["id"]}">{e(d["name"])} ({e(d["email"] or d["phone"])})</a>'
                          for d in dups) + '. Open the existing record, or tick "Save anyway".</div>')
    inner = (inp("name", "Name", vals, errs, required="required") + inp("email", "Email", vals, errs) +
             inp("phone", "Phone", vals, errs) + area("address", "Address (optional)", vals, errs) +
             area("notes", "Notes", vals, errs) +
             (f'<input type="hidden" name="version" value="{e(vals.get("version"))}">' if vals.get("version") else "") +
             ('<label><input type="checkbox" name="allow_duplicate" value="1"> Save anyway</label>' if dups else ""))
    return layout(req, title, error_box(msg) + warn + '<div class="card">' + form(req, action, inner) + "</div>")


@route("GET", "/gardeners/new")
def gardener_new(req):
    return gardener_form(req, "/gardeners/new", {}, {})


@route("POST", "/gardeners/new")
def gardener_new_post(req):
    v = form_vals(req)
    try:
        gid = C.add_gardener(req.conn, req.user, v, allow_duplicate=v.get("allow_duplicate") == "1")
    except C.FieldErrors as x:
        return gardener_form(req, "/gardeners/new", v, x.errors)
    except C.DuplicateWarning as x:
        return gardener_form(req, "/gardeners/new", v, {}, dups=x.matches)
    return redirect(f"/gardeners/{gid}", ok="Gardener added")


@route("GET", r"/gardeners/(\d+)/edit")
def gardener_edit(req):
    g = C.get_gardener(req.conn, int(req.params[0]))
    return gardener_form(req, f"/gardeners/{g['id']}/edit", dict(g), {}, title=f"Edit {g['name']}")


@route("POST", r"/gardeners/(\d+)/edit")
def gardener_edit_post(req):
    gid, v = int(req.params[0]), form_vals(req)
    try:
        C.edit_gardener(req.conn, req.user, gid, v.get("version"), v)
    except C.FieldErrors as x:
        return gardener_form(req, f"/gardeners/{gid}/edit", v, x.errors, title="Edit gardener")
    except C.DomainError as x:
        return gardener_form(req, f"/gardeners/{gid}/edit", v, {}, str(x), title="Edit gardener")
    return redirect(f"/gardeners/{gid}", ok="Saved")


@route("POST", r"/gardeners/(\d+)/archive")
def gardener_archive(req):
    gid = int(req.params[0])
    C.archive_gardener(req.conn, req.user, gid, req.f("archived") == "1")
    return redirect(f"/gardeners/{gid}", ok="Archived" if req.f("archived") == "1" else "Restored")


@route("GET", r"/gardeners/(\d+)")
def gardener_detail(req):
    conn = req.conn
    g = C.get_gardener(conn, int(req.params[0]))
    gid = g["id"]
    a = C.current_assignment(conn, gid=gid)
    en = C.active_entry(conn, gid)
    info = (f'<div class="card"><p><b>Email:</b> {e(g["email"]) or "—"} · <b>Phone:</b> {e(g["phone"]) or "—"}</p>'
            f'<p><b>Address:</b> {e(g["address"]) or "—"}</p><p><b>Notes:</b> {e(g["notes"]) or "—"}</p>'
            f'<a class="btn sec" href="/gardeners/{gid}/edit">Edit</a> ' +
            button_form(req, f"/gardeners/{gid}/archive", "Restore" if g["archived"] else "Archive",
                        f'<input type="hidden" name="archived" value="{0 if g["archived"] else 1}">', "sec") +
            (' <span class="tag">archived</span>' if g["archived"] else "") + "</div>")
    plot = (f'<p>Holds <a href="/plots/{a["plot_id"]}">{e(a["code"])}</a> ({a["size"]}) since {a["start_date"]}</p>'
            if a else "<p>No plot.</p>")
    if en:
        pos = C.entry_position(conn, en["id"])
        wl = (f'<p>On the waiting list at <b>position {pos}</b>, preference {en["preference"]}, joined '
              f'{C.local_ts(conn, en["joined_at"], False)}{" — <b>offer open</b>" if en["status"] == "offered" else ""}.</p>' +
              button_form(req, f"/waitlist/{en['id']}/preference", "Change preference",
                          sel("preference", "", C.PREFERENCES, dict(en), {})) + " " +
              button_form(req, f"/waitlist/{en['id']}/remove", "Remove from list",
                          sel("reason", "", C.REMOVE_REASONS, {}, {}, "Reason…") +
                          '<input name="note" placeholder="Note (optional)">', "warn"))
    elif not a and not g["archived"]:
        wl = button_form(req, "/waitlist/new", "Add to waiting list",
                         f'<input type="hidden" name="gardener_id" value="{gid}">' +
                         sel("preference", "", [(p, f"Preference: {p}") for p in C.PREFERENCES], {}, {}) +
                         ' Joined <input type="date" name="joined">')
    else:
        wl = "<p>Not on the waiting list.</p>"
    seasons = C.list_seasons(conn)
    bal_rows = []
    for s in seasons:
        f = C.season_figures(conn, gid, s["id"])
        if f["charged"] or f["paid"] or f["balance"]:
            st = C.due_status(f["charged"], f["balance"], s["due_date"], C.today(conn))
            bal_rows.append((s["year"], money(f["charged"]), money(f["paid"]), money(f["balance"]),
                             f'<span class="tag {e(st)}">{st}</span>'))
    money_links = ""
    if seasons:
        money_links = (f'<a class="btn" href="/gardeners/{gid}/money?kind=payment">Record payment</a> '
                       f'<a class="btn sec" href="/gardeners/{gid}/money?kind=refund">Refund</a> ' +
                       (f'<a class="btn sec" href="/gardeners/{gid}/money?kind=adjustment">Adjustment</a>' if req.is_admin else ""))
    led = C.gardener_ledger(conn, gid)
    led_rows = []
    for r in led:
        kind = r["kind"].capitalize()
        if r["voided_by"]:
            kind = f"<s>{kind}</s> (voided)"
        void = ""
        if r["kind"] == "payment" and not r["voided_by"]:
            void = button_form(req, f"/ledger/{r['id']}/void", "Void",
                               '<input name="reason" placeholder="Reason" required size="12">', "sec")
        led_rows.append((r["entry_date"], r["year"], kind, money(r["amount"]),
                         e(" ".join(x for x in [r["method"] or "", r["reference"], r["reason"]] if x)),
                         e(r["username"] or ""), money(r["running"]), void))
    hist = conn.execute("SELECT a.*, u.username FROM audit a LEFT JOIN users u ON u.id=a.user_id "
                        "WHERE a.gardener_id=? ORDER BY a.id DESC LIMIT 200", (gid,)).fetchall()
    body = (info + f'<div class="card"><h3>Plot and waiting list</h3>{plot}{wl}</div>' +
            f'<h2>Balances ({cur(req)})</h2>' + table(["Season", "Charged", "Paid", "Balance", "Status"], bal_rows, (1, 2, 3)) +
            money_links + "<h2>Ledger</h2><p class='muted'>Amount is the effect on the balance: charges are +, payments −.</p>" +
            table(["Date", "Season", "Type", "Amount", "Details", "By", "Running balance", ""], led_rows, (3, 6)) +
            "<h2>History</h2>" + table(["When", "Who", "What"], [(C.local_ts(conn, h["at"]), e(h["username"] or "system"),
                                                                  e(h["summary"])) for h in hist]))
    return layout(req, g["name"], body)


# ------------------------------------------------------------------ money

KIND_TITLES = {"payment": "Record payment", "refund": "Record refund", "adjustment": "Record adjustment"}


@route("GET", r"/gardeners/(\d+)/money")
def money_page(req, vals=None, errs=None, msg=None):
    conn = req.conn
    g = C.get_gardener(conn, int(req.params[0]))
    kind = (vals or {}).get("kind") or req.q("kind", "payment")
    if kind not in KIND_TITLES:
        kind = "payment"
    if kind == "adjustment" and not req.is_admin:
        raise PermissionError("Admins only")
    seasons = C.list_seasons(conn)
    if not seasons:
        return redirect(f"/gardeners/{g['id']}", err="No season yet")
    cs = C.current_season(conn)
    vals = vals or {"date": C.today(conn).isoformat(), "season_id": cs["id"], "token": secrets.token_urlsafe(16)}
    errs = errs or {}
    lines = []
    for s in seasons:
        f = C.season_figures(conn, g["id"], s["id"])
        lines.append(f'{s["year"]}: balance {money(f["balance"])}, paid {money(f["paid"])}')
    inner = (f'<input type="hidden" name="kind" value="{kind}"><input type="hidden" name="token" value="{e(vals.get("token"))}">' +
             inp("amount", f"Amount ({C.get_setting(conn, 'currency')})" + (" — use + to add a charge, − to waive" if kind == "adjustment" else ""),
                 vals, errs, inputmode="decimal") +
             inp("date", "Date", vals, errs, type="date") +
             sel("season_id", "Season", [(s["id"], s["year"]) for s in seasons], vals, errs) +
             (sel("method", "Method", [(m, m.replace("_", " ")) for m in C.METHODS], vals, errs, "Choose…")
              if kind != "adjustment" else "") +
             (inp("reference", "Reference (optional)", vals, errs) if kind == "payment" else
              inp("reason", "Reason", vals, errs, size="50")))
    return layout(req, f"{KIND_TITLES[kind]}: {g['name']}", error_box(msg) +
                  f'<p class="muted">{"; ".join(lines)}</p><div class="card">' +
                  form(req, f"/gardeners/{g['id']}/money", inner) + "</div>")


@route("POST", r"/gardeners/(\d+)/money")
def money_post(req):
    gid, v = int(req.params[0]), form_vals(req)
    sid = int(v["season_id"]) if v.get("season_id", "").isdigit() else None
    try:
        if v.get("kind") == "refund":
            C.record_refund(req.conn, req.user, gid, sid, v.get("amount"), v.get("date"), v.get("method"),
                            v.get("reason"), v.get("token"))
        elif v.get("kind") == "adjustment":
            C.record_adjustment(req.conn, req.user, gid, sid, v.get("amount"), v.get("date"), v.get("reason"),
                                v.get("token"))
        else:
            C.record_payment(req.conn, req.user, gid, sid, v.get("amount"), v.get("date"), v.get("method"),
                             v.get("reference"), v.get("token"))
    except C.FieldErrors as x:
        return money_page(req, v, x.errors)
    except C.DomainError as x:
        return money_page(req, v, {}, str(x))
    return redirect(f"/gardeners/{gid}", ok="Saved to the ledger")


@route("POST", r"/ledger/(\d+)/void")
def void_post(req):
    lid = int(req.params[0])
    row = req.conn.execute("SELECT gardener_id FROM ledger WHERE id=?", (lid,)).fetchone()
    if not row:
        raise C.DomainError("No such entry")
    try:
        C.void_payment(req.conn, req.user, lid, req.f("reason"))
    except (C.FieldErrors, C.DomainError) as x:
        msg = " ".join(x.errors.values()) if isinstance(x, C.FieldErrors) else str(x)
        return redirect(f"/gardeners/{row['gardener_id']}", err=msg)
    return redirect(f"/gardeners/{row['gardener_id']}", ok="Payment voided")


# ------------------------------------------------------------------ waiting list

@route("GET", "/waitlist")
def waitlist_page(req, vals=None, errs=None, msg=None):
    conn = req.conn
    wl = C.waiting_list(conn)
    td = C.today(conn)
    rows = []
    for w in wl:
        joined = C.parse_iso(w["joined_at"]).astimezone(C.garden_tz(conn)).date()
        rows.append((w["position"], f'<a href="/gardeners/{w["gardener_id"]}">{e(w["name"])}</a>',
                     joined.isoformat(), w["preference"], (td - joined).days,
                     "offer open" if w["status"] == "offered" else (f'declined {w["declines"]}×' if w["declines"] else "")))
    cands = conn.execute(
        "SELECT g.id, g.name, g.email, g.phone FROM gardeners g WHERE g.archived=0 "
        "AND NOT EXISTS (SELECT 1 FROM assignments a WHERE a.gardener_id=g.id AND a.end_date IS NULL) "
        "AND NOT EXISTS (SELECT 1 FROM waitlist w WHERE w.gardener_id=g.id AND w.status IN ('active','offered')) "
        "ORDER BY g.name COLLATE NOCASE").fetchall()
    vals, errs = vals or {}, errs or {}
    add = ('<div class="card"><h3>Add to waiting list</h3>' + form(
        req, "/waitlist/new", '<div class="row"><div>' +
        sel("gardener_id", "Gardener", [(g["id"], f'{g["name"]} ({g["email"] or g["phone"]})') for g in cands], vals, errs, "Choose…") +
        "</div><div>" + sel("preference", "Size preference", C.PREFERENCES, vals, errs) + "</div><div>" +
        inp("joined", "Join date (leave empty for now; backdate when migrating)", vals, errs, type="date") +
        "</div></div>", "Add") + '<p class="hint">Not listed? <a href="/gardeners/new">Add the gardener</a> first.</p></div>')
    return layout(req, "Waiting list", error_box(msg) +
                  table(["#", "Name", "Joined", "Preference", "Days waiting", ""], rows, (0, 4)) +
                  '<p><a href="/export/waitlist.csv">Export waiting list (CSV)</a></p>' + add)


@route("POST", "/waitlist/new")
def waitlist_add(req):
    v = form_vals(req)
    gid = int(v["gardener_id"]) if v.get("gardener_id", "").isdigit() else None
    try:
        if not gid:
            raise C.FieldErrors({"gardener_id": "Choose a gardener"})
        C.add_to_waitlist(req.conn, req.user, gid, v.get("preference"), v.get("joined") or None)
    except C.FieldErrors as x:
        return waitlist_page(req, v, x.errors)
    except C.DomainError as x:
        return waitlist_page(req, v, {}, str(x))
    return redirect("/waitlist", ok="Added to the waiting list")


def _entry_gid(req):
    r = req.conn.execute("SELECT gardener_id FROM waitlist WHERE id=?", (int(req.params[0]),)).fetchone()
    if not r:
        raise C.DomainError("No such entry")
    return r["gardener_id"]


@route("POST", r"/waitlist/(\d+)/preference")
def waitlist_pref(req):
    gid = _entry_gid(req)
    C.change_preference(req.conn, req.user, int(req.params[0]), req.f("preference"))
    return redirect(f"/gardeners/{gid}", ok="Preference changed; position kept")


@route("POST", r"/waitlist/(\d+)/remove")
def waitlist_remove(req):
    gid = _entry_gid(req)
    try:
        C.remove_from_waitlist(req.conn, req.user, int(req.params[0]), req.f("reason"), req.f("note"))
    except C.FieldErrors as x:
        return redirect(f"/gardeners/{gid}", err=" ".join(x.errors.values()))
    return redirect(f"/gardeners/{gid}", ok="Removed from the waiting list")


# ------------------------------------------------------------------ seasons

@route("GET", "/seasons")
def seasons_page(req):
    rows = []
    cs = C.current_season(req.conn)
    for s in C.list_seasons(req.conn):
        close = ""
        if req.is_admin and not s["closed_at"]:
            close = button_form(req, f"/seasons/{s['id']}/close", "Close season", "", "sec")
        rows.append((f'<a href="/dues?season={s["id"]}">{s["year"]}</a>' + (" (current)" if cs and s["id"] == cs["id"] else ""),
                     s["due_date"], money(s["fee_small"]), money(s["fee_standard"]), money(s["fee_large"]),
                     "closed" if s["closed_at"] else "open", close))
    new = '<p><a class="btn" href="/seasons/new">Open a season</a></p>' if req.is_admin else ""
    return layout(req, "Seasons", new + table(["Year", "Due date", f"Small ({cur(req)})", "Standard", "Large", "State", ""],
                                              rows, (2, 3, 4)))


@route("GET", "/seasons/new", "admin")
def season_new(req, vals=None, errs=None):
    conn = req.conn
    fees = C.default_fees(conn)
    last = C.current_season(conn)
    year = max(C.today(conn).year, (last["year"] + 1) if last else 0)
    vals = vals or {"year": str(year), "due_date": f"{year}-{C.get_setting(conn, 'seasons.due_date')}",
                    **{f"fee_{z}": money(fees[z]) for z in C.SIZES}}
    errs = errs or {}
    inner = ('<input type="hidden" name="step" value="preview">' + inp("year", "Year", vals, errs) +
             inp("due_date", "Due date", vals, errs, type="date") +
             "".join(inp(f"fee_{z}", f"Fee for {z} plots ({C.get_setting(conn, 'currency')})", vals, errs) for z in C.SIZES))
    return layout(req, "Open a season", '<div class="card">' + form(req, "/seasons/new", inner, "Preview") + "</div>")


@route("POST", "/seasons/new", "admin")
def season_new_post(req):
    conn, v = req.conn, form_vals(req)
    try:
        if v.get("step") == "confirm":
            sid, n = C.open_season(conn, req.user, v)
            return redirect(f"/dues?season={sid}", ok=f"Season opened; {n} charges created")
        year, due, fees = C.clean_season(conn, v)
    except C.FieldErrors as x:
        return season_new(req, v, x.errors)
    pv = C.season_preview(conn, fees)
    hidden = "".join(f'<input type="hidden" name="{k}" value="{e(val)}">' for k, val in v.items() if k not in ("_csrf", "step"))
    rows = [(z, money(fees[z]), pv[z]["count"], money(pv[z]["total"])) for z in C.SIZES]
    rows.append(("<b>Total</b>", "", sum(p["count"] for p in pv.values()), f'<b>{money(sum(p["total"] for p in pv.values()))}</b>'))
    body = (f'<div class="card"><p>Season <b>{year}</b>, due {due}. These current holders will be charged:</p>' +
            table(["Size", "Fee", "Assignments", f"Total ({cur(req)})"], rows, (1, 2, 3)) +
            form(req, "/seasons/new", hidden + '<input type="hidden" name="step" value="confirm">', "Confirm and charge") +
            '<a href="/seasons/new">Back</a></div>')
    return layout(req, f"Preview season {year}", body)


@route("POST", r"/seasons/(\d+)/close", "admin")
def season_close(req):
    C.close_season(req.conn, req.user, int(req.params[0]))
    return redirect("/seasons", ok="Season closed")


# ------------------------------------------------------------------ dues & exports

def _range(req):
    td = C.today(req.conn)
    errs = {}
    start = C.parse_date(req.q("from") or td.isoformat(), "from", errs)
    end = C.parse_date(req.q("to") or td.isoformat(), "to", errs)
    if start and end and end < start:
        errs["to"] = "End date must be on or after the start date"
    return start, end, errs


@route("GET", "/dues")
def dues_page(req):
    conn = req.conn
    season = C.get_season(conn, req.q("season"))
    if not season:
        return layout(req, "Dues", '<p class="msg bad">No season yet.' +
                      (' <a href="/seasons/new">Open a season</a>.' if req.is_admin else "") + "</p>")
    status, sort = req.q("status"), req.q("sort", "name")
    rows = C.dues(conn, season["id"], status=status, sort=sort)
    t = C.season_totals(conn, season["id"])
    start, end, rerrs = _range(req)
    td = C.today(conn)
    filt = (f'<form method="get" class="row"><div>{sel("season", "Season", [(s["id"], s["year"]) for s in C.list_seasons(conn)], {"season": season["id"]}, {})}</div>'
            f'<div>{sel("status", "Status", C.DUE_STATUSES, {"status": status}, {}, "All")}</div>'
            f'<div>{sel("sort", "Sort by", [("name", "Name"), ("balance", "Balance (highest first)")], {"sort": sort}, {})}</div>'
            f'<div><button>Show</button></div></form>')
    head = (f'<div class="cards"><div class="card"><h3>Season {season["year"]} ({cur(req)})</h3>'
            f'Charged {money(t["charged"])}<br>Paid {money(t["paid"])}<br><b>Outstanding {money(t["outstanding"])}</b><br>'
            f'Net balance {money(t["balance"])}<br>Due date {season["due_date"]}</div><div class="card"><h3>By status</h3>' +
            "".join(f"<div>{k}: {v}</div>" for k, v in t["counts"].items()) + "</div>")
    if rerrs:
        bm = "".join(f'<div class="err">{e(m)}</div>' for m in rerrs.values())
    else:
        pm = C.payments_by_method(conn, start, end)
        bm = "".join(f"<div>{m.replace('_', ' ')}: {money(v)}</div>" for m, v in pm.items()) + \
            f"<div><b>Total {money(sum(pm.values()))}</b></div>"
    base = f'/dues?season={season["id"]}'
    head += (f'<div class="card"><h3>Payments by method</h3><form method="get"><input type="hidden" name="season" value="{season["id"]}">'
             f'<input type="date" name="from" value="{e(req.q("from") or td)}"> to <input type="date" name="to" value="{e(req.q("to") or td)}"> '
             f'<button class="sec">Go</button></form><p><a href="{base}">Today</a> · '
             f'<a href="{base}&from={td.replace(day=1)}&to={td}">This month</a></p>{bm}</div></div>')
    trs = [(f'<a href="/gardeners/{r["id"]}">{e(r["name"])}</a>', e(r["plot_code"] or ""), money(r["charged"]),
            money(r["paid"]), money(r["balance"]), f'<span class="tag {e(r["status"])}">{r["status"]}</span>',
            f'<a href="/gardeners/{r["id"]}/money?kind=payment">Record payment</a>') for r in rows]
    exp = (f'<p>Export: <a href="/export/dues.csv?season={season["id"]}">season dues</a> · '
           f'<a href="/export/payments.csv?from={start or td}&to={end or td}">payments ledger for the date range</a></p>')
    return layout(req, "Dues", filt + head + table(["Gardener", "Plot", "Charged", "Paid", "Balance", "Status", ""],
                                                   trs, (2, 3, 4)) + exp)


def csv_response(name, header, rows):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(header)
    for r in rows:
        w.writerow(["'" + c if isinstance(c, str) and c[:1] in ("=", "+", "-", "@") and not re.match(r"^-?\d", c) else c
                    for c in r])
    return Response(buf.getvalue(), ctype="text/csv; charset=utf-8",
                    headers=[("Content-Disposition", f'attachment; filename="{name}"')])


@route("GET", r"/export/dues\.csv")
def export_dues(req):
    s = C.get_season(req.conn, req.q("season"))
    if not s:
        return csv_response("dues.csv", ["gardener", "email", "phone", "plot", "charged", "paid", "balance", "status"], [])
    rows = C.dues(req.conn, s["id"], sort=req.q("sort", "name"))
    return csv_response(f"dues-{s['year']}.csv",
                        ["gardener", "email", "phone", "plot", "charged", "paid", "balance", "status"],
                        [(r["name"], r["email"], r["phone"], r["plot_code"] or "", money(r["charged"]),
                          money(r["paid"]), money(r["balance"]), r["status"]) for r in rows])


@route("GET", r"/export/payments\.csv")
def export_payments(req):
    start, end, errs = _range(req)
    if errs:
        return redirect("/dues", err=" ".join(errs.values()))
    rows = C.payments_in_range(req.conn, start, end)
    out = [(r["entry_date"], r["name"], r["year"], r["kind"], money(-r["amount"]), r["method"] or "",
            r["reference"], r["reason"], r["username"] or "") for r in rows]
    if out:  # an empty range exports headers only
        out.append(("TOTAL", "", "", "", money(-sum(r["amount"] for r in rows)), "", "", "", ""))
    return csv_response(f"payments-{start}-to-{end}.csv",
                        ["date", "gardener", "season", "type", "amount_received", "method", "reference", "reason", "user"], out)


@route("GET", r"/export/plots\.csv")
def export_plots(req):
    rows = C.list_plots(req.conn, include_retired=True)
    return csv_response("plot-register.csv", ["plot", "size", "area_m2", "status", "holder", "since"],
                        [(p["code"], p["size"], p["area"] if p["area"] is not None else "", C.status_label(p["status"]),
                          p["holder"] or "", p["start_date"] or "") for p in rows])


@route("GET", r"/export/waitlist\.csv")
def export_waitlist(req):
    conn = req.conn
    return csv_response("waiting-list.csv", ["position", "name", "email", "phone", "joined", "preference", "status"],
                        [(w["position"], w["name"], w["email"], w["phone"], C.local_ts(conn, w["joined_at"], False),
                          w["preference"], w["status"]) for w in C.waiting_list(conn)])


# ------------------------------------------------------------------ admin: users, settings, audit

@route("GET", "/users", "admin")
def users_page(req, vals=None, errs=None, created=None):
    rows = []
    for u in req.conn.execute("SELECT * FROM users ORDER BY username COLLATE NOCASE"):
        acts = (button_form(req, f"/users/{u['id']}/role", "Set role", sel("role", "", C.ROLES, dict(u), {}), "sec") + " " +
                    button_form(req, f"/users/{u['id']}/reset", "Reset password", "", "sec") + " " +
                    button_form(req, f"/users/{u['id']}/active", "Reactivate" if not u["active"] else "Deactivate",
                                f'<input type="hidden" name="active" value="{0 if u["active"] else 1}">', "warn"))
        rows.append((e(u["username"]), u["role"], "active" if u["active"] else "deactivated",
                     "must change password" if u["must_change"] else "", acts))
    vals, errs = vals or {}, errs or {}
    note = (f'<div class="msg ok">Temporary password for <b>{e(created[0])}</b>: <code>{e(created[1])}</code> — '
            f'shown once. They must change it at first sign-in.</div>') if created else ""
    add = '<div class="card"><h3>Add user</h3>' + form(req, "/users", '<div class="row"><div>' +
                                                     inp("username", "Username", vals, errs) + "</div><div>" +
                                                     sel("role", "Role", C.ROLES, vals or {"role": "coordinator"}, errs) +
                                                     "</div></div>", "Add user") + "</div>"
    return layout(req, "Users", note + table(["Username", "Role", "State", "", ""], rows) + add)


@route("POST", "/users", "admin")
def users_add(req):
    v = form_vals(req)
    try:
        _, pw = C.create_user(req.conn, req.user, v.get("username"), v.get("role"))
    except C.FieldErrors as x:
        return users_page(req, v, x.errors)
    return users_page(req, created=(v["username"].strip(), pw))


@route("POST", r"/users/(\d+)/role", "admin")
def users_role(req):
    C.set_role(req.conn, req.user, int(req.params[0]), req.f("role"))
    return redirect("/users", ok="Role changed")


@route("POST", r"/users/(\d+)/reset", "admin")
def users_reset(req):
    uid = int(req.params[0])
    pw = C.reset_password(req.conn, req.user, uid)
    u = req.conn.execute("SELECT username FROM users WHERE id=?", (uid,)).fetchone()
    return users_page(req, created=(u["username"], pw))


@route("POST", r"/users/(\d+)/active", "admin")
def users_active(req):
    C.set_active(req.conn, req.user, int(req.params[0]), req.f("active") == "1")
    return redirect("/users", ok="User updated")


SETTING_LABELS = [
    ("garden_name", "Garden name"), ("fee.small", "Default fee, small plot"), ("fee.standard", "Default fee, standard plot"),
    ("fee.large", "Default fee, large plot"), ("offers.expiry_days", "Offer expiry (days)"),
    ("seasons.due_date", "Default due date (MM-DD)"), ("waitlist.max_declines", "Declines before removal from list"),
    ("waitlist.decline_policy", "waitlist.decline_policy"), ("fees.new_holder_charge", "fees.new_holder_charge"),
    ("payments.overpayment", "payments.overpayment"), ("plots.release_with_balance", "plots.release_with_balance"),
    ("auth.session_hours", "Session inactivity timeout (hours)"), ("auth.max_failed", "Failed sign-ins before lockout"),
    ("auth.lockout_minutes", "Lockout duration (minutes)"),
    ("fees.prorate_from", "fees.prorate_from (prorating month)"),
    ("assign.direct_with_active_entry", "assign.direct_with_active_entry (direct assign to someone on the list)"),
    ("seasons.current_rule", "seasons.current_rule (which season is current)"),
    ("offers.valid_on_expiry_date", "offers.valid_on_expiry_date (offer still open on its expiry date)")]


@route("GET", "/settings", "admin")
def settings_page(req, vals=None, errs=None):
    s = C.get_settings(req.conn)
    if vals is None:
        vals = {k: (money(int(s[k])) if k.startswith("fee.") else s[k]) for k, _ in SETTING_LABELS}
    errs = errs or {}
    inner = ""
    for k, label in SETTING_LABELS:
        inner += (sel(k, label, C.CHOICE_SETTINGS[k], vals, errs) if k in C.CHOICE_SETTINGS
                  else inp(k, label, vals, errs))
    info = (f'<p class="muted">Currency {e(s["currency"])} · time zone {e(C.garden_tz(req.conn).key)} (set at setup). '
            f'Fees here are the defaults for the next season; existing charges never change.</p>')
    return layout(req, "Settings", info + '<div class="card">' + form(req, "/settings", inner) + "</div>")


@route("POST", "/settings", "admin")
def settings_post(req):
    v = {k: req.f(k) for k, _ in SETTING_LABELS}
    try:
        C.update_settings(req.conn, req.user, v)
    except C.FieldErrors as x:
        return settings_page(req, v, x.errors)
    return redirect("/settings", ok="Settings saved")


@route("GET", "/audit", "admin")
def audit_page(req):
    conn = req.conn
    sql = ("SELECT a.*, u.username FROM audit a LEFT JOIN users u ON u.id=a.user_id WHERE 1=1")
    args = []
    if req.q("user"):
        sql += " AND a.user_id=?"
        args.append(req.q("user"))
    if req.q("record"):
        sql += " AND a.record_type=?"
        args.append(req.q("record"))
    if req.q("record_id").isdigit():
        sql += " AND a.record_id=?"
        args.append(int(req.q("record_id")))
    for key, op, add in (("from", ">=", 0), ("to", "<", 1)):
        d = req.q(key)
        try:
            day = dt.date.fromisoformat(d) + dt.timedelta(days=add)
            sql += f" AND a.at {op} ?"
            args.append(C.local_date_to_iso(conn, day))
        except ValueError:
            pass
    rows = conn.execute(sql + " ORDER BY a.id DESC LIMIT 500", args).fetchall()
    users = [(u["id"], u["username"]) for u in conn.execute("SELECT id, username FROM users ORDER BY username")]
    types = [r[0] for r in conn.execute("SELECT DISTINCT record_type FROM audit ORDER BY 1")]
    q = {k: req.q(k) for k in ("user", "record", "record_id", "from", "to")}
    filt = (f'<form method="get" class="row"><div>{sel("user", "User", users, q, {}, "Any")}</div>'
            f'<div>{sel("record", "Record type", types, q, {}, "Any")}</div><div>{inp("record_id", "Record id", q, {}, size="6")}</div>'
            f'<div>{inp("from", "From", q, {}, type="date")}</div><div>{inp("to", "To", q, {}, type="date")}</div>'
            f'<div><button>Filter</button></div></form>')

    def ch(r):
        parts = []
        if r["before"]:
            parts.append("before " + r["before"])
        if r["after"]:
            parts.append("after " + r["after"])
        return f'<span class="muted">{e("; ".join(parts))}</span>'
    trs = [(C.local_ts(conn, r["at"]), e(r["username"] or "system"), e(r["action"]),
            f'{e(r["record_type"])} {r["record_id"] or ""}', e(r["summary"]), ch(r)) for r in rows]
    return layout(req, "Audit log", filt + table(["When", "Who", "Action", "Record", "Summary", "Change"], trs) +
                  '<p class="muted">Showing up to 500 most recent entries.</p>')


# ------------------------------------------------------------------ application

class App:
    def __init__(self, db_file, secret, default_tz="UTC"):
        self.db_file, self.secret, self.default_tz = db_file, secret.encode(), default_tz

    def sign(self, token):
        return token + "." + hmac.new(self.secret, token.encode(), hashlib.sha256).hexdigest()[:32]

    def unsign(self, value):
        token, _, sig = (value or "").rpartition(".")
        if token and hmac.compare_digest(self.sign(token), value):
            return token
        return None

    def login(self, req, uid):
        token = C.create_session(req.conn, uid)
        req.set_cookies.append(f"pk_session={self.sign(token)}; Path=/; HttpOnly; SameSite=Lax")

    def handle(self, method, raw_path, headers, body):
        url = urlparse(raw_path)
        query = parse_qs(url.query, keep_blank_values=True)
        form_data = parse_qs(body.decode("utf-8", "replace"), keep_blank_values=True) if method == "POST" else {}
        cookies = {}
        if headers.get("Cookie"):
            sc = SimpleCookie()
            try:
                sc.load(headers.get("Cookie"))
                cookies = {k: m.value for k, m in sc.items()}
            except Exception:
                pass
        req = Request(self, method, url.path, query, form_data, cookies)
        new_pre = None
        if not cookies.get("pk_pre"):
            new_pre = secrets.token_urlsafe(16)
            req.cookies["pk_pre"] = new_pre
        req.conn = connect(self.db_file)
        try:
            resp = self.dispatch(req)
        except PermissionError:
            resp = layout(req, "Not allowed", '<p class="msg bad">Only Admins can do this.</p>')
            resp.status = 403
        except C.DomainError as x:
            back = headers.get("Referer") or "/"
            back = urlparse(back)
            target = back.path + ("?" + "&".join(p for p in back.query.split("&") if not p.startswith(("ok=", "err="))) if back.query else "")
            resp = redirect(target.rstrip("?") or "/", err=str(x)) if method == "POST" else \
                layout(req, "Problem", error_box(str(x)))
        except C.FieldErrors as x:
            resp = layout(req, "Problem", error_box(" ".join(x.errors.values())))
            resp.status = 400
        except Exception:
            log.error("Unhandled error on %s %s\n%s", method, raw_path, traceback.format_exc())
            resp = layout(req, "Error", '<p class="msg bad">Something went wrong. Nothing was saved. '
                                        'Details are in the server log.</p>')
            resp.status = 500
        finally:
            req.conn.close()
        if new_pre:
            resp.headers.append(("Set-Cookie", f"pk_pre={new_pre}; Path=/; HttpOnly; SameSite=Lax"))
        for c in req.set_cookies:
            resp.headers.append(("Set-Cookie", c))
        resp.headers += [("X-Frame-Options", "DENY"), ("X-Content-Type-Options", "nosniff"),
                         ("Cache-Control", "no-store")]
        return resp

    def dispatch(self, req):
        if req.path == "/health":
            return Response(json.dumps({"ok": True}), ctype="application/json")
        token = self.unsign(req.cookies.get("pk_session"))
        if token:
            req.user = C.load_session(req.conn, token)
        for method, pat, fn, role in ROUTES:
            m = pat.match(req.path)
            if not m or method != req.method:
                continue
            req.params = m.groups()
            if req.method == "POST":
                expected = req.csrf
                if not expected or not hmac.compare_digest(req.f("_csrf"), expected):
                    return Response("Form expired or invalid (CSRF check failed). Go back, reload and try again.", 403,
                                    "text/plain; charset=utf-8")
            if role is not None:
                if not req.user:
                    if not C.has_users(req.conn):
                        return redirect("/setup")
                    return redirect("/login")
                if req.user["must_change"] and req.path not in ("/account/password", "/logout"):
                    return redirect("/account/password")
                if role == "admin" and not req.is_admin:
                    raise PermissionError()
            return fn(req)
        resp = layout(req, "Not found", "<p>No such page.</p>")
        resp.status = 404
        return resp


def make_handler(app):
    class Handler(BaseHTTPRequestHandler):
        server_version = "Plotkeeper"
        timeout = REQUEST_TIMEOUT  # seconds a client may stay silent before its connection is closed

        def _go(self, method):
            raw = (self.headers.get("Content-Length") or "0").strip()
            if not raw.isdigit():
                self.close_connection = True
                self.send_error(400, "Invalid Content-Length")
                return
            length = int(raw)
            if length > 1_000_000:
                self.close_connection = True
                self.send_error(413)
                return
            body = self.rfile.read(length) if length else b""
            resp = app.handle(method, self.path, self.headers, body)
            self.send_response(resp.status)
            for k, v in resp.headers:
                self.send_header(k, v)
            self.send_header("Content-Length", str(len(resp.body)))
            self.end_headers()
            self.wfile.write(resp.body)

        def do_GET(self):
            self._go("GET")

        def do_POST(self):
            self._go("POST")

        def log_message(self, fmt, *args):
            log.info("%s %s", self.address_string(), fmt % args)
    return Handler


REQUEST_TIMEOUT = 10
MAX_CONNECTIONS = 64


class BoundedServer(ThreadingHTTPServer):
    """One thread per connection, but never more than MAX_CONNECTIONS at once; extra connections are closed."""
    daemon_threads = True

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.slots = threading.BoundedSemaphore(MAX_CONNECTIONS)

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()


def serve(app, host, port):
    return BoundedServer((host, port), make_handler(app))
