#!/usr/bin/env python3
"""Apply curated user settings without starting programs or copying personal data.

Usage: apply-user.py PAYLOAD USER_HOME BACKUP
       apply-user.py --check PAYLOAD USER_HOME
The backup contract is user-files.txt plus home/<relative path>. A manifest
entry without a saved original denotes a newly created path. Reusing the same
backup never overwrites the first snapshot. Dictionary directories are untouched.
"""
import configparser
import io
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile

# Exact initial generated file only: never strip arbitrary personal Zsh code.
LEGACY_ZSHRC = '# Managed by install-desktop.sh; put personal additions in ~/.zshrc.local.\nexport ZSH="$HOME/.oh-my-zsh"\nexport ZSH_CACHE_DIR="$HOME/.cache/oh-my-zsh"\nexport STARSHIP_CONFIG="$HOME/.config/starship.toml"\nexport BAT_CONFIG_PATH="$HOME/.config/bat/config"\nexport PATH="$HOME/.local/bin:$PATH"\nZSH_THEME=""\nzstyle \':omz:update\' mode reminder\nplugins=(git zsh-autosuggestions)\nHISTFILE="$HOME/.zsh_history"\nHISTSIZE=50000\nSAVEHIST=50000\nsetopt HIST_IGNORE_DUPS HIST_REDUCE_BLANKS SHARE_HISTORY\nZSH_AUTOSUGGEST_HIGHLIGHT_STYLE=\'fg=244\'\n[[ -r "$ZSH/oh-my-zsh.sh" ]] && source "$ZSH/oh-my-zsh.sh"\nbindkey -e\nbindkey \'^[[A\' up-line-or-search\nbindkey \'^[[B\' down-line-or-search\nalias ls=\'eza --icons\'\nalias ll=\'eza --icons --long --group-directories-first --git\'\nalias la=\'eza --icons --all --long --group-directories-first\'\nalias tree=\'eza --icons --tree\'\nalias cat=\'bat\'\nalias top=\'btop\'\n[[ -r "$HOME/.zshrc.local" ]] && source "$HOME/.zshrc.local"\ncommand -v starship >/dev/null && eval "$(starship init zsh)"\n# Show system info once per terminal, excluding noninteractive `zsh -ic` checks.\nif [[ -o interactive && -t 1 && -z ${DESKTOP_FETCH_SHOWN:-} && -z ${DESKTOP_SETUP_TEST:-} ]]; then\n    export DESKTOP_FETCH_SHOWN=1\n    command -v fastfetch >/dev/null && fastfetch\nfi\n# Upstream requires highlighting after other ZLE widgets and prompt setup.\n[[ -r "$ZSH/custom/plugins/zsh-syntax-highlighting/zsh-syntax-highlighting.zsh" ]] &&\n    source "$ZSH/custom/plugins/zsh-syntax-highlighting/zsh-syntax-highlighting.zsh"\n'


def ini(text):
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    parser.optionxform = str
    if text.strip():
        parser.read_string(text)
    return parser


def render(parser):
    stream = io.StringIO()
    parser.write(stream, space_around_delimiters=False)
    return stream.getvalue()


def set_values(parser, section, values, defaults=False):
    if not parser.has_section(section):
        parser.add_section(section)
    for key, value in values.items():
        if not defaults or not parser.has_option(section, key):
            parser.set(section, key, value)


def managed_block(text, name, content=None):
    begin, end = '# BEGIN ' + name, '# END ' + name
    pattern = re.compile(r'^' + re.escape(begin) + r'\n.*?^' + re.escape(end) + r'(?:\n|$)', re.M | re.S)
    if (begin in text or end in text) and not pattern.search(text):
        raise ValueError(f'Incomplete managed block {name}; preserve it and fix its markers first')
    if content is None:
        return pattern.sub('', text)
    block = begin + '\n' + content.rstrip() + '\n' + end + '\n'
    if pattern.search(text):
        # Replace once and remove any duplicate managed copies.
        first = True
        def replace(_match):
            nonlocal first
            if first:
                first = False
                return block
            return ''
        return pattern.sub(replace, text)
    return text + ('\n' if text and not text.endswith('\n') else '') + ('\n' if text else '') + block


def root_values(text, values, default_values=None):
    """Fcitx addon files have root keys before any [section]; preserve the rest."""
    match = re.search(r'^\[', text, re.M)
    head, tail = (text[:match.start()], text[match.start():]) if match else (text, '')
    for key, value in values.items():
        pattern = re.compile(r'^' + re.escape(key) + r'=.*$', re.M)
        if pattern.search(head):
            head = pattern.sub(key + '=' + value, head)
        else:
            head += ('' if not head or head.endswith('\n') else '\n') + key + '=' + value + '\n'
    for key, value in (default_values or {}).items():
        if not re.search(r'^' + re.escape(key) + r'=', head, re.M):
            head += ('' if not head or head.endswith('\n') else '\n') + key + '=' + value + '\n'
    return head + tail


