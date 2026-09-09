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
import socket

from typing import AsyncGenerator
from typing import Any

import passlib.apache

import pytest

from kvmd.yamlconf import make_config

from kvmd.apps.kvmd.auth import AuthManager

from kvmd.crypto import KvmdHtpasswdFile

from kvmd.plugins.auth import get_auth_service_class

from kvmd.htserver import HttpExposed


# =====
_E_AUTH = HttpExposed("GET", "/foo_auth", True, True, (), (lambda: None))
_E_UNAUTH = HttpExposed("GET", "/bar_unauth", True, True, (), (lambda: None))
_E_FREE = HttpExposed("GET", "/baz_free", False, True, (), (lambda: None))


def _make_service_kwargs(path: str) -> dict:
    cls = get_auth_service_class("htpasswd")
    scheme = cls.get_plugin_options()
    return make_config({"file": path}, scheme)._unpack()


@contextlib.asynccontextmanager
async def _get_configured_manager(
    unauth_paths: list[str],
    internal_path: str,
    external_path: str="",
    force_internal_users: (list[str] | None)=None,
) -> AsyncGenerator[AuthManager, None]:

    manager = AuthManager(
        enabled=True,
        expire=0,
        usc_users=[],
        usc_groups=[],
        unauth_paths=unauth_paths,

        int_type="htpasswd",
        int_kwargs=_make_service_kwargs(internal_path),
        force_int_users=(force_internal_users or []),

        ext_type=("htpasswd" if external_path else ""),
        ext_kwargs=(_make_service_kwargs(external_path) if external_path else {}),

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

        assert (await manager.login("user", "foo", 0))[0] is None
        assert (await manager.login("admin", "foo", 0))[0] is None
        assert (await manager.login("user", "pass", 0))[0] is None

        (token1, _) = await manager.login("admin", "pass", 0)
        assert isinstance(token1, str)
        assert len(token1) == 64

        (token2, _) = await manager.login("admin", "pass", 0)
        assert isinstance(token2, str)
        assert len(token2) == 64
        assert token1 != token2

        assert manager.check(token1) == "admin"
        assert manager.check(token2) == "admin"
        assert manager.check("foobar") is None

        # The fork's logout() closes only the session it is given. Upstream
        # closed every session belonging to that user, and the loop that did
        # so survives commented out at auth.py:337-341. token2 therefore stays
        # valid here; this assertion records the fork's behaviour, not a wish.
        manager.logout(token1)

        assert manager.check(token1) is None
        assert manager.check(token2) == "admin"
        assert manager.check("foobar") is None

        (token3, _) = await manager.login("admin", "pass", 0)
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

        assert (await manager.login("local", "foobar", 0))[0] is None
        assert (await manager.login("admin", "pass2", 0))[0] is None

        (token, _) = await manager.login("admin", "pass1", 0)
        assert token is not None

        assert manager.check(token) == "admin"
        manager.logout(token)
        assert manager.check(token) is None

        (token, _) = await manager.login("user", "foobar", 0)
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
            expire=0,
            usc_users=[],
            usc_groups=[],
            unauth_paths=[],

            int_type="foobar",
            int_kwargs={},
            force_int_users=[],

            ext_type="",
            ext_kwargs={},

        )

        assert not manager.is_auth_enabled()
        assert not manager.is_auth_required(_E_AUTH)
        assert not manager.is_auth_required(_E_UNAUTH)
        assert not manager.is_auth_required(_E_FREE)

        with pytest.raises(AssertionError):
            await manager.authorize("admin", "admin")

        with pytest.raises(AssertionError):
            await manager.login("admin", "admin", 0)

        with pytest.raises(AssertionError):
            manager.logout("xxx")

        with pytest.raises(AssertionError):
            manager.check("xxx")
    finally:
        await manager.cleanup()


# =====
# Client identity for rate limiting and the "local network only" gates.
#
# _get_client_ip used to take a headers dict, so every lockout decision, every
# rate-limit decision and the unauthenticated /same_check gate were keyed on a
# string the caller supplied. It now takes the REQUEST and honours X-Real-IP /
# X-Forwarded-For only when the immediate peer is trusted -- a Unix socket
# (which is how nginx reaches kvmd; kvmd/server has only a `unix` listener) or
# loopback. From anywhere else the headers are ignored in favour of the
# transport address.
class _FakeTransport:
    def __init__(self, sock: Any, peername: Any) -> None:
        self.__sock = sock
        self.__peername = peername

    def get_extra_info(self, name: str, default: Any=None) -> Any:
        if name == "socket":
            return self.__sock
        if name == "peername":
            return self.__peername
        return default


