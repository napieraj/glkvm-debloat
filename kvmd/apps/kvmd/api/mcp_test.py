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


"""
Tests for api/mcp.py.

Everything here drives the REAL module through a REAL aiohttp application
built by the fork's own HttpServer, with the routes discovered by the fork's
own @exposed_http scanner -- no reimplementation of the dispatch, the
envelope, or the route wrapper.  Only the four backends the module talks to
are faked, and each fake honours the interface in the source:

  - HID / ATX / MSD subclass the actual plugin base classes
    (kvmd/plugins/{hid,atx,msd}/__init__.py), so the real send_key_events
    pacing, the real send_key_event auto-release and the real mouse remapping
    all run.  The fork ships no fake plugins to reuse: `disabled.py` in each
    plugin family raises on every call, and there is no dummy HID at all.
  - Streamer and Ocr are hand-written stubs, because the real classes need a
    ustreamer process and an RKNN socket.  Their method signatures are copied
    from kvmd/apps/kvmd/streamer.py:428 and kvmd/apps/kvmd/ocr.py:196-255.
  - LogReader is the REAL class pointed at a temporary file.
"""


import os
import io
import json
import asyncio
import time
import base64
import atexit
import logging
import tempfile
import contextlib
import dataclasses

from typing import Any
from typing import AsyncGenerator
from typing import Iterable

import pytest

from aiohttp.test_utils import TestClient
from aiohttp.test_utils import TestServer

from PIL import Image as PilImage

import kvmd.utils


# The device exposes its model at /proc/gl-hw-info/model; off-device that path
# is absent and kvmd/utils.py:39 then raises NameError (get_logger is never
# imported there).  Importing kvmd.apps.kvmd.api.mcp pulls in the package
# __init__ -> server.py -> api/fingerbot.py:46, which calls get_model_name() at
# IMPORT time, so the path has to be redirected before that import happens.
# This is a sandbox artefact, not something the module under test does.
if not os.path.exists(kvmd.utils.MODEL_PATH):
    (_model_fd, _model_path) = tempfile.mkstemp(prefix="kvmd-model-")
    os.write(_model_fd, b"rm1pe\n")
    os.close(_model_fd)
    kvmd.utils.MODEL_PATH = _model_path
    atexit.register(lambda: os.path.exists(_model_path) and os.remove(_model_path))


from ....clients.streamer import StreamerSnapshot  # noqa: E402

from ....htserver import HttpServer  # noqa: E402
from ....htserver import _get_exposed_http  # noqa: E402

from ....keyboard.mappings import WEB_TO_EVDEV  # noqa: E402

from ....mouse import MOUSE_TO_EVDEV  # noqa: E402
from ....mouse import MouseRange  # noqa: E402

from ....plugins.atx import BaseAtx  # noqa: E402
from ....plugins.hid import BaseHid  # noqa: E402
from ....plugins.msd import BaseMsd  # noqa: E402
from ....plugins.msd import BaseMsdWriter  # noqa: E402
from ....plugins.msd import MsdConnectedError  # noqa: E402

from .... import __version__  # noqa: E402

from ..logreader import LogReader  # noqa: E402

from ..ocr import OcrError  # noqa: E402

from . import mcp as mcp_module  # noqa: E402
from . import wol as wol_module  # noqa: E402

from .mcp import McpApi  # noqa: E402


# =====
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))

# The device keeps its keymaps in /usr/share/kvmd/keymaps (api/hid.py:80-81);
# in the source tree the same files live here.
_KEYMAP_PATH = os.path.join(_REPO_ROOT, "contrib", "keymaps", "en-us")

_SRC_WIDTH = 1024
_SRC_HEIGHT = 768


def _make_jpeg(width: int, height: int) -> bytes:
    with contextlib.closing(PilImage.new("RGB", (width, height), (30, 60, 90))) as image:
        with io.BytesIO() as bio:
            image.save(bio, format="jpeg", quality=90)
            return bio.getvalue()


_FRAME = _make_jpeg(_SRC_WIDTH, _SRC_HEIGHT)


def _jpeg_size(data: bytes) -> tuple[int, int]:
    with io.BytesIO(data) as bio:
        with PilImage.open(bio) as image:
            return (image.width, image.height)


# =====
class _FakeStreamer:
    """kvmd/apps/kvmd/streamer.py: take_snapshot(save, load, allow_offline) never raises
    and returns None on any failure (streamer.py:428-445); get_state() may have a NULL
    "streamer" sub-dict (streamer.py:347-354)."""

    def __init__(self, data: bytes=_FRAME, online: bool=True, broken: bool=False, running: bool=True) -> None:
        self.data = data
        self.online = online
        self.broken = broken
        self.running = running
        self.snapshot_calls: list[dict] = []

    async def take_snapshot(self, save: bool, load: bool, allow_offline: bool) -> (StreamerSnapshot | None):
        self.snapshot_calls.append({"save": save, "load": load, "allow_offline": allow_offline})
        if self.broken:
            return None
        return StreamerSnapshot(
            online=self.online,
            width=_SRC_WIDTH,
            height=_SRC_HEIGHT,
            headers=(("X-UStreamer-Online", str(self.online).lower()),),
            data=self.data,
        )

    async def get_state(self) -> dict:
        inner: (dict | None) = None
        if self.running:
            inner = {"source": {
                "online": self.online,
                "resolution": {"width": _SRC_WIDTH, "height": _SRC_HEIGHT},
            }}
        return {
            "features": {},
            "limits": {},
            "params": {"resolution": f"{_SRC_WIDTH}x{_SRC_HEIGHT}", "quality": 80},
            "snapshot": {"saved": None},
            "streamer": inner,
        }


class _FakeOcr:
    """kvmd/apps/kvmd/ocr.py: recognize(data, langs, left, top, right, bottom) (ocr.py:249),
    _use_rknn() (ocr.py:196) and get_state() (ocr.py:200)."""

    def __init__(self, texts: Iterable[str]=("",), use_rknn: bool=True) -> None:
        self.texts = list(texts)
        self.use_rknn = use_rknn
        self.calls: list[dict] = []

    def _use_rknn(self) -> bool:
        return self.use_rknn

    async def recognize(self, data: bytes, langs: list[str], left: int, top: int, right: int, bottom: int) -> str:
        self.calls.append({"data": data, "langs": langs, "box": (left, top, right, bottom)})
        return self.texts[min(len(self.calls) - 1, len(self.texts) - 1)]

    async def get_state(self) -> dict:
        return {
            "enabled": True,
            "engine": ("rknn" if self.use_rknn else "tesseract"),
            "langs": {"default": [], "available": []},
        }


class _FakeHid(BaseHid):
    """A real BaseHid: the pacing in send_key_events, the auto-release in
    send_key_event and the mouse remapping in send_mouse_move_event are the
    fork's own code (plugins/hid/__init__.py:152-229)."""

    def __init__(self, absolute: bool=True) -> None:
        super().__init__(
            ignore_keys=[],
            mouse_x_min=MouseRange.MIN,
            mouse_x_max=MouseRange.MAX,
            mouse_y_min=MouseRange.MIN,
            mouse_y_max=MouseRange.MAX,
            jiggler_enabled=False,
            jiggler_active=False,
            jiggler_interval=20,
        )
        self.absolute = absolute
        self.events: list[tuple] = []
        self.cleared = 0

    async def get_state(self) -> dict:
        return {
            # otg hardcodes this to True (plugins/hid/otg/__init__.py:270).
            "online": True,
            "connected": True,
            "busy": False,
            "keyboard": {"online": True, "leds": {}, "outputs": {}},
            "mouse": {"online": True, "absolute": self.absolute, "outputs": {}},
        }

    def _send_key_event(self, key: int, state: bool) -> None:
        self.events.append(("key", key, state))

    def _send_mouse_button_event(self, button: int, state: bool) -> None:
        self.events.append(("button", button, state))

    def _send_mouse_move_event(self, to_x: int, to_y: int) -> None:
        self.events.append(("move", to_x, to_y))

    def _send_mouse_wheel_event(self, delta_x: int, delta_y: int) -> None:
        self.events.append(("wheel", delta_x, delta_y))

    def _clear_events(self) -> None:
        self.cleared += 1


