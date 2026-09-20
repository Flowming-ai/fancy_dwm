#!/usr/bin/env python3
"""Set only the installing user's next graphical session, preserving backups."""
from pathlib import Path
import configparser
import io
import json
import os
import pwd
import re
import shlex
import shutil
import subprocess
import sys
import tempfile

SERVICE = 'org.freedesktop.Accounts'
INTERFACE = 'org.freedesktop.Accounts.User'
DESKTOP = Path('/usr/share/xsessions/dwm.desktop')


def run(args, *, privileged=False, check=True):
    command = (['sudo', '-n'] if privileged else []) + list(map(str, args))
    result = subprocess.run(command, text=True, capture_output=True, timeout=30)
    if check and result.returncode:
        raise RuntimeError(f"Command failed: {shlex.join(command)}\n{result.stderr.strip()}")
    return result


def ancestors_safe(path):
    """Leaf symlinks may be backed up/replaced; never traverse a parent symlink."""
    for parent in path.absolute().parents:
        if parent.is_symlink():
            raise RuntimeError(f'Refusing a path with a symlink parent: {path} ({parent})')


def write_atomic(path, text, mode=0o600):
    ancestors_safe(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f'.{path.name}.new-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            stream.write(text)
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        if os.path.lexists(temporary): os.unlink(temporary)


def update_ini(text, section, values):
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    parser.optionxform = str
    if text.strip(): parser.read_string(text)
    if not parser.has_section(section): parser.add_section(section)
    for key, value in values.items(): parser.set(section, key, value)
    stream = io.StringIO()
    parser.write(stream, space_around_delimiters=False)
    return stream.getvalue()


def backup_user_file(home, backup, relative):
    path = home / relative
    ancestors_safe(path)
    manifest = backup / 'user-files.txt'
    if manifest.is_symlink(): raise RuntimeError('User manifest must not be a symlink')
    existing = manifest.read_text().splitlines() if manifest.exists() else []
    if relative in existing: return
    destination = backup / 'home' / relative
    ancestors_safe(destination)
    if destination.exists() or destination.is_symlink():
        raise RuntimeError('Backup destination already exists: ' + str(destination))
    if path.is_dir() and not path.is_symlink():
        raise RuntimeError(f'Expected a regular user file, found directory: {path}')
    if path.exists() or path.is_symlink():
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination, follow_symlinks=False)
    with manifest.open('a') as stream: stream.write(relative + '\n')


def validate_desktop(path=DESKTOP):
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    parser.optionxform = str
    with path.open() as stream: parser.read_file(stream)
    section = parser['Desktop Entry']
    if section.get('Type') != 'Application' or section.get('Hidden', '').lower() == 'true':
        raise RuntimeError('dwm.desktop is not an enabled Application session')
    command = shlex.split(section.get('Exec', ''))
    if not command: raise RuntimeError('dwm.desktop lacks Exec')
    executable = command[0]
    if not (Path(executable).is_file() and os.access(executable, os.X_OK)):
        if not shutil.which(executable): raise RuntimeError('Missing session executable: ' + executable)
    try_exec = section.get('TryExec', '')
    if try_exec and not shutil.which(try_exec):
        raise RuntimeError('Missing DWM executable: ' + try_exec)


def object_path(uid):
    return f'/org/freedesktop/Accounts/User{uid}'


def methods(uid, runner=run):
    result = runner(['busctl', '--system', '--no-pager', 'introspect', SERVICE,
                     object_path(uid), INTERFACE], check=False)
    if result.returncode:
        result = runner(['busctl', '--system', '--no-pager', 'introspect', SERVICE,
                         object_path(uid), INTERFACE], privileged=True, check=False)
    if result.returncode: return set()
    return set(re.findall(r'^\s*\.?(Set\w+)\s+method\b', result.stdout, re.M))


def get_property(uid, name, runner=run):
    command = ['busctl', '--system', 'get-property', SERVICE, object_path(uid), INTERFACE, name]
    result = runner(command, check=False)
    if result.returncode: result = runner(command, privileged=True)
    parts = shlex.split(result.stdout.strip())
    if len(parts) != 2 or parts[0] != 's':
        raise RuntimeError(f'Unexpected AccountsService property: {name}: {result.stdout!r}')
    return parts[1]


def set_property(uid, method, value, runner=run):
    command = ['busctl', '--system', 'call', SERVICE, object_path(uid), INTERFACE,
               method, 's', value]
    result = runner(command, check=False)
    if result.returncode: runner(command, privileged=True)


def session_changes(available):
    if 'SetSession' in available:
        result = {'Session': ('SetSession', 'dwm')}
    elif 'SetXSession' in available:
        result = {'XSession': ('SetXSession', 'dwm')}
    else:
        return {}
    if 'SetSessionType' in available:
        result['SessionType'] = ('SetSessionType', 'x11')
    return result


def service_inactive(runner=run):
    result = runner(['systemctl', 'is-active', 'accounts-daemon.service'], check=False)
    return result.stdout.strip() in ('inactive', 'failed', 'unknown')