class _FakeRequest:
    def __init__(self, transport: Any, headers: (dict | None)=None) -> None:
        self.transport = transport
        self.headers = (headers or {})


def _make_disabled_manager() -> AuthManager:
    return AuthManager(
        enabled=False,
        expire=0,
        usc_users=[],
        usc_groups=[],
        unauth_paths=[],

        int_type="foobar",
        int_kwargs={},
        force_int_users=[],

        ext_type="",
        ext_kwargs={},

    )


def _client_ip(transport: Any, headers: (dict | None)=None) -> str:
    manager = _make_disabled_manager()
    return manager._get_client_ip(_FakeRequest(transport, headers))  # pylint: disable=protected-access


def test_fail__spoofed_real_ip_is_ignored_from_a_remote_peer() -> None:
    # A remote client claiming to be on the LAN. This is the exact bypass of
    # the /same_check gate and of every rate-limit bucket.
    transport = _FakeTransport(None, ("203.0.113.7", 54321))
    assert _client_ip(transport, {"X-Real-IP": "192.168.1.1"}) == "203.0.113.7"


def test_fail__spoofed_forwarded_for_is_ignored_from_a_remote_peer() -> None:
    transport = _FakeTransport(None, ("203.0.113.7", 54321))
    headers = {"X-Forwarded-For": "192.168.1.1, 10.0.0.1"}
    assert _client_ip(transport, headers) == "203.0.113.7"


def test_ok__real_ip_is_honoured_from_a_unix_peer() -> None:
    # A real AF_UNIX socketpair, so SO_PEERCRED genuinely succeeds rather than
    # being mocked. This is the nginx path.
    (sock, other) = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        transport = _FakeTransport(sock, None)
        assert _client_ip(transport, {"X-Real-IP": "10.1.2.3"}) == "10.1.2.3"
    finally:
        sock.close()
        other.close()


def test_ok__real_ip_is_honoured_from_loopback() -> None:
    transport = _FakeTransport(None, ("127.0.0.1", 41234))
    assert _client_ip(transport, {"X-Real-IP": "10.1.2.3"}) == "10.1.2.3"


def test_ok__falls_back_to_the_peer_address_without_headers() -> None:
    transport = _FakeTransport(None, ("203.0.113.7", 54321))
    assert _client_ip(transport) == "203.0.113.7"


def test_ok__unknown_without_a_transport() -> None:
    assert _client_ip(None) == "unknown"


# =====
# The 2FA removal was an ATOMICITY TRAP and these pin both halves of it.
#
# The login page used to concatenate a six-character code onto the password
# (web/share/js/login/main.js) and authorize() sliced the last six characters
# back off whenever /etc/kvmd/user/totp.secret was non-empty. Removing one side
# without the other does not crash: it silently eats or appends six characters
# of every real password. A silent corruption, so it needs an assertion rather
# than a smoke test.
@pytest.mark.asyncio
async def test_ok__password_is_not_truncated(tmpdir) -> None:  # type: ignore
    path = os.path.abspath(str(tmpdir.join("htpasswd")))

    # The last six characters are load-bearing: "123456" is exactly what the
    # old TOTP slice would have removed.
    passwd = "correcthorse123456"

    htpasswd = KvmdHtpasswdFile(path, new=True)
    htpasswd.set_password("admin", passwd)
    htpasswd.save()

    async with _get_configured_manager([], path) as manager:
        # The whole password authenticates ...
        (token, _) = await manager.login("admin", passwd, 0)
        assert isinstance(token, str)

        # ... and the sliced form does not, which is what fails if the server
        # side of the 2FA removal is ever reintroduced on its own.
        assert (await manager.login("admin", passwd[:-6], 0))[0] is None


def test_fail__totp_secret_path_is_no_longer_accepted() -> None:
    # Pins the removal so it cannot quietly come back with the web half absent.
    with pytest.raises(TypeError):
        AuthManager(  # type: ignore[call-arg]
            enabled=False,
            expire=0,
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
