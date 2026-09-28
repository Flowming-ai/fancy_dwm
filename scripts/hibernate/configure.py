#!/usr/bin/env python3
"""Check/configure disk hibernation on Ubuntu; never request sleep or reboot.

Supported storage: an unencrypted ext4 root on a plain disk/partition, GRUB.
Other layouts fail closed instead of guessing their early-boot requirements.
"""
import argparse
import datetime
import fcntl
import json
import math
import os
from pathlib import Path
import pwd
import re
import shlex
import shutil
import stat
import struct
import subprocess
import sys
import tempfile
import uuid

GIB = 1024 ** 3
PAGE = os.sysconf('SC_PAGESIZE')
OWNER = 'ubuntu-dwm-setup/hibernate-v1'
STATE = Path('/var/lib/dwm-hibernate/config.json')
FSTAB = Path('/etc/fstab')
GRUB = Path('/etc/default/grub.d/99-dwm-hibernate.cfg')
DRACUT = Path('/etc/dracut.conf.d/99-dwm-hibernate.conf')
RESUME = Path('/etc/initramfs-tools/conf.d/zz-dwm-hibernate')
SLEEP = Path('/etc/systemd/sleep.conf.d/70-dwm-hibernate.conf')
MINIMAL = Path('/etc/systemd/system/systemd-hibernate.service.d/20-dwm-minimal-image.conf')
POLICY = Path('/etc/polkit-1/rules.d/49-dwm-hibernate.rules')
BACKUPS = Path('/var/backups/dwm-hibernate')
MINIMAL_TEXT = """# Reduce snapshot RAM demand before every hibernation attempt.
[Service]
ExecStartPre=/usr/bin/sh -c 'echo 0 > /sys/power/image_size'
ExecStartPre=/usr/bin/grep -qx 0 /sys/power/image_size
"""
SLEEP_TEXT = """# Save to disk, then enter ACPI S4. Wake support depends on firmware.
[Sleep]
HibernateMode=platform
"""


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def run(args, *, timeout=120):
    result = subprocess.run([str(x) for x in args], capture_output=True, text=True,
                            timeout=timeout, check=False)
    if result.returncode:
        raise RuntimeError(shlex.join(str(x) for x in args) + ': ' + result.stderr.strip())
    return result.stdout.strip()


def safe_path(path, *, defer_unreadable_leaf=False):
    path = Path(path)
    require(path.is_absolute() and '..' not in path.parts, f'Unsafe path: {path}')
    # lstat consistently reports EACCES on Python 3.12 and 3.14. Check every
    # ancestor before allowing an ordinary user's unreadable final policy file
    # to be deferred to the mandatory privileged preflight.
    for parent in [*reversed(path.parents), path]:
        try:
            info = parent.lstat()
        except FileNotFoundError:
            continue
        except PermissionError:
            if defer_unreadable_leaf and parent == path and os.geteuid() != 0:
                return False
            raise
        require(not stat.S_ISLNK(info.st_mode), f'Refusing symlink: {parent}')
        require(info.st_uid == 0 and not info.st_mode & 0o022,
                f'Expected root ownership and no group/world write permission: {parent}')
    return True


def atomic_write(path, text, mode=0o644):
    safe_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.' + path.name + '.', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            os.fchmod(stream.fileno(), mode)
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def parse_os_release(text):
    result = {}
    for line in text.splitlines():
        if '=' in line and not line.startswith('#'):
            key, value = line.split('=', 1)
            fields = shlex.split(value)
            result[key] = fields[0] if fields else ''
    return result


def swap_bytes(mem_bytes, explicit_gib=None):
    minimum = math.ceil(mem_bytes / GIB) + max(4, math.ceil(mem_bytes / GIB * .10))
    require(explicit_gib is None or explicit_gib >= minimum,
            f'Swap must be at least {minimum} GiB for this RAM size')
    return (minimum if explicit_gib is None else explicit_gib) * GIB


