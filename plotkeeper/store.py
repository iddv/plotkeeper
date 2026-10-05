"""Data store: SQLite connection, versioned migrations, backup and restore."""
import datetime as dt
import os
import shutil
import sqlite3
from contextlib import contextmanager

DB_NAME = "plotkeeper.db"

SCHEMA_V1 = """
CREATE TABLE settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE users(
  id INTEGER PRIMARY KEY, username TEXT NOT NULL UNIQUE COLLATE NOCASE,
  role TEXT NOT NULL CHECK(role IN ('admin','coordinator')), pw_hash TEXT NOT NULL,
  must_change INTEGER NOT NULL DEFAULT 0, active INTEGER NOT NULL DEFAULT 1,
  failed INTEGER NOT NULL DEFAULT 0, locked_until TEXT, created_at TEXT NOT NULL);
CREATE TABLE sessions(token TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
  csrf TEXT NOT NULL, last_seen TEXT NOT NULL);
CREATE TABLE plots(
  id INTEGER PRIMARY KEY, code TEXT NOT NULL UNIQUE COLLATE NOCASE,
  size TEXT NOT NULL CHECK(size IN ('small','standard','large')), area REAL,
  notes TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'available'
    CHECK(status IN ('available','offered','occupied','out_of_service','retired')),
  status_reason TEXT NOT NULL DEFAULT '', version INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL);
CREATE TABLE gardeners(
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, email TEXT NOT NULL DEFAULT '',
  phone TEXT NOT NULL DEFAULT '', address TEXT NOT NULL DEFAULT '', notes TEXT NOT NULL DEFAULT '',
  archived INTEGER NOT NULL DEFAULT 0, version INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL);
CREATE TABLE waitlist(
  id INTEGER PRIMARY KEY, gardener_id INTEGER NOT NULL REFERENCES gardeners(id),
  preference TEXT NOT NULL CHECK(preference IN ('any','small','standard','large')),
  joined_at TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','offered','placed','removed')),
  declines INTEGER NOT NULL DEFAULT 0, close_reason TEXT, closed_at TEXT, created_at TEXT NOT NULL);
CREATE UNIQUE INDEX one_active_entry ON waitlist(gardener_id) WHERE status IN ('active','offered');
CREATE TABLE assignments(
  id INTEGER PRIMARY KEY, plot_id INTEGER NOT NULL REFERENCES plots(id),
  gardener_id INTEGER NOT NULL REFERENCES gardeners(id), start_date TEXT NOT NULL,
  end_date TEXT, end_reason TEXT, via TEXT NOT NULL, note TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL);
CREATE UNIQUE INDEX one_holder_per_plot ON assignments(plot_id) WHERE end_date IS NULL;
CREATE UNIQUE INDEX one_plot_per_gardener ON assignments(gardener_id) WHERE end_date IS NULL;
CREATE TABLE offers(
  id INTEGER PRIMARY KEY, plot_id INTEGER NOT NULL REFERENCES plots(id),
  entry_id INTEGER NOT NULL REFERENCES waitlist(id), offered_on TEXT NOT NULL,
  expires_on TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'open'
    CHECK(status IN ('open','accepted','declined','expired','withdrawn')),
  resolved_at TEXT, user_id INTEGER REFERENCES users(id), created_at TEXT NOT NULL);
CREATE UNIQUE INDEX one_open_offer_plot ON offers(plot_id) WHERE status='open';
CREATE UNIQUE INDEX one_open_offer_entry ON offers(entry_id) WHERE status='open';
CREATE TABLE seasons(
  id INTEGER PRIMARY KEY, year INTEGER NOT NULL UNIQUE, due_date TEXT NOT NULL,
  fee_small INTEGER NOT NULL, fee_standard INTEGER NOT NULL, fee_large INTEGER NOT NULL,
  opened_at TEXT NOT NULL, closed_at TEXT, user_id INTEGER REFERENCES users(id));
CREATE TABLE ledger(
  id INTEGER PRIMARY KEY, gardener_id INTEGER NOT NULL REFERENCES gardeners(id),
  season_id INTEGER NOT NULL REFERENCES seasons(id),
  kind TEXT NOT NULL CHECK(kind IN ('charge','payment','void','refund','adjustment')),
  amount INTEGER NOT NULL, entry_date TEXT NOT NULL, method TEXT,
  reference TEXT NOT NULL DEFAULT '', reason TEXT NOT NULL DEFAULT '',
  assignment_id INTEGER REFERENCES assignments(id), voids_id INTEGER UNIQUE REFERENCES ledger(id),
  form_token TEXT UNIQUE, user_id INTEGER REFERENCES users(id), created_at TEXT NOT NULL);
CREATE UNIQUE INDEX one_charge_per_assignment_season ON ledger(assignment_id, season_id)
  WHERE kind='charge';
CREATE TRIGGER ledger_no_update BEFORE UPDATE ON ledger
  BEGIN SELECT RAISE(ABORT, 'ledger is append-only'); END;
CREATE TRIGGER ledger_no_delete BEFORE DELETE ON ledger
  BEGIN SELECT RAISE(ABORT, 'ledger is append-only'); END;
CREATE TABLE audit(
  id INTEGER PRIMARY KEY, at TEXT NOT NULL, user_id INTEGER REFERENCES users(id),
  action TEXT NOT NULL, record_type TEXT NOT NULL, record_id INTEGER,
  plot_id INTEGER, gardener_id INTEGER, summary TEXT NOT NULL DEFAULT '',
  before TEXT, after TEXT);
CREATE INDEX audit_plot ON audit(plot_id);
CREATE INDEX audit_gardener ON audit(gardener_id);
CREATE INDEX ledger_gardener ON ledger(gardener_id, season_id);
"""

