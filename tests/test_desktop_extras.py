#!/usr/bin/env python3
"""Portable scaling/launcher checks in temporary homes; no X11 or real apps."""
import importlib.machinery
import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
PAYLOAD = ROOT / 'payload'


def load(name, path):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


extras = load('desktop_extras', PAYLOAD / 'desktop-extras.py')
scaling = load('dwm_scale_apply', PAYLOAD / 'home/.local/bin/dwm-scale-apply')


class DesktopExtrasTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='dwm-extras-')
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name) / 'new user'
        self.home.mkdir()

    def plan(self, old=None, percent=150):
        old = old or {}
        pending = {}
        def write(name, text, mode=None):
            pending[name] = text
        with patch('subprocess.Popen', side_effect=AssertionError('must not launch a daemon')):
            extras.configure(lambda name: old.get(name, ''), write, self.home, percent)
        return pending

    def test_default_and_alternative_scales_preserve_shared_settings(self):
        original = {
            '.Xresources': '! personal\nXTerm*foreground: white\nXft.dpi: 96\n',
            '.config/xsettingsd/xsettingsd.conf': 'Net/ThemeName "Adwaita"\nXft/DPI 98304\n',
            '.config/gtk-3.0/settings.ini': '[Settings]\ngtk-theme-name=MyTheme\n[Extra]\nkeep=yes\n',
            '.gtkrc-2.0': 'gtk-theme-name="MyTheme"\ngtk-xft-dpi=98304\n',
            '.xprofile': 'export PERSONAL=keep\n# BEGIN DWM-SCALE\nold-scale\n# END DWM-SCALE\n'
                         '# BEGIN DWM-XSCREENSAVER\nold-saver\n# END DWM-XSCREENSAVER\n',
        }
        result = self.plan(original)
        self.assertIn('Xft.dpi: 144', result['.Xresources'])
        self.assertIn('Xcursor.size: 36', result['.Xresources'])
        self.assertIn('XTerm*foreground: white', result['.Xresources'])
        self.assertIn('Xft/DPI 147456', result['.config/xsettingsd/xsettingsd.conf'])
        self.assertIn('Net/ThemeName "Adwaita"', result['.config/xsettingsd/xsettingsd.conf'])
        self.assertIn('gtk-theme-name=MyTheme', result['.config/gtk-3.0/settings.ini'])
        self.assertIn('keep=yes', result['.config/gtk-3.0/settings.ini'])
        self.assertIn('gtk-theme-name="MyTheme"', result['.gtkrc-2.0'])
        self.assertEqual(result['.xprofile'], 'export PERSONAL=keep\n')
        self.assertIn('dpi: 144;', result['.config/rofi/config.rasi'])
        repeated = self.plan(result)
        for name in result.keys() - {'.xprofile'}:
            self.assertEqual(result[name], repeated[name], name)
        alternative = self.plan(result, 125)
        self.assertIn('Xft.dpi: 120', alternative['.Xresources'])
        self.assertNotIn('Xft.dpi: 144', alternative['.Xresources'])
        self.assertIn('Xft/DPI 122880', alternative['.config/xsettingsd/xsettingsd.conf'])
        self.assertIn('dpi: 120;', alternative['.config/rofi/config.rasi'])
        for name, content in alternative.items():
            self.assertNotIn(str(Path.home()), content, name)
            self.assertNotIn('3840x2160', content, name)

    def test_retire_each_legacy_login_hook_independently(self):
        for name in ('DWM-SCALE', 'DWM-XSCREENSAVER'):
            with self.subTest(name=name):
                previous = f'export PERSONAL=keep\n# BEGIN {name}\nold-command\n# END {name}\n'
                result = self.plan({'.xprofile': previous})
                self.assertEqual(result['.xprofile'], 'export PERSONAL=keep\n')
                self.assertNotIn('.xprofile', self.plan(result))
                with self.assertRaisesRegex(ValueError, 'Incomplete'):
                    self.plan({'.xprofile': f'# BEGIN {name}\nold-command\n'})

    def test_reject_bad_scale_and_broken_managed_block(self):
        for value in ('150', 150.0, True, 0, 151):
            with self.assertRaises(ValueError):
                self.plan(percent=value)
        with self.assertRaisesRegex(ValueError, 'Incomplete'):
            self.plan({'.Xresources': '! BEGIN DWM-SCALE\nXft.dpi: 100\n'})

    def test_launcher_path_uses_target_home_and_exec_escaping(self):
        self.home = self.home / 'a $dollar %percent "quote" \\slash'
        entry = self.plan()['.local/share/applications/microsoft-teams-web.desktop']
        self.assertIn('Icon=microsoft-teams-web', entry)
        self.assertIn('%%percent', entry)
        self.assertIn('\\\\$dollar', entry)
        self.assertIn('\\\\"quote', entry)
        self.assertIn('\\\\\\\\slash', entry)
        if Path('/usr/bin/desktop-file-validate').exists():
            candidate = Path(self.temp.name) / 'teams.desktop'
            candidate.write_text(entry)
            subprocess.run(['/usr/bin/desktop-file-validate', str(candidate)], check=True,
                           capture_output=True, text=True)

    def test_apply_user_integration_backs_up_and_repeats_without_starting_apps(self):
        apply_user = load('extras_apply_user_test', PAYLOAD / 'apply-user.py')
        original = '! personal settings\nXTerm*foreground: white\nXft.dpi: 96\n'
        (self.home / '.Xresources').write_text(original)
        old_xprofile = 'export KEEP=1\n# BEGIN DWM-SCALE\nold-scaler\n# END DWM-SCALE\n' \
                       '# BEGIN DWM-XSCREENSAVER\nold-saver\n# END DWM-XSCREENSAVER\n'
        (self.home / '.xprofile').write_text(old_xprofile)
        personal = self.home / '.local/share/fcitx5/pinyin/user.dict'
        personal.parent.mkdir(parents=True)
        personal.write_bytes(b'private-dictionary-not-for-distribution')
        backup = Path(self.temp.name) / 'backup'
        with patch.dict(os.environ, {'DWM_SETUP_SCALE': '125'}), \
                patch('subprocess.Popen', side_effect=AssertionError('unexpected app launch')):
            apply_user.apply(PAYLOAD, self.home, check=True)
            self.assertEqual((self.home / '.Xresources').read_text(), original)
            self.assertFalse(backup.exists())
            apply_user.apply(PAYLOAD, self.home, backup)
            first_manifest = (backup / 'user-files.txt').read_text()
            apply_user.apply(PAYLOAD, self.home, backup)
        self.assertIn('Xft.dpi: 120', (self.home / '.Xresources').read_text())
        self.assertEqual((backup / 'home/.Xresources').read_text(), original)
        self.assertEqual((backup / 'home/.xprofile').read_text(), old_xprofile)
        self.assertEqual((self.home / '.xprofile').read_text(), 'export KEEP=1\n')
        self.assertEqual((backup / 'user-files.txt').read_text(), first_manifest)
        self.assertEqual(personal.read_bytes(), b'private-dictionary-not-for-distribution')
        self.assertNotIn('user.dict', first_manifest)
        self.assertTrue(os.access(self.home / '.local/bin/teams-web', os.X_OK))
        self.assertTrue(os.access(self.home / '.local/bin/dwm-scale-apply', os.X_OK))

    def fake_browser(self, name):
        binary = self.home / 'bin' / name
        binary.parent.mkdir(exist_ok=True)
        binary.write_text('#!/bin/sh\nprintf "%s\\n" "$0" "$@"\n')
        binary.chmod(0o755)
        return binary

    def run_teams(self):
        return subprocess.run(['/bin/sh', str(PAYLOAD / 'home/.local/bin/teams-web')],
                              env={'PATH': str(self.home / 'bin'), 'HOME': str(self.home)},
                              capture_output=True, text=True)

    def test_teams_runtime_browser_detection_and_fallback(self):
        chrome = self.fake_browser('google-chrome')
        self.fake_browser('firefox')
        result = self.run_teams()
        self.assertEqual(result.returncode, 0)
        self.assertIn('--app=https://teams.microsoft.com/', result.stdout)
        chrome.unlink()
        result = self.run_teams()
        self.assertEqual(result.returncode, 0)
        self.assertIn('/firefox\nhttps://teams.microsoft.com/', result.stdout)
        self.assertIn('default browser instead', result.stderr)
        (self.home / 'bin/firefox').unlink()
        self.fake_browser('xdg-open')
        self.assertEqual(self.run_teams().returncode, 0)
        (self.home / 'bin/xdg-open').unlink()
        self.assertEqual(self.run_teams().returncode, 127)

    def test_scaling_leaves_other_settings_manager_running(self):
        cfg = self.home / '.config/xsettingsd/xsettingsd.conf'
        cfg.parent.mkdir(parents=True)
        cfg.write_text('Xft/DPI 147456\n')
        selection = Mock(screen=0)
        selection.owner.return_value = 77
        with patch.dict(os.environ, {'DISPLAY': ':99', 'XDG_SESSION_TYPE': 'x11'}), \
                patch.object(scaling.Path, 'home', return_value=self.home), \
                patch.object(scaling.shutil, 'which', return_value='/usr/bin/xsettingsd'), \
                patch.object(scaling, 'Selection', return_value=selection), \
                patch.object(scaling.subprocess, 'Popen') as spawn, \
                patch.object(scaling.os, 'kill') as kill:
            scaling.apply_scaling()
        spawn.assert_not_called()
        kill.assert_not_called()
        selection.close.assert_called_once()

    def test_only_matching_user_command_and_display_can_receive_hup(self):
        proc = self.home / 'proc'
        process = proc / '123'
        process.mkdir(parents=True)
        pidfile = self.home / 'display.pid'
        pidfile.write_text('123\n')
        command = ['/usr/bin/xsettingsd', '-c', '/tmp/test-config', '-s', '0']
        (process / 'cmdline').write_bytes(b'\0'.join(argument.encode() for argument in command) + b'\0')
        (process / 'environ').write_bytes(b'DISPLAY=:99\0')
        self.assertEqual(scaling.owned_pid(pidfile, command, ':99', proc), 123)
        self.assertIsNone(scaling.owned_pid(pidfile, command, ':0', proc))
        self.assertIsNone(scaling.owned_pid(pidfile, ['/usr/bin/other'], ':99', proc))
        with patch.object(scaling.os, 'getuid', return_value=os.getuid() + 1):
            self.assertIsNone(scaling.owned_pid(pidfile, command, ':99', proc))


if __name__ == '__main__':
    unittest.main()
