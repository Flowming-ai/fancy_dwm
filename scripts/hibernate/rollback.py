#!/usr/bin/env python3
"""Self-contained rollback, copied inside each root-owned hibernation backup.

No swapoff, deletion of swap files, sleep, or reboot is performed. Run without
--apply to preview the exact restore scope; use sudo python3 rollback.py --apply.
"""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile

ALLOWED = {
    '/etc/fstab', '/etc/default/grub.d/99-dwm-hibernate.cfg',
    '/etc/dracut.conf.d/99-dwm-hibernate.conf',
    '/etc/initramfs-tools/conf.d/zz-dwm-hibernate',
    '/etc/systemd/sleep.conf.d/70-dwm-hibernate.conf',
    '/etc/systemd/system/systemd-hibernate.service.d/20-dwm-minimal-image.conf',
    '/etc/polkit-1/rules.d/49-dwm-hibernate.rules',
    '/var/lib/dwm-hibernate/config.json', '/boot/grub/grub.cfg',
    '/etc/dwm-hibernate-memory.json', '/usr/local/libexec/dwm-hibernate-memory',
    '/etc/systemd/system/dwm-hibernate-memory.service',
    '/etc/systemd/system/systemd-hibernate.service.d/30-dwm-memory-guard.conf',
    '/etc/systemd/system/nvidia-hibernate.service.d/30-dwm-memory-guard.conf',
    '/etc/systemd/system/nvidia-resume.service.d/30-dwm-memory-guard.conf',
}


def safe_target(value):
    return value in ALLOWED or bool(re.fullmatch(r'/boot/initrd\.img-[A-Za-z0-9.+_-]+', value))


def trusted(path, *, required=False):
    for item in [path, *path.parents]:
        if item.is_symlink():
            raise RuntimeError('Refusing symlink: ' + str(item))
        if item.exists():
            info = item.stat()
            if info.st_uid != 0 or info.st_mode & 0o022:
                raise RuntimeError('Expected a root-owned, non-writable path: ' + str(item))
    if required and not path.is_file():
        raise RuntimeError('Backup file is missing: ' + str(path))


def load_plan(backup):
    if backup.parent != Path('/var/backups/dwm-hibernate') or not backup.name.startswith('portable-'):
        raise RuntimeError('Run the rollback.py copy in its original hibernation backup directory')
    trusted(backup / 'manifest.json', required=True)
    trusted(backup / 'runtime.json', required=True)
    manifest = json.loads((backup / 'manifest.json').read_text())
    runtime = json.loads((backup / 'runtime.json').read_text())
    if not isinstance(manifest, dict) or not manifest:
        raise RuntimeError('Invalid manifest')
    for name, existed in manifest.items():
        if not isinstance(name, str) or not safe_target(name) or not isinstance(existed, bool):
            raise RuntimeError('Unsafe manifest entry: ' + repr(name))
        target = Path(name)
        trusted(target)
        if target.exists() and not target.is_file():
            raise RuntimeError('Target is not a regular file: ' + str(target))
        if existed:
            trusted(backup / target.relative_to('/'), required=True)
    if runtime.get('disk') not in ('platform', 'shutdown', 'reboot', 'suspend', 'test_resume'):
        raise RuntimeError('Invalid saved hibernation mode')
    if not re.fullmatch(r'[0-9]+', str(runtime.get('image_size', ''))):
        raise RuntimeError('Invalid saved image size')
    return manifest, runtime


def atomic_restore(source, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.' + target.name + '.rollback-', dir=target.parent)
    try:
        with os.fdopen(fd, 'wb') as output, source.open('rb') as original:
            shutil.copyfileobj(original, output)
            output.flush()
            os.fsync(output.fileno())
        shutil.copystat(source, name)
        os.replace(name, target)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def refuse_active_transition():
    result = subprocess.run(['/usr/bin/systemctl', 'list-jobs', '--no-legend', '--no-pager'],
                            capture_output=True, text=True, timeout=15)
    if result.returncode:
        raise RuntimeError('Cannot check pending power operations: ' + result.stderr.strip())
    if re.search(r'dwm-hibernate-memory\.service|(?:hibernate|suspend|sleep)\.(service|target)', result.stdout):
        raise RuntimeError('Wait until the power transition or memory preparation has finished before rollback')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args(argv)
    backup = Path(__file__).absolute().parent
    manifest, runtime = load_plan(backup)
    for name, existed in manifest.items():
        print(('RESTORE ' if existed else 'REMOVE CREATED FILE ') + name)
    print('RESTORE image_size=' + str(runtime['image_size']) + ', disk=' + runtime['disk'])
    print('RETAIN swap file and active swap: ' + str(runtime.get('retained_swap', 'unknown')))
    if not args.apply:
        print('Preview only. Add --apply as root to restore.')
        return 0
    if os.geteuid() != 0:
        raise RuntimeError('Rollback requires sudo')
    refuse_active_transition()
    errors = []
    for name, existed in manifest.items():
        target = Path(name)
        try:
            if existed:
                atomic_restore(backup / target.relative_to('/'), target)
            else:
                target.unlink(missing_ok=True)
        except OSError as exc:
            errors.append(str(exc))
    for target, content in [(Path('/sys/power/image_size'), str(runtime['image_size'])),
                            (Path('/sys/power/disk'), runtime['disk'])]:
        try:
            target.write_text(content + '\n')
        except OSError as exc:
            errors.append(str(exc))
    result = subprocess.run(['/usr/bin/systemctl', 'daemon-reload'], capture_output=True, text=True, timeout=30)
    if result.returncode:
        errors.append(result.stderr.strip())
    os.sync()
    if errors:
        raise RuntimeError('Rollback requires attention:\n' + '\n'.join(errors))
    print('Restored configuration and boot files. Swap was retained; no reboot or sleep requested.')
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        print('ERROR: ' + str(exc), file=sys.stderr)
        sys.exit(1)
