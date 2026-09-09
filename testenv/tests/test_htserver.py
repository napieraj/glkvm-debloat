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


import socket

from typing import Any

from kvmd.htserver import is_request_secure


# =====
# The Secure flag on the session cookie is conditional, and both branches
# matter. nginx/https/enabled is a real config option defaulting to True; with
# it False the entire API including login is served over plain HTTP, and an
# unconditional Secure cookie would make that deployment fail to log in with no
# error anywhere — the browser would just decline to store it.
#
# kvmd listens only on a Unix socket, so it never sees the client's scheme
# itself; nginx forwards it as X-Forwarded-Proto, trustworthy for the same
# reason X-Real-IP is (only a local process in the socket's group can set it).
class _FakeTransport:
    def __init__(self, sock: Any) -> None:
        self.__sock = sock

    def get_extra_info(self, name: str, default: Any=None) -> Any:
        if name == "socket":
            return self.__sock
        return default


class _FakeRequest:
    def __init__(self, transport: Any, headers: (dict | None)=None) -> None:
        self.transport = transport
        self.headers = (headers or {})


def _secure(headers: (dict | None)=None, unix: bool=True) -> bool:
    if not unix:
        return is_request_secure(_FakeRequest(_FakeTransport(None), headers))  # type: ignore[arg-type]
    (sock, other) = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        return is_request_secure(_FakeRequest(_FakeTransport(sock), headers))  # type: ignore[arg-type]
    finally:
        sock.close()
        other.close()


def test_ok__secure_when_the_proxy_says_https() -> None:
    assert _secure({"X-Forwarded-Proto": "https"})


def test_ok__secure_is_case_and_space_insensitive() -> None:
    assert _secure({"X-Forwarded-Proto": " HTTPS "})


def test_fail__not_secure_when_the_proxy_says_http() -> None:
    # This is the nginx/https/enabled=False deployment. It must NOT get a Secure
    # cookie or login silently stops working.
    assert not _secure({"X-Forwarded-Proto": "http"})


def test_fail__not_secure_without_the_header() -> None:
    assert not _secure({})


def test_fail__header_is_ignored_from_an_untrusted_peer() -> None:
    # No Unix peer means no trusted proxy, so the header is its sender's claim.
    assert not _secure({"X-Forwarded-Proto": "https"}, unix=False)