# Append new (version, sql) pairs here; never edit a released migration.
MIGRATIONS = [(1, SCHEMA_V1)]
LATEST = MIGRATIONS[-1][0]


def db_path(data_dir):
    return os.path.join(data_dir, DB_NAME)


def connect(path):
    conn = sqlite3.connect(path, isolation_level=None, check_same_thread=False, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=15000")
    return conn


@contextmanager
def tx(conn):
    """Write transaction. BEGIN IMMEDIATE serialises writers, so status/version checks
    inside it cannot race. Re-entrant: nested calls join the outer transaction."""
    if conn.in_transaction:
        yield conn
        return
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


def schema_version(conn):
    return conn.execute("PRAGMA user_version").fetchone()[0]


def migrate(conn, data_dir=None, log=print):
    """Apply pending migrations. An existing database is backed up first."""
    current = schema_version(conn)
    pending = [(v, sql) for v, sql in MIGRATIONS if v > current]
    if not pending:
        return []
    if current > 0 and data_dir:
        path = backup(conn, data_dir, label="pre-migration")
        log(f"Backed up database before migration to {path}")
    for version, sql in pending:
        conn.executescript(f"BEGIN;\n{sql}\nPRAGMA user_version={version};\nCOMMIT;")
        log(f"Applied schema migration {version}")
    return [v for v, _ in pending]


def backup_dir(data_dir):
    d = os.path.join(data_dir, "backups")
    os.makedirs(d, exist_ok=True)
    return d


def backup(conn, data_dir, label="backup", dest=None):
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    dest = dest or os.path.join(backup_dir(data_dir), f"plotkeeper-{label}-{stamp}.db")
    target = sqlite3.connect(dest)
    try:
        conn.backup(target)
    finally:
        target.close()
    return dest


def validate_backup(path):
    if not os.path.isfile(path):
        raise ValueError(f"No such file: {path}")
    try:
        c = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            v = c.execute("PRAGMA user_version").fetchone()[0]
            c.execute("SELECT count(*) FROM plots").fetchone()
        finally:
            c.close()
    except sqlite3.Error as exc:
        raise ValueError(f"Not a Plotkeeper backup: {exc}")
    if v < 1 or v > LATEST:
        raise ValueError(f"Backup schema version {v} is not supported by this version")
    return v


def restore(data_dir, src):
    """Replace the live database with a backup. The current data is backed up first."""
    validate_backup(src)
    live = db_path(data_dir)
    safety = None
    if os.path.exists(live):
        conn = connect(live)
        try:
            safety = backup(conn, data_dir, label="pre-restore")
        finally:
            conn.close()
    for suffix in ("-wal", "-shm"):
        if os.path.exists(live + suffix):
            os.remove(live + suffix)
    tmp = live + ".restoring"
    shutil.copyfile(src, tmp)
    os.replace(tmp, live)
    return safety
