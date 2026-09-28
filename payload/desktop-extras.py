#!/usr/bin/env python3
"""Plan portable display scaling and a Teams entry; never launch applications.

The caller supplies safe read(relative) and plan(relative, text, mode=None)
callbacks, so these settings participate in apply-user's preflight and backup.
"""
import configparser
import io
from pathlib import Path
import re

SCALE_PERCENTAGES = (100, 125, 150, 175, 200)


def scale_values(percent):
    if type(percent) is not int or percent not in SCALE_PERCENTAGES:
        raise ValueError('Display scale must be one of: ' + ', '.join(map(str, SCALE_PERCENTAGES)))
    dpi = 96 * percent // 100
    return dpi, dpi * 1024, 24 * percent // 100


def block(text, content=None, marker='#', name='DWM-SCALE'):
    begin, end = f'{marker} BEGIN {name}', f'{marker} END {name}'
    pattern = re.compile(r'^' + re.escape(begin) + r'\n.*?^' + re.escape(end) + r'(?:\n|$)', re.M | re.S)
    if (begin in text or end in text) and not pattern.search(text):
        raise ValueError(f'Incomplete {name} block; fix its markers before installation')
    text = pattern.sub('', text)
    if content is None:
        return text
    return text.rstrip() + ('\n\n' if text.strip() else '') + begin + '\n' + content.rstrip() + '\n' + end + '\n'


def desktop_quote(value):
    # Desktop Entry Exec escaping is independent of shell quoting.
    value = str(value)
    if any(char in value for char in ('\n', '\r', '\x00')):
        raise ValueError('Desktop paths must not contain newlines or NUL')
    for original, escaped in (('\\', '\\\\'), ('"', '\\"'), ('`', '\\`'), ('$', '\\$'), ('%', '%%')):
        value = value.replace(original, escaped)
    # String-value unescaping precedes Exec argument unescaping.
    return '"' + value.replace('\\', '\\\\') + '"'


def configure(read, plan, home, percent=150):
    dpi, encoded_dpi, cursor_size = scale_values(percent)
    resources = block(read('.Xresources'), marker='!')
    resources = re.sub(r'^\s*(?:Xft\.dpi|Xcursor\.size)\s*:.*\n?', '', resources, flags=re.M)
    plan('.Xresources', block(resources, f'Xft.dpi: {dpi}\nXcursor.size: {cursor_size}', marker='!'))

    settings = block(read('.config/xsettingsd/xsettingsd.conf'))
    settings = re.sub(r'^\s*(?:Xft/DPI|Gdk/UnscaledDPI|Gdk/WindowScalingFactor|Gtk/CursorThemeSize)\s+.*\n?',
                      '', settings, flags=re.M)
    plan('.config/xsettingsd/xsettingsd.conf', block(settings,
         f'Xft/DPI {encoded_dpi}\nGdk/UnscaledDPI {encoded_dpi}\nGdk/WindowScalingFactor 1\nGtk/CursorThemeSize {cursor_size}'))
    for relative in ('.config/gtk-3.0/settings.ini', '.config/gtk-4.0/settings.ini'):
        cfg = configparser.ConfigParser(interpolation=None, strict=False)
        cfg.optionxform = str
        old = read(relative)
        if old.strip():
            cfg.read_string(old)
        if not cfg.has_section('Settings'):
            cfg.add_section('Settings')
        cfg.set('Settings', 'gtk-xft-dpi', str(encoded_dpi))
        stream = io.StringIO()
        cfg.write(stream, space_around_delimiters=False)
        plan(relative, stream.getvalue())
    gtk2 = block(read('.gtkrc-2.0'))
    gtk2 = re.sub(r'^\s*gtk-xft-dpi\s*=.*\n?', '', gtk2, flags=re.M)
    plan('.gtkrc-2.0', block(gtk2, f'gtk-xft-dpi = {encoded_dpi}'))

    # The installer already owns this theme; use its template, not monitor names
    # or geometry taken from the machine on which the snapshot was made.
    rofi = (Path(__file__).parent / 'home/.config/rofi/config.rasi').read_text()
    rofi = re.sub(r'^\s*dpi\s*:\s*[^;]+;[^\n]*\n?', '', rofi, flags=re.M)
    rofi = re.sub(r'(\bconfiguration\s*\{)', lambda match: match[0] + f'\n    dpi: {dpi};', rofi, count=1)
    plan('.config/rofi/config.rasi', rofi)

    # Retire the earlier login hook. dwm-session now applies scaling once after
    # taking its display lock. Do not load DWM settings in another desktop.
    xprofile = read('.xprofile')
    if any(f'# {edge} {name}' in xprofile
           for name in ('DWM-SCALE', 'DWM-XSCREENSAVER')
           for edge in ('BEGIN', 'END')):
        plan('.xprofile', block(block(xprofile), name='DWM-XSCREENSAVER'))

    template = (Path(__file__).parent / 'home/.local/share/applications/microsoft-teams-web.desktop').read_text()
    template = re.sub(r'^Exec=.*$', lambda _match: 'Exec=' + desktop_quote(Path(home) / '.local/bin/teams-web'), template, flags=re.M)
    plan('.local/share/applications/microsoft-teams-web.desktop', template, 0o644)
