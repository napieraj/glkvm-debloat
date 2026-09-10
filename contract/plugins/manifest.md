# Manifest schema

The manifest is authored as YAML (as in `docs/modules/plugins.md`) and travels
on the wire as canonical JSON. The two are the same object; only the encoding
differs. Validation is defined here once and both sides implement exactly it.

## Shape

```yaml
name: <string>
revision: <integer>          # monotonic, anti-rollback — mandatory
type: atx | msd | hid | ugpio | auth
runtime: device | management
model_compat: ">=rm1pe"
firmware_compat: ">=1.10.0"
entry: plugins/<type>/<name>.py
payload:
  sha256: <64 lowercase hex>
  size: <bytes>
signature:                   # required; shaped for every model, populated by none yet
  model: hash-only           # required enum; v2 accepts only this value
  entries: []                # required list; v2 requires it empty
  threshold: <integer>       # optional
  expires: <ISO-8601>        # optional
sandbox: []                  # optional; v2 requires it empty
```

## Field rules

### `name` (required)

Matches `^[a-z][a-z0-9_]{0,31}$`.

This becomes the module name in `kvmd.plugins.<type>.<name>`, which the device
loader imports. It is constrained to what a Python module name may be, and
leading underscores are excluded because the existing `get_plugin_class` in
`kvmd/plugins/__init__.py` already treats a leading `_` as unknown.

Violation: `manifest.bad_name`.

### `revision` (required)

A monotonic integer, `>= 1`. Violation: `manifest.bad_revision`.

The device refuses any bundle whose `revision` is less than or equal to the
revision already installed for that `name`. This closes the downgrade and
freeze attack class — re-serving a genuinely-signed older plugin with a known
flaw — and it does so **independent of any signing model**, because it is an
integer comparison and nothing more.

That independence is why it lands now rather than with signing. Even mature
implementations get this subtly wrong; the referenced research cites a
rollback-protection bug in go-tuf. A comparison this small is worth owning
outright rather than inheriting.

The check runs at **offer admission**, before a `fetch` is sent: the device
already knows its installed revision, so there is no reason to transfer a
bundle it will reject. The refusal is `install_result` `state:"refused"` with
`reason:"policy.rollback_refused"` — `refused`, not `failed`, because nothing
touched the disk.

`revision` is separate from any human-facing version string. It orders
releases for the machine; it is not required to be meaningful to a person.

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

### `signature` (required — shaped now, populated later)

```yaml
signature:
  model: hash-only     # required
  entries: []          # required
  threshold: <integer> # optional
  expires: <ISO-8601>  # optional
```

- `model` — required. **v2 accepts exactly one value, `hash-only`.** Any other
  value is `manifest.malformed`: a manifest declaring a trust model this
  implementation does not have is not merely invalid, it is uninterpretable,
  and guessing at it is precisely the failure this field exists to prevent.
- `entries` — required list, one entry per signer. **v2 requires it empty.** A
  non-empty list is `manifest.malformed`, because a v2 implementation cannot
  check a signature and must not accept a manifest that claims one.
- `threshold` — optional integer, for a future K-of-N model.
- `expires` — optional ISO-8601 instant, for future expiring metadata.

The block is **required** rather than optional so that every manifest states
its trust model explicitly. That is what makes the later swap safe: a `signed`
verifier refuses `model: hash-only` outright, instead of having to infer intent
from an absent field. An optional block would leave "unsigned" and "signature
omitted" indistinguishable, which is the ambiguity a downgrade attack lives in.

Populating `entries` — algorithms, key custody, threshold policy, transparency
logs — is the signing module and is explicitly out of this cycle. The shape is
here so that work is an implementation behind the `Verifier` seam and a config
change, never a schema migration across a fleet of deployed devices.

### `sandbox` (optional — reserved, must be empty)

An array declaring what the plugin process itself may reach: filesystem paths,
network egress, devices. **v2 requires it absent or empty.** A non-empty value
is `manifest.sandbox_not_allowed` — the field is reserved so the vocabulary can
land without a schema migration, and refused until that vocabulary exists,
because accepting a declaration nothing enforces would be worse than having no
field at all.

It is deliberately **not** called `capabilities`. kazbek already has a
capability vocabulary — `permission.Key` values such as `device.read` and
`auth.write`, which `middleware.Require` calls "capability keys" and which are
scoped to *subjects*: which user may perform which action. What this field will
describe is entirely different: which resources a plugin *process* may touch.
Two vocabularies under one word, in a system whose whole authorization model
turns on that word, is a bug waiting to be written by someone who reads the
wrong one.

## Unknown fields

Unknown top-level fields are **rejected** (`manifest.malformed`), not ignored.
This costs forward compatibility and buys the thing worth more: a device and a
server can never disagree about what a manifest said. Extension happens by
bumping `v`.

## Canonical JSON encoding

Keys sorted bytewise ascending, UTF-8, no insignificant whitespace, integers
without exponent or fraction. `signature` and `capabilities` are omitted
entirely when absent rather than encoded as `null`.
