"""Demo data: loaded only by the explicit `demo` command, and only into an empty install."""
import datetime as dt
import random

from . import core as C
from .store import tx

FIRST = ["Ana", "Ben", "Chloe", "Dev", "Ella", "Femi", "Grace", "Hiro", "Ines", "Jon", "Kai", "Lena", "Malik",
         "Nora", "Omar", "Pia", "Quinn", "Rosa", "Sam", "Tara", "Umar", "Vera", "Wen", "Xavi", "Yara", "Zoe",
         "Arlo", "Bea", "Cyril", "Dina", "Eli", "Fay", "Gus", "Hana", "Ivo", "Jade", "Kofi", "Lia", "Milo",
         "Nell", "Otto", "Priya", "Rui", "Sofia", "Theo"]
LAST = ["Okafor", "Smith", "Novak", "Patel", "Garcia", "Jansen", "Kowalski", "Murphy", "Rossi", "Silva",
        "Tanaka", "Weber", "Nguyen", "Dubois", "Haddad"]


def is_empty(conn):
    return not any(conn.execute(f"SELECT 1 FROM {t} LIMIT 1").fetchone()
                   for t in ("users", "plots", "gardeners", "seasons"))


def load(conn, garden_name="Riverside Community Garden", currency="EUR", timezone="UTC"):
    if not is_empty(conn):
        raise C.DomainError("Demo data can only be loaded into an empty install")
    rnd = random.Random(42)
    pw = {}
    with tx(conn):
        C._set_setting(conn, "garden_name", garden_name)
        C._set_setting(conn, "currency", currency)
        C._set_setting(conn, "timezone", timezone)
        for name, role in (("admin", "admin"), ("coordinator", "coordinator")):
            pw[name] = C.temp_password()
            conn.execute("INSERT INTO users(username, role, pw_hash, created_at) VALUES (?,?,?,?)",
                         (name, role, C.hash_password(pw[name]), C.now_iso()))
        conn.execute("DELETE FROM meta WHERE key='setup_code'")
        admin = dict(conn.execute("SELECT * FROM users WHERE username='admin'").fetchone())
        today = C.today(conn)
        year = today.year

        # 40 plots
        plots = []
        for i in range(40):
            size = C.SIZES[i % 3] if i % 5 else "standard"
            code = f"{'ABCD'[i // 10]}-{i % 10 + 1:02d}"
            plots.append(C.add_plot(conn, admin, {"code": code, "size": size,
                                                  "area": str({"small": 25, "standard": 50, "large": 100}[size]),
                                                  "notes": "Near the water tap" if i % 7 == 0 else ""}))
        # 45 gardeners
        gardeners = []
        for i in range(45):
            name = f"{FIRST[i]} {LAST[i % len(LAST)]}"
            gardeners.append(C.add_gardener(conn, admin, {
                "name": name, "email": f"{FIRST[i].lower()}.{LAST[i % len(LAST)].lower()}@example.org",
                "phone": f"+44 7700 9{i:05d}" if i % 3 else "", "address": f"{i + 1} Garden Row"}))

        # Last season: 6 long-standing holders, closed with some still owing
        for i in range(6):
            C.direct_assign(conn, admin, plots[i], None, gardeners[i], f"{year - 3}-0{i % 9 + 1}-01",
                            "Imported from spreadsheet")
        last_sid, _ = C.open_season(conn, admin, {"year": str(year - 1), "due_date": f"{year - 1}-03-31",
                                                  "fee_small": "38.00", "fee_standard": "55.00", "fee_large": "75.00"})
        for i in range(3):
            C.record_payment(conn, admin, gardeners[i], last_sid, C.fmt_money(
                C.season_figures(conn, gardeners[i], last_sid)["balance"]), f"{year - 1}-03-1{i}", "cash")
        C.record_payment(conn, admin, gardeners[3], last_sid, "20.00", f"{year - 1}-05-02", "bank_transfer", "BT-0412")
        C.close_season(conn, admin, last_sid)

        # 24 more holders, then this season charged
        for i in range(6, 30):
            C.direct_assign(conn, admin, plots[i], None, gardeners[i], f"{year - 1}-{i % 12 + 1:02d}-15",
                            "Imported from spreadsheet")
        due = min(today + dt.timedelta(days=60), dt.date(year, 12, 31))
        sid, _ = C.open_season(conn, admin, {"year": str(year), "due_date": due.isoformat(),
                                             **{f"fee_{z}": C.fmt_money(C.fee_for(conn, z)) for z in C.SIZES}})
        methods = ["cash", "bank_transfer", "cheque", "card", "bank_transfer"]

        def pay(g, amount, n):
            d = min(today, dt.date(year, 1, 10) + dt.timedelta(days=n * 7))
            return C.record_payment(conn, admin, gardeners[g], sid, amount, d.isoformat(), methods[n % 5],
                                    f"R{1000 + n}" if n % 2 else "")

        n = 0
        for g in range(0, 16):       # paid in full
            pay(g, C.fmt_money(C.season_figures(conn, gardeners[g], sid)["balance"]), n)
            n += 1
        for g in range(16, 21):      # partly paid
            pay(g, "20.00", n)
            n += 1
        C._set_setting(conn, "payments.overpayment", "credit")
        for g in range(21, 23):      # in credit
            pay(g, C.fmt_money(C.season_figures(conn, gardeners[g], sid)["balance"] + 1000), n)
            n += 1
        C._set_setting(conn, "payments.overpayment", "reject")
        # a payment entered by mistake, then voided
        bad = pay(23, "15.00", n)
        C.void_payment(conn, admin, bad, "Entered against the wrong gardener")
        # refund part of one credit; waive part of one fee
        C.record_refund(conn, admin, gardeners[21], sid, "5.00", today.isoformat(), "cash", "Returned overpayment")
        C.record_adjustment(conn, admin, gardeners[24], sid, "-20.00", today.isoformat(), "Hardship discount agreed by committee")

        # out of service, retired, and available plots
        for i in (30, 31, 32):
            C.change_plot_status(conn, admin, plots[i], None, "out_of_service", rnd.choice(
                ["Flooded", "Fence repair", "Soil remediation"]))
        for i in (33, 34):
            C.change_plot_status(conn, admin, plots[i], None, "retire", "Merged into path")

        # 12 waiting-list entries with mixed preferences, backdated
        prefs = ["any", "small", "standard", "large", "any", "standard", "small", "any", "large", "standard",
                 "any", "small"]
        for k, g in enumerate(range(30, 42)):
            joined = today - dt.timedelta(days=700 - k * 50)
            C.add_to_waitlist(conn, admin, gardeners[g], prefs[k], joined.isoformat())

        # one open offer, one expired offer (plots 35 and 36); plots 37-39 stay available
        for i in (35, 36):
            p = C.get_plot(conn, plots[i])
            _, e = C.preview_offer(conn, plots[i])
            C.make_offer(conn, admin, plots[i], p["version"], e["id"])
        old = today - dt.timedelta(days=20)
        conn.execute("UPDATE offers SET offered_on=?, expires_on=? WHERE plot_id=?",
                     (old.isoformat(), (old + dt.timedelta(days=14)).isoformat(), plots[36]))
        # an archived former gardener
        conn.execute("UPDATE gardeners SET archived=1 WHERE id=?", (gardeners[44],))
    return pw