class _FakeAtx(BaseAtx):
    """BaseAtx's seven actions take `wait` as a required positional bool
    (plugins/atx/__init__.py:69-89).  broken_wait reproduces glatx.py:113,
    where `async with` on a sync-only AioExclusiveRegion raises TypeError."""

    def __init__(self, broken_wait: bool=True) -> None:
        self.broken_wait = broken_wait
        self.actions: list[tuple[str, bool]] = []

    async def get_state(self) -> dict:
        return {
            "enabled": True,
            "busy": False,
            "power": "on",
            # glatx hardcodes both LEDs to False (glatx.py:33-35).
            "leds": {"power": False, "hdd": False},
        }

    async def __do(self, name: str, wait: bool) -> None:
        if wait and self.broken_wait:
            raise TypeError("'AioExclusiveRegion' object does not support the asynchronous context manager protocol")
        self.actions.append((name, wait))

    async def power_on(self, wait: bool) -> None:
        await self.__do("power_on", wait)

    async def power_off(self, wait: bool) -> None:
        await self.__do("power_off", wait)

    async def power_off_hard(self, wait: bool) -> None:
        await self.__do("power_off_hard", wait)

    async def power_reset_hard(self, wait: bool) -> None:
        await self.__do("power_reset_hard", wait)

    async def click_power(self, wait: bool) -> None:
        await self.__do("click_power", wait)

    async def click_power_long(self, wait: bool) -> None:
        await self.__do("click_power_long", wait)

    async def click_reset(self, wait: bool) -> None:
        await self.__do("click_reset", wait)


class _FakeMsdWriter(BaseMsdWriter):
    """write_chunk returns the CUMULATIVE size, not the chunk length
    (plugins/msd/__init__.py:294-319)."""

    def __init__(self) -> None:
        self.data = b""

    def get_chunk_size(self) -> int:
        return 4096

    async def write_chunk(self, chunk: bytes) -> int:
        self.data += chunk
        return len(self.data)


class _FakeMsd(BaseMsd):
    def __init__(self, connected: bool=False, free: int=(1 << 30)) -> None:
        self.connected = connected
        self.free = free
        self.images = {"ubuntu.iso": {"size": 1234, "complete": True}}
        self.calls: list[tuple] = []
        self.params: (tuple | None) = None
        self.removed: list[str] = []
        self.written: dict[str, bytes] = {}

    async def get_state(self) -> dict:
        return {
            "enabled": True,
            "online": True,
            "busy": False,
            "storage": {
                "images": dict(self.images),
                # Free space hides under the EMPTY-STRING partition key (api/msd.py:282).
                "parts": {"": {"size": (1 << 31), "free": self.free, "writable": True}},
            },
            "drive": {
                "image": {"name": "ubuntu.iso", "size": 1234},
                "connected": self.connected,
                "cdrom": True,
                "rw": False,
            },
        }

    async def set_params(self, name: (str | None)=None, cdrom: (bool | None)=None, rw: (bool | None)=None) -> None:
        if self.connected:
            # otg/__init__.py:396 refuses while the drive is connected.
            raise MsdConnectedError()
        self.params = (name, cdrom, rw)
        self.calls.append(("set_params", name, cdrom, rw))

    async def set_connected(self, connected: bool) -> None:
        self.connected = connected
        self.calls.append(("set_connected", connected))

    async def remove(self, name: str) -> None:
        self.removed.append(name)
        self.calls.append(("remove", name))

    @contextlib.asynccontextmanager
    async def write_image(self, name: str, size: int, remove_incomplete: (bool | None)) -> AsyncGenerator[BaseMsdWriter, None]:
        self.calls.append(("write_image", name, size, remove_incomplete))
        writer = _FakeMsdWriter()
        yield writer
        self.written[name] = writer.data


# =====
class _FakeRemote:
    """The subset of aiohttp.ClientResponse that htclient.get_filename (htclient.py:52)
    and api/mcp.py's fetch_iso touch."""

    def __init__(self, data: bytes, path: str, content_length: (int | None)=None) -> None:
        self.headers: dict[str, str] = {}
        self.url = dataclasses.make_dataclass("_Url", [("path", str)])(path)
        self.content_length = (len(data) if content_length is None else content_length)
        self.content = self
        self.__data = data

    async def iter_chunked(self, size: int) -> AsyncGenerator[bytes, None]:
        for index in range(0, len(self.__data), size):
            yield self.__data[index:index + size]


@contextlib.contextmanager
def _patched_download(monkeypatch: Any, remote: _FakeRemote, error: (Exception | None)=None) -> Any:
    @contextlib.asynccontextmanager
    async def fake_download(url: str, verify: bool=True, timeout: float=10.0, read_timeout: (float | None)=None, app: str="KVMD") -> Any:
        calls.append({"url": url, "verify": verify, "timeout": timeout, "read_timeout": read_timeout, "app": app})
        if error is not None:
            raise error
        yield remote

    calls: list[dict] = []
    monkeypatch.setattr(mcp_module.htclient, "download", fake_download)
    yield calls


# =====
class _TestServer(TestServer):
    """aiohttp's own TestServer forces handler_cancellation=True
    (aiohttp/test_utils.py:129).  The fork does NOT: HttpServer.run() calls
    web.run_app() without that argument and it defaults to False
    (htserver.py:403-411, aiohttp/web.py:462).  Left as aiohttp's test default
    every test here would run against a server that cancels handlers when the
    peer goes away while the device does not -- which would hide exactly the
    behaviour api/hid.py's disconnect watchdog exists to provide."""

    async def _make_runner(self, **kwargs: Any) -> Any:
        kwargs["handler_cancellation"] = False
        return (await super()._make_runner(**kwargs))


class _Server(HttpServer):
    def __init__(self, api: McpApi) -> None:
        super().__init__()
        self.__api = api

    async def _init_app(self) -> None:
        self._add_exposed(self.__api)

    async def make_app(self) -> Any:
        # __make_app() is name-mangled private (htserver.py:541) and there is no
        # public accessor; reimplementing it here would test a copy of the
        # fork's routing instead of the fork's routing.
        return (await getattr(self, "_HttpServer__make_app")())


@dataclasses.dataclass(frozen=True)
class _Kvm:
    client: TestClient
    streamer: _FakeStreamer
    ocr: _FakeOcr
    hid: _FakeHid
    atx: _FakeAtx
    msd: _FakeMsd

    async def post(self, body: (str | bytes | Any), headers: (dict | None)=None) -> tuple[int, str]:
        async with self.client.post("/mcp", data=body, headers=headers) as resp:
            return (resp.status, (await resp.text()))

    async def rpc(self, method: str, params: (dict | None)=None, req_id: Any=1) -> dict:
        request: dict = {"jsonrpc": "2.0", "method": method}
        if req_id is not None:
            request["id"] = req_id
        if params is not None:
            request["params"] = params
        (status, text) = await self.post(json.dumps(request))
        assert status == 200, text
        return json.loads(text)

    async def ok(self, method: str, params: (dict | None)=None) -> dict:
        envelope = await self.rpc(method, params)
        assert "error" not in envelope, envelope
        assert envelope["jsonrpc"] == "2.0"
        assert envelope["id"] == 1
        return envelope["result"]

    async def error(self, method: str, params: (dict | None)=None) -> dict:
        envelope = await self.rpc(method, params)
        assert "result" not in envelope, envelope
        return envelope["error"]

    async def call(self, tool: str, args: (dict | None)=None) -> dict:
        return (await self.ok("tools/call", {"name": tool, "arguments": (args or {})}))

    async def call_ok(self, tool: str, args: (dict | None)=None) -> dict:
        result = await self.call(tool, args)
        assert result["isError"] is False, result
        return result

    async def call_err(self, tool: str, args: (dict | None)=None) -> str:
        result = await self.call(tool, args)
        assert result["isError"] is True, result
        return str(result["content"][0]["text"])

    async def payload(self, tool: str, args: (dict | None)=None) -> Any:
        # Every non-`see`/`read` tool answers with a single JSON text part.
        result = await self.call_ok(tool, args)
        assert [part["type"] for part in result["content"]] == ["text"]
        return json.loads(result["content"][0]["text"])


