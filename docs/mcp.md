# kvmd MCP endpoint

`POST /api/mcp` — a Model Context Protocol server, spoken as JSON-RPC 2.0 over a
single HTTP route, implemented as an ordinary kvmd API module in
`kvmd/apps/kvmd/api/mcp.py` and registered alongside the other APIs in
`kvmd/apps/kvmd/server.py:259`.

It exists so that an LLM agent can drive the machine at the console —
look at the screen, read it, type at it, power-cycle it, mount an ISO —
without a bespoke client for kvmd's REST surface, and without a
poll-over-the-network loop for the one thing agents do constantly: wait for
something to appear on screen.

Everything the endpoint does is already possible through the existing REST API.
The endpoint adds three things:

1. **A single, self-describing surface.** `tools/list` hands an agent the whole
   vocabulary with JSON schemas, so a generic MCP client needs no kvmd-specific
   code.
2. **`wait_for`, which runs on the device.** A client-side "OCR the screen every
   3 s until `login:` shows up" is one HTTP round trip plus one JPEG transfer per
   poll. On-device it is one request that returns once. See
   [wait_for](#wait_for-and-why-it-is-on-device).
3. **Failure modes made explicit.** Several kvmd behaviours are silently lossy
   (unmappable characters dropped while typing, WoL failures reported as
   success, absolute mouse moves discarded in relative mode). The REST layer
   passes those through; this module surfaces them, because an agent cannot see
   the screen the way a human operator can. Each is documented under
   [Device facts](#device-facts-the-module-relies-on) with a `file:line`
   citation.

## Why one module and no new port

Decision D-001. The endpoint is a normal `@exposed_http("POST", "/mcp")` handler
on a class in `kvmd/apps/kvmd/api/`. That gets it, for free and with no new
code:

- **The existing auth.** `auth_required` defaults to `True`, so
  `KvmdServer._check_request_auth` → `check_request_auth` gates `/mcp` exactly
  like `/atx` and `/msd` (`kvmd/apps/kvmd/server.py:616`,
  `kvmd/apps/kvmd/api/auth.py:162`). No second credential store, no tokens of its
  own.
- **The existing network posture.** kvmd listens on an AF_UNIX socket; nginx
  fronts it and rewrites `^/api/(.*)$ → /$1`
  (`configs/nginx/kvmd.ctx-server.conf:110-116`). Nothing new is exposed, no
  firewall rule changes, no second process to supervise or restart.
- **The existing objects.** `McpApi` is constructed with the same instances
  `HidApi`/`AtxApi`/`MsdApi`/`StreamerApi` receive. It creates no plugin, opens
  no socket, starts no task, and owns no state beyond a keymap LRU.

A separate MCP process would have needed its own port, its own auth, its own
copies of the plugin handles (which are exclusive — MSD and ATX hold exclusive
regions), and its own place in the boot order. None of that buys anything.

**Constructor signature.** The design brief specified
`McpApi(streamer, ocr, hid, atx, msd, wol, hid_api_keymaps, default_keymap, log)`
and instructed the implementer to adapt it to what `server.py` actually has.
The implemented signature is:

```python
McpApi(streamer, ocr, hid, atx, msd, keymap_path, log_reader)
```

- `wol` is not a variable in `KvmdServer.__init__`: `WolApi()` is built inline at
  `server.py:229` and the reference discarded. `WolApi` takes no constructor
  arguments and holds only a logger and a path (`api/wol.py:43-46`), so `McpApi`
  builds its own.
- `hid_api_keymaps` / `default_keymap` do not exist; the scope has
  `keymap_path: str`, split with `os.path.dirname`/`basename` exactly as
  `HidApi` does at `api/hid.py:80-81`.
- `log` does not exist; `log_reader` (a `LogReader | None`) does, and is what
  `kvm://log` needs.

## Authentication

The same as every other kvmd route:

- `X-KVMD-User` + `X-KVMD-Passwd` headers, or
- `Authorization: Bearer <token>` / the `auth_token` cookie from
  `POST /api/auth/login`.

Note also that `allow_usc` defaults to `True` on `@exposed_http`, so **any local
process on the device that passes `check_unix_credentials` reaches `/mcp`
without a password** — the same posture as `/atx`, `/msd` and every other route,
but worth stating plainly rather than assuming the endpoint is password-only.

No new auth, no scopes, no signed requests, no manifests. Deferred; see
[Deferred decisions](#deferred-decisions).

## Protocol surface

One POST per request, one JSON body in response. No SSE stream: nothing here is
long-running except `wait_for`, which returns exactly once.

| method | behaviour |
|---|---|
| `initialize` | `{protocolVersion, capabilities: {tools: {}, resources: {}}, serverInfo: {name: "kvmd-mcp", version}}`. Echoes the client's `protocolVersion` if it is one of `2024-11-05`, `2025-03-26`, `2025-06-18`; otherwise answers `2025-06-18`, the latest it supports, as the lifecycle spec's SHOULD asks. |
| `ping` | `{}` |
| `notifications/*` | Accepted, no-op. Answered with **HTTP 202 and no body at all**, as the streamable-HTTP transport requires. Covers `notifications/initialized`. |
| `tools/list` | `{tools: [...]}` — the static list below, each with an `inputSchema`. |
| `tools/call` | `{content: [...], isError: bool}` |
| `resources/list` | `{resources: [...]}` — `kvm://frame`, `kvm://log` |
| `resources/read` | `kvm://frame` → `{mimeType: "image/jpeg", blob: <base64>}`, or `-32602` when no snapshot is available (an idle device — routine, not `-32603`); `kvm://log` → `{mimeType: "text/plain", text: <last 200 parseable lines>}` |

**Errors.** Unknown method → `-32601`. Unparseable JSON → `-32700`. A JSON array
body (a JSON-RPC batch) → `-32600`; batches are deliberately unsupported. Bad
`params` on `tools/call`, or an unknown tool or resource name → `-32602`. An
unexpected exception escaping the dispatcher → `-32603`, logged with a traceback.

**Tool failures are not JSON-RPC errors.** A tool that ran and failed returns
HTTP 200 with `{"content": [{"type": "text", "text": <message>}], "isError":
true}`, which is what the MCP spec asks for and what lets an agent read the
failure and retry. Only envelope-level problems produce an `error` object.

**Requests with no `id`** are notifications. JSON-RPC 2.0 §4.1 forbids
answering them at all, so the handler returns **HTTP 202 with an empty body** —
including when the notification names an unknown method or bad params, where an
`{"id": null, "error": ...}` answer would be an unsolicited response. An
explicit `"id": null` is *not* a notification: it is a malformed request and
still gets an answer, so a caller that sent one does not wait forever.

**Body cap: 64 KB**, enforced in Python by streaming
`req.content.iter_chunked()` with a `Content-Length` pre-check (the
`api/upgrade.py:414-440` pattern), returning `-32600`. This is *not* the limit
you will hit in practice — see the nginx warning below.

### Two nginx limits you will hit before you hit ours

Neither is a bug in this module, and neither was changed, because a new nginx
location is outside the file list this change is scoped to. Both are worth
knowing before the first `type` call fails mysteriously.

1. **`client_max_body_size 4k` is global**
   (`configs/nginx/nginx.conf.mako:28`) and the catch-all `location /api`
   (`kvmd.ctx-server.conf:110-116`) does not include `loc-bigpost.conf`. So a
   `POST /api/mcp` body over 4096 bytes gets a **413 HTML page from nginx before
   kvmd runs**. Keep `type` payloads and any JSON-RPC envelope under ~3.5 KB.
2. **`location /api` sets no `proxy_read_timeout`**, so nginx's 60 s default
   applies. A `wait_for` with `timeout_s > ~60`, and any `fetch_iso` of real
   size, will **504 at the proxy while the kvmd handler keeps running to
   completion**. Every other long-lived route in this fork has its own location
   block with `proxy_read_timeout 7d` (`kvmd.ctx-server.conf:77, :87, :106`).

The fix for both is a dedicated `location /api/mcp` mirroring those blocks.
Whoever lands this upstream should decide whether that belongs in this change.

## Tools

Arguments are validated with the fork's existing validators
(`validators/hid.py`, `validators/basic.py`, `validators/kvm.py`,
`validators/net.py`, `validators/os.py`). JSON has no integer type, and the
fork's validators are string-first — `valid_int_f0(640.0)` raises where
`valid_int_f0(640)` does not (`validators/basic.py:71-80`) — so integral floats
are narrowed to `int` before validation.

Unless noted, a tool returns a single `text` content part holding a compact JSON
object.

| tool | arguments | returns |
|---|---|---|
| `see` | `mode: "full"\|"preview"\|"region"` (default `full`), `max_width: int >= 0` (default 640 for `preview`, 0 = native otherwise), `quality: 1..100` (default 80), `box: [l,t,r,b]` (required for `region`) | three parts: `{type:"image", mimeType:"image/jpeg", data:<b64>}`, `{type:"text", text:"<w>x<h>"}`, `{type:"text", text:"online=<bool> source=<w>x<h>"}` |
| `read` | `box?: [l,t,r,b]` | one `text` part: the raw OCR text |
| `wait_for` | `text: str` (non-empty), `timeout_s: 1..900` (default 60), `every_s: >= 1.0` (default 3), `stable_frames: 1..10` (default 2), `box?` | two `text` parts: last OCR text, then `{"found": true, "polls": n, "errors": n, "stable_frames": n}`; on timeout `isError` with the last text and, if any read failed, how many |
| `type` | `text: str` (<= 4096 chars), `slow?: bool`, `keymap?: str` (a file name, e.g. `en-us`) | `{"len": <chars given>, "events": <key events emitted>}` |
| `keys` | `chord: [str]` (1..6 DOM `KeyboardEvent.code` names) | `{}` |
| `key` | `name: str`, `down?: bool` | `{}` |
| `click` | `fx: 0..1`, `fy: 0..1`, `button?` (`left`/`right`/`middle`/`up`/`down`, default `left`) | `{}` |
| `move` | `fx: 0..1`, `fy: 0..1` | `{}` |
| `wheel` | `delta_y: -127..127` | `{}` |
| `power` | `action: "on"\|"off"\|"off_hard"\|"reset_hard"`, `wait?: bool` (default false) | `{"action": ..., "wait": ...}` |
| `press` | `button: "power"\|"power_long"\|"reset"`, `wait?: bool` (default false) | `{"button": ..., "wait": ...}` |
| `wake` | `mac?: str`, `name?: str` (one is required) | `{"mac": ..., "sent": {"<iface>": bool, ...}}`; `isError` if every interface failed |
| `fetch_iso` | `url: http(s)`, `image?: str`, `insecure?: bool` | `{"name", "size", "written"}` |
| `mount` | `image: str`, `cdrom?: bool` (default true), `rw?: bool` (default false) | `{"image", "cdrom", "rw"}` — the *resolved* flags |
| `unmount` | — | `{}` |
| `remove_image` | `image: str` | `{"image": ...}` |
| `state` | — | `{atx, msd, streamer, hid, ocr, kvmd}` — see below |

### Notes on individual tools

**`see`.** `mode=full` with `max_width=0` returns ustreamer's own JPEG bytes
untouched and only parses the header for the reported size — no re-encode, no
quality loss. Any other mode does exactly one PIL decode: optional crop, optional
`thumbnail()`, one JPEG save, image closed in a `finally`. The reported `<w>x<h>`
is **measured from the produced JPEG**, never echoed back from `max_width`,
because `thumbnail()` fits to a box preserving aspect and never upscales — ask
for 640 on a 320-wide crop and you get 320.

`StreamerSnapshot.make_preview` is deliberately not used: it is memoized with
`functools.lru_cache(maxsize=1)` on a bound method
(`kvmd/clients/streamer.py:107-114`), pinning a whole ~1 MB JPEG and its preview
for the life of the process.

The third content part exists because **"no signal" is not an error**. ustreamer
serves a placeholder JPEG with `X-UStreamer-Online: false`
(`kvmd/apps/kvmd/streamer.py:435-440`), and that placeholder is
indistinguishable from a real blank console in the image itself. `see` passes
`allow_offline=True` so an agent can look at a dark screen, and reports
`online=` so it can tell the difference.

**`read` and OCR correlation.** On this model `Ocr._use_rknn()` is true, and the
RKNN branch of `Ocr.recognize` **ignores its `data` argument entirely**:
`ocr_service` fetches its own live frame from `/run/kvmd/ustreamer.sock`
(`kvmd/apps/kvmd/ocr.py:112-115, 252-254, 259-271`). So `read` takes no snapshot
at all under RKNN — doing so would pay for a second frame grab whose bytes are
then discarded, which is what the existing `?ocr=1` REST route does. The
consequence for callers: **the text `read` returns is not correlated with the
image a preceding `see` returned.** On the tesseract fallback (other models, and
any off-device test) a snapshot *is* taken and passed.

`langs` is not exposed at all. `api/streamer.py:69-72` swaps in an identity
sub-validator whenever `get_available_langs()` is empty — exactly the RKNN case —
so any string is accepted and then ignored. Rather than offer an argument that
silently does nothing, `recognize()` is always called with `langs=[]`, which makes
`ocr.py:250` substitute the configured defaults.

`box` is `[left, top, right, bottom]` in **absolute source pixels**, PIL-style
half-open. There are no fractional coordinates anywhere in the OCR path.

**`type`.** Returns `{"len", "events"}` rather than `{}` because
`text_to_evdev_keys` silently drops characters it cannot map — non-printable,
absent from the symmap, or requiring CTRL
(`kvmd/keyboard/printer.py:170-171, 181, 185-187`). Roughly two events per typed
character, so a large gap between `len` and `events/2` is the caller's only
signal that the keymap ate its input. Long text is chunked at 1024 characters so
a cancel lands promptly; each chunk emits its own trailing modifier releases
(`printer.py:215-219`) and is therefore self-balanced. On cancellation the module
calls `hid.clear_events()`, the same recovery `api/hid.py:189-190` uses.
Nothing cancels it by itself, though: aiohttp leaves `handler_cancellation` at
its `False` default (`htserver.py:403-411`), so `type` and `wait_for` run under
the same `req.transport` watchdog `POST /hid/print` uses
(`api/hid.py:180-190`) — without it an abandoned paste keeps typing into the
target for minutes after nginx has 504'd, and the client's retry interleaves
with it. `fetch_iso` is deliberately left out: a multi-GB download always
outlives the proxy timeout and finishing it is the useful behaviour.

**`keys` / `key`.** Names are **case-sensitive DOM `KeyboardEvent.code`**
values: `ControlLeft`, `AltLeft`, `Delete`, `KeyA` — not `ctrl`, `del`, `keya`.
`F13`..`F19` do not exist. `keys` presses in order and releases in reverse with
`slow=True`, exactly as `POST /hid/events/send_shortcut` does
(`api/hid.py:347-353`). `key` without `down` is a tap using
`send_key_event`'s own auto-release; with `down` it is an explicit press or
release, which is how you hold a modifier across other calls.

**`click` / `move`.** `fx`/`fy` are fractions of the screen, `0..1`, mapped onto
`MouseRange.MIN..MAX` = `-32768..32767` the way `web/share/js/kvm/mouse.js:383-384`
does. They are range-checked here first because `valid_hid_mouse_move` *clamps*
silently instead of rejecting (`validators/hid.py:50-53`). Both check
`state["mouse"]["absolute"]` first: in relative mode
`BaseHid._send_mouse_move_event` is a no-op stub
(`plugins/hid/__init__.py:201-203`), so an unchecked call would report success
having moved nothing.

**`wheel`.** `MOUSE_TO_EVDEV`'s `"up"`/`"down"` are BTN_BACK/BTN_FORWARD side
buttons, **not scroll** (`kvmd/mouse.py:54-60`). Scrolling goes through
`send_mouse_wheel_event`, and the web UI inverts the DOM sign
(`web/share/js/kvm/mouse.js:360-366`), so **a negative `delta_y` scrolls down**.

**`power` / `press` and `wait`.** `wait` defaults to `false` and you should leave
it there. With `wait=false` the action is fire-and-forget: `run_region_task`
returns as soon as the exclusive region is entered, and later failures are only
logged (`kvmd/aiotools.py:347-365`). **A successful result is not evidence the
machine changed state** — poll `state` to confirm.

`wait=true` is *broken on this hardware*: `glatx.py:113` does
`async with self.__region:` but `AioExclusiveRegion` implements only
`__enter__`/`__exit__` (`aiotools.py:299`), so every ATX call with `wait=True`
raises `TypeError`. htserver does not catch `TypeError`, so unhandled it would
escape as a bare 500. This module catches it and returns an `isError` result
naming the fork bug and telling the caller to retry with `wait=false`.
`glatx.py` is not touched by this change.

**`wake`.** `POST /wol/wake` gathers the per-interface booleans and then
**discards them** (`api/wol.py:145-150`), returning 200 "WOL packet sent" even
when `ether-wake` is missing and every interface failed. `wake` calls
`WolApi._get_available_interfaces()` and `_send_wol_to_interface()` directly,
keeps the booleans, and reports `isError` when every interface failed.
`wol.py` has no name→MAC resolution at all — `/wol/wake` accepts only `mac` — so
`name` is resolved here by reading `/etc/kvmd/user/wol_list.json` through
`common.read_json_file`, rejecting a missing or ambiguous name.

**`fetch_iso`.** A re-implementation of `POST /msd/write_remote`
(`api/msd.py:248-316`) without its ndjson progress stream, since an MCP result is
one JSON body. Same 7-day read timeout, the same bare inline literal the REST
route uses (`api/msd.py:269`) — subject to nginx's 60 s default, above.
Caveats:
- **Not idempotent.** `write_image` raises `MsdImageExistsError` for a name
  already in storage (`otg/__init__.py:1170`).
- **Holds the MSD exclusive region for the whole download**, so every other MSD
  call (`mount`/`unmount`/`remove_image`) fails with 409 meanwhile.
- **The remote must send `Content-Length`.** A chunked response fails with a
  `ValidatorError` before anything is written, same as the REST route.
- Free space is checked first, under the empty-string partition key,
  `state["storage"]["parts"][""]["free"]` (`api/msd.py:282`).
- `http://` and `https://` only (`validators/net.py`).

There is no `sha256` in the result: the device computes no hash, and hashing a
multi-GB stream on an A53 was not measured. Verify against the NAS's
`SHA256SUMS` client-side (D-004).

**`mount`.** The brief said "`set_params` then `set_connected`". That literal
sequence fails on an already-mounted drive, because `set_params` raises
`MsdConnectedError` while connected (`plugins/msd/otg/__init__.py:396`). So
`mount` reads state first and disconnects if needed — but only **after**
checking the requested name against `state["storage"]["images"]`. That check is
not redundant: the name is resolved inside `set_params`, which raises
`MsdUnknownImageError` for anything that is not a storage key
(`otg/__init__.py:398-402, 1238-1244`), by which point the drive has already
been disconnected, so a typo would eject a running target's install media and
*then* fail with nothing mounted and no rollback. It also resolves the
`cdrom`/`rw` collision: the two are mutually exclusive with last-one-wins
(`otg/__init__.py:404-412`), so `cdrom=true, rw=true` would silently yield
`cdrom=false, rw=true`; `mount` forces `cdrom=False` when `rw` is true and
**echoes the resolved flags back** in the result. An empty image name is
rejected outright, because `set_params` treats it as "deselect"
(`otg/__init__.py:398-402`).

Name validation is deliberately asymmetric, matching the REST layer: `mount`
uses `valid_msd_mount_name` (as `POST /msd/set_params` does, `api/msd.py:82`,
which permits `/dev/...` paths), `remove_image` uses `valid_msd_image_name` (as
`POST /msd/remove` does, `api/msd.py:329`). The storage check above still
rejects a `/dev/...` name, because storage keys only ever come from scanning the
storage tree (`plugins/msd/otg/storage.py:203-211`) — such a name could never
resolve in `set_params` either, it would only have ejected whatever was
mounted.

**`state`.** Every field may be `null`. The underlying shapes are
plugin-dependent and partly produced outside Python, so every read goes through
`.get()`:

```json
{
  "atx":      {"enabled": bool, "busy": bool, "power": <opaque string>, "leds": {...}},
  "msd":      {"enabled", "online", "busy", "connected", "image", "cdrom", "rw", "images": [...]},
  "streamer": {"online": bool, "resolution": {"width", "height"}, "running": bool},
  "hid":      {"online", "connected", "keyboard_online", "mouse_online", "mouse_absolute"},
  "ocr":      {"enabled", "engine"},
  "kvmd":     {"version": "4.82"}
}
```

`atx.power` is passed through as an **opaque string** from `/usr/sbin/atxpower`
(`glatx.py:39, 52`) and never compared against a guessed enum; the exact strings
that binary emits could not be verified from this repo. `atx.leds.power` and
`.hdd` are hardcoded `False` on every glatx path (`glatx.py:33-35, 59-61, 73-75`)
and must not be used to derive power, the way `api/redfish.py:113` does.
`hid.online` is the hardcoded literal `True` on the otg plugin this hardware uses
(`plugins/hid/otg/__init__.py:270`), so the per-device fields are the useful
ones. `streamer.running` is false when ustreamer is not up at all — including in
`gl_webrtc` adaptive mode, where `server.py:362-380` kills it.

## `wait_for`, and why it is on-device

The single most common agent loop at a console is "do a thing, then wait for the
screen to say something". Done client-side that is, per poll, an HTTP request, a
JPEG over the wire, and an OCR round trip — for a reboot that is a minute of
traffic to learn one boolean. `wait_for` collapses it into one request that
returns once.

Semantics:

- Both the needle and each OCR result are **normalised the same way**: casefold,
  then collapse all whitespace runs to single spaces. So `"login:"` matches
  `"PVE1 LOGIN:"` and `"pve1\n  login:"`, but not `"log in:"` — the collapse
  normalises runs of whitespace, it does not remove it. It is a plain substring
  test, not a regex.
- A read that *fails* is not a wait that fails. During a reboot ustreamer is
  restarted and `ocr_service`'s socket disappears, so `OcrError` and an
  offline streamer are the expected middle of a `wait_for`, not a reason to
  end it. Failures are counted in `errors`, they reset any partial
  `stable_frames` streak (an unread screen is not a matching screen), and
  polling continues to the deadline. The timeout message names the failure
  count and the last error.
- `stable_frames` (default 2) consecutive matching reads are required before
  returning, so a half-rendered screen does not count. A non-matching read resets
  the counter to zero.
- Between polls it holds **no snapshot buffer**. Only the normalised needle, a
  counter and the last text string survive the loop.
- It sleeps with `asyncio.sleep(min(every_s, remaining))`, so it yields to the
  event loop, never busy-waits, and never overshoots the deadline by a whole
  interval. Other requests are served normally throughout.
- On timeout it returns `isError` with the last OCR text, which is usually enough
  for the agent to work out what went wrong without another call.

Two caveats a caller should know:

1. Under RKNN, `wait_for` stabilises over frames `ocr_service` grabs for itself,
   not over frames this module holds. Pairing `see` with `wait_for` does not mean
   they saw the same screen.
2. Each poll occupies a default-executor thread for up to
   `_RKNN_SOCK_TIMEOUT = 15 s` (`ocr.py:118`) via `aiotools.run_async`
   (`aiotools.py:196-197`), and that pool is `min(32, cpu_count + 4)` = 8 threads
   on the A53. Several concurrent `wait_for`/`see` calls can saturate it.

## Worked example

Everything below assumes the device at `kvm.example.net` and a user `admin`.
Replace the credentials; do not put a real password in shell history.

```sh
KVM=https://kvm.example.net
AUTH='-H X-KVMD-User:admin -H X-KVMD-Passwd:secret'
rpc() { curl -sk $AUTH -H 'Content-Type: application/json' -d "$1" "$KVM/api/mcp"; }
```

**initialize**

```sh
rpc '{"jsonrpc":"2.0","id":1,"method":"initialize",
      "params":{"protocolVersion":"2025-06-18",
                "capabilities":{},
                "clientInfo":{"name":"demo","version":"0"}}}'
```

```json
{"jsonrpc":"2.0","id":1,"result":{
  "protocolVersion":"2025-06-18",
  "capabilities":{"tools":{},"resources":{}},
  "serverInfo":{"name":"kvmd-mcp","version":"4.82"}}}
```

**tools/list** (truncated)

```sh
rpc '{"jsonrpc":"2.0","id":2,"method":"tools/list"}'
```

```json
{"jsonrpc":"2.0","id":2,"result":{"tools":[
  {"name":"see","description":"Capture the console screen as JPEG...",
   "inputSchema":{"type":"object","properties":{
     "mode":{"type":"string","enum":["full","preview","region"],"default":"full"},
     "max_width":{"type":"integer","minimum":0},
     "quality":{"type":"integer","minimum":1,"maximum":100,"default":80},
     "box":{"type":"array","items":{"type":"integer","minimum":0},
            "minItems":4,"maxItems":4}}}},
  {"name":"read","...":"..."}]}}
```

**see** — a 640-wide preview, decoded to a file:

```sh
rpc '{"jsonrpc":"2.0","id":3,"method":"tools/call",
      "params":{"name":"see","arguments":{"mode":"preview","max_width":640,"quality":70}}}' \
  | python3 -c 'import sys,json,base64
r=json.load(sys.stdin)["result"]
open("frame.jpg","wb").write(base64.b64decode(r["content"][0]["data"]))
print(r["content"][1]["text"], r["content"][2]["text"])'
```

```
640x480 online=True source=1280x960
```

The raw result, for shape:

```json
{"jsonrpc":"2.0","id":3,"result":{"isError":false,"content":[
  {"type":"image","mimeType":"image/jpeg","data":"/9j/4AAQSkZJRg..."},
  {"type":"text","text":"640x480"},
  {"type":"text","text":"online=True source=1280x960"}]}}
```

**read** — OCR the top-left quadrant of a 1280x960 signal:

```sh
rpc '{"jsonrpc":"2.0","id":4,"method":"tools/call",
      "params":{"name":"read","arguments":{"box":[0,0,640,480]}}}'
```

```json
{"jsonrpc":"2.0","id":4,"result":{"isError":false,"content":[
  {"type":"text","text":"Ubuntu 24.04.1 LTS pve1 tty1\n\npve1 login:"}]}}
```

**wait_for** — across a reboot. Note `timeout_s` above ~60 needs the nginx
change described earlier, or the proxy will 504 while the handler runs on:

```sh
rpc '{"jsonrpc":"2.0","id":5,"method":"tools/call",
      "params":{"name":"wait_for","arguments":{
        "text":"login:","timeout_s":50,"every_s":3,"stable_frames":2}}}'
```

Found:

```json
{"jsonrpc":"2.0","id":5,"result":{"isError":false,"content":[
  {"type":"text","text":"pve1 login:"},
  {"type":"text","text":"{\"errors\": 0, \"found\": true, \"polls\": 7, \"stable_frames\": 2}"}]}}
```

Timed out:

```json
{"jsonrpc":"2.0","id":5,"result":{"isError":true,"content":[
  {"type":"text","text":"Timed out after 50s waiting for 'login:'; last text: 'Loading initial ramdisk ...'"}]}}
```

**An envelope-level error**, for contrast — note it is an `error`, not an
`isError` result:

```sh
rpc '{"jsonrpc":"2.0","id":6,"method":"tools/frobnicate"}'
```

```json
{"jsonrpc":"2.0","id":6,"error":{"code":-32601,"message":"Method not found: tools/frobnicate"}}
```

## Logging

One line per `tools/call` at INFO, via `get_logger(0)` inside the handler:

```
mcp <client-ip> <tool> args=<json> ms=<n> ok=<bool>
```

Failures log the same line at WARNING with a trailing ` err=<message>`.

Redaction, per the brief: an argument named `text` logs as `len=N` and never its
content; `url` logs the hostname only; `passwd`/`password`/`token`/`auth_token`
log as `***`. Frames are never logged at any level.

The `err=` field is redacted too, and separately, because redacting the `args=`
field alone does not hold the line: the fork's validators embed the offending
value verbatim in their message (`validators/__init__.py` `raise_error`), and
`valid_url` accepts userinfo, so a rejected
`https://admin:hunter2@nas.lan/isos/x.iso` would otherwise be logged in full
next to a properly redacted `args=`. Every redacted argument value is
substituted wherever it appears in the message. Where the message itself is the
problem, a tool supplies its own log text: `wait_for`'s timeout returns the
needle and the whole OCR'd screen **to the caller** — which may be holding a
recovery key or an echoed password — and logs only
`text len=N polls=N last_len=N`. The log is persisted to eMMC, served back by
`kvm://log`, and swept into the diagnostics bundle (`api/upgrade.py:135`), so
nothing that was on the screen may enter it.

Two implementation notes for anyone reading these lines back:

- The module-level `logger = get_logger()` idiom used by seven API modules in
  this fork (`api/ap.py:24` and friends) produces a logger literally named
  `importlib._bootstrap`, outside the `kvmd` hierarchy, whose records never reach
  `/var/log/kvmd.log`. This module calls `get_logger(0)` *inside* handlers
  (`kvmd/logging.py:29`), which names it `kvmd.apps.kvmd.api.mcp` and lands in
  both the journal and the log file.
- `LogReader.__line_to_record` discards the logger name and level and returns
  `{}` for any line that is not four `" - "`-separated fields
  (`kvmd/apps/kvmd/logreader.py:62-71`). So the literal `mcp ` prefix in the
  message text is the only way to grep these lines back out, and any reader must
  skip falsy records.
- `kvm://log` does **not** go through `LogReader.poll_log()`. Its `seek` is a
  **byte** offset from EOF and lands mid-line, and worse, a line that *does*
  split into four `" - "` fields without a leading timestamp makes `strptime`
  raise straight out of the async generator, which cannot then be resumed
  (`logreader.py:48-51, 62-70`) — one such line would make the whole resource
  unreadable until the file rotated. Those lines are reachable in production:
  the `webrtc_client` stderr pipe writes raw, unformatted text into the very
  same file (`server.py:446-448`). So the module parses the file itself in the
  reader's own record shape, off the event loop via `aiotools.run_async`,
  dropping the lines that do not parse and keeping the tail in a bounded
  deque.

## Device facts the module relies on

Each was verified in this tree at kvmd 4.82 (`kvmd/__init__.py:23`). The module
docstring carries the same list; this is the summary.

### Routing and transport

| fact | citation |
|---|---|
| `@exposed_http` registers the path verbatim; there is no `/api` prefix in Python. `POST /api/mcp` reaches the handler only because nginx rewrites `^/api/(.*)$ → /$1`. | `kvmd/htserver.py:112-127`, `configs/nginx/kvmd.ctx-server.conf:110-116` |
| `auth_required` and `allow_usc` both default to `True`. | `kvmd/apps/kvmd/server.py:616`, `kvmd/apps/kvmd/api/auth.py:162` |
| `make_json_response()` wraps its argument as `{"ok":..., "result":...}`; a JSON-RPC body must not be double-wrapped, so every response passes `wrap_result=False` — the same escape hatch `api/redfish.py:77` uses. | `kvmd/htserver.py:181-195` |
| The route wrapper catches only `IsBusyError`, `ValidatorError`, `OperationError` and `HttpError`; anything else escapes as a bare 500 with no JSON envelope. Hence the broad catches here. | `kvmd/htserver.py:422-433` |
| nginx caps bodies at 4 KB globally and sets no `proxy_read_timeout` on `location /api`. | `configs/nginx/nginx.conf.mako:28`, `kvmd.ctx-server.conf:110-116` |
| aiohttp's own body cap is 1 MiB (no `client_max_size` is passed). | `kvmd/htserver.py:542-547` |
| kvmd listens on AF_UNIX, so `req.remote` is empty; the client IP comes from nginx's headers. | `kvmd/htserver.py:397-399`, idiom from `kvmd/apps/kvmd/server.py:548-550` |

### Streamer

| fact | citation |
|---|---|
| `take_snapshot(save, load, allow_offline)` takes three required args and **never raises**: `None` is the only failure signal. | `kvmd/apps/kvmd/streamer.py:428-445` |
| `load=True` short-circuits to the cached saved snapshot without touching ustreamer, so it is never used here. | `streamer.py:429-430` |
| "No signal" is a placeholder JPEG with `X-UStreamer-Online: false`. | `streamer.py:435-440` |
| `StreamerSnapshot` has exactly five fields; `.width`/`.height` describe the **source** frame, not anything re-encoded here. | `kvmd/clients/streamer.py:83-89` |
| `make_preview` is `lru_cache(maxsize=1)` on a bound method and fits-to-box; not used. | `kvmd/clients/streamer.py:107-114` |
| `get_state()["streamer"]` is **nullable**; live geometry at `["streamer"]["source"]["resolution"]` is produced by ustreamer's C code and validated nowhere in Python. `params["resolution"]` is the *configured* capture string, not the live signal. | `streamer.py:347-354, 404-416`; only in-repo evidence for the shape is `web/share/js/kvm/stream.js:247-253` |
| The streamer is not kept running unless something needs it, so a snapshot on an idle device can legitimately fail. This module does **not** force it up: the internal flag is edge-triggered and poking it from here would pin ustreamer on permanently. | `server.py:682-684`, `server.py:763-768` |

### OCR

| fact | citation |
|---|---|
| `Ocr.recognize(data, langs, left, top, right, bottom)` is the only entry point. Under RKNN it ignores `data` and `langs` and fetches its own frame from `/run/kvmd/ustreamer.sock`. | `kvmd/apps/kvmd/ocr.py:249-255, 112-115, 252-254, 259-271` |
| `_use_rknn()` is a fresh `os.stat()` of the socket path on every call; off-device it is always false and the tesseract branch runs. | `ocr.py:156-163, 196-198` |
| Box coordinates are absolute source pixels, PIL half-open, with `-1` as the **per-edge** unset sentinel. | `ocr.py:279-287`, `api/streamer.py:75-78` |
| `recognize` burns a default-executor thread for up to `_RKNN_SOCK_TIMEOUT = 15 s`. | `ocr.py:118`, `kvmd/aiotools.py:196-197` |
| An empty `get_available_langs()` swaps in an identity validator, so `langs` is unenforceable — hence not exposed. | `api/streamer.py:69-72` |

### HID

| fact | citation |
|---|---|
| There is no reusable public typing API: `HidApi`'s print handler and symmap loader are name-mangled privates; only `get_keymaps()` is public. `type` rebuilds the pipeline from `build_symmap` + `text_to_evdev_keys` + `send_key_events`. | `api/hid.py:169-210` |
| `text_to_evdev_keys` silently drops unmappable characters. | `kvmd/keyboard/printer.py:170-171, 181, 185-187` |
| `send_key_events` sleeps **before** every event: 5 ms, or 30 ms with `slow=True`. | `plugins/hid/__init__.py:162-167` |
| `valid_hid_key` is case-sensitive DOM `KeyboardEvent.code`; `F13`..`F19` do not exist. | `kvmd/validators/hid.py:46-47`, `kvmd/keyboard/mappings.py:165` |
| `MOUSE_TO_EVDEV`'s `"up"`/`"down"` are BTN_BACK/BTN_FORWARD, not scroll; the web UI inverts the DOM wheel sign. | `kvmd/mouse.py:54-60`, `web/share/js/kvm/mouse.js:360-366` |
| `valid_hid_mouse_move` / `valid_hid_mouse_delta` **clamp** silently rather than reject. | `validators/hid.py:50-61` |
| `MouseRange.MIN..MAX` = `-32768..32767`. | `kvmd/mouse.py:29-41` |
| Absolute moves are silently dropped in relative mode (`_send_mouse_move_event` is a no-op stub). | `plugins/hid/__init__.py:201-203` |
| otg's `get_state()["online"]` is the hardcoded literal `True`. | `plugins/hid/otg/__init__.py:270` |

### ATX

| fact | citation |
|---|---|
| All seven action methods take `wait` as a **required positional** bool. | `plugins/atx/__init__.py:69-89` |
| `wait=False` is fire-and-forget: `run_region_task` returns once the region is entered and later failures are only logged. | `kvmd/aiotools.py:347-365` |
| **Fork bug:** `glatx.py:113` uses `async with self.__region:` on an `AioExclusiveRegion` that implements only `__enter__`/`__exit__`, so `wait=True` raises `TypeError`. Not fixed here. | `plugins/atx/glatx.py:113`, `aiotools.py:299` |
| State shape is plugin-dependent: glatx returns `{enabled, busy, power, leds}` with leds hardcoded `False`; `gpio.py` and `disabled.py` have no `power` key at all. | `glatx.py:33-35, 59-61, 73-75`; `plugins/atx/gpio.py:124`; `disabled.py:42` |

### MSD

| fact | citation |
|---|---|
| `set_params`'s first keyword is `name`, not `image`; only the REST layer calls it `image`. | `plugins/msd/__init__.py:167-174` |
| `set_params` raises `MsdConnectedError` while connected. | `plugins/msd/otg/__init__.py:396` |
| `cdrom` and `rw` are mutually exclusive, last-one-wins. | `otg/__init__.py:404-412` |
| An empty `image` **deselects** rather than erroring. | `api/msd.py:82`, `otg/__init__.py:398-402` |
| `write_image` raises `MsdImageExistsError` on a duplicate name and holds the exclusive region for the whole download. | `otg/__init__.py:1170` |
| `MsdFileWriter.write_chunk` returns the **cumulative** bytes written, not the chunk length — assign, do not `+=`. | `plugins/msd/__init__.py:294-319` |
| The 7-day read timeout is a bare inline literal in the REST route, not a constant or a config option; it is repeated here. | `api/msd.py:269` |
| Image names are storage-relative keys with no leading slash; free space lives under the **empty-string** partition key. | `plugins/msd/otg/storage.py:249-255`, `api/msd.py:282` |

### WoL

| fact | citation |
|---|---|
| `WolApi` takes no constructor arguments and is built inline with no reference kept, so this module builds its own. | `api/wol.py:43-46`, `server.py:229` |
| `POST /wol/wake` gathers per-interface booleans and discards them, reporting success unconditionally. | `api/wol.py:145-150` |
| There is no name→MAC resolution in `wol.py`; records live in `/etc/kvmd/user/wol_list.json` as `{ip, mac, name}`. | `api/wol.py:105-116, 186-190` |
| `valid_mac` lives in `api/common.py:215`, not `kvmd/validators/`, and raises `BadRequestError` (an `HttpError`), not `ValidatorError`. | `api/common.py:215` |

## Performance budget

**No number in the "measured" column has been filled in. The module was written
and reviewed off-device: there is no GL-RM1PE and no `ustreamer` C extension in
the development sandbox, so nothing below has been timed. Do not quote these as
results.** Fill the column from a real unit before the PR is merged, using the
[on-unit checklist](#on-unit-checklist).

| call | target | measured |
|---|---|---|
| `see` full, 1024x768 | < 30 ms server time | **NOT YET MEASURED — to be filled from a real unit** |
| `see` region, 1024x768 | (record; no target) | **NOT YET MEASURED — to be filled from a real unit** |
| `see` region, 1920x1080 | (record; no target) | **NOT YET MEASURED — to be filled from a real unit** |
| `see` preview, 1024x768 | (record; no target) | **NOT YET MEASURED — to be filled from a real unit** |
| `see` preview, 1920x1080 | (record; no target) | **NOT YET MEASURED — to be filled from a real unit** |
| `read` | < 400 ms (NPU) | **NOT YET MEASURED — to be filled from a real unit** |
| `wait_for` idle cost | one OCR per `every_s`, no CPU between | **NOT YET MEASURED — to be filled from a real unit** |
| `type`, 1000 chars | bounded by the HID rate, not by this module | **NOT YET MEASURED — to be filled from a real unit** |
| VmRSS across 1,000 `wait_for` polls | no growth (`/proc/self/status`) | **NOT YET MEASURED — to be filled from a real unit** |
| VmRSS across 200 `see` calls | no growth | **NOT YET MEASURED — to be filled from a real unit** |

What can be said without a device, structurally rather than numerically:

- `see full` with `max_width=0` performs **no pixel decode at all** — it returns
  ustreamer's bytes and parses only the JPEG header for the reported size.
- Every other `see` mode is exactly **one** PIL decode and one encode, with the
  image closed in a `finally` and no buffer retained across calls.
- `wait_for` holds no snapshot between polls; only a counter and the last text
  string survive the loop.
- The only cache in the module is a module-level
  `@functools.lru_cache(maxsize=4)` on `build_symmap`, keyed on
  `(path, st_mtime)` — mirroring `api/hid.py:206-210`, but on a free function so
  it does not pin the `McpApi` instance the way `HidApi` pins itself. There is no
  frame cache, no differ, and no thread pool. `StreamerSnapshot.make_preview`'s
  own `lru_cache` is avoided entirely.

Per the brief: if a target is missed, **report it — do not "optimise" by adding
machinery**. These numbers are what decide whether frame differencing moves
on-device later (D-002).

## On-unit checklist

Manual, to be run on a real GL-RM1PE with a target machine attached, and pasted
into the PR with its output.

- [ ] `initialize` returns `serverInfo.name == "kvmd-mcp"` and the running kvmd
      version.
- [ ] `tools/list` returns all 17 tools with schemas.
- [ ] `see` returns a JPEG that opens, with `online=True` and a plausible
      `source=WxH`, on a live signal.
- [ ] `see` on a disconnected input returns `online=False` and the placeholder,
      not an error.
- [ ] `read` on a text console returns the console's text.
- [ ] `wait_for "login:"` across a real reboot: trigger `press reset`, then
      `wait_for` and confirm it returns once with `found: true` and a sane
      `polls` count. (Use `timeout_s <= 50` unless `/api/mcp` has been given its
      own nginx location.)
- [ ] `type` a login and a password, then `key {"name":"Enter"}`; confirm the
      login succeeds and that `events` is roughly `2 * len`.
- [ ] `power reset_hard` with `wait=false` returns cleanly, and `state` shows the
      machine coming back.
- [ ] `power` with `wait=true` returns the documented `isError` about the glatx
      fork bug, **not** a 500.
- [ ] `fetch_iso` from the HTTP export of the NAS `/isos` share; confirm `size`
      matches, and verify the SHA256 client-side against `SHA256SUMS`.
- [ ] `mount` that image, confirm the target sees the virtual drive, `unmount`,
      `remove_image`.
- [ ] `mount` while something is already mounted succeeds (it disconnects
      first), and `mount` with `rw=true` returns `cdrom: false`.
- [ ] `wake` by `name` from `wol_list.json` returns per-interface booleans.
- [ ] Memory before/after: VmRSS of the kvmd process before and after 1,000
      `wait_for` polls and 200 `see` calls.
- [ ] `grep 'mcp ' /var/log/kvmd.log` shows one line per call with the client IP,
      the duration, and **no** typed text or passwords.
- [ ] Reboot the unit and confirm the endpoint comes back with no manual step.

## Out of scope

Deliberately not in this change (brief section 1):

- **Frame differencing.** Stays in the client (`framediff.py`). Pillow is on the
  device, so a later change may move fingerprint/tile hashing on-device once
  `see`'s real cost is known — not before.
- **New auth, scopes, signed requests, manifests.** The endpoint uses kvmd's
  existing auth and nothing else.
- **Any new dependency.** stdlib, aiohttp, PIL, and what kvmd already imports.
  Nothing was added to the PKGBUILD.
- **Any change to existing routes.** No REST handler, plugin, or config file was
  touched. In particular the two known fork bugs this module works around —
  `glatx.py:113`'s `async with` on a sync-only region, and
  `kvmd/utils.py`'s `get_logger` `NameError` — were left alone.
- **The nginx config.** The 4 KB body cap and the 60 s read timeout described
  above are documented, not fixed; a `location /api/mcp` block is a separate,
  reviewable change.

## Deferred decisions

From brief section 13, recorded so they are not re-litigated by accident:

- **D-001** MCP lives on the device as a kvmd API module — no separate process,
  no new port, existing auth and firewall. *Done.*
- **D-002** `wait_for` on-device; frame differencing client-side for now. Pillow
  being present makes an on-device differ possible; **deferred until `see` is
  measured.**
- **D-003** No new dependencies on the device. *Holds.*
- **D-004** ISOs arrive over HTTP from an export of the NAS share; no CIFS/NFS on
  the device. Hash verification is a client concern — the device computes none.
  A `sha256` field on the `fetch_iso` result is deferred until it is shown cheap
  for a multi-GB stream on an A53.
- **D-005** Scoped tokens, signed requests and manifests are deferred; the
  launcher scopes tools by host state for now. Per-tool scopes on the device
  itself are a later, separate change.
- **D-006** The module degrades to *absent* after a firmware update, never to a
  broken KVM. A firmware upgrade replaces `kvmd/`; `scripts/apply_to_glkvm.sh`
  re-applies this branch. `_warn_if_newer_kvmd()` logs a WARNING when the running
  kvmd is newer than the `4.82` this was written against, and **never refuses to
  load** — a missing MCP endpoint is visible, a KVM that will not start is not
  acceptable.
