# Invariants as a test contract

The six invariants from `docs/modules/plugins.md` hold regardless of trust
model. They are written here as claims each repo's suite must assert, with the
vectors that carry the shared cases. Where a claim can only be asserted against
a repo's own implementation (placement, rollback, loading), the vector supplies
the inputs and the expected outcome, and each repo asserts it locally.

Status column: **now** = assertable in this cycle against the stub verifiers;
**half** = asserted by the repo half that owns the behaviour.

---

## 1. A plugin loads only from a loader-owned location

> Never an arbitrary path from the manifest.

The manifest cannot express a destination. The loader derives the on-disk
location from `type` and `name` alone; `entry` is cross-checked against that
derivation and a disagreement is a refusal, not a redirection.

- `manifest.entry_type_mismatch` and `manifest.entry_name_mismatch` fire.
- Traversal, absolute paths and backslashes are refused at
  `manifest.bad_entry`, and again at unpack as `bundle.unsafe_path`.
- These checks run for **every** verifier, `noop` included.

Vectors: `vectors/manifest.json` ids `entry-*`, `name-*`.
Status: **now** (validation) + **half** (placement derivation).

---

## 2. Push is idempotent

> The same manifest pushed twice is a no-op.

The second `offer` of a `payload.sha256` that is already installed **and whose
on-disk tree still matches** is answered `install_result state:"noop"` with no
`fetch`, no write and no reload.

If the hash is installed but the tree has drifted, it is *not* a no-op — that
is a repair, and it proceeds as a normal install.

Status: **half** (device owns the disk truth; server asserts it does not
re-push on `noop`).

---

## 3. A failed Verify refuses install — **the load-bearing one**

> Prove with an always-fail verifier: the refuse path must fire.

With `always-fail` configured, an offer+payload that is otherwise perfectly
valid results in `install_result state:"refused"`, `reason:"verify.refused"`,
and **nothing on disk**: no unpack, no temp tree, no placement, no load.

This test is **mutation-checked**: remove the refuse-on-fail branch from the
gate and the test must go red. It is written now against a stub and becomes
the real signature-verification guard later, unchanged.

It must have teeth before `noop` exists anywhere in a tree, because `noop`
accepting everything is precisely the thing this test proves is contained.

Vectors: `vectors/verify.json` ids `gate-alwaysfail-*`, `gate-order-*`.
Status: **now** (the gate refuses) + **half** (nothing reaches the disk).

---

## 4. Read-back is mandatory

> Install is not "done" until the on-disk hash is reported and matches.

An `installed` result is not terminal. The server holds the install open until
a `readback` arrives; a `tree_sha256` that differs from the server's own
recomputation from the bundle it sent is flagged as
`install.readback_mismatch` drift.

Drift is flagged, never ignored and never silently re-pushed — a device that
disagrees with the catalog is a fact to surface, not a race to win.

Vectors: `vectors/treehash.json` (both sides must compute the same tree hash,
or every readback comparison is meaningless).
Status: **now** (tree hash agreement) + **half** (the open-until-readback
state machine and the drift flag).

---

## 5. Identical verify path for local vs pushed

> Same `Verify` call, same place/load, same readback.

Local drop-in and fleet push are two **sources** feeding one
**verify-and-load** path. Downstream of the gate they are indistinguishable:
the same gate call with the same arguments, the same placement, the same
rollback, the same readback emission.

The device half drives both sources through the path and asserts the
post-gate observations are identical. Trust is the verification result, never
the delivery channel — so there is no code path where "it arrived locally" or
"it came from the server" is an input to the decision.

Status: **half** (device), and it is the invariant that makes "local +
centralized" free rather than a second mechanism.

---

## 6. Runtime tiers are not crossed

> `management` plugins are not loaded by a device; `device` plugins are not
> loaded in-process by the server.

Both refusals report `policy.wrong_runtime`. This is blast-radius separation:
a device plugin's worst case is one console, a management plugin's worst case
is the fleet, and the two must never be reachable through the same load path.

Enforced as policy at each loader, deliberately **not** in the gate — see
`verifier.md` on keeping the gate's single claim small.

Vectors: `vectors/manifest.json` ids `runtime-*`.
Status: **now** (parse) + **half** (each side refuses the other's tier).

---

## Cross-cutting, also tested now

- **Contract sync** — each repo recomputes `CONTRACT-SHA256` over its vendored
  copy. A one-sided contract edit fails that repo's own suite.
- **Canonical JSON** — encoding a manifest and re-encoding the decode is
  byte-stable, in both languages, over the same vectors.
- **Frame round-trip** — every sub-type encodes and decodes to the same bytes
  on both sides (`vectors/frames.json`), including the malformed cases.
- **Chunk reassembly** — a payload split at chunk boundaries reassembles to the
  original bytes; a gap, a repeat, an unknown flag bit and an oversized chunk
  each refuse.