def detect_backend(script, owner=''):
    # Both packages can be present. Inspect the actual update-initramfs wrapper.
    if 'adapted for dracut' in script or owner.startswith('dracut:'):
        return 'dracut'
    if 'mkinitramfs' in script and ('initramfs-tools' in script or owner.startswith('initramfs-tools:')):
        return 'initramfs-tools'
    raise RuntimeError('Cannot identify the active update-initramfs implementation')


def assert_plain_storage(tree):
    def walk(node):
        require(node.get('type') in ('disk', 'part'),
                'Encrypted, LVM, RAID and device-mapper roots require manual hibernation setup')
        for child in node.get('children', []):
            walk(child)
    nodes = tree.get('blockdevices', [])
    require(bool(nodes), 'Cannot identify the root block-device ancestry')
    for node in nodes:
        walk(node)


def secure_boot_disabled():
    if not Path('/sys/firmware/efi').exists():
        return
    variables = list(Path('/sys/firmware/efi/efivars').glob('SecureBoot-*'))
    require(len(variables) == 1, 'Cannot determine Secure Boot state; check it manually first')
    data = variables[0].read_bytes()
    require(len(data) >= 5 and data[4] == 0,
            'Secure Boot is enabled; this module will not disable it or bypass lockdown')


def parse_swaps(text):
    result = {}
    for line in text.splitlines()[1:]:
        words = line.split()
        if len(words) == 5:
            name = re.sub(r'\\([0-7]{3})', lambda m: chr(int(m[1], 8)), words[0])
            result[name] = dict(type=words[1], size_kib=int(words[2]), used_kib=int(words[3]))
    return result


def fiemap_offset(buffer, page_size):
    header = struct.unpack_from('<QQIIII', buffer)
    logical, physical, length, _, _, flags, _, _, _ = struct.unpack_from('<QQQQQIIII', buffer, 32)
    require(header[3] == 1 and logical == 0 and physical > 0 and length >= page_size,
            'Cannot locate the complete first swap-file page')
    require(flags & ~(0x1 | 0x1000) == 0 and physical % page_size == 0,
            'Swap extent is uninitialized, shared, unknown or misaligned')
    return physical // page_size


def filefrag_offset(text):
    match = re.search(r'^\s*0:\s+0\.\.\s*\d+:\s+(\d+)\.\.', text, re.M)
    require(match is not None, 'Cannot parse filefrag first extent')
    return int(match[1])


def get_offset(swap):
    buffer = bytearray(struct.pack('<QQIIII', 0, PAGE, 1, 0, 1, 0) + bytes(56))
    with swap.open('rb') as stream:
        fcntl.ioctl(stream.fileno(), 0xC020660B, buffer, True)
    offset = fiemap_offset(buffer, PAGE)
    require(offset == filefrag_offset(run(['filefrag', '-s', '-v', f'-b{PAGE}', swap])),
            'FIEMAP and filefrag disagree on the resume offset')
    return offset


def validate_swap(config, *, physical=False):
    swap = Path(config['swap_file'])
    info = swap.lstat()
    require(stat.S_ISREG(info.st_mode) and info.st_uid == 0 and stat.S_IMODE(info.st_mode) == 0o600,
            'Dedicated swap must be a root-owned regular file with mode 0600')
    require(info.st_dev == os.stat('/').st_dev and info.st_size == config['expected_bytes'],
            'Dedicated swap filesystem or size changed')
    require(info.st_ino == config['swap_inode'], 'Swap inode changed; do not reuse the old resume offset')
    active = parse_swaps(Path('/proc/swaps').read_text()).get(str(swap))
    require(active and active['type'] == 'file', 'Dedicated swap is not active')
    require(active['size_kib'] * 1024 >= config['expected_bytes'] - PAGE, 'Active swap is undersized')
    if physical:
        require(get_offset(swap) == config['resume_offset'], 'Swap physical offset changed')


