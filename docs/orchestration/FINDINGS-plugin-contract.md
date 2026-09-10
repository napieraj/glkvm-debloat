# Plugin contract findings — 2026-09-10

> **STATUS: all six resolved or recorded.** Findings 1, 2 and 4 are fixed in
> both halves with mutation-checked tests and shared conformance vectors.
> Findings 3 and 5 are constraints on code that does not exist yet and are
> recorded at the definitions someone would undo them at. Finding 6 is
> informational. Everything below is the original report; the resolution of
> each is appended at the end.

From the branch-scoping pass. **Provenance is marked on every item**: what this
orchestrator executed itself, versus what a subagent measured and this orchestrator
has not independently reproduced. Per the working agreement, a relayed measurement
is a claim with a source, not a fact.

## 1. `_check_path` admits bytecode and native objects — VERIFIED HERE

Executed directly against `kvmd/pluginmgr/bundle.py` on
`claude/repo-status-report-6vi5r1`:

```
ACCEPTED  plugins/atx/__pycache__/evil.cpython-311.pyc
ACCEPTED  plugins/atx/evil.so
ACCEPTED  plugins/atx/probe.py
refused   ../escape.py   -> RefusalError
refused   /abs.py        -> RefusalError
```

`_check_path` (bundle.py:81-103) refuses absolute paths, backslashes, traversal
segments, trailing slashes and non-printable ASCII. It does not refuse a
`__pycache__` segment, a `.pyc`/`.pyo` suffix, or a `.so`. `require_entry` only
asserts the manifest's declared entry is *present*, never that it is *alone*.

## 2. A forged `.pyc` is invisible to readback — AGENT-MEASURED, not reproduced here

Reported by the `plugin-device-placement` scoping agent, with an end-to-end
measurement: a `.pyc` whose header (mtime, size) matches its `.py` is executed in
preference to the source even in a fresh interpreter after `cache_clear()`,
`del sys.modules[...]` and `importlib.invalidate_caches()`. They rewrote
`probe.py` from `VERSION = 1` to `VERSION = 2` at identical size and mtime-second
and got `VERSION = 1` back four times; deleting `__pycache__` returned `2`.

Composed with finding 1, that means **a bundle can carry code the device runs
which is not in the `.py` the device shows**. Readback cannot catch it, because
both files are in the bundle, so the device's tree hash and the server's
expectation agree. That is invariant 4 failing silently — the failure mode the
whole readback design exists to prevent.

I have verified the path-acceptance half myself (finding 1). I have **not**
reproduced the `.pyc`-precedence half. It should be reproduced before it is acted
on, and it is cheap to reproduce.

## 3. Load poisons readback — AGENT-MEASURED, not reproduced here

Same agent, measured with tree hashes: create `root/plugins/atx/probe3.py`,
`readback_for("00"*32, root)` → `38013ee7...`; then
`get_plugin_class("atx","probe3")`; then readback again → `a1434df0...`, entries
now including `plugins/atx/__pycache__/probe3.cpython-311.pyc`.

So a naive `place → load → readback` ordering produces `install.readback_mismatch`
on **every successful install**. The fix — readback before load — is free, and
needs a test pinning the order, because the bug only appears once something
imports.

Note this is not a device question. A subagent's attempt to model a read-only
remount with `chmod 0555` failed to model it: running as root, the import wrote
`__pycache__` through the 0555 directory anyway. So the suite must assert "nothing
touched disk" by before/after tree hashing of the store root, never by
permissions. That assertion is strictly stronger and needs no device.

## 4. `WriteMsg` truncates silently at the uint16 boundary — AGENT-MEASURED

Reported reproduced over `net.Pipe`: a 65536-byte body declares `len=0`, and a
70000-byte body declares `len=4464`, both writing the full bytes and returning a
nil error. The envelope cap is the contract's stated hard constraint, which is
why bundles chunk at 32768. A silent wrap at the boundary is a masked defect
rather than a gutted one (rule 5), and it is live today.

Not reproduced here — kazbek Go does not build in this environment without the
frontend workaround. Reproduce before acting.

## 5. `noop` is nameable in production config — AGENT-MEASURED

`Resolve("noop")` returns `VerifierNoop{}` successfully. `always-fail` is
correctly not nameable. `verifier.md` says `noop` is "dev only" and "**never a
default in any real config**" — but nothing enforces that, so a config naming it
silently disables authenticity. `noop` still keeps structural path safety, which
is the only reason it is tolerable in the tree at all; that is unaffected.

## 6. A plugin capability already exists, in the other vocabulary

`internal/authz/model.go:55` on `claude/glkvm-stock-debloat-migration-0pibl7`
declares `CapPluginInstall Capability = "plugin.install"`, and it is in
`AllCapabilities`.

This matters for **D-017** (the `sandbox` vocabulary stays empty): the decision to
keep `sandbox` empty is unaffected and still correct, but it should be recorded
that plugin installation is *already* a named capability on the authz side. The
two vocabularies are distinct on purpose — `sandbox` is deliberately not called
`capabilities` precisely because `permission.Key` and `middleware.Require` already
claim that word — and this is the first place they touch the same subject.

