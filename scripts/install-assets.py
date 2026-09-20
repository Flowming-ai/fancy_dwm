#!/usr/bin/env python3
"""Fetch pinned assets as the desktop user; back up and apply only managed trees."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile

LOCK = Path(__file__).with_name('downloads.json')


def download(spec, target):
    subprocess.run([
        'curl', '--fail', '--location', '--retry', '3', '--connect-timeout', '20',
        '--max-time', '600', '--proto', '=https', '--proto-redir', '=https',
        '--tlsv1.2', '--output', str(target), spec['url'],
    ], check=True)
    with target.open('rb') as source:
        digest = hashlib.file_digest(source, 'sha256').hexdigest()
    if digest != spec['sha256']:
        raise RuntimeError(f'SHA256 mismatch: {target.name}; refusing to use download')


def unpack_file(archive, basename, target):
    with tarfile.open(archive) as tar:
        candidates = [m for m in tar if m.isfile() and Path(m.name).name == basename
                      and (basename != 'fastfetch' or m.name.endswith('/usr/bin/fastfetch')
                           or m.name == 'usr/bin/fastfetch')]
        if len(candidates) != 1:
            raise RuntimeError(f'Expected exactly one {basename} in {archive.name}')
        with tar.extractfile(candidates[0]) as source, target.open('wb') as dest:
            shutil.copyfileobj(source, dest)
    with target.open('rb') as binary:
        if binary.read(4) != b'\x7fELF':
            raise RuntimeError(f'{basename} is not an ELF executable')
    target.chmod(0o755)


def git_checkout(spec, target):
    # No installer from a remote repository is executed.
    subprocess.run(['git', '-c', 'init.templateDir=', '-c', 'core.hooksPath=/dev/null',
                    'init', '--quiet', str(target)], check=True)
    prefix = ['git', '-c', 'core.hooksPath=/dev/null', '-C', str(target)]
    subprocess.run(prefix + ['remote', 'add', 'origin', spec['url']], check=True)
    subprocess.run(prefix + ['fetch', '--depth', '1', 'origin', spec['commit']], check=True)
    subprocess.run(prefix + ['-c', 'advice.detachedHead=false', 'checkout', '--detach',
                              spec['commit']], check=True)
    actual = subprocess.check_output(prefix + ['rev-parse', 'HEAD'], text=True).strip()
    if actual != spec['commit']:
        raise RuntimeError(f'Git commit mismatch in {target.name}')


def prepare(arch, stage, starship, fastfetch):
    lock = json.loads(LOCK.read_text())
    downloads = stage / 'downloads'
    downloads.mkdir()
    artifacts = stage / 'artifacts'
    artifacts.mkdir()
    for name, needed in [('starship', starship), ('fastfetch', fastfetch)]:
        if not needed:
            continue
        archive = downloads / (name + '.tar.gz')
        download(lock[name][arch], archive)
        unpack_file(archive, name, artifacts / name)
        subprocess.run([str(artifacts / name), '--version'], check=True)
    font_archive = downloads / 'JetBrainsMono.tar.xz'
    download(lock['font'], font_archive)
    font_dir = stage / 'fonts'
    font_dir.mkdir()
    count = 0
    with tarfile.open(font_archive) as tar:
        for member in tar:
            name = Path(member.name).name
            if not member.isfile() or not (
                (name.startswith('JetBrainsMonoNerdFontMono-') and name.endswith('.ttf'))
                or name in ('OFL.txt', 'LICENSE')
            ):
                continue
            dest = font_dir / name
            if dest.exists():
                raise RuntimeError(f'Duplicate font archive entry: {name}')
            with tar.extractfile(member) as source, dest.open('wb') as output:
                shutil.copyfileobj(source, output)
            dest.chmod(0o644)
            count += name.endswith('.ttf')
    if not count:
        raise RuntimeError('Pinned font archive contained no JetBrainsMono Nerd Font Mono files')
    for name, spec in lock['git'].items():
        git_checkout(spec, stage / name)
    shutil.copy2(LOCK, stage / 'downloads-used.json')


def remove(path):
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    elif path.exists() or path.is_symlink():
        path.unlink()


def save(home, backup, relative):
    target = home / relative
    manifest = backup / 'user-files.txt'
    already = manifest.read_text().splitlines() if manifest.exists() else []
    if relative in already:
        return
    old = backup / 'home' / relative
    old.parent.mkdir(parents=True, exist_ok=True)
    if target.is_dir() and not target.is_symlink():
        shutil.copytree(target, old, symlinks=True)
    elif target.exists() or target.is_symlink():
        shutil.copy2(target, old, follow_symlinks=False)
    with manifest.open('a') as output:
        output.write(relative + '\n')


def replace_tree(source, home, backup, relative):
    target = home / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + f'.dwm-new-{os.getpid()}')
    previous = target.with_name(target.name + f'.dwm-old-{os.getpid()}')
    if temporary.exists() or temporary.is_symlink() or previous.exists() or previous.is_symlink():
        raise RuntimeError(f'Unexpected staging path beside {target}')
    shutil.copytree(source, temporary, symlinks=True)
    save(home, backup, relative)
    moved = False
    try:
        if target.exists() or target.is_symlink():
            target.replace(previous)
            moved = True
        temporary.replace(target)
    except BaseException:
        if moved and not (target.exists() or target.is_symlink()):
            previous.replace(target)
        raise
    finally:
        remove(temporary)
    remove(previous)


def preflight(home):
    for relative in ('.oh-my-zsh', '.local/share/fonts/JetBrainsMono'):
        parent = (home / relative).parent
        while parent != home:
            if parent.is_symlink():
                raise RuntimeError(f'Managed asset parent is a symlink: {parent}')
            parent = parent.parent
    if (home / '.oh-my-zsh/custom/plugins').is_symlink():
        raise RuntimeError('Existing Oh My Zsh custom/plugins is a symlink; use a real directory first')


def apply(stage, home, backup):
    preflight(home)
    omz = stage / 'ohmyzsh'
    existing_custom = home / '.oh-my-zsh/custom'
    if existing_custom.is_dir():
        shutil.copytree(existing_custom, omz / 'custom', symlinks=True, dirs_exist_ok=True)
    for plugin in ('zsh-autosuggestions', 'zsh-syntax-highlighting'):
        target = omz / 'custom/plugins' / plugin
        remove(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(stage / plugin, target, symlinks=True)
    replace_tree(omz, home, backup, '.oh-my-zsh')
    replace_tree(stage / 'fonts', home, backup, '.local/share/fonts/JetBrainsMono')


if __name__ == '__main__':
    if len(sys.argv) == 6 and sys.argv[1] == 'prepare':
        _, _, arch, stage, starship, fastfetch = sys.argv
        if arch not in ('amd64', 'arm64'):
            raise SystemExit('Unsupported architecture')
        prepare(arch, Path(stage), starship == '1', fastfetch == '1')
    elif len(sys.argv) == 3 and sys.argv[1] == 'check':
        preflight(Path(sys.argv[2]))
    elif len(sys.argv) == 5 and sys.argv[1] == 'apply':
        _, _, stage, home, backup = sys.argv
        apply(Path(stage), Path(home), Path(backup))
    else:
        raise SystemExit('Usage: install-assets.py prepare ARCH STAGE STARSHIP FASTFETCH | apply STAGE HOME BACKUP | check HOME')
