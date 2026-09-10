# Plugin contract findings — 2026-09-10

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