## What to do

Findings 1 and 3 are cheap, local, and ungated: refuse `__pycache__` segments,
`.pyc`/`.pyo` suffixes and native objects at `_check_path`, and order readback
before load. Both want mutation-checked tests.

Finding 2 is the one that changes the threat model, and it should be reproduced
first. Findings 4 and 5 are kazbek-side and want reproduction before action.

None of this is affected by D-016 or D-017 — it is all inside the existing
`hash-only` floor.

---

# Resolution — 2026-09-10, later the same day

Everything relayed as agent-measured above was independently reproduced before
being acted on, per the working agreement. Two of them turned out sharper than
reported.

## 1 + 2, fixed in both halves

Reproduced the `.pyc` precedence directly: a `.py` on disk reading
`VERSION = 2`, with a stale `.pyc` from `VERSION = 1` at matching size and
mtime, imported as **1** in a fresh interpreter after `invalidate_caches()` —
and `__file__` still named the `.py`, so introspection lies too. Deleting
`__pycache__` returned 2.

Then found the report understated it. `.so` is not merely accepted, it **wins**:
`EXTENSION_SUFFIXES` resolve before `SOURCE_SUFFIXES`, so with a valid
`probe.py` and a 16-byte non-ELF `probe.so` present, the import raised
`ImportError` on the `.so` rather than falling through to the source.

Both halves now refuse `__pycache__` path segments and the `.pyc` / `.pyo` /
`.pyd` / `.so` suffixes at admission, before anything reaches disk, with
`bundle.unsafe_entry`. The suffix list is fixed rather than derived from
`importlib.machinery`, so the two languages can agree across CPython versions;
a test asserts every suffix the runtime reports as importable is covered, so a
CPython change reddens the *reason* rather than silently widening the hole.

Four mutations bite in each language: dropping the call, dropping the
`__pycache__` refusal, dropping `.so`, and making the match case-sensitive.

Three shared conformance vectors were added — `unsafe-bytecode-cache`,
`unsafe-native-extension`, `unsafe-sourceless-bytecode` — generated from
`tools/genvectors.py` rather than hand-crafted. `CONTRACT-SHA256` moves
`c2dc4976…` → `4888f9ea…`, vendored byte-identically into both repos. Without
these the two halves would have agreed by construction rather than by contract.

Worth recording: **the contract-hash guard worked.** `test_contract_sha256`
went red the moment the vectors changed and before the recorded hash was
updated — exactly the one-sided-edit alarm it exists to be.

## 3, recorded — placement does not exist yet

Nothing in `kvmd/pluginmgr/` writes to disk, so there is no ordering to fix,
only one to record. The constraint is now in `readback_for`'s docstring, which
is where whoever writes placement will read it, along with the measurement
(`38013ee7…` before a `get_plugin_class()`, `a1434df0…` after) and the warning
that `chmod 0555` does not model the production ro remount — as root the import
writes through it, so the nothing-touched-disk assertion must be a before/after
hash of the store root.

## 4, fixed — and it is worse than truncation

Reproduced over `net.Pipe`: body 100 → declared 100, body 65533 → declared
65533, **body 70000 → declared 4464**, all 70000 bytes written, nil error.

That is frame desynchronisation, not truncation: the peer reads 4464 bytes as
the message and parses the remaining ~65k as further frames, so the tail is
interpreted as attacker-chosen framing. `internal/plugins/wire.go:128` already
refused at this bound — the plugin layer was correct and the rtty transport
underneath it was not. `WriteMsg` now refuses. Three mutations bite.

A note on the tests, because it nearly bit: the first draft **hung** under the
remove-the-bound mutation instead of failing, because `net.Pipe` is unbuffered
and an unrefused oversized write blocks on an unread pipe. A hung test is not a
red test. Both tests now race the write against a deadline, and the boundary
test deadlines its read for the symmetric reason — a too-strict bound writes
nothing and would otherwise hang.

Baseline honesty: `go test ./internal/server/` is red on the base with and
without the change, identically (`FATA open : no such file or directory`, from
the log-file hook that attaches whenever stdout is not a TTY). These tests were
run filtered.

## 5, recorded — latent, not live, and not fixable at `Resolve`

Measured reachability: `Resolve`'s only caller is `GateNamed`, whose only
caller is the vector suite. **Nothing reaches it from configuration**, so this
is not a live hole.

It also cannot be fixed at `Resolve`: the shared vectors in `verify.json`
exercise `noop`, so removing it would break the conformance suite that proves
the two halves agree. The constraint belongs at the boundary where a name first
arrives from config, and that boundary does not exist yet. Recorded at both
definitions naming who owns it.

## 6, informational — unchanged

`CapPluginInstall = "plugin.install"` exists in the authz vocabulary. D-017
(the `sandbox` vocabulary stays empty) is unaffected and still correct.
