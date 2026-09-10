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
# ========================================================================== #


import typing

from kvmd.apps.kvmd.switch.sysfs_device import Device


# =====
# The rm4pe sysfs switch driver's context-manager annotation named a class that
# does not exist -- the class is Device, the annotation said "SysfsDevice". It
# was the last F821 in the tree.
#
# What it did NOT do is raise. A string annotation is stored, not evaluated, so
# `with device:` worked and no error path was reachable through it. The failure
# needs something that RESOLVES hints -- typing.get_type_hints, or a framework
# that calls it -- and nothing in this tree does today. That is the whole
# distance between "cosmetic" and "load-bearing", and it is why this asserts on
# resolution rather than on the string.
#
# It matters because the port interlock that depends on this driver may later
# introspect. If it does, an unresolvable hint becomes a real NameError in the
# path that constructs the device.


def test_ok__the_context_manager_hint_resolves() -> None:
    hints = typing.get_type_hints(Device.__enter__)
    assert hints["return"] is Device


def test_ok__the_context_manager_returns_self_without_resolving_hints() -> None:
    # The behaviour that held even while the hint was wrong. Pinned so the
    # correction above is not mistaken for a behaviour change.
    class _Stub(Device):  # pylint: disable=too-few-public-methods
        def __init__(self) -> None:
            pass

    stub = _Stub()
    with stub as got:
        assert got is stub
