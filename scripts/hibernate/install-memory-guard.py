#!/usr/bin/env python3
"""Install an optional pre-graphics memory guard, without requesting sleep."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys

import configure as base

DIRECTORY = Path(__file__).resolve().parent
NAME = 'dwm-hibernate-memory.service'
UNIT = Path('/etc/systemd/system') / NAME
HELPER = Path('/usr/local/libexec/dwm-hibernate-memory')
CONFIG = Path('/etc/dwm-hibernate-memory.json')
HIBERNATE = Path('/etc/systemd/system/systemd-hibernate.service.d/30-dwm-memory-guard.conf')
NVIDIA = Path('/etc/systemd/system/nvidia-hibernate.service.d/30-dwm-memory-guard.conf')
RESUME = Path('/etc/systemd/system/nvidia-resume.service.d/30-dwm-memory-guard.conf')
MARKER = '# Managed by ubuntu-dwm-setup hibernation memory guard.\n'
UNIT_TEXT = MARKER + '''[Unit]
Description=Prepare memory before hibernation graphics shutdown
Before=nvidia-hibernate.service systemd-hibernate.service

[Service]
Type=oneshot
ExecStart=/usr/bin/python3 -I /usr/local/libexec/dwm-hibernate-memory
TimeoutStartSec=55s
TimeoutStopSec=5s
KillMode=control-group
RemainAfterExit=no
'''
DEPENDENCY = MARKER + '''[Unit]
Requires=dwm-hibernate-memory.service
After=dwm-hibernate-memory.service
'''
RESUME_TEXT = MARKER + '''# The vendor post hook may already have restored the VT and removed this file.
[Unit]
ConditionPathExists=/run/nvidia-sleep/Xorg.vt_number
'''


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--user', required=True)
    parser.add_argument('--available-percent', type=int, default=67)
    parser.add_argument('--max-reclaim-gib', type=int, default=10)
    args = parser.parse_args(argv)
    spec = importlib.util.spec_from_file_location('memory_guard', DIRECTORY / 'memory-guard.py')
    guard = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(guard)
    config = dict(available_percent=args.available_percent, max_reclaim_gib=args.max_reclaim_gib,
                  timeout_seconds=45, notify_user=args.user,
                  hibernate_swap=json.loads(base.STATE.read_text())['swap_file'])
    guard.validate(config)
    version = re.match(r'(\d+)\.(\d+)', platform.release())
    base.require(version and tuple(map(int, version.groups())) >= (6, 12),
                 'This optional guard requires Linux 6.12 or newer')
    base.require(guard.CGROUP.exists(), 'cgroup v2 user.slice memory.reclaim is unavailable')
    base.require(guard.dedicated_swap_free(config) > 0, 'Hibernation swap must be active')
    files = {UNIT: UNIT_TEXT, HIBERNATE: DEPENDENCY,
             HELPER: (DIRECTORY / 'memory-guard.py').read_text(),
             CONFIG: json.dumps(config, indent=2) + '\n'}
    nvidia_script = Path('/usr/bin/nvidia-sleep.sh')
    if Path('/proc/driver/nvidia').exists():
        script = nvidia_script.read_text()
        base.require(all(part in script for part in ('/var/run/nvidia-sleep',
                     'Xorg.vt_number', 'fgconsole > "${XORG_VT_FILE}"', 'rm "${XORG_VT_FILE}"')),
                     'Review the installed NVIDIA suspend/resume script before adding this guard')
        for service in ('nvidia-hibernate.service', 'nvidia-resume.service'):
            base.require(base.run(['systemctl', 'is-enabled', service]) == 'enabled',
                         service + ' must already be enabled')
        files[NVIDIA] = DEPENDENCY
        files[RESUME] = RESUME_TEXT
    for path in files:
        base.safe_path(path)
        if path.exists() and path not in (HELPER, CONFIG):
            base.require(path.read_text().startswith(MARKER), 'Unmanaged file: ' + str(path))
    if HELPER.exists():
        base.require('Bounded, opt-in RAM preparation' in HELPER.read_text(),
                     'An unrelated memory helper already exists')
    if CONFIG.exists():
        guard.validate(json.loads(CONFIG.read_text()))
    print(json.dumps(dict(config=config, files=[str(path) for path in files]), indent=2))
    if not args.apply:
        print('Preview only; no changes, reclaim, or power operation performed.')
        return 0
    base.require(os.geteuid() == 0, 'Use sudo for --apply')
    # Do not replace hooks while an actual power transition is queued/running.
    jobs = base.run(['systemctl', 'list-jobs', '--no-legend', '--no-pager'])
    base.require(not re.search(r'dwm-hibernate-memory\.service|(?:hibernate|suspend|sleep)\.(service|target)', jobs),
                 'A power transition is already queued')
    backup = base.make_backup(list(files), swap_file=config['hibernate_swap'])
    try:
        for path, content in files.items():
            base.atomic_write(path, content, 0o755 if path == HELPER else 0o644)
        base.run(['systemd-analyze', 'verify', str(UNIT), 'systemd-hibernate.service',
                  *(['nvidia-hibernate.service', 'nvidia-resume.service'] if NVIDIA in files else [])])
        base.run(['systemctl', 'daemon-reload'])
        for name in ['systemd-hibernate.service', *(['nvidia-hibernate.service'] if NVIDIA in files else [])]:
            for prop in ['Requires', 'After']:
                base.require(NAME in base.run(['systemctl', 'show', name, '-p', prop, '--value']).split(),
                             f'Missing {prop} dependency on {name}')
    except BaseException:
        try:
            base.run([sys.executable, backup / 'rollback.py', '--apply'])
        except (OSError, RuntimeError, subprocess.SubprocessError) as rollback_error:
            print('Rollback needs attention: ' + str(rollback_error), file=sys.stderr)
        raise
    print('Installed. No hibernation, reboot, graphics suspension, or memory reclaim performed.')
    print('Rollback: sudo python3 ' + str(backup / 'rollback.py') + ' --apply')
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError) as exc:
        print('ERROR: ' + str(exc), file=sys.stderr)
        sys.exit(1)
