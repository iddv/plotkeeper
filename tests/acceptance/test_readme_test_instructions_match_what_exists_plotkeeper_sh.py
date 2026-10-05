"""README test instructions match what exists: `./plotkeeper.sh test` runs the suite and it passes.

Expected: command exits 0 and the tests/ suite it runs exists
Source: "README "## Tests: ./plotkeeper.sh test""
"""

import os
import subprocess
from _helpers.driver import REPO


def test_readme_test_instructions_match_what_exists_plotkeeper_sh():
    assert os.path.exists(os.path.join(REPO, "tests", "test_plotkeeper.py"))
    p = subprocess.run([os.path.join(REPO, "plotkeeper.sh"), "test"], cwd=REPO, capture_output=True, text=True, timeout=120)
    assert p.returncode == 0, p.stdout[-500:] + p.stderr[-500:]
    assert "OK" in p.stdout + p.stderr
