# Queued patches — not applied

Each patch adds the branch-vacuity rule to that repo's `AGENTS.md`. They are
**not pushed**, because `AGENTS.md` lives only on the worker branches and the
orchestrator's push scope is `claude/repo-status-report-6vi5r1`. Landing them
needs explicit sign-off to push to a worker branch.

| Patch | Applies onto | Adds |
|---|---|---|
| `glkvm-debloat-AGENTS-guard-branch-rule.patch` | `claude/glkvm-status-hutk39` | a bullet in *Verification conventions* |
| `kazbek-AGENTS-guard-branch-rule.patch` | `claude/glkvm-stock-debloat-migration-0pibl7` | rule 12 in *Standing rules* |
| `webauthn-tests.patch` | `claude/glkvm-webauthn` | two commits, ten tests, closing eight mutations that left the suite green |

Apply with `git am < <patch>` on the named branch. Both are doc-only.

## `webauthn-tests.patch` — read this one before applying

Two commits onto `claude/glkvm-webauthn`, taking it from 84 to 96 passing.
It supersedes the earlier `webauthn-origin-pin-tests.patch`, which is folded
in as the first commit.

Eight mutations of that plugin left the whole suite green and every one is
proven exploitable. The worst is fail-open on the signature gate itself:
`verify_es256_openssl` treats any status but 1 as success, and `kvmd/tools.py`
returns the asyncio returncode unchanged, which is NEGATIVE when the child dies
on a signal. An `openssl` killed by the OOM killer returns -9 and the assertion
verifies. No attacker action is needed to reach it.

**Measure with `cryptography` ABSENT.** It is not in `testenv/requirements.txt`.
With it importable, `verify_es256` takes the `cryptography` fast path and the
openssl gate is never exercised at all — two fail-open mutations inside that
fast path can never redden, which is a separate finding recorded in
`FINDINGS-plugin-contract.md`.

**And clear `__pycache__` between every mutation and restore**, with
`python -B` and `PYTHONDONTWRITEBYTECODE=1`. See the bytecode hazard in
`WORKING-AGREEMENT.md`: a same-length mutation restored by `cp` leaves valid-
looking bytecode behind and the suite keeps running the mutation.

Applying these tests does not decide whether the branch merges. That is a
design step, and the branch is the only copy of the implementation.
