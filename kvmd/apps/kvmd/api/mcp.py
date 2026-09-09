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
MCP (Model Context Protocol) endpoint for kvmd: JSON-RPC 2.0 over a single
POST route, so an agent can drive the machine at the console with the same
primitives the REST API already exposes, plus `wait_for`, which would
otherwise be a polling loop over the network.

Device facts this module relies on, each verified in this tree.  Line numbers
are those of kvmd 4.82 (kvmd/__init__.py:23), the revision this was written
against; see _WRITTEN_AGAINST below.

Routing and transport
  - @exposed_http registers the path VERBATIM; there is no /api prefix in
    Python (kvmd/htserver.py:112-127).  POST /api/mcp reaches this handler
    only because nginx rewrites ^/api/(.*)$ -> /$1
    (configs/nginx/kvmd.ctx-server.conf:110-116).
  - auth_required defaults to True, so KvmdServer._check_request_auth ->
    check_request_auth gates this route exactly like /atx and /msd
    (kvmd/apps/kvmd/server.py:616, kvmd/apps/kvmd/api/auth.py:162).
    allow_usc also defaults True: a local process on the device can
    authenticate by SO_PEERCRED, same posture as every other route.
  - make_json_response() wraps its argument as {"ok":..., "result":...}
    (kvmd/htserver.py:181-195).  A JSON-RPC body must NOT be wrapped, so
    every response here passes wrap_result=False -- the same escape hatch
    api/redfish.py:77 uses.
  - The htserver route wrapper catches only IsBusyError, ValidatorError,
    OperationError and HttpError (kvmd/htserver.py:422-433).  Anything else
    escapes as a bare 500 with no JSON envelope, so this module catches
    broadly and converts to JSON-RPC / tool errors itself.
  - nginx caps request bodies at 4 KB globally (configs/nginx/nginx.conf.mako:28)
    and `location /api` does not include loc-bigpost.conf, so the brief's
    64 KB body cap is enforced here but is NOT reachable through nginx --
    keep `type` payloads under ~3.5 KB per call, or give /api/mcp its own
    nginx location.  Likewise `location /api` sets no proxy_read_timeout, so
    nginx cuts requests at its 60 s default: `wait_for` timeout_s and
    `fetch_iso` are bounded by that in practice.
  - The client IP is only available from the headers nginx sets; kvmd listens
    on an AF_UNIX socket, so req.remote is empty (kvmd/htserver.py:397-399).
    The idiom below is copied from kvmd/apps/kvmd/server.py:548-550.

Streamer / snapshots
  - Streamer.take_snapshot(save, load, allow_offline) takes three REQUIRED
    positional-or-keyword args and NEVER raises: every failure -- offline,
    connection refused, unparseable response -- returns None
    (kvmd/apps/kvmd/streamer.py:428-445).  None is the only failure signal.
  - load=True short-circuits to the cached saved snapshot without touching
    ustreamer (streamer.py:429-430), so it is never used here.
  - "No signal" is not an error: ustreamer serves a placeholder JPEG with
    X-UStreamer-Online: false.  `see` passes allow_offline=True so the agent
    can look at a blank console, and reports `online` alongside the image.
  - StreamerSnapshot has exactly five fields (online, width, height, headers,
    data) and .width/.height describe the SOURCE frame, not anything this
    module re-encodes (kvmd/clients/streamer.py:83-89).
  - StreamerSnapshot.make_preview is deliberately NOT used: it is memoized
    with functools.lru_cache(maxsize=1) on a bound method
    (kvmd/clients/streamer.py:107-114), which pins a whole JPEG plus its
    preview for the life of the process, and its Image.thumbnail() fits to
    box while preserving aspect, so the size it returns is not the size you
    asked for.  This module does its own one-decode PIL pass instead, the
    way the brief prescribes, and measures the result with PilImage.open().
  - Streamer.get_state() returns {features, limits, params, streamer,
    snapshot} and the "streamer" value is NULLABLE (streamer.py:347-354,
    404-416).  Live geometry lives at ["streamer"]["source"]["resolution"],
    a shape produced by ustreamer's C code and validated nowhere in Python
    (only in-repo evidence: web/share/js/kvm/stream.js:247-253), so every
    read of it here goes through .get().  params["resolution"] is the
    CONFIGURED capture string, not the live signal.
  - The streamer is not kept running unless something needs it
    (server.py:682-684), so a snapshot on an idle device can legitimately
    fail.  This module does NOT force the stream up: the internal flag is
    edge-triggered by KvmdServer.__stream_controller (server.py:763-768) and
    poking it from here would pin ustreamer on forever.

OCR
  - Ocr.recognize(data, langs, left, top, right, bottom) is the only entry
    point (kvmd/apps/kvmd/ocr.py:249-255).  On this model _use_rknn() is
    true and the RKNN branch IGNORES `data` and `langs` entirely: ocr_service
    fetches its own frame from /run/kvmd/ustreamer.sock (ocr.py:112-115,
    252-254, 259-271).  So `read` cannot OCR a frame this module holds, and
    it does not pretend to: under RKNN it takes no snapshot at all.
  - _use_rknn() is a fresh os.stat() of the socket path on every call
    (ocr.py:156-163, 196-198); off-device it is always False and the
    tesseract branch is used.
  - Box coordinates are absolute SOURCE pixels, PIL-style half-open, with -1
    as the per-edge "unset" sentinel (ocr.py:279-287, api/streamer.py:75-78).
    There are no fractional coordinates anywhere in the OCR path.
  - Ocr.recognize burns a default-executor thread for up to
    _RKNN_SOCK_TIMEOUT = 15 s (ocr.py:118) via aiotools.run_async
    (kvmd/aiotools.py:196-197), which is the loop's default pool.

HID
  - There is no reusable public typing API: HidApi's print handler and its
    symmap loader are name-mangled privates (api/hid.py:169-210); only
    get_keymaps() is public.  So `type` rebuilds the same pipeline from
    keyboard.keysym.build_symmap + keyboard.printer.text_to_evdev_keys +
    BaseHid.send_key_events, mirroring api/hid.py:196-210 for keymap
    resolution.
  - text_to_evdev_keys SILENTLY DROPS characters it cannot map -- anything
    non-printable, anything absent from the symmap, anything needing CTRL
    (kvmd/keyboard/printer.py:170-171, 181, 185-187).  `type` therefore
    reports how many key events it actually emitted.
  - send_key_events sleeps BEFORE every event: 5 ms, or 30 ms with slow=True
    (kvmd/plugins/hid/__init__.py:162-167).  ~2 events per character makes
    1000 characters >= ~10 s, so `type` must be cancellable; on cancel it
    calls hid.clear_events() the way api/hid.py:189-190 does.
  - valid_hid_key is CASE-SENSITIVE DOM KeyboardEvent.code
    (kvmd/validators/hid.py:46-47, kvmd/keyboard/mappings.py:165): ControlLeft,
    Delete, KeyA -- not ctrl, del, keya.  F13..F19 do not exist.
  - MOUSE_TO_EVDEV "up"/"down" are BTN_BACK/BTN_FORWARD side buttons, NOT
    scroll (kvmd/mouse.py:54-60).  Scrolling goes through
    send_mouse_wheel_event, and the web UI inverts the DOM sign
    (web/share/js/kvm/mouse.js:360-366), so a NEGATIVE delta_y scrolls down.
  - valid_hid_mouse_move / valid_hid_mouse_delta CLAMP silently instead of
    rejecting (validators/hid.py:50-61), so fx/fy are range-checked here
    before being mapped onto MouseRange.MIN..MAX = -32768..32767
    (kvmd/mouse.py:29-41).
  - Absolute moves are silently dropped when the HID plugin is in relative
    mode (BaseHid._send_mouse_move_event is a no-op stub,
    plugins/hid/__init__.py:201-203), so `click`/`move` check
    state["mouse"]["absolute"] first rather than reporting a false success.
  - hid get_state()["online"] is the hardcoded literal True on the otg plugin
    this hardware uses (plugins/hid/otg/__init__.py:270), so `state` reports
    keyboard.online / mouse.online / connected as well.

