import json, os, textwrap
claims = {c["id"]: c for c in json.load(open("_helpers/claims.json"))["claims"]}
HDR = "from _helpers.driver import *\n\n\n"
T = {}
T["c1"] = """
s = System(monkeypatch)
cl = s.client()
r = cl.post("/setup", dict(code="WRONG-CODE", garden_name="G", currency="EUR", timezone="UTC", username="boss", password=PW, password2=PW))
assert "Invalid setup code" in r.text
assert s.q("SELECT count(*) n FROM users")[0]["n"] == 0
"""
T["c2"] = """
s = System(monkeypatch)
s.setup_admin()
cl = s.client()
r = cl.post("/setup", dict(code=s.code, garden_name="G", currency="EUR", timezone="UTC", username="boss2", password=PW, password2=PW))
r = cl.follow(r) if r.location else r
assert s.q("SELECT count(*) n FROM users")[0]["n"] == 1
assert "Invalid setup code" in r.text or r.location
"""
T["c3"] = """
s = System(monkeypatch)
cl = s.client()
r = cl.post("/setup", dict(code=s.code, garden_name="G", currency="EUR", timezone="UTC", username="boss", password="a"*11, password2="a"*11))
assert r.status != 303 and s.q("SELECT count(*) n FROM users")[0]["n"] == 0
assert 'class="err"' in r.body
r = cl.post("/setup", dict(code=s.code, garden_name="G", currency="EUR", timezone="UTC", username="boss", password="a"*12, password2="a"*12))
assert r.status == 303 and s.q("SELECT count(*) n FROM users")[0]["n"] == 1
"""
T["c4"] = """
s = System(monkeypatch)
cl = s.client()
r = cl.post("/setup", dict(code=s.code, garden_name="My Garden", currency="GBP", timezone="Europe/London", username="bossy", password=PW, password2=PW+"x"))
assert 'class="err"' in r.body
for v in ("My Garden", "GBP", "Europe/London", "bossy"):
    assert f'value="{v}"' in r.body, v
assert s.q("SELECT count(*) n FROM users")[0]["n"] == 0
"""
T["c5"] = """
s = System(monkeypatch)
a = s.setup_admin()
t = a.c.get("/").text
assert "No plots yet" in t and "Nobody is waiting" in t and "No season yet" in t
"""
T["c6"] = """
import subprocess, sys
s = System(monkeypatch)
a = s.setup_admin()
a.new_plot("A-1")
env = dict(os.environ, PLOTKEEPER_DATA_DIR=s.dir)
p = subprocess.run([sys.executable, "-m", "plotkeeper", "demo"], cwd=REPO, env=env, capture_output=True, text=True, timeout=60)
assert p.returncode != 0
assert "Demo data can only be loaded into an empty install" in p.stdout + p.stderr
assert s.q("SELECT count(*) n FROM plots")[0]["n"] == 1
"""
T["c7"] = """
import socket, subprocess, sys, tempfile
sk = socket.socket(); sk.bind(("127.0.0.1", 0)); sk.listen(1); port = sk.getsockname()[1]
d = tempfile.mkdtemp()
env = dict(os.environ, PLOTKEEPER_DATA_DIR=d, PLOTKEEPER_PORT=str(port))
p = subprocess.run([sys.executable, "-m", "plotkeeper", "start"], cwd=REPO, env=env, capture_output=True, text=True, timeout=20)
sk.close()
assert p.returncode != 0
out = p.stdout + p.stderr
assert str(port) in out and "PLOTKEEPER_PORT" in out
"""
T["c8"] = """
s = System(monkeypatch); a = s.setup_admin()
a.new_plot("B-07")
r = a.add_plot("B-07")
assert "Plot code B-07 already exists" in r.text
assert s.q("SELECT count(*) n FROM plots")[0]["n"] == 1
"""
T["c9"] = """
s = System(monkeypatch); a = s.setup_admin()
a.new_plot("B-07"); p8 = a.new_plot("B-08")
r = a.edit_plot(p8, code="B-07")
assert "already exists" in r.text
assert a.plot(p8)["code"] == "B-08"
"""
T["c10"] = """
s = System(monkeypatch); a = s.setup_admin()
r = a.add_plot(""); assert r.status != 303
r = a.add_plot("X"*21); assert r.status != 303
assert s.q("SELECT count(*) n FROM plots")[0]["n"] == 0
r = a.add_plot("Y"*20); assert r.status == 303
assert a.plot(a.plot_id("Y"*20))["status"] == "available"
"""
T["c11"] = """
s = System(monkeypatch); a = s.setup_admin()
r = a.add_plot("H-1", size="huge")
assert r.status != 303 and s.q("SELECT count(*) n FROM plots")[0]["n"] == 0
"""
T["c12"] = """
s = System(monkeypatch); a = s.setup_admin()
po = a.new_plot("O-1"); pf = a.new_plot("F-1")
g = a.new_gardener("Holder"); assert a.assign(po, g, "2026-05-01").status == 303
a.waiter("Waiter"); assert a.offer(pf).status == 303
for pid, st in ((po, "occupied"), (pf, "offered")):
    for act in ("out_of_service", "retire"):
        r = a.plot_status(pid, act)
        assert "Release the holder or withdraw the offer first" in r.msg, (act, r.msg)
        assert a.plot(pid)["status"] == st
"""
T["c13"] = """
s = System(monkeypatch); a = s.setup_admin()
p = a.new_plot("S-1"); a.waiter("W")
a.plot_status(p, "out_of_service", "broken fence")
assert a.plot(p)["status"] == "out_of_service"
r = a.offer_preview(p); assert 'name="entry_id"' not in r.body
r = a.c.post(f"/plots/{p}/offer", dict(version=a.plot(p)["version"], entry_id=a.entry(s.q("SELECT gardener_id FROM waitlist")[0]["gardener_id"])["id"]), referer=f"/plots/{p}")
g2 = a.new_gardener("Other")
r2 = a.assign(p, g2, "2026-05-10")
assert a.plot(p)["status"] == "out_of_service"
assert s.q("SELECT count(*) n FROM offers")[0]["n"] == 0
assert s.q("SELECT count(*) n FROM assignments")[0]["n"] == 0
"""
T["c14"] = """
s = System(monkeypatch); a = s.setup_admin()
p = a.new_plot("R-1"); q = a.new_plot("R-2")
a.plot_status(p, "out_of_service", "x"); a.plot_status(p, "return")
assert a.plot(p)["status"] == "available"
assert a.plot_status(p, "retire", "gone").status == 303 and a.plot(p)["status"] == "retired"
a.plot_status(q, "out_of_service", "x")
assert a.plot_status(q, "retire", "gone").status == 303 and a.plot(q)["status"] == "retired"
lst = a.c.get("/plots").text
assert "R-1" not in lst
d = a.c.get(f"/plots/{p}").text
assert "History" in d and "etire" in d
"""
T["c15"] = """
s = System(monkeypatch); a = s.setup_admin()
p = a.new_plot("R-1"); a.waiter("W")
a.plot_status(p, "retire", "gone")
a.plot_status(p, "return")
a.offer_preview(p)
w = s.q("SELECT id FROM waitlist")[0]["id"]
a.c.post(f"/plots/{p}/offer", dict(version=a.plot(p)["version"], entry_id=w), referer=f"/plots/{p}")
a.assign(p, a.new_gardener("Z"), "2026-05-10")
assert a.plot(p)["status"] == "retired"
assert s.q("SELECT count(*) n FROM offers")[0]["n"] == 0 and s.q("SELECT count(*) n FROM assignments")[0]["n"] == 0
"""
T["c16"] = """
s = System(monkeypatch); a = s.setup_admin()
p = a.new_plot("E-1"); v = a.plot(p)["version"]
assert a.edit_plot(p, version=v, notes="first").status == 303
r = a.edit_plot(p, version=v, notes="second")
assert "This plot changed since you opened it" in r.text + r.msg
assert a.plot(p)["notes"] == "first"
"""
T["c17"] = """
s = System(monkeypatch); a = s.setup_admin()
p = a.new_plot("E-1")
s.clock.advance(days=1)
assert a.edit_plot(p, size="large", notes="raised beds").status == 303
d = a.c.get(f"/plots/{p}").text
h = d[d.find("History"):]
assert "2026-05-11" in h and "large" in h
"""
T["c18"] = """
s = System(monkeypatch); a = s.setup_admin()
r = a.add_gardener("Nobody")
assert r.status != 303 and s.q("SELECT count(*) n FROM gardeners")[0]["n"] == 0
"""
T["c19"] = """
s = System(monkeypatch); a = s.setup_admin()
g = a.new_gardener("Ann", "ann@example.org")
r = a.add_gardener("Annie", "ann@example.org")
assert r.status != 303
assert f'/gardeners/{g}"' in r.body and "uplicate" in r.text
assert s.q("SELECT count(*) n FROM gardeners")[0]["n"] == 1
"""
T["c20"] = """
s = System(monkeypatch); a = s.setup_admin()
p = a.new_plot("B-07"); g = a.new_gardener("H"); a.assign(p, g, "2026-05-01")
r = a.wait(g)
assert "B-07" in (r.msg + r.text)
assert s.q("SELECT count(*) n FROM waitlist")[0]["n"] == 0
"""
T["c21"] = """
s = System(monkeypatch); a = s.setup_admin()
a.waiter("A1"); a.waiter("A2"); g = a.waiter("A3")
r = a.wait(g, "small")
assert "position 3" in (r.msg + r.text)
assert s.q("SELECT count(*) n FROM waitlist")[0]["n"] == 3
"""
T["c22"] = """
s = System(monkeypatch); a = s.setup_admin()
a.waiter("Alpha"); a.waiter("Beta", joined="2025-05-10")
assert a.waitlist_names() == ["Beta", "Alpha"]
t = a.c.get("/waitlist").text
assert t.find("Beta") < t.find("Alpha") and "365" in t
"""
T["c23"] = """
s = System(monkeypatch); a = s.setup_admin()
a.waiter("First", joined="2025-01-01"); s.clock.advance(minutes=1); a.waiter("Second", joined="2025-01-01")
assert a.waitlist_names() == ["First", "Second"]
"""
T["c24"] = """
s = System(monkeypatch); a = s.setup_admin()
gs = [a.waiter(n) for n in ("P1", "P2", "P3", "P4")]
e = a.entry(gs[1])
r = a.c.post(f"/waitlist/{e['id']}/remove", dict(reason="withdrew", note=""), referer="/waitlist")
assert a.entry(gs[1])["status"] == "removed"
assert a.waitlist_names() == ["P1", "P3", "P4"]
assert "withdrew" in a.c.get(f"/gardeners/{gs[1]}").text.lower()
"""
T["c25"] = """
s = System(monkeypatch); a = s.setup_admin()
a.waiter("P1"); g = a.waiter("P2", "small"); a.waiter("P3")
e = a.entry(g)
a.c.post(f"/waitlist/{e['id']}/preference", dict(preference="large"), referer="/waitlist")
assert a.entry(g)["preference"] == "large"
assert a.waitlist_names() == ["P1", "P2", "P3"]
"""
T["c26"] = """
s = System(monkeypatch); a = s.setup_admin()
a.open_season(2026)
g1 = a.new_gardener("Credit"); g2 = a.new_gardener("Owes")
sid = a.season_id(2026)
assert a.money(g1, "adjustment", "-5.00", season_id=sid, reason="waiver").status == 303
assert a.money(g2, "adjustment", "10.00", season_id=sid, reason="fee").status == 303
for g in (g1, g2):
    r = a.c.post(f"/gardeners/{g}/archive", dict(archived="1"), referer=f"/gardeners/{g}")
    assert s.q("SELECT archived FROM gardeners WHERE id=?", g)[0]["archived"] == 0, g
"""
T["c27"] = """
s = System(monkeypatch); a = s.setup_admin()
g = a.new_gardener("Zelda Quiet"); a.new_gardener("Other Person")
a.c.post(f"/gardeners/{g}/archive", dict(archived="1"), referer=f"/gardeners/{g}")
assert s.q("SELECT archived FROM gardeners WHERE id=?", g)[0]["archived"] == 1
assert "Zelda" not in a.c.get("/gardeners").text
assert "Zelda" in a.c.get("/gardeners?q=Zelda").text
"""
T["c28"] = """
s = System(monkeypatch); a = s.setup_admin()
a.waiter("Large1", "large"); a.waiter("Small2", "small"); a.waiter("Any3", "any")
p = a.new_plot("S-1", "standard")
t = a.offer_preview(p).text
assert "Any3" in t and "Large1" not in t and "Small2" not in t
"""
T["c29"] = """
s = System(monkeypatch); a = s.setup_admin()
a.waiter("L1", "large"); p = a.new_plot("S-1", "small")
t = a.offer_preview(p).text
assert "No one on the waiting list matches a small plot" in t
assert a.plot(p)["status"] == "available"
"""
T["c30"] = """
s = System(monkeypatch); a = s.setup_admin()
a.waiter("First"); a.waiter("Second")
pa = a.new_plot("A-1"); pb = a.new_plot("B-1")
assert a.offer(pa).status == 303
t = a.offer_preview(pb).text
assert "Second" in t and "First" not in t
"""
T["c31"] = """
s = System(monkeypatch); a = s.setup_admin()
g = a.waiter("W"); p = a.new_plot("A-1")
a.offer(p)
assert a.plot(p)["status"] == "offered"
o = a.open_offer(p)
assert o["expires_on"] == "2026-05-24"
assert a.entry(g)["status"] == "offered"
"""
T["c32"] = """
s = System(monkeypatch); a = s.setup_admin()
a.waiter("W1"); a.waiter("W2"); p = a.new_plot("A-1")
r1 = a.offer_preview(p); r2 = a.offer_preview(p)
import re
v = re.search(r'name="version" value="(\\d+)"', r1.body).group(1)
e1 = re.search(r'name="entry_id" value="(\\d+)"', r1.body).group(1)
x = a.c.post(f"/plots/{p}/offer", dict(version=v, entry_id=e1), referer=f"/plots/{p}")
y = a.c.post(f"/plots/{p}/offer", dict(version=v, entry_id=e1), referer=f"/plots/{p}")
assert s.q("SELECT count(*) n FROM offers")[0]["n"] == 1
assert "changed" in y.msg or "just offered" in y.msg
"""
T["c33"] = """
s = System(monkeypatch); a = s.setup_admin()
g = a.waiter("W"); p = a.new_plot("A-1"); a.offer(p)
s.clock.advance(days=30)
assert a.plot(p)["status"] == "offered"
assert "Expired" in a.c.get("/").text
assert a.entry(g)["status"] == "offered" and a.open_offer(p)["status"] == "open"
"""
T["c34"] = """
s = System(monkeypatch); a = s.setup_admin()
a.waiter("W"); p = a.new_plot("A-1"); a.offer(p)
s.clock.advance(days=13)
t = a.c.get("/").text
assert "1 open, 0 expired" in t
"""
T["c35"] = """
s = System(monkeypatch); a = s.setup_admin()
a.waiter("P1", "large"); g = a.waiter("P2"); a.waiter("P3")
p = a.new_plot("A-1"); a.offer(p)
assert a.entry(g)["status"] == "offered"
a.outcome(p, "withdrawn")
assert a.entry(g)["status"] == "active" and a.plot(p)["status"] == "available"
assert a.waitlist_names() == ["P1", "P2", "P3"]
"""
T["c36"] = """
s = System(monkeypatch); a = s.setup_admin()
g = a.waiter("P1"); a.waiter("P2")
p = a.new_plot("A-1"); a.offer(p); a.outcome(p, "declined")
assert a.plot(p)["status"] == "available"
assert a.waitlist_names() == ["P1", "P2"]
"""
T["c37"] = """
s = System(monkeypatch); a = s.setup_admin()
a.set("waitlist.decline_policy", "move_to_end")
for n in ("P1", "P2", "P3", "P4", "P5"): a.waiter(n)
g = s.q("SELECT id FROM gardeners WHERE name='P1'")[0]["id"]
p = a.new_plot("A-1"); a.offer(p)
s.clock.advance(days=2)
a.outcome(p, "declined")
assert a.entry(g)["joined_at"].startswith("2026-05-12")
assert a.waitlist_names() == ["P2", "P3", "P4", "P5", "P1"]
"""
T["c38"] = """
s = System(monkeypatch); a = s.setup_admin()
g = a.waiter("P1")
p = a.new_plot("A-1"); a.offer(p); a.outcome(p, "declined")
a.offer(p); s.clock.advance(days=20); a.outcome(p, "expired")
e = a.entry(g)
assert e["status"] == "removed" and "declined twice" in (e["close_reason"] or "")
"""
T["c39"] = """
s = System(monkeypatch); a = s.setup_admin()
g = a.waiter("P1")
p = a.new_plot("A-1"); a.offer(p); a.outcome(p, "declined")
assert a.entry(g)["status"] == "active" and a.waitlist_names() == ["P1"]
"""
T["c40"] = """
s = System(monkeypatch); a = s.setup_admin()
a.open_season(2026)
g = a.waiter("P1"); p = a.new_plot("A-1"); a.offer(p)
a.outcome(p, "accepted", "2026-05-12")
asg = s.q("SELECT * FROM assignments WHERE plot_id=?", p)[0]
assert asg["start_date"] == "2026-05-12" and asg["gardener_id"] == g
assert a.entry(g)["status"] == "placed" and a.plot(p)["status"] == "occupied"
ch = [l for l in a.ledger(g) if l["kind"] == "charge"]
assert len(ch) == 1 and ch[0]["amount"] == 6000
"""
T["c41"] = """
s = System(monkeypatch); a = s.setup_admin()
g = a.waiter("P1"); p = a.new_plot("A-1"); a.offer(p)
a.outcome(p, "accepted", "2026-05-10")
assert a.plot(p)["status"] == "occupied" and a.ledger(g) == []
"""
T["c42"] = """
s = System(monkeypatch); a = s.setup_admin()
p = a.new_plot("A-1"); g0 = a.new_gardener("Old")
a.assign(p, g0, "2026-01-01"); a.release(p, "2026-06-01")
s.clock.set(utc(2026, 6, 5))
g = a.waiter("P1"); a.offer(p)
r = a.outcome(p, "accepted", "2026-05-31")
assert a.plot(p)["status"] == "offered" and a.entry(g)["status"] == "offered"
assert s.q("SELECT count(*) n FROM assignments WHERE gardener_id=?", g)[0]["n"] == 0
"""
T["c43"] = """
s = System(monkeypatch); a = s.setup_admin()
a.c.post("/users", dict(username="coord", role="coordinator"))
pw = re.search(r"temporary password[^A-Za-z0-9_-]*([A-Za-z0-9_-]{8,})", a.c.get("/users").text)
import plotkeeper.core as CC
p = a.new_plot("A-1"); g = a.new_gardener("G")
c = s.db(); c.execute("UPDATE users SET password_hash=?, must_change=0 WHERE username='coord'", (CC.hash_password(PW),)); c.commit(); c.close()
cl, r = s.login("coord", PW)
r = cl.post(f"/plots/{p}/assign", dict(version=a.plot(p)["version"], gardener_id=g, start_date="2026-05-10", reason="x"))
assert r.status == 403
assert a.plot(p)["status"] == "available"
"""
T["c44"] = """
s = System(monkeypatch); a = s.setup_admin()
p = a.new_plot("A-1"); q = a.new_plot("B-1")
h = a.new_gardener("Holder"); a.assign(q, h, "2026-05-01")
a.assign(p, h, "2026-05-10")
assert a.plot(p)["status"] == "available"
g = a.new_gardener("Free")
a.assign(p, g, "2026-05-10", reason="")
assert a.plot(p)["status"] == "available"
assert a.assign(p, g, "2026-05-10", reason="wheelchair access").status == 303
assert a.plot(p)["status"] == "occupied"
assert s.q("SELECT count(*) n FROM audit WHERE action LIKE '%assign%'")[0]["n"] >= 1
"""
T["c45"] = """
s = System(monkeypatch); a = s.setup_admin()
p = a.new_plot("A-1"); g = a.new_gardener("H"); a.assign(p, g, "2026-01-01")
a.open_season(2026); sid = a.season_id(2026)
a.money(g, "payment", "30.00", season_id=sid)
a.set("plots.release_with_balance", "block")
r = a.release(p, "2026-05-10")
assert "Gardener owes 30.00 for 2026; record payment or adjustment first" in r.msg
assert a.plot(p)["status"] == "occupied"
a.set("plots.release_with_balance", "allow")
assert a.release(p, "2026-05-10").status == 303 and a.plot(p)["status"] == "available"
assert len([l for l in a.ledger(g) if l["kind"] == "charge"]) == 1
"""
T["c46"] = """
s = System(monkeypatch); a = s.setup_admin()
sizes = ["small", "standard", "large", "standard", "small", "large", "small"]
for i, z in enumerate(sizes):
    p = a.new_plot(f"P-{i}", z)
    if i < 5: a.assign(p, a.new_gardener(f"G{i}"), "2026-01-01")
assert a.open_season(2026).status == 303
ch = s.q("SELECT amount FROM ledger WHERE kind='charge' ORDER BY id")
assert sorted(c["amount"] for c in ch) == sorted([4000, 6000, 8000, 6000, 4000])
assert "2026" in a.c.get("/seasons").text
"""
T["c47"] = """
import threading
s = System(monkeypatch); a = s.setup_admin()
p = a.new_plot("A-1"); a.assign(p, a.new_gardener("G"), "2026-01-01")
a.open_season(2026)
r = a.open_season(2026)
assert "Season 2026 already exists" in r.text + r.msg
s2 = System(monkeypatch); b = s2.setup_admin(); q = b.new_plot("A-1"); b.assign(q, b.new_gardener("G"), "2026-01-01")
c2 = s2.client(); c2.cookies = dict(b.c.cookies)
th = [threading.Thread(target=b.open_season, args=(2026,)) for _ in range(2)]
[t.start() for t in th]; [t.join() for t in th]
assert s2.q("SELECT count(*) n FROM ledger WHERE kind='charge'")[0]["n"] == 1
assert s.q("SELECT count(*) n FROM ledger WHERE kind='charge'")[0]["n"] == 1
"""
T["c48"] = """
s = System(monkeypatch); a = s.setup_admin()
for kw in (dict(small="0"), dict(small="-5.00"), dict(due="2027-01-01")):
    r = a.open_season(2026, **kw)
    assert r.status != 303 and s.q("SELECT count(*) n FROM seasons")[0]["n"] == 0, kw
assert a.open_season(2026, due="2026-12-31").status == 303
assert s.q("SELECT count(*) n FROM seasons")[0]["n"] == 1
"""
T["c49"] = """
import plotkeeper.core as CC
s = System(monkeypatch); a = s.setup_admin()
a.c.post("/users", dict(username="coord", role="coordinator"))
c = s.db(); c.execute("UPDATE users SET password_hash=?, must_change=0 WHERE username='coord'", (CC.hash_password(PW),)); c.commit(); c.close()
cl, r = s.login("coord", PW)
r = cl.post("/seasons/new", dict(step="confirm", year="2026", due_date="2026-03-31", fee_small="40.00", fee_standard="60.00", fee_large="80.00"))
assert r.status == 403 and s.q("SELECT count(*) n FROM seasons")[0]["n"] == 0
"""
T["c50"] = """
s = System(monkeypatch); a = s.setup_admin()
p = a.new_plot("A-1"); g = a.new_gardener("G"); a.assign(p, g, "2026-01-01")
a.open_season(2026)
a.set("fee.standard", "70.00")
ch = [l for l in a.ledger(g) if l["kind"] == "charge"]
assert len(ch) == 1 and ch[0]["amount"] == 6000
"""
T["c51"] = """
s = System(monkeypatch, now=utc(2026, 1, 10)); a = s.setup_admin()
a.open_season(2026); a.set("fees.new_holder_charge", "prorated")
g1 = a.waiter("Jan"); p1 = a.new_plot("A-1"); a.offer(p1); a.outcome(p1, "accepted", "2026-01-10")
s.clock.set(utc(2026, 10, 5))
g2 = a.waiter("Oct"); p2 = a.new_plot("A-2"); a.offer(p2); a.outcome(p2, "accepted", "2026-10-05")
assert [l["amount"] for l in a.ledger(g1) if l["kind"] == "charge"] == [6000]
assert [l["amount"] for l in a.ledger(g2) if l["kind"] == "charge"] == [1500]
"""
T["c52"] = """
s = System(monkeypatch, now=utc(2026, 10, 5)); a = s.setup_admin()
a.open_season(2026, small="60.50"); a.set("fees.new_holder_charge", "prorated")
g = a.waiter("Oct", "small"); p = a.new_plot("A-1", "small"); a.offer(p); a.outcome(p, "accepted", "2026-10-05")
assert [l["amount"] for l in a.ledger(g) if l["kind"] == "charge"] == [1513]
"""
T["c53"] = """
s = System(monkeypatch); a = s.setup_admin()
p = a.new_plot("A-1"); g = a.new_gardener("G"); a.assign(p, g, "2026-01-01"); a.open_season(2026)
for amt in ("0", "-5.00", "10.001"):
    r = a.money(g, "payment", amt)
    assert r.status != 303, amt
assert [l["kind"] for l in a.ledger(g)] == ["charge"]
assert a.money(g, "payment", "0.01").status == 303
assert [l["amount"] for l in a.ledger(g) if l["kind"] == "payment"] == [-1]
"""
T["c54"] = """
s = System(monkeypatch); a = s.setup_admin()
p = a.new_plot("A-1", "small"); g = a.new_gardener("G"); a.assign(p, g, "2026-01-01"); a.open_season(2026)
r = a.money(g, "payment", "40.01")
assert "Balance is 40.00; amount exceeds it" in r.text
assert a.money(g, "payment", "40.00").status == 303
t = a.c.get(f"/dues?season={a.season_id(2026)}").text
assert "Paid" in t and "Partly" not in t.split("Paid")[-1][:0]
assert C.due_status(4000, 0, "2026-03-31", dt.date(2026, 5, 10)) == "Paid"
"""
T["c55"] = """
s = System(monkeypatch); a = s.setup_admin()
p = a.new_plot("A-1"); g = a.new_gardener("G"); a.assign(p, g, "2026-01-01"); a.open_season(2026)
a.money(g, "payment", "60.00")
r = a.money(g, "refund", "60.01", reason="moved away")
assert "Refund cannot exceed 60.00 paid" in r.text
assert a.money(g, "refund", "60.00", reason="moved away").status == 303
rf = [l for l in a.ledger(g) if l["kind"] == "refund"]
assert len(rf) == 1 and abs(rf[0]["amount"]) == 6000
"""
T["c56"] = """
s = System(monkeypatch); a = s.setup_admin()
p = a.new_plot("A-1"); g = a.new_gardener("G"); a.assign(p, g, "2026-01-01"); a.open_season(2026)
a.money(g, "payment", "20.00")
pid = [l for l in a.ledger(g) if l["kind"] == "payment"][0]["id"]
assert a.c.post(f"/ledger/{pid}/void", dict(reason="typo"), referer=f"/gardeners/{g}").status == 303
r = a.c.post(f"/ledger/{pid}/void", dict(reason="typo"), referer=f"/gardeners/{g}")
assert "Already voided" in r.msg + r.text
assert len([l for l in a.ledger(g) if l["kind"] == "void"]) == 1
t = a.c.get(f"/gardeners/{g}").text
assert "voided" in t.lower()
"""
T["c57"] = """
s = System(monkeypatch); a = s.setup_admin()
p = a.new_plot("A-1"); g = a.new_gardener("G"); a.assign(p, g, "2026-01-01"); a.open_season(2026)
a.money(g, "payment", "10.00", token="tok-123")
r = a.money(g, "payment", "10.00", token="tok-123")
assert len([l for l in a.ledger(g) if l["kind"] == "payment"]) == 1
"""
T["c58"] = """
s = System(monkeypatch, now=utc(2026, 3, 1)); a = s.setup_admin()
p = a.new_plot("A-1"); g = a.new_gardener("Gina"); a.assign(p, g, "2026-01-01"); a.open_season(2026)
sid = a.season_id(2026)
def st():
    t = a.c.get(f"/dues?season={sid}").text
    return t[t.find("Gina"):][:200]
s.clock.set(utc(2026, 3, 31, 20)); assert "Unpaid" in st() and "Overdue" not in st()
s.clock.set(utc(2026, 4, 1, 8)); assert "Overdue" in st()
s.clock.set(utc(2026, 10, 5)); assert "Overdue" in st()
"""
T["c59"] = """
s = System(monkeypatch); a = s.setup_admin()
a.set("payments.overpayment", "credit")
gs = []
for i, z in enumerate(["small", "standard", "large", "standard"]):
    p = a.new_plot(f"P-{i}", z); g = a.new_gardener(f"Name{i}"); a.assign(p, g, "2026-01-01"); gs.append(g)
a.open_season(2026); sid = a.season_id(2026)
a.money(gs[1], "payment", "20.00")
a.money(gs[0], "payment", "40.00"); a.money(gs[0], "payment", "5.00")
a.money(gs[2], "payment", "80.00"); a.money(gs[2], "refund", "10.00", reason="x")
pid = [l for l in a.ledger(gs[3]) if l["kind"] == "charge"]
a.money(gs[3], "payment", "30.00"); vid = [l for l in a.ledger(gs[3]) if l["kind"] == "payment"][0]["id"]
a.c.post(f"/ledger/{vid}/void", dict(reason="typo"), referer=f"/gardeners/{gs[3]}")
a.money(gs[3], "adjustment", "-10.00", reason="disc")
bal = s.q("SELECT sum(amount) b FROM ledger WHERE season_id=?", sid)[0]["b"]
t = a.c.get(f"/dues?season={sid}").text
row = t[t.find("Name1"):][:200]
assert "Partly paid" in row
csv = a.c.get(f"/export/dues.csv?season={sid}").body
assert "%d.%02d" % (bal // 100, bal % 100) in t
total = 0
import csv as _csv, io
rows = list(_csv.reader(io.StringIO(csv)))
bi = [h.lower() for h in rows[0]].index("balance")
for r_ in rows[1:]:
    if r_[bi]: total += round(float(r_[bi]) * 100)
assert total == bal
"""
T["c60"] = """
s = System(monkeypatch); a = s.setup_admin()
for _ in range(5): s.login("boss", "wrong password!")
cl, r = s.login("boss", PW)
assert r.status != 303 or "pk_session" not in cl.cookies
s.clock.advance(minutes=15, seconds=1)
cl, r = s.login("boss", PW)
assert r.status == 303 and "pk_session" in cl.cookies
"""
for cid, body in T.items():
    c = claims[cid]
    src = (c.get("quote") or "convention").replace("\n", " ")
    hdr = (f"# rule: {c['action']} ({c['situation']})\n# expect: {c['expect']}\n# source: {src}\n# claim: {cid}\n").replace("\n\n", "\n")
    code = hdr + "import re\nimport datetime as dt\nimport os\n" + HDR + f"def test_{cid}(monkeypatch):\n" + textwrap.indent(body.strip("\n"), "    ") + "\n"
    open(f"_helpers/scenarios/test_{cid}.py", "w").write(code)
print(len(T))
