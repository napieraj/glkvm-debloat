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

import pytest

from kvmd.apps.kvmd.api.auth import get_client_ip


# =====
# Client identity for the local-network gate on GET /same_check.
#
# These helpers used to live on AuthManager, because the deleted rate-limit
# subsystem was their other consumer. same_check is the only one left, so they
# moved here with it.
#
# The finding they close: identity came from a headers dict, so the
# unauthenticated /same_check "local network only" gate was keyed on a value the
# caller supplied. X-Real-IP and X-Forwarded-For are now honoured only from a
# trusted peer -- a Unix socket, which is how nginx reaches kvmd, or loopback.
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


def _client_ip(transport: Any, headers: (dict | None)=None) -> str:
    return get_client_ip(_FakeRequest(transport, headers))  # type: ignore[arg-type]


def test_fail__spoofed_real_ip_is_ignored_from_a_remote_peer() -> None:
    # A remote client claiming to be on the LAN. This is the exact bypass of the
    # /same_check gate.
    transport = _FakeTransport(None, ("8.8.8.8", 54321))
    assert _client_ip(transport, {"X-Real-IP": "192.168.1.1"}) == "8.8.8.8"


def test_fail__spoofed_forwarded_for_is_ignored_from_a_remote_peer() -> None:
    transport = _FakeTransport(None, ("8.8.8.8", 54321))
    headers = {"X-Forwarded-For": "192.168.1.1, 10.0.0.1"}
    assert _client_ip(transport, headers) == "8.8.8.8"


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


def test_ok__a_genuine_local_peer_passes_the_same_check_gate() -> None:
    # The positive case the rebuild must not break: a real LAN client behind
    # nginx still resolves to a private address, so _is_local_network accepts it.
    from kvmd.apps.kvmd.api.auth import _is_local_network  # pylint: disable=protected-access
    (sock, other) = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        transport = _FakeTransport(sock, None)
        resolved = _client_ip(transport, {"X-Real-IP": "192.168.7.50"})
        assert resolved == "192.168.7.50"
        assert _is_local_network(resolved)
    finally:
        sock.close()
        other.close()

    # ...and the spoofing remote peer does not, which is the gate working.
    # NB: 8.8.8.8 rather than a 203.0.113.0/24 documentation address, because
    # ipaddress.is_private is TRUE for the RFC 5737 documentation ranges (also
    # RFC 2544 benchmarking and 240.0.0.0/4), so _is_local_network accepts more
    # than the LAN. Recorded in docs/audit.md; it only started to matter once
    # this gate became genuinely enforceable.
    remote = _FakeTransport(None, ("8.8.8.8", 54321))
    assert not _is_local_network(_client_ip(remote, {"X-Real-IP": "192.168.7.50"}))


def test_ok__falls_back_to_the_peer_address_without_headers() -> None:
    transport = _FakeTransport(None, ("8.8.8.8", 54321))
    assert _client_ip(transport) == "8.8.8.8"


def test_ok__unknown_without_a_transport() -> None:
    assert _client_ip(None) == "unknown"
