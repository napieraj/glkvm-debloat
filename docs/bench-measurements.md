# Bench measurements — questions that need hardware

Everything here is blocked on having a device in front of you. They are
collected in one file, and ordered so a **single pass answers all of them**,
because the alternative is discovering the second question after the device has
been put away.

Target: a GL.iNet GLKVM (RM1PE or RM4PE) over SSH.

Run the whole block, paste the output into the relevant item's PR or issue, and
record the answers back into this file.

```sh
# --- everything below is read-only; nothing here modifies the device ---
echo "== 1. pst partition =="
grep -n 'X-kvmd\.pst' /etc/fstab || echo "NO pst entry in /etc/fstab"

echo "== 2. listening sockets =="
ss -ltnp 2>/dev/null || netstat -ltnp 2>/dev/null || echo "NEITHER ss NOR netstat"

echo "== 3. init system =="
ls /etc/init.d/ 2>/dev/null | head -40
[ -d /run/systemd/system ] && echo "systemd IS running" || echo "systemd is NOT running"

echo "== 4. is pst deployed / running =="
command -v kvmd-pst kvmd-pstrun kvmd-helper-pst-remount 2>/dev/null || echo "pst binaries NOT on PATH"
ps w 2>/dev/null | grep -i '[p]st' || echo "no pst process"

echo "== 5. writable storage and rootfs mode =="
mount | grep -E ' / | /var | /etc | overlay|ubifs|jffs2|f2fs'
df -h
echo "== 6. overlay support =="
grep -c overlay /proc/filesystems
```

---

## 1. Does a `pst`-tagged partition exist?

**Blocks:** the plugin foundation's device half
(`kazbek/docs/modules/plugins.md`).

`kvmd/fstab.py`'s `find_pst()` does not look for a partition by name. It scans
`/etc/fstab` for an entry whose mount options contain
`X-kvmd.pst-root=` / `X-kvmd.pst-user=` / `X-kvmd.pst-group=`, so
`grep 'X-kvmd\.pst' /etc/fstab` is the whole test.

**This is a fork in the plan, not a detail, and the two branches are not the
same size:**

- **Entry present.** The remount discipline is largely an *adoption* problem.
  `kvmd/apps/pst`, `kvmd/apps/pstrun` and `kvmd-helper-pst-remount` all survive
  in this fork, and the storage they need already exists. What is still missing
  is the launcher — see item 3.
- **No entry.** The device half is writing a launcher **and provisioning
  storage**: partitioning or carving out a writable area, an fstab entry, users
  and groups, and whatever the firmware's image build needs to keep it across
  an upgrade. Materially bigger.

**No estimate for the device half should be given before this is answered.**

## 2. What is actually listening?

**Blocks:** the `/web` port allowlist item (owned elsewhere; the details of that
item are outside this repository's docs).

The allowlist has to be written against what the device really listens on, not
against what the configuration implies. `ss -ltnp` is the primary form;
BusyBox builds may only have `netstat -ltnp`, and the block above falls back.

Record the full output, including the owning process per socket — a port with
no identifiable owner is itself a finding.

## 3. Confirming the launcher gap

**Context:** `kvmd-pst`'s only launcher in this repository is
`configs/os/services/kvmd-pst.service`, a **systemd unit**, and this device
runs BusyBox init — the firmware's own code shells out to `/etc/init.d/S99rkipc`,
`S99tailscale`, `S99gl-pion`, `S80ttyd`, `S99firewall` and `S99gl-cloud`.

So the mechanism is adoptable and the launcher is not. Items 3 and 4 in the
block confirm this on hardware rather than from the tree: whether the pst
binaries are installed at all, whether anything starts them, and what the init
directory actually contains.

If `systemd IS running`, stop and re-check every assumption in this file — the
whole device-side picture would be different from what the source implies.

## 4. Writable storage and rootfs mode

**Why it is here:** it is the immediate follow-up question if item 1 comes back
empty, and going back to the bench a second time to ask it would defeat the
purpose of this file.

The rw/ro remount dance constrains everything downstream in the device half, so
what is mounted where, in which mode, on which filesystem, and whether
`overlay` is available in `/proc/filesystems` all feed directly into that
design.

---

## Answers

_Unanswered. Fill in with the date, the device model, the firmware version, and
the raw output._

## 5. Does anything on the device start `localhid`, `media` or `swctl`?

`kvmd/apps/localhid` (591 lines), `kvmd/apps/media` (273) and `kvmd/apps/swctl`
(197) have **zero importers in either tree** and no `console_scripts` entry, but
each carries a `__main__.py` and a `main()` — so each is a standalone app meant
to be started as `python -m kvmd.apps.<name>`. Rule 12: that no caller exists
here says nothing about whether GL's init scripts start them on the unit.

**Procedure:** on a device, `ps` for the three module names, then
`grep -rE 'localhid|apps\.media|swctl' /etc/init.d/ /etc/rc.d/ /usr/bin/ 2>/dev/null`.

**What it decides:** if nothing starts them they are strip candidates under
rule 5 (gut, not mask) — roughly 1,061 lines and three packages out of a debloat
fork. If something does, they are load-bearing and `setup.py` must keep shipping
them. They are declared in `packages` today because the failure modes are not
symmetric: an unused package costs bytes, a missing used one breaks the daemon.

Contrast `kvmd/apps/kvmd/switch` (3,265 lines), which has three in-tree
importers including an unconditional `from .switch import Switch` — that one
needed no device answer and its omission from `packages` was a live bug.

## 6. Does the device image provide `evdev`?

`PKGBUILD` does not list it, and 14 modules import it unconditionally at module
scope — `kvmd/mouse.py`, `kvmd/keyboard/{mappings,printer,magic}.py`,
`kvmd/apps/vnc/{server.py,rfb/__init__.py}`, `kvmd/apps/localhid/{hid,server}.py`,
`kvmd/plugins/hid/**` and more. `grep -c evdev PKGBUILD` returns 0.

If nothing supplies it, an installed kvmd cannot import, which is the same shape
as the four packages missing from `setup.py` (fixed) and would be far more
visible. So something almost certainly does provide it — GL's image, or a
transitive dependency of another Arch package — and rule 12 says a missing entry
in a dependency list here proves nothing about the unit.

**Procedure:** on a device, `python3 -c "import evdev; print(evdev.__file__)"`,
then `pacman -Qo` that path to see which package owns it.

**What it decides:** whether `PKGBUILD` has a real missing dependency that has
been masked by something else installing it, or whether the list is simply
incomplete-but-harmless. Left unchanged meanwhile, consistently with
`openssl-1.1` and `python-periphery`: `PKGBUILD` is the device package's
dependency list, not this container's.
