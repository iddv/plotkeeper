import datetime as dt
import os
import re
import shutil
import tempfile
import threading
import unittest
from urllib.parse import urlencode

from plotkeeper import core as C
from plotkeeper import demo, store
from plotkeeper.web import App

PW = "correct horse battery"


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = store.db_path(self.dir)
        self.conn = store.connect(self.path)
        self.conn.execute("PRAGMA journal_mode=WAL")
        store.migrate(self.conn, self.dir, log=lambda *_: None)
        code = C.new_setup_code(self.conn)
        uid = C.setup(self.conn, code, "Test Garden", "EUR", "UTC", "boss", PW, PW)
        self.admin = dict(self.conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone())
        cid, _ = C.create_user(self.conn, self.admin, "coord", "coordinator")
        self.coord = dict(self.conn.execute("SELECT * FROM users WHERE id=?", (cid,)).fetchone())

    def tearDown(self):
        self.conn.close()
        shutil.rmtree(self.dir)

    def plot(self, code, size="standard"):
        return C.add_plot(self.conn, self.admin, {"code": code, "size": size})

    def gardener(self, name):
        return C.add_gardener(self.conn, self.admin, {"name": name, "email": f"{name.lower()}@x.org"})

    def wait(self, name, pref="any", joined=None):
        g = self.gardener(name)
        return g, C.add_to_waitlist(self.conn, self.admin, g, pref, joined)

    def offer(self, pid):
        p, e = C.preview_offer(self.conn, pid)
        return C.make_offer(self.conn, self.admin, pid, p["version"], e["id"]), e

    def season(self, year=None, **fees):
        year = year or C.today(self.conn).year
        data = {"year": str(year), "due_date": f"{year}-03-31", "fee_small": "40.00", "fee_standard": "60.00",
                "fee_large": "80.00"}
        data.update(fees)
        return C.open_season(self.conn, self.admin, data)

    def assign(self, pid, gid, start=None):
        start = start or C.today(self.conn).replace(month=1, day=1).isoformat()
        return C.direct_assign(self.conn, self.admin, pid, None, gid, start, "test")


class WaitingListTests(Base):
    def test_order_backdating_and_positions(self):
        a, ea = self.wait("A")
        b, eb = self.wait("B", joined="2020-05-01")
        c, ec = self.wait("C", joined="2021-01-01")
        self.assertEqual([e["name"] for e in C.waiting_list(self.conn)], ["B", "C", "A"])
        C.remove_from_waitlist(self.conn, self.admin, eb, "withdrew")
        self.assertEqual(C.entry_position(self.conn, ec), 1)
        self.assertEqual(C.entry_position(self.conn, ea), 2)

    def test_ties_broken_by_creation_order(self):
        _, e1 = self.wait("First", joined="2022-01-01")
        _, e2 = self.wait("Second", joined="2022-01-01")
        self.assertLess(C.entry_position(self.conn, e1), C.entry_position(self.conn, e2))

    def test_size_matching(self):
        self.wait("Large", "large", "2020-01-01")
        self.wait("Small", "small", "2020-02-01")
        self.wait("Any", "any", "2020-03-01")
        self.assertEqual(C.next_in_line(self.conn, "small")["name"], "Small")
        self.assertEqual(C.next_in_line(self.conn, "standard")["name"], "Any")
        pid = self.plot("M1", "standard")
        self.offer(pid)
        p = self.plot("M2", "standard")
        with self.assertRaisesRegex(C.DomainError, "No one on the waiting list matches a standard plot"):
            C.preview_offer(self.conn, p)

    def test_one_entry_and_holder_rules(self):
        g, _ = self.wait("Dup")
        with self.assertRaisesRegex(C.DomainError, "Already on the list at position 1"):
            C.add_to_waitlist(self.conn, self.admin, g, "any")
        h = self.gardener("Holder")
        self.assign(self.plot("H1"), h)
        with self.assertRaisesRegex(C.DomainError, "Already holds plot H1"):
            C.add_to_waitlist(self.conn, self.admin, h, "any")

    def test_preference_change_keeps_position(self):
        _, e1 = self.wait("P1", joined="2020-01-01")
        self.wait("P2", joined="2020-02-01")
        C.change_preference(self.conn, self.admin, e1, "large")
        self.assertEqual(C.entry_position(self.conn, e1), 1)


