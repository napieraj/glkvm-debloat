"""Compute CONTRACT-SHA256: the canonical tree hash of the contract directory.

Deliberately the same algorithm as the readback tree hash in wire.md, so both
repos verify contract sync with the function they already had to implement.
"""
import hashlib, os, sys

root = sys.argv[1]
files = []
for dirpath, _, names in os.walk(root):
    for n in names:
        if n == "CONTRACT-SHA256":
            continue
        full = os.path.join(dirpath, n)
        files.append((os.path.relpath(full, root).replace(os.sep, "/"), full))

lines = b""
for rel, full in sorted(files, key=lambda f: f[0].encode("utf-8")):
    with open(full, "rb") as f:
        h = hashlib.sha256(f.read()).hexdigest()
    lines += (h + "  " + rel + "\n").encode("utf-8")
print(hashlib.sha256(lines).hexdigest())
