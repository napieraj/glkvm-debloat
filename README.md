# GLKVM KVMD

GLKVM KVMD is a derivative project based on the open-source [PiKVM](https://github.com/pikvm/pikvm). We would like to express our sincere gratitude to the PiKVM team for their outstanding contributions to the open-source community.

## License

GLKVM KVMD is released under the [GPL V3](https://github.com/gl-inet/glkvm/blob/main/LICENSE) license. As a derivative project of PiKVM, we are committed to complying with all terms of the GPL V3 license.

## About KVMD

KVMD is the core daemon of GLKVM/PiKVM. This repository contains the configuration and code of KVMD. If you have any questions not directly related to this codebase, please submit them to the [GLKVM](https://github.com/gl-inet/glkvm/issues) repository.

## Firmware Download

If you want to download the latest or previous firmware, please visit: https://dl.gl-inet.com/kvm/rm1/stable

## Operator notes for this fork

This tree is a debloat fork, not stock GL.iNet firmware. Two things an operator
needs to know before running it on a unit; the full detail is in
[docs/audit.md](docs/audit.md) and [docs/webauthn.md](docs/webauthn.md).

### Change the admin password after upgrading — do not just upgrade

Passwords set by earlier firmware are stored as `$apr1$` (Apache MD5). The fix
in this tree makes new passwords `{SSHA512}`, but it cannot rewrite a hash that
is already on disk. **Upgrading is not sufficient: change the admin password
afterwards.** Until you do, the device holds a cheaply crackable hash of its
current password.

### WebAuthn clone detection resets when kvmd restarts

The credential store is delivered read-only by the enrolment ticket, so the
per-credential `signCount` cannot be written back. Clone detection therefore
works within one kvmd process and starts over on restart: a cloned
authenticator used after a restart will not be flagged. Accepted deliberately —
the alternative is a writable credential store on the device — but it means
`signCount` is not a control you can rely on. If you suspect a key is cloned,
re-issue the enrolment ticket rather than waiting for a counter warning.
Detail: `docs/webauthn.md` §7.3.

### Never deploy `configs/kvmd/webauthn.json`

That file is the empty reference store documenting the format. Copying it onto
an enrolled device replaces its credentials with an empty set — kvmd starts, the
login page offers the security key, and nothing matches. `apply_to_glkvm.sh`
refuses to deploy it and `testenv/tests/test_apply_script.py` enforces that.

## Synchronize kvmd changes to the device

When you modify the contents of the kvmd folder and want to synchronize it to the kvm device, you can do so by executing the **apply_to_glkvm.sh** script (note: it needs to be in the same LAN as the kvm device). After execution, you need to restart the kvm device.