@contextlib.asynccontextmanager
async def _make_kvm(  # pylint: disable=too-many-arguments
    streamer: (_FakeStreamer | None)=None,
    ocr: (_FakeOcr | None)=None,
    hid: (_FakeHid | None)=None,
    atx: (_FakeAtx | None)=None,
    msd: (_FakeMsd | None)=None,
    log_reader: Any=None,
) -> AsyncGenerator[_Kvm, None]:

    streamer = (streamer or _FakeStreamer())
    ocr = (ocr or _FakeOcr(["login:"]))
    hid = (hid or _FakeHid())
    atx = (atx or _FakeAtx())
    msd = (msd or _FakeMsd())

    api = McpApi(streamer, ocr, hid, atx, msd, _KEYMAP_PATH, log_reader)  # type: ignore
    server = _Server(api)
    async with TestClient(_TestServer(await server.make_app())) as client:
        yield _Kvm(client, streamer, ocr, hid, atx, msd)


# =====
@pytest.mark.asyncio
async def test_route_is_registered_as_a_normal_exposed_post() -> None:
    # Brief section 4: auth is inherited because this is a plain @exposed_http.
    api = McpApi(_FakeStreamer(), _FakeOcr(), _FakeHid(), _FakeAtx(), _FakeMsd(), _KEYMAP_PATH, None)  # type: ignore
    routes = [(item.method, item.path, item.auth_required) for item in _get_exposed_http(api)]
    assert routes == [("POST", "/mcp", True)]


@pytest.mark.asyncio
async def test_initialize_and_ping() -> None:
    async with _make_kvm() as kvm:
        result = await kvm.ok("initialize", {"protocolVersion": "2025-06-18", "clientInfo": {"name": "t"}})
        assert result["protocolVersion"] == "2025-06-18"
        assert result["capabilities"] == {"tools": {}, "resources": {}}
        assert result["serverInfo"] == {"name": "kvmd-mcp", "version": __version__}

        # An unknown revision falls back to one this server actually speaks.
        result = await kvm.ok("initialize", {"protocolVersion": "1999-01-01"})
        assert result["protocolVersion"] in mcp_module._PROTOCOL_VERSIONS  # pylint: disable=protected-access

        assert (await kvm.ok("ping")) == {}


@pytest.mark.asyncio
async def test_tools_list() -> None:
    async with _make_kvm() as kvm:
        tools = (await kvm.ok("tools/list"))["tools"]
        names = [tool["name"] for tool in tools]
        assert names == [
            "see", "read", "wait_for", "type", "keys", "key", "click", "move", "wheel",
            "power", "press", "wake", "fetch_iso", "mount", "unmount", "remove_image", "state",
        ]
        assert len(names) == 17
        for tool in tools:
            assert tool["description"].strip()
            assert tool["inputSchema"]["type"] == "object"
            assert isinstance(tool["inputSchema"]["properties"], dict)


@pytest.mark.asyncio
async def test_resources_list_and_read_frame() -> None:
    async with _make_kvm() as kvm:
        resources = (await kvm.ok("resources/list"))["resources"]
        assert [item["uri"] for item in resources] == ["kvm://frame", "kvm://log"]

        contents = (await kvm.ok("resources/read", {"uri": "kvm://frame"}))["contents"]
        assert contents[0]["mimeType"] == "image/jpeg"
        assert base64.b64decode(contents[0]["blob"]) == _FRAME

        assert (await kvm.error("resources/read", {"uri": "kvm://nope"}))["code"] == mcp_module._E_PARAMS  # pylint: disable=protected-access
        # No LogReader was given to this instance.
        assert "LogReader is disabled" in (await kvm.error("resources/read", {"uri": "kvm://log"}))["message"]


@pytest.mark.asyncio
async def test_resources_read_log(tmp_path: Any) -> None:
    # The REAL LogReader, pointed at a temp file.  Its constructor attaches a
    # RotatingFileHandler to the global "kvmd" logger (logreader.py:36-44), so
    # it has to be detached again or it would follow the whole session.
    path = str(tmp_path / "kvmd.log")
    open(path, "w").close()  # pylint: disable=consider-using-with
    reader = LogReader(log_file=path)
    try:
        reader.logger.info("hello from the log")
        # server.py:446-447 writes raw lines that __line_to_record cannot parse;
        # they come back as {} and must be skipped, not crash the reader.
        with open(path, "a") as file:
            file.write("this line has no timestamp fields\n")
        async with _make_kvm(log_reader=reader) as kvm:
            contents = (await kvm.ok("resources/read", {"uri": "kvm://log"}))["contents"]
            assert contents[0]["mimeType"] == "text/plain"
            text = contents[0]["text"]
            assert "hello from the log" in text
            assert "this line has no timestamp fields" not in text
    finally:
        for handler in list(reader.logger.handlers):
            reader.logger.removeHandler(handler)
            handler.close()


# ===== JSON-RPC error paths

@pytest.mark.asyncio
async def test_parse_error() -> None:
    async with _make_kvm() as kvm:
        (status, text) = await kvm.post("{not json at all")
        assert status == 200
        envelope = json.loads(text)
        assert envelope["id"] is None
        assert envelope["error"]["code"] == -32700
        assert "Parse error" in envelope["error"]["message"]


@pytest.mark.asyncio
async def test_batch_is_rejected() -> None:
    async with _make_kvm() as kvm:
        (status, text) = await kvm.post(json.dumps([{"jsonrpc": "2.0", "id": 1, "method": "ping"}]))
        assert status == 200
        envelope = json.loads(text)
        assert envelope["error"]["code"] == -32600
        assert "Batch" in envelope["error"]["message"]


@pytest.mark.asyncio
async def test_invalid_request_shapes() -> None:
    async with _make_kvm() as kvm:
        for body in ["7", '"hello"', "null"]:
            envelope = json.loads((await kvm.post(body))[1])
            assert envelope["error"]["code"] == -32600, body
        # A non-string method and a non-object params are both bad envelopes.
        envelope = json.loads((await kvm.post(json.dumps({"jsonrpc": "2.0", "id": 3, "method": 9})))[1])
        assert envelope["error"]["code"] == -32600
        assert envelope["id"] == 3
        envelope = json.loads((await kvm.post(json.dumps({"jsonrpc": "2.0", "id": 4, "method": "ping", "params": 5})))[1])
        assert envelope["error"]["code"] == -32600


@pytest.mark.asyncio
async def test_unknown_method() -> None:
    async with _make_kvm() as kvm:
        error = await kvm.error("frobnicate/now")
        assert error["code"] == -32601
        assert "frobnicate/now" in error["message"]


@pytest.mark.asyncio
async def test_bad_params() -> None:
    async with _make_kvm() as kvm:
        for params in [{"name": 1}, {"name": "see", "arguments": []}, {}]:
            error = await kvm.error("tools/call", params)
            assert error["code"] == -32602, params
        error = await kvm.error("tools/call", {"name": "frobnicate"})
        assert error["code"] == -32602
        assert "Unknown tool" in error["message"]


@pytest.mark.asyncio
async def test_notification_gets_no_jsonrpc_response() -> None:
    async with _make_kvm() as kvm:
        for method in ["notifications/initialized", "notifications/cancelled"]:
            (status, text) = await kvm.post(json.dumps({"jsonrpc": "2.0", "method": method}))
            # A notification must not be answered with a JSON-RPC response
            # object -- and MCP streamable-HTTP wants no body at all.
            assert status == 202
            assert text == ""