def grub_entries(text):
    # Exclude memtest, which also uses a GRUB linux command.
    return [shlex.split(line) for line in text.splitlines()
            if re.match(r'^\s*linux(?:efi)?\s+\S*/vmlinuz-', line)]


def validate_grub_defaults(text):
    # Never source GRUB shell configuration. Refuse obvious custom defaults
    # because /boot/vmlinuz cannot identify a saved/named/numbered older entry.
    for line in text.splitlines():
        match = re.match(r'^\s*(?:export\s+)?(GRUB_DEFAULT|GRUB_SAVEDEFAULT)\s*=(.*)$', line)
        if not match:
            continue
        words = shlex.split(match[2], comments=True)
        allowed = (['0'],) if match[1] == 'GRUB_DEFAULT' else ([], [''], ['false'], ['0'], ['no'])
        require(words in allowed, 'Automatic hibernation requires GRUB_DEFAULT=0 and no saved default; review ' + match[1])


def validate_grub(text, root_uuid, offset):
    entries = grub_entries(text)
    require(entries, 'No Ubuntu kernel boot entries in GRUB')
    for words in entries:
        require('noresume' not in words, 'GRUB contains noresume')
        require([w for w in words if w.startswith('resume=')] == [f'resume=UUID={root_uuid}'],
                'GRUB resume device is missing or conflicting')
        require([w for w in words if w.startswith('resume_offset=')] == [f'resume_offset={offset}'],
                'GRUB resume offset is missing or conflicting')


def validate_image_tree(root, backend, config):
    paths = {str(p.relative_to(root)): p for p in root.rglob('*') if p.is_file()}
    def has(relative):
        return [p for name, p in paths.items() if name == relative or name.endswith('/' + relative)]
    if backend == 'dracut':
        for relative in ('usr/lib/systemd/system-generators/systemd-hibernate-resume-generator',
                         'usr/lib/systemd/systemd-hibernate-resume',
                         'usr/lib/systemd/system/systemd-hibernate-resume.service', 'etc/initrd-release'):
            require(has(relative), 'Dracut initrd missing ' + relative)
        service = has('usr/lib/systemd/system/systemd-hibernate-resume.service')[0].read_text()
        require('Before=local-fs-pre.target' in service, 'Resume must happen before filesystem mounting')
        for relative in ('usr/lib/systemd/system-generators/systemd-hibernate-resume-generator',
                         'usr/lib/systemd/systemd-hibernate-resume'):
            require(has(relative)[0].stat().st_mode & 0o111, 'Initrd resume helper is not executable')
        settings = [p for name, p in paths.items() if '/cmdline.d/' in name and name.endswith('.conf')]
        for setting in settings:
            words = setting.read_text().split()
            require('noresume' not in words, 'Initrd disables resume')
            for key, value in [('resume', 'UUID=' + config['root_uuid']), ('resume_offset', str(config['resume_offset']))]:
                require(all(w == key + '=' + value for w in words if w.startswith(key + '=')),
                        'Conflicting initrd command line: ' + str(setting))
    else:
        require(has('scripts/local-premount/resume'), 'initramfs-tools image lacks the early resume script')
        script = has('scripts/local-premount/resume')[0]
        require(script.stat().st_mode & 0o111, 'Early resume script is not executable')
        content = script.read_text()
        # Older initramfs-tools invokes klibc resume; newer versions write the
        # device/offset to sysfs after validating its swap header with blkid.
        if '/bin/resume' in content:
            executable = has('usr/bin/resume') or has('bin/resume')
            require(executable and executable[0].stat().st_mode & 0o111, 'Initrd lacks executable klibc resume')
        else:
            require('/sys/power/resume' in content and 'resume_offset' in content,
                    'Unknown initramfs-tools resume implementation')
            require(any(has(relative) for relative in ('bin/blkid', 'sbin/blkid', 'usr/bin/blkid', 'usr/sbin/blkid')),
                    'Initrd lacks blkid for swap-header validation')
        settings = has('conf/conf.d/zz-dwm-hibernate')
        require(len(settings) == 1, 'initramfs-tools image lacks explicit resume configuration')
        content = settings[0].read_text()
        require(f'RESUME=UUID={config["root_uuid"]}' in content and
                f'resume_offset={config["resume_offset"]}' in content,
                'initramfs-tools resume configuration differs')


