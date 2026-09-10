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
import time
import contextlib

from typing import AsyncGenerator

import pytest

from kvmd.yamlconf import make_config

from kvmd.apps.kvmd.auth import AuthManager

from kvmd.crypto import KvmdHtpasswdFile

from kvmd.plugins.auth import get_auth_service_class


# =====
# AuthManager.login_verified is the ONE method the WebAuthn integration adds to
# auth.py. It mints a session for a caller already authenticated by other means.
#
# Every assertion below covers a way of getting it wrong that produces NO error
# at the point of the mistake:
#
#   1. calling authorize() -- would make WebAuthn depend on a password
#   2. a token of the wrong shape -- rejected on the NEXT request, not this one
#   3. a wall-clock expire_ts -- sessions that never expire, or expire instantly
#   4. ws_started != 0 -- the WS lifecycle silently stops reference-counting
#   5. not consuming the counter -- the UI's failed-attempt count never resets
def _service_kwargs(path: str) -> dict:
    cls = get_auth_service_class("htpasswd")
    return make_config({"file": path}, cls.get_plugin_options())._unpack()


@contextlib.asynccontextmanager
async def _manager(path: str, expire: int=0, extend: bool=False) -> AsyncGenerator[AuthManager, None]:
    htpasswd = KvmdHtpasswdFile(path, new=True)
    htpasswd.set_password("admin", "password")
    htpasswd.save()
    manager = AuthManager(
        enabled=True,
        expire=expire,
        extend=extend,
        usc_users=[],
        usc_groups=[],
        unauth_paths=[],
        int_type="htpasswd",
        int_kwargs=_service_kwargs(path),
        force_int_users=[],
        ext_type="",
        ext_kwargs={},
    )
    try:
        yield manager
    finally:
        await manager.cleanup()


# ===== 1. does NOT call authorize()
@pytest.mark.asyncio
async def test_ok__does_not_call_authorize(tmpdir) -> None:  # type: ignore
    path = os.path.abspath(str(tmpdir.join("htpasswd")))
    async with _manager(path) as manager:
        calls: list = []

        async def spy(user: str, passwd: str) -> bool:
            calls.append((user, passwd))
            return False   # would deny everything if it were consulted

        manager.authorize = spy  # type: ignore[method-assign]

        (token, _) = manager.login_verified("admin", 0)
        assert isinstance(token, str)
        assert manager.check(token) == "admin"
        assert calls == [], "login_verified consulted the password path"


# ===== 2. token comes from __make_new_token() -- 64 lowercase hex
@pytest.mark.asyncio
async def test_ok__token_shape_survives_the_next_request(tmpdir) -> None:  # type: ignore
    import re
    from kvmd.validators.auth import valid_auth_token

    path = os.path.abspath(str(tmpdir.join("htpasswd")))
    async with _manager(path) as manager:
        (token, _) = manager.login_verified("admin", 0)
        assert re.fullmatch(r"[0-9a-f]{64}", token), f"token is not 64 lowercase hex: {token!r}"
        # The real gate: the NEXT request runs the token through this validator
        # before check() ever sees it. A wrong shape fails there, not here.
        assert manager.check(valid_auth_token(token)) == "admin"


# ===== 3. expire_ts from __make_expire_ts() -- the monotonic-vs-wall-clock one
@pytest.mark.asyncio
async def test_ok__expires_on_the_same_clock_as_a_password_session(tmpdir, monkeypatch) -> None:  # type: ignore
    path = os.path.abspath(str(tmpdir.join("htpasswd")))
    async with _manager(path, expire=600) as manager:
        (pw_token, _) = await manager.login("admin", "password", 0)
        (wa_token, _) = manager.login_verified("admin", 0)
        assert isinstance(pw_token, str)

        sessions = manager._AuthManager__sessions  # pylint: disable=protected-access
        pw_ts = sessions[pw_token].expire_ts
        wa_ts = sessions[wa_token].expire_ts

        # Compared against the password session rather than an absolute bound:
        # a time.time() mint is also a large positive integer and would pass any
        # absolute check, while being ~55 years in the future.
        assert abs(wa_ts - pw_ts) <= 1, (
            f"WebAuthn expire_ts {wa_ts} is not on the same clock as the"
            f" password session's {pw_ts} -- a wall-clock mint never expires"
        )

        # And both must actually expire when that clock advances.
        monkeypatch.setattr(time, "monotonic", (lambda: (time.perf_counter() + 100000)))
        assert manager.check(pw_token) is None
        assert manager.check(wa_token) is None, "the WebAuthn session outlived the password one"


@pytest.mark.asyncio
async def test_ok__a_bare_expire_would_not_be_mistaken_for_valid(tmpdir) -> None:  # type: ignore
    # The other half of the same defect: passing `expire` straight through
    # instead of __make_expire_ts() gives an expire_ts in the past, so the
    # session is dead on arrival. Assert the session is alive right after mint.
    path = os.path.abspath(str(tmpdir.join("htpasswd")))
    async with _manager(path, expire=600) as manager:
        (token, _) = manager.login_verified("admin", 0)
        assert manager.check(token) == "admin", "session expired immediately after minting"


# ===== 4. ws_started=0
@pytest.mark.asyncio
async def test_ok__ws_started_is_zero_and_the_lifecycle_works(tmpdir) -> None:  # type: ignore
    path = os.path.abspath(str(tmpdir.join("htpasswd")))
    async with _manager(path, expire=600, extend=True) as manager:
        (token, _) = manager.login_verified("admin", 0)
        sessions = manager._AuthManager__sessions  # pylint: disable=protected-access
        assert sessions[token].ws_started == 0

        # A non-zero start would leave the count unable to reach 0 on close, so
        # the session would stay infinite forever.
        manager.start_ws_session(token)
        assert sessions[token].expire_ts == 0
        manager.stop_ws_session(token)
        assert sessions[token].expire_ts > 0


# ===== 5. consumes __consume_failed_since_last_success()
@pytest.mark.asyncio
async def test_ok__consumes_the_failed_attempt_counter(tmpdir) -> None:  # type: ignore
    path = os.path.abspath(str(tmpdir.join("htpasswd")))
    async with _manager(path) as manager:
        for _ in range(3):
            assert (await manager.login("admin", "wrong", 0))[0] is None

        (token, failed) = manager.login_verified("admin", 0)
        assert isinstance(token, str)
        assert failed == 3, "login_verified did not report the accumulated failures"

        (_, failed_again) = manager.login_verified("admin", 0)
        assert failed_again == 0, "the counter was not consumed, so the UI never resets it"
