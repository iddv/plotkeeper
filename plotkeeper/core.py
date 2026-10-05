"""Domain rules for Plotkeeper. Every function that changes data runs in one
transaction, validates before writing and records an audit entry."""
import datetime as dt
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
from zoneinfo import ZoneInfo

from .store import tx

SIZES = ("small", "standard", "large")
PREFERENCES = ("any",) + SIZES
PLOT_STATUSES = ("available", "offered", "occupied", "out_of_service", "retired")
METHODS = ("cash", "bank_transfer", "cheque", "card", "other")
REMOVE_REASONS = ("withdrew", "unreachable", "other")
RELEASE_REASONS = ("gave up", "moved", "removed by committee")
ROLES = ("admin", "coordinator")
DUE_STATUSES = ("Paid", "Partly paid", "Unpaid", "Overdue", "In credit")

DEFAULT_SETTINGS = {
    "garden_name": "Community Garden",
    "currency": "EUR",
    "timezone": "UTC",
    "fee.small": "4000",
    "fee.standard": "6000",
    "fee.large": "8000",
    "offers.expiry_days": "14",
    "seasons.due_date": "03-31",
    "waitlist.max_declines": "2",
    "waitlist.decline_policy": "keep_place",
    "fees.new_holder_charge": "full",
    "payments.overpayment": "reject",
    "plots.release_with_balance": "allow",
    "auth.session_hours": "8",
    "auth.max_failed": "5",
    "auth.lockout_minutes": "15",
    "fees.prorate_from": "start_date",
    "seasons.current_rule": "latest_year",
    "assign.direct_with_active_entry": "close_entry",
    "offers.valid_on_expiry_date": "true",
}
CHOICE_SETTINGS = {
    "waitlist.decline_policy": ("keep_place", "move_to_end"),
    "fees.new_holder_charge": ("full", "prorated"),
    "payments.overpayment": ("reject", "credit"),
    "plots.release_with_balance": ("allow", "block"),
    "fees.prorate_from": ("recorded_date", "start_date"),
    "seasons.current_rule": ("most_recently_opened", "latest_year"),
    "assign.direct_with_active_entry": ("close_entry", "refused"),
    "offers.valid_on_expiry_date": ("true", "false"),
}
INT_SETTINGS = {"offers.expiry_days": (1, 365), "waitlist.max_declines": (1, 99),
                "auth.session_hours": (1, 720), "auth.max_failed": (1, 100),
                "auth.lockout_minutes": (1, 1440)}


class DomainError(Exception):
    """A rule refused the action. The message is shown to the user."""


class FieldErrors(Exception):
    def __init__(self, errors):
        super().__init__("; ".join(f"{k}: {v}" for k, v in errors.items()))
        self.errors = errors


class DuplicateWarning(Exception):
    def __init__(self, matches):
        super().__init__("Possible duplicate")
        self.matches = matches


# ---------------------------------------------------------------- time & money

def utcnow():
    return dt.datetime.now(dt.timezone.utc)


def now_iso():
    return utcnow().strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def parse_iso(s):
    return dt.datetime.strptime(s, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=dt.timezone.utc)


def garden_tz(conn):
    name = os.environ.get("PLOTKEEPER_TIMEZONE") or get_setting(conn, "timezone")
    try:
        return ZoneInfo(name)
    except Exception:
        return ZoneInfo("UTC")


def today(conn):
    return utcnow().astimezone(garden_tz(conn)).date()


def local_ts(conn, iso, with_time=True):
    if not iso:
        return ""
    t = parse_iso(iso).astimezone(garden_tz(conn))
    return t.strftime("%Y-%m-%d %H:%M" if with_time else "%Y-%m-%d")


def local_date_to_iso(conn, d):
    """Midnight of a local date, as a UTC timestamp (used for backdated join dates)."""
    local = dt.datetime(d.year, d.month, d.day, tzinfo=garden_tz(conn))
    return local.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def parse_date(value, field="date", errors=None):
    try:
        return dt.date.fromisoformat((value or "").strip())
    except ValueError:
        if errors is not None:
            errors[field] = "Enter a date as YYYY-MM-DD"
            return None
        raise FieldErrors({field: "Enter a date as YYYY-MM-DD"})


AMOUNT_RE = re.compile(r"^\d+(\.\d{1,2})?$")
SIGNED_AMOUNT_RE = re.compile(r"^[+-]?\d+(\.\d{1,2})?$")
MAX_CENTS = 100_000_000_00  # 100 million: far above any garden fee, well inside SQLite's integer range


def parse_amount(value, signed=False):
    """Parse a decimal string into integer cents. Returns (cents, error)."""
    s = (value or "").strip().replace(",", "")
    if not (SIGNED_AMOUNT_RE if signed else AMOUNT_RE).match(s):
        if not signed and s.startswith("-"):
            return None, "Enter a positive amount"
        return None, "Enter an amount with at most 2 decimals, e.g. 40.00"
    neg = s.startswith("-")
    s = s.lstrip("+-")
    whole, _, frac = s.partition(".")
    cents = int(whole) * 100 + int((frac + "00")[:2])
    if cents == 0:
        return None, "Amount cannot be zero"
    if cents > MAX_CENTS:
        return None, f"Amount is too large (at most {fmt_money(MAX_CENTS)})"
    return (-cents if neg else cents), None


def fmt_money(cents):
    cents = cents or 0
    sign = "-" if cents < 0 else ""
    return f"{sign}{abs(cents) // 100}.{abs(cents) % 100:02d}"


def prorate(fee_cents, start_month):
    """fee x remaining months / 12, months counting the acceptance month through
    December, rounded half-up to the cent."""
    months = 12 - start_month + 1
    q, r = divmod(fee_cents * months, 12)
    return q + (1 if r * 2 >= 12 else 0)


# ---------------------------------------------------------------- settings & audit

# Operator settings that an environment variable overrides everywhere when set: key -> variable.
ENV_OVERRIDES = {
    "fees.prorate_from": "FEES_PRORATE_FROM",
    "seasons.current_rule": "SEASONS_CURRENT_RULE",
    "assign.direct_with_active_entry": "ASSIGN_DIRECT_WITH_ACTIVE_ENTRY",
    "offers.valid_on_expiry_date": "OFFERS_VALID_ON_EXPIRY_DATE",
}


def _env_override(key):
    value = os.environ.get(ENV_OVERRIDES.get(key, ""), "").strip()
    return value if value in CHOICE_SETTINGS.get(key, ()) else None


