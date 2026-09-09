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


import pwd
import grp
import dataclasses
import ipaddress
import time
import datetime

import secrets


from aiohttp.web import BaseRequest

from ...logging import get_logger

from ... import aiotools

from ...plugins.auth import BaseAuthService
from ...plugins.auth import get_auth_service_class

from ...htserver import HttpExposed
from ...htserver import RequestUnixCredentials
from ...htserver import get_request_unix_credentials


# =====
@dataclasses.dataclass(frozen=False)  # Mutable to allow sliding expiration
class _Session:
    user:      str
    expire_ts: int

    def __post_init__(self) -> None:
        assert self.user == self.user.strip()
        assert self.user
        assert self.expire_ts >= 0


class AuthManager:  # pylint: disable=too-many-arguments,too-many-instance-attributes
    def __init__(
        self,
        enabled: bool,
        expire: int,
        usc_users: list[str],
        usc_groups: list[str],
        unauth_paths: list[str],

        int_type: str,
        int_kwargs: dict,
        force_int_users: list[str],

        ext_type: str,
        ext_kwargs: dict,
    ) -> None:

        logger = get_logger(0)

        self.__enabled = enabled
        if not enabled:
            logger.warning("AUTHORIZATION IS DISABLED")

        assert expire >= 0
        self.__expire = expire
        if expire > 0:
            logger.info("Maximum user session time is limited: %s",
                        self.__format_seconds(expire))

        self.__usc_uids = self.__load_usc_uids(usc_users, usc_groups)
        if self.__usc_uids:
            logger.info("Selfauth UNIX socket access is allowed for users: %s",
                        list(self.__usc_uids.values()))

        self.__unauth_paths = frozenset(unauth_paths)  # To speed up
        if self.__unauth_paths:
            logger.info("Authorization is disabled for APIs: %s",
                        list(self.__unauth_paths))

        self.__int_service: (BaseAuthService | None) = None
        if enabled:
            self.__int_service = get_auth_service_class(int_type)(**int_kwargs)
            logger.info("Using internal auth service %r",
                        self.__int_service.get_plugin_name())

        self.__force_int_users = force_int_users

        self.__ext_service: (BaseAuthService | None) = None
        if enabled and ext_type:
            self.__ext_service = get_auth_service_class(ext_type)(**ext_kwargs)
            logger.info("Using external auth service %r",
                        self.__ext_service.get_plugin_name())

        self.__sessions: dict[str, _Session] = {}  # {token: session}

        # 自上一次登录成功以来的全局登录失败次数（仅内存，重启清零），
        # 用于在登录成功时提示用户是否疑似遭遇暴力破解。
        self.__failed_since_last_success = 0

    def is_auth_enabled(self) -> bool:
        return self.__enabled

    def is_auth_required(self, exposed: HttpExposed) -> bool:
        return (
            self.is_auth_enabled()
            and exposed.auth_required
            and exposed.path not in self.__unauth_paths
        )

    async def authorize(self, user: str, passwd: str) -> bool:
        assert user == user.strip()
        assert user
        assert self.__enabled
        assert self.__int_service
        logger = get_logger(0)

        if user not in self.__force_int_users and self.__ext_service:
            service = self.__ext_service
        else:
            service = self.__int_service

        pname = service.get_plugin_name()
        ok = (await service.authorize(user, passwd))
        if ok:
            logger.info("Authorized user %r via auth service %r", user, pname)
        else:
            logger.error("Got access denied for user %r from auth service %r", user, pname)
        return ok

    async def login(self, user: str, passwd: str, expire: int) -> tuple[str | None, int]:
        assert user == user.strip()
        assert user
        assert expire >= 0
        assert self.__enabled

        if (await self.authorize(user, passwd)):
            token = self.__make_new_token()
            session = _Session(
                user=user,
                expire_ts=self.__make_expire_ts(expire),
            )
            self.__sessions[token] = session
            failed_since_last = self.__consume_failed_since_last_success()
            get_logger(0).info("Logged in user %r; expire=%s, sessions_now=%d, failed_since_last_success=%d",
                               session.user,
                               self.__format_expire_ts(session.expire_ts),
                               self.__get_sessions_number(session.user),
                               failed_since_last)
            return (token, failed_since_last)
        else:
            self.__failed_since_last_success += 1

        return (None, 0)

    def __consume_failed_since_last_success(self) -> int:
        """返回自上一次登录成功以来累计的全局登录失败次数，并清零计数。"""
        count = self.__failed_since_last_success
        self.__failed_since_last_success = 0
        return count

    def __make_new_token(self) -> str:
        for _ in range(10):
            token = secrets.token_hex(32)
            if token not in self.__sessions:
                return token
        raise RuntimeError("Can't generate new unique token")

    def __make_expire_ts(self, expire: int) -> int:
        assert expire >= 0
        assert self.__expire >= 0

        if expire == 0:
            # The user requested infinite session: apply global expire.
            # It will allow this (0) or set a limit.
            expire = self.__expire
        else:
            # The user wants a limited session
            if self.__expire > 0:
                # If we have a global limit, override the user limit
                assert expire > 0
                expire = min(expire, self.__expire)

        if expire > 0:
            return (self.__get_now_ts() + expire)

        assert expire == 0
        return 0

    def __get_now_ts(self) -> int:
        return int(time.monotonic())

    def __format_expire_ts(self, expire_ts: int) -> str:
        if expire_ts > 0:
            seconds = expire_ts - self.__get_now_ts()
            return f"[{self.__format_seconds(seconds)}]"
        return "INF"

    def __format_seconds(self, seconds: int) -> str:
        return str(datetime.timedelta(seconds=seconds))

    def __get_sessions_number(self, user: str) -> int:
        return sum(
            1
            for session in self.__sessions.values()
            if session.user == user
        )

    def logout(self, token: str) -> None:
        assert self.__enabled
        if token in self.__sessions:
            user = self.__sessions[token].user
            # count = 0
            # for (key_t, session) in list(self.__sessions.items()):
            #     if session.user == user:
            #         count += 1
            #         del self.__sessions[key_t]
            # get_logger(0).info("Logged out user %r; sessions_closed=%d", user, count)
            # 去掉删除所有此用户token的代码, 实在太蠢
            del self.__sessions[token]
            get_logger(0).info("Logged out user %r; sessions_left=%d", user, self.__get_sessions_number(user))

    def check(self, token: str) -> (str | None):
        assert self.__enabled
        session = self.__sessions.get(token)
        if session is not None:
            if session.expire_ts <= 0:
                # Infinite session
                return session.user
            else:
                # Limited session
                if self.__get_now_ts() < session.expire_ts:
                    return session.user
                else:
                    del self.__sessions[token]
                    get_logger(0).info("The session of user %r is expired; sessions_left=%d",
                                       session.user,
                                       self.__get_sessions_number(session.user))
        return None

    def refresh_token_expiry(self, token: str) -> bool:
        """Refresh token expiration time (sliding expiration).
        Returns True if token was found and refreshed.
        Uses throttling: only refresh when remaining time < half of expire time.
        """
        assert self.__enabled
        session = self.__sessions.get(token)
        if session is not None:
            if self.__expire > 0 and session.expire_ts > 0:
                now = self.__get_now_ts()
                remaining = session.expire_ts - now
                # Only refresh if remaining time is less than half of expire time (throttling)
                if remaining < self.__expire // 2:
                    session.expire_ts = now + self.__expire
                return True
        return False

    @aiotools.atomic_fg
    async def cleanup(self) -> None:
        if self.__enabled:
            assert self.__int_service
            await self.__int_service.cleanup()
            if self.__ext_service:
                await self.__ext_service.cleanup()

    # =====

    def __load_usc_uids(self, users: list[str], groups: list[str]) -> dict[int, str]:
        uids: dict[int, str] = {}

        pwds: dict[str, int] = {}
        for pw in pwd.getpwall():
            assert pw.pw_name == pw.pw_name.strip()
            assert pw.pw_name
            pwds[pw.pw_name] = pw.pw_uid
            if pw.pw_name in users:
                uids[pw.pw_uid] = pw.pw_name

        for gr in grp.getgrall():
            if gr.gr_name in groups:
                for member in gr.gr_mem:
                    if member in pwds:
                        uid = pwds[member]
                        uids[uid] = member

        return uids

    def check_unix_credentials(self, creds: RequestUnixCredentials) -> (str | None):
        assert self.__enabled
        return self.__usc_uids.get(creds.uid)

    # =====
    # Rate limiting methods

    def __is_trusted_peer(self, req: BaseRequest) -> bool:
        """本次连接的对端是否可信到可以相信它设置的代理头。

        Trusted means the immediate peer is local: either a Unix socket
        connection, which is how nginx reaches kvmd (kvmd/server has only a
        `unix` listener, apps/__init__.py:422), or a loopback TCP address.
        Anything else is a remote client talking to us directly, and its
        headers are its own claims.
        """
        if get_request_unix_credentials(req) is not None:
            # SO_PEERCRED succeeded, so this is a Unix socket peer.
            return True
        peer_ip = self.__get_peer_ip(req)
        if not peer_ip:
            return False
        try:
            return ipaddress.ip_address(peer_ip).is_loopback
        except ValueError:
            return False

    def __get_peer_ip(self, req: BaseRequest) -> str:
        """对端 socket 的地址；Unix socket 连接没有地址,返回空串。"""
        if req.transport is None:
            return ""
        peername = req.transport.get_extra_info("peername")
        if isinstance(peername, tuple) and len(peername) >= 1:
            return str(peername[0])
        return ""

    def _get_client_ip(self, req: BaseRequest) -> str:
        """Identify the client for rate limiting and local-network checks.

        Takes the REQUEST, not a headers dict, so that identifying a caller by
        its own headers is not expressible at the call site. X-Real-IP and
        X-Forwarded-For are honoured only when the immediate peer is trusted
        (see __is_trusted_peer); from an untrusted peer they are ignored
        entirely in favour of the transport address, because a header a remote
        client controls is that client naming itself.
        """
        if self.__is_trusted_peer(req):
            real_ip = req.headers.get("X-Real-IP", "").strip()
            if real_ip:
                return real_ip
            forwarded_for = req.headers.get("X-Forwarded-For", "")
            if forwarded_for:
                # X-Forwarded-For can carry a chain; the client is the first entry.
                first = forwarded_for.split(",")[0].strip()
                if first:
                    return first
        return (self.__get_peer_ip(req) or "unknown")
