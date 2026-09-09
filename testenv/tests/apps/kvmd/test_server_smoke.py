# ========================================================================== #
#                                                                            #
#    KVMD - The main PiKVM daemon.                                           #
#                                                                            #
#    Copyright (C) 2018-2024  Maxim Devaev <mdevaev@gmail.com>               #
#                                                                            #
#    This program is free software: you can redistribute it and/or modify    #
#    it under the terms of the GNU General Public License as published by    #
#    the Free Software Foundation, either version 3 of the License, or       #
#    (at your option) any later version.                                     #
#                                                                            #
#    This program is distributed in the hope that it will be useful,         #
#    but WITHOUT ANY WARRANTY; without even the implied warranty of          #
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the           #
#    GNU General Public License for more details.                            #
#                                                                            #
#    You should have received a copy of the GNU General Public License       #
#    along with this program.  If not, see <https://www.gnu.org/licenses/>.  #
#                                                                            #
# ========================================================================== #


import os

from unittest.mock import MagicMock

from kvmd.apps.kvmd.server import KvmdServer


# =====
# Construction smoke check for KvmdServer.
#
# The route-inventory guard (testenv/tests/test_routes.py) is a static AST walk,
# so it catches a route that disappeared but CANNOT catch the other failure mode
# the kvmd-lean strip can produce: server.py still referring to something the
# strip removed. Those references live inside __init__ -- the __apis list and the
# _Subsystem.make calls -- so they fail at CONSTRUCTION, not at import, and
# nothing else in this suite ever constructs a KvmdServer.
#
# Removing an api attribute while leaving its __apis entry or its
# _Subsystem.make line raises AttributeError here; leaving a _Subsystem.make
# whose event_type is set but whose api has no trigger/poll state raises
# AssertionError from _Subsystem.__post_init__ (server.py:141-144). Both are
# hard startup failures on a real device -- a dead daemon, not a missing route.
#
# Every collaborator is a MagicMock, deliberately: the point is not to exercise
# the subsystems, it is to prove that server.py can still assemble itself.
_KEYMAP = os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "contrib", "keymaps", "en-us")


def _make_server(**overrides: object) -> KvmdServer:
    kwargs: dict = {
        "auth_manager": MagicMock(),
        "init_manager": MagicMock(),
        "info_manager": MagicMock(),
        "log_reader": None,
        "user_gpio": MagicMock(),
        "ocr": MagicMock(),
        "switch": None,          # None on an RM1PE; Switch is rm4pe-only
        "hid": MagicMock(),
        "atx": MagicMock(),
        "msd": MagicMock(),
        "rndis": MagicMock(),
        "upgrade": MagicMock(),
        "streamer": MagicMock(),
        "snapshoter": MagicMock(),
        "keymap_path": os.path.abspath(_KEYMAP),
        "stream_forever": False,
    }
    kwargs.update(overrides)
    return KvmdServer(**kwargs)  # type: ignore


def test_ok__server_constructs() -> None:
    # Fails with AttributeError if server.py references an api object the strip
    # removed, and with AssertionError if a _Subsystem.make lost its state
    # provider. Either way the daemon would not start.
    server = _make_server()
    assert isinstance(server, KvmdServer)


def test_ok__server_builds_its_api_and_subsystem_lists() -> None:
    # The two lists the strip edits are both built in __init__ (the routes
    # themselves are only registered later, in the async _init_app). Assert them
    # directly: a dangling entry cannot survive here, and neither can a list
    # that has been emptied by an over-broad deletion.
    server = _make_server()
    apis = server._KvmdServer__apis            # pylint: disable=protected-access
    subsystems = server._KvmdServer__subsystems  # pylint: disable=protected-access
    assert len(apis) > 10
    assert all(api is not None for api in apis)
    assert len(subsystems) > 5
    assert all(sub is not None for sub in subsystems)
