# Wire protocol

Plugins ride the **existing** device connection. There is no new socket, no new
TLS context and no new handshake: the channel is the pinned-mTLS tunnel that
already carries register/heartbeat/cmd/file/http traffic.

## Envelope (unchanged)

The device connection's existing frame, as implemented by `Device.ReadMsg` /
`Device.WriteMsg` in `kazbek`:

```
+--------+------------------+---------------------+
| type:1 | len:2 big-endian | body: `len` bytes   |
+--------+------------------+---------------------+
```

`len` is a **uint16**, so a body is at most 65535 bytes. This is the single
hardest constraint on the design and is why payloads are chunked: a plugin
bundle does not fit in a frame and never will.

## Plugin message type

```
type = 0xF1   (PLUGIN)
```

`0xF1` sits in the custom-extension range that `kazbek` already reserves above
the upstream rtty message types (`0xF0` is `DEVICE_INFO`). Upstream types run
`0x00`–`0x09`; keeping extensions at `0xF0`+ leaves room for upstream to grow
without collision.

## Plugin body

Every plugin frame body is:

```
+---------+-------+---------------------------+
| tid:32  | sub:1 | payload: len-33 bytes     |
+---------+-------+---------------------------+
```

- `tid` — transfer id: exactly 32 ASCII characters, lowercase hex
  (16 random bytes, hex-encoded). This deliberately matches the existing
  32-byte `sid` convention used by the login/termdata/file messages, so the
  device-side framing code shape is unchanged.
- `sub` — sub-type byte, below. This mirrors the existing `msgTypeFile`
  pattern, where one envelope type carries a leading sub-type byte.

A body shorter than 33 bytes is malformed and the connection is dropped, which
is how every other message type in this protocol handles a short read.

Maximum plugin payload per frame: `65535 - 33 = 65502` bytes.

## Sub-types

| `sub` | Name             | Direction        | Body encoding |
|-------|------------------|------------------|---------------|
| 0x00  | `offer`          | server -> device | canonical JSON |
| 0x01  | `fetch`          | device -> server | canonical JSON |
| 0x02  | `payload`        | server -> device | binary chunk   |
| 0x03  | `install_result` | device -> server | canonical JSON |
| 0x04  | `readback`       | device -> server | canonical JSON |

There is no `abort` sub-type. A refusal, a failed load and a rolled-back
install are all reported through `install_result` with the appropriate `state`,
so there is exactly one place a transfer can end unhappily and exactly one code
path that reports it.

## Canonical JSON

Every JSON body is UTF-8, with **object keys sorted bytewise ascending**, no
insignificant whitespace, and no trailing newline. Canonical form is required
so that a body can be hashed reproducibly by either side — the signing module
will need exactly this property and gets it for free by being specified now.

Every JSON body carries `"v": 2`. A receiver that does not recognise `v`
refuses with `manifest.unsupported_version` rather than guessing.

Version 2 is the current protocol. It differs from version 1 by three manifest
changes — a mandatory monotonic `revision`, a structured and required
`signature` block, and `capabilities` renamed to `sandbox` and reserved. All
three are schema changes, and because unknown manifest fields are refused
rather than ignored, they could not be added compatibly. That is the bump
working as designed: extension happens by version, so strictness costs nothing
that cannot be bought back deliberately.

## Message bodies

### `offer` (0x00) — server -> device

"This plugin is available." Manifest only; no payload bytes.

```json
{"manifest":{...},"v":1}
```

`manifest` is the object defined in `manifest.md`. The device validates it
(see `verifier.md`, gate step 1) and, if it wants the bytes and does not
already have this exact plugin installed, replies with `fetch`.

A device that already has the offered `payload.sha256` installed and matching
replies with `install_result` `state:"noop"` and does **not** fetch. This is
invariant 2 (idempotent push) and it is resolved on the device, because the
device is the only party that knows the truth about its own disk.

### `fetch` (0x01) — device -> server

```json
{"sha256":"<64 lowercase hex>","v":1}
```

Requests the bundle for a previously offered manifest, keyed by its
`payload.sha256`. The server refuses to serve a hash it has not offered on this
connection — a device cannot use `fetch` to enumerate the catalog.

There is no resume/offset in v1. A dropped transfer is retried from the start;
bundles are capped and the tunnel is already reliable, so resume is complexity
without a paying customer.

Because a retry restarts from chunk 0, bundle size and link reliability
multiply: a large bundle over a lossy link may never complete. v1 bounds that
rather than solving it, and the bound is enforced **before the first chunk
moves**:

> **A device MUST admit an offer before sending `fetch`.** Admission validates
> the manifest, which refuses `manifest.payload_too_large` for a declared
> `payload.size` above the cap, and compares `revision` against the installed
> revision, which refuses `policy.rollback_refused` for a downgrade. A bundle
> too large to transfer, or older than what is already installed, is refused
> while it is still a claim rather than discovered on the last chunk.

Anti-rollback belongs at admission for the same reason the size ceiling does:
the device already knows its installed revision, so there is no reason to
transfer a bundle it will reject. Both refusals report `state:"refused"` — not
`failed` — because nothing touched the disk.