def validate_boot(config, images):
    run(['findmnt', '--verify', '--tab-file', FSTAB])
    run(['grub-script-check', '/boot/grub/grub.cfg'])
    validate_grub(Path('/boot/grub/grub.cfg').read_text(), config['root_uuid'], config['resume_offset'])
    for image in images:
        if config['initramfs_backend'] == 'dracut':
            modules = set(run(['lsinitrd', '-m', image]).split())
            require({'resume', 'systemd'} <= modules, 'Dracut image needs resume and systemd modules')
        with tempfile.TemporaryDirectory(prefix='dwm-initrd-', dir='/var/tmp') as directory:
            run(['unmkinitramfs', image, directory], timeout=600)
            validate_image_tree(Path(directory), config['initramfs_backend'], config)
    device = '/dev/disk/by-uuid/' + config['root_uuid']
    require(run(['blkid', '-p', '-O', str(config['resume_offset'] * PAGE), '-s', 'TYPE', '-o', 'value', device]) == 'swap',
            'Resume offset does not point at a swap header')
    validate_swap(config, physical=True)


def sleep_assignments(text):
    section = ''
    values = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith('[') and line.endswith(']'):
            section = line
        if section == '[Sleep]' and re.match(r'^HibernateMode\s*=', line):
            values.append(line.split('=', 1)[1].strip())
    return values


def existing_conflicts(deferred_paths=()):
    groups = [([Path('/etc/default/grub'), *Path('/etc/default/grub.d').glob('*.cfg')],
               r'\b(?:resume|resume_offset)=|\bnoresume\b'),
              (list(Path('/etc/initramfs-tools/conf.d').glob('*')), r'^\s*(?:export\s+)?(?:RESUME|resume_offset)='),
              ([Path('/etc/systemd/sleep.conf'), *Path('/etc/systemd/sleep.conf.d').glob('*.conf')],
               r'^\s*HibernateMode\s*=')]
    for paths, pattern in groups:
        for path in paths:
            if path.is_file():
                active = '\n'.join(line for line in path.read_text().splitlines() if not line.lstrip().startswith('#'))
                require(not re.search(pattern, active, re.M), 'Existing resume/sleep setting requires review: ' + str(path))
    for path in (GRUB, DRACUT, RESUME, SLEEP, MINIMAL, POLICY):
        if path in deferred_paths:
            continue
        try:
            path.lstat()
        except FileNotFoundError:
            continue
        raise RuntimeError('Refusing unmanaged file: ' + str(path))
    # Includes vendor and /run overrides, not just /etc. Do not assume filename
    # ordering will override somebody else's hibernation policy correctly.
    require(not sleep_assignments(run(['systemd-analyze', 'cat-config', 'systemd/sleep.conf'])),
            'An existing effective HibernateMode setting requires review')