@pytest.mark.asyncio
async def test_notification_is_202_with_empty_body() -> None:
    async with _make_kvm() as kvm:
        async with kvm.client.post("/mcp", data=json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"})) as resp:
            body = await resp.text()
            assert resp.status == 202
            assert body == ""


@pytest.mark.asyncio
async def test_notification_errors_are_swallowed_not_answered() -> None:
    # JSON-RPC 2.0 section 4.1: a message with no `id` gets no answer, not
    # even an error one -- an unsolicited {"id": null, "error": ...} is a
    # response to something that was never a request.
    async with _make_kvm() as kvm:
        for request in [
            {"jsonrpc": "2.0", "method": "frobnicate/now"},                                    # -32601
            {"jsonrpc": "2.0", "method": "resources/read", "params": {"uri": "kvm://nope"}},    # -32602
        ]:
            (status, text) = await kvm.post(json.dumps(request))
            assert status == 202, text
            assert text == ""


@pytest.mark.asyncio
async def test_explicit_null_id_is_a_request_not_a_notification() -> None:
    # {"id": null} is a malformed request, but it IS a request: answering it
    # with 202 would leave a caller that sent one waiting forever.
    async with _make_kvm() as kvm:
        (status, text) = await kvm.post(json.dumps({"jsonrpc": "2.0", "id": None, "method": "ping"}))
        assert status == 200
        assert json.loads(text) == {"jsonrpc": "2.0", "id": None, "result": {}}


@pytest.mark.asyncio
async def test_body_size_cap() -> None:
    async with _make_kvm() as kvm:
        # Just under the cap, with a Content-Length: accepted.
        under = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping", "params": {"pad": "x" * 60000}})
        assert len(under) < mcp_module._MAX_BODY  # pylint: disable=protected-access
        envelope = json.loads((await kvm.post(under))[1])
        assert envelope["result"] == {}

        # Over the cap with a Content-Length: rejected by the pre-check.
        over = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping", "params": {"pad": "x" * 70000}})
        assert len(over) > mcp_module._MAX_BODY  # pylint: disable=protected-access
        (status, text) = await kvm.post(over)
        assert status == 200
        envelope = json.loads(text)
        assert envelope["error"]["code"] == -32600
        assert "larger than" in envelope["error"]["message"]

        # Over the cap WITHOUT a Content-Length (chunked): rejected while streaming.
        async def chunks() -> AsyncGenerator[bytes, None]:
            yield b'{"jsonrpc": "2.0", "id": 1, "method": "ping", "params": {"pad": "'
            for _ in range(10):
                yield b"x" * 8192
            yield b'"}}'
        (status, text) = await kvm.post(chunks())
        assert status == 200
        assert json.loads(text)["error"]["code"] == -32600


# ===== Logging

@pytest.mark.asyncio
async def test_log_line_redacts_typed_text(caplog: Any) -> None:
    caplog.set_level(logging.INFO)
    async with _make_kvm() as kvm:
        secret = "hunter2-correct-horse"
        assert (await kvm.payload("type", {"text": secret}))["len"] == len(secret)
    lines = [record.getMessage() for record in caplog.records if record.getMessage().startswith("mcp ")]
    assert len(lines) == 1
    assert secret not in caplog.text
    assert f"len={len(secret)}" in lines[0]
    assert " type args=" in lines[0]
    assert " ok=True" in lines[0]


@pytest.mark.asyncio
async def test_log_line_redacts_url_to_host(caplog: Any) -> None:
    caplog.set_level(logging.INFO)
    async with _make_kvm() as kvm:
        assert "not a valid HTTP(S) URL" in (await kvm.call_err("fetch_iso", {"url": "ftp://nas.lan/isos/secret-path.iso"}))
    lines = [record.getMessage() for record in caplog.records if record.getMessage().startswith("mcp ")]
    assert len(lines) == 1
    # The args= field itself keeps only the host (brief section 6).
    assert 'args={"url": "nas.lan"}' in lines[0]
    assert " ok=False" in lines[0]


@pytest.mark.asyncio
async def test_log_line_never_leaks_url_credentials(caplog: Any) -> None:
    caplog.set_level(logging.INFO)
    async with _make_kvm() as kvm:
        # An unusable scheme, so it fails in valid_url before any I/O.
        await kvm.call_err("fetch_iso", {"url": "ftp://admin:hunter2@nas.lan/isos/secret-path.iso"})
    lines = [record.getMessage() for record in caplog.records if record.getMessage().startswith("mcp ")]
    assert len(lines) == 1
    assert "hunter2" not in lines[0]
    assert "secret-path.iso" not in lines[0]


@pytest.mark.asyncio
async def test_successful_fetch_iso_never_leaks_url_credentials(monkeypatch: Any, caplog: Any) -> None:
    # The happy path logs its own progress line before the transfer starts, and
    # that line must obey the same host-only rule as the per-call line: the
    # module hands /var/log/kvmd.log back to any authenticated client through
    # kvm://log, and api/upgrade.py:135 ships it in the diagnostics bundle.
    caplog.set_level(logging.INFO)
    data = b"ISO" * 100
    async with _make_kvm() as kvm:
        with _patched_download(monkeypatch, _FakeRemote(data, "/isos/secret-path.iso")):
            payload = await kvm.payload("fetch_iso", {
                "url": "https://admin:hunter2@nas.lan/isos/secret-path.iso",
                "image": "u.iso",
            })
    assert payload == {"name": "u.iso", "size": len(data), "written": len(data)}
    assert "hunter2" not in caplog.text
    assert "admin" not in caplog.text
    assert "secret-path.iso" not in caplog.text
    # The host itself is still logged, so the line stays useful.
    assert "nas.lan" in caplog.text


@pytest.mark.asyncio
async def test_log_line_reports_the_client_ip_from_the_nginx_header(caplog: Any) -> None:
    # kvmd listens on a unix socket, so req.remote is empty and the IP can only
    # come from the headers nginx sets (server.py:548-550).
    caplog.set_level(logging.INFO)
    async with _make_kvm() as kvm:
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                           "params": {"name": "state", "arguments": {}}})
        (status, _) = await kvm.post(body, headers={"X-Real-IP": "10.0.0.9"})
        assert status == 200
    lines = [record.getMessage() for record in caplog.records if record.getMessage().startswith("mcp ")]
    assert lines[0].startswith("mcp 10.0.0.9 state args=")


def test_redact_args_unit() -> None:
    redacted = json.loads(mcp_module._redact_args({  # pylint: disable=protected-access
        "text": "swordfish",
        "url": "https://nas.lan:8080/isos/ubuntu.iso",
        "passwd": "letmein",
        "mode": "full",
    }))
    assert redacted == {"text": "len=9", "url": "nas.lan", "passwd": "***", "mode": "full"}


# ===== Tools

@pytest.mark.asyncio
async def test_tool_see() -> None:
    async with _make_kvm() as kvm:
        result = await kvm.call_ok("see", {"mode": "full"})
        assert [part["type"] for part in result["content"]] == ["image", "text", "text"]
        assert result["content"][0]["mimeType"] == "image/jpeg"
        # mode=full with no max_width hands back ustreamer's own bytes untouched.
        data = base64.b64decode(result["content"][0]["data"])
        assert data == _FRAME
        assert result["content"][1]["text"] == f"{_SRC_WIDTH}x{_SRC_HEIGHT}"
        assert result["content"][2]["text"] == f"online=True source={_SRC_WIDTH}x{_SRC_HEIGHT}"
        # The snapshot must be live and offline-tolerant, never the cached one.
        assert kvm.streamer.snapshot_calls[-1] == {"save": False, "load": False, "allow_offline": True}

        # preview: the reported size is MEASURED from the produced JPEG.
        result = await kvm.call_ok("see", {"mode": "preview", "max_width": 320, "quality": 80.0})
        data = base64.b64decode(result["content"][0]["data"])
        assert _jpeg_size(data) == (320, 240)
        assert result["content"][1]["text"] == "320x240"
        assert len(data) < len(_FRAME)

        # region: cropped to the box, right/bottom exclusive.
        result = await kvm.call_ok("see", {"mode": "region", "box": [10, 20, 110, 120]})
        assert _jpeg_size(base64.b64decode(result["content"][0]["data"])) == (100, 100)
        assert result["content"][1]["text"] == "100x100"

        assert "requires a 'box'" in (await kvm.call_err("see", {"mode": "region"}))
        assert "not a valid see mode" in (await kvm.call_err("see", {"mode": "sideways"}))
        assert "does not intersect" in (await kvm.call_err("see", {"mode": "region", "box": [5000, 5000, 6000, 6000]}))
        assert "must satisfy left < right" in (await kvm.call_err("see", {"mode": "region", "box": [10, 10, 10, 20]}))