def get_settings(conn):
    s = dict(DEFAULT_SETTINGS)
    s.update({r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM settings")})
    for key in ENV_OVERRIDES:
        s[key] = _env_override(key) or s[key]
    return s


def get_setting(conn, key):
    override = _env_override(key)
    if override:
        return override
    row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else DEFAULT_SETTINGS[key]


def _set_setting(conn, key, value):
    conn.execute("INSERT INTO settings(key, value) VALUES (?, ?) "
                 "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(value)))


def fee_for(conn, size):
    return int(get_setting(conn, f"fee.{size}"))


def audit(conn, actor, action, record_type, record_id, summary="", before=None, after=None,
          plot_id=None, gardener_id=None):
    if record_type == "plot" and plot_id is None:
        plot_id = record_id
    if record_type == "gardener" and gardener_id is None:
        gardener_id = record_id
    conn.execute(
        "INSERT INTO audit(at, user_id, action, record_type, record_id, plot_id, gardener_id,"
        " summary, before, after) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (now_iso(), actor["id"] if actor else None, action, record_type, record_id, plot_id,
         gardener_id, summary,
         json.dumps(before, default=str) if before is not None else None,
         json.dumps(after, default=str) if after is not None else None))


def _row(r):
    return dict(r) if r is not None else None


def require_admin(actor):
    if not actor or actor["role"] != "admin":
        raise PermissionError("Admins only")


def update_settings(conn, actor, values):
    require_admin(actor)
    errors, clean = {}, {}
    for key, raw in values.items():
        raw = (raw or "").strip()
        if key == "garden_name":
            if not raw or len(raw) > 100:
                errors[key] = "Enter a garden name (up to 100 characters)"
            clean[key] = raw
        elif key.startswith("fee."):
            cents, err = parse_amount(raw)
            if err:
                errors[key] = err
            clean[key] = str(cents)
        elif key in CHOICE_SETTINGS:
            if raw not in CHOICE_SETTINGS[key]:
                errors[key] = "Choose one of: " + ", ".join(CHOICE_SETTINGS[key])
            clean[key] = raw
        elif key in INT_SETTINGS:
            lo, hi = INT_SETTINGS[key]
            if not raw.isdigit() or not lo <= int(raw) <= hi:
                errors[key] = f"Enter a whole number from {lo} to {hi}"
            clean[key] = raw
        elif key == "seasons.due_date":
            try:
                dt.date.fromisoformat("2001-" + raw)
            except ValueError:
                errors[key] = "Enter month and day as MM-DD, e.g. 03-31"
            clean[key] = raw
        else:
            errors[key] = "Unknown setting"
    if errors:
        raise FieldErrors(errors)
    with tx(conn):
        current = get_settings(conn)
        for key, value in clean.items():
            if current.get(key) != value:
                _set_setting(conn, key, value)
                audit(conn, actor, "setting.change", "setting", None, key,
                      {key: current.get(key)}, {key: value})


# ---------------------------------------------------------------- users & auth

def hash_password(pw):
    salt = secrets.token_bytes(16)
    h = hashlib.scrypt(pw.encode(), salt=salt, n=2 ** 14, r=8, p=1, dklen=32)
    return f"scrypt${salt.hex()}${h.hex()}"


def verify_password(pw, stored):
    try:
        _, salt, h = stored.split("$")
        calc = hashlib.scrypt(pw.encode(), salt=bytes.fromhex(salt), n=2 ** 14, r=8, p=1, dklen=32)
        return hmac.compare_digest(calc.hex(), h)
    except Exception:
        return False


def _check_new_password(pw, pw2, errors, field="password"):
    if len(pw or "") < 12:
        errors[field] = "Password must be at least 12 characters"
    elif pw != pw2:
        errors[field + "2"] = "The two passwords do not match"


def _check_username(conn, username, errors):
    if not re.match(r"^[A-Za-z0-9_.-]{2,40}$", username or ""):
        errors["username"] = "Use 2-40 letters, digits, dots, dashes or underscores"
    elif conn.execute("SELECT 1 FROM users WHERE username=?", (username,)).fetchone():
        errors["username"] = f"Username {username} is already taken"


def has_users(conn):
    return conn.execute("SELECT 1 FROM users LIMIT 1").fetchone() is not None


def new_setup_code(conn):
    code = "-".join(secrets.token_hex(2).upper() for _ in range(3))
    with tx(conn):
        conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES ('setup_code', ?)",
                     (hashlib.sha256(code.encode()).hexdigest(),))
    return code


def setup(conn, code, garden_name, currency, timezone, username, password, password2):
    with tx(conn):
        row = conn.execute("SELECT value FROM meta WHERE key='setup_code'").fetchone()
        given = hashlib.sha256((code or "").strip().upper().encode()).hexdigest()
        if has_users(conn) or not row or not hmac.compare_digest(row["value"], given):
            raise DomainError("Invalid setup code")
        errors = {}
        if not (garden_name or "").strip():
            errors["garden_name"] = "Enter the garden name"
        if not re.match(r"^[A-Z]{3}$", (currency or "").strip().upper()):
            errors["currency"] = "Enter a 3-letter currency code, e.g. EUR"
        try:
            ZoneInfo((timezone or "").strip())
        except Exception:
            errors["timezone"] = "Unknown time zone, e.g. Europe/London"
        _check_username(conn, (username or "").strip(), errors)
        _check_new_password(password, password2, errors)
        if errors:
            raise FieldErrors(errors)
        _set_setting(conn, "garden_name", garden_name.strip())
        _set_setting(conn, "currency", currency.strip().upper())
        _set_setting(conn, "timezone", timezone.strip())
        cur = conn.execute("INSERT INTO users(username, role, pw_hash, created_at) VALUES (?,?,?,?)",
                           (username.strip(), "admin", hash_password(password), now_iso()))
        conn.execute("DELETE FROM meta WHERE key='setup_code'")
        actor = {"id": cur.lastrowid, "role": "admin"}
        audit(conn, actor, "setup", "user", cur.lastrowid, f"First admin {username.strip()} created")
        return cur.lastrowid


def authenticate(conn, username, password):
    """Returns the user row, or raises DomainError with a generic message."""
    s = get_settings(conn)
    u = conn.execute("SELECT * FROM users WHERE username=?", ((username or "").strip(),)).fetchone()
    if not u:
        raise DomainError("Wrong username or password")
    if u["locked_until"] and parse_iso(u["locked_until"]) > utcnow():
        raise DomainError("Too many failed attempts. Try again later.")
    ok = u["active"] and verify_password(password or "", u["pw_hash"])
    error = None
    with tx(conn):  # the failure count must be committed, so errors are raised after the transaction
        u = conn.execute("SELECT * FROM users WHERE id=?", (u["id"],)).fetchone()
        if not ok:
            failed = u["failed"] + 1
            locked = None
            if failed >= int(s["auth.max_failed"]):
                locked = (utcnow() + dt.timedelta(minutes=int(s["auth.lockout_minutes"]))
                          ).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
                failed = 0
            conn.execute("UPDATE users SET failed=?, locked_until=? WHERE id=?", (failed, locked, u["id"]))
            if locked:
                audit(conn, None, "user.locked", "user", u["id"], f"{u['username']} locked out")
                error = "Too many failed attempts. Try again later."
            else:
                error = "Wrong username or password"
        else:
            conn.execute("UPDATE users SET failed=0, locked_until=NULL WHERE id=?", (u["id"],))
    if error:
        raise DomainError(error)
    return conn.execute("SELECT * FROM users WHERE id=?", (u["id"],)).fetchone()


def temp_password():
    return secrets.token_urlsafe(12)


def create_user(conn, actor, username, role):
    require_admin(actor)
    username = (username or "").strip()
    errors = {}
    _check_username(conn, username, errors)
    if role not in ROLES:
        errors["role"] = "Choose a role"
    if errors:
        raise FieldErrors(errors)
    pw = temp_password()
    with tx(conn):
        cur = conn.execute("INSERT INTO users(username, role, pw_hash, must_change, created_at) "
                           "VALUES (?,?,?,1,?)", (username, role, hash_password(pw), now_iso()))
        audit(conn, actor, "user.create", "user", cur.lastrowid, f"{username} ({role})",
              None, {"username": username, "role": role})
    return cur.lastrowid, pw


def _other_active_admins(conn, uid):
    return conn.execute("SELECT count(*) FROM users WHERE role='admin' AND active=1 AND id<>?",
                        (uid,)).fetchone()[0]


def set_role(conn, actor, uid, role):
    require_admin(actor)
    if role not in ROLES:
        raise FieldErrors({"role": "Choose a role"})
    with tx(conn):
        u = conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
        if not u:
            raise DomainError("No such user")
        if u["role"] == "admin" and role != "admin" and u["active"] and not _other_active_admins(conn, uid):
            raise DomainError("You cannot demote the last active Admin")
        conn.execute("UPDATE users SET role=? WHERE id=?", (role, uid))
        audit(conn, actor, "user.role", "user", uid, u["username"], {"role": u["role"]}, {"role": role})


def set_active(conn, actor, uid, active):
    require_admin(actor)
    with tx(conn):
        u = conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
        if not u:
            raise DomainError("No such user")
        if not active and u["role"] == "admin" and not _other_active_admins(conn, uid):
            raise DomainError("You cannot deactivate the last active Admin")
        conn.execute("UPDATE users SET active=? WHERE id=?", (1 if active else 0, uid))
        if not active:
            conn.execute("DELETE FROM sessions WHERE user_id=?", (uid,))
        audit(conn, actor, "user.activate" if active else "user.deactivate", "user", uid, u["username"],
              {"active": u["active"]}, {"active": int(bool(active))})


def reset_password(conn, actor, uid):
    require_admin(actor)
    pw = temp_password()
    with tx(conn):
        u = conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
        if not u:
            raise DomainError("No such user")
        conn.execute("UPDATE users SET pw_hash=?, must_change=1, failed=0, locked_until=NULL WHERE id=?",
                     (hash_password(pw), uid))
        conn.execute("DELETE FROM sessions WHERE user_id=?", (uid,))
        audit(conn, actor, "user.reset_password", "user", uid, u["username"])
    return pw


def change_password(conn, uid, current, new, new2, keep_token=None):
    errors = {}
    u = conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if not verify_password(current or "", u["pw_hash"]):
        errors["current"] = "Current password is wrong"
    _check_new_password(new, new2, errors, "new")
    if not errors and new == current:
        errors["new"] = "Choose a password different from the current one"
    if errors:
        raise FieldErrors(errors)
    with tx(conn):
        conn.execute("UPDATE users SET pw_hash=?, must_change=0 WHERE id=?", (hash_password(new), uid))
        conn.execute("DELETE FROM sessions WHERE user_id=? AND token IS NOT ?", (uid, keep_token))
        audit(conn, {"id": uid}, "user.change_password", "user", uid, u["username"])


# sessions -----------------------------------------------------------------

def create_session(conn, uid):
    token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(24)
    with tx(conn):
        conn.execute("INSERT INTO sessions(token, user_id, csrf, last_seen) VALUES (?,?,?,?)",
                     (token, uid, csrf, now_iso()))
    return token


def load_session(conn, token):
    if not token:
        return None
    row = conn.execute(
        "SELECT s.token, s.csrf, s.last_seen, u.* FROM sessions s JOIN users u ON u.id=s.user_id "
        "WHERE s.token=?", (token,)).fetchone()
    if not row:
        return None
    hours = int(get_setting(conn, "auth.session_hours"))
    if not row["active"] or parse_iso(row["last_seen"]) < utcnow() - dt.timedelta(hours=hours):
        with tx(conn):
            conn.execute("DELETE FROM sessions WHERE token=?", (token,))
        return None
    with tx(conn):
        conn.execute("UPDATE sessions SET last_seen=? WHERE token=?", (now_iso(), token))
    return row


def end_session(conn, token):
    with tx(conn):
        conn.execute("DELETE FROM sessions WHERE token=?", (token,))


# ---------------------------------------------------------------- plots

def _clean_plot(conn, data, exclude_id=None):
    errors = {}
    code = (data.get("code") or "").strip()
    size = (data.get("size") or "").strip()
    area_raw = (data.get("area") or "").strip()
    notes = (data.get("notes") or "").strip()
    area = None
    if not 1 <= len(code) <= 20:
        errors["code"] = "Enter a plot code of 1-20 characters"
    elif conn.execute("SELECT 1 FROM plots WHERE code=? AND id IS NOT ?", (code, exclude_id)).fetchone():
        errors["code"] = f"Plot code {code} already exists"
    if size not in SIZES:
        errors["size"] = "Choose small, standard or large"
    if area_raw:
        try:
            area = float(area_raw)
            if area <= 0 or area > 100000:
                raise ValueError
        except ValueError:
            errors["area"] = "Enter the area in m² as a positive number"
    if errors:
        raise FieldErrors(errors)
    return {"code": code, "size": size, "area": area, "notes": notes}


def get_plot(conn, pid):
    p = conn.execute("SELECT * FROM plots WHERE id=?", (pid,)).fetchone()
    if not p:
        raise DomainError("No such plot")
    return p


def add_plot(conn, actor, data):
    with tx(conn):
        d = _clean_plot(conn, data)
        cur = conn.execute("INSERT INTO plots(code, size, area, notes, created_at) VALUES (?,?,?,?,?)",
                           (d["code"], d["size"], d["area"], d["notes"], now_iso()))
        audit(conn, actor, "plot.create", "plot", cur.lastrowid, f"Plot {d['code']} added", None, d)
        return cur.lastrowid


def _lock_plot(conn, pid, version):
    p = get_plot(conn, pid)
    if version is not None and str(p["version"]) != str(version):
        raise DomainError("This plot changed since you opened it. Reload and try again.")
    return p


def _set_plot_status(conn, pid, status, reason=""):
    conn.execute("UPDATE plots SET status=?, status_reason=?, version=version+1 WHERE id=?",
                 (status, reason, pid))


def edit_plot(conn, actor, pid, version, data):
    with tx(conn):
        p = _lock_plot(conn, pid, version)
        d = _clean_plot(conn, data, exclude_id=pid)
        before = {k: p[k] for k in d}
        changed = {k: v for k, v in d.items() if before[k] != v}
        if not changed:
            return
        conn.execute("UPDATE plots SET code=?, size=?, area=?, notes=?, version=version+1 WHERE id=?",
                     (d["code"], d["size"], d["area"], d["notes"], pid))
        audit(conn, actor, "plot.edit", "plot", pid, "Edited " + ", ".join(changed),
              {k: before[k] for k in changed}, changed)


def change_plot_status(conn, actor, pid, version, action, reason):
    """action: out_of_service | return | retire"""
    reason = (reason or "").strip()
    with tx(conn):
        p = _lock_plot(conn, pid, version)
        if action in ("out_of_service", "retire") and p["status"] in ("occupied", "offered"):
            raise DomainError("Release the holder or withdraw the offer first")
        if action in ("out_of_service", "retire") and not reason:
            raise FieldErrors({"reason": "Enter a reason"})
        allowed = {"out_of_service": ("available",), "return": ("out_of_service",),
                   "retire": ("available", "out_of_service")}[action]
        if p["status"] not in allowed:
            raise DomainError(f"This action is not possible while the plot is {status_label(p['status'])}")
        new = {"out_of_service": "out_of_service", "return": "available", "retire": "retired"}[action]
        _set_plot_status(conn, pid, new, reason if new != "available" else "")
        audit(conn, actor, f"plot.{action}", "plot", pid,
              f"{status_label(p['status'])} → {status_label(new)}" + (f": {reason}" if reason else ""),
              {"status": p["status"]}, {"status": new, "reason": reason})


def status_label(s):
    return {"out_of_service": "Out of service"}.get(s, (s or "").capitalize())


def current_assignment(conn, pid=None, gid=None):
    col, val = ("plot_id", pid) if pid is not None else ("gardener_id", gid)
    return conn.execute(
        f"SELECT a.*, g.name, p.code, p.size FROM assignments a JOIN gardeners g ON g.id=a.gardener_id "
        f"JOIN plots p ON p.id=a.plot_id WHERE a.{col}=? AND a.end_date IS NULL", (val,)).fetchone()


def open_offer_for_plot(conn, pid):
    return conn.execute(
        "SELECT o.*, g.name, g.id AS gardener_id, g.email, g.phone FROM offers o "
        "JOIN waitlist w ON w.id=o.entry_id JOIN gardeners g ON g.id=w.gardener_id "
        "WHERE o.plot_id=? AND o.status='open'", (pid,)).fetchone()


def plot_counts(conn):
    counts = {s: 0 for s in PLOT_STATUSES}
    for r in conn.execute("SELECT status, count(*) n FROM plots GROUP BY status"):
        counts[r["status"]] = r["n"]
    return counts


def list_plots(conn, status="", size="", q="", include_retired=False):
    sql = ("SELECT p.*, g.name AS holder, g.id AS holder_id, a.start_date FROM plots p "
           "LEFT JOIN assignments a ON a.plot_id=p.id AND a.end_date IS NULL "
           "LEFT JOIN gardeners g ON g.id=a.gardener_id WHERE 1=1")
    args = []
    if status:
        sql += " AND p.status=?"
        args.append(status)
    elif not include_retired:
        sql += " AND p.status<>'retired'"
    if size:
        sql += " AND p.size=?"
        args.append(size)
    if q:
        sql += " AND (p.code LIKE ? OR g.name LIKE ?)"
        args += [f"%{q}%", f"%{q}%"]
    return conn.execute(sql + " ORDER BY p.code COLLATE NOCASE", args).fetchall()


def last_release_date(conn, pid):
    r = conn.execute("SELECT max(end_date) d FROM assignments WHERE plot_id=? AND end_date IS NOT NULL",
                     (pid,)).fetchone()
    return dt.date.fromisoformat(r["d"]) if r["d"] else None


# ---------------------------------------------------------------- gardeners

def _clean_gardener(data):
    d = {k: (data.get(k) or "").strip() for k in ("name", "email", "phone", "address", "notes")}
    errors = {}
    if not d["name"]:
        errors["name"] = "Enter a name"
    if not d["email"] and not d["phone"]:
        errors["email"] = "Enter an email or a phone number"
    elif d["email"] and not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", d["email"]):
        errors["email"] = "Enter a valid email address"
    if errors:
        raise FieldErrors(errors)
    return d


def _phone_key(p):
    return re.sub(r"\D", "", p or "")


def find_duplicates(conn, email, phone, exclude_id=None):
    out = []
    pk = _phone_key(phone)
    for g in conn.execute("SELECT * FROM gardeners WHERE id IS NOT ?", (exclude_id,)):
        if (email and g["email"] and g["email"].lower() == email.lower()) or \
                (pk and len(pk) >= 6 and _phone_key(g["phone"]) == pk):
            out.append(g)
    return out


def get_gardener(conn, gid):
    g = conn.execute("SELECT * FROM gardeners WHERE id=?", (gid,)).fetchone()
    if not g:
        raise DomainError("No such gardener")
    return g


def add_gardener(conn, actor, data, allow_duplicate=False):
    d = _clean_gardener(data)
    with tx(conn):
        dups = find_duplicates(conn, d["email"], d["phone"])
        if dups and not allow_duplicate:
            raise DuplicateWarning(dups)
        cur = conn.execute("INSERT INTO gardeners(name, email, phone, address, notes, created_at) "
                           "VALUES (?,?,?,?,?,?)", (d["name"], d["email"], d["phone"], d["address"],
                                                    d["notes"], now_iso()))
        audit(conn, actor, "gardener.create", "gardener", cur.lastrowid, f"{d['name']} added", None, d)
        return cur.lastrowid


def edit_gardener(conn, actor, gid, version, data):
    d = _clean_gardener(data)
    with tx(conn):
        g = get_gardener(conn, gid)
        if version is not None and str(g["version"]) != str(version):
            raise DomainError("This gardener changed since you opened it. Reload and try again.")
        changed = {k: v for k, v in d.items() if g[k] != v}
        if not changed:
            return
        conn.execute("UPDATE gardeners SET name=?, email=?, phone=?, address=?, notes=?, "
                     "version=version+1 WHERE id=?",
                     (d["name"], d["email"], d["phone"], d["address"], d["notes"], gid))
        audit(conn, actor, "gardener.edit", "gardener", gid, "Edited " + ", ".join(changed),
              {k: g[k] for k in changed}, changed)


def gardener_total_balance(conn, gid):
    return conn.execute("SELECT coalesce(sum(amount),0) FROM ledger WHERE gardener_id=?",
                        (gid,)).fetchone()[0]


def archive_gardener(conn, actor, gid, archived=True):
    with tx(conn):
        g = get_gardener(conn, gid)
        if archived:
            a = current_assignment(conn, gid=gid)
            if a:
                raise DomainError(f"Cannot archive: {g['name']} holds plot {a['code']}")
            if active_entry(conn, gid):
                raise DomainError(f"Cannot archive: {g['name']} is on the waiting list")
            bal = gardener_total_balance(conn, gid)
            if bal:
                raise DomainError(f"Cannot archive: balance is {fmt_money(bal)}, it must be 0.00")
        conn.execute("UPDATE gardeners SET archived=?, version=version+1 WHERE id=?", (int(archived), gid))
        audit(conn, actor, "gardener.archive" if archived else "gardener.unarchive", "gardener", gid,
              g["name"])


def list_gardeners(conn, q="", include_archived=False):
    sql = ("SELECT g.*, p.code AS plot_code, p.id AS plot_id FROM gardeners g "
           "LEFT JOIN assignments a ON a.gardener_id=g.id AND a.end_date IS NULL "
           "LEFT JOIN plots p ON p.id=a.plot_id WHERE 1=1")
    args = []
    if q:
        sql += " AND (g.name LIKE ? OR g.email LIKE ? OR g.phone LIKE ?)"
        args += [f"%{q}%"] * 3
    if not include_archived and not q:
        sql += " AND g.archived=0"
    return conn.execute(sql + " ORDER BY g.name COLLATE NOCASE", args).fetchall()


# ---------------------------------------------------------------- waiting list

def active_entry(conn, gid):
    return conn.execute("SELECT * FROM waitlist WHERE gardener_id=? AND status IN ('active','offered')",
                        (gid,)).fetchone()


def waiting_list(conn):
    """Active entries (including those with an open offer) in order. Positions are derived."""
    rows = conn.execute(
        "SELECT w.*, g.name, g.email, g.phone FROM waitlist w JOIN gardeners g ON g.id=w.gardener_id "
        "WHERE w.status IN ('active','offered') ORDER BY w.joined_at, w.id").fetchall()
    return [dict(r, position=i + 1) for i, r in enumerate(rows)]


def entry_position(conn, eid):
    for e in waiting_list(conn):
        if e["id"] == eid:
            return e["position"]
    return None


def add_to_waitlist(conn, actor, gid, preference, joined=None):
    errors = {}
    if preference not in PREFERENCES:
        errors["preference"] = "Choose a size preference"
    jd = None
    if joined:
        jd = parse_date(joined, "joined", errors)
        if jd and jd > today(conn):
            errors["joined"] = "Join date cannot be in the future"
    if errors:
        raise FieldErrors(errors)
    with tx(conn):
        g = get_gardener(conn, gid)
        if g["archived"]:
            raise DomainError(f"{g['name']} is archived")
        a = current_assignment(conn, gid=gid)
        if a:
            raise DomainError(f"Already holds plot {a['code']}")
        e = active_entry(conn, gid)
        if e:
            raise DomainError(f"Already on the list at position {entry_position(conn, e['id'])}")
        now = now_iso()
        joined_at = local_date_to_iso(conn, jd) if jd and jd < today(conn) else now
        cur = conn.execute("INSERT INTO waitlist(gardener_id, preference, joined_at, created_at) "
                           "VALUES (?,?,?,?)", (gid, preference, joined_at, now))
        audit(conn, actor, "waitlist.add", "waitlist", cur.lastrowid,
              f"{g['name']} joined the waiting list ({preference})", None,
              {"preference": preference, "joined_at": joined_at}, gardener_id=gid)
        return cur.lastrowid


def _get_entry(conn, eid):
    e = conn.execute("SELECT w.*, g.name FROM waitlist w JOIN gardeners g ON g.id=w.gardener_id "
                     "WHERE w.id=?", (eid,)).fetchone()
    if not e:
        raise DomainError("No such waiting-list entry")
    return e


def change_preference(conn, actor, eid, preference):
    if preference not in PREFERENCES:
        raise FieldErrors({"preference": "Choose a size preference"})
    with tx(conn):
        e = _get_entry(conn, eid)
        if e["status"] not in ("active", "offered"):
            raise DomainError("This entry is closed")
        conn.execute("UPDATE waitlist SET preference=? WHERE id=?", (preference, eid))
        audit(conn, actor, "waitlist.preference", "waitlist", eid, f"{e['name']}: preference changed",
              {"preference": e["preference"]}, {"preference": preference}, gardener_id=e["gardener_id"])


def remove_from_waitlist(conn, actor, eid, reason, note=""):
    if reason not in REMOVE_REASONS:
        raise FieldErrors({"reason": "Choose a reason"})
    with tx(conn):
        e = _get_entry(conn, eid)
        if e["status"] == "offered":
            raise DomainError("This person has an open offer. Record its outcome first.")
        if e["status"] != "active":
            raise DomainError("This entry is already closed")
        text = reason + (f": {note.strip()}" if note and note.strip() else "")
        conn.execute("UPDATE waitlist SET status='removed', close_reason=?, closed_at=? WHERE id=?",
                     (text, now_iso(), eid))
        audit(conn, actor, "waitlist.remove", "waitlist", eid, f"{e['name']} removed: {text}",
              {"status": "active"}, {"status": "removed", "reason": text}, gardener_id=e["gardener_id"])


def next_in_line(conn, size):
    return conn.execute(
        "SELECT w.*, g.name, g.email, g.phone FROM waitlist w JOIN gardeners g ON g.id=w.gardener_id "
        "WHERE w.status='active' AND w.preference IN ('any', ?) "
        "AND NOT EXISTS (SELECT 1 FROM assignments a WHERE a.gardener_id=w.gardener_id AND a.end_date IS NULL) "
        "ORDER BY w.joined_at, w.id LIMIT 1", (size,)).fetchone()


# ---------------------------------------------------------------- offers & assignments

def preview_offer(conn, pid):
    p = get_plot(conn, pid)
    if p["status"] != "available":
        raise DomainError(f"Only Available plots can be offered (this one is {status_label(p['status'])})")
    e = next_in_line(conn, p["size"])
    if not e:
        raise DomainError(f"No one on the waiting list matches a {p['size']} plot")
    return p, e


def make_offer(conn, actor, pid, version, entry_id):
    with tx(conn):
        p = get_plot(conn, pid)
        if p["status"] == "offered":
            o = open_offer_for_plot(conn, pid)
            raise DomainError(f"This plot was just offered to {o['name'] if o else 'someone else'}")
        if p["status"] == "occupied":
            a = current_assignment(conn, pid=pid)
            raise DomainError(f"This plot was just assigned to {a['name'] if a else 'someone else'}")
        _lock_plot(conn, pid, version)
        if p["status"] != "available":
            raise DomainError("Only Available plots can be offered")
        e = next_in_line(conn, p["size"])
        if not e:
            raise DomainError(f"No one on the waiting list matches a {p['size']} plot")
        if str(e["id"]) != str(entry_id):
            raise DomainError("The waiting list changed since you opened this page. Review the next person again.")
        d = today(conn)
        expires = d + dt.timedelta(days=int(get_setting(conn, "offers.expiry_days")))
        cur = conn.execute("INSERT INTO offers(plot_id, entry_id, offered_on, expires_on, user_id, created_at) "
                           "VALUES (?,?,?,?,?,?)", (pid, e["id"], d.isoformat(), expires.isoformat(),
                                                   actor["id"], now_iso()))
        conn.execute("UPDATE waitlist SET status='offered' WHERE id=?", (e["id"],))
        _set_plot_status(conn, pid, "offered")
        audit(conn, actor, "offer.create", "offer", cur.lastrowid,
              f"Plot {p['code']} offered to {e['name']}, expires {expires}", None,
              {"entry_id": e["id"], "expires_on": expires.isoformat()}, plot_id=pid, gardener_id=e["gardener_id"])
        return cur.lastrowid


def get_offer(conn, oid):
    o = conn.execute("SELECT o.*, w.gardener_id, g.name, p.code, p.size FROM offers o "
                     "JOIN waitlist w ON w.id=o.entry_id JOIN gardeners g ON g.id=w.gardener_id "
                     "JOIN plots p ON p.id=o.plot_id WHERE o.id=?", (oid,)).fetchone()
    if not o:
        raise DomainError("No such offer")
    return o


def resolve_offer(conn, actor, oid, outcome, start_date=None):
    """outcome: accepted | declined | expired | withdrawn"""
    if outcome not in ("accepted", "declined", "expired", "withdrawn"):
        raise DomainError("Unknown outcome")
    with tx(conn):
        o = get_offer(conn, oid)
        if o["status"] != "open":
            raise DomainError(f"This offer was already recorded as {o['status']}")
        p = get_plot(conn, o["plot_id"])
        if p["status"] != "offered":
            raise DomainError("This plot changed since you opened it. Reload and try again.")
        conn.execute("UPDATE offers SET status=?, resolved_at=? WHERE id=?", (outcome, now_iso(), oid))
        summary = f"Offer of {o['code']} to {o['name']}: {outcome}"
        if outcome == "accepted":
            sd = parse_date(start_date, "start_date")
            last = last_release_date(conn, p["id"])
            if last and sd < last:
                raise FieldErrors({"start_date": f"Start date cannot be before the last release ({last})"})
            if current_assignment(conn, gid=o["gardener_id"]):
                raise DomainError(f"{o['name']} already holds a plot")
            conn.execute("UPDATE waitlist SET status='placed', close_reason='placed', closed_at=? WHERE id=?",
                         (now_iso(), o["entry_id"]))
            _start_assignment(conn, actor, p, o["gardener_id"], sd, "offer")
        elif outcome == "withdrawn":
            conn.execute("UPDATE waitlist SET status='active' WHERE id=?", (o["entry_id"],))
            _set_plot_status(conn, p["id"], "available")
        else:
            e = _get_entry(conn, o["entry_id"])
            declines = e["declines"] + 1
            if declines >= int(get_setting(conn, "waitlist.max_declines")):
                conn.execute("UPDATE waitlist SET status='removed', declines=?, close_reason='declined twice', "
                             "closed_at=? WHERE id=?", (declines, now_iso(), e["id"]))
                summary += "; removed from list (declined twice)"
            elif get_setting(conn, "waitlist.decline_policy") == "move_to_end":
                conn.execute("UPDATE waitlist SET status='active', declines=?, joined_at=? WHERE id=?",
                             (declines, now_iso(), e["id"]))
                summary += "; moved to end of list"
            else:
                conn.execute("UPDATE waitlist SET status='active', declines=? WHERE id=?", (declines, e["id"]))
                summary += "; keeps place"
            _set_plot_status(conn, p["id"], "available")
        audit(conn, actor, f"offer.{outcome}", "offer", oid, summary, {"status": "open"},
              {"status": outcome, "start_date": start_date}, plot_id=p["id"], gardener_id=o["gardener_id"])


def _start_assignment(conn, actor, plot, gid, start, via, note=""):
    cur = conn.execute("INSERT INTO assignments(plot_id, gardener_id, start_date, via, note, created_at) "
                       "VALUES (?,?,?,?,?,?)", (plot["id"], gid, start.isoformat(), via, note, now_iso()))
    aid = cur.lastrowid
    _set_plot_status(conn, plot["id"], "occupied")
    g = get_gardener(conn, gid)
    audit(conn, actor, "assignment.start", "assignment", aid,
          f"{g['name']} holds {plot['code']} from {start}" + (f" (direct: {note})" if via == "direct" else ""),
          None, {"start_date": start.isoformat(), "via": via, "note": note}, plot_id=plot["id"], gardener_id=gid)
    season = current_season(conn)
    if season and not season["closed_at"]:
        fee = season[f"fee_{plot['size']}"]
        if get_setting(conn, "fees.new_holder_charge") == "prorated":
            basis = today(conn) if get_setting(conn, "fees.prorate_from") == "recorded_date" else start
            month = basis.month if basis.year == season["year"] else (1 if basis.year < season["year"] else 13)
            fee = prorate(fee, month) if month <= 12 else 0
        if fee > 0:
            _insert_charge(conn, actor, gid, season, aid, fee, start if start.year == season["year"] else today(conn),
                           f"Fee {season['year']} plot {plot['code']}")
    return aid


def _insert_charge(conn, actor, gid, season, aid, amount, date, reason):
    cur = conn.execute(
        "INSERT OR IGNORE INTO ledger(gardener_id, season_id, kind, amount, entry_date, reason, assignment_id, "
        "user_id, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
        (gid, season["id"], "charge", amount, date.isoformat(), reason, aid, actor["id"], now_iso()))
    if cur.rowcount:
        audit(conn, actor, "ledger.charge", "ledger", cur.lastrowid, f"{reason}: {fmt_money(amount)}",
              None, {"amount": amount}, gardener_id=gid)
    return cur.rowcount


def direct_assign(conn, actor, pid, version, gid, start_date, reason):
    require_admin(actor)
    errors = {}
    sd = parse_date(start_date, "start_date", errors)
    if not (reason or "").strip():
        errors["reason"] = "Enter the reason for bypassing the waiting list"
    if not gid:
        errors["gardener_id"] = "Choose a gardener"
    if errors:
        raise FieldErrors(errors)
    with tx(conn):
        p = _lock_plot(conn, pid, version)
        if p["status"] != "available":
            raise DomainError("Only Available plots can be assigned")
        g = get_gardener(conn, gid)
        a = current_assignment(conn, gid=gid)
        if a:
            raise DomainError(f"{g['name']} already holds plot {a['code']}")
        last = last_release_date(conn, pid)
        if last and sd < last:
            raise FieldErrors({"start_date": f"Start date cannot be before the last release ({last})"})
        e = active_entry(conn, gid)
        if e:
            if e["status"] == "offered":
                raise DomainError(f"{g['name']} has an open offer for another plot")
            if get_setting(conn, "assign.direct_with_active_entry") == "refused":
                raise DomainError(f"{g['name']} is on the waiting list at position {entry_position(conn, e['id'])}; "
                                  f"remove the entry before assigning directly")
            conn.execute("UPDATE waitlist SET status='placed', close_reason='placed (direct assign)', "
                         "closed_at=? WHERE id=?", (now_iso(), e["id"]))
        return _start_assignment(conn, actor, p, gid, sd, "direct", reason.strip())


def release_plot(conn, actor, pid, version, end_date, reason):
    errors = {}
    ed = parse_date(end_date, "end_date", errors)
    if reason not in RELEASE_REASONS:
        errors["reason"] = "Choose a reason"
    if errors:
        raise FieldErrors(errors)
    with tx(conn):
        p = _lock_plot(conn, pid, version)
        a = current_assignment(conn, pid=pid)
        if p["status"] != "occupied" or not a:
            raise DomainError("This plot is not occupied")
        if ed < dt.date.fromisoformat(a["start_date"]):
            raise FieldErrors({"end_date": f"End date cannot be before the start date ({a['start_date']})"})
        if get_setting(conn, "plots.release_with_balance") == "block":
            for s in conn.execute("SELECT s.year, sum(l.amount) bal FROM ledger l JOIN seasons s ON s.id=l.season_id "
                                  "WHERE l.gardener_id=? GROUP BY s.id HAVING bal>0 ORDER BY s.year",
                                  (a["gardener_id"],)):
                raise DomainError(f"{a['name']} owes {fmt_money(s['bal'])} for {s['year']}; "
                                  f"record payment or adjustment first")
        conn.execute("UPDATE assignments SET end_date=?, end_reason=? WHERE id=?", (ed.isoformat(), reason, a["id"]))
        _set_plot_status(conn, pid, "available")
        audit(conn, actor, "assignment.end", "assignment", a["id"],
              f"{a['name']} released {p['code']} on {ed}: {reason}", {"end_date": None},
              {"end_date": ed.isoformat(), "reason": reason}, plot_id=pid, gardener_id=a["gardener_id"])


def offer_is_expired(conn, expires_on):
    t = today(conn).isoformat()
    if get_setting(conn, "offers.valid_on_expiry_date") == "false":
        return expires_on <= t
    return expires_on < t


def open_offers(conn):
    return [dict(r, expired=offer_is_expired(conn, r["expires_on"])) for r in conn.execute(
        "SELECT o.*, g.name, g.id AS gardener_id, p.code FROM offers o JOIN waitlist w ON w.id=o.entry_id "
        "JOIN gardeners g ON g.id=w.gardener_id JOIN plots p ON p.id=o.plot_id WHERE o.status='open' "
        "ORDER BY o.expires_on")]


# ---------------------------------------------------------------- seasons

def current_season(conn):
    if get_setting(conn, "seasons.current_rule") == "most_recently_opened":
        return conn.execute("SELECT * FROM seasons ORDER BY opened_at DESC, id DESC LIMIT 1").fetchone()
    return conn.execute("SELECT * FROM seasons ORDER BY year DESC LIMIT 1").fetchone()


def get_season(conn, sid=None):
    if sid:
        s = conn.execute("SELECT * FROM seasons WHERE id=?", (sid,)).fetchone()
        if s:
            return s
    return current_season(conn)


def list_seasons(conn):
    return conn.execute("SELECT * FROM seasons ORDER BY year DESC").fetchall()


def default_fees(conn):
    s = current_season(conn)
    if s:
        return {z: s[f"fee_{z}"] for z in SIZES}
    return {z: fee_for(conn, z) for z in SIZES}


def clean_season(conn, data):
    errors = {}
    year = (data.get("year") or "").strip()
    if not year.isdigit() or not 2000 <= int(year) <= 2100:
        errors["year"] = "Enter a year, e.g. 2026"
    fees = {}
    for z in SIZES:
        cents, err = parse_amount(data.get(f"fee_{z}"))
        if err:
            errors[f"fee_{z}"] = "Enter a positive fee with at most 2 decimals"
        fees[z] = cents
    due = parse_date(data.get("due_date"), "due_date", errors)
    if due and "year" not in errors and due.year != int(year):
        errors["due_date"] = f"The due date must be in {year}"
    if "year" not in errors and conn.execute("SELECT 1 FROM seasons WHERE year=?", (int(year),)).fetchone():
        errors["year"] = f"Season {year} already exists"
    if errors:
        raise FieldErrors(errors)
    return int(year), due, fees


def season_preview(conn, fees):
    out = {z: {"count": 0, "total": 0} for z in SIZES}
    for r in conn.execute("SELECT p.size, count(*) n FROM assignments a JOIN plots p ON p.id=a.plot_id "
                          "WHERE a.end_date IS NULL GROUP BY p.size"):
        out[r["size"]] = {"count": r["n"], "total": r["n"] * fees[r["size"]]}
    return out


def open_season(conn, actor, data):
    require_admin(actor)
    with tx(conn):
        year, due, fees = clean_season(conn, data)
        cur = conn.execute("INSERT INTO seasons(year, due_date, fee_small, fee_standard, fee_large, opened_at, user_id)"
                           " VALUES (?,?,?,?,?,?,?)", (year, due.isoformat(), fees["small"], fees["standard"],
                                                       fees["large"], now_iso(), actor["id"]))
        sid = cur.lastrowid
        audit(conn, actor, "season.open", "season", sid, f"Season {year} opened",
              None, {"year": year, "due_date": due.isoformat(), **{f"fee_{k}": v for k, v in fees.items()}})
        n = charge_season(conn, actor, sid)
    return sid, n


def charge_season(conn, actor, sid):
    """Charge every active assignment once. Safe to re-run: the unique index on
    (assignment, season) means a second run creates nothing."""
    require_admin(actor)
    with tx(conn):
        s = conn.execute("SELECT * FROM seasons WHERE id=?", (sid,)).fetchone()
        if s["closed_at"]:
            raise DomainError(f"Season {s['year']} is closed")
        n = 0
        for a in conn.execute("SELECT a.id, a.gardener_id, p.size, p.code FROM assignments a JOIN plots p "
                              "ON p.id=a.plot_id WHERE a.end_date IS NULL ORDER BY a.id").fetchall():
            n += _insert_charge(conn, actor, a["gardener_id"], s, a["id"], s[f"fee_{a['size']}"],
                                min(today(conn), dt.date(s["year"], 12, 31)) if today(conn).year == s["year"]
                                else dt.date(s["year"], 1, 1), f"Fee {s['year']} plot {a['code']}")
        return n


def close_season(conn, actor, sid):
    require_admin(actor)
    with tx(conn):
        s = conn.execute("SELECT * FROM seasons WHERE id=?", (sid,)).fetchone()
        if not s or s["closed_at"]:
            raise DomainError("Season not found or already closed")
        conn.execute("UPDATE seasons SET closed_at=? WHERE id=?", (now_iso(), sid))
        audit(conn, actor, "season.close", "season", sid, f"Season {s['year']} closed")


# ---------------------------------------------------------------- ledger

def season_figures(conn, gid, sid):
    r = conn.execute(
        "SELECT coalesce(sum(CASE WHEN kind IN ('charge','adjustment') THEN amount END),0) charged,"
        " coalesce(-sum(CASE WHEN kind IN ('payment','void','refund') THEN amount END),0) paid,"
        " coalesce(sum(amount),0) balance FROM ledger WHERE gardener_id=? AND season_id=?", (gid, sid)).fetchone()
    return {"charged": r["charged"], "paid": r["paid"], "balance": r["balance"]}


def due_status(charged, balance, due_date, on_date):
    """Fee status from the scope's rules."""
    if balance < 0:
        return "In credit"
    if balance == 0:
        return "Paid"
    if on_date > (dt.date.fromisoformat(due_date) if isinstance(due_date, str) else due_date):
        return "Overdue"
    if balance >= charged:
        return "Unpaid"
    return "Partly paid"


def _clean_money_form(conn, gid, sid, amount, date, signed=False):
    errors = {}
    cents, err = parse_amount(amount, signed=signed)
    if err:
        errors["amount"] = err
    d = parse_date(date or today(conn).isoformat(), "date", errors)
    s = conn.execute("SELECT * FROM seasons WHERE id=?", (sid,)).fetchone() if sid else None
    if not s:
        errors["season_id"] = "Choose a season"
    get_gardener(conn, gid)
    return cents, d, s, errors


def _existing_token(conn, token):
    if token:
        r = conn.execute("SELECT id FROM ledger WHERE form_token=?", (token,)).fetchone()
        if r:
            return r["id"]
    return None


def _insert_entry(conn, actor, gid, s, kind, amount, d, method=None, reference="", reason="", token=None,
                  voids_id=None):
    try:
        cur = conn.execute(
            "INSERT INTO ledger(gardener_id, season_id, kind, amount, entry_date, method, reference, reason, "
            "voids_id, form_token, user_id, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (gid, s["id"], kind, amount, d.isoformat(), method, reference, reason, voids_id, token or None,
             actor["id"], now_iso()))
    except sqlite3.IntegrityError as exc:
        if "voids_id" in str(exc):
            raise DomainError("Already voided")
        raise
    audit(conn, actor, f"ledger.{kind}", "ledger", cur.lastrowid,
          f"{kind.capitalize()} {fmt_money(abs(amount))} ({s['year']})" + (f": {reason}" if reason else ""),
          None, {"amount": amount, "method": method, "reference": reference, "reason": reason,
                 "season": s["year"], "date": d.isoformat(), "voids": voids_id}, gardener_id=gid)
    return cur.lastrowid


