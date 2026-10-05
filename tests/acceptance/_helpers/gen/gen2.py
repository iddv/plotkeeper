import textwrap
F = {}
F["F1"] = """
import subprocess, sys, tempfile, socket, time, urllib.request, http.cookiejar, urllib.parse
import shutil
work = tempfile.mkdtemp()
shutil.copytree(os.path.join(REPO, "plotkeeper"), os.path.join(work, "plotkeeper")); shutil.copy(os.path.join(REPO, "plotkeeper.sh"), work)
env = dict(os.environ); [env.pop(k, None) for k in list(env) if k.startswith("PLOTKEEPER_")]
sk = socket.socket(); free = sk.connect_ex(("127.0.0.1", 8080)) != 0; sk.close()
port = 8080
if not free:
    sk = socket.socket(); sk.bind(("127.0.0.1", 0)); port = sk.getsockname()[1]; sk.close(); env["PLOTKEEPER_PORT"] = str(port)
pr = subprocess.Popen([os.path.join(work, "plotkeeper.sh")], cwd=work, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
try:
    out = ""
    t0 = time.time()
    while "setup code" not in out and time.time() - t0 < 15:
        out += pr.stdout.readline()
    assert f"http://127.0.0.1:{port}/" in out
    code = re.search(r"setup code: (\\S+)", out).group(1)
    B = f"http://127.0.0.1:{port}"
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    h = op.open(B + "/").read().decode()
    assert "Setup code" in h
    csrf = re.search(r'name="_csrf" value="([^"]+)"', h).group(1)
    d = dict(_csrf=csrf, code="BAD-CODE", garden_name="G", currency="EUR", timezone="UTC", username="boss", password=PW, password2=PW)
    assert "Invalid setup code" in op.open(B + "/setup", urllib.parse.urlencode(d).encode()).read().decode()
    d["code"] = code
    t = text(op.open(B + "/setup", urllib.parse.urlencode(d).encode()).read().decode())
    assert "No plots yet" in t and "Nobody is waiting" in t and "No season yet" in t
    p = subprocess.run([sys.executable, "-m", "plotkeeper", "demo"], cwd=work, env=env, capture_output=True, text=True, timeout=60)
    assert p.returncode != 0 and "Demo data can only be loaded into an empty install" in p.stdout + p.stderr
finally:
    pr.terminate(); pr.wait(5)
w2 = tempfile.mkdtemp()
p = subprocess.run([sys.executable, "-m", "plotkeeper", "demo"], cwd=work, env=dict(env, PLOTKEEPER_DATA_DIR=os.path.join(w2, "data")), capture_output=True, text=True, timeout=60)
assert p.returncode == 0 and "admin" in p.stdout and "coordinator" in p.stdout
import sqlite3
c = sqlite3.connect(os.path.join(w2, "data", os.path.basename(store.db_path(w2))))
assert c.execute("select count(*) from plots").fetchone()[0] == 40
assert c.execute("select count(*) from gardeners").fetchone()[0] == 45
"""
F["F2"] = """
s = System(monkeypatch); a = s.setup_admin()
assert a.add_plot("B-07", "small", "12.5", "near tap").status == 303
p = a.plot_id("B-07")
assert "Plot code B-07 already exists" in a.add_plot("B-07").text
assert "B-07" in a.c.get("/plots?q=B-07").text
assert a.edit_plot(p, size="large", notes="moved").status == 303 and a.plot(p)["size"] == "large"
a.plot_status(p, "out_of_service", "flooded"); assert a.plot(p)["status"] == "out_of_service"
a.plot_status(p, "return"); assert a.plot(p)["status"] == "available"
q = a.new_plot("C-01"); a.assign(q, a.new_gardener("Holder"), "2026-05-01")
assert "Release the holder or withdraw the offer first" in a.plot_status(q, "retire", "x").msg
a.plot_status(p, "retire", "path"); assert a.plot(p)["status"] == "retired"
assert "B-07" not in a.c.get("/plots").text
h = a.c.get(f"/plots/{p}").text; h = h[h.find("History"):]
for w in ("added", "Edited", "Available → Out of service", "Out of service → Available", "→ Retired"):
    assert w in h, w
"""
F["F3"] = """
s = System(monkeypatch); a = s.setup_admin()
g1 = a.new_gardener("Ann Smith", "ann@example.org")
r = a.add_gardener("Ann S", "ann@example.org"); assert r.status != 303 and f'/gardeners/{g1}"' in r.body
assert "Ann Smith" in a.c.get("/gardeners?q=ann@example").text
g2 = a.new_gardener("Bob"); g3 = a.new_gardener("Cat"); g4 = a.new_gardener("Dan")
a.wait(g1); a.wait(g2, "small", "2024-01-15"); a.wait(g3, "large"); a.wait(g4)
assert a.waitlist_names() == ["Bob", "Ann Smith", "Cat", "Dan"]
e = a.entry(g1); a.c.post(f"/waitlist/{e['id']}/remove", dict(reason="unreachable", note=""), referer="/waitlist")
assert a.waitlist_names() == ["Bob", "Cat", "Dan"]
a.open_season(2026); a.money(g1, "adjustment", "10.00", season_id=a.season_id(2026), reason="key deposit")
a.c.post(f"/gardeners/{g1}/archive", dict(archived="1"), referer=f"/gardeners/{g1}")
assert s.q("SELECT archived FROM gardeners WHERE id=?", g1)[0]["archived"] == 0
"""
F["F4"] = """
s = System(monkeypatch); a = s.setup_admin()
a.open_season(2026)
p = a.new_plot("S-1", "small"); h = a.new_gardener("Holder"); a.assign(p, h, "2026-01-01")
a.waiter("Large", "large"); g = a.waiter("Small", "small"); g2 = a.waiter("Any", "any")
assert a.release(p, "2026-05-10", "moved").status == 303 and a.plot(p)["status"] == "available"
t = a.offer_preview(p).text
assert "Small" in t and "small@x.org" in t
import re
r1 = a.offer_preview(p)
v = re.search(r'name="version" value="(\\d+)"', r1.body).group(1); eid = re.search(r'name="entry_id" value="(\\d+)"', r1.body).group(1)
assert a.c.post(f"/plots/{p}/offer", dict(version=v, entry_id=eid), referer=f"/plots/{p}").status == 303
y = a.c.post(f"/plots/{p}/offer", dict(version=v, entry_id=eid), referer=f"/plots/{p}")
assert s.q("SELECT count(*) n FROM offers")[0]["n"] == 1
a.outcome(p, "declined"); assert a.plot(p)["status"] == "available" and a.waitlist_names()[1] == "Small"
a.offer(p); a.outcome(p, "accepted", "2026-05-11")
assert a.plot(p)["status"] == "occupied"
assert [l["amount"] for l in a.ledger(g) if l["kind"] == "charge"] == [4000]
"""
F["F5"] = """
s = System(monkeypatch, now=utc(2026, 1, 5)); a = s.setup_admin()
for i, z in enumerate(["small", "standard", "large"]):
    a.assign(a.new_plot(f"P{i}", z), a.new_gardener(f"G{i}"), "2026-01-01")
t = a.c.get("/seasons/new").body
assert "40.00" in t and "60.00" in t and "80.00" in t
r = a.c.post("/seasons/new", dict(year="2026", due_date="2026-03-31", fee_small="40.00", fee_standard="60.00", fee_large="80.00"), referer="/seasons/new")
assert "3" in r.text
assert a.open_season(2026).status == 303
assert sorted(x["amount"] for x in s.q("SELECT amount FROM ledger WHERE kind='charge'")) == [4000, 6000, 8000]
assert "already exists" in a.open_season(2026).text
assert s.q("SELECT count(*) n FROM ledger WHERE kind='charge'")[0]["n"] == 3
s.clock.set(utc(2026, 7, 1))
g = a.waiter("Mid"); p = a.new_plot("M", "standard"); a.offer(p); a.outcome(p, "accepted", "2026-07-01")
assert [l["amount"] for l in a.ledger(g) if l["kind"] == "charge"] == [6000]
a.set("fees.new_holder_charge", "prorated")
g = a.waiter("Mid2"); p = a.new_plot("M2", "standard"); a.offer(p); a.outcome(p, "accepted", "2026-07-01")
assert [l["amount"] for l in a.ledger(g) if l["kind"] == "charge"] == [3000]
"""
F["F6"] = """
s = System(monkeypatch); a = s.setup_admin()
p = a.new_plot("A", "standard"); g = a.new_gardener("Payer"); a.assign(p, g, "2026-01-01"); a.open_season(2026, due="2026-12-31")
assert "Balance is 60.00; amount exceeds it" in a.money(g, "payment", "70.00").text
assert a.money(g, "payment", "60.00", method="bank_transfer", token="T1").status == 303
a.money(g, "payment", "60.00", method="bank_transfer", token="T1")
assert len([l for l in a.ledger(g) if l["kind"] == "payment"]) == 1
pid = [l for l in a.ledger(g) if l["kind"] == "payment"][0]["id"]
a.c.post(f"/ledger/{pid}/void", dict(reason="wrong person"), referer=f"/gardeners/{g}")
a.money(g, "payment", "50.00")
assert "Refund cannot exceed 50.00 paid" in a.money(g, "refund", "50.01", reason="x").text
a.money(g, "refund", "5.00", reason="returned")
a.money(g, "adjustment", "-10.00", reason="discount")
kinds = [l["kind"] for l in a.ledger(g)]
assert kinds == ["charge", "payment", "void", "payment", "refund", "adjustment"]
assert sum(l["amount"] for l in a.ledger(g)) == 500
t = a.c.get(f"/gardeners/{g}").text
assert "5.00" in t and "voided" in t.lower()
"""
F["F7"] = """
import csv, io
s = System(monkeypatch); a = s.setup_admin()
a.set("payments.overpayment", "credit")
gs = []
for i, z in enumerate(["small", "standard", "large", "small"]):
    p = a.new_plot(f"P{i}", z); g = a.new_gardener(f"Name{i}"); a.assign(p, g, "2026-01-01"); gs.append(g)
a.waiter("Waiting One")
a.open_season(2026, due="2026-12-31"); sid = a.season_id(2026)
a.money(gs[0], "payment", "40.00"); a.money(gs[1], "payment", "20.00"); a.money(gs[2], "payment", "90.00", method="card")
t = a.c.get(f"/dues?season={sid}").text
for n, st in (("Name0", "Paid"), ("Name1", "Partly paid"), ("Name2", "In credit"), ("Name3", "Unpaid")):
    assert st in t[t.find(n):][:150], n
bal = s.q("SELECT sum(amount) b FROM ledger")[0]["b"]
d = list(csv.reader(io.StringIO(a.c.get(f"/export/dues.csv?season={sid}").body)))
bi = [h.lower() for h in d[0]].index("balance")
assert sum(round(float(r[bi]) * 100) for r in d[1:] if r[bi]) == bal
pay = a.c.get("/export/payments.csv?from=2026-05-01&to=2026-05-31").body
assert "150.00" in pay
pl = a.c.get("/export/plots.csv").body.strip().splitlines(); assert len(pl) == 5
wl = a.c.get("/export/waitlist.csv").body.strip().splitlines(); assert len(wl) == 2 and "Waiting One" in wl[1]
"""
F["F8"] = """
s = System(monkeypatch); a = s.setup_admin()
r = a.c.follow(a.c.post("/users", dict(username="coord", role="coordinator")))
pw = re.search(r"Temporary password for coord : (\\S+)", r.text).group(1)
cl, r = s.login("coord", pw)
assert r.location == "/account/password"
assert cl.get("/plots").location == "/account/password"
r = cl.post("/account/password", dict(current=pw, new="new password 123", new2="new password 123"))
assert s.q("SELECT must_change FROM users WHERE username='coord'")[0]["must_change"] == 0, r.text[-300:]
assert cl.get("/settings").status == 403
assert cl.post("/settings", dict(garden_name="Hacked")).status == 403
p = a.new_plot("A"); g = a.new_gardener("G"); a.assign(p, g, "2026-01-01"); a.open_season(2026)
r = cl.post(f"/gardeners/{g}/money", dict(kind="adjustment", amount="-60.00", season_id=a.season_id(2026), date="2026-05-10", reason="x", token="zz"))
assert [l["kind"] for l in a.ledger(g)] == ["charge"]
uid = s.q("SELECT id FROM users WHERE username='boss'")[0]["id"]
a.c.post(f"/users/{uid}/active", dict(active="0"), referer="/users")
assert s.q("SELECT active FROM users WHERE id=?", uid)[0]["active"] == 1
a.set("offers.expiry_days", "21")
assert "offers.expiry_days" in a.c.get("/audit").text
"""
for fid, body in F.items():
    code = f"# flow: {fid}\n# claim: flow\nimport re\nimport os\nfrom _helpers.driver import *\n\n\ndef test_flow_{fid}(monkeypatch):\n" + textwrap.indent(body.strip("\n"), "    ") + "\n"
    open(f"_helpers/scenarios/test_flow_{fid}.py", "w").write(code)
