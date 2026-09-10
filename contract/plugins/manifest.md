# Manifest schema

The manifest is authored as YAML (as in `docs/modules/plugins.md`) and travels
on the wire as canonical JSON. The two are the same object; only the encoding
differs. Validation is defined here once and both sides implement exactly it.

## Shape

```yaml
name: <string>
type: atx | msd | hid | ugpio | auth
runtime: device | management
model_compat: ">=rm1pe"
firmware_compat: ">=1.10.0"
entry: plugins/<type>/<name>.py
payload:
  sha256: <64 lowercase hex>
  size: <bytes>
signature:            # STUBBED — defined, never populated in v1
  alg: <deferred>
  value: <deferred>
  key_id: <deferred>
capabilities: []      # management runtime only
```

## Field rules

### `name` (required)

Matches `^[a-z][a-z0-9_]{0,31}$`.

This becomes the module name in `kvmd.plugins.<type>.<name>`, which the device
loader imports. It is constrained to what a Python module name may be, and
leading underscores are excluded because the existing `get_plugin_class` in
`kvmd/plugins/__init__.py` already treats a leading `_` as unknown.

Violation: `manifest.bad_name`.

### `type` (required)

One of `atx`, `msd`, `hid`, `ugpio`, `auth` — the plugin sub-directories that
exist today under `kvmd/plugins/`. A type outside this set has no loader and
cannot be placed anywhere meaningful.

Violation: `manifest.bad_type`.

### `runtime` (required)

`device` or `management`. This is the blast-radius tier and it is load-bearing
for invariant 6: a device refuses to load a `management` plugin, and the server
refuses to load a `device` plugin in-process. A missing or unknown value is not
defaulted — defaulting a security tier is how tiers stop meaning anything.

Violation: `manifest.bad_runtime`.

### `entry` (required)

Matches `^plugins/(atx|msd|hid|ugpio|auth)/[a-z][a-z0-9_]{0,31}\.py$`, and
additionally:

- the `<type>` path segment MUST equal the `type` field
  (else `manifest.entry_type_mismatch`);
- the file stem MUST equal the `name` field
  (else `manifest.entry_name_mismatch`).

`entry` is a **description of the bundle's shape, not an instruction about
where to write**. The loader places into its own root and derives the on-disk
location from `type` and `name`; `entry` is cross-checked against that
derivation and a disagreement is a refusal. This is invariant 1: there is no
input in the manifest that can move the write.

Violation of the pattern itself: `manifest.bad_entry`.

### `model_compat`, `firmware_compat` (required)

A minimal constraint grammar, so both sides agree without importing a version
library:

```
constraint := "*" | op token
op         := ">=" | "<=" | "==" | ""      ("" means exact match)
token      := [A-Za-z0-9][A-Za-z0-9._-]{0,63}
```

Ordering comparisons split the token on `.` and `-` and compare segments
numerically when both are all-digits, bytewise otherwise. `*` matches anything.
This is deliberately small: compatibility gating is a device-side policy
decision, and the contract's job is only to make the expression parse the same
on both sides.

Violation: `manifest.bad_compat`.

### `payload` (required)

- `sha256` — exactly 64 lowercase hex characters, the hash of the bundle bytes.
  Uppercase is a violation, not something to normalise: canonical means one
  spelling. Violation: `manifest.bad_payload_hash`.
- `size` — integer, `1 <= size <= 8388608` (8 MiB). Violation:
  `manifest.bad_payload_size`; a value over the cap is
  `manifest.payload_too_large`.

The cap exists because the receiver is an embedded device that must buffer and
hash the bundle before it may touch the disk. An unbounded payload is a
memory-exhaustion path that the verify gate cannot protect against, because it
is reached before verification is possible.

The cap is enforced at **offer admission**, before a `fetch` is sent and before
any chunk moves — see `wire.md`. Because a dropped transfer restarts from chunk
0, size and link reliability multiply, and a bundle too large to transfer must
be refused while it is still a declaration rather than discovered on the last
chunk.

### `signature` (optional in v1 — the stub)

If present it is an object; its `alg`, `value` and `key_id` members are strings
if present. **v1 implementations MUST NOT reject a manifest for a missing,
empty or unrecognised `signature`, and MUST NOT treat its presence as
meaningful.** The `hash-only` verifier ignores it entirely.

The block exists now purely so that signing lands as an implementation change
behind the `Verifier` seam and not as a schema migration across a fleet of
already-deployed devices.

When signing lands, a `signed` verifier will refuse a manifest whose signature
is absent or does not verify against the pinned anchor. That is a verifier-tier
change and a config change; nothing in this schema moves.

### `capabilities` (conditional)

An array of strings, each matching `^[a-z][a-z0-9_.]{0,63}$`.

Permitted **only** when `runtime` is `management`. For `runtime: device` it
MUST be absent or empty; a non-empty `capabilities` on a device-runtime plugin
is `manifest.capabilities_not_allowed`. Device plugins draw their blast radius
from the console they run on, not from a capability grant, and allowing the
field there would create a second, weaker authorisation story.

## Unknown fields

Unknown top-level fields are **rejected** (`manifest.malformed`), not ignored.
This costs forward compatibility and buys the thing worth more: a device and a
server can never disagree about what a manifest said. Extension happens by
bumping `v`.

## Canonical JSON encoding

Keys sorted bytewise ascending, UTF-8, no insignificant whitespace, integers
without exponent or fraction. `signature` and `capabilities` are omitted
entirely when absent rather than encoded as `null`.
