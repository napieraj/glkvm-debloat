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


import pytest

from kvmd.apps.kvmd.api.edid import EdidApi
from kvmd.apps.kvmd.api.edid import GSV1127X_UPGRADE_CMD
from kvmd.apps.kvmd.api.edid import GSV1127_UPGRADE_CMD
from kvmd.apps.kvmd.api.edid import LT6911C_UPGRADE_CMD
from kvmd.apps.kvmd.api.edid import _CMD_MAP


# =====
# The EDID handlers moved out of api/upgrade.py in lean-plan step 9. The two
# helpers below are the only real logic in them, and a move is exactly the kind
# of change that silently drops a branch, so they get pinned here.
#
# 128-byte EDIDs are 256 hex chars and get a fixed 128-byte block appended;
# 256-byte EDIDs are 512 chars and pass through. Anything else is rejected
# before it reaches a subprocess.


def _api() -> EdidApi:
    return EdidApi()


def _validate(api: EdidApi, value: str) -> bool:
    return api._EdidApi__validate_edid(value)  # type: ignore  # pylint: disable=protected-access


def _convert(api: EdidApi, value: str) -> bytes:
    return api._EdidApi__convert_edid_to_bytes(value)  # type: ignore  # pylint: disable=protected-access


# =====
@pytest.mark.parametrize("length", [256, 512])
def test_ok__validate_accepts_both_edid_lengths(length: int) -> None:
    assert _validate(_api(), "A" * length)


# 128 and 64 are here because they are the plausible wrong answers: a 128-CHAR
# string is a 64-byte blob, and it is the value someone reaches for when they
# confuse the byte count with the hex-char count. A validator widened to accept
# either would pass a short blob to bytes.fromhex and on to the i2c write.
@pytest.mark.parametrize("length", [0, 1, 64, 128, 255, 257, 511, 513, 1024])
def test_fail__validate_rejects_other_lengths(length: int) -> None:
    assert not _validate(_api(), "A" * length)


def test_ok__validate_ignores_whitespace() -> None:
    # The vendor UI pastes EDIDs with spaces and newlines in them.
    spaced = " ".join("AB" for _ in range(128))
    assert len(spaced) != 256
    assert _validate(_api(), spaced)


@pytest.mark.parametrize("bad", ["G" * 256, ("A" * 255) + "z!", ("A" * 255) + "-"])
def test_fail__validate_rejects_non_hex(bad: str) -> None:
    assert not _validate(_api(), bad)


def test_ok__convert_passes_through_a_256_byte_edid() -> None:
    out = _convert(_api(), "AB" * 256)
    assert len(out) == 256
    assert out == bytes.fromhex("AB" * 256)


def test_ok__convert_appends_128_bytes_to_a_128_byte_edid() -> None:
    out = _convert(_api(), "AB" * 128)
    assert len(out) == 256
    assert out[:128] == bytes.fromhex("AB" * 128)
    # The appended block is fixed, and its last byte is the checksum 0xC0.
    assert out[128] == 0x02
    assert out[-1] == 0xC0


def test_ok__the_command_map_covers_every_model_with_a_gsv_receiver() -> None:
    # Models absent from the map fall through to LT6911C. get_model_name()'s
    # fallback ("rm10") and the old upgrade.py fallback ("rm1") are both absent,
    # which is why the split did not change behaviour on an unreadable model file.
    assert _CMD_MAP == {
        "rm10rc": GSV1127X_UPGRADE_CMD,
        "rm4pe": GSV1127X_UPGRADE_CMD,
        "rmq1": GSV1127_UPGRADE_CMD,
    }
    for absent in ("rm1", "rm10", "", "rm4pe "):
        assert _CMD_MAP.get(absent, LT6911C_UPGRADE_CMD) == LT6911C_UPGRADE_CMD
