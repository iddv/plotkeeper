"""Run the start command (Another process already uses the configured port).

Expected: It exits with a message naming the port and the configuration variable to change it
Source: "Port already in use: the start command exits with a message naming the port and the config variable to change it."
"""

import re
import datetime as dt
import os
from _helpers.driver import *


def test_run_start_command_another_process_already_uses_configured(monkeypatch):
    import socket, subprocess, sys, tempfile
    sk = socket.socket(); sk.bind(("127.0.0.1", 0)); sk.listen(1); port = sk.getsockname()[1]
    d = tempfile.mkdtemp()
    env = dict(os.environ, PLOTKEEPER_DATA_DIR=d, PLOTKEEPER_PORT=str(port))
    p = subprocess.run([sys.executable, "-m", "plotkeeper", "start"], cwd=REPO, env=env, capture_output=True, text=True, timeout=20)
    sk.close()
    assert p.returncode != 0
    out = p.stdout + p.stderr
    assert str(port) in out and "PLOTKEEPER_PORT" in out
