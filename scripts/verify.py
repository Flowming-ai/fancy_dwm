#!/usr/bin/env python3
"""Read-only verification of the files in a distributed setup snapshot."""
from pathlib import Path, PurePosixPath
import hashlib
import re
import sys


def main():
    root = Path(__file__).resolve().parents[1]
    manifest = root / "SHA256SUMS"
    if not manifest.is_file():
        raise SystemExit("SHA256SUMS is missing; use the complete installation archive.")
    seen = set()
    failures = []
    for line in manifest.read_text().splitlines():
        match = re.fullmatch(r"([a-f0-9]{64})  (.+)", line)
        if not match:
            raise SystemExit("Invalid checksum manifest line")
        digest, name = match.groups()
        path = PurePosixPath(name)
        if path.is_absolute() or ".." in path.parts or name in seen:
            raise SystemExit("Unsafe or duplicate manifest path: " + name)
        seen.add(name)
        target = root / name
        if (target.is_symlink() or root not in target.resolve().parents
                or not target.is_file()):
            failures.append(name + " (missing/unsafe)")
        elif hashlib.sha256(target.read_bytes()).hexdigest() != digest:
            failures.append(name + " (checksum mismatch)")
    required = {
        "install.sh", "scripts/install-main.sh", "scripts/verify.py",
        "scripts/downloads.json", "scripts/set-default-session.py",
        "scripts/rollback.sh", "payload/apply-user.py",
        "payload/src/dwm/systray.c", "payload/system/dwm-session",
        "payload/system/dwm.desktop", "README.md",
        "payload/desktop-extras.py", "payload/home/.local/bin/dwm-hibernate",
        "payload/home/.local/bin/dwm-scale-apply", "payload/home/.local/bin/teams-web",
        "scripts/install-forticlient.py", "scripts/hibernate/configure.py",
        "scripts/hibernate/rollback.py", "scripts/package.sh",
    }
    if required - seen:
        failures.append("Missing required manifest entries: " + ", ".join(sorted(required - seen)))
    if failures:
        raise SystemExit("Installation archive verification failed:\n" + "\n".join(failures))
    print(f"Installation archive integrity verified ({len(seen)} files).")


if __name__ == "__main__":
    main()
