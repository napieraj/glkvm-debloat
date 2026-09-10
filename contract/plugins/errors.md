# Refusal reason codes

A refusal carries a **code**, never prose. The code is what crosses the wire in
`install_result.reason`, what a `Verifier` raises, and what a conformance
vector asserts. Both implementations use exactly these strings.

## Manifest validation (gate step 1)

| Code | Meaning |
|------|---------|
| `manifest.malformed` | Not canonical JSON, not an object, missing a required field, or carrying an unknown top-level field. |
| `manifest.unsupported_version` | `v` is absent or not `1`. |
| `manifest.bad_name` | `name` fails `^[a-z][a-z0-9_]{0,31}$`. |
| `manifest.bad_type` | `type` is not one of `atx`, `msd`, `hid`, `ugpio`, `auth`. |
| `manifest.bad_runtime` | `runtime` is not `device` or `management`. |
| `manifest.bad_entry` | `entry` fails the entry pattern. |
| `manifest.entry_type_mismatch` | `entry`'s type segment disagrees with `type`. |
| `manifest.entry_name_mismatch` | `entry`'s file stem disagrees with `name`. |
| `manifest.bad_compat` | `model_compat` or `firmware_compat` does not parse. |
| `manifest.bad_payload_hash` | `payload.sha256` is not 64 lowercase hex. |
| `manifest.bad_payload_size` | `payload.size` is absent, non-integer, or `< 1`. |
| `manifest.payload_too_large` | `payload.size` exceeds 8388608. |
| `manifest.capabilities_not_allowed` | Non-empty `capabilities` with `runtime: device`. |
| `manifest.bad_capability` | A capability string fails `^[a-z][a-z0-9_.]{0,63}$`. |

## Payload checks (gate step 2, and assembly)

| Code | Meaning |
|------|---------|
| `payload.size_mismatch` | Assembled payload length differs from `payload.size`. |
| `payload.hash_mismatch` | `sha256(payload)` differs from `payload.sha256`. Raised by `hash-only`. |

## Verifier (gate step 3)

| Code | Meaning |
|------|---------|
| `verify.refused` | The verifier refused without a more specific code. What `always-fail` raises. |
| `verify.unconfigured` | No verifier configured, or an unrecognised name. Fails closed; never falls back to `noop`. |

## Bundle unpacking (device side, after the gate)

| Code | Meaning |
|------|---------|
| `bundle.malformed` | Not a readable ustar archive. |
| `bundle.unsafe_path` | An entry path is absolute, escapes the root, or contains a backslash or non-printable-ASCII. |
| `bundle.unsafe_entry` | An entry is not a regular file. |
| `bundle.entry_missing` | The archive does not contain the file named by `entry`. |

## Transport

| Code | Meaning |
|------|---------|
| `wire.bad_frame` | Body shorter than 33 bytes, or an unknown sub-type. |
| `wire.bad_sequence` | A payload chunk `seq` gap or repeat. |
| `wire.bad_flags` | A payload chunk with unknown `flags` bits set. |
| `wire.unsolicited` | A `fetch` for a hash not offered on this connection. |
| `wire.chunk_too_large` | A payload chunk carrying more than 32768 data bytes. |

## Policy (not the gate — see `verifier.md`)

| Code | Meaning |
|------|---------|
| `policy.wrong_runtime` | A device was offered `runtime: management`, or the server was asked to load `runtime: device` in-process. Invariant 6. |
| `policy.incompatible_model` | `model_compat` excludes this device. |
| `policy.incompatible_firmware` | `firmware_compat` excludes this firmware. |

## Install outcome

| Code | Meaning |
|------|---------|
| `install.load_failed` | Verified and placed, but the loader rejected it. Rolled back. |
| `install.place_failed` | Verified, but placement failed. Rolled back. |
| `install.readback_mismatch` | On-disk tree hash does not match what was sent. Flagged as drift. |