def record_payment(conn, actor, gid, sid, amount, date, method, reference="", token=None):
    with tx(conn):
        if _existing_token(conn, token):
            return _existing_token(conn, token)
        cents, d, s, errors = _clean_money_form(conn, gid, sid, amount, date)
        if method not in METHODS:
            errors["method"] = "Choose a payment method"
        if errors:
            raise FieldErrors(errors)
        bal = season_figures(conn, gid, s["id"])["balance"]
        if get_setting(conn, "payments.overpayment") == "reject" and cents > bal:
            raise FieldErrors({"amount": f"Balance is {fmt_money(bal)}; amount exceeds it"})
        return _insert_entry(conn, actor, gid, s, "payment", -cents, d, method, (reference or "").strip(),
                             token=token)


def record_refund(conn, actor, gid, sid, amount, date, method, reason, token=None):
    with tx(conn):
        if _existing_token(conn, token):
            return _existing_token(conn, token)
        cents, d, s, errors = _clean_money_form(conn, gid, sid, amount, date)
        if method not in METHODS:
            errors["method"] = "Choose a method"
        if not (reason or "").strip():
            errors["reason"] = "Enter a reason"
        if errors:
            raise FieldErrors(errors)
        paid = season_figures(conn, gid, s["id"])["paid"]
        if cents > paid:
            raise FieldErrors({"amount": f"Refund cannot exceed {fmt_money(max(paid, 0))} paid"})
        return _insert_entry(conn, actor, gid, s, "refund", cents, d, method, reason=reason.strip(), token=token)


