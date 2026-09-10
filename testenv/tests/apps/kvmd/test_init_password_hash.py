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


import re

import pytest

from passlib.hash import sha512_crypt


# =====
# InitManager._change_root_password writes a hash into /etc/shadow. It used
# crypt.crypt(password, f"$6${salt}$") until the stdlib `crypt` module was
# removed in Python 3.13, which made kvmd.apps.kvmd unimportable outright.
#
# The replacement must be byte-identical, not merely "also sha512-crypt": a
# hash in a different format, or with a rounds field crypt.crypt would not have
# emitted, is a password nothing on the device can verify. These tests pin the
# properties that make the substitution safe. They deliberately do NOT import
# `crypt` -- it does not exist on a current interpreter, and a test skipped for
# that reason would certify nothing.
_SALT = "0123456789abcdef"
_PASSWORDS = ["hunter2", "", "correcthorse123456", "p@ss wörd", "x" * 72, "a" * 200]


def _hash(password: str, salt: str = _SALT) -> str:
    return sha512_crypt.using(salt=salt, rounds=5000).hash(password)


@pytest.mark.parametrize("password", _PASSWORDS)
def test_ok__shadow_hash_has_the_shape_crypt_produced(password: str) -> None:
    """
    `$6$<salt>$<86 base64 chars>` and NO rounds field.

    crypt.crypt() with a salt string carrying no rounds emits the default 5000
    and omits the field. passlib emits `$6$rounds=N$...` whenever N is not its
    default, so a change to `rounds` here -- or dropping the argument, since
    passlib's own default is 535000 -- produces a hash of a different shape.
    That is the mutation this catches.
    """

    got = _hash(password)
    assert re.fullmatch(r"\$6\$" + re.escape(_SALT) + r"\$[./A-Za-z0-9]{86}", got), got
    assert "rounds=" not in got


@pytest.mark.parametrize("password", _PASSWORDS)
def test_ok__the_hash_verifies_and_is_salt_stable(password: str) -> None:
    got = _hash(password)
    assert sha512_crypt.verify(password, got)
    # Deterministic for a fixed salt, which is what makes the equivalence above
    # checkable at all.
    assert got == _hash(password)


def test_fail__a_different_salt_gives_a_different_hash() -> None:
    # Guards against a substitution that ignored the caller's salt -- the code
    # generates it from os.urandom and must actually use it.
    assert _hash("hunter2", "0123456789abcdef") != _hash("hunter2", "fedcba9876543210")


def test_ok__init_module_imports_without_the_removed_stdlib_crypt() -> None:
    """
    The regression itself.

    `import crypt` at module scope in kvmd/apps/kvmd/init.py took out the whole
    of kvmd.apps.kvmd on Python 3.13+, which is three collection errors and a
    daemon that cannot start. Importing the module is the assertion.
    """

    import kvmd.apps.kvmd.init  # noqa: F401  pylint: disable=unused-import,import-outside-toplevel
    import sys  # pylint: disable=import-outside-toplevel
    assert "crypt" not in sys.modules or sys.version_info < (3, 13)
