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


import pytest

from kvmd.keyboard.mappings import KEYMAP
from kvmd.keyboard.mappings import WEB_TO_EVDEV


# =====
# The fork re-keyed KEYMAP by evdev code (dict[int, Key], mappings.py:46);
# upstream keyed it by the web name directly. WEB_TO_EVDEV (mappings.py:165)
# is now the name-to-code hop, and is what valid_hid_key validates against.
def test_ok__keymap() -> None:
    assert KEYMAP[WEB_TO_EVDEV["KeyA"]].mcu.code == 1


def test_fail__keymap() -> None:
    with pytest.raises(KeyError):
        print(WEB_TO_EVDEV["keya"])