@pytest.mark.asyncio
async def test_tool_see_reports_offline_and_missing_streamer() -> None:
    async with _make_kvm(streamer=_FakeStreamer(online=False)) as kvm:
        result = await kvm.call_ok("see")
        assert result["content"][2]["text"] == f"online=False source={_SRC_WIDTH}x{_SRC_HEIGHT}"
    async with _make_kvm(streamer=_FakeStreamer(broken=True)) as kvm:
        assert "No snapshot available" in (await kvm.call_err("see"))


@pytest.mark.asyncio
async def test_tool_read() -> None:
    ocr = _FakeOcr(["  Ubuntu 22.04 LTS  login:  "], use_rknn=True)
    async with _make_kvm(ocr=ocr) as kvm:
        result = await kvm.call_ok("read")
        assert result["content"] == [{"type": "text", "text": "  Ubuntu 22.04 LTS  login:  "}]
        # No box -> the per-edge "unset" sentinel (-1), not (0, 0, 0, 0).
        assert ocr.calls[-1]["box"] == (-1, -1, -1, -1)
        # Under RKNN the OCR service grabs its own frame, so no snapshot is taken
        # and no bytes are handed over (ocr.py:252-254).
        assert ocr.calls[-1]["data"] == b""
        assert ocr.calls[-1]["langs"] == []
        assert kvm.streamer.snapshot_calls == []

        await kvm.call_ok("read", {"box": [10, 20, 110, 120]})
        assert ocr.calls[-1]["box"] == (10, 20, 110, 120)
        assert "must be a list of four" in (await kvm.call_err("read", {"box": [1, 2]}))

    # The tesseract branch is the only one that reads `data`.
    ocr = _FakeOcr(["tess text"], use_rknn=False)
    async with _make_kvm(ocr=ocr) as kvm:
        await kvm.call_ok("read")
        assert ocr.calls[-1]["data"] == _FRAME
        assert kvm.streamer.snapshot_calls[-1]["allow_offline"] is True


@pytest.mark.asyncio
async def test_tool_wait_for_returns_after_stable_frames() -> None:
    ocr = _FakeOcr(["Booting...", "  LOGIN:  ", "login: root"])
    async with _make_kvm(ocr=ocr) as kvm:
        started = time.monotonic()
        result = await kvm.call_ok("wait_for", {"text": "Login:", "timeout_s": 20, "every_s": 1, "stable_frames": 2})
        elapsed = time.monotonic() - started
        # Poll 1 misses, polls 2 and 3 both match after normalisation.
        assert len(ocr.calls) == 3
        assert result["content"][0]["text"] == "login: root"
        assert json.loads(result["content"][1]["text"]) == {
            "found": True, "polls": 3, "errors": 0, "stable_frames": 2}
        # It slept between polls instead of spinning, and did not sleep after the hit.
        assert 1.5 < elapsed < 10


@pytest.mark.asyncio
async def test_tool_wait_for_times_out() -> None:
    ocr = _FakeOcr(["kernel panic"])
    async with _make_kvm(ocr=ocr) as kvm:
        started = time.monotonic()
        message = await kvm.call_err("wait_for", {"text": "login:", "timeout_s": 2, "every_s": 1})
        elapsed = time.monotonic() - started
        assert "Timed out after 2s" in message
        assert "kernel panic" in message  # the last text comes back with the failure
        assert 1.5 < elapsed < 10
        assert len(ocr.calls) >= 2


@pytest.mark.asyncio
async def test_tool_wait_for_ignores_a_flapping_match() -> None:
    # A half-rendered screen that matches once, then stops matching, must NOT
    # satisfy stable_frames=2 (brief section 5).
    ocr = _FakeOcr(["login:", "", "login:", "", "login:", ""])
    async with _make_kvm(ocr=ocr) as kvm:
        message = await kvm.call_err("wait_for", {"text": "login:", "timeout_s": 4, "every_s": 1, "stable_frames": 2})
        assert "Timed out" in message
        # It really did keep polling, and the needle really was on screen more
        # than once -- it just never held for two consecutive reads.
        assert len(ocr.calls) >= 4
        seen = [ocr.texts[min(index, len(ocr.texts) - 1)] for index in range(len(ocr.calls))]
        assert seen.count("login:") >= 2
        # With stable_frames=1 the very same sequence returns on the first poll.
    ocr = _FakeOcr(["login:", "", "login:"])
    async with _make_kvm(ocr=ocr) as kvm:
        result = await kvm.call_ok("wait_for", {"text": "login:", "timeout_s": 4, "every_s": 1, "stable_frames": 1})
        assert json.loads(result["content"][1]["text"])["polls"] == 1


@pytest.mark.asyncio
async def test_tool_wait_for_validates_its_bounds() -> None:
    async with _make_kvm() as kvm:
        assert "timeout_s" in (await kvm.call_err("wait_for", {"text": "x", "timeout_s": 901}))
        assert "every_s" in (await kvm.call_err("wait_for", {"text": "x", "every_s": 0.5}))
        assert "non-empty string" in (await kvm.call_err("wait_for", {"text": "   "}))
        assert "Missing required argument 'text'" in (await kvm.call_err("wait_for", {}))


@pytest.mark.asyncio
async def test_tool_type() -> None:
    async with _make_kvm() as kvm:
        payload = await kvm.payload("type", {"text": "hello"})
        assert payload["len"] == 5
        # ~2 events per character: press and release.
        assert payload["events"] == len(kvm.hid.events) == 10
        assert [event[0] for event in kvm.hid.events] == ["key"] * 10
        assert kvm.hid.events[0][2] is True
        assert kvm.hid.events[1][2] is False

        # A character the keymap cannot produce is dropped by kvmd itself, so
        # `events` is the only honest report of what was sent.
        kvm.hid.events.clear()
        payload = await kvm.payload("type", {"text": "\x01\x02\x03"})
        assert payload["len"] == 3
        assert payload["events"] == 0

        assert "at most 4096" in (await kvm.call_err("type", {"text": "x" * 4097}))
        # The keymap name is a file name, never a path.
        assert "not a valid keymap" in (await kvm.call_err("type", {"text": "x", "keymap": "../../../etc/passwd"}))
        assert "not a valid keymap" in (await kvm.call_err("type", {"text": "x", "keymap": "nonexistent-keymap"}))


@pytest.mark.asyncio
async def test_tool_keys() -> None:
    async with _make_kvm() as kvm:
        assert (await kvm.payload("keys", {"chord": ["ControlLeft", "AltLeft", "Delete"]})) == {}
        (ctrl, alt, delete) = (WEB_TO_EVDEV["ControlLeft"], WEB_TO_EVDEV["AltLeft"], WEB_TO_EVDEV["Delete"])
        # Pressed in order, released in reverse.
        assert kvm.hid.events == [
            ("key", ctrl, True), ("key", alt, True), ("key", delete, True),
            ("key", delete, False), ("key", alt, False), ("key", ctrl, False),
        ]
        # DOM KeyboardEvent.code is case-sensitive (validators/hid.py:46-47).
        assert "not a valid Keyboard key" in (await kvm.call_err("keys", {"chord": ["ctrl"]}))
        assert "at most 6 keys" in (await kvm.call_err("keys", {"chord": ["KeyA"] * 7}))
        assert "non-empty list" in (await kvm.call_err("keys", {"chord": []}))


@pytest.mark.asyncio
async def test_tool_key() -> None:
    async with _make_kvm() as kvm:
        enter = WEB_TO_EVDEV["Enter"]
        assert (await kvm.payload("key", {"name": "Enter"})) == {}
        # No `down` -> a tap: the base class auto-releases (plugins/hid/__init__.py:171-174).
        assert kvm.hid.events == [("key", enter, True), ("key", enter, False)]

        kvm.hid.events.clear()
        shift = WEB_TO_EVDEV["ShiftLeft"]
        await kvm.payload("key", {"name": "ShiftLeft", "down": True})
        await kvm.payload("key", {"name": "ShiftLeft", "down": False})
        assert kvm.hid.events == [("key", shift, True), ("key", shift, False)]
        assert "not a valid Keyboard key" in (await kvm.call_err("key", {"name": "enter"}))


