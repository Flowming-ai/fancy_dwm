#!/usr/bin/env python3
"""Optional FortiClient VPN-only install; no VPN profiles or credentials are copied."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
SERVICE = 'forticlient.service'


def run(args, check=True):
    return subprocess.run(list(map(str, args)), check=check, text=True,
                          capture_output=True, timeout=30)


def specification():
    spec = json.loads((ROOT / 'scripts/downloads.json').read_text())['forticlient']
    asset = spec['amd64']
    url = urlparse(asset['url'])
    if (url.scheme != 'https' or url.netloc != 'filestore.fortinet.com'
            or not url.path.startswith('/forticlient/downloads/')
            or not re.fullmatch('[a-f0-9]{64}', asset['sha256'])):
        raise RuntimeError('Invalid pinned Fortinet download specification')
    return spec


def validate_package(path, spec):
    with path.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    if digest != spec['amd64']['sha256']:
        raise RuntimeError('FortiClient SHA-256 mismatch; package was not installed')
    fields = run(['dpkg-deb', '-f', path, 'Package', 'Version', 'Architecture']).stdout
    actual = dict(line.split(': ', 1) for line in fields.splitlines())
    expected = {'Package': 'forticlient', 'Version': spec['version'], 'Architecture': 'amd64'}
    if actual != expected:
        raise RuntimeError('Unexpected FortiClient package metadata: ' + repr(actual))


def preflight():
    if run(['dpkg', '--print-architecture']).stdout.strip() != 'amd64':
        raise RuntimeError('The pinned FortiClient VPN-only package supports amd64 only; omit --with-forticlient/--full')
    os_info = dict(line.split('=', 1) for line in Path('/etc/os-release').read_text().splitlines()
                   if '=' in line)
    if os_info.get('ID', '').strip('"') != 'ubuntu' or os_info.get('VERSION_ID', '').strip('"') not in ('24.04', '26.04'):
        raise RuntimeError('This module targets Ubuntu 24.04 / 26.04')


def installed_package():
    result = run(['dpkg-query', '-W', '-f=${Status}\t${Version}', 'forticlient'], check=False)
    parts = result.stdout.strip().split('\t')
    return parts if len(parts) == 2 else ['', '']


def apply(spec, local_package=None, state_dir=None):
    if os.geteuid() == 0:
        raise RuntimeError('Run as the desktop user; this module invokes sudo when needed')
    status, version = installed_package()
    before = {'package_status': status, 'package_version': version,
              'service_enabled': run(['systemctl', 'is-enabled', SERVICE], False).stdout.strip(),
              'service_active': run(['systemctl', 'is-active', SERVICE], False).stdout.strip()}
    # An upgrade can run vendor maintainer scripts that stop the scheduler.
    # Preserve any healthy installation; upgrades are a separate deliberate task.
    keep = bool(version) and status == 'install ok installed'
    if not keep and before['service_active'] == 'active':
        raise RuntimeError('FortiClient is active but its package is incomplete; repair it separately after disconnecting the VPN')
    if not keep and version and run(
            ['dpkg', '--compare-versions', version, 'gt', spec['version']], False).returncode == 0:
        raise RuntimeError('A newer incomplete FortiClient package exists; refusing to replace it with this older pinned package')
    if state_dir is not None:
        state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        record = state_dir / 'forticlient-before.json'
        with record.open('x') as stream:
            json.dump(before, stream, indent=2)
            stream.write('\n')
        record.chmod(0o600)
    if not keep:
        with tempfile.TemporaryDirectory(prefix='dwm-forticlient-') as temporary:
            target = Path(temporary) / 'forticlient.deb'
            if local_package is not None:
                # Stage the verified bytes so later path replacement cannot change them.
                target.write_bytes(local_package.read_bytes())
            else:
                subprocess.run(['curl', '--fail', '--location', '--proto', '=https',
                                '--proto-redir', '=https', '--retry', '2',
                                '--connect-timeout', '20', '--max-time', '900',
                                '--output', str(target), spec['amd64']['url']], check=True)
            validate_package(target, spec)
            print('Installing verified VPN-only package; sudo may request your password.', flush=True)
            subprocess.run(['sudo', 'apt-get', '--no-remove', 'install', '-y',
                            'libnss3-tools', str(target)], check=True)
    else:
        print('Keeping installed FortiClient ' + version)
    # enable --now starts an inactive scheduler but does not restart an active VPN.
    subprocess.run(['sudo', 'systemctl', 'enable', '--now', SERVICE], check=True)
    if installed_package()[0] != 'install ok installed':
        raise RuntimeError('FortiClient did not reach configured package state')
    if run(['systemctl', 'is-active', SERVICE], False).stdout.strip() != 'active':
        raise RuntimeError('FortiClient scheduler did not start')
    print('FortiClient installed; configure your VPN gateway and complete SAML login in its UI.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--check', action='store_true', help='Read-only local preflight; no download, sudo or service changes')
    group.add_argument('--apply', action='store_true')
    parser.add_argument('--package', type=Path, help='Use a local copy of the exact pinned package; SHA-256 still required')
    parser.add_argument('--state-dir', type=Path, help='Save prior package/service status (never VPN account data)')
    args = parser.parse_args()
    preflight()
    spec = specification()
    if args.check:
        if args.package:
            validate_package(args.package, spec)
        print('FortiClient local preflight passed; pinned VPN-only version ' + spec['version'])
        print('Ubuntu 26.04/DWM was used locally; this is not a claim of vendor-certified support.')
        return
    apply(spec, args.package, args.state_dir)


if __name__ == '__main__':
    try:
        main()
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
        raise SystemExit('FortiClient setup stopped: ' + str(error))