def record_adjustment(conn, actor, gid, sid, amount, date, reason, token=None):
    require_admin(actor)
    with tx(conn):
        if _existing_token(conn, token):
            return _existing_token(conn, token)
        cents, d, s, errors = _clean_money_form(conn, gid, sid, amount, date, signed=True)
        if not (reason or "").strip():
            errors["reason"] = "Enter a reason"
        if errors:
            raise FieldErrors(errors)
        return _insert_entry(conn, actor, gid, s, "adjustment", cents, d, reason=reason.strip(), token=token)


def void_payment(conn, actor, lid, reason):
    if not (reason or "").strip():
        raise FieldErrors({"reason": "Enter a reason"})
    with tx(conn):
        e = conn.execute("SELECT * FROM ledger WHERE id=?", (lid,)).fetchone()
        if not e or e["kind"] != "payment":
            raise DomainError("Only payments can be voided")
        if conn.execute("SELECT 1 FROM ledger WHERE voids_id=?", (lid,)).fetchone():
            raise DomainError("Already voided")
        s = conn.execute("SELECT * FROM seasons WHERE id=?", (e["season_id"],)).fetchone()
        return _insert_entry(conn, actor, e["gardener_id"], s, "void", -e["amount"], today(conn), e["method"],
                             e["reference"], reason.strip(), voids_id=lid)


