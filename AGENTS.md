# AGENTS.md

Working notes for anyone — human or agent — changing this repository.

## This tree is a daemon inside a firmware image nobody has in-repo

`kvmd` is one process in a GL.iNet buildroot system. The init scripts, the
updater binaries, the bootloader and its environment, the tunnel client, and
the native GUI application are all **outside** this repository and cannot be
read, changed, or removed from here.

So:

> **"Not in the repo" never means "not on the device."** A search of this tree
> proves the absence of a **caller**, never the absence of a **mechanism**.

This has produced a wrong conclusion three times, each time in the same shape —
something looked absent because the half that referenced it lived outside the
tree, and the repo-scoped reading was "orphaned, therefore inert":

| Looked absent | Actually | Where it lives |
|---|---|---|
| `rtty` tunnel client | shipped and running | `/etc/init.d/S99rtty` |
| firmware updater | invoked here by name | `updateEngine`, `swupdate_start.sh` |
| flash trigger | a partition write | `--misc=update`, read by the **bootloader** |

Before concluding that deleting a caller removes a capability, ask where the
other half of the mechanism lives. If the answer is "the image", the question is
**device-verifiable, not source-verifiable**, and it belongs in
`test_on_device_residuals` in `testenv/tests/test_attestation.py` — the
skipped-by-default docstring that records checks needing a unit on the bench —
not in a grep and not in a design document.

The same shape applies to the provisioning repo: its device-side tunnel client
is missing for exactly this reason.

## Two consequences worth stating separately

**Deleting a writer does not delete what it wrote.** Routes that wrote to
`/root/.ssh/authorized_keys`, `/etc/shadow` and `/userdata/update.img` are gone
from this tree. Their output survives on any unit that ran earlier firmware, and
`/userdata` in particular survives a rootfs-only reflash.

**Absence of a route is not absence of a capability.** The strip removes API
surface. It does not remove binaries, services, or boot behaviour.

## Verification conventions

- **Re-derive before editing.** Line numbers in `docs/lean-plan.md` and
  `docs/audit.md` go stale. So does the *reasoning*: a KEEP entry written when a
  consumer existed is not evidence once the consumer is deleted.
- **Mutation-check every assertion.** A test that has never been seen to fail has
  not been shown to test anything. Revert the fix; the test must go red.
- **Restore from a snapshot, not from git.** `git checkout -- <path>` discards
  uncommitted work, and `git checkout <sha> -- <path>` *stages* what it restores.
  Copy the file aside before mutating it.
- **Claim the environment you actually ran.** `testenv/tox.ini` declares
  `basepython = python3.12`; a bare `python3` here is 3.11. Both are staged and
  both pass — but say which, and name the dependency set, because a missing test
  dependency presents as a failure rather than a skip.

The full set of build hazards, with the incidents behind them, is at the top of
`docs/lean-plan.md`.
