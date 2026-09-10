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

from kvmd.plugins.atx import AtxIsBusyError
from kvmd.plugins.atx.glatx import Plugin


# =====
# Regression guard for the ATX wait=true path. AioExclusiveRegion is a
# SYNCHRONOUS context manager (aiotools.py:317-344), but __run_cmd used
# `async with` on it, so every power_on/power_off/reset with wait=true raised
# TypeError before touching the hardware. gpio.py:194 has always used the
# correct form; glatx.py was the only site in the tree that did not.
def _make_plugin(calls: list) -> Plugin:
    plugin = Plugin()

    async def fake_inner(action: str) -> None:
        calls.append(action)

    # Name-mangled private method on the plugin class.
    plugin._Plugin__inner_run_cmd = fake_inner  # type: ignore  # pylint: disable=protected-access
    return plugin


@pytest.mark.asyncio
async def test_ok__wait_enters_the_region() -> None:
    calls: list = []
    plugin = _make_plugin(calls)

    await plugin.power_on(wait=True)

    assert calls == ["power_on"]
    assert not plugin._Plugin__region.is_busy()  # pylint: disable=protected-access


@pytest.mark.asyncio
async def test_ok__no_wait_uses_the_region_task() -> None:
    calls: list = []
    plugin = _make_plugin(calls)

    await plugin.power_off(wait=False)

    assert calls == ["power_off"]


@pytest.mark.asyncio
async def test_fail__wait_is_exclusive() -> None:
    calls: list = []
    plugin = _make_plugin(calls)
    region = plugin._Plugin__region  # pylint: disable=protected-access

    region.enter()
    try:
        with pytest.raises(AtxIsBusyError):
            await plugin.power_reset_hard(wait=True)
    finally:
        region.exit()

    assert calls == []