@pytest.mark.asyncio
async def test_tool_click() -> None:
    async with _make_kvm() as kvm:
        assert (await kvm.payload("click", {"fx": 0.5, "fy": 0.5})) == {}
        left = MOUSE_TO_EVDEV["left"]
        assert kvm.hid.events == [("move", 0, 0), ("button", left, True), ("button", left, False)]

        kvm.hid.events.clear()
        await kvm.payload("click", {"fx": 0, "fy": 1, "button": "right"})
        assert kvm.hid.events[0] == ("move", MouseRange.MIN, MouseRange.MAX)
        assert kvm.hid.events[1][1] == MOUSE_TO_EVDEV["right"]

        # The fraction is range-checked here, because valid_hid_mouse_move
        # silently CLAMPS instead of rejecting (validators/hid.py:50-53).
        assert "lesser or equal then 1" in (await kvm.call_err("click", {"fx": 1.5, "fy": 0}))
        # (The fork's own message has a typo -- "equial" -- quoted here as it really is.)
        assert "greater or equial than 0" in (await kvm.call_err("click", {"fx": -0.1, "fy": 0}))
        assert "Missing required argument 'fy'" in (await kvm.call_err("click", {"fx": 0.5}))


@pytest.mark.asyncio
async def test_tool_move() -> None:
    async with _make_kvm() as kvm:
        assert (await kvm.payload("move", {"fx": 1, "fy": 0})) == {}
        assert kvm.hid.events == [("move", MouseRange.MAX, MouseRange.MIN)]

    # A relative-mode mouse drops absolute moves on the floor
    # (plugins/hid/__init__.py:201-203), so the tool must refuse.
    async with _make_kvm(hid=_FakeHid(absolute=False)) as kvm:
        assert "relative mode" in (await kvm.call_err("move", {"fx": 0.5, "fy": 0.5}))
        assert "relative mode" in (await kvm.call_err("click", {"fx": 0.5, "fy": 0.5}))
        assert kvm.hid.events == []


@pytest.mark.asyncio
async def test_tool_wheel() -> None:
    async with _make_kvm() as kvm:
        assert (await kvm.payload("wheel", {"delta_y": -5})) == {}
        assert kvm.hid.events == [("wheel", 0, -5)]
        kvm.hid.events.clear()
        # MouseDelta clamps at +-127 (validators/hid.py:59-61).
        await kvm.payload("wheel", {"delta_y": 5000})
        assert kvm.hid.events == [("wheel", 0, 127)]
        assert "Missing required argument 'delta_y'" in (await kvm.call_err("wheel", {}))


@pytest.mark.asyncio
async def test_tool_power() -> None:
    async with _make_kvm() as kvm:
        assert (await kvm.payload("power", {"action": "reset_hard"})) == {"action": "reset_hard", "wait": False}
        assert kvm.atx.actions == [("power_reset_hard", False)]
        await kvm.payload("power", {"action": "on"})
        await kvm.payload("power", {"action": "off_hard"})
        assert kvm.atx.actions[1:] == [("power_on", False), ("power_off_hard", False)]
        assert "not a valid ATX power action" in (await kvm.call_err("power", {"action": "nuke"}))

        # The glatx wait=True fork bug must surface as a readable tool error,
        # not as a bare 500 (htserver.py:427-432 does not catch TypeError).
        message = await kvm.call_err("power", {"action": "on", "wait": True})
        assert "wait=true is unsupported" in message
        assert "glatx.py:113" in message

    # On a plugin where wait works, it is passed straight through.
    async with _make_kvm(atx=_FakeAtx(broken_wait=False)) as kvm:
        assert (await kvm.payload("power", {"action": "on", "wait": True}))["wait"] is True
        assert kvm.atx.actions == [("power_on", True)]


@pytest.mark.asyncio
async def test_tool_press() -> None:
    async with _make_kvm() as kvm:
        assert (await kvm.payload("press", {"button": "power_long"})) == {"button": "power_long", "wait": False}
        await kvm.payload("press", {"button": "power"})
        await kvm.payload("press", {"button": "reset"})
        assert kvm.atx.actions == [("click_power_long", False), ("click_power", False), ("click_reset", False)]
        assert "not a valid ATX button" in (await kvm.call_err("press", {"button": "eject"}))


@pytest.mark.asyncio
async def test_tool_wake(monkeypatch: Any, tmp_path: Any) -> None:
    sent: list[list[str]] = []

    async def fake_run_process(cmd: Any, **kwargs: Any) -> str:
        _ = kwargs
        sent.append(list(cmd))
        if "ff:ff:ff:ff:ff:ff" in cmd:
            raise RuntimeError("ether-wake: no such interface")
        return ""

    monkeypatch.setattr(wol_module, "run_process", fake_run_process)

    wol_list = tmp_path / "wol_list.json"
    wol_list.write_text(json.dumps({"devices": [
        {"name": "pve1", "mac": "AA:BB:CC:DD:EE:FF", "ip": "10.0.0.5"},
        {"name": "dup", "mac": "11:22:33:44:55:66", "ip": ""},
        {"name": "dup", "mac": "77:88:99:AA:BB:CC", "ip": ""},
    ]}))
    monkeypatch.setattr(mcp_module, "_WOL_LIST_PATH", str(wol_list))

    async with _make_kvm() as kvm:
        payload = await kvm.payload("wake", {"mac": "AA:BB:CC:DD:EE:FF"})
        assert payload["mac"] == "AA:BB:CC:DD:EE:FF"
        # Unlike POST /wol/wake, which throws the booleans away (api/wol.py:145-150).
        assert set(payload["sent"]) >= {"eth0"}
        assert all(payload["sent"].values())
        assert sent[0][:2] == ["ether-wake", "-i"]

        # Resolution by name from the saved list.
        assert (await kvm.payload("wake", {"name": "pve1"}))["mac"] == "AA:BB:CC:DD:EE:FF"
        assert "No WOL device named 'nope'" in (await kvm.call_err("wake", {"name": "nope"}))
        assert "Ambiguous WOL device name 'dup'" in (await kvm.call_err("wake", {"name": "dup"}))

        assert "either 'mac' or 'name'" in (await kvm.call_err("wake", {}))
        assert "Invalid MAC address format" in (await kvm.call_err("wake", {"mac": "not-a-mac"}))
        # Every interface failed -> the tool reports the failure.
        assert "Failed to send a WOL packet" in (await kvm.call_err("wake", {"mac": "ff:ff:ff:ff:ff:ff"}))


@pytest.mark.asyncio
async def test_tool_fetch_iso(monkeypatch: Any) -> None:
    data = b"ISO" * 5000
    async with _make_kvm() as kvm:
        with _patched_download(monkeypatch, _FakeRemote(data, "/isos/ubuntu-24.04.iso")) as calls:
            payload = await kvm.payload("fetch_iso", {"url": "https://nas.lan/isos/ubuntu-24.04.iso"})
        assert payload == {"name": "ubuntu-24.04.iso", "size": len(data), "written": len(data)}
        assert kvm.msd.written["ubuntu-24.04.iso"] == data
        assert ("write_image", "ubuntu-24.04.iso", len(data), None) in kvm.msd.calls
        # The REST route's own 7-day read timeout (api/msd.py:269).
        assert calls[0]["read_timeout"] == 7 * 24 * 3600
        assert calls[0]["verify"] is True

        with _patched_download(monkeypatch, _FakeRemote(data, "/isos/ubuntu-24.04.iso")) as calls:
            payload = await kvm.payload("fetch_iso", {
                "url": "https://nas.lan/isos/ubuntu-24.04.iso",
                "image": "renamed.iso",
                "insecure": True,
            })
        assert payload["name"] == "renamed.iso"
        assert calls[0]["verify"] is False

        assert "not a valid HTTP(S) URL" in (await kvm.call_err("fetch_iso", {"url": "ftp://nas.lan/x.iso"}))

        # A chunked remote (no Content-Length) is refused, as in api/msd.py:277.
        remote = _FakeRemote(data, "/isos/x.iso")
        remote.content_length = None  # type: ignore
        with _patched_download(monkeypatch, remote):
            assert "not a valid int" in (await kvm.call_err("fetch_iso", {"url": "https://nas.lan/isos/x.iso"}))

    # Not enough free space on the MSD.
    async with _make_kvm(msd=_FakeMsd(free=10)) as kvm:
        with _patched_download(monkeypatch, _FakeRemote(data, "/isos/big.iso")):
            assert "space" in (await kvm.call_err("fetch_iso", {"url": "https://nas.lan/isos/big.iso"})).lower()
        assert kvm.msd.written == {}


