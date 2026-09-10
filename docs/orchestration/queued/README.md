# Queued patches — not applied

Each patch adds the branch-vacuity rule to that repo's `AGENTS.md`. They are
**not pushed**, because `AGENTS.md` lives only on the worker branches and the
orchestrator's push scope is `claude/repo-status-report-6vi5r1`. Landing them
needs explicit sign-off to push to a worker branch.

| Patch | Applies onto | Adds |
|---|---|---|
| `glkvm-debloat-AGENTS-guard-branch-rule.patch` | `claude/glkvm-status-hutk39` | a bullet in *Verification conventions* |
| `kazbek-AGENTS-guard-branch-rule.patch` | `claude/glkvm-stock-debloat-migration-0pibl7` | rule 12 in *Standing rules* |

Apply with `git am < <patch>` on the named branch. Both are doc-only.

## `webauthn-tests.patch` — APPLIED, removed

Both commits landed with the webauthn merge. All eight mutations were
re-verified biting on the merged tree, so the patch has done its job and is
deleted rather than left here to rot as a stale copy of committed history.

The two measurement conditions still matter for anyone reproducing them:
`cryptography` must be ABSENT (with it importable, `verify_es256` takes the
fast path and the openssl gate is never exercised), and `__pycache__` must be
cleared between mutation and restore. Both are in `WORKING-AGREEMENT.md`.
