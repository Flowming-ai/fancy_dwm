#!/usr/bin/env bash
# Self-contained rollback; preview by default. Run as the desktop user.
if [ -z "${BASH_VERSION:-}" ]; then exec bash "$0" "$@"; fi
set -Eeuo pipefail
[[ $EUID != 0 ]] || { echo 'Run as your desktop user, without sudo before bash.' >&2; exit 1; }
[[ $# -ge 1 && $# -le 2 ]] || { echo 'Usage: bash rollback.sh BACKUP_DIRECTORY [--apply]' >&2; exit 2; }
mode=${2:---preview}
[[ $mode == --preview || $mode == --apply ]] || { echo 'Expected --apply or --preview.' >&2; exit 2; }
if [[ $mode == --apply ]]; then
    if [[ $(awk '/^NoNewPrivs:/ {print $2}' /proc/self/status) == 1 ]]; then
        echo 'NoNewPrivs=1: run rollback from a native Ubuntu terminal. No files changed.' >&2
        exit 77
    fi
    echo 'Rollback will restore the listed backup. sudo may request your local password.'
    sudo -v
fi
python3 - "$1" "$mode" "${BASH_SOURCE[0]}" <<'PY'
from pathlib import Path
from datetime import datetime
import json
import configparser
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


def run(args, privileged=False, check=True):
    command = (['sudo', '-n'] if privileged else []) + list(map(str, args))
    result = subprocess.run(command, text=True, capture_output=True, timeout=30)
    if check and result.returncode:
        raise RuntimeError(f'Command failed: {shlex.join(command)}\n{result.stderr.strip()}')
    return result


def ancestors_safe(path):
    for parent in path.absolute().parents:
        if parent.is_symlink():
            raise RuntimeError(f'Refusing a path with a symlink parent: {path} ({parent})')


def exists(path, privileged=False):
    if privileged:
        return (run(['test', '-e', path], True, False).returncode == 0 or
                run(['test', '-L', path], True, False).returncode == 0)
    return path.exists() or path.is_symlink()


def copy_user(source, destination):
    ancestors_safe(source)
    ancestors_safe(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() or destination.is_symlink():
        raise RuntimeError('Backup destination already exists: ' + str(destination))
    if source.is_dir() and not source.is_symlink():
        shutil.copytree(source, destination, symlinks=True)
    else:
        shutil.copy2(source, destination, follow_symlinks=False)


def restore_user(target, original):
    ancestors_safe(target)
    ancestors_safe(original)
    # Never recurse into a symlink. copytree also copies nested symlinks verbatim.
    if target.is_symlink() or target.is_file():
        target.unlink()
    elif target.is_dir():
        shutil.rmtree(target)
    elif target.exists():
        raise RuntimeError('Refusing a special target file: ' + str(target))
    if exists(original): copy_user(original, target)


def read_manifest(path):
    if not path.exists(): return []
    if path.is_symlink(): raise RuntimeError('Manifest must not be a symlink: ' + str(path))
    return list(dict.fromkeys(line for line in path.read_text().splitlines() if line))


def allowed_system(path, username):
    if '..' in path.parts or not path.is_absolute(): return False
    if path.parent in (Path('/usr/local/bin'), Path('/usr/local/share/man/man1')):
        return bool(re.fullmatch(r'[A-Za-z0-9_.+-]+', path.name))
    return path in (Path('/usr/share/xsessions/dwm.desktop'),
                    Path('/usr/local/share/dwm/larbs.mom'),
                    Path('/var/lib/AccountsService/users') / username)


def build_plan(backup, home, username):
    plan = []
    relatives = []
    for raw in read_manifest(backup/'user-files.txt'):
        relative = Path(raw)
        if relative.is_absolute() or '..' in relative.parts or relative == Path('.'):
            raise RuntimeError('Invalid user manifest path: ' + repr(raw))
        for other in relatives:
            if relative.is_relative_to(other) or other.is_relative_to(relative):
                raise RuntimeError('Overlapping user manifest paths: ' + raw + ' / ' + str(other))
        relatives.append(relative)
        plan.append((False, home/relative, backup/'home'/relative, Path('home')/relative))
    for raw in read_manifest(backup/'system-files.txt'):
        target = Path(raw)
        if not allowed_system(target, username):
            raise RuntimeError('Invalid system manifest path: ' + repr(raw))
        relative = target.relative_to('/')
        plan.append((True, target, backup/'system'/relative, Path('system')/relative))
    for privileged, target, original, relative in plan:
        ancestors_safe(target)
        ancestors_safe(original)
        if privileged and original.is_dir() and not original.is_symlink():
            raise RuntimeError('System backup must contain files, not directories: ' + str(original))
    return plan


def api_methods(uid):
    args = ['busctl', '--system', '--no-pager', 'introspect', SERVICE,
            f'/org/freedesktop/Accounts/User{uid}', INTERFACE]
    result = run(args, check=False)
    if result.returncode: result = run(args, True, False)
    return set(re.findall(r'^\s*\.?(Set\w+)\s+method\b', result.stdout, re.M)) if result.returncode == 0 else set()


def property_value(uid, name):
    args = ['busctl', '--system', 'get-property', SERVICE,
            f'/org/freedesktop/Accounts/User{uid}', INTERFACE, name]
    result = run(args, check=False)
    if result.returncode: result = run(args, True)
    parts = shlex.split(result.stdout.strip())
    if len(parts) != 2 or parts[0] != 's': raise RuntimeError('Unexpected AccountsService property: ' + name)
    return parts[1]


def change_property(uid, method, value):
    args = ['busctl', '--system', 'call', SERVICE, f'/org/freedesktop/Accounts/User{uid}',
            INTERFACE, method, 's', value]
    result = run(args, check=False)
    if result.returncode: run(args, True)


def validate_session(state, account):
    if (state.get('user') != account.pw_name or state.get('uid') != account.pw_uid
            or state.get('home') != account.pw_dir):
        raise RuntimeError('Session backup belongs to a different user or home')
    expected = '/var/lib/AccountsService/users/' + account.pw_name
    if state.get('account_file') != expected: raise RuntimeError('Invalid session account file')
    if state.get('provider') not in ('accountsservice-dbus', 'accountsservice-file'):
        raise RuntimeError('Unknown session backup provider')
    for name, item in state.get('previous', {}).items():
        if name not in ('Session', 'XSession', 'SessionType') or item.get('method') != 'Set' + name:
            raise RuntimeError('Invalid saved session method')
        if not isinstance(item.get('value'), str) or '\x00' in item['value']:
            raise RuntimeError('Invalid saved session value')


def append_session_file(plan, state, backup):
    target = Path(state['account_file'])
    original = backup/'session/accounts-user'
    ancestors_safe(target)
    ancestors_safe(original)
    if state['account_file_existed'] and not exists(original):
        raise RuntimeError('Missing original AccountsService file in backup')
    if original.is_symlink() or original.is_dir():
        raise RuntimeError('AccountsService backup must be a regular file')
    if not any(existing == target for _, existing, _, _ in plan):
        plan.append((True, target, original, Path('system')/target.relative_to('/')))


def main(argv):
    backup = Path(argv[1]).absolute()
    apply = argv[2] == '--apply'
    account = pwd.getpwuid(os.getuid())
    home = Path(account.pw_dir)
    ancestors_safe(backup)
    if backup.is_symlink() or not backup.is_dir() or backup.stat().st_uid != account.pw_uid:
        raise RuntimeError('Select an existing backup directory owned by your user')
    identity_path = backup/'identity.json'
    if identity_path.is_symlink(): raise RuntimeError('identity.json must not be a symlink')
    identity = json.loads(identity_path.read_text())
    if (identity.get('user') != account.pw_name or identity.get('uid') != account.pw_uid
            or identity.get('home') != account.pw_dir):
        raise RuntimeError('Backup belongs to a different user, UID, or home directory')
    previous_shell = identity.get('shell', '')
    if previous_shell and (not isinstance(previous_shell, str) or not previous_shell.startswith('/')
                           or '\x00' in previous_shell):
        raise RuntimeError('Invalid original shell')
    plan = build_plan(backup, home, account.pw_name)
    state_path = backup/'session-state.json'
    if state_path.is_symlink(): raise RuntimeError('Session state must not be a symlink')
    state = json.loads(state_path.read_text()) if state_path.exists() else None
    if state: validate_session(state, account)
    if state and state['provider'] == 'accountsservice-file':
        append_session_file(plan, state, backup)
    for privileged, target, original, relative in plan:
        print(('RESTORE' if exists(original) else 'REMOVE NEW FILE') + ': ' + str(target), flush=True)
    if previous_shell: print('RESTORE LOGIN SHELL: ' + previous_shell)
    if state: print('RESTORE DEFAULT SESSION: ' + json.dumps(state['previous'], ensure_ascii=False))
    if state and state['provider'] == 'accountsservice-dbus':
        print('SESSION FILE FALLBACK, only if AccountsService is inactive: ' + state['account_file'])
    if not apply:
        print('\nPreview only. Run again with --apply to restore. Packages and apt repositories remain installed.')
        return 0
    if previous_shell and not (Path(previous_shell).is_file() and os.access(previous_shell, os.X_OK)):
        raise RuntimeError('Original shell is no longer executable: ' + previous_shell)
    session_api = []
    current_session = None
    if state:
        available = api_methods(account.pw_uid)
        for name, item in state['previous'].items():
            if item['method'] in available:
                session_api.append((name, item['method'], item['value']))
        uses_api = any(name in ('Session', 'XSession') for name, _, _ in session_api)
        if not uses_api:
            status = run(['systemctl', 'is-active', 'accounts-daemon.service'], check=False)
            if status.stdout.strip() not in ('inactive', 'failed', 'unknown'):
                raise RuntimeError('Cannot restore session API while AccountsService is active or its state is unknown')
        # A file-based setup must restore the exact file as well as refresh a live API.
        if state['provider'] == 'accountsservice-file' or not uses_api:
            append_session_file(plan, state, backup)
        current_session = {'version': 1, 'user': account.pw_name, 'uid': account.pw_uid,
                           'home': account.pw_dir, 'account_file': state['account_file'],
                           'account_file_existed': exists(Path(state['account_file']), True),
                           'provider': 'accountsservice-dbus' if uses_api else 'accountsservice-file',
                           'previous': {}, 'completed': True}
        if uses_api:
            current_session['previous'] = {name: {'method': method, 'value': property_value(account.pw_uid, name)}
                                           for name, method, value in session_api}
        else:
            # Retain raw per-user values for a self-contained undo of this rollback.
            parser = configparser.ConfigParser(interpolation=None, strict=False)
            parser.optionxform = str
            if current_session['account_file_existed']:
                parser.read_string(run(['cat', state['account_file']], True).stdout)
            current_session['previous'] = {name: {'method': 'Set'+name, 'value': parser.get('User', name, fallback='')}
                                           for name in ('Session', 'XSession', 'SessionType')}
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S') + f'-{os.getpid()}'
    current = home/'.local/state/ubuntu-dwm-setup'/('rollback-current-' + stamp)
    ancestors_safe(current)
    current.mkdir(parents=True, mode=0o700)
    (current/'identity.json').write_text(json.dumps({'user': account.pw_name, 'uid': account.pw_uid,
                                                   'home': account.pw_dir, 'shell': account.pw_shell}, indent=2)+'\n')
    shutil.copy2(Path(argv[3]), current/'rollback.sh')
    # Snapshot every current target before changing any file.
    for privileged, target, original, relative in plan:
        ancestors_safe(target)
        saved = current/relative
        saved.parent.mkdir(parents=True, exist_ok=True)
        with (current/('system-files.txt' if privileged else 'user-files.txt')).open('a') as stream:
            stream.write((str(target) if privileged else str(target.relative_to(home))) + '\n')
        if exists(target, privileged):
            if privileged:
                if (run(['test', '-d', target], True, False).returncode == 0 and
                        run(['test', '-L', target], True, False).returncode != 0):
                    raise RuntimeError('Refusing a system directory: ' + str(target))
                run(['cp', '-a', '--', target, saved], True)
            else: copy_user(target, saved)
    if current_session:
        (current/'session').mkdir(mode=0o700)
        if current_session['account_file_existed']:
            run(['cp', '-a', '--', current_session['account_file'], current/'session/accounts-user'], True)
        (current/'session-state.json').write_text(json.dumps(current_session, indent=2)+'\n')
    for privileged, target, original, relative in plan:
        ancestors_safe(target)
        ancestors_safe(original)
        if privileged:
            if exists(original):
                run(['mkdir', '-p', '--', target.parent], True)
                temporary = Path(run(['mktemp', '--tmpdir=' + str(target.parent), '.dwm-rollback.XXXXXX'], True).stdout.strip())
                if temporary.parent != target.parent:
                    raise RuntimeError('Unexpected temporary system path: ' + str(temporary))
                run(['cp', '-a', '--', original, temporary], True)
                run(['mv', '-fT', '--', temporary, target], True)
            else: run(['rm', '-f', '--', target], True)
        else: restore_user(target, original)
    if previous_shell and previous_shell != account.pw_shell:
        run(['chsh', '-s', previous_shell, account.pw_name], True)
    for name, method, value in session_api:
        change_property(account.pw_uid, method, value)
    for name, method, value in session_api:
        if property_value(account.pw_uid, name) != value:
            raise RuntimeError('Could not verify restored session property: ' + name)
    print('\nRollback complete. Previous current state was saved to: ' + str(current))
    print('Installed packages and apt repositories remain. No logout or restart was performed.')
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main(sys.argv))
    except (OSError, RuntimeError, KeyError, ValueError, configparser.Error, subprocess.SubprocessError) as exc:
        print('Rollback failed: ' + str(exc), file=sys.stderr)
        sys.exit(1)
PY