@pytest.mark.asyncio
async def test_tool_mount() -> None:
    async with _make_kvm() as kvm:
        assert (await kvm.payload("mount", {"image": "ubuntu.iso"})) == {"image": "ubuntu.iso", "cdrom": True, "rw": False}
        assert kvm.msd.calls == [("set_params", "ubuntu.iso", True, False), ("set_connected", True)]
        assert kvm.msd.connected is True

        # Already connected: set_params would raise MsdConnectedError
        # (otg/__init__.py:396), so the drive is disconnected first.
        kvm.msd.calls.clear()
        payload = await kvm.payload("mount", {"image": "ubuntu.iso", "rw": True})
        assert kvm.msd.calls == [("set_connected", False), ("set_params", "ubuntu.iso", False, True), ("set_connected", True)]
        # cdrom and rw are mutually exclusive with last-one-wins
        # (otg/__init__.py:404-412); the resolved flags are echoed back.
        assert payload == {"image": "ubuntu.iso", "cdrom": False, "rw": True}

        # An empty name would DESELECT the image instead of erroring.
        assert "not a valid MSD mount name" in (await kvm.call_err("mount", {"image": "   "}))
        assert "Missing required argument 'image'" in (await kvm.call_err("mount", {}))


@pytest.mark.asyncio
async def test_tool_unmount() -> None:
    async with _make_kvm(msd=_FakeMsd(connected=True)) as kvm:
        assert (await kvm.payload("unmount")) == {}
        assert kvm.msd.calls == [("set_connected", False)]
        assert kvm.msd.connected is False


@pytest.mark.asyncio
async def test_tool_remove_image() -> None:
    async with _make_kvm() as kvm:
        assert (await kvm.payload("remove_image", {"image": "ubuntu.iso"})) == {"image": "ubuntu.iso"}
        assert kvm.msd.removed == ["ubuntu.iso"]
        # valid_msd_image_name strips the leading slash (validators/kvm.py:59-67).
        assert (await kvm.payload("remove_image", {"image": "/ubuntu.iso"}))["image"] == "ubuntu.iso"
        assert "not a valid MSD image name" in (await kvm.call_err("remove_image", {"image": " "}))


@pytest.mark.asyncio
async def test_tool_state() -> None:
    async with _make_kvm(msd=_FakeMsd(connected=True)) as kvm:
        state = await kvm.payload("state")
        assert sorted(state) == ["atx", "hid", "kvmd", "msd", "ocr", "streamer"]
        assert state["atx"] == {"enabled": True, "busy": False, "power": "on",
                                "leds": {"power": False, "hdd": False}}
        assert state["msd"]["connected"] is True
        assert state["msd"]["images"] == ["ubuntu.iso"]
        assert state["streamer"] == {
            "online": True,
            "resolution": {"width": _SRC_WIDTH, "height": _SRC_HEIGHT},
            "running": True,
        }
        assert state["hid"]["mouse_absolute"] is True
        assert state["ocr"] == {"enabled": True, "engine": "rknn"}
        assert state["kvmd"] == {"version": __version__}

    # ustreamer is not running: every field is nullable, nothing raises.
    async with _make_kvm(streamer=_FakeStreamer(running=False)) as kvm:
        state = await kvm.payload("state")
        assert state["streamer"] == {"online": None, "resolution": {"width": None, "height": None}, "running": False}


# ===== Routine conditions must not be reported as server malfunctions

@pytest.mark.asyncio
async def test_resources_read_frame_with_no_snapshot(caplog: Any) -> None:
    # The streamer is only kept up while something needs it (server.py:682-684),
    # so an idle device answers every read of kvm://frame this way.  That is a
    # resource-level condition, not an internal error, and it must not write a
    # stack trace per call into the 512 KB rotating log this module also serves.
    caplog.set_level(logging.DEBUG)
    async with _make_kvm(streamer=_FakeStreamer(broken=True)) as kvm:
        error = await kvm.error("resources/read", {"uri": "kvm://frame"})
    assert error["code"] == mcp_module._E_PARAMS  # pylint: disable=protected-access
    assert error["code"] != mcp_module._E_INTERNAL  # pylint: disable=protected-access
    assert "No snapshot available" in error["message"]
    # The module-private exception class name must not leak to the client.
    assert "_ToolError" not in error["message"]
    assert [record for record in caplog.records if record.exc_info] == []


@pytest.mark.asyncio
async def test_resources_read_log_survives_an_unparseable_four_field_line(tmp_path: Any) -> None:
    # server.py:446-448 pipes webrtc_client's stderr verbatim into the same
    # file LogReader parses.  A raw line carrying three ' - ' separators splits
    # into four fields, so LogReader.__line_to_record takes the strptime path
    # and raises ValueError (logreader.py:62-70) instead of returning {} -- and
    # the generator cannot be resumed, so one such line used to make the whole
    # resource unreadable until the file rotated.
    path = str(tmp_path / "kvmd.log")
    open(path, "w").close()  # pylint: disable=consider-using-with
    reader = LogReader(log_file=path)
    try:
        reader.logger.info("before the raw line")
        with open(path, "a") as file:
            file.write("ice - gathering - state - complete\n")
            file.write("this line has no timestamp fields\n")
        reader.logger.info("after the raw line")
        async with _make_kvm(log_reader=reader) as kvm:
            text = (await kvm.ok("resources/read", {"uri": "kvm://log"}))["contents"][0]["text"]
        # Both real records survive; only the unparseable lines are dropped.
        assert "before the raw line" in text
        assert "after the raw line" in text
        assert "gathering" not in text
        assert "no timestamp fields" not in text
    finally:
        for handler in list(reader.logger.handlers):
            reader.logger.removeHandler(handler)
            handler.close()


@pytest.mark.asyncio
async def test_tool_mount_rejects_an_unknown_image_without_ejecting() -> None:
    # set_params resolves the name only INSIDE the plugin (otg/__init__.py:
    # 398-402), which is after the drive would have been disconnected -- so a
    # typo used to eject a running target's install media and then fail.
    async with _make_kvm(msd=_FakeMsd(connected=True)) as kvm:
        assert "Unknown image" in (await kvm.call_err("mount", {"image": "ubuntu-24.04-server.iso"}))
        assert kvm.msd.calls == []
        assert kvm.msd.connected is True

        # valid_msd_mount_name lets a /dev/... name through, but storage keys
        # only ever come from scanning the storage tree (msd/otg/storage.py:
        # 203-211), so it can never resolve -- and must not eject anything.
        assert "Unknown image" in (await kvm.call_err("mount", {"image": "/dev/sda1"}))
        assert kvm.msd.calls == []
        assert kvm.msd.connected is True


# ===== Lifecycle

@pytest.mark.asyncio
async def test_initialize_falls_back_to_the_newest_supported_revision() -> None:
    # The lifecycle spec: when the server does not support the revision the
    # client asked for it SHOULD answer with the latest one it does support.
    async with _make_kvm() as kvm:
        versions = mcp_module._PROTOCOL_VERSIONS  # pylint: disable=protected-access
        latest = max(versions)
        for wanted in [{"protocolVersion": "2026-03-01"}, {"protocolVersion": 7}, {}]:
            assert (await kvm.ok("initialize", wanted))["protocolVersion"] == latest, wanted
        # Every revision this server names is one it actually speaks.
        assert latest in versions


# ===== Disconnect handling

