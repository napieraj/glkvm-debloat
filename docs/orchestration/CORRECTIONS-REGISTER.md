# Corrections register — orchestration delta

Claims that were believed, then measured, then found wrong. This file carries the
corrected WebAuthn entry and the corrections produced by the 2026-09-10
orchestration pass. It supplements the register in the handoff package; where the
two disagree, this one is later.

Rule 1 applies to relayed reports and to handoff documents, not only to plans.
It applies to the register itself.

## Corrected entry — WebAuthn

**Superseded claim:** "WebAuthn integrated, origin pin, five non-negotiables" →
"**Absent from both working trees.** … no WebAuthn anywhere in either repo."

**The correction is to the correction.** The rebuttal was generalised from a
worker's report about the auth core into a claim about the whole tree. Accurate
version:

> The **implementation** is absent from both working trees and lives only on
> `claude/glkvm-webauthn`. `claude/glkvm-status-hutk39` retains documentation and
> one guard that reference it: `docs/lean-plan.md` (12 hits, steps 11/12),
> `docs/audit.md:768`, and `testenv/tests/test_attestation.py:259`.

Measured: `webauthn` matches 0 files on `main`, `claude/new-session-2w6w30` and
`mcp`; 3 files on `hutk39`; 17 files on `claude/glkvm-webauthn`.

**"Five non-negotiables" was never a code invariant.** The phrase appears exactly
once in the tree, in `docs/webauthn.md`. That is why a review bar set from it
could not be met. Relatedly, commit `13d6eb6` says "five guard tests";
`testenv/tests/apps/kvmd/test_login_verified.py` has **six**.

## New — the origin pin is defended against deletion, not against weakening

Directed mutation pass on `claude/glkvm-webauthn` @ `13d6eb6`.

Environment, named per rule 2: Python **3.11.15**, `pytest 9.1.1`,
`pytest-asyncio 1.4.0`, `pytest-aiohttp 1.1.1`, `pytest-mock 3.15.1`,
`aiohttp-basicauth 1.2.0`, `aiohttp 3.14.3`. Reconstructed venv, not the staged
testenv. Baseline `testenv/tests/plugins/auth/test_webauthn.py`: **84 passed**
(46 test functions with parametrisation).

The first run reported *26 failed*. That was the recorded hazard, not a real
failure — absent `pytest-asyncio` presents async tests as failures, not skips.

| Mutation to `kvmd/plugins/auth/webauthn.py` | Result |
|---|---|
| **A.** Delete the `if origin not in accepted` membership check | **3 failed** — bites |
| **B.** Weaken exact membership to `any(origin.startswith(a) for a in accepted)` | **84 passed — silent** |
| **C.** Drop the `crossOrigin` guard | **1 failed** — bites |
| **D.** `accepted = self.__origins or get_default_origins() + (origin,)` | **84 passed — silent** |

**B** ships a cross-origin relay hole green: with `https://kvm-pve1.oskar.co`
pinned, `https://kvm-pve1.oskar.co.attacker.test` prefix-matches and is accepted.
The suite's three negative origin cases (`https://evil.oskar.co`,
`http://kvm-pve1.oskar.co`, `""`) are all rejected by prefix matching too, so
none of them distinguishes exact match from prefix match.

**D** is the sharper one. `origins` defaults to `[]`
(`webauthn.py:473`) and **nothing in `configs/` sets it**, so a shipped device
takes the `get_default_origins()` fallback — the per-device half of the pin, and
per its own docstring the defence against exactly this relay. Every test
constructs the plugin with `origins=[_ORIGIN]` explicitly
(`test_webauthn.py:75`, `kwargs.setdefault`). `test_ok__default_origins_is_the_device_fqdn`
exercises `get_default_origins()` in isolation but never through
`verify_assertion`.

**So the code path that ships is the one path the suite never verifies.** Not
"the sole relay defence is undefended" — narrower and more awkward: it is
defended only on a configuration no shipped device uses.

Two cases would close it, and neither is a merge blocker in itself: an assertion
against an origin that is a superstring of a pinned one, and one verification run
with `origins` unset.

## New — `test_auth.py`: neither version is a superset

`07-INTEGRATION-CONFLICTS.md` recommends taking Worker B's file on the grounds it
"is almost certainly a superset". True against `1ab2083` (4 tests). Not true now:
`hutk39` carries **10**, `claude/new-session-2w6w30` carries **6**, and each has
tests the other lacks. Following the recommendation drops six tests, including
the WS-session lifecycle trio and the TOTP-removal guard. Resolution is a union
of twelve. See the status board for the two name lists.

## Standing consequence

Add to the vacuity class: **a guard and the thing it guards must live on the same
branch.** Every prior instance — `_ROOT` one level short, the uncovered session
expiry, the five tests passing against a nonexistent directory — was inside a
single tree. This one is a property of the branch topology, and nothing checks
it.
