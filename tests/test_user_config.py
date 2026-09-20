#!/usr/bin/env python3
"""User migration tests: temporary homes only; no applications or daemons run."""
import configparser
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
PAYLOAD = ROOT / 'payload'
spec = importlib.util.spec_from_file_location('apply_user', PAYLOAD / 'apply-user.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class UserConfigTests(unittest.TestCase):
    def setUp(self):
        self.sandbox = tempfile.TemporaryDirectory(prefix='dwm-config-test-')
        self.addCleanup(self.sandbox.cleanup)
        self.base = Path(self.sandbox.name)
        self.home = self.base / 'home'
        self.home.mkdir()
        self.backup = self.base / 'backup'

    def put(self, relative, data, mode=0o644):
        path = self.home / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(data, bytes):
            path.write_bytes(data)
        else:
            path.write_text(data)
        path.chmod(mode)
        return path

    def run_apply(self, backup=None):
        # Configuration migration itself must never spawn desktop services.
        with patch('subprocess.Popen', side_effect=AssertionError('unexpected subprocess')):
            module.apply(PAYLOAD, self.home, backup or self.backup)

    def text(self, relative):
        return (self.home / relative).read_text()

    def config(self, relative):
        return module.ini(self.text(relative))

    def test_preflight_creates_no_files(self):
        self.put('.zshrc', 'export KEEP=1\n')
        count = module.apply(PAYLOAD, self.home, check=True)
        self.assertGreater(count, 10)
        self.assertEqual([p.name for p in self.home.iterdir()], ['.zshrc'])
        self.assertFalse(self.backup.exists())
        self.assertEqual(self.text('.zshrc'), 'export KEEP=1\n')

    def test_fresh_install_has_shell_font_pinyin_and_unique_manifest(self):
        self.run_apply()
        self.assertEqual(self.text('.zshrc').count('# BEGIN DWM-SHELL'), 1)
        self.assertIn('background_opacity 0.85', self.text('.config/kitty/kitty.conf'))
        self.assertIn('JetBrainsMono Nerd Font Mono', self.text('.config/kitty/kitty.conf'))
        self.assertIn('alias ls=\'eza --icons\'', self.text('.config/dwm-shell/zshrc'))
        self.assertIn('alias cat=\'bat\'', self.text('.config/dwm-shell/zshrc'))
        self.assertIn('GLFW_IM_MODULE=ibus', self.text('.config/fcitx5/dwm-env.sh'))
        self.assertTrue(os.access(self.home / '.local/bin/bat', os.X_OK))
        profile = self.config('.config/fcitx5/profile')
        self.assertEqual(profile['Groups/0']['DefaultIM'], 'pinyin')
        self.assertEqual(profile['Groups/0/Items/0']['Name'], 'keyboard-us')
        self.assertEqual(profile['Groups/0/Items/1']['Name'], 'pinyin')
        config = self.config('.config/fcitx5/config')
        self.assertEqual(dict(config['Hotkey/TriggerKeys']), {'0': 'Control+space'})
        self.assertEqual(dict(config['Hotkey/EnumerateGroupForwardKeys']), {})
        self.assertIn('CloudPinyinEnabled=False', self.text('.config/fcitx5/conf/pinyin.conf'))
        self.assertFalse((self.home / '.local/share/fcitx5').exists())
        entries = (self.backup / 'user-files.txt').read_text().splitlines()
        self.assertEqual(len(entries), len(set(entries)))
        for item in entries:
            self.assertFalse(any(other.startswith(item + '/') for other in entries))
        self.assertIn('.xinputrc', entries)
        self.assertIn('.terminfo', entries)
        self.assertIn('.local/src/larbs-ubuntu', entries)
        self.assertFalse((self.backup / 'home/.zshrc').exists())

    def test_existing_personal_settings_and_dictionaries_survive(self):
        original = "# personal shell\nexport TEST_PERSONAL=keep\nalias mine='printf own'\n"
        self.put('.zshrc', original, 0o600)
        self.put('.profile', '# personal profile\nexport TEST_PROFILE=keep\n')
        self.put('.zshrc.local', 'alias local_override=true\n')
        dictionary = self.put('.local/share/fcitx5/pinyin/user.dict', b'\x00PERSONAL DICTIONARY\xff')
        history = self.put('.local/share/fcitx5/pinyin/user.history', b'private-learning-state')
        config_dict = self.put('.config/fcitx5/pinyin/user.dict', b'legacy-private-dictionary')
        self.put('.config/fcitx5/conf/pinyin.conf', 'CloudPinyinEnabled=True\nPageSize=5\n\n[Fuzzy]\nCustom=True\nPrediction=section-value\n')
        self.put('.config/fcitx5/conf/classicui.conf', 'Font=Personal Font 16\nTheme=custom\n')
        self.run_apply()
        self.assertTrue(self.text('.zshrc').startswith(original))
        self.assertEqual((self.home / '.zshrc').stat().st_mode & 0o777, 0o600)
        self.assertEqual((self.backup / 'home/.zshrc').read_text(), original)
        self.assertIn('TEST_PROFILE=keep', self.text('.profile'))
        self.assertEqual(self.text('.zshrc.local'), 'alias local_override=true\n')
        self.assertEqual(dictionary.read_bytes(), b'\x00PERSONAL DICTIONARY\xff')
        self.assertEqual(history.read_bytes(), b'private-learning-state')
        self.assertEqual(config_dict.read_bytes(), b'legacy-private-dictionary')
        self.assertIn('CloudPinyinEnabled=True', self.text('.config/fcitx5/conf/pinyin.conf'))
        self.assertIn('[Fuzzy]\nCustom=True\nPrediction=section-value', self.text('.config/fcitx5/conf/pinyin.conf'))
        self.assertIn('PageSize=7', self.text('.config/fcitx5/conf/pinyin.conf').split('[Fuzzy]')[0])
        self.assertIn('Font=Personal Font 16', self.text('.config/fcitx5/conf/classicui.conf'))
        self.assertIn('Theme=custom', self.text('.config/fcitx5/conf/classicui.conf'))
        self.assertNotIn('user.dict', (self.backup / 'user-files.txt').read_text())

    def test_pinyin_added_to_active_group_and_super_space_conflicts_removed(self):
        self.put('.config/fcitx5/profile', '''[Groups/0]
Name=Other
Default Layout=us
DefaultIM=pinyin
[Groups/0/Items/0]
Name=pinyin
Layout=
[Groups/3]
Name=Work
Default Layout=de
DefaultIM=anthy
[Groups/3/Items/0]
Name=keyboard-de
Layout=
[Groups/3/Items/1]
Name=anthy
Layout=
[GroupOrder]
0=Work
1=Other
''')
        self.put('.config/fcitx5/config', '''[Hotkey/TriggerKeys]
0=Super+space
1=Control+space
2=Control+Alt+space
[Hotkey/AltTriggerKeys]
0=Shift_R
[Hotkey/EnumerateGroupForwardKeys]
0=Super+space
1=Control+Alt+F6
[Hotkey/EnumerateGroupBackwardKeys]
0=Shift+Super+space
[Behavior]
ActiveByDefault=True
PersonalOption=keep
''')
        self.run_apply()
        profile = self.config('.config/fcitx5/profile')
        self.assertEqual(profile['Groups/3']['Default Layout'], 'de')
        self.assertEqual(profile['Groups/3/Items/1']['Name'], 'anthy')
        self.assertEqual(profile['Groups/3/Items/2']['Name'], 'pinyin')
        self.assertEqual(profile['Groups/0/Items/0']['Name'], 'pinyin')
        self.assertEqual(profile['GroupOrder']['1'], 'Other')
        config = self.config('.config/fcitx5/config')
        self.assertEqual(dict(config['Hotkey/TriggerKeys']), {'0': 'Control+space', '1': 'Control+Alt+space'})
        self.assertEqual(dict(config['Hotkey/EnumerateGroupForwardKeys']), {'0': 'Control+Alt+F6'})
        self.assertEqual(dict(config['Hotkey/EnumerateGroupBackwardKeys']), {})
        self.assertEqual(config['Hotkey/AltTriggerKeys']['0'], 'Shift_R')
        self.assertEqual(config['Behavior']['ActiveByDefault'], 'True')
        self.assertEqual(config['Behavior']['PersonalOption'], 'keep')

    def test_repeat_is_idempotent_and_keeps_first_backup(self):
        original = 'export PRIVATE_SETTING=original\n'
        self.put('.zshrc', original)
        self.put('.xinputrc', 'original-input-config\n')
        self.put('.terminfo/x/original', b'original-terminfo')
        self.put('.local/src/larbs-ubuntu/old-source.c', 'original source\n')
        self.run_apply()
        first_manifest = (self.backup / 'user-files.txt').read_text()
        first_files = {rel: self.text(rel) for rel in ('.zshrc', '.profile', '.config/fcitx5/profile', '.config/fcitx5/config', '.config/fcitx5/conf/pinyin.conf')}
        self.run_apply()
        self.assertEqual((self.backup / 'user-files.txt').read_text(), first_manifest)
        for rel, value in first_files.items():
            self.assertEqual(self.text(rel), value)
        self.assertEqual((self.backup / 'home/.zshrc').read_text(), original)
        self.assertEqual((self.backup / 'home/.xinputrc').read_text(), 'original-input-config\n')
        self.assertEqual((self.backup / 'home/.terminfo/x/original').read_bytes(), b'original-terminfo')
        self.assertEqual((self.backup / 'home/.local/src/larbs-ubuntu/old-source.c').read_text(), 'original source\n')
        second_backup = self.base / 'second-backup'
        self.run_apply(second_backup)
        self.assertEqual((second_backup / 'home/.zshrc').read_text(), first_files['.zshrc'])

    def test_legacy_generated_zsh_migrates_without_personal_tail(self):
        personal = "\n# Personal tail is not part of the managed template\nalias private_command='true'\n"
        old = module.LEGACY_ZSHRC + personal
        self.put('.zshrc', old)
        self.run_apply()
        self.assertTrue(self.text('.zshrc').startswith(personal))
        self.assertNotIn('plugins=(git zsh-autosuggestions)', self.text('.zshrc'))
        self.assertEqual(self.text('.zshrc').count('# BEGIN DWM-SHELL'), 1)
        self.assertEqual((self.backup / 'home/.zshrc').read_text(), old)

    def test_symlink_leaf_is_backed_up_without_modifying_external_target(self):
        outside = self.base / 'personal-zshrc'
        outside.write_text('export OUTSIDE=keep\n')
        (self.home / '.zshrc').symlink_to(outside)
        input_target = self.base / 'external-xinputrc'
        input_target.write_text('keep-input-target\n')
        (self.home / '.xinputrc').symlink_to(input_target)
        self.run_apply()
        self.assertEqual(outside.read_text(), 'export OUTSIDE=keep\n')
        self.assertFalse((self.home / '.zshrc').is_symlink())
        self.assertEqual(os.readlink(self.backup / 'home/.zshrc'), str(outside))
        self.assertFalse((self.home / '.xinputrc').is_symlink())
        self.assertEqual(input_target.read_text(), 'keep-input-target\n')
        self.assertEqual(os.readlink(self.backup / 'home/.xinputrc'), str(input_target))

    def test_symlink_ancestor_and_terminfo_rejected_before_any_changes(self):
        outside = self.base / 'outside'
        outside.mkdir()
        (self.home / '.config').symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'symlink ancestor'):
            self.run_apply()
        self.assertEqual(list(outside.iterdir()), [])
        self.assertFalse((self.home / '.zshrc').exists())
        (self.home / '.config').unlink()
        (self.home / '.terminfo').symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, '.terminfo symlink'):
            self.run_apply()
        self.assertFalse((self.home / '.zshrc').exists())

    def test_incomplete_markers_fail_without_overwriting(self):
        original = '# BEGIN DWM-SHELL\nunfinished personal edit\n'
        self.put('.zshrc', original)
        with self.assertRaisesRegex(ValueError, 'Incomplete managed block'):
            self.run_apply()
        self.assertEqual(self.text('.zshrc'), original)
        self.assertFalse((self.home / '.config').exists())


if __name__ == '__main__':
    unittest.main()
