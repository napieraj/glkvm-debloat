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
import contextlib

from typing import AsyncGenerator

import passlib.apache

import pytest

from kvmd.yamlconf import make_config

from kvmd.apps.kvmd.auth import AuthManager

from kvmd.plugins.auth import get_auth_service_class

from kvmd.htserver import HttpExposed


# =====
# allow_usc and allowed_exe_paths carry the defaults exposed_http() applies when
# a handler does not specify them. These fixtures exercise auth_required routing
# only, so the added fields must not change what is under test.
_E_AUTH = HttpExposed("GET", "/foo_auth", True, True, (), (lambda: None))
_E_UNAUTH = HttpExposed("GET", "/bar_unauth", True, True, (), (lambda: None))
_E_FREE = HttpExposed("GET", "/baz_free", False, True, (), (lambda: None))

# The shipped default from kvmd/apps/__init__.py (auth.expire): 12 hours.
_EXPIRE = 43200


async def _login(manager: AuthManager, user: str, passwd: str) -> (str | None):
    """
    login() returns (token, failed_since_last_success).

    These tests assert on the token, which is what they have always asserted
    on. The counter is orthogonal state they never covered -- it is an advisory
    signal returned to the client and logged, separate from the per-IP rate
    limiting that actually gates access -- so inventing assertions about it here
    would be adding scope rather than migrating.
    """

    (token, _) = await manager.login(user, passwd, expire=_EXPIRE)
    return token


def _make_service_kwargs(path: str) -> dict:
    cls = get_auth_service_class("htpasswd")
    scheme = cls.get_plugin_options()
    return make_config({"file": path}, scheme)._unpack()


@contextlib.contextmanager
def _advance(manager: AuthManager, seconds: int):  # type: ignore
    """
    Advances the manager's clock. __get_now_ts() reads time.monotonic(), so
    expiry is testable without sleeping; the name mangling is the price of
    reaching a private method, and is preferable to a real delay in a suite
    that otherwise runs in a third of a second.
    """

    attr = "_AuthManager__get_now_ts"
    original = getattr(manager, attr)
    base = original()
    setattr(manager, attr, (lambda: base + seconds))
    try:
        yield
    finally:
        setattr(manager, attr, original)


@contextlib.asynccontextmanager
async def _get_configured_manager(
    unauth_paths: list[str],
    internal_path: str,
    external_path: str="",
    force_internal_users: (list[str] | None)=None,
    expire: int=_EXPIRE,
) -> AsyncGenerator[AuthManager, None]:

    manager = AuthManager(
        enabled=True,
        expire=expire,
        usc_users=[],
        usc_groups=[],
        unauth_paths=unauth_paths,

        int_type="htpasswd",
        int_kwargs=_make_service_kwargs(internal_path),
        force_int_users=(force_internal_users or []),

        ext_type=("htpasswd" if external_path else ""),
        ext_kwargs=(_make_service_kwargs(external_path) if external_path else {}),

        totp_secret_path="",
    )

    try:
        yield manager
    finally:
        await manager.cleanup()


# =====
@pytest.mark.asyncio
async def test_ok__internal(tmpdir) -> None:  # type: ignore
    path = os.path.abspath(str(tmpdir.join("htpasswd")))

    htpasswd = passlib.apache.HtpasswdFile(path, new=True)
    htpasswd.set_password("admin", "pass")
    htpasswd.save()

    async with _get_configured_manager([], path) as manager:
        assert manager.is_auth_enabled()
        assert manager.is_auth_required(_E_AUTH)
        assert manager.is_auth_required(_E_UNAUTH)
        assert not manager.is_auth_required(_E_FREE)

        assert manager.check("xxx") is None
        manager.logout("xxx")

        assert (await _login(manager, "user", "foo")) is None
        assert (await _login(manager, "admin", "foo")) is None
        assert (await _login(manager, "user", "pass")) is None

        token1 = await _login(manager, "admin", "pass")
        assert isinstance(token1, str)
        assert len(token1) == 64

        token2 = await _login(manager, "admin", "pass")
        assert isinstance(token2, str)
        assert len(token2) == 64
        assert token1 != token2

        assert manager.check(token1) == "admin"
        assert manager.check(token2) == "admin"
        assert manager.check("foobar") is None

        manager.logout(token1)

        # This fork deliberately narrowed logout from "revoke every session this
        # user holds" to "revoke this one session"; the revoke-all loop is
        # commented out in AuthManager.logout with a note calling it stupid.
        # Asserted positively rather than deleted, so the narrower contract is
        # something a future change has to break on purpose.
        #
        # Note the security trade-off this encodes: a stolen token now survives
        # the victim logging out. Revoking all sessions is the behaviour that
        # lets a user end an attacker's session by logging out.
        assert manager.check(token1) is None
        assert manager.check(token2) == "admin"
        assert manager.check("foobar") is None

        manager.logout(token2)
        assert manager.check(token2) is None

        token3 = await _login(manager, "admin", "pass")
        assert isinstance(token3, str)
        assert len(token3) == 64
        assert token1 != token3
        assert token2 != token3