def main(argv):
    if len(argv) != 3:
        print('Usage: python3 set-default-session.py USER BACKUP_DIRECTORY', file=sys.stderr)
        return 2
    if os.geteuid() == 0: raise RuntimeError('Run as the desktop user, not root')
    if re.search(r'^NoNewPrivs:\s+1$', Path('/proc/self/status').read_text(), re.M):
        print('NoNewPrivs=1: run the installer in a native Ubuntu terminal; no session settings changed.', file=sys.stderr)
        return 77
    account = pwd.getpwnam(argv[1])
    if account.pw_uid != os.getuid(): raise RuntimeError('Only your own session may be changed')
    home = Path(account.pw_dir)
    backup = Path(argv[2]).absolute()
    ancestors_safe(backup)
    if backup.is_symlink() or not backup.is_dir() or backup.stat().st_uid != account.pw_uid:
        raise RuntimeError('Backup must be an existing directory owned by the desktop user')
    if not backup.is_relative_to(home / '.local/state/ubuntu-dwm-setup'):
        raise RuntimeError('Backup must be inside ~/.local/state/ubuntu-dwm-setup')
    validate_desktop()
    dmrc = home / '.dmrc'
    ancestors_safe(dmrc)
    if dmrc.is_dir() and not dmrc.is_symlink(): raise RuntimeError('~/.dmrc is a directory')
    # Read a symlink's content only; back up the link and atomically replace its leaf.
    dmrc_text = dmrc.read_text() if dmrc.exists() else ''
    new_dmrc = update_ini(dmrc_text, 'Desktop', {'Session': 'dwm'})
    # The installer has already authenticated; fail explicitly if that expired.
    run(['true'], privileged=True)
    account_file = Path('/var/lib/AccountsService/users') / account.pw_name
    ancestors_safe(account_file)
    exists_result = run(['test', '-e', account_file], privileged=True, check=False)
    existed = exists_result.returncode == 0
    if run(['test', '-L', account_file], privileged=True, check=False).returncode == 0:
        raise RuntimeError('Refusing a symlink AccountsService user file')
    changes = session_changes(methods(account.pw_uid))
    previous = {}
    if changes:
        for name, (method, value) in changes.items():
            previous[name] = {'method': method, 'value': get_property(account.pw_uid, name)}
        provider = 'accountsservice-dbus'
        new_account = None
    else:
        if not service_inactive():
            raise RuntimeError('AccountsService is active or its state is unknown, but its session API is unavailable; refusing a stale file override')
        raw = run(['cat', account_file], privileged=True).stdout if existed else ''
        parser = configparser.ConfigParser(interpolation=None, strict=False)
        parser.optionxform = str
        if raw.strip(): parser.read_string(raw)
        for name in ('Session', 'XSession', 'SessionType'):
            previous[name] = {'method': 'Set' + name, 'value': parser.get('User', name, fallback='')}
        new_account = update_ini(raw, 'User', {'Session': 'dwm', 'XSession': 'dwm', 'SessionType': 'x11'})
        provider = 'accountsservice-file'
    state = {'version': 1, 'user': account.pw_name, 'uid': account.pw_uid, 'home': str(home),
             'provider': provider, 'previous': previous, 'account_file_existed': existed,
             'account_file': str(account_file), 'completed': False}
    state_path = backup / 'session-state.json'
    if state_path.exists(): raise RuntimeError('This backup already contains a session snapshot; use a fresh installation backup')
    session_backup = backup / 'session'
    if session_backup.is_symlink(): raise RuntimeError('Session backup must not be a symlink')
    session_backup.mkdir(mode=0o700, exist_ok=True)
    if existed: run(['cp', '-a', '--', account_file, session_backup/'accounts-user'], privileged=True)
    backup_user_file(home, backup, '.dmrc')
    write_atomic(state_path, json.dumps(state, indent=2) + '\n')
    if provider == 'accountsservice-dbus':
        for name, (method, value) in changes.items(): set_property(account.pw_uid, method, value)
        for name, (_, value) in changes.items():
            if get_property(account.pw_uid, name) != value:
                raise RuntimeError('AccountsService did not retain ' + name)
    else:
        # Only write this fallback when the daemon was confirmed inactive.
        # It reads the preserved per-user file on its next start; no daemon restart.
        if not service_inactive(): raise RuntimeError('AccountsService became active; retry with its D-Bus API')
        temporary = session_backup / 'accounts-user.new'
        write_atomic(temporary, new_account)
        if run(['test', '-d', account_file.parent], privileged=True, check=False).returncode != 0:
            run(['install', '-d', '-m', '700', account_file.parent], privileged=True)
        staged = account_file.with_name(account_file.name + f'.dwm-new-{os.getpid()}')
        run(['install', '-m', '600', '--', temporary, staged], privileged=True)
        run(['mv', '-fT', '--', staged, account_file], privileged=True)
        temporary.unlink()
    write_atomic(dmrc, new_dmrc)
    state['completed'] = True
    write_atomic(state_path, json.dumps(state, indent=2) + '\n')
    print('Default session saved for ' + account.pw_name + ': DWM / X11. Current login remains active.')
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main(sys.argv))
    except (OSError, RuntimeError, KeyError, ValueError, configparser.Error, subprocess.SubprocessError) as exc:
        print('Default-session setup failed: ' + str(exc), file=sys.stderr)
        sys.exit(1)
