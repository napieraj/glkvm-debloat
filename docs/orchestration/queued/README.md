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