@pytest.mark.asyncio
async def test_type_stops_when_the_client_goes_away() -> None:
    # aiohttp leaves handler_cancellation False (htserver.py:403-411), so
    # nothing cancels a handler when the peer disconnects; without the
    # api/hid.py:180-190 watchdog an abandoned `type` keeps injecting
    # keystrokes into the target and a client retry interleaves with it.
    async with _make_kvm() as kvm:
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {
            "name": "type", "arguments": {"text": "x" * 400, "slow": True},
        }})
        # 400 chars * ~2 events * 30 ms = ~24 s of typing (hid/__init__.py:162-167).
        task = asyncio.ensure_future(kvm.post(body))
        await asyncio.sleep(0.5)
        assert kvm.hid.events, "the paste should have started"
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        # The watchdog polls req.transport every 50 ms.
        for _ in range(100):
            if kvm.hid.cleared:
                break
            await asyncio.sleep(0.05)
        assert kvm.hid.cleared == 1
        sent = len(kvm.hid.events)
        assert sent < 800, "it must not have typed the whole payload"
        await asyncio.sleep(0.3)
        assert len(kvm.hid.events) == sent, "no key event may be sent after the client is gone"


# ===== The see schema is the contract an agent plans against

@pytest.mark.asyncio
async def test_see_full_with_max_width_downscales_and_says_so() -> None:
    async with _make_kvm() as kvm:
        result = await kvm.call_ok("see", {"mode": "full", "max_width": 320})
        data = base64.b64decode(result["content"][0]["data"])
        assert _jpeg_size(data) == (320, 240)
        assert data != _FRAME
        assert result["content"][1]["text"] == "320x240"

        see = {tool["name"]: tool for tool in (await kvm.ok("tools/list"))["tools"]}["see"]
        published = json.dumps(see)
        assert "ignored by mode=full" not in published
        assert "max_width=0" in see["description"]
        assert "every mode" in published


# ===== Redaction on the failure path

@pytest.mark.asyncio
async def test_wait_for_timeout_never_logs_the_screen_or_the_needle(caplog: Any) -> None:
    caplog.set_level(logging.INFO)
    screen = "BitLocker recovery key 483920-119284-772201"
    needle = "login-prompt-that-never-comes"
    async with _make_kvm(ocr=_FakeOcr([screen])) as kvm:
        message = await kvm.call_err("wait_for", {"text": needle, "timeout_s": 1})
    # The caller asked, so the caller gets both back in the isError content.
    assert screen in message
    assert needle in message
    lines = [record.getMessage() for record in caplog.records if record.getMessage().startswith("mcp ")]
    assert len(lines) == 1
    # Neither reaches the log: it is persisted to eMMC, served back by
    # kvm://log, and swept into the diagnostics bundle (api/upgrade.py:135).
    assert "BitLocker" not in caplog.text
    assert "483920" not in caplog.text
    assert needle not in caplog.text
    assert f"text len={len(needle)}" in lines[0]
    assert " ok=False" in lines[0]


# =====
class _FlakyOcr(_FakeOcr):
    """An OCR that fails its first `fail_first` calls, then behaves normally.

    Models the real thing during a reboot: ocr_service's socket disappears
    while the target restarts, and ocr.py raises OcrError from
    _rknn_recognize_params (ocr.py:136-139) until it is back.
    """

    def __init__(self, texts: Iterable[str], fail_first: int) -> None:
        super().__init__(texts)
        self.fail_first = fail_first
        self.failures = 0

    async def recognize(self, data: bytes, langs: list[str], left: int, top: int, right: int, bottom: int) -> str:
        if self.failures < self.fail_first:
            self.failures += 1
            self.calls.append({"data": data, "langs": langs, "box": (left, top, right, bottom)})
            raise OcrError("ocr_service socket unavailable (/run/kvmd/ocr.sock): [Errno 2]")
        return (await super().recognize(data, langs, left, top, right, bottom))


@pytest.mark.asyncio
async def test_wait_for_survives_transient_ocr_failure() -> None:
    # The tool's whole purpose is watching a machine through a reboot, and OCR
    # is guaranteed to fail during one.  A transient failure must not end the
    # wait; it must be counted and retried until the deadline.
    ocr = _FlakyOcr(["login:"], fail_first=3)
    async with _make_kvm(ocr=ocr) as kvm:
        payload = await kvm.call_ok("wait_for", {
            "text": "login:", "timeout_s": 10, "every_s": 1, "stable_frames": 1})
    body = json.loads(payload["content"][1]["text"])
    assert body["found"] is True
    assert body["errors"] == 3
    assert body["polls"] == 4          # three failures, then the match
    assert ocr.failures == 3


@pytest.mark.asyncio
async def test_wait_for_failed_read_breaks_the_stable_frames_streak() -> None:
    # An unread screen is not a matching screen: a failure between two matches
    # must reset the streak, or stable_frames would certify a screen that was
    # never seen twice in a row.
    class _MatchFailMatch(_FakeOcr):
        def __init__(self) -> None:
            super().__init__(["login:"])
            self.n = 0

        async def recognize(self, data: bytes, langs: list[str],
                            left: int, top: int, right: int, bottom: int) -> str:
            self.n += 1
            if self.n == 2:
                raise OcrError("transient")
            return "login:"

    ocr = _MatchFailMatch()
    async with _make_kvm(ocr=ocr) as kvm:
        payload = await kvm.call_ok("wait_for", {
            "text": "login:", "timeout_s": 20, "every_s": 1, "stable_frames": 2})
    body = json.loads(payload["content"][1]["text"])
    # Without the reset this would have returned at poll 3 (match, fail, match).
    assert body["polls"] == 4
    assert body["errors"] == 1


@pytest.mark.asyncio
async def test_wait_for_reports_read_failures_on_timeout(caplog: Any) -> None:
    caplog.set_level(logging.INFO)

    class _AlwaysFails(_FakeOcr):
        async def recognize(self, data: bytes, langs: list[str],
                            left: int, top: int, right: int, bottom: int) -> str:
            raise OcrError("ocr_service socket unavailable")

    async with _make_kvm(ocr=_AlwaysFails()) as kvm:
        message = await kvm.call_err("wait_for", {"text": "login:", "timeout_s": 2, "every_s": 1})
    # It timed out rather than surfacing the first OCR error as the failure,
    # and it says why every read failed.
    assert "Timed out" in message
    assert "reads failed" in message
    assert "OcrError" in message
    lines = [record.getMessage() for record in caplog.records if record.getMessage().startswith("mcp ")]
    assert len(lines) == 1
    assert "errors=" in lines[0]


def test_log_tail_survives_an_undecodable_byte() -> None:
    # One bad byte in kvmd.log must not make kvm://log raise forever -- and the
    # failure would be logged to that same file, so it would amplify itself.
    with tempfile.NamedTemporaryFile(suffix=".log", delete=False) as file:
        file.write(b"2026-01-01 00:00:00,000 - kvmd - INFO - before\n")
        file.write(b"2026-01-01 00:00:01,000 - kvmd - INFO - bad \xff\xfe byte\n")
        file.write(b"2026-01-01 00:00:02,000 - kvmd - INFO - after\n")
        path = file.name
    try:
        text = mcp_module._log_tail(path, 100)  # pylint: disable=protected-access
    finally:
        os.unlink(path)
    assert "before" in text
    assert "after" in text
    assert "byte" in text


def test_redact_message_scrubs_url_credentials_it_did_not_match() -> None:
    # The value substitution only catches the URL exactly as the caller sent
    # it.  A validator that reformats before quoting -- here, lowercasing the
    # host -- slips past it, so the userinfo backstop has to catch it.
    args = {"url": "https://admin:hunter2@NAS.lan/iso/win.iso"}
    msg = "Invalid URL: https://admin:hunter2@nas.lan/iso/win.iso"
    out = mcp_module._redact_message(msg, args)  # pylint: disable=protected-access
    assert "hunter2" not in out
    assert "admin" not in out
    assert "<redacted>@" in out
    assert "nas.lan" in out          # the host itself is still useful in a log


def test_redact_message_leaves_short_values_alone() -> None:
    # Substituting a one-character value would rewrite every occurrence of that
    # character and protect nothing.
    out = mcp_module._redact_message("cannot type 'a' at offset a", {"text": "a"})  # pylint: disable=protected-access
    assert out == "cannot type 'a' at offset a"
