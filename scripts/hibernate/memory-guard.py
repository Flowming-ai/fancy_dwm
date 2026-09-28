#!/usr/bin/env python3
"""Bounded, opt-in RAM preparation before hibernation; never initiates sleep.

The thresholds are a conservative mitigation, not a snapshot size prediction
or proof that graphics and firmware will resume successfully.
"""
import argparse
import errno
import json
import os
from pathlib import Path
import pwd
import subprocess
import sys
import time

GIB = 1024 ** 3
MIB = 1024 ** 2
PAGE = os.sysconf('SC_PAGESIZE')
CONFIG = Path('/etc/dwm-hibernate-memory.json')
CGROUP = Path('/sys/fs/cgroup/user.slice/memory.reclaim')
STATUS = Path('/run/dwm-hibernate-memory.json')


def meminfo():
    result = {}
    for line in Path('/proc/meminfo').read_text().splitlines():
        key, value, *_ = line.split()
        result[key.rstrip(':')] = int(value) * 1024
    for key in ('MemTotal', 'MemAvailable', 'SwapFree'):
        if key not in result:
            raise RuntimeError('Missing memory counter: ' + key)
    return result


def validate(config):
    required = {'available_percent', 'max_reclaim_gib', 'timeout_seconds',
                'notify_user', 'hibernate_swap'}
    if set(config) != required:
        raise ValueError('Unexpected or missing memory guard settings')
    for key, low, high in [('available_percent', 50, 80), ('max_reclaim_gib', 1, 16),
                           ('timeout_seconds', 5, 45)]:
        if type(config[key]) is not int or not low <= config[key] <= high:
            raise ValueError('Out-of-range setting: ' + key)
    if not isinstance(config['notify_user'], str):
        raise ValueError('notify_user must name a local user')
    pwd.getpwnam(config['notify_user'])
    swap = Path(config['hibernate_swap'])
    if not swap.is_absolute() or '..' in swap.parts or any(c.isspace() for c in str(swap)):
        raise ValueError('Unsupported swap path')
    return config


def dedicated_swap_free(config):
    for line in Path('/proc/swaps').read_text().splitlines()[1:]:
        words = line.split()
        if len(words) == 5 and words[0] == config['hibernate_swap']:
            return (int(words[2]) - int(words[3])) * 1024
    raise RuntimeError('The configured hibernation swap is not active')


def target_bytes(memory, config):
    return memory['MemTotal'] * config['available_percent'] // 100


def swap_floor(memory):
    # Retain space for an uncompressed image near half RAM plus a margin.
    # The separate desktop guard still validates resume identity and offsets.
    return memory['MemTotal'] // 2 + 2 * GIB


def reclaim(amount, timeout):
    # Bound each write without changing memory limits, invoking OOM, freezing
    # user processes, dropping caches globally, or terminating applications.
    child = subprocess.run([sys.executable, '-I', str(Path(__file__).resolve()),
                            '--reclaim-chunk', str(amount)],
                           capture_output=True, text=True, timeout=timeout)
    if child.returncode not in (0, 11):
        raise RuntimeError(child.stderr.strip() or 'Proactive reclaim failed')


def prepare(config, read=meminfo, read_swap=dedicated_swap_free,
            reclaim_fn=reclaim, clock=time.monotonic):
    memory = read()
    target = target_bytes(memory, config)
    deadline = clock() + config['timeout_seconds']
    requested = 0
    maximum = config['max_reclaim_gib'] * GIB
    while memory['MemAvailable'] < target:
        remaining = deadline - clock()
        if remaining <= 0 or requested >= maximum:
            raise RuntimeError('RAM preparation reached its time or reclaim limit. '
                               'Close memory-heavy applications and try again.')
        gap = target - memory['MemAvailable']
        amount = min(256 * MIB, maximum - requested, ((gap + PAGE - 1) // PAGE) * PAGE)
        if min(memory['SwapFree'], read_swap(config)) - amount < swap_floor(memory):
            raise RuntimeError('Not enough free hibernation swap remains for preparation. '
                               'Close memory-heavy applications and try again.')
        reclaim_fn(amount, min(5, remaining))
        requested += amount
        memory = read()
    # A pass is a heuristic, not a promise about later driver allocations.
    free_swap = min(memory['SwapFree'], read_swap(config))
    if free_swap < swap_floor(memory):
        raise RuntimeError('Insufficient free hibernation swap for the image.')
    return dict(available_bytes=memory['MemAvailable'], target_bytes=target,
                requested_reclaim_bytes=requested, swap_free_bytes=free_swap)


def write_status(state, **details):
    data = dict(state=state, boot_id=Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
                monotonic=time.monotonic(), **details)
    temporary = STATUS.with_suffix('.tmp')
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o644)
    with os.fdopen(fd, 'w') as stream:
        json.dump(data, stream, indent=2)
        stream.write('\n')
    os.replace(temporary, STATUS)
    print(json.dumps(data), flush=True)


def notify(config, message):
    account = pwd.getpwnam(config['notify_user'])
    bus = Path(f'/run/user/{account.pw_uid}/bus')
    if not bus.exists() or not Path('/usr/bin/notify-send').exists():
        return
    try:
        subprocess.run(['/usr/sbin/runuser', '-u', account.pw_name, '--', '/usr/bin/env',
                        f'DBUS_SESSION_BUS_ADDRESS=unix:path={bus}',
                        '/usr/bin/notify-send', '-u', 'critical', '-t', '20000',
                        'Hibernation cancelled before graphics shutdown', message],
                       timeout=3, check=False, capture_output=True)
    except (OSError, subprocess.SubprocessError):
        pass


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--check', action='store_true', help='Read-only memory report')
    mode.add_argument('--reclaim-chunk', type=int, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.reclaim_chunk is not None:
        if os.geteuid() != 0 or not 0 < args.reclaim_chunk <= 256 * MIB:
            return 1
        try:
            CGROUP.write_text(f'{args.reclaim_chunk} swappiness=200\n')
        except OSError as exc:
            if exc.errno == errno.EAGAIN:
                return 11
            raise
        return 0
    config = validate(json.loads(CONFIG.read_text()))
    if args.check:
        memory = meminfo()
        print(json.dumps(dict(memory=memory, config=config,
                              target_bytes=target_bytes(memory, config),
                              swap_floor_bytes=swap_floor(memory),
                              dedicated_swap_free=dedicated_swap_free(config)), indent=2))
        return 0
    if os.geteuid() != 0:
        raise RuntimeError('Memory preparation requires root; --check is read-only')
    try:
        if not CGROUP.exists():
            raise RuntimeError('The cgroup v2 memory.reclaim interface is unavailable')
        write_status('preparing')
        result = prepare(config)
        Path('/sys/power/image_size').write_text('0\n')
        if Path('/sys/power/image_size').read_text().strip() != '0':
            raise RuntimeError('Failed to select the minimal hibernation image')
        write_status('prepared', **result)
        return 0
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        message = str(exc)
        write_status('cancelled', error=message)
        notify(config, message)
        return 1


if __name__ == '__main__':
    sys.exit(main())