ATX
  - BaseAtx's seven action methods take `wait` as a REQUIRED POSITIONAL bool
    (plugins/atx/__init__.py:69-89); there is no default and no keyword-only
    form.  wait=False is fire-and-forget: run_region_task returns as soon as
    the exclusive region is entered and later failures are only logged
    (kvmd/aiotools.py:347-365), so an empty result is NOT evidence the
    machine changed state.
  - FORK BUG: glatx.py:113 uses `async with self.__region:` but
    AioExclusiveRegion implements only __enter__/__exit__ (aiotools.py:299),
    so every ATX call with wait=True raises TypeError on this hardware.
    `power`/`press` default wait to False and translate that TypeError into
    a readable tool error instead of a 500.
  - ATX state shape is plugin-dependent: glatx returns {enabled, busy, power,
    leds} with leds.power/leds.hdd HARDCODED False on every path
    (plugins/atx/glatx.py:33-35, 59-61, 73-75), while gpio.py:124 and
    disabled.py:42 have no "power" key at all.  `state` reads both with
    .get() and never derives power from leds the way api/redfish.py:113 does.

MSD
  - BaseMsd.set_params's first keyword is `name`, NOT `image`
    (plugins/msd/__init__.py:167-174); only the REST layer calls it "image".
  - set_params raises MsdConnectedError while the drive is connected
    (plugins/msd/otg/__init__.py:396), so `mount` disconnects first.
  - cdrom and rw are mutually exclusive and the LAST one processed wins
    (otg/__init__.py:404-412): passing both true yields cdrom=False, rw=True.
    `mount` resolves that here rather than letting it surprise the caller.
  - An empty `image` on set_params DESELECTS the image instead of erroring
    (api/msd.py:82, otg/__init__.py:398-402), so `mount` rejects an empty
    name outright.
  - write_image raises MsdImageExistsError if the name already exists
    (otg/__init__.py:1170), so `fetch_iso` is not idempotent, and it holds
    the MSD exclusive region for the whole download, making every other MSD
    call fail with 409 meanwhile.
  - MsdFileWriter.write_chunk returns the CUMULATIVE bytes written, not the
    chunk length (plugins/msd/__init__.py:294-319) -- assign, don't +=.
  - The REST route's 7-day read timeout is a bare inline literal at
    api/msd.py:269, not a constant or a config option; it is repeated here.
  - Image names are storage-relative keys with no leading slash
    (plugins/msd/otg/storage.py:249-255); free space lives under the
    EMPTY-STRING partition key, state["storage"]["parts"][""]["free"]
    (api/msd.py:282).

WoL
  - WolApi takes no constructor arguments, holds only a logger and a path,
    and is built inline at server.py:229 with no reference kept
    (api/wol.py:43-46), so this module builds its own -- it is free.
  - POST /wol/wake reports success unconditionally: it gathers the
    per-interface booleans and discards them (api/wol.py:145-150).  `wake`
    keeps them.
  - There is no name->mac resolution in wol.py; names live in
    /etc/kvmd/user/wol_list.json as {ip, mac, name} records
    (api/wol.py:105-116, 186-190), read here with common.read_json_file.
  - valid_mac lives in api/common.py:215, not in kvmd/validators/, and raises
    BadRequestError (an HttpError), not ValidatorError.

Logging
  - The module-level `logger = get_logger()` idiom used by seven API modules
    in this fork (api/ap.py:24 and friends) produces a logger literally named
    "importlib._bootstrap", outside the "kvmd" hierarchy, whose records never
    reach /var/log/kvmd.log.  get_logger(0) is called inside handlers here
    instead (kvmd/logging.py:29), which names the logger
    "kvmd.apps.kvmd.api.mcp" and lands in both the journal and the log file.
  - LogReader.__line_to_record returns {} for any line that is not four
    " - "-separated fields, and the logger name and level are discarded
    (kvmd/apps/kvmd/logreader.py:62-71).  So the "mcp " prefix inside the
    message text is the only way to find these lines again, and any reader
    must skip falsy records.
  - LogReader.poll_log(seek) is a BYTE offset from EOF and lands mid-line,
    which makes strptime raise (logreader.py:48-51, 65).  kvm://log reads
    with seek=0 and keeps the tail in a bounded deque instead.
