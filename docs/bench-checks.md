# Bench checks — one pass on a flashed unit

Everything in this file is **device-verifiable and not source-verifiable**. It is
here because a search of this repository proves the absence of a *caller*, never
the absence of a *mechanism* — see `AGENTS.md`. Three measurements, one session
with a unit on the bench, one recorded result each.

Run them on a unit **running the debloat build**, and where noted also on a
stock unit for comparison. Record the raw output, not a summary: the value of
these is that they contradict the repo, and a paraphrase cannot.

Related: `test_on_device_residuals` in `testenv/tests/test_attestation.py` lists
the residual-state checks (`authorized_keys`, cron, ttyd, htpasswd,
`/etc/shadow`, staged image, misc partition). This file covers the three that
need a procedure rather than a yes/no.

---

## 1. The real listening surface — `ss -ltnp`

**Command**

    ss -ltnp
    ss -lxp | grep kvmd          # unix sockets too

**Why.** The strip removes API surface. It removes no binaries, no services and
no listeners. A route deleted from `api/` does not close a socket that
`/etc/init.d/S*` opened, and every one of those init scripts is outside this
repo.

**What the repo predicts.** nginx on `${http_port}` / `${https_port}`,
defaulting to 80 and 443 (`kvmd/apps/__init__.py:925,931`), serving
`/usr/share/kvmd/web` (`configs/nginx/kvmd.ctx-server.conf:16,26,31`). kvmd
itself binds **unix sockets only** — `/run/kvmd/kvmd.sock`,
`ustreamer.sock`, `media.sock`, `pst.sock` — so kvmd should contribute **no TCP
listener at all**. Janus takes UDP `20000-40000` for RTP
(`configs/janus/janus.jcfg:12`). The IPMI and VNC schemes default to 623 and
5900 (`:828`, `:857`) but their subsystems are not registered in this build.

**What to look for.** Any TCP listener that is not nginx. Specifically:

- a **ttyd**, and on which port. The client is stripped, `S80ttyd` is not ours.
- **rtty** — outbound rather than listening, so also check
  `ss -tnp state established` and the process list.
- anything owned by the native GUI, the updater, or a vendor helper.
- **IPMI 623 or VNC 5900 actually bound**, which would mean a subsystem this
  build does not register is nonetheless running from the image.

**Interpretation.** A listener with no route behind it is not harmless: it is a
surface this repository cannot see, cannot test and cannot remove. Anything
unexpected here becomes a masking entry in `apply_to_glkvm.sh` and an item in
the attestation contract.

---

## 2. The `pst` partition — does the plugin device half exist?

**Command**

    grep -n 'X-kvmd' /etc/fstab
    mount | grep -i pst
    systemctl status kvmd-pst 2>/dev/null || /etc/init.d/S*pst status 2>/dev/null

**Why.** `fstab.find_pst()` (`kvmd/fstab.py:44`) resolves the persistent-storage
root by parsing `/etc/fstab` for an `X-kvmd.pst-root=` / `-user=` / `-group=`
option inside a six-field entry (`kvmd/fstab.py:56-74`). If no entry carries
that marker it raises `RuntimeError("Can't find 'pst' mountpoint")`.

That raise happens in `PstServer.__init__` at
`kvmd/apps/pst/server.py:55` — construction time, not first use. So on a device
whose fstab lacks the marker, `kvmd-pst` does not start at all, and
`kvmd/helpers/remount` (`__init__.py:164`) fails the same way.

**What the repo predicts.** Nothing. `/etc/fstab` is supplied by the GL image,
not by this repository, and no file here asserts the marker is present.

**What to look for.** Whether the marker exists, what it points at, and whether
the partition is mounted read-only. Then whether `kvmd-pst` is actually running
or has been failing silently since flash.

**Interpretation.** If the marker is absent, the pst subsystem has never worked
on this hardware and anything depending on persistent storage needs re-reading
on that assumption. If it is present, record the path — it is a second
persistent location alongside `/userdata`, with the same survives-a-reflash
property.

---

## 3. The staged image and the boot path

**Commands, in this order**

    # a. bootloader first
    fw_printenv 2>/dev/null | grep -iE 'update|misc|recovery|boot(cmd|script)'
    # or, if fw_printenv is absent, read the env partition directly:
    cat /proc/mtd ; cat /proc/cmdline
    # and dump the boot script if one is on a readable partition

    # b. then userspace
    grep -rniE 'update\.img|misc|recovery' /etc/init.d/ 2>/dev/null

    # c. then the staging area itself
    ls -la /userdata/update.img 2>/dev/null
    cat /proc/cmdline | tr ' ' '\n' | grep -i misc

**Why.** `POST /upgrade/upload` is deleted, but the **read half is device-side**
and cannot be removed from here: this daemon invoked
`updateEngine --image_url=/userdata/update.img --misc=update` on most models and
`swupdate_start.sh -i /userdata/update.img` on rmq1. Neither binary ships in
either repository.

`--misc=update` writes the Rockchip **misc partition**, which is a bootloader
input. So the mechanism that applies a staged image is not confined to the
running system, and `/userdata` is persistent — a staged image survives a
rootfs-only reflash.

**The question this answers.** Does anything consume `/userdata/update.img`
**without** an explicit invocation — a boot-time scan, the recovery path, or the
U-Boot boot script?

**Interpretation.**

- **If nothing picks it up unprompted**, a staged image is inert on a build with
  no apply path, and item 6 of `test_on_device_residuals` is hygiene.
- **If anything does**, the staged file alone is sufficient to flash. That makes
  the deleted route a *write-now, apply-at-next-boot* primitive rather than an
  upload endpoint, it is materially worse than the advisory currently states,
  and the vendor draft in the disclosure file should be updated before sending.

Either way: clearing a suspect unit means clearing `/userdata/update.img` **and**
the misc partition. Reflashing the rootfs clears neither, and a post-flash
integrity check that hashes the rootfs attests neither.

---

## Recording

One file per unit, raw output, with model and firmware version at the top
(`cat /etc/version`). Discrepancies against the predictions above are the
finding; agreement is worth recording too, because these predictions have not
been checked against hardware before.
