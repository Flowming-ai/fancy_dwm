"""Read-only API fakes and temporary-filesystem tests; no real session changes."""
from pathlib import Path
import configparser
import os
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SESSION = {'__name__': 'session_under_test'}
exec(compile((ROOT/'scripts/set-default-session.py').read_text(), 'session-helper', 'exec'), SESSION)
ROLLBACK = {'__name__': 'rollback_under_test'}
rollback_python = (ROOT/'scripts/rollback.sh').read_text().split("<<'PY'\n", 1)[1].rsplit('\nPY\n', 1)[0]
exec(compile(rollback_python, 'rollback-helper', 'exec'), ROLLBACK)


class SessionTests(unittest.TestCase):
    def test_modern_and_legacy_interfaces(self):
        self.assertEqual(SESSION['session_changes']({'SetSession', 'SetXSession', 'SetSessionType'}),
                         {'Session': ('SetSession', 'dwm'), 'SessionType': ('SetSessionType', 'x11')})
        self.assertEqual(SESSION['session_changes']({'SetXSession'}), {'XSession': ('SetXSession', 'dwm')})
        self.assertEqual(SESSION['session_changes'](set()), {})

    def test_unknown_ini_keys_and_sections_preserved(self):
        text = '[User]\nSession=ubuntu\nIcon=/tmp/100%icon\nCustomKey=keep me\n\n[Other]\nThing=retained\n'
        updated = SESSION['update_ini'](text, 'User', {'Session': 'dwm', 'SessionType': 'x11'})
        parser = configparser.ConfigParser(interpolation=None); parser.optionxform = str
        parser.read_string(updated)
        self.assertEqual(parser['User']['Icon'], '/tmp/100%icon')
        self.assertEqual(parser['User']['CustomKey'], 'keep me')
        self.assertEqual(parser['Other']['Thing'], 'retained')
        self.assertEqual(parser['User']['Session'], 'dwm')
        self.assertEqual(SESSION['update_ini'](updated, 'User', {'Session': 'dwm', 'SessionType': 'x11'}), updated)

    def test_api_snapshot_set_and_privilege_fallback(self):
        calls = []
        properties = {'Session': 'ubuntu', 'SessionType': 'wayland'}
        def fake(args, privileged=False, check=True):
            calls.append((list(args), privileged))
            if 'introspect' in args:
                out = '.SetSession method s -\n.SetSessionType method s -\n'
            elif 'get-property' in args:
                out = 's "' + properties[args[-1]] + '"\n'
            else:
                if not privileged:
                    return subprocess.CompletedProcess(args, 1, '', 'Access denied')
                properties[args[-3].removeprefix('Set')] = args[-1]
                out = ''
            return subprocess.CompletedProcess(args, 0, out, '')
        self.assertEqual(SESSION['methods'](1234, fake), {'SetSession', 'SetSessionType'})
        self.assertEqual(SESSION['get_property'](1234, 'Session', fake), 'ubuntu')
        SESSION['set_property'](1234, 'SetSession', 'dwm', fake)
        self.assertEqual(properties['Session'], 'dwm')
        self.assertTrue(calls[-1][1])
        self.assertIn('/org/freedesktop/Accounts/User1234', calls[-1][0])

    def test_fallback_requires_confirmed_inactive_service(self):
        for status, expected in [('inactive', True), ('active', False), ('', False)]:
            def fake(args, **kwargs): return subprocess.CompletedProcess(args, 3, status, '')
            self.assertEqual(SESSION['service_inactive'](fake), expected)

    def test_session_entry_is_validated_without_execution(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); executable = root/'dwm-session'
            executable.write_text('#!/bin/sh\nexit 99\n'); executable.chmod(0o755)
            desktop = root/'dwm.desktop'
            desktop.write_text(f'[Desktop Entry]\nType=Application\nExec={executable}\nTryExec={executable}\n')
            SESSION['validate_desktop'](desktop)
            desktop.write_text(desktop.read_text()+'Hidden=true\n')
            with self.assertRaises(RuntimeError): SESSION['validate_desktop'](desktop)

    def test_dmrc_backup_once_and_leaf_symlink_not_followed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); home = root/'home'; backup = root/'backup'
            home.mkdir(); backup.mkdir()
            outside = root/'outside'; outside.write_text('[Desktop]\nSession=old\n')
            (home/'.dmrc').symlink_to(outside)
            SESSION['backup_user_file'](home, backup, '.dmrc')
            self.assertTrue((backup/'home/.dmrc').is_symlink())
            SESSION['write_atomic'](home/'.dmrc', '[Desktop]\nSession=dwm\n')
            SESSION['backup_user_file'](home, backup, '.dmrc')
            self.assertEqual((backup/'user-files.txt').read_text(), '.dmrc\n')
            self.assertEqual(outside.read_text(), '[Desktop]\nSession=old\n')
            self.assertFalse((home/'.dmrc').is_symlink())


class RollbackTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.home = self.root/'home'; self.home.mkdir()
        self.backup = self.root/'backup'; self.backup.mkdir()

    def tearDown(self): self.temporary.cleanup()

    def plan(self, text):
        (self.backup/'user-files.txt').write_text(text)
        return ROLLBACK['build_plan'](self.backup, self.home, 'portableuser')

    def test_new_file_and_original_file_plan(self):
        (self.backup/'home').mkdir()
        (self.backup/'home/.profile').write_text('previous profile\n')
        plan = self.plan('.profile\n.new-config\n')
        self.assertEqual(len(plan), 2)
        self.assertTrue(ROLLBACK['exists'](plan[0][2]))
        self.assertFalse(ROLLBACK['exists'](plan[1][2]))

    def test_traversal_and_overlaps_refused(self):
        for text in ('../outside\n', '/etc/passwd\n', '.\n', '.config\n.config/settings\n'):
            with self.assertRaises(RuntimeError): self.plan(text)

    def test_target_ancestor_symlink_refused(self):
        outside = self.root/'outside'; outside.mkdir()
        (self.home/'.config').symlink_to(outside, target_is_directory=True)
        with self.assertRaises(RuntimeError): self.plan('.config/settings\n')
        self.assertEqual(list(outside.iterdir()), [])

    def test_backup_ancestor_symlink_refused(self):
        outside = self.root/'outside'; outside.mkdir()
        (self.backup/'home').mkdir()
        (self.backup/'home/.config').symlink_to(outside, target_is_directory=True)
        with self.assertRaises(RuntimeError): self.plan('.config/settings\n')

    def test_restore_leaf_symlink_preserves_external_target(self):
        original = self.root/'original'; original.write_text('saved value\n')
        outside = self.root/'outside'; outside.write_text('leave untouched\n')
        target = self.home/'config'; target.symlink_to(outside)
        ROLLBACK['restore_user'](target, original)
        self.assertEqual(outside.read_text(), 'leave untouched\n')
        self.assertEqual(target.read_text(), 'saved value\n')
        self.assertFalse(target.is_symlink())

    def test_restore_directory_copies_nested_links_without_recursing(self):
        outside = self.root/'outside'; outside.mkdir(); (outside/'precious').write_text('kept')
        original = self.root/'original'; original.mkdir()
        (original/'link').symlink_to(outside, target_is_directory=True)
        (original/'config').write_text('saved')
        target = self.home/'config'; target.mkdir()
        (target/'link').symlink_to(outside, target_is_directory=True)
        (target/'new').write_text('new')
        ROLLBACK['restore_user'](target, original)
        self.assertEqual((outside/'precious').read_text(), 'kept')
        self.assertTrue((target/'link').is_symlink())
        self.assertEqual((target/'config').read_text(), 'saved')
        self.assertFalse((target/'new').exists())

    def test_system_restore_allowlist(self):
        self.assertTrue(ROLLBACK['allowed_system'](Path('/usr/local/bin/dwm'), 'portableuser'))
        self.assertTrue(ROLLBACK['allowed_system'](Path('/var/lib/AccountsService/users/portableuser'), 'portableuser'))
        for path in ('/etc/passwd', '/usr/local/bin/../passwd', '/var/lib/AccountsService/users/someoneelse'):
            self.assertFalse(ROLLBACK['allowed_system'](Path(path), 'portableuser'))

    def test_session_file_is_in_preview_plan_without_api_lookup(self):
        state = {'account_file': '/var/lib/AccountsService/users/portableuser',
                 'account_file_existed': False}
        plan = []
        ROLLBACK['append_session_file'](plan, state, self.backup)
        self.assertEqual(len(plan), 1)
        self.assertEqual(str(plan[0][1]), state['account_file'])
        self.assertFalse(ROLLBACK['exists'](plan[0][2]))
        (self.backup/'session').mkdir()
        (self.backup/'session/accounts-user').write_text('[User]\nSession=ubuntu\n')
        state['account_file_existed'] = True
        ROLLBACK['append_session_file'](plan, state, self.backup)
        self.assertEqual(len(plan), 1)
        self.assertTrue(ROLLBACK['exists'](plan[0][2]))


if __name__ == '__main__': unittest.main()
