"""Flow F1: Install and first run.

Flow: F1 in SCOPE.md.
"""

import re
import os
from _helpers.driver import *


def test_flow_f1_install_first_run(monkeypatch):
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
        code = re.search(r"setup code: (\S+)", out).group(1)
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