def inspect_host(args):
    report = dict(eligible=False, problems=[], warnings=[], facts={})
    facts = report['facts']
    try:
        osinfo = parse_os_release(Path('/etc/os-release').read_text())
        require(osinfo.get('ID') == 'ubuntu' and osinfo.get('VERSION_ID') in ('24.04', '26.04'),
                'Only Ubuntu 24.04 and 26.04 are supported')
        facts['ubuntu'] = osinfo['VERSION_ID']
        for binary in ('findmnt', 'lsblk', 'fallocate', 'mkswap', 'swapon', 'filefrag', 'blkid',
                       'update-initramfs', 'update-grub', 'grub-script-check', 'unmkinitramfs',
                       'systemctl', 'systemd-analyze'):
            require(shutil.which(binary), 'Missing prerequisite: ' + binary)
        script = Path(shutil.which('update-initramfs')).read_text()
        facts['initramfs_backend'] = detect_backend(script)
        if facts['initramfs_backend'] == 'dracut':
            require(shutil.which('lsinitrd'), 'Missing dracut inspection command: lsinitrd')
        require('disk' in Path('/sys/power/state').read_text().split(), 'Kernel does not support disk hibernation')
        require('platform' in Path('/sys/power/disk').read_text().replace('[', '').replace(']', '').split(),
                'Kernel/firmware does not expose ACPI platform hibernation')
        secure_boot_disabled()
        lockdown = Path('/sys/kernel/security/lockdown')
        require(not lockdown.exists() or '[none]' in lockdown.read_text(), 'Kernel lockdown prevents hibernation')
        require(run(['findmnt', '-n', '-o', 'FSTYPE', '/']) == 'ext4', 'Only an ext4 root filesystem is supported')
        facts['root_uuid'] = str(uuid.UUID(run(['findmnt', '-n', '-o', 'UUID', '/'])))
        device = Path('/dev/disk/by-uuid') / facts['root_uuid']
        info = device.stat()
        require(stat.S_ISBLK(info.st_mode) and info.st_rdev == Path('/').stat().st_dev,
                'Root UUID does not identify the root block device')
        assert_plain_storage(json.loads(run(['lsblk', '--json', '--inverse', '--output', 'NAME,TYPE', device.resolve()])))
        facts['root_device'] = str(device.resolve())
        mem = int(re.search(r'^MemTotal:\s+(\d+)', Path('/proc/meminfo').read_text(), re.M)[1]) * 1024
        facts['ram_bytes'] = mem
        facts['expected_bytes'] = swap_bytes(mem, args.swap_size_gib)
        require(re.fullmatch(r'/[A-Za-z0-9][A-Za-z0-9_.-]*', args.swap_file), 'Swap file must be a simple file directly under /')
        facts['swap_file'] = args.swap_file
        images = sorted(Path('/boot').glob('initrd.img-*'))
        require(images, 'No installed initramfs images')
        for image in images:
            safe_path(image)
            require(image.is_file(), 'Expected an initramfs file: ' + str(image))
        facts['images'] = [str(p) for p in images]
        kernel_link = next((p for p in (Path('/boot/vmlinuz'), Path('/vmlinuz')) if p.exists()), None)
        require(kernel_link is not None, 'Cannot identify the next-boot kernel')
        facts['next_boot_kernel'] = kernel_link.resolve(strict=True).name.removeprefix('vmlinuz-')
        require('/boot/initrd.img-' + facts['next_boot_kernel'] in facts['images'], 'Default kernel has no matching initramfs')
        require(Path('/boot/grub/grub.cfg').is_file(), 'GRUB installation is required')
        for source in (Path('/etc/default/grub'), *sorted(Path('/etc/default/grub.d').glob('*.cfg'))):
            if source.is_file():
                validate_grub_defaults(source.read_text())
        deferred_paths = set()
        for path in (FSTAB, STATE, GRUB, DRACUT, RESUME, SLEEP, MINIMAL, POLICY, BACKUPS):
            if not safe_path(path, defer_unreadable_leaf=(path == POLICY)):
                deferred_paths.add(path)
                report['warnings'].append('Cannot inspect ' + str(path) +
                                          ' as an ordinary user; final-file safety/conflict checks are deferred to the privileged preflight.')
        if STATE.exists():
            config = json.loads(STATE.read_text())
            require(config.get('status') == 'configured' and config.get('root_uuid') == facts['root_uuid'],
                    'Existing hibernation state is incomplete or belongs to another filesystem')
            validate_swap(config, physical=False)
            facts['existing'] = config
            facts['action'] = 'verify-existing-without-changing-it'
            facts['swap_file'] = config['swap_file']
            facts['expected_bytes'] = config['expected_bytes']
            report['warnings'].append('Existing hibernation configuration will be validated, not overwritten or resized.')
            facts['hibernate_mode_settings'] = sleep_assignments(run(['systemd-analyze', 'cat-config', 'systemd/sleep.conf']))
            facts['runtime_disk_mode'] = Path('/sys/power/disk').read_text().strip()
            facts['runtime_image_size'] = Path('/sys/power/image_size').read_text().strip()
            prestart = run(['systemctl', 'show', 'systemd-hibernate.service', '-p', 'ExecStartPre'])
            facts['per_hibernate_minimal_image'] = 'echo 0 > /sys/power/image_size' in prestart
            expected = (facts['hibernate_mode_settings'] == ['platform'] and
                        facts['per_hibernate_minimal_image'])
            if config.get('owner') == OWNER:
                require(expected, 'Managed hibernation policy changed; review before reapplying')
            elif not expected:
                report['warnings'].append('Legacy settings differ from platform plus per-hibernate image_size=0; existing settings are preserved, not repaired.')
        else:
            existing_conflicts(deferred_paths)
            swap = Path(args.swap_file)
            safe_path(swap)
            if args.reuse_swap:
                candidate = dict(swap_file=str(swap), expected_bytes=facts['expected_bytes'],
                                 swap_inode=args.reuse_swap[0], resume_offset=args.reuse_swap[1])
                validate_swap(candidate, physical=False)
            else:
                require(not swap.exists(), 'Unmanaged swap file exists; it will not be overwritten: ' + str(swap))
            require(str(swap) not in FSTAB.read_text(), 'Existing fstab entry for the dedicated swap needs review')
            facts['action'] = 'configure'
            # Space for swap, image backups/extraction and ordinary operation. Never fill / or /boot.
            root_need = (0 if args.reuse_swap else facts['expected_bytes']) + 8 * GIB
            root_need += sum(p.stat().st_size for p in images) * 4
            require(shutil.disk_usage('/').free > root_need, 'Insufficient free root disk space for swap and boot backups')
            require(shutil.disk_usage('/boot').free > max(p.stat().st_size for p in images) * 3 + 256 * 1024**2,
                    'Insufficient /boot free space to regenerate initramfs safely')
        if os.geteuid() != 0:
            report['warnings'].append('Boot archive contents and physical swap offsets are fully verified by the privileged apply step.')
        if Path('/proc/driver/nvidia/params').exists():
            params = Path('/proc/driver/nvidia/params').read_text()
            facts['nvidia_preserve_vram'] = bool(re.search(r'^PreserveVideoMemoryAllocations:\s*1\s*$', params, re.M))
            report['warnings'].append('NVIDIA detected: vendor hibernate/resume services, VRAM preservation and a disk-backed temporary directory must be configured by the driver. This module does not replace GPU-driver settings.')
        report['warnings'].append('A normal reboot is required when resume parameters/kernel changed; keyboard/mouse wake depends on firmware and USB standby power.')
        report['eligible'] = True
    except (OSError, RuntimeError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as exc:
        report['problems'].append(str(exc))
    return report


def make_backup(paths, *, swap_file):
    safe_path(BACKUPS)
    stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    backup = BACKUPS / ('portable-' + stamp)
    backup.mkdir(mode=0o700, parents=True)
    manifest = {}
    for path in paths:
        safe_path(path)
        require(not path.exists() or path.is_file(), 'Expected a file: ' + str(path))
        manifest[str(path)] = path.exists()
        if path.exists():
            destination = backup / path.relative_to('/')
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, destination)
    modes = dict(image_size=Path('/sys/power/image_size').read_text().strip(),
                 disk=re.search(r'\[([a-z_]+)\]', Path('/sys/power/disk').read_text())[1],
                 retained_swap=str(swap_file))
    atomic_write(backup / 'manifest.json', json.dumps(manifest, indent=2) + '\n', 0o600)
    atomic_write(backup / 'runtime.json', json.dumps(modes, indent=2) + '\n', 0o600)
    shutil.copy2(Path(__file__).with_name('rollback.py'), backup / 'rollback.py')
    (backup / 'rollback.py').chmod(0o700)
    return backup


