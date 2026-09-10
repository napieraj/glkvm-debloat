# The `Verifier` seam and the verify gate

## Why a seam and not a gate-keeper

Signing is deferred, but *the place signing will go* is not. Everything in this
foundation — transport, manifest, placement, rollback, readback — is identical
whichever crypto eventually lands. So the crypto is a hook, and the hook is
specified now, filled later. Nothing downstream of the hook knows or cares
which implementation is behind it.

## The interface

```
Verify(manifest, payload) -> ok | reason
```

Go (`kazbek`, `internal/plugins`):

```go
type Verifier interface {
    Name() string
    Verify(m *Manifest, payload []byte) error   // nil == ok
}
```

Python (`glkvm-debloat`, `kvmd/pluginmgr`):

```python
class Verifier(abc.ABC):
    @property
    @abc.abstractmethod
    def name(self) -> str: ...

    @abc.abstractmethod
    def verify(self, manifest: Manifest, payload: bytes) -> None:
        """Return normally on success, raise VerifyError(code) to refuse."""
```

The two shapes are idiomatic in their own languages and semantically
identical: success is silent, refusal carries a code from `errors.md`.

## Implementations

| Name        | Status      | Behaviour |
|-------------|-------------|-----------|
| `noop`      | dev only    | Accepts any payload. **Never a default in any real config.** |
| `hash-only` | v1 floor    | Refuses unless `sha256(payload) == manifest.payload.sha256`. Integrity without authenticity. |
| `signed`    | **later**   | Verifies `signature` against the pinned trust anchor. Not in this cycle. |

A test-only `always-fail` verifier also exists in both repos. It is not a
deployable tier; it exists so invariant 3 has something with teeth to bite.

### On `noop`

`noop` accepts any *payload*. It does **not** skip the gate's structural
checks — see below. That distinction is the whole reason `noop` is tolerable
in a tree at all: it disables authenticity checking, not path safety. A `noop`
verifier still cannot be used to write outside the loader-owned root, load a
mismatched module name, or install an oversized bundle.

Configuration MUST fail closed: an absent or unrecognised verifier name
resolves to a refusal, never to `noop`.

## The verify gate

Both halves call **the gate**, never a `Verifier` directly. The gate is the
single choke point where an install can be refused, which is what makes
invariant 3 a single testable claim rather than a property scattered across two
codebases.

```
Gate(verifier, manifest, payload):
    1. ValidateManifest(manifest)            -> refuse with the manifest.* code
    2. len(payload) == manifest.payload.size -> else refuse payload.size_mismatch
    3. verifier.Verify(manifest, payload)    -> else refuse with its code
    ok
```

Contract on the caller, and the reason `refused` and `failed` are separate
states in `install_result`:

> **If the gate refuses, the caller MUST NOT unpack, place, or load. Nothing
> may touch the disk.**

Steps 1 and 2 run **before** the verifier and run for every verifier including
`noop`. Step 2 is not redundant with `hash-only`: it bounds the work done
before hashing and it holds even when the configured verifier does not hash.

Ordering is part of the contract, not an implementation detail — vectors assert
which code comes back when a manifest is invalid *and* the payload is corrupt,
so the two implementations cannot diverge on precedence.

## What the gate is not

The gate does not decide compatibility (`model_compat`, `firmware_compat`) and
does not enforce the runtime tier. Those are policy decisions belonging to the
side doing the loading:

- the device refuses `runtime: management` (invariant 6);
- the server refuses to load `runtime: device` in-process (invariant 6);
- the device applies `model_compat` / `firmware_compat` against itself.

Keeping policy out of the gate keeps the gate's single claim — "unverified
plugins do not reach the disk" — small enough to be obviously true.

## The swap, later

When the signing module lands:

1. A `signed` verifier implements the same interface.
2. Config selects it instead of `hash-only`.
3. The `signature` block, already in the schema, is populated.

Steps 1–3 touch no transport, no manifest schema, no placement code, no
rollback, no readback, and no invariant. The gate's shape is unchanged and
invariant 3's test is unchanged — it simply becomes a real
signature-verification guard rather than a stub one. That is the point of
writing it now.