"""


import asyncio
import base64
import collections
import functools
import io
import json
import os
import stat
import time
import urllib.parse

from typing import Any
from typing import Callable

from aiohttp.web import Request
from aiohttp.web import Response

from PIL import Image as PilImage

from .... import __version__
from .... import aiotools
from .... import htclient

from ....logging import get_logger

from ....clients.streamer import StreamerSnapshot

from ....htserver import exposed_http
from ....htserver import make_json_response

from ....keyboard.keysym import build_symmap
from ....keyboard.mappings import WEB_TO_EVDEV
from ....keyboard.printer import text_to_evdev_keys

from ....mouse import MOUSE_TO_EVDEV
from ....mouse import MouseRange

from ....plugins.atx import BaseAtx
from ....plugins.hid import BaseHid
from ....plugins.msd import BaseMsd
from ....plugins.msd import MsdNoSpaceError

from ....validators import ValidatorError
from ....validators import check_string_in_list
from ....validators import raise_error
from ....validators.basic import valid_bool
from ....validators.basic import valid_int_f0
from ....validators.basic import valid_number
from ....validators.hid import valid_hid_key
from ....validators.hid import valid_hid_mouse_button
from ....validators.hid import valid_hid_mouse_delta
from ....validators.kvm import valid_atx_button
from ....validators.kvm import valid_atx_power_action
from ....validators.kvm import valid_msd_image_name
from ....validators.kvm import valid_msd_mount_name
from ....validators.kvm import valid_stream_quality
from ....validators.net import valid_url
from ....validators.os import valid_printable_filename

from ..logreader import LogReader
from ..ocr import Ocr
from ..streamer import Streamer

from .common import read_json_file
from .common import valid_mac
from .wol import WolApi


# =====
# The kvmd version this module was written and verified against
# (kvmd/__init__.py:23).  See _warn_if_newer_kvmd(): a newer kvmd only ever
# produces a WARNING.  D-006 -- the module degrades to "absent" after a
# firmware upgrade, never to a broken KVM.
_WRITTEN_AGAINST = "4.82"

_SERVER_NAME = "kvmd-mcp"

# MCP protocol revisions this endpoint speaks.  The first is what we answer
# with when the client does not name one it wants.
_PROTOCOL_VERSIONS = ("2024-11-05", "2025-03-26", "2025-06-18")

# Self-imposed request body cap (brief section 4).  Note that aiohttp's own
# client_max_size is 1 MiB (kvmd/htserver.py:542-547 passes none) and nginx's
# is 4 KB (configs/nginx/nginx.conf.mako:28), so this is the middle limit and
# not the one an HTTP client will usually hit.
_MAX_BODY = 64 * 1024

# Read the body in the same chunk size upgrade.py:414-440 uses.
_BODY_CHUNK = 64 * 1024

# `type` is split into pieces so a long paste can be cancelled promptly.
# 1024 matches the default ?limit= of POST /hid/print (api/hid.py:172); there
# is no hardware cap -- BaseHid.send_key_events just iterates (see docstring).
_TYPE_CHUNK = 1024
_TYPE_MAX = 4096

_KEYS_MAX = 6

_WAIT_FOR_MAX_TIMEOUT = 900.0
_WAIT_FOR_MIN_EVERY = 1.0

_LOG_TAIL_LINES = 200

_WOL_LIST_PATH = "/etc/kvmd/user/wol_list.json"

_RES_FRAME = "kvm://frame"
_RES_LOG = "kvm://log"

# JSON-RPC 2.0 error codes.
_E_PARSE = -32700
_E_REQUEST = -32600
_E_METHOD = -32601
_E_PARAMS = -32602
_E_INTERNAL = -32603

_UNSET = object()


def _warn_if_newer_kvmd() -> None:
    # Brief section 10: warn, never refuse.  Note KvmdServer unpacks
    # __version__ into exactly two ints (server.py:560-565), so the format is
    # "<major>.<minor>" and must never be rewritten by anyone.
    try:
        current = tuple(int(part) for part in __version__.split("."))
        written = tuple(int(part) for part in _WRITTEN_AGAINST.split("."))
    except ValueError:
        return
    if current > written:
        get_logger(0).warning(
            "mcp: kvmd %s is newer than the version this MCP module was written against (%s);"
            " the endpoint is still enabled, but verify it against the new API",
            __version__, _WRITTEN_AGAINST,
        )


_warn_if_newer_kvmd()


# =====
class _McpError(Exception):
    """A JSON-RPC level failure: malformed envelope, unknown method, bad params."""

    def __init__(self, code: int, msg: str) -> None:
        super().__init__(msg)
        self.code = code
        self.msg = msg


class _ToolError(Exception):
    """A tool that ran and failed; rendered as {"isError": true}, HTTP 200."""

    def __init__(self, msg: str) -> None:
        super().__init__(msg)
        self.msg = msg


# =====
def _coerce_number(value: Any) -> Any:
    # The fork's validators are string-first: valid_int_f0(640.0) and
    # valid_stream_quality(80.0) both raise, because they str() then int()
    # (kvmd/validators/basic.py:71-80).  JSON has no integer type, so a client
    # that sends 80.0 would be rejected where 80 is accepted.  Narrow integral
    # floats before validating; everything else is passed through untouched.
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def _get_arg(args: dict, name: str, default: Any=_UNSET) -> Any:
    if name not in args or args[name] is None:
        if default is _UNSET:
            raise ValidatorError(f"Missing required argument '{name}'")
        return default
    return _coerce_number(args[name])


def _valid_fraction(arg: Any, name: str) -> float:
    # valid_hid_mouse_move CLAMPS out-of-range input instead of rejecting it
    # (validators/hid.py:50-53), so bound the fraction before mapping.
    return float(valid_number(arg, min=0, max=1, type=float, name=name))


def _fraction_to_mouse(value: float) -> int:
    # web/share/js/kvm/mouse.js:383-384 does remap(px, 0, w-1, MIN, MAX);
    # for a 0..1 fraction that is round(f * 65535) + MIN.
    return MouseRange.normalize(round(value * (MouseRange.MAX - MouseRange.MIN)) + MouseRange.MIN)


def _valid_box(arg: Any) -> tuple[int, int, int, int]:
    if not isinstance(arg, (list, tuple)) or len(arg) != 4:
        raise ValidatorError("The argument 'box' must be a list of four integers [left, top, right, bottom]")
    (left, top, right, bottom) = (int(valid_number(_coerce_number(item), min=0, name="box coordinate")) for item in arg)
    if left >= right or top >= bottom:
        raise ValidatorError("The argument 'box' must satisfy left < right and top < bottom")
    return (left, top, right, bottom)


def _normalize_text(text: str) -> str:
    # Brief section 5: casefold plus whitespace collapse on both sides.
    return " ".join(text.split()).casefold()


def _redact_args(args: dict) -> str:
    # Brief section 6.  `text` never reaches the log; `url` logs host only.
    out: dict = {}
    for (key, value) in args.items():
        if key == "text":
            out[key] = f"len={len(value) if isinstance(value, str) else 0}"
        elif key == "url":
            try:
                out[key] = (urllib.parse.urlsplit(str(value)).hostname or "?")
            except ValueError:
                out[key] = "?"
        elif key in ("passwd", "password", "token", "auth_token"):
            out[key] = "***"
        else:
            out[key] = value
    try:
        return json.dumps(out, sort_keys=True, ensure_ascii=False)
    except (TypeError, ValueError):
        return "<unserializable>"


def _client_ip(req: Request) -> str:
    # kvmd listens on a unix socket, so req.remote is empty; nginx supplies
    # these headers (configs/nginx/loc-proxy.conf:2).  Idiom copied verbatim
    # from kvmd/apps/kvmd/server.py:548-550.
    return (
        req.headers.get("X-Real-IP")
        or req.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        or "unknown"
    )


@functools.lru_cache(maxsize=4)
def _cached_symmap(path: str, mod_ts: float) -> dict[int, dict[int, int]]:
    # Same shape as HidApi.__inner_ensure_symmap (api/hid.py:206-210), but on a
    # module-level function so it does not pin an McpApi instance.  build_symmap
    # does blocking file I/O plus an Xlib keysym walk; without this every `type`
    # call would reparse the keymap on the event loop.
    _ = mod_ts  # For LRU
    return build_symmap(path)


def _probe_jpeg_size(data: bytes) -> tuple[int, int]:
    # PilImage.open is lazy: this parses the JPEG header only, no pixel decode
    # (same idiom as kvmd/clients/streamer.py:111).
    with io.BytesIO(data) as bio:
        with PilImage.open(bio) as image:
            return (image.width, image.height)


def _render_jpeg(
    data: bytes,
    box: (tuple[int, int, int, int] | None),
    max_width: int,
    quality: int,
) -> tuple[bytes, int, int]:

    # One decode per call, and the image is closed before returning
    # (brief section 5).  Runs in the loop's existing default executor via
    # aiotools.run_async -- the same one make_preview and Ocr already use
    # (kvmd/aiotools.py:196-197); no new thread pool.
    with io.BytesIO(data) as src:
        image = PilImage.open(src)
        try:
            if box is not None:
                # Clamp to the frame the way ocr.py:280-287 does, then crop.
                left = min(box[0], image.width)
                top = min(box[1], image.height)
                right = min(box[2], image.width)
                bottom = min(box[3], image.height)
                if left >= right or top >= bottom:
                    raise _ToolError(f"box {list(box)} does not intersect the {image.width}x{image.height} frame")
                cropped = image.crop((left, top, right, bottom))
                image.close()
                image = cropped
            if max_width > 0 and image.width > max_width:
                # thumbnail() preserves aspect and never upscales, so the
                # result is not necessarily max_width wide -- which is why the
                # size reported to the caller is measured, not echoed.
                image.thumbnail((max_width, image.height), PilImage.Resampling.LANCZOS)
            if image.mode != "RGB":
                converted = image.convert("RGB")
                image.close()
                image = converted
            (width, height) = (image.width, image.height)
            with io.BytesIO() as dst:
                image.save(dst, format="jpeg", quality=quality)
                return (dst.getvalue(), width, height)
        finally:
            image.close()


# =====
class McpApi:  # pylint: disable=too-many-instance-attributes
    def __init__(  # pylint: disable=too-many-arguments
        self,
        streamer: Streamer,
        ocr: Ocr,
        hid: BaseHid,
        atx: BaseAtx,
        msd: BaseMsd,
        keymap_path: str,
        log_reader: (LogReader | None),
    ) -> None:

        self.__streamer = streamer
        self.__ocr = ocr
        self.__hid = hid
        self.__atx = atx
        self.__msd = msd
        self.__log_reader = log_reader

        # HidApi splits the same value this way (api/hid.py:80-81).  Unlike
        # HidApi we do NOT resolve the default keymap in __init__: that call
        # raises when /usr/share/kvmd/keymaps/en-us is missing (api/hid.py:82),
        # and a missing keymap must not stop the KVM from starting.
        self.__keymaps_dir_path = os.path.dirname(keymap_path)
        self.__default_keymap_name = os.path.basename(keymap_path)

        # WolApi() holds only a logger and a path string and is constructed
        # inline at server.py:229 with no reference kept, so there is nothing
        # to be handed; building our own is free and side-effect-free.
        self.__wol = WolApi()

        self.__tools: dict[str, Callable] = {
            "see":          self.__tool_see,
            "read":         self.__tool_read,
            "wait_for":     self.__tool_wait_for,
            "type":         self.__tool_type,
            "keys":         self.__tool_keys,
            "key":          self.__tool_key,
            "click":        self.__tool_click,
            "move":         self.__tool_move,
            "wheel":        self.__tool_wheel,
            "power":        self.__tool_power,
            "press":        self.__tool_press,
            "wake":         self.__tool_wake,
            "fetch_iso":    self.__tool_fetch_iso,
            "mount":        self.__tool_mount,
            "unmount":      self.__tool_unmount,
            "remove_image": self.__tool_remove_image,
            "state":        self.__tool_state,
        }

    # ===== HTTP entry point

    @exposed_http("POST", "/mcp")
    async def __mcp_handler(self, req: Request) -> Response:
        try:
            body = await self.__read_body(req)
        except _McpError as ex:
            return self.__reply(self.__error_envelope(None, ex.code, ex.msg))

        try:
            request = json.loads(body)
        except ValueError as ex:
            return self.__reply(self.__error_envelope(None, _E_PARSE, f"Parse error: {ex}"))

        if isinstance(request, list):
            # Batches are deliberately unsupported (brief section 4).
            return self.__reply(self.__error_envelope(None, _E_REQUEST, "Batch requests are not supported"))
        if not isinstance(request, dict):
            return self.__reply(self.__error_envelope(None, _E_REQUEST, "Invalid Request: expected a JSON object"))

        req_id = request.get("id")
        method = request.get("method")
        params = request.get("params")
        if params is None:
            params = {}

        if not isinstance(method, str) or not isinstance(params, dict):
            return self.__reply(self.__error_envelope(req_id, _E_REQUEST, "Invalid Request: bad 'method' or 'params'"))

        try:
            result = await self.__dispatch(req, method, params)
        except _McpError as ex:
            return self.__reply(self.__error_envelope(req_id, ex.code, ex.msg))
        except asyncio.CancelledError:
            raise
        except Exception as ex:  # pylint: disable=broad-except
            # htserver's wrapper would turn this into a bare 500 with no JSON
            # envelope (kvmd/htserver.py:427-432), so it is caught here.
            get_logger(0).exception("mcp: unhandled error in method %r", method)
            return self.__reply(self.__error_envelope(req_id, _E_INTERNAL, f"{type(ex).__name__}: {ex}"))

        if req_id is None:
            # A notification: no response body per JSON-RPC 2.0.
            return self.__reply({})
        return self.__reply({"jsonrpc": "2.0", "id": req_id, "result": result})

    async def __read_body(self, req: Request) -> bytes:
        # aiohttp only enforces its own 1 MiB cap when the body is read, and
        # raises HTTPRequestEntityTooLarge, which htserver does not catch.
        # Enforce the module's cap up front and stream the rest, the way
        # api/upgrade.py:414-440 does.
        if req.content_length is not None and req.content_length > _MAX_BODY:
            raise _McpError(_E_REQUEST, f"Request body is larger than {_MAX_BODY} bytes")
        buf = bytearray()
        async for chunk in req.content.iter_chunked(_BODY_CHUNK):
            buf.extend(chunk)
            if len(buf) > _MAX_BODY:
                raise _McpError(_E_REQUEST, f"Request body is larger than {_MAX_BODY} bytes")
        return bytes(buf)

    def __reply(self, envelope: dict) -> Response:
        # wrap_result=False: the default {"ok":..., "result":...} wrapper would
        # double-envelope the JSON-RPC body (kvmd/htserver.py:185-195).
        return make_json_response(envelope, wrap_result=False)

    def __error_envelope(self, req_id: Any, code: int, msg: str) -> dict:
        return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": msg}}

    # ===== JSON-RPC methods

    async def __dispatch(self, req: Request, method: str, params: dict) -> dict:
        if method == "initialize":
            wanted = params.get("protocolVersion")
            version = (wanted if (isinstance(wanted, str) and wanted in _PROTOCOL_VERSIONS) else _PROTOCOL_VERSIONS[0])
            return {
                "protocolVersion": version,
                "capabilities": {"tools": {}, "resources": {}},
                "serverInfo": {"name": _SERVER_NAME, "version": __version__},
            }
        if method == "ping":
            return {}
        if method.startswith("notifications/"):
            # notifications/initialized and friends: accepted, no-op.
            return {}
        if method == "tools/list":
            return {"tools": _TOOLS}
        if method == "tools/call":
            return await self.__call_tool(req, params)
        if method == "resources/list":
            return {"resources": _RESOURCES}
        if method == "resources/read":
            return await self.__read_resource(params)
        raise _McpError(_E_METHOD, f"Method not found: {method}")

    async def __call_tool(self, req: Request, params: dict) -> dict:
        name = params.get("name")
        args = params.get("arguments")
        if args is None:
            args = {}
        if not isinstance(name, str) or not isinstance(args, dict):
            raise _McpError(_E_PARAMS, "Invalid params: 'name' must be a string and 'arguments' an object")
        handler = self.__tools.get(name)
        if handler is None:
            raise _McpError(_E_PARAMS, f"Unknown tool: {name}")

        logger = get_logger(0)
        line = "mcp %s %s args=%s ms=%d ok=%s"
        ip = _client_ip(req)
        redacted = _redact_args(args)
        started = time.monotonic()
        try:
            content = await handler(args)
        except asyncio.CancelledError:
            raise
        except Exception as ex:  # pylint: disable=broad-except
            # Everything a tool can raise becomes an isError result at HTTP
            # 200: ValidatorError, the plugins' OperationError/IsBusyError
            # families, htserver's BadRequestError (which valid_mac raises),
            # and the TypeError from the glatx wait=True fork bug.
            msg = (ex.msg if isinstance(ex, _ToolError) else f"{type(ex).__name__}: {ex}")
            ms = int((time.monotonic() - started) * 1000)
            logger.warning(line + " err=%s", ip, name, redacted, ms, False, msg)
            return {"content": [{"type": "text", "text": msg}], "isError": True}
        ms = int((time.monotonic() - started) * 1000)
        logger.info(line, ip, name, redacted, ms, True)
        return {"content": content, "isError": False}

    async def __read_resource(self, params: dict) -> dict:
        uri = params.get("uri")
        if uri == _RES_FRAME:
            snapshot = await self.__snapshot(allow_offline=True)
            return {"contents": [{
                "uri": _RES_FRAME,
                "mimeType": "image/jpeg",
                "blob": base64.b64encode(snapshot.data).decode("ascii"),
            }]}
        if uri == _RES_LOG:
            return {"contents": [{
                "uri": _RES_LOG,
                "mimeType": "text/plain",
                "text": await self.__read_log_tail(),
            }]}
        raise _McpError(_E_PARAMS, f"Unknown resource: {uri}")

    async def __read_log_tail(self) -> str:
        if self.__log_reader is None:
            raise _McpError(_E_PARAMS, "LogReader is disabled")
        tail: collections.deque = collections.deque(maxlen=_LOG_TAIL_LINES)
        # seek must be 0: it is a byte offset from EOF and any other value
        # lands mid-line and makes strptime raise (logreader.py:48-51, 65).
        async for record in self.__log_reader.poll_log(0, False):
            if not record:
                # Unparseable lines yield {} (logreader.py:64, 71) and are
                # reachable in production (server.py:446-447 writes raw lines).
                continue
            tail.append("[%s %s] --- %s" % (
                record["dt"].strftime("%Y-%m-%d %H:%M:%S"),
                record["service"],
                record["msg"],
            ))
        return "\n".join(tail)

    # ===== Shared helpers

    async def __snapshot(self, allow_offline: bool) -> StreamerSnapshot:
        # take_snapshot never raises: None is the only failure signal
        # (streamer.py:428-445).  load=False always -- load=True returns the
        # stale cached snapshot without touching ustreamer (streamer.py:429).
        snapshot = await self.__streamer.take_snapshot(save=False, load=False, allow_offline=allow_offline)
        if snapshot is None:
            raise _ToolError(
                "No snapshot available: the streamer is not running, or there is no signal."
                " The streamer is only kept up while something needs it (server.py:682-684)."
            )
        return snapshot

    def __ensure_symmap(self, keymap_name: str) -> dict[int, dict[int, int]]:
        # Mirrors HidApi.__ensure_symmap (api/hid.py:196-205): validate the
        # NAME, join it onto the keymaps dir, require a readable regular file.
        # Never join a raw caller string onto the directory.
        keymap_name = valid_printable_filename(keymap_name, "keymap")
        path = os.path.join(self.__keymaps_dir_path, keymap_name)
        try:
            st = os.stat(path)
            if not (os.access(path, os.R_OK) and stat.S_ISREG(st.st_mode)):
                raise_error(keymap_name, "keymap")
        except Exception:
            raise_error(keymap_name, "keymap")
        return _cached_symmap(path, st.st_mtime)

    async def __check_mouse_absolute(self) -> None:
        # BaseHid._send_mouse_move_event is a no-op stub in relative mode
        # (plugins/hid/__init__.py:201-203) -- nothing raises, the move just
        # goes nowhere.  Refuse rather than report a false success.
        state = await self.__hid.get_state()
        if not (state.get("mouse") or {}).get("absolute", True):
            raise _ToolError("The HID mouse is in relative mode; absolute positioning is unavailable")

    def __ocr_box(self, args: dict) -> tuple[int, int, int, int]:
        box = _get_arg(args, "box", None)
        if box is None:
            # -1 is the per-edge "unset" sentinel (ocr.py:279-287,
            # api/streamer.py:75-78), not a whole-box one.
            return (-1, -1, -1, -1)
        return _valid_box(box)

    async def __recognize(self, box: tuple[int, int, int, int]) -> str:
        data = b""
        if not self.__ocr._use_rknn():  # pylint: disable=protected-access
            # Only the tesseract branch reads `data` (ocr.py:255, 273).  Under
            # RKNN, ocr_service fetches its own frame from the ustreamer socket
            # (ocr.py:112-115, 260-262), so taking a snapshot here would just
            # pay for a second frame grab and would not correlate anyway.
            data = (await self.__snapshot(allow_offline=True)).data
        # langs=[] -> recognize() substitutes the configured defaults
        # (ocr.py:250); under RKNN they are ignored entirely.
        return await self.__ocr.recognize(data=data, langs=[], left=box[0], top=box[1], right=box[2], bottom=box[3])

    def __text_result(self, payload: Any) -> list[dict]:
        return [{"type": "text", "text": json.dumps(payload, sort_keys=True, ensure_ascii=False)}]

    # ===== Tools

    async def __tool_see(self, args: dict) -> list[dict]:
        mode = check_string_in_list(_get_arg(args, "mode", "full"), "see mode", ["full", "preview", "region"])
        quality = valid_stream_quality(_get_arg(args, "quality", 80))
        max_width = valid_int_f0(_get_arg(args, "max_width", (640 if mode == "preview" else 0)))
        raw_box = _get_arg(args, "box", None)
        box: (tuple[int, int, int, int] | None) = None
        if mode == "region":
            if raw_box is None:
                raise ValidatorError("The 'region' mode requires a 'box' argument")
            box = _valid_box(raw_box)

        snapshot = await self.__snapshot(allow_offline=True)
        if mode == "full" and max_width == 0:
            # Nothing to change: hand back ustreamer's own JPEG untouched and
            # only parse its header for the reported size.
            (data, width, height) = (snapshot.data, *(await aiotools.run_async(_probe_jpeg_size, snapshot.data)))
        else:
            (data, width, height) = await aiotools.run_async(_render_jpeg, snapshot.data, box, max_width, quality)

        return [
            {"type": "image", "mimeType": "image/jpeg", "data": base64.b64encode(data).decode("ascii")},
            {"type": "text", "text": f"{width}x{height}"},
            # snapshot.online is the ONLY way to tell a real screen from
            # ustreamer's no-signal placeholder (streamer.py:435-440).
            {"type": "text", "text": f"online={bool(snapshot.online)} source={snapshot.width}x{snapshot.height}"},
        ]

    async def __tool_read(self, args: dict) -> list[dict]:
        text = await self.__recognize(self.__ocr_box(args))
        return [{"type": "text", "text": text}]

    async def __tool_wait_for(self, args: dict) -> list[dict]:
        needle = _get_arg(args, "text")
        if not isinstance(needle, str) or not needle.strip():
            raise ValidatorError("The argument 'text' must be a non-empty string")
        timeout_s = float(valid_number(
            _get_arg(args, "timeout_s", 60), min=1, max=_WAIT_FOR_MAX_TIMEOUT, type=float, name="timeout_s"))
        every_s = float(valid_number(
            _get_arg(args, "every_s", 3), min=_WAIT_FOR_MIN_EVERY, max=_WAIT_FOR_MAX_TIMEOUT, type=float, name="every_s"))
        stable_frames = int(valid_number(_get_arg(args, "stable_frames", 2), min=1, max=10, name="stable_frames"))
        box = self.__ocr_box(args)

        wanted = _normalize_text(needle)
        deadline = time.monotonic() + timeout_s
        hits = 0
        last = ""
        polls = 0
        while True:
            # One OCR per poll, nothing held between polls: the snapshot (when
            # the tesseract branch even takes one) is dropped inside
            # __recognize, and only the normalized text survives the loop.
            last = await self.__recognize(box)
            polls += 1
            hits = (hits + 1 if wanted in _normalize_text(last) else 0)
            if hits >= stable_frames:
                return [
                    {"type": "text", "text": last},
                    {"type": "text", "text": json.dumps(
                        {"found": True, "polls": polls, "stable_frames": stable_frames}, sort_keys=True)},
                ]
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            # Yield to the loop; never busy-wait, and never overshoot the
            # deadline by a whole interval.
            await asyncio.sleep(min(every_s, remaining))
        raise _ToolError(f"Timed out after {timeout_s:g}s waiting for {needle!r}; last text: {last!r}")

    async def __tool_type(self, args: dict) -> list[dict]:
        text = _get_arg(args, "text")
        if not isinstance(text, str):
            raise ValidatorError("The argument 'text' must be a string")
        if len(text) > _TYPE_MAX:
            raise ValidatorError(f"The argument 'text' must be at most {_TYPE_MAX} characters")
        slow = valid_bool(_get_arg(args, "slow", False))
        keymap = _get_arg(args, "keymap", self.__default_keymap_name)
        symmap = self.__ensure_symmap(str(keymap))

        events = 0
        try:
            for start in range(0, len(text), _TYPE_CHUNK):
                # Each chunk gets its own generator, which emits its own
                # trailing modifier releases (printer.py:215-219), so chunks
                # are self-balanced and a cancel between them is safe.
                chunk = list(text_to_evdev_keys(text[start:start + _TYPE_CHUNK], symmap))
                events += len(chunk)
                await self.__hid.send_key_events(chunk, no_ignore_keys=True, slow=slow)
        except asyncio.CancelledError:
            # Same recovery as HidApi's paste handler (api/hid.py:189-190).
            self.__hid.clear_events()
            raise
        # text_to_evdev_keys silently drops unmappable characters
        # (printer.py:170-171, 181, 185-187), so report what was really sent.
        return self.__text_result({"len": len(text), "events": events})

    async def __tool_keys(self, args: dict) -> list[dict]:
        chord = _get_arg(args, "chord")
        if not isinstance(chord, list) or not chord:
            raise ValidatorError("The argument 'chord' must be a non-empty list of web key names")
        if len(chord) > _KEYS_MAX:
            raise ValidatorError(f"The argument 'chord' must contain at most {_KEYS_MAX} keys")
        # valid_hid_key is case-sensitive DOM KeyboardEvent.code
        # (validators/hid.py:46-47): ControlLeft, AltLeft, Delete.
        press = [WEB_TO_EVDEV[valid_hid_key(key)] for key in chord]
        # Press in the given order, release in reverse, slow -- exactly what
        # POST /hid/events/send_shortcut does (api/hid.py:347-353).
        events = [(key, True) for key in press] + [(key, False) for key in reversed(press)]
        await self.__hid.send_key_events(events, no_ignore_keys=True, slow=True)
        return self.__text_result({})

    async def __tool_key(self, args: dict) -> list[dict]:
        key = WEB_TO_EVDEV[valid_hid_key(_get_arg(args, "name"))]
        raw_down = _get_arg(args, "down", None)
        if raw_down is None:
            # No explicit state: a tap, with send_key_event's own auto-release
            # (plugins/hid/__init__.py:171-174), as api/hid.py:364 does.
            self.__hid.send_key_event(key, True, True)
        else:
            self.__hid.send_key_event(key, valid_bool(raw_down), False)
        return self.__text_result({})

    async def __tool_click(self, args: dict) -> list[dict]:
        button = valid_hid_mouse_button(_get_arg(args, "button", "left"))
        fx = _valid_fraction(_get_arg(args, "fx"), "fx")
        fy = _valid_fraction(_get_arg(args, "fy"), "fy")
        await self.__check_mouse_absolute()
        self.__hid.send_mouse_move_event(_fraction_to_mouse(fx), _fraction_to_mouse(fy))
        code = MOUSE_TO_EVDEV[button]
        self.__hid.send_mouse_button_event(code, True)
        self.__hid.send_mouse_button_event(code, False)
        return self.__text_result({})

    async def __tool_move(self, args: dict) -> list[dict]:
        fx = _valid_fraction(_get_arg(args, "fx"), "fx")
        fy = _valid_fraction(_get_arg(args, "fy"), "fy")
        await self.__check_mouse_absolute()
        self.__hid.send_mouse_move_event(_fraction_to_mouse(fx), _fraction_to_mouse(fy))
        return self.__text_result({})

    async def __tool_wheel(self, args: dict) -> list[dict]:
        # Clamped to +-127 by MouseDelta (validators/hid.py:59-61).  Sign
        # follows the web UI, which inverts the DOM wheel delta
        # (web/share/js/kvm/mouse.js:360-366): negative scrolls down.
        delta_y = valid_hid_mouse_delta(_get_arg(args, "delta_y"))
        self.__hid.send_mouse_wheel_event(0, delta_y)
        return self.__text_result({})

    async def __tool_power(self, args: dict) -> list[dict]:
        action = valid_atx_power_action(_get_arg(args, "action"))
        wait = valid_bool(_get_arg(args, "wait", False))
        handler = {
            "on": self.__atx.power_on,
            "off": self.__atx.power_off,
            "off_hard": self.__atx.power_off_hard,
            "reset_hard": self.__atx.power_reset_hard,
        }[action]
        await self.__atx_call(handler, wait)
        return self.__text_result({"action": action, "wait": wait})

    async def __tool_press(self, args: dict) -> list[dict]:
        button = valid_atx_button(_get_arg(args, "button"))
        wait = valid_bool(_get_arg(args, "wait", False))
        handler = {
            "power": self.__atx.click_power,
            "power_long": self.__atx.click_power_long,
            "reset": self.__atx.click_reset,
        }[button]
        await self.__atx_call(handler, wait)
        return self.__text_result({"button": button, "wait": wait})

    async def __atx_call(self, handler: Callable, wait: bool) -> None:
        # `wait` is a required positional bool on every BaseAtx action
        # (plugins/atx/__init__.py:69-89).  With wait=False the click is
        # fire-and-forget, so an empty result is not proof the machine moved.
        try:
            await handler(wait)
        except TypeError as ex:
            # glatx.py:113 does `async with self.__region:` but
            # AioExclusiveRegion has no __aenter__ (aiotools.py:299), so
            # wait=True is broken on this hardware.  Report it instead of
            # letting a 500 escape.  Do not "fix" glatx.py from here.
            if wait:
                raise _ToolError(
                    "wait=true is unsupported by this ATX plugin (fork bug: glatx.py:113 uses"
                    f" 'async with' on a sync-only AioExclusiveRegion); retry with wait=false. {ex}"
                ) from ex
            raise

    async def __tool_wake(self, args: dict) -> list[dict]:
        mac = _get_arg(args, "mac", None)
        name = _get_arg(args, "name", None)
        if mac is None and name is None:
            raise ValidatorError("wake requires either 'mac' or 'name'")
        if mac is None:
            mac = await self.__resolve_wol_name(str(name))
        # valid_mac raises BadRequestError (an HttpError), not ValidatorError
        # (api/common.py:215) -- the tool wrapper catches both.
        mac = valid_mac(str(mac).strip())
        interfaces = self.__wol._get_available_interfaces()  # pylint: disable=protected-access
        results = await asyncio.gather(*[
            self.__wol._send_wol_to_interface(mac, iface)  # pylint: disable=protected-access
            for iface in interfaces
        ])
        sent = dict(zip(interfaces, [bool(ok) for ok in results]))
        if not any(sent.values()):
            raise _ToolError(f"Failed to send a WOL packet to {mac} on any of {interfaces}")
        return self.__text_result({"mac": mac, "sent": sent})

    async def __resolve_wol_name(self, name: str) -> str:
        # There is no name->mac resolution in wol.py; the records live in the
        # list file as {ip, mac, name} (api/wol.py:105-116, 186-190).
        data = await read_json_file(_WOL_LIST_PATH, {"devices": []}, logger=get_logger(0))
        devices = data.get("devices") or []
        wanted = name.strip().casefold()
        found = [
            dev for dev in devices
            if isinstance(dev, dict) and str(dev.get("name", "")).strip().casefold() == wanted
        ]
        if not found:
            raise _ToolError(f"No WOL device named {name!r} in {_WOL_LIST_PATH}")
        if len(found) > 1:
            raise _ToolError(f"Ambiguous WOL device name {name!r}: {len(found)} matches in {_WOL_LIST_PATH}")
        return str(found[0].get("mac", ""))

    async def __tool_fetch_iso(self, args: dict) -> list[dict]:
        # A re-implementation of POST /msd/write_remote (api/msd.py:248-316)
        # without its ndjson progress stream, because an MCP result is a single
        # JSON body.  The 7-day read timeout is the same inline literal the
        # REST route uses (api/msd.py:269).
        url = valid_url(_get_arg(args, "url"))
        insecure = valid_bool(_get_arg(args, "insecure", False))
        wanted_name = str(_get_arg(args, "image", "")).strip()

        name = ""
        size = written = 0
        async with htclient.download(
            url=url,
            verify=(not insecure),
            timeout=10.0,
            read_timeout=(7 * 24 * 3600),
        ) as remote:

            if not wanted_name:
                wanted_name = htclient.get_filename(remote)
            name = valid_msd_image_name(wanted_name)
            # A remote that omits Content-Length (chunked) fails here with a
            # ValidatorError, exactly as the REST route does (api/msd.py:277).
            size = valid_int_f0(remote.content_length)

            state = await self.__msd.get_state()
            storage = state.get("storage")
            if isinstance(storage, dict):
                # Free space lives under the EMPTY-STRING partition key
                # (api/msd.py:282).
                free = (storage.get("parts") or {}).get("", {}).get("free", 0)
                if size > free:
                    raise MsdNoSpaceError()

            get_logger(0).info("mcp: downloading image %r as %r to MSD ...", url, name)
            async with self.__msd.write_image(name, size, None) as writer:
                chunk_size = writer.get_chunk_size()
                async for chunk in remote.content.iter_chunked(chunk_size):
                    # write_chunk returns the CUMULATIVE total, not the chunk
                    # length (plugins/msd/__init__.py:294-319).
                    written = await writer.write_chunk(chunk)
        return self.__text_result({"name": name, "size": size, "written": written})

    async def __tool_mount(self, args: dict) -> list[dict]:
        # /msd/set_params validates its `image` with valid_msd_mount_name, not
        # valid_msd_image_name (api/msd.py:82); the two differ on a leading
        # slash, and the fork uses the former to allow /dev/... paths.
        image = valid_msd_mount_name(_get_arg(args, "image"))
        if not image.strip("/"):
            # An empty name DESELECTS the image instead of erroring
            # (otg/__init__.py:398-402).
            raise ValidatorError("The argument 'image' must not be empty")
        cdrom = valid_bool(_get_arg(args, "cdrom", True))
        rw = valid_bool(_get_arg(args, "rw", False))
        if rw:
            # cdrom and rw are mutually exclusive and the last one processed
            # wins (otg/__init__.py:404-412).  Resolve it here so the caller
            # gets what it asked for rather than a surprise.
            cdrom = False

        state = await self.__msd.get_state()
        if ((state.get("drive") or {}).get("connected")):
            # set_params raises MsdConnectedError while connected
            # (otg/__init__.py:396), so unmount first.
            await self.__msd.set_connected(False)
        await self.__msd.set_params(name=image, cdrom=cdrom, rw=rw)
        await self.__msd.set_connected(True)
        return self.__text_result({"image": image, "cdrom": cdrom, "rw": rw})

    async def __tool_unmount(self, _: dict) -> list[dict]:
        await self.__msd.set_connected(False)
        return self.__text_result({})

    async def __tool_remove_image(self, args: dict) -> list[dict]:
        # /msd/remove uses valid_msd_image_name (api/msd.py:329).
        image = valid_msd_image_name(_get_arg(args, "image"))
        await self.__msd.remove(image)
        return self.__text_result({"image": image})

    async def __tool_state(self, _: dict) -> list[dict]:
        (atx_st, msd_st, streamer_st, hid_st, ocr_st) = await asyncio.gather(
            self.__atx.get_state(),
            self.__msd.get_state(),
            self.__streamer.get_state(),
            self.__hid.get_state(),
            self.__ocr.get_state(),
        )

        # Every read below is a .get(): none of these shapes is fixed.  ATX has
        # three plugin shapes (glatx/gpio/disabled), MSD two, and the streamer
        # sub-dict is produced by ustreamer's C code.
        inner = streamer_st.get("streamer")
        source = ((inner or {}).get("source") or {})
        resolution = (source.get("resolution") or {})
        online = source.get("online")
        if inner is None:
            # ustreamer is not running (or the device is in gl_webrtc adaptive
            # mode, where server.py:362-380 kills it).  Fall back to the last
            # saved snapshot's typed, in-repo-guaranteed state
            # (streamer.py:418-424) -- which may be minutes old.
            saved = (streamer_st.get("snapshot") or {}).get("saved")
            if saved:
                online = saved.get("online")
                resolution = {"width": saved.get("width"), "height": saved.get("height")}

        drive = (msd_st.get("drive") or {})
        drive_image = (drive.get("image") or {})
        storage = (msd_st.get("storage") or {})

        keyboard = (hid_st.get("keyboard") or {})
        mouse = (hid_st.get("mouse") or {})

        return self.__text_result({
            "atx": {
                "enabled": atx_st.get("enabled"),
                "busy": atx_st.get("busy"),
                # glatx's only real indicator is this opaque string from
                # /usr/sbin/atxpower (glatx.py:39, 52); leds are hardcoded
                # False there, so never derive power from them.
                "power": atx_st.get("power"),
                "leds": atx_st.get("leds"),
            },
            "msd": {
                "enabled": msd_st.get("enabled"),
                "online": msd_st.get("online"),
                "busy": msd_st.get("busy"),
                "connected": drive.get("connected"),
                "image": drive_image.get("name"),
                "cdrom": drive.get("cdrom"),
                "rw": drive.get("rw"),
                # The image name survives only as the dict key
                # (otg/__init__.py:303-306).
                "images": sorted((storage.get("images") or {}).keys()),
            },
            "streamer": {
                "online": online,
                "resolution": {"width": resolution.get("width"), "height": resolution.get("height")},
                "running": (inner is not None),
            },
            "hid": {
                # otg hardcodes the top-level "online" to True
                # (plugins/hid/otg/__init__.py:270), so the useful fields are
                # the per-device ones.
                "online": hid_st.get("online"),
                "connected": hid_st.get("connected"),
                "keyboard_online": keyboard.get("online"),
                "mouse_online": mouse.get("online"),
                "mouse_absolute": mouse.get("absolute"),
            },
            "ocr": {"enabled": ocr_st.get("enabled"), "engine": ocr_st.get("engine")},
            "kvmd": {"version": __version__},
        })


# =====
_TOOLS: list[dict] = [
    {
        "name": "see",
        "description": (
            "Capture the console screen as JPEG. mode=full returns ustreamer's frame untouched;"
            " mode=preview downscales to max_width; mode=region crops to box first."
            " The second content part is the produced image's real WxH, which is not necessarily"
            " max_width wide because downscaling preserves aspect and never upscales."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "mode": {"type": "string", "enum": ["full", "preview", "region"], "default": "full"},
                "max_width": {"type": "integer", "minimum": 0, "description": "0 means native; ignored by mode=full"},
                "quality": {"type": "integer", "minimum": 1, "maximum": 100, "default": 80},
                "box": {
                    "type": "array",
                    "items": {"type": "integer", "minimum": 0},
                    "minItems": 4,
                    "maxItems": 4,
                    "description": "[left, top, right, bottom] in source pixels; right/bottom exclusive",
                },
            },
        },
    },
    {
        "name": "read",
        "description": (
            "OCR the console screen and return the text. box is [left, top, right, bottom] in"
            " absolute source pixels. On the NPU (RKNN) model the OCR service grabs its own live"
            " frame, so the text is not correlated with any image a previous `see` returned."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "box": {"type": "array", "items": {"type": "integer", "minimum": 0}, "minItems": 4, "maxItems": 4},
            },
        },
    },
    {
        "name": "wait_for",
        "description": (
            "Poll OCR on the device until `text` appears in stable_frames consecutive reads, or"
            " time out. Both sides are casefolded and whitespace-collapsed before comparison."
            " Note that nginx cuts /api requests at its 60 s default read timeout."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "timeout_s": {"type": "number", "minimum": 1, "maximum": _WAIT_FOR_MAX_TIMEOUT, "default": 60},
                "every_s": {"type": "number", "minimum": _WAIT_FOR_MIN_EVERY, "default": 3},
                "stable_frames": {"type": "integer", "minimum": 1, "maximum": 10, "default": 2},
                "box": {"type": "array", "items": {"type": "integer", "minimum": 0}, "minItems": 4, "maxItems": 4},
            },
            "required": ["text"],
        },
    },
    {
        "name": "type",
        "description": (
            "Type text on the target's keyboard. Characters the keymap cannot produce are silently"
            " dropped by kvmd, so the result reports how many key events were actually emitted."
            " ~2 events per character at 5 ms each (30 ms with slow), so long text takes seconds."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "maxLength": _TYPE_MAX},
                "slow": {"type": "boolean", "default": False},
                "keymap": {"type": "string", "description": "Keymap file name, e.g. en-us"},
            },
            "required": ["text"],
        },
    },
    {
        "name": "keys",
        "description": (
            "Press a chord and release it in reverse order. Key names are case-sensitive DOM"
            " KeyboardEvent.code values, e.g. [\"ControlLeft\", \"AltLeft\", \"Delete\"]."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "chord": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": _KEYS_MAX},
            },
            "required": ["chord"],
        },
    },
    {
        "name": "key",
        "description": (
            "Send one key. Without `down` it is a tap (press and auto-release); with `down` it is"
            " an explicit press or release, which lets you hold a modifier."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "DOM KeyboardEvent.code, e.g. KeyA, Enter, ArrowUp"},
                "down": {"type": "boolean"},
            },
            "required": ["name"],
        },
    },
    {
        "name": "click",
        "description": "Move the absolute pointer to the fractional position (0..1) and click. Requires an absolute-mode mouse.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "fx": {"type": "number", "minimum": 0, "maximum": 1},
                "fy": {"type": "number", "minimum": 0, "maximum": 1},
                "button": {"type": "string", "enum": sorted(MOUSE_TO_EVDEV), "default": "left"},
            },
            "required": ["fx", "fy"],
        },
    },
    {
        "name": "move",
        "description": "Move the absolute pointer to the fractional position (0..1) without clicking.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "fx": {"type": "number", "minimum": 0, "maximum": 1},
                "fy": {"type": "number", "minimum": 0, "maximum": 1},
            },
            "required": ["fx", "fy"],
        },
    },
    {
        "name": "wheel",
        "description": "Scroll the wheel. delta_y is clamped to -127..127 and the sign is inverted versus the DOM: negative scrolls down.",
        "inputSchema": {
            "type": "object",
            "properties": {"delta_y": {"type": "integer", "minimum": -127, "maximum": 127}},
            "required": ["delta_y"],
        },
    },
    {
        "name": "power",
        "description": (
            "State-aware ATX power control. With wait=false (the default) the click is"
            " fire-and-forget: an empty result is not proof the machine changed state."
            " wait=true is broken on GL hardware and returns an error explaining why."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["on", "off", "off_hard", "reset_hard"]},
                "wait": {"type": "boolean", "default": False},
            },
            "required": ["action"],
        },
    },
    {
        "name": "press",
        "description": "Press an ATX button unconditionally (no state check), unlike `power`.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "button": {"type": "string", "enum": ["power", "power_long", "reset"]},
                "wait": {"type": "boolean", "default": False},
            },
            "required": ["button"],
        },
    },
    {
        "name": "wake",
        "description": (
            "Send a Wake-on-LAN packet on every available interface. Give either a MAC or a"
            f" `name` from {_WOL_LIST_PATH}. The result reports per-interface success."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "mac": {"type": "string", "description": "AA:BB:CC:DD:EE:FF or AA-BB-CC-DD-EE-FF"},
                "name": {"type": "string", "description": "A device name from the saved WOL list"},
            },
        },
    },
    {
        "name": "fetch_iso",
        "description": (
            "Download an http(s) image into MSD storage and return {name, size, written}. Blocks"
            " for the whole transfer and holds the MSD lock, so every other MSD call fails with"
            " 409 meanwhile. Not idempotent: an existing name is an error. The remote must send"
            " Content-Length. Long transfers need an nginx location with a raised read timeout."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "http:// or https:// only, lowercase scheme"},
                "image": {"type": "string", "description": "Target storage name; defaults to the remote filename"},
                "insecure": {"type": "boolean", "default": False, "description": "Skip TLS verification"},
            },
            "required": ["url"],
        },
    },
    {
        "name": "mount",
        "description": (
            "Select an image and connect the virtual drive. Disconnects first if something is"
            " already mounted. cdrom and rw are mutually exclusive; rw=true forces cdrom=false."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "image": {"type": "string", "description": "A key of state.msd.images"},
                "cdrom": {"type": "boolean", "default": True},
                "rw": {"type": "boolean", "default": False},
            },
            "required": ["image"],
        },
    },
    {
        "name": "unmount",
        "description": "Disconnect the virtual drive from the target.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "remove_image",
        "description": "Delete an image from MSD storage. Fails if it is currently mounted.",
        "inputSchema": {
            "type": "object",
            "properties": {"image": {"type": "string"}},
            "required": ["image"],
        },
    },
    {
        "name": "state",
        "description": (
            "A point-in-time snapshot of ATX, MSD, streamer, HID and OCR state. Every field may be"
            " null: the underlying shapes are plugin-dependent and partly produced outside Python."
        ),
        "inputSchema": {"type": "object", "properties": {}},
    },
]

_RESOURCES: list[dict] = [
    {
        "uri": _RES_FRAME,
        "name": "Console frame",
        "description": "The current console screen as a JPEG, exactly as ustreamer serves it.",
        "mimeType": "image/jpeg",
    },
    {
        "uri": _RES_LOG,
        "name": "kvmd log tail",
        "description": f"The last {_LOG_TAIL_LINES} parseable lines of the kvmd log.",
        "mimeType": "text/plain",
    },
]