def policy_text(username):
    return ('// Permit this active local desktop account; do not bypass inhibitors.\n'
            'polkit.addRule(function(action, subject) {\n'
            f'    if (subject.local && subject.active && subject.user == {json.dumps(username)} &&\n'
            '        (action.id == "org.freedesktop.login1.hibernate" ||\n'
            '         action.id == "org.freedesktop.login1.hibernate-multiple-sessions"))\n'
            '        return polkit.Result.YES;\n});\n')


def apply(args, report):
    require(os.geteuid() == 0, 'Run --apply with sudo and --user YOUR_DESKTOP_ACCOUNT')
    require(not re.search(r'^NoNewPrivs:\s*1$', Path('/proc/self/status').read_text(), re.M),
            'NoNewPrivs prevents privileged installation; use a normal Ubuntu terminal')
    user = pwd.getpwnam(args.user or os.environ.get('SUDO_USER', ''))
    require(user.pw_uid >= 1000 and user.pw_uid != 65534, 'Specify a regular desktop account with --user')
    facts = report['facts']
    images = [Path(p) for p in facts['images']]
    if 'existing' in facts:
        config = facts['existing']
        require(config.get('initramfs_backend') == facts['initramfs_backend'], 'Existing boot generator changed')
        validate_boot(config, images)
        print('Existing hibernation configuration verified. No changes made.')
        return
    swap = Path(facts['swap_file'])
    if args.reuse_swap:
        require(get_offset(swap) == args.reuse_swap[1], 'Recovery inode/offset does not match')
    backend = DRACUT if facts['initramfs_backend'] == 'dracut' else RESUME
    paths = [FSTAB, GRUB, backend, SLEEP, MINIMAL, POLICY, STATE, Path('/boot/grub/grub.cfg'), *images]
    backup = make_backup(paths, swap_file=swap)
    print('Backup: ' + str(backup), flush=True)
    try:
        if not args.reuse_swap:
            fd = os.open(swap, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            os.close(fd)
            run(['fallocate', '-l', str(facts['expected_bytes']), swap], timeout=600)
            run(['mkswap', '-L', 'dwm-hibernate', swap])
            run(['swapon', '--priority', '100', swap])
        offset = get_offset(swap)
        config = dict(owner=OWNER, status='configured', swap_file=str(swap), root_uuid=facts['root_uuid'],
                      resume_offset=offset, expected_bytes=facts['expected_bytes'], page_size=PAGE,
                      configured_kernel=os.uname().release, swap_inode=swap.stat().st_ino,
                      initramfs_backend=facts['initramfs_backend'], hibernate_desktop_user=user.pw_name,
                      backup=str(backup), hibernate_mode='platform')
        atomic_write(backup / 'retained-swap.json', json.dumps(config, indent=2) + '\n', 0o600)
        if backend == DRACUT:
            atomic_write(DRACUT, '# Include early resume support before first boot with resume=.\nadd_dracutmodules+=" resume "\n')
        else:
            atomic_write(RESUME, f'RESUME=UUID={facts["root_uuid"]}\nresume_offset={offset}\n')
        atomic_write(GRUB, '# Dedicated ext4 swap: do not recreate without recalculating offset.\n'
                     f'GRUB_CMDLINE_LINUX="${{GRUB_CMDLINE_LINUX}} resume=UUID={facts["root_uuid"]} resume_offset={offset}"\n')
        atomic_write(FSTAB, FSTAB.read_text().rstrip() + '\n# ubuntu-dwm-setup dedicated hibernation swap\n'
                     f'{swap} none swap sw,pri=100 0 0\n')
        atomic_write(SLEEP, SLEEP_TEXT)
        atomic_write(MINIMAL, MINIMAL_TEXT)
        require(sleep_assignments(run(['systemd-analyze', 'cat-config', 'systemd/sleep.conf'])) == ['platform'],
                'Unexpected merged HibernateMode settings')
        run(['findmnt', '--verify', '--tab-file', FSTAB])
        run(['sh', '-n', GRUB])
        for image in images:
            run(['update-initramfs', '-u', '-k', image.name.removeprefix('initrd.img-')], timeout=1800)
        run(['update-grub'], timeout=300)
        validate_boot(config, images)
        atomic_write(POLICY, policy_text(user.pw_name))
        atomic_write(STATE, json.dumps(config, indent=2) + '\n')
        run(['systemd-analyze', 'verify', 'systemd-hibernate.service'])
        run(['systemctl', 'daemon-reload'])
        effective = run(['systemctl', 'show', 'systemd-hibernate.service', '-p', 'DropInPaths', '-p', 'ExecStartPre'])
        require(str(MINIMAL) in effective and 'echo 0 > /sys/power/image_size' in effective,
                'The per-hibernate minimal-image setting was not loaded')
        Path('/sys/power/image_size').write_text('0\n')
        Path('/sys/power/disk').write_text('platform\n')
        require(Path('/sys/power/image_size').read_text().strip() == '0' and
                '[platform]' in Path('/sys/power/disk').read_text(), 'Runtime hibernation settings did not take effect')
        os.sync()
    except BaseException:
        print('Restoring configuration/boot files. The new swap is retained; no swapoff is attempted.', file=sys.stderr)
        try:
            run([sys.executable, backup / 'rollback.py', '--apply'], timeout=600)
        except (OSError, RuntimeError, subprocess.SubprocessError) as rollback_error:
            print('Rollback needs attention: ' + str(rollback_error), file=sys.stderr)
        raise
    print('Configured: platform hibernation and image_size=0. No sleep/reboot was requested.')
    print('Save work and reboot normally before using dwm-hibernate --check.')
    print('Rollback: sudo python3 ' + shlex.quote(str(backup / 'rollback.py')) + ' --apply')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--check', action='store_true', help='Read-only eligibility report (default)')
    modes.add_argument('--apply', action='store_true', help='Configure and back up; never sleep/reboot')
    parser.add_argument('--json', action='store_true', help='Machine-readable read-only report')
    parser.add_argument('--user', help='Desktop account receiving local hibernation permission')
    parser.add_argument('--swap-file', default='/swap-hibernate.img')
    parser.add_argument('--swap-size-gib', type=int, help='Optional size, at least RAM plus headroom')
    parser.add_argument('--reuse-swap', type=int, nargs=2, metavar=('INODE', 'OFFSET'),
                        help='Recover a retained active swap after rollback; never reformat it')
    args = parser.parse_args(argv)
    require(not (args.apply and args.json), '--json is only available for read-only checks')
    os.environ['PATH'] = '/usr/sbin:/usr/bin:/sbin:/bin'
    os.environ['LC_ALL'] = 'C'
    report = inspect_host(args)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(('ELIGIBLE' if report['eligible'] else 'NOT ELIGIBLE') + ' for automatic hibernation configuration')
        for kind in ('problems', 'warnings'):
            for message in report[kind]:
                print(kind.upper() + ': ' + message)
        print(json.dumps(report['facts'], indent=2))
    if not report['eligible']:
        return 1
    if args.apply:
        require(os.geteuid() == 0, '--apply requires sudo; --check does not')
        require(not re.search(r'^NoNewPrivs:\s*1$', Path('/proc/self/status').read_text(), re.M),
                'NoNewPrivs prevents privileged installation; no changes made')
        with open('/run/dwm-hibernate-setup.lock', 'w') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            # Repeat eligibility after obtaining the lock, before mutations.
            report = inspect_host(args)
            require(report['eligible'], '; '.join(report['problems']))
            apply(args, report)
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, RuntimeError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        print('ERROR: ' + str(exc), file=sys.stderr)
        sys.exit(1)
