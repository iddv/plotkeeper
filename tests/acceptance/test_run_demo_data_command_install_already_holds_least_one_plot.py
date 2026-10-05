"""Run the demo data command (An install that already holds at least one plot or gardener).

Expected: Refused with "Demo data can only be loaded into an empty install"; existing data is unchanged
Source: "Demo command run on a non-empty install: refused with "Demo data can only be loaded into an empty install"."
"""

import re
import datetime as dt
import os
from _helpers.driver import *


def test_run_demo_data_command_install_already_holds_least_one_plot(monkeypatch):
    import subprocess, sys
    s = System(monkeypatch)
    a = s.setup_admin()
    a.new_plot("A-1")
    env = dict(os.environ, PLOTKEEPER_DATA_DIR=s.dir)
    p = subprocess.run([sys.executable, "-m", "plotkeeper", "demo"], cwd=REPO, env=env, capture_output=True, text=True, timeout=60)
    assert p.returncode != 0
    assert "Demo data can only be loaded into an empty install" in p.stdout + p.stderr
    assert s.q("SELECT count(*) n FROM plots")[0]["n"] == 1