def gardener_ledger(conn, gid):
    rows = conn.execute(
        "SELECT l.*, s.year, u.username, (SELECT v.id FROM ledger v WHERE v.voids_id=l.id) AS voided_by "
        "FROM ledger l JOIN seasons s ON s.id=l.season_id LEFT JOIN users u ON u.id=l.user_id "
        "WHERE l.gardener_id=? ORDER BY l.id", (gid,)).fetchall()
    out, running = [], 0
    for r in rows:
        running += r["amount"]
        out.append(dict(r, running=running))
    return out


def dues(conn, sid, on_date=None, status="", sort="name"):
    s = conn.execute("SELECT * FROM seasons WHERE id=?", (sid,)).fetchone()
    on_date = on_date or today(conn)
    rows = []
    for r in conn.execute(
            "SELECT g.id, g.name, g.email, g.phone,"
            " coalesce(sum(CASE WHEN l.kind IN ('charge','adjustment') THEN l.amount END),0) charged,"
            " coalesce(-sum(CASE WHEN l.kind IN ('payment','void','refund') THEN l.amount END),0) paid,"
            " sum(l.amount) balance,"
            " (SELECT p.code FROM assignments a JOIN plots p ON p.id=a.plot_id WHERE a.gardener_id=g.id"
            "   ORDER BY a.end_date IS NULL DESC, a.id DESC LIMIT 1) plot_code"
            " FROM ledger l JOIN gardeners g ON g.id=l.gardener_id WHERE l.season_id=? GROUP BY g.id", (sid,)):
        if r["charged"] == 0 and r["paid"] == 0 and r["balance"] == 0:
            continue
        row = dict(r, status=due_status(r["charged"], r["balance"], s["due_date"], on_date))
        if not status or row["status"] == status:
            rows.append(row)
    if sort == "balance":
        rows.sort(key=lambda x: (-x["balance"], x["name"].lower()))
    else:
        rows.sort(key=lambda x: x["name"].lower())
    return rows


