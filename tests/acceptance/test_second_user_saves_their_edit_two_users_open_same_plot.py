"""The second user saves their edit (Two users open the same plot for editing; the first saves a change).

Expected: Refused with "This plot changed since you opened it"; the first user's change is kept and the second changes nothing
Source: "Record edited by someone else since it was opened: "This plot changed since you opened it", and the user reloads."
"""

import re
import datetime as dt
import os
from _helpers.driver import *


def test_second_user_saves_their_edit_two_users_open_same_plot(monkeypatch):
    s = System(monkeypatch); a = s.setup_admin()
    p = a.new_plot("E-1"); v = a.plot(p)["version"]
    assert a.edit_plot(p, version=v, notes="first").status == 303
    r = a.edit_plot(p, version=v, notes="second")
    assert "This plot changed since you opened it" in r.text + r.msg
    assert a.plot(p)["notes"] == "first"