@pytest.mark.asyncio
async def test_ok__external(tmpdir) -> None:  # type: ignore
    path1 = os.path.abspath(str(tmpdir.join("htpasswd1")))
    path2 = os.path.abspath(str(tmpdir.join("htpasswd2")))

    htpasswd1 = passlib.apache.HtpasswdFile(path1, new=True)
    htpasswd1.set_password("admin", "pass1")
    htpasswd1.set_password("local", "foobar")
    htpasswd1.save()

    htpasswd2 = passlib.apache.HtpasswdFile(path2, new=True)
    htpasswd2.set_password("admin", "pass2")
    htpasswd2.set_password("user", "foobar")
    htpasswd2.save()

    async with _get_configured_manager([], path1, path2, ["admin"]) as manager:
        assert manager.is_auth_enabled()
        assert manager.is_auth_required(_E_AUTH)
        assert manager.is_auth_required(_E_UNAUTH)
        assert not manager.is_auth_required(_E_FREE)

        assert (await _login(manager, "local", "foobar")) is None
        assert (await _login(manager, "admin", "pass2")) is None

        token = await _login(manager, "admin", "pass1")
        assert token is not None

        assert manager.check(token) == "admin"
        manager.logout(token)
        assert manager.check(token) is None

        token = await _login(manager, "user", "foobar")
        assert token is not None

        assert manager.check(token) == "user"
        manager.logout(token)
        assert manager.check(token) is None


@pytest.mark.asyncio
async def test_ok__unauth(tmpdir) -> None:  # type: ignore
    path = os.path.abspath(str(tmpdir.join("htpasswd")))

    htpasswd = passlib.apache.HtpasswdFile(path, new=True)
    htpasswd.set_password("admin", "pass")
    htpasswd.save()

    async with _get_configured_manager([
        "", " ",
        "foo_auth", "/foo_auth ", " /foo_auth",
        "/foo_authx", "/foo_auth/", "/foo_auth/x",
        "/bar_unauth",  # Only this one is matching
    ], path) as manager:

        assert manager.is_auth_enabled()
        assert manager.is_auth_required(_E_AUTH)
        assert not manager.is_auth_required(_E_UNAUTH)
        assert not manager.is_auth_required(_E_FREE)


@pytest.mark.asyncio
async def test_ok__disabled() -> None:
    try:
        manager = AuthManager(
            enabled=False,
            expire=_EXPIRE,
            usc_users=[],
            usc_groups=[],
            unauth_paths=[],

            int_type="foobar",
            int_kwargs={},
            force_int_users=[],

            ext_type="",
            ext_kwargs={},

            totp_secret_path="",
        )

        assert not manager.is_auth_enabled()
        assert not manager.is_auth_required(_E_AUTH)
        assert not manager.is_auth_required(_E_UNAUTH)
        assert not manager.is_auth_required(_E_FREE)

        with pytest.raises(AssertionError):
            await manager.authorize("admin", "admin")

        with pytest.raises(AssertionError):
            await _login(manager, "admin", "admin")

        with pytest.raises(AssertionError):
            manager.logout("xxx")

        with pytest.raises(AssertionError):
            manager.check("xxx")
    finally:
        await manager.cleanup()


# =====
@pytest.mark.asyncio
async def test_ok__session_expires(tmpdir) -> None:  # type: ignore
    """
    Sessions actually expire.

    This was not covered by any of the four migrated tests: disabling the
    expiry comparison in AuthManager.check left every one of them green, so
    a token that outlived its expiry would have shipped unnoticed. Time is
    driven rather than slept on -- __get_now_ts reads time.monotonic(), so the
    test advances it instead of waiting.
    """

    path = os.path.abspath(str(tmpdir.join("htpasswd")))
    htpasswd = passlib.apache.HtpasswdFile(path, new=True)
    htpasswd.set_password("admin", "pass")
    htpasswd.save()

    async with _get_configured_manager([], path, expire=100) as manager:
        (token, _) = await manager.login("admin", "pass", expire=100)
        assert token is not None
        assert manager.check(token) == "admin"

        # Just inside the window.
        with _advance(manager, 99):
            assert manager.check(token) == "admin"

        # Past it.
        with _advance(manager, 101):
            assert manager.check(token) is None


@pytest.mark.asyncio
async def test_ok__zero_expire_never_expires(tmpdir) -> None:  # type: ignore
    """
    expire=0 is the documented infinite session, and must not be confused with
    "already expired" -- the check is `expire_ts <= 0`, so an off-by-one there
    would turn every unlimited session into an instantly-dead one.
    """

    path = os.path.abspath(str(tmpdir.join("htpasswd")))
    htpasswd = passlib.apache.HtpasswdFile(path, new=True)
    htpasswd.set_password("admin", "pass")
    htpasswd.save()

    async with _get_configured_manager([], path, expire=0) as manager:
        (token, _) = await manager.login("admin", "pass", expire=0)
        assert token is not None
        assert manager.check(token) == "admin"
        with _advance(manager, 10 ** 6):
            assert manager.check(token) == "admin"