def apply(package, home, backup=None, check=False):
    package, home = package.resolve(), home.resolve()
    backup = backup.resolve() if backup is not None else None
    if not check and backup is None:
        raise ValueError("A backup directory is required")
    if not (package / 'home').is_dir() or not (package / 'src').is_dir():
        raise ValueError('Payload must contain home/ and src/')
    if not home.is_dir():
        raise ValueError('USER_HOME must already exist')
    manifest = backup / 'user-files.txt' if backup is not None else None
    saved = set(manifest.read_text().splitlines()) if manifest is not None and manifest.exists() else set()
    pending = {}

    def safe(relative, directory=False):
        rel = Path(relative)
        if rel.is_absolute() or '..' in rel.parts or not rel.parts:
            raise ValueError(f'Unsafe relative path: {relative}')
        current = home
        for part in rel.parts[:-1]:
            current /= part
            if current.is_symlink():
                raise ValueError(f'Refusing symlink ancestor: {current}')
            if current.exists() and not current.is_dir():
                raise ValueError(f'Ancestor is not a directory: {current}')
        target = home / rel
        if target.exists() and not target.is_symlink() and target.is_dir() != directory:
            raise ValueError(f'Unexpected file type: {target}')
        return target

    def read(relative):
        path = safe(relative)
        return path.read_text() if path.exists() else ''

    def plan(relative, text, mode=None):
        target = safe(relative)
        if mode is None:
            mode = target.stat().st_mode & 0o777 if target.exists() else 0o644
        pending[str(relative)] = (text.encode(), mode)

    # Build and validate every planned change before writing any user file.
    for source in sorted((package / 'home').rglob('*')):
        if source.is_symlink():
            raise ValueError(f'Payload symlinks are not accepted: {source}')
        if source.is_file():
            relative = str(source.relative_to(package / 'home'))
            safe(relative)
            pending[relative] = (source.read_bytes(), source.stat().st_mode & 0o777)

    shell = read('.zshrc')
    if LEGACY_ZSHRC and shell.startswith(LEGACY_ZSHRC):
        shell = shell[len(LEGACY_ZSHRC):]
    shell = managed_block(shell, 'FCITX5-ENV')
    shell = managed_block(shell, 'DWM-SHELL',
                          '[ -r "$HOME/.config/dwm-shell/zshrc" ] && source "$HOME/.config/dwm-shell/zshrc"')
    plan('.zshrc', shell)
    profile = managed_block(read('.profile'), 'FCITX5-ENV',
                            '[ -r "$HOME/.config/fcitx5/dwm-env.sh" ] && . "$HOME/.config/fcitx5/dwm-env.sh"')
    plan('.profile', profile)
    # Retire only our older startup block: the session now owns XScreenSaver.
    xprofile = read('.xprofile')
    if '# BEGIN DWM-XSCREENSAVER' in xprofile:
        plan('.xprofile', managed_block(xprofile, 'DWM-XSCREENSAVER'))

    cfg = ini(read('.config/fcitx5/config'))
    for section in cfg.sections():
        if not section.startswith('Hotkey'):
            continue
        for key, value in list(cfg.items(section)):
            parts = value.strip().lower().split('+')
            if parts[-1] == 'space' and set(parts[:-1]) in ({'super'}, {'shift', 'super'}):
                cfg.remove_option(section, key)
        entries = list(cfg.items(section))
        if entries and all(key.isdecimal() for key, _ in entries):
            values = [value for key, value in sorted(entries, key=lambda item: int(item[0]))]
            for key, _ in entries:
                cfg.remove_option(section, key)
            for index, value in enumerate(values):
                cfg.set(section, str(index), value)
    for section in ('Hotkey/EnumerateGroupForwardKeys', 'Hotkey/EnumerateGroupBackwardKeys'):
        set_values(cfg, section, {})  # Explicit empty sections suppress conflicting defaults.
    set_values(cfg, 'Hotkey/AltTriggerKeys', {'0': 'Shift_L'}, defaults=True)
    triggers = list(cfg.items('Hotkey/TriggerKeys')) if cfg.has_section('Hotkey/TriggerKeys') else []
    for key, _ in triggers:
        cfg.remove_option('Hotkey/TriggerKeys', key)
    set_values(cfg, 'Hotkey/TriggerKeys', {'0': 'Control+space'})
    extra = [value for _, value in triggers if value.strip().lower() != 'control+space']
    for index, value in enumerate(extra, 1):
        cfg.set('Hotkey/TriggerKeys', str(index), value)
    set_values(cfg, 'Behavior', {'ActiveByDefault': 'False', 'PreeditEnabledByDefault': 'True',
                                'DefaultPageSize': '7', 'PreloadInputMethod': 'True',
                                'AllowInputMethodForPassword': 'False', 'AutoSavePeriod': '5'}, defaults=True)
    plan('.config/fcitx5/config', render(cfg))

    # Ensure Pinyin belongs to the first active group, preserving all groups and
    # keyboard layouts. A Pinyin entry in some other group is insufficient.
    cfg = ini(read('.config/fcitx5/profile'))
    groups = sorted((name for name in cfg.sections() if re.fullmatch(r'Groups/\d+', name)),
                    key=lambda name: int(name.split('/')[1]))
    first_name = cfg.get('GroupOrder', '0', fallback='')
    group = next((name for name in groups if cfg.get(name, 'Name', fallback='') == first_name),
                 groups[0] if groups else 'Groups/0')
    group_name = cfg.get(group, 'Name', fallback='')
    if not group_name:
        used = {cfg.get(name, 'Name', fallback='') for name in groups}
        group_name, index = 'Default', 1
        while group_name in used:
            group_name, index = f'Default {index}', index + 1
    layout = cfg.get(group, 'Default Layout', fallback='us')
    set_values(cfg, group, {'Name': group_name, 'Default Layout': layout, 'DefaultIM': 'pinyin'})
    set_values(cfg, 'GroupOrder', {'0': group_name})
    items = [name for name in cfg.sections() if re.fullmatch(re.escape(group) + r'/Items/\d+', name)]
    if not items:
        set_values(cfg, group + '/Items/0', {'Name': 'keyboard-' + layout, 'Layout': ''})
        items = [group + '/Items/0']
    if not any(cfg.get(name, 'Name', fallback='') == 'pinyin' for name in items):
        index = max(int(name.rsplit('/', 1)[1]) for name in items) + 1
        set_values(cfg, f'{group}/Items/{index}', {'Name': 'pinyin', 'Layout': ''})
    plan('.config/fcitx5/profile', render(cfg))
    plan('.config/fcitx5/conf/pinyin.conf', root_values(read('.config/fcitx5/conf/pinyin.conf'),
         {'Prediction': 'True', 'PageSize': '7', 'KeepCurrentContext': 'True'},
         {'CloudPinyinEnabled': 'False', 'SpellEnabled': 'True', 'SymbolsEnabled': 'True',
          'VAsQuickphrase': 'True', 'FirstRun': 'False'}))
    plan('.config/fcitx5/conf/classicui.conf', root_values(read('.config/fcitx5/conf/classicui.conf'), {},
         {'Vertical Candidate List': 'False', 'Font': 'Noto Sans CJK SC 14',
          'MenuFont': 'Noto Sans CJK SC 12', 'Theme': 'default-dark',
          'DarkTheme': 'default-dark', 'UseDarkTheme': 'False'}))

    # These are subsequently changed by im-config / tic in the installer.
    xinput = safe('.xinputrc')
    if xinput.is_symlink():
        # Preserve the original link in the backup, not its external target.
        pending['.xinputrc'] = (xinput.read_bytes() if xinput.exists() else b'', 0o644)
    terminfo = safe('.terminfo', directory=True)
    if terminfo.is_symlink():
        raise ValueError('Refusing .terminfo symlink: tic must not write outside USER_HOME')
    source_relative = '.local/src/larbs-ubuntu'
    safe(source_relative, directory=True)
    if check:
        return len(pending)
    backup.mkdir(parents=True, exist_ok=True, mode=0o700)
    backup.chmod(0o700)

    def save(relative):
        if relative in saved:
            return
        path = home / relative
        old = backup / 'home' / relative
        old.parent.mkdir(parents=True, exist_ok=True)
        if old.exists() or old.is_symlink():
            raise ValueError(f'Backup exists without manifest entry: {old}')
        if path.is_symlink() or path.exists():
            if path.is_dir() and not path.is_symlink():
                shutil.copytree(path, old, symlinks=True)
            else:
                shutil.copy2(path, old, follow_symlinks=False)
        with manifest.open('a') as stream:
            stream.write(relative + '\n')
        manifest.chmod(0o600)
        saved.add(relative)

    for relative, (data, mode) in pending.items():
        path = home / relative
        save(relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(prefix='.dwm-setup-', dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(data)
        try:
            temporary.chmod(mode)
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
    save('.xinputrc')
    save('.terminfo')
    save(source_relative)
    source_root = home / source_relative
    source_root.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix='.dwm-source-', dir=source_root.parent))
    try:
        shutil.copytree(package / 'src', staging / 'sources', symlinks=True)
        if source_root.is_symlink():
            source_root.unlink()
        elif source_root.exists():
            shutil.rmtree(source_root)
        (staging / 'sources').replace(source_root)
    finally:
        shutil.rmtree(staging)
    return backup


if __name__ == '__main__':
    try:
        if len(sys.argv) == 4 and sys.argv[1] == '--check':
            count = apply(Path(sys.argv[2]), Path(sys.argv[3]), check=True)
            print(f'User configuration preflight passed: {count} planned files; no changes made')
        elif len(sys.argv) == 4:
            print('User settings applied; backup:', apply(*map(Path, sys.argv[1:])))
        else:
            raise SystemExit('Usage: apply-user.py [--check] PAYLOAD USER_HOME [BACKUP]')
    except (OSError, ValueError, configparser.Error) as error:
        raise SystemExit(f'Configuration update stopped: {error}')