def season_totals(conn, sid, on_date=None):
    all_rows = dues(conn, sid, on_date)
    t = {"charged": sum(r["charged"] for r in all_rows), "paid": sum(r["paid"] for r in all_rows),
         "balance": sum(r["balance"] for r in all_rows),
         "outstanding": sum(r["balance"] for r in all_rows if r["balance"] > 0),
         "counts": {k: 0 for k in DUE_STATUSES}}
    for r in all_rows:
        t["counts"][r["status"]] += 1
    return t


def payments_in_range(conn, start, end):
    return conn.execute(
        "SELECT l.*, g.name, s.year, u.username FROM ledger l JOIN gardeners g ON g.id=l.gardener_id "
        "JOIN seasons s ON s.id=l.season_id LEFT JOIN users u ON u.id=l.user_id "
        "WHERE l.kind IN ('payment','void','refund') AND l.entry_date BETWEEN ? AND ? ORDER BY l.entry_date, l.id",
        (start.isoformat(), end.isoformat())).fetchall()


def payments_by_method(conn, start, end):
    """Net money received per method (payments less voids and refunds)."""
    out = {m: 0 for m in METHODS}
    for r in payments_in_range(conn, start, end):
        out[r["method"] or "other"] = out.get(r["method"] or "other", 0) - r["amount"]
    return out
