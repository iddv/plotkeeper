"""Command line: start | demo | backup | restore | test"""
import argparse
import logging
import os
import secrets
import sys

from . import core as C
from . import demo, store

CONFIG_KEYS = {
    "PLOTKEEPER_HOST": "127.0.0.1",
    "PLOTKEEPER_PORT": "8080",
    "PLOTKEEPER_DATA_DIR": "./data",
    "PLOTKEEPER_SESSION_SECRET": "",
    "PLOTKEEPER_LOG_LEVEL": "INFO",
    "PLOTKEEPER_TIMEZONE": "",
}


def load_config():
    """Defaults < config file < environment variables."""
    cfg = dict(CONFIG_KEYS)
    path = os.environ.get("PLOTKEEPER_CONFIG", "plotkeeper.conf")
    if os.path.isfile(path):
        with open(path) as fh:
            for line in fh:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    if k.strip() in cfg:
                        cfg[k.strip()] = v.strip().strip('"')
    for k in cfg:
        if os.environ.get(k):
            cfg[k] = os.environ[k]
    cfg["PLOTKEEPER_DATA_DIR"] = os.path.abspath(cfg["PLOTKEEPER_DATA_DIR"])
    if cfg["PLOTKEEPER_TIMEZONE"]:
        os.environ["PLOTKEEPER_TIMEZONE"] = cfg["PLOTKEEPER_TIMEZONE"]
    return cfg


def server_timezone():
    if os.environ.get("TZ"):
        return os.environ["TZ"].lstrip(":")
    try:
        target = os.path.realpath("/etc/localtime")
        if "zoneinfo/" in target:
            return target.split("zoneinfo/", 1)[1]
    except OSError:
        pass
    return "UTC"


def open_db(cfg, quiet=False):
    os.makedirs(cfg["PLOTKEEPER_DATA_DIR"], exist_ok=True)
    conn = store.connect(store.db_path(cfg["PLOTKEEPER_DATA_DIR"]))
    conn.execute("PRAGMA journal_mode=WAL")
    store.migrate(conn, cfg["PLOTKEEPER_DATA_DIR"], log=(lambda *_: None) if quiet else print)
    return conn


def session_secret(cfg):
    if cfg["PLOTKEEPER_SESSION_SECRET"]:
        return cfg["PLOTKEEPER_SESSION_SECRET"]
    path = os.path.join(cfg["PLOTKEEPER_DATA_DIR"], "session_secret")
    if not os.path.exists(path):
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as fh:
            fh.write(secrets.token_hex(32))
    with open(path) as fh:
        return fh.read().strip()


def cmd_start(cfg, args):
    from .web import App, serve
    conn = open_db(cfg)
    host, port = cfg["PLOTKEEPER_HOST"], int(cfg["PLOTKEEPER_PORT"])
    app = App(store.db_path(cfg["PLOTKEEPER_DATA_DIR"]), session_secret(cfg), server_timezone())
    try:
        server = serve(app, host, port)
    except OSError as exc:
        print(f"Cannot listen on {host}:{port} ({exc.strerror}). Port {port} is probably already in use.\n"
              f"Set PLOTKEEPER_PORT (or PLOTKEEPER_HOST) to change it, e.g. PLOTKEEPER_PORT=8081.", file=sys.stderr)
        return 2
    url = f"http://{host}:{port}/"
    print(f"Plotkeeper is running at {url}")
    print(f"Data directory: {cfg['PLOTKEEPER_DATA_DIR']}")
    if not C.has_users(conn):
        code = C.new_setup_code(conn)
        print(f"\n  First run: open {url}setup and enter this one-time setup code: {code}\n")
    conn.close()
    sys.stdout.flush()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Stopping.")
    return 0


def cmd_demo(cfg, args):
    conn = open_db(cfg)
    try:
        pw = demo.load(conn, timezone=os.environ.get("PLOTKEEPER_TIMEZONE") or server_timezone())
    except C.DomainError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print("Demo data loaded. These passwords are shown only once:")
    for user, p in pw.items():
        print(f"  {user:12s} {p}")
    return 0


def cmd_backup(cfg, args):
    conn = open_db(cfg, quiet=True)
    path = store.backup(conn, cfg["PLOTKEEPER_DATA_DIR"], dest=args.output)
    print(f"Backup written to {path}")
    return 0


def cmd_restore(cfg, args):
    try:
        version = store.validate_backup(args.file)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if not args.yes:
        print(f"This REPLACES all data in {cfg['PLOTKEEPER_DATA_DIR']} with {args.file} (schema v{version}).")
        print("Stop the running service first. A safety backup of the current data is taken.")
        if input("Type RESTORE to continue: ").strip() != "RESTORE":
            print("Cancelled; nothing changed.")
            return 1
    safety = store.restore(cfg["PLOTKEEPER_DATA_DIR"], args.file)
    if safety:
        print(f"Previous data saved to {safety}")
    conn = open_db(cfg)
    conn.close()
    print("Restore complete. Start Plotkeeper again.")
    return 0


def cmd_test(cfg, args):
    import unittest
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    # Only the unit tests: tests/acceptance holds pytest suites, run with `python -m pytest tests/acceptance`.
    if root not in sys.path:
        sys.path.insert(0, root)
    suite = unittest.defaultTestLoader.loadTestsFromName("tests.test_plotkeeper")
    return 0 if unittest.TextTestRunner(verbosity=1).run(suite).wasSuccessful() else 1


def main(argv=None):
    p = argparse.ArgumentParser(prog="plotkeeper", description="Plotkeeper community garden register")
    sub = p.add_subparsers(dest="cmd")
    sub.add_parser("start", help="start the web service (default)")
    sub.add_parser("demo", help="load demo data into an empty install")
    b = sub.add_parser("backup", help="write a timestamped single-file backup")
    b.add_argument("-o", "--output", help="backup file path (default: DATA_DIR/backups/...)")
    r = sub.add_parser("restore", help="replace all data from a backup file")
    r.add_argument("file")
    r.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    sub.add_parser("test", help="run the automated test suite")
    args = p.parse_args(argv)
    cfg = load_config()
    logging.basicConfig(level=getattr(logging, cfg["PLOTKEEPER_LOG_LEVEL"].upper(), logging.INFO),
                        format="%(asctime)s %(levelname)s %(message)s")
    return {"start": cmd_start, None: cmd_start, "demo": cmd_demo, "backup": cmd_backup,
            "restore": cmd_restore, "test": cmd_test}[args.cmd](cfg, args)


if __name__ == "__main__":
    sys.exit(main())