Admission is a distinct check from the verify gate's step 2. Gate step 2
compares the *assembled* length against the declared size and can only run once
the bytes have arrived. Admission compares the *declared* size against the
protocol ceiling and runs before any arrive. Neither substitutes for the other:
without admission an oversized bundle is transferred in full and then refused;
without gate step 2 a truthful declaration is never checked against reality.

The receiver additionally bounds reassembly at exactly `payload.size`, so a
sender that declares one size and streams more is cut off at the offending
chunk rather than at the end of the transfer.

### `payload` (0x02) — server -> device

```
+---------+-------+----------+--------+------------------+
| tid:32  | 0x02  | seq:4 BE | flags:1| data: <= 32768 B |
+---------+-------+----------+--------+------------------+
```

- `seq` — chunk sequence, starting at 0 and incrementing by exactly 1. A
  receiver that sees a gap or a repeat drops the transfer; it does not attempt
  to reorder.
- `flags` — bit 0 (`0x01`) is `LAST`. All other bits MUST be zero and a
  receiver MUST refuse a frame with unknown bits set, so that adding a flag
  later cannot be silently ignored by an old device.
- `data` — at most `PAYLOAD_CHUNK_MAX` = 32768 bytes. The envelope would permit
  65502; 32768 is chosen to leave clear headroom under the uint16 ceiling and
  to be a size an embedded device can buffer without thought.

The concatenation of `data` across `seq` 0..N is the bundle. The receiver
checks the assembled length against `payload.size` and the assembled hash
against `payload.sha256` before anything is unpacked.

### `install_result` (0x03) — device -> server

```json
{"reason":"","sha256":"<64 hex>","state":"installed","v":1}
```

`state` is one of:

| `state`     | Meaning |
|-------------|---------|
| `installed` | Verified, placed, loaded. A `readback` follows. |
| `noop`      | This exact `payload.sha256` was already installed and on-disk state matches. Nothing was written. |
| `refused`   | The verify gate said no. **Nothing was unpacked, placed or loaded.** |
| `failed`    | Verify passed but place-or-load failed. The install was rolled back; the device is on its previous state. |

`reason` is a code from `errors.md`, or `""` when `state` is `installed` or
`noop`. It is a code and not prose so the server can act on it.

`refused` and `failed` are deliberately distinct. `refused` means the plugin
never touched the disk — it is the observable signature of invariant 3.
`failed` means the disk was touched and then restored. Collapsing them would
make invariant 3 untestable from the server's side.

### `readback` (0x04) — device -> server

```json
{"entries":[{"path":"...","sha256":"..."}],"sha256":"<64 hex>","tree_sha256":"<64 hex>","v":1}
```

Sent after every `installed`. Reports what is **actually on disk**, hashed by
the device, not what the device was told to write.

> **The device MUST re-read the placed files from the loader-owned location and
> hash those bytes. It MUST NOT hash the bundle it received.**

This is the whole point of the message, and the two are the same value only in
the happy path. They differ in exactly the cases readback exists for: a partial
write, a failed rename, an overlay that did not survive the ro remount, or a
later local edit. Hashing the in-memory bundle proves the transfer arrived
intact — which the chunk sequencing already told you — and proves nothing about
the disk. Hashing the re-read files proves the device's disk matches what was
sent, which is the only claim worth making, and it is the claim drift detection
and any later migration attestation actually lean on.

- `sha256` — echoes the manifest's `payload.sha256`, identifying the transfer.
- `tree_sha256` — the canonical tree hash (below) of the placed tree.
- `entries` — per-file detail, sorted by `path`, so drift is actionable rather
  than merely detected. Capped at 64 entries; a larger tree reports
  `tree_sha256` only and an empty `entries`.

The server recomputes the expected tree hash **from the bundle it still holds**
and compares. This is why the manifest needs no extra hash field: the server
has the bytes it sent, so it can derive the expectation itself. The device
derives its side from the disk, the server from the bundle, and the comparison
is meaningful precisely because the two are computed from different sources.

An install is not complete until a `readback` arrives and matches. A mismatch
is flagged as drift — it is never ignored and never silently re-pushed.

## Canonical tree hash

Defined here because both sides must compute it identically, and vectors in
`vectors/treehash.json` prove that they do.

```
for each regular file in the placed tree:
    p = path relative to the plugin root, POSIX separators, no leading "./"
lines = sorted(p bytewise ascending) mapped to:
    sha256_hex(file_bytes) + "  " + p + "\n"        (two spaces, as sha256sum)
tree_sha256 = sha256_hex(concat(lines))
```

Directories, symlinks, hardlinks, device nodes and file modes are **not**
hashed and are **not permitted** in a v1 bundle, so there is nothing to
disagree about. An empty tree hashes to the sha256 of the empty string.

## Bundle format

A v1 bundle is an **uncompressed POSIX ustar archive** containing regular files
only. Both sides already have a tar reader in their standard library
(`archive/tar`, `tarfile`), so the bundle costs no dependency on the device.

A bundle is rejected before unpacking if any entry:

- is not a regular file (no symlinks, hardlinks, directories, devices, FIFOs);
- has an absolute path, a `..` component, a drive letter or a backslash;
- has a path that is not NFC-safe printable ASCII;
- would place a file outside the plugin root.

These checks are not defence in depth over the verify gate — they are the
reason a `noop` verifier is survivable. Path safety is structural and is
enforced regardless of which `Verifier` is configured.