class OfferTests(Base):
    def test_keep_place_decline_and_removal_after_two(self):
        g1, e1 = self.wait("One", joined="2020-01-01")
        self.wait("Two", joined="2020-02-01")
        pid = self.plot("K1")
        oid, e = self.offer(pid)
        self.assertEqual(e["id"], e1)
        C.resolve_offer(self.conn, self.admin, oid, "declined")
        self.assertEqual(C.get_plot(self.conn, pid)["status"], "available")
        self.assertEqual(C.entry_position(self.conn, e1), 1)
        oid, e = self.offer(pid)
        self.assertEqual(e["id"], e1)
        C.resolve_offer(self.conn, self.admin, oid, "expired")
        row = self.conn.execute("SELECT * FROM waitlist WHERE id=?", (e1,)).fetchone()
        self.assertEqual((row["status"], row["close_reason"]), ("removed", "declined twice"))
        self.assertEqual(C.next_in_line(self.conn, "standard")["name"], "Two")

    def test_move_to_end_policy(self):
        C.update_settings(self.conn, self.admin, {"waitlist.decline_policy": "move_to_end"})
        _, e1 = self.wait("One", joined="2020-01-01")
        self.wait("Two", joined="2020-02-01")
        oid, _ = self.offer(self.plot("E1"))
        C.resolve_offer(self.conn, self.admin, oid, "declined")
        self.assertEqual([w["name"] for w in C.waiting_list(self.conn)], ["Two", "One"])

    def test_withdraw_restores_place(self):
        _, e1 = self.wait("One", joined="2020-01-01")
        self.wait("Two", joined="2020-02-01")
        pid = self.plot("W1")
        oid, _ = self.offer(pid)
        C.resolve_offer(self.conn, self.admin, oid, "withdrawn")
        self.assertEqual(C.entry_position(self.conn, e1), 1)
        self.assertEqual(C.next_in_line(self.conn, "standard")["id"], e1)

    def test_accept_creates_assignment_and_charge(self):
        sid, _ = self.season()
        g, e1 = self.wait("Acc")
        pid = self.plot("A1", "large")
        oid, _ = self.offer(pid)
        C.resolve_offer(self.conn, self.admin, oid, "accepted", C.today(self.conn).isoformat())
        self.assertEqual(C.get_plot(self.conn, pid)["status"], "occupied")
        self.assertEqual(C.season_figures(self.conn, g, sid)["charged"], 8000)
        self.assertIsNone(C.active_entry(self.conn, g))

    def test_start_before_last_release_refused(self):
        h = self.gardener("Old")
        pid = self.plot("R1")
        self.assign(pid, h, "2024-01-01")
        C.release_plot(self.conn, self.admin, pid, None, "2025-06-30", "moved")
        self.wait("New")
        oid, _ = self.offer(pid)
        with self.assertRaises(C.FieldErrors):
            C.resolve_offer(self.conn, self.admin, oid, "accepted", "2025-06-01")
        self.assertEqual(C.get_plot(self.conn, pid)["status"], "offered")

    def test_concurrent_offers_only_one_succeeds(self):
        self.wait("One", joined="2020-01-01")
        self.wait("Two", joined="2020-02-01")
        pid = self.plot("C1")
        p, e = C.preview_offer(self.conn, pid)
        results, barrier = [], threading.Barrier(2)

        def go(user):
            c = store.connect(self.path)
            barrier.wait()
            try:
                C.make_offer(c, user, pid, p["version"], e["id"])
                results.append("ok")
            except C.DomainError as x:
                results.append(str(x))
            finally:
                c.close()
        ts = [threading.Thread(target=go, args=(u,)) for u in (self.admin, self.coord)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        self.assertEqual(results.count("ok"), 1)
        self.assertTrue(any("just offered to One" in r for r in results), results)
        self.assertEqual(self.conn.execute("SELECT count(*) FROM offers").fetchone()[0], 1)

    def test_concurrent_accept_and_withdraw(self):
        self.wait("One")
        pid = self.plot("C2")
        oid, _ = self.offer(pid)
        results, barrier = [], threading.Barrier(2)

        def go(outcome):
            c = store.connect(self.path)
            barrier.wait()
            try:
                C.resolve_offer(c, self.admin, oid, outcome, C.today(c).isoformat())
                results.append(outcome)
            except C.DomainError:
                results.append("refused")
            finally:
                c.close()
        ts = [threading.Thread(target=go, args=(o,)) for o in ("accepted", "withdrawn")]
        [t.start() for t in ts]
        [t.join() for t in ts]
        self.assertEqual(results.count("refused"), 1)

    def test_valid_on_expiry_date_setting(self):
        self.wait("One")
        pid = self.plot("X1")
        self.offer(pid)
        self.conn.execute("UPDATE offers SET expires_on=?", (C.today(self.conn).isoformat(),))
        self.assertEqual(C.get_setting(self.conn, "offers.valid_on_expiry_date"), "true")
        self.assertFalse(C.open_offers(self.conn)[0]["expired"])
        C.update_settings(self.conn, self.admin, {"offers.valid_on_expiry_date": "false"})
        self.assertTrue(C.open_offers(self.conn)[0]["expired"])
        os.environ["OFFERS_VALID_ON_EXPIRY_DATE"] = "true"
        try:
            self.assertFalse(C.open_offers(self.conn)[0]["expired"])
        finally:
            del os.environ["OFFERS_VALID_ON_EXPIRY_DATE"]
        yesterday = (C.today(self.conn) - dt.timedelta(days=1)).isoformat()
        self.conn.execute("UPDATE offers SET expires_on=?", (yesterday,))
        C.update_settings(self.conn, self.admin, {"offers.valid_on_expiry_date": "true"})
        self.assertTrue(C.open_offers(self.conn)[0]["expired"])

    def test_stale_version_refused(self):
        pid = self.plot("V1")
        v = C.get_plot(self.conn, pid)["version"]
        C.edit_plot(self.conn, self.admin, pid, v, {"code": "V1", "size": "large"})
        with self.assertRaisesRegex(C.DomainError, "changed since you opened it"):
            C.edit_plot(self.conn, self.coord, pid, v, {"code": "V1", "size": "small"})

    def test_direct_assign_with_active_entry_setting(self):
        self.assertEqual(C.get_setting(self.conn, "assign.direct_with_active_entry"), "close_entry")
        g1, e1 = self.wait("Listed1")
        self.assign(self.plot("D1"), g1)
        row = self.conn.execute("SELECT status FROM waitlist WHERE id=?", (e1,)).fetchone()
        self.assertEqual(row["status"], "placed")
        C.update_settings(self.conn, self.admin, {"assign.direct_with_active_entry": "refused"})
        g2, e2 = self.wait("Listed2")
        p2 = self.plot("D2")
        with self.assertRaisesRegex(C.DomainError, "on the waiting list at position 1"):
            self.assign(p2, g2)
        self.assertEqual(C.get_plot(self.conn, p2)["status"], "available")
        self.assertEqual(self.conn.execute("SELECT status FROM waitlist WHERE id=?", (e2,)).fetchone()[0], "active")
        os.environ["ASSIGN_DIRECT_WITH_ACTIVE_ENTRY"] = "close_entry"
        try:
            self.assign(p2, g2)
        finally:
            del os.environ["ASSIGN_DIRECT_WITH_ACTIVE_ENTRY"]
        self.assertEqual(C.get_plot(self.conn, p2)["status"], "occupied")

    def test_release_with_balance_block(self):
        C.update_settings(self.conn, self.admin, {"plots.release_with_balance": "block"})
        g = self.gardener("Owes")
        pid = self.plot("B1", "small")
        self.assign(pid, g)
        self.season()
        with self.assertRaisesRegex(C.DomainError, r"owes 40\.00 for \d{4}; record payment"):
            C.release_plot(self.conn, self.admin, pid, None, C.today(self.conn).isoformat(), "moved")


class PlotTests(Base):
    def test_duplicate_code_and_retire_rules(self):
        self.plot("B-07")
        with self.assertRaises(C.FieldErrors) as cm:
            self.plot("b-07")
        self.assertEqual(cm.exception.errors["code"], "Plot code b-07 already exists")
        pid = self.plot("B-08")
        self.assign(pid, self.gardener("X"))
        with self.assertRaisesRegex(C.DomainError, "Release the holder or withdraw the offer first"):
            C.change_plot_status(self.conn, self.admin, pid, None, "retire", "gone")
        p2 = self.plot("B-09")
        C.change_plot_status(self.conn, self.admin, p2, None, "out_of_service", "flood")
        C.change_plot_status(self.conn, self.admin, p2, None, "return", "")
        C.change_plot_status(self.conn, self.admin, p2, None, "retire", "path")
        self.assertEqual(C.get_plot(self.conn, p2)["status"], "retired")
        n = self.conn.execute("SELECT count(*) FROM audit WHERE plot_id=?", (p2,)).fetchone()[0]
        self.assertEqual(n, 4)

    def test_archive_blocked_with_balance(self):
        g = self.gardener("Arch")
        pid = self.plot("Z1", "small")
        self.assign(pid, g)
        self.season()
        C.release_plot(self.conn, self.admin, pid, None, C.today(self.conn).isoformat(), "moved")
        with self.assertRaisesRegex(C.DomainError, "balance is 40.00"):
            C.archive_gardener(self.conn, self.admin, g)

    def test_duplicate_gardener_warning(self):
        self.gardener("Same")
        with self.assertRaises(C.DuplicateWarning):
            C.add_gardener(self.conn, self.admin, {"name": "Other", "email": "SAME@x.org"})
        C.add_gardener(self.conn, self.admin, {"name": "Other", "email": "same@x.org"}, allow_duplicate=True)
        with self.assertRaises(C.FieldErrors):
            C.add_gardener(self.conn, self.admin, {"name": "NoContact"})


class SeasonAndMoneyTests(Base):
    def test_idempotent_charging(self):
        for i, size in enumerate(C.SIZES):
            self.assign(self.plot(f"S{i}", size), self.gardener(f"G{i}"))
        sid, n = self.season()
        self.assertEqual(n, 3)
        self.assertEqual(C.charge_season(self.conn, self.admin, sid), 0)
        with self.assertRaises(C.FieldErrors) as cm:
            self.season()
        self.assertIn("already exists", cm.exception.errors["year"])
        total = self.conn.execute("SELECT sum(amount) FROM ledger WHERE kind='charge'").fetchone()[0]
        self.assertEqual(total, 4000 + 6000 + 8000)

    def test_concurrent_charging_never_duplicates(self):
        for i in range(5):
            self.assign(self.plot(f"T{i}"), self.gardener(f"H{i}"))
        sid, _ = self.season()
        self.conn.execute("PRAGMA foreign_keys=ON")
        barrier = threading.Barrier(3)

        def go():
            c = store.connect(self.path)
            barrier.wait()
            C.charge_season(c, self.admin, sid)
            c.close()
        ts = [threading.Thread(target=go) for _ in range(3)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        self.assertEqual(self.conn.execute("SELECT count(*) FROM ledger WHERE kind='charge'").fetchone()[0], 5)

    def test_season_validation(self):
        with self.assertRaises(C.FieldErrors) as cm:
            C.open_season(self.conn, self.admin, {"year": "2026", "due_date": "2027-01-01", "fee_small": "0",
                                                  "fee_standard": "-5", "fee_large": "1.234"})
        self.assertEqual(set(cm.exception.errors), {"due_date", "fee_small", "fee_standard", "fee_large"})
        with self.assertRaises(PermissionError):
            C.open_season(self.conn, self.coord, {})

    def test_prorating_and_rounding(self):
        self.assertEqual(C.prorate(6000, 1), 6000)
        self.assertEqual(C.prorate(6000, 12), 500)
        self.assertEqual(C.prorate(4000, 7), 2000)    # 40 x 6/12
        self.assertEqual(C.prorate(4000, 11), 667)    # 66.666.. -> 6.67
        self.assertEqual(C.prorate(1001, 7), 501)     # 500.5 -> half-up 501
        self.assertEqual(C.prorate(1003, 12), 84)     # 83.58 -> 84

    def test_mid_season_prorated_charge(self):
        year = C.today(self.conn).year
        sid, _ = self.season(year)
        C.update_settings(self.conn, self.admin, {"fees.new_holder_charge": "prorated"})
        g = self.gardener("Mid")
        self.assign(self.plot("P1", "small"), g, f"{year}-11-15")
        self.assertEqual(C.season_figures(self.conn, g, sid)["charged"], 667)
        C.update_settings(self.conn, self.admin, {"fees.new_holder_charge": "full"})
        g2 = self.gardener("Full")
        self.assign(self.plot("P2", "small"), g2, f"{year}-11-15")
        self.assertEqual(C.season_figures(self.conn, g2, sid)["charged"], 4000)

    def test_prorate_from_setting(self):
        year = C.today(self.conn).year
        sid, _ = self.season(year)
        C.update_settings(self.conn, self.admin, {"fees.new_holder_charge": "prorated"})
        self.assertEqual(C.get_setting(self.conn, "fees.prorate_from"), "start_date")
        fixed = dt.datetime(year, 7, 10, 12, tzinfo=dt.timezone.utc)
        orig = C.utcnow
        C.utcnow = lambda: fixed
        try:
            g1 = self.gardener("ByStart")
            self.assign(self.plot("S1", "small"), g1, f"{year}-11-15")
            self.assertEqual(C.season_figures(self.conn, g1, sid)["charged"], 667)   # Nov-Dec
            C.update_settings(self.conn, self.admin, {"fees.prorate_from": "recorded_date"})
            g2 = self.gardener("ByRecorded")
            self.assign(self.plot("S2", "small"), g2, f"{year}-11-15")
            self.assertEqual(C.season_figures(self.conn, g2, sid)["charged"], 2000)  # Jul-Dec
            os.environ["FEES_PRORATE_FROM"] = "start_date"
            try:
                self.assertEqual(C.get_setting(self.conn, "fees.prorate_from"), "start_date")
                g3 = self.gardener("EnvWins")
                self.assign(self.plot("S3", "small"), g3, f"{year}-11-15")
                self.assertEqual(C.season_figures(self.conn, g3, sid)["charged"], 667)
            finally:
                del os.environ["FEES_PRORATE_FROM"]
        finally:
            C.utcnow = orig

    def test_current_season_rule(self):
        new, _ = self.season(2026)
        old, _ = self.season(2025)
        self.assertEqual(C.get_setting(self.conn, "seasons.current_rule"), "latest_year")
        self.assertEqual(C.current_season(self.conn)["id"], new)
        C.update_settings(self.conn, self.admin, {"seasons.current_rule": "most_recently_opened"})
        self.assertEqual(C.current_season(self.conn)["id"], old)
        os.environ["SEASONS_CURRENT_RULE"] = "latest_year"
        try:
            self.assertEqual(C.current_season(self.conn)["id"], new)
        finally:
            del os.environ["SEASONS_CURRENT_RULE"]

    def test_amount_parsing(self):
        self.assertEqual(C.parse_amount("40"), (4000, None))
        self.assertEqual(C.parse_amount("0.05"), (5, None))
        for bad in ("0", "-1", "1.234", "abc", ""):
            self.assertIsNotNone(C.parse_amount(bad)[1], bad)
        self.assertEqual(C.parse_amount("-20.5", signed=True), (-2050, None))
        self.assertIn("too large", C.parse_amount("99999999999999999999.00")[1])
        self.assertIn("too large", C.parse_amount("-99999999999999999999", signed=True)[1])

    def test_huge_payment_is_field_error(self):
        g, sid = self._holder()
        C.update_settings(self.conn, self.admin, {"payments.overpayment": "credit"})
        with self.assertRaises(C.FieldErrors) as cm:
            C.record_payment(self.conn, self.coord, g, sid, "99999999999999999999.00", None, "cash")
        self.assertIn("amount", cm.exception.errors)
        self.assertEqual([r["kind"] for r in C.gardener_ledger(self.conn, g)], ["charge"])

    def _holder(self, size="standard"):
        g = self.gardener("Payer")
        self.assign(self.plot("L1", size), g)
        sid, _ = self.season()
        return g, sid

    def test_balance_status_and_ledger(self):
        g, sid = self._holder()
        on_time = dt.date(C.today(self.conn).year, 3, 1)
        late = dt.date(C.today(self.conn).year, 4, 1)
        f = C.season_figures(self.conn, g, sid)
        self.assertEqual(C.due_status(f["charged"], f["balance"], f"{on_time.year}-03-31", on_time), "Unpaid")
        self.assertEqual(C.due_status(f["charged"], f["balance"], f"{on_time.year}-03-31", late), "Overdue")
        p = C.record_payment(self.conn, self.coord, g, sid, "25.00", None, "cash")
        f = C.season_figures(self.conn, g, sid)
        self.assertEqual((f["paid"], f["balance"]), (2500, 3500))
        self.assertEqual(C.due_status(f["charged"], f["balance"], f"{on_time.year}-03-31", on_time), "Partly paid")
        C.void_payment(self.conn, self.coord, p, "typo")
        with self.assertRaisesRegex(C.DomainError, "Already voided"):
            C.void_payment(self.conn, self.coord, p, "again")
        self.assertEqual(C.season_figures(self.conn, g, sid)["balance"], 6000)
        C.record_payment(self.conn, self.coord, g, sid, "60.00", None, "card")
        self.assertEqual(C.due_status(6000, 0, "2000-01-01", on_time), "Paid")
        C.record_adjustment(self.conn, self.admin, g, sid, "-10.00", None, "discount")
        f = C.season_figures(self.conn, g, sid)
        self.assertEqual(f["balance"], -1000)
        self.assertEqual(C.due_status(f["charged"], f["balance"], "2000-01-01", on_time), "In credit")
        C.record_refund(self.conn, self.coord, g, sid, "10.00", None, "cash", "returned")
        led = C.gardener_ledger(self.conn, g)
        self.assertEqual([r["kind"] for r in led], ["charge", "payment", "void", "payment", "adjustment", "refund"])
        self.assertEqual(led[-1]["running"], 0)
        with self.assertRaises(Exception):
            self.conn.execute("UPDATE ledger SET amount=0")
        with self.assertRaises(Exception):
            self.conn.execute("DELETE FROM ledger")

    def test_overpayment_and_refund_limits(self):
        g, sid = self._holder("small")
        C.record_payment(self.conn, self.coord, g, sid, "20.00", None, "cash")
        with self.assertRaises(C.FieldErrors) as cm:
            C.record_payment(self.conn, self.coord, g, sid, "20.01", None, "cash")
        self.assertEqual(cm.exception.errors["amount"], "Balance is 20.00; amount exceeds it")
        with self.assertRaises(C.FieldErrors) as cm:
            C.record_refund(self.conn, self.coord, g, sid, "20.01", None, "cash", "x")
        self.assertEqual(cm.exception.errors["amount"], "Refund cannot exceed 20.00 paid")
        C.update_settings(self.conn, self.admin, {"payments.overpayment": "credit"})
        C.record_payment(self.conn, self.coord, g, sid, "30.00", None, "cash")
        self.assertEqual(C.season_figures(self.conn, g, sid)["balance"], -1000)

    def test_double_submit_saves_once(self):
        g, sid = self._holder()
        a = C.record_payment(self.conn, self.coord, g, sid, "10.00", None, "cash", token="tok1")
        b = C.record_payment(self.conn, self.coord, g, sid, "10.00", None, "cash", token="tok1")
        self.assertEqual(a, b)
        self.assertEqual(self.conn.execute("SELECT count(*) FROM ledger WHERE kind='payment'").fetchone()[0], 1)

    def test_adjustment_admin_only(self):
        g, sid = self._holder()
        with self.assertRaises(PermissionError):
            C.record_adjustment(self.conn, self.coord, g, sid, "-5", None, "x")

    def test_season_totals_equal_sum_of_balances(self):
        for i in range(4):
            self.assign(self.plot(f"Q{i}"), self.gardener(f"Q{i}"))
        sid, _ = self.season()
        gs = [r["id"] for r in self.conn.execute("SELECT id FROM gardeners")]
        C.record_payment(self.conn, self.coord, gs[0], sid, "60", None, "cash")
        C.record_payment(self.conn, self.coord, gs[1], sid, "10", None, "cash")
        t = C.season_totals(self.conn, sid)
        self.assertEqual(t["balance"], sum(C.season_figures(self.conn, g, sid)["balance"] for g in gs))
        self.assertEqual(t["balance"], self.conn.execute("SELECT sum(amount) FROM ledger WHERE season_id=?",
                                                         (sid,)).fetchone()[0])


class AccountTests(Base):
    def test_setup_code_single_use(self):
        with self.assertRaisesRegex(C.DomainError, "Invalid setup code"):
            C.setup(self.conn, "ANY", "G", "EUR", "UTC", "x2", PW, PW)

    def test_last_admin_protection_and_lockout(self):
        with self.assertRaisesRegex(C.DomainError, "last active Admin"):
            C.set_active(self.conn, self.admin, self.admin["id"], False)
        with self.assertRaisesRegex(C.DomainError, "last active Admin"):
            C.set_role(self.conn, self.admin, self.admin["id"], "coordinator")
        for _ in range(4):
            with self.assertRaisesRegex(C.DomainError, "Wrong"):
                C.authenticate(self.conn, "boss", "nope")
        with self.assertRaisesRegex(C.DomainError, "Too many"):
            C.authenticate(self.conn, "boss", "nope")
        with self.assertRaisesRegex(C.DomainError, "Too many"):
            C.authenticate(self.conn, "boss", PW)

    def test_settings_admin_only_and_audited(self):
        with self.assertRaises(PermissionError):
            C.update_settings(self.conn, self.coord, {"offers.expiry_days": "7"})
        C.update_settings(self.conn, self.admin, {"offers.expiry_days": "7"})
        row = self.conn.execute("SELECT * FROM audit WHERE action='setting.change'").fetchone()
        self.assertEqual(row["summary"], "offers.expiry_days")


class WebTests(Base):
    """Role enforcement and CSRF through the HTTP layer."""

    def setUp(self):
        super().setUp()
        self.app = App(self.path, "secret")

    def call(self, method, path, cookies=None, form=None):
        headers = {"Cookie": "; ".join(f"{k}={v}" for k, v in (cookies or {}).items())}
        body = urlencode(form or {}).encode()
        r = self.app.handle(method, path, headers, body)
        for k, v in r.headers:
            if k == "Set-Cookie" and cookies is not None:
                name, _, rest = v.partition("=")
                cookies[name] = rest.split(";")[0]
        return r

    def login(self, username, password):
        jar = {}
        self.call("GET", "/login", jar)
        r = self.call("POST", "/login", jar, {"username": username, "password": password, "_csrf": jar["pk_pre"]})
        self.assertEqual(r.status, 303)
        return jar

    def csrf(self, jar):
        body = self.call("GET", "/account/password", jar).body.decode()
        return re.search(r'name="_csrf" value="([^"]+)"', body).group(1)

    def test_roles_enforced_by_server(self):
        uid, temp = C.create_user(self.conn, self.admin, "c2", "coordinator")
        jar = self.login("c2", temp)
        # must change temporary password first
        self.assertEqual(dict(self.call("GET", "/plots", jar).headers)["Location"], "/account/password")
        tok = self.csrf(jar)
        r = self.call("POST", "/account/password", jar, {"current": temp, "new": PW + "!", "new2": PW + "!", "_csrf": tok})
        self.assertEqual(r.status, 303)
        self.assertEqual(self.call("GET", "/plots", jar).status, 200)
        for path in ("/settings", "/users", "/audit", "/seasons/new"):
            self.assertEqual(self.call("GET", path, jar).status, 403, path)
        r = self.call("POST", "/settings", jar, {"garden_name": "Hacked", "_csrf": tok})
        self.assertEqual(r.status, 403)
        self.assertEqual(C.get_setting(self.conn, "garden_name"), "Test Garden")

    def test_current_season_rule_on_settings_page(self):
        jar = self.login("boss", PW)
        page = self.call("GET", "/settings", jar).body.decode()
        self.assertIn('name="seasons.current_rule"', page)
        vals = dict(re.findall(r'name="([a-z_.]+)" type="[^"]*" value="([^"]*)"', page))
        for name, body in re.findall(r'<select[^>]*name="([a-z_.]+)"[^>]*>(.*?)</select>', page, re.S):
            vals[name] = re.search(r'<option value="([^"]*)"[^>]*selected', body).group(1)
        vals["seasons.current_rule"], vals["_csrf"] = "most_recently_opened", self.csrf(jar)
        self.assertEqual(self.call("POST", "/settings", jar, vals).status, 303)
        self.assertEqual(C.get_setting(self.conn, "seasons.current_rule"), "most_recently_opened")

    def test_csrf_required_and_anonymous_redirect(self):
        self.assertEqual(dict(self.call("GET", "/plots", {}).headers)["Location"], "/login")
        jar = self.login("boss", PW)
        r = self.call("POST", "/plots/new", jar, {"code": "X1", "size": "small", "_csrf": "wrong"})
        self.assertEqual(r.status, 403)
        r = self.call("POST", "/plots/new", jar, {"code": "X1", "size": "small", "_csrf": self.csrf(jar)})
        self.assertEqual(r.status, 303)

    def test_release_offer_accept_pay_flow(self):
        sid, _ = self.season()
        old, new = self.gardener("Old"), self.gardener("New")
        pid = self.plot("F1", "small")
        self.assign(pid, old)
        C.add_to_waitlist(self.conn, self.admin, new, "small")
        jar = self.login("boss", PW)
        tok = self.csrf(jar)
        v = lambda: str(C.get_plot(self.conn, pid)["version"])  # noqa: E731
        t = C.today(self.conn).isoformat()
        r = self.call("POST", f"/plots/{pid}/release", jar, {"_csrf": tok, "version": v(), "end_date": t, "reason": "moved"})
        self.assertIn("released", dict(r.headers)["Location"])
        page = self.call("GET", f"/plots/{pid}/offer", jar).body.decode()
        self.assertIn("New", page)
        entry = re.search(r'name="entry_id" value="(\d+)"', page).group(1)
        form = {"_csrf": tok, "version": v(), "entry_id": entry}
        self.assertEqual(self.call("POST", f"/plots/{pid}/offer", jar, form).status, 303)
        r = self.call("POST", f"/plots/{pid}/offer", jar, form)  # stale second offer
        self.assertIn("just+offered+to+New", dict(r.headers)["Location"])
        oid = C.open_offer_for_plot(self.conn, pid)["id"]
        self.call("POST", f"/offers/{oid}/outcome", jar, {"_csrf": tok, "outcome": "accepted", "start_date": t})
        self.assertEqual(C.get_plot(self.conn, pid)["status"], "occupied")
        self.assertEqual(C.season_figures(self.conn, new, sid)["charged"], 4000)
        pay = {"_csrf": tok, "kind": "payment", "token": "abc", "amount": "15.00", "date": t, "season_id": str(sid),
               "method": "cash"}
        self.call("POST", f"/gardeners/{new}/money", jar, pay)
        self.call("POST", f"/gardeners/{new}/money", jar, pay)
        self.assertEqual(C.season_figures(self.conn, new, sid)["paid"], 1500)
        r = self.call("POST", f"/gardeners/{new}/money", jar, dict(pay, token="x2", amount="99"))
        self.assertIn("Balance is 25.00; amount exceeds it", r.body.decode())

    def test_payments_export_empty_range_is_headers_only(self):
        jar = self.login("boss", PW)
        body = self.call("GET", "/export/payments.csv?from=2026-06-01&to=2026-06-30", jar).body.decode()
        self.assertEqual(body.strip().splitlines(),
                         ["date,gardener,season,type,amount_received,method,reference,reason,user"])
        g = self.gardener("Payer")
        self.assign(self.plot("E1"), g)
        sid, _ = self.season()
        C.record_payment(self.conn, self.admin, g, sid, "10.00", "2026-06-15", "cash")
        lines = self.call("GET", "/export/payments.csv?from=2026-06-01&to=2026-06-30", jar).body.decode().strip().splitlines()
        self.assertEqual(len(lines), 3)
        self.assertTrue(lines[-1].startswith("TOTAL,,,,10.00"))

    def test_admin_pages_render(self):
        demo_dir = tempfile.mkdtemp()
        try:
            c = store.connect(store.db_path(demo_dir))
            store.migrate(c, demo_dir, log=lambda *_: None)
            pw = demo.load(c)
            with self.assertRaisesRegex(C.DomainError, "only be loaded into an empty install"):
                demo.load(c)
            app = App(store.db_path(demo_dir), "s")
            self.app = app
            jar = self.login("admin", pw["admin"])
            pages = ["/", "/plots", "/plots?status=occupied", "/gardeners", "/waitlist", "/dues", "/dues?sort=balance",
                     "/seasons", "/seasons/new", "/users", "/settings", "/audit", "/export/dues.csv",
                     "/export/payments.csv?from=2000-01-01&to=2100-01-01", "/export/plots.csv", "/export/waitlist.csv"]
            pages += [f"/plots/{i}" for i in range(1, 41)] + [f"/gardeners/{i}" for i in range(1, 46)]
            pages += ["/gardeners/1/money?kind=payment", "/gardeners/1/money?kind=adjustment", "/plots/38/offer",
                      "/plots/38/assign"]
            for p in pages:
                r = self.call("GET", p, jar)
                self.assertEqual(r.status, 200, p)
            csv_body = self.call("GET", "/export/dues.csv", jar).body.decode()
            self.assertTrue(csv_body.startswith("gardener,email,phone,plot,charged,paid,balance,status"))
            c.close()
        finally:
            shutil.rmtree(demo_dir)


class HttpServerTests(Base):
    """Raw-socket checks against the real HTTP server."""

    def setUp(self):
        super().setUp()
        from plotkeeper.web import serve
        self.server = serve(App(self.path, "secret"), "127.0.0.1", 0)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.port = self.server.server_address[1]

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        super().tearDown()

    def raw(self, data):
        import socket
        with socket.create_connection(("127.0.0.1", self.port), 5) as so:
            so.sendall(data)
            return so.recv(1024)

    def test_bad_content_length_rejected(self):
        for value in (b"-1", b"abc", b"1e3"):
            reply = self.raw(b"POST /login HTTP/1.1\r\nHost: x\r\nContent-Length: " + value + b"\r\n\r\n")
            self.assertTrue(reply.startswith(b"HTTP/1.0 400"), reply[:40])


    def test_idle_connection_is_closed(self):
        from plotkeeper import web
        import socket
        old = web.REQUEST_TIMEOUT
        self.server.RequestHandlerClass.timeout = 1
        try:
            with socket.create_connection(("127.0.0.1", self.port), 5) as so:
                so.sendall(b"GET / HTTP/1.1\r\nHost: x\r\n")
                so.settimeout(5)
                self.assertEqual(so.recv(1024), b"")
        finally:
            self.server.RequestHandlerClass.timeout = old

    def test_connections_are_bounded(self):
        from plotkeeper import web
        self.assertLessEqual(self.server.slots._value, web.MAX_CONNECTIONS)
        self.assertGreater(web.REQUEST_TIMEOUT, 0)


class PasswordChangeSessionTests(Base):
    def test_change_password_ends_other_sessions_only(self):
        mine = C.create_session(self.conn, self.admin["id"])
        other = C.create_session(self.conn, self.admin["id"])
        C.change_password(self.conn, self.admin["id"], PW, "another long password", "another long password",
                          keep_token=mine)
        self.assertIsNotNone(C.load_session(self.conn, mine))
        self.assertIsNone(C.load_session(self.conn, other))


class BackupTests(Base):
    def test_backup_restore_round_trip(self):
        self.plot("KEEP")
        path = store.backup(self.conn, self.dir)
        self.plot("LATER")
        self.conn.close()
        store.restore(self.dir, path)
        self.conn = store.connect(self.path)
        codes = [r["code"] for r in self.conn.execute("SELECT code FROM plots")]
        self.assertEqual(codes, ["KEEP"])
        with self.assertRaises(ValueError):
            store.validate_backup(os.path.join(self.dir, "nope.db"))


if __name__ == "__main__":
    unittest.main()
