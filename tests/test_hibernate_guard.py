from pathlib import Path
import contextlib
import importlib.util
from importlib.machinery import SourceFileLoader
import io
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace

HELPER = Path(__file__).resolve().parents[1] / 'payload/home/.local/bin/dwm-hibernate'
spec = importlib.util.spec_from_loader('dwm_hibernate_tested', SourceFileLoader('dwm_hibernate_tested', str(HELPER)))
h = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = h
spec.loader.exec_module(h)


def response(args, output='', code=0):
    return subprocess.CompletedProcess(args, code, output, '')


class GuardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.swap = self.root / 'swap.img'
        self.page = os.sysconf('SC_PAGESIZE')
        self.swap.write_bytes(b'\0' * (self.page * 2))
        self.config = {'swap_file': str(self.swap),
                       'root_uuid': '11111111-2222-3333-4444-555555555555',
                       'resume_offset': 123456, 'expected_bytes': self.page * 2,
                       'configured_kernel': 'fixture-kernel', 'backup': str(self.root/'backup')}
        (self.root/'config').write_text(json.dumps(self.config))
        (self.root/'cmdline').write_text('ro resume=UUID=' + self.config['root_uuid'] + ' resume_offset=123456 quiet')
        dev = self.root.stat().st_dev
        (self.root/'resume').write_text(f'{os.major(dev)}:{os.minor(dev)}\n')
        (self.root/'offset').write_text('123456\n')
        (self.root/'swaps').write_text('Filename Type Size Used Priority\n' + str(self.swap) + f' file {self.page//1024} 0 100\n')
        (self.root/'kernel-release').write_text('fixture-kernel\n')
        (self.root/'vmlinuz-fixture-kernel').touch()
        (self.root/'vmlinuz').symlink_to('vmlinuz-fixture-kernel')
        (self.root/'grub-defaults').write_text('GRUB_DEFAULT=0\n')
        (self.root/'grub.d').mkdir()
        self.paths = h.Paths(self.root/'config', self.root/'cmdline', self.root/'resume',
                             self.root/'offset', self.root/'swaps', self.root, self.root/'by-uuid',
                             self.root/'vmlinuz', self.root/'kernel-release',
                             self.root/'grub-defaults', self.root/'grub.d')
        self.runner = lambda args, **kwargs: response(args, 's "yes"\n')
        self.swap_uid = 0
        self.swap_mode = 0o600
        self.uuid_mode = stat.S_IFBLK
        self.uuid_device = dev
        self.uuid_exists = True

    def tearDown(self): self.temp.cleanup()
    def fake_stat(self, path):
        if Path(path) == self.paths.uuid_directory / self.config['root_uuid']:
            if not self.uuid_exists: raise FileNotFoundError(str(path))
            return SimpleNamespace(st_mode=self.uuid_mode, st_rdev=self.uuid_device)
        return os.stat(path)

    def fake_lstat(self, path):
        actual = os.lstat(path)
        return SimpleNamespace(st_uid=self.swap_uid, st_mode=stat.S_IFMT(actual.st_mode) | self.swap_mode,
                               st_ino=actual.st_ino, st_dev=actual.st_dev, st_size=actual.st_size)

    def report(self):
        return h.check_ready(self.paths, self.runner, stat_path=self.fake_stat, lstat_path=self.fake_lstat)

    def test_all_checks_pass_with_swap_header_page(self):
        self.assertTrue(self.report().ready)

    def test_new_default_kernel_requires_reboot_before_hibernation(self):
        (self.root/'vmlinuz').unlink()
        (self.root/'vmlinuz-new-kernel').touch()
        (self.root/'vmlinuz').symlink_to('vmlinuz-new-kernel')
        report = self.report()
        self.assertFalse(report.ready)
        self.assertTrue(report.reboot_required)
        self.assertEqual(report.facts['next_boot_kernel'], 'new-kernel')

    def test_missing_boot_kernel_fails_closed(self):
        (self.root/'vmlinuz-fixture-kernel').unlink()
        self.assertFalse(self.report().ready)

    def test_custom_grub_defaults_block_even_with_correct_kernel_link(self):
        for text in ('GRUB_DEFAULT=saved', 'GRUB_DEFAULT=1', 'GRUB_DEFAULT="old kernel"',
                     'GRUB_DEFAULT=$(touch /never-execute)', 'GRUB_SAVEDEFAULT=true'):
            with self.subTest(text=text):
                (self.root/'grub.d/custom.cfg').write_text(text + '\n')
                self.assertFalse(self.report().ready)
        (self.root/'grub.d/custom.cfg').write_text('#GRUB_DEFAULT=saved\nGRUB_DEFAULT="0"\nGRUB_SAVEDEFAULT=false\n')
        self.assertTrue(self.report().ready)

    def test_yes_capability_does_not_bypass_required_reboot(self):
        (self.root/'cmdline').write_text('ro quiet splash')
        (self.root/'resume').write_text('0:0')
        (self.root/'offset').write_text('0')
        result = self.report()
        self.assertFalse(result.ready)
        self.assertTrue(result.reboot_required)
        self.assertEqual(result.facts['can_hibernate'], 'yes')

    def test_wrong_or_duplicate_cmdline_rejected(self):
        with (self.root/'cmdline').open('a') as stream: stream.write(' resume_offset=123456')
        self.assertFalse(self.report().ready)

    def test_noresume_fails_closed_even_with_matching_resume_parameters(self):
        with (self.root/'cmdline').open('a') as stream: stream.write(' noresume')
        self.assertFalse(self.report().ready)

    def test_wrong_sysfs_device_rejected(self):
        (self.root/'resume').write_text('99:99')
        self.assertFalse(self.report().ready)

    def test_wrong_sysfs_offset_rejected(self):
        (self.root/'offset').write_text('123455')
        self.assertFalse(self.report().ready)

    def test_inactive_swap_rejected(self):
        (self.root/'swaps').write_text('Filename Type Size Used Priority\n/other.img file 200 0 1\n')
        self.assertFalse(self.report().ready)

    def test_truncated_swap_rejected(self):
        self.swap.write_bytes(b'\0' * self.page)
        self.assertFalse(self.report().ready)

    def test_non_root_swap_owner_rejected(self):
        self.swap_uid = 1000
        self.assertFalse(self.report().ready)

    def test_swap_permission_must_be_exactly_0600(self):
        self.swap_mode = 0o640
        self.assertFalse(self.report().ready)

    def test_optional_inode_matches_or_rejects_recreated_file(self):
        self.config['swap_inode'] = self.swap.stat().st_ino
        (self.root/'config').write_text(json.dumps(self.config))
        self.assertTrue(self.report().ready)
        self.config['swap_inode'] += 1
        (self.root/'config').write_text(json.dumps(self.config))
        self.assertFalse(self.report().ready)

    def test_uuid_must_resolve_to_root_block_device(self):
        self.uuid_device += 1
        self.assertFalse(self.report().ready)

    def test_uuid_non_block_device_rejected(self):
        self.uuid_mode = stat.S_IFREG
        self.assertFalse(self.report().ready)

    def test_missing_uuid_device_rejected(self):
        self.uuid_exists = False
        self.assertFalse(self.report().ready)

    def test_challenge_allowed_but_no_rejected(self):
        for ability, expected in [('challenge', True), ('no', False), ('na', False)]:
            self.runner = lambda args, **kwargs: response(args, 's "'+ability+'"\n')
            self.assertEqual(self.report().ready, expected)

    def test_proc_swaps_escaped_filename(self):
        row = h.parse_swaps('Filename Type Size Used Priority\n/a\\040b file 20 3 100\n')[0]
        self.assertEqual(row['path'], '/a b')


class ConfirmationTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.selection = h.CANCEL
        def fake(args, **kwargs):
            self.calls.append((args, kwargs))
            if args[0] == 'dmenu': return response(args, self.selection+'\n')
            return response(args)
        self.runner = fake

    def test_check_never_opens_menu_or_requests_hibernation(self):
        with contextlib.redirect_stdout(io.StringIO()):
            rc = h.main(['--check'], runner=self.runner, checker=lambda: h.CheckResult())
        self.assertEqual(rc, 0)
        self.assertEqual(self.calls, [])

    def test_cancel_is_first_and_never_requests_hibernation(self):
        rc = h.main([], runner=self.runner, checker=lambda: h.CheckResult())
        self.assertEqual(rc, 0)
        self.assertEqual(self.calls[0][1]['input'].splitlines()[0], h.CANCEL)
        self.assertEqual([call[0][0] for call in self.calls], ['dmenu'])

    def test_partial_confirmation_does_not_request_hibernation(self):
        self.selection = 'Hibernate'
        h.main([], runner=self.runner, checker=lambda: h.CheckResult())
        self.assertEqual([call[0][0] for call in self.calls], ['dmenu'])

    def test_exact_confirmation_invokes_only_mocked_systemctl(self):
        self.selection = h.CONFIRM
        rc = h.main([], runner=self.runner, checker=lambda: h.CheckResult())
        self.assertEqual(rc, 0)
        self.assertEqual(self.calls[-1][0], ['systemctl', 'hibernate'])

    def test_failed_second_check_cancels_after_confirmation(self):
        self.selection = h.CONFIRM
        reports = iter([h.CheckResult(), h.CheckResult(['Swap was deactivated'])])
        with contextlib.redirect_stderr(io.StringIO()):
            rc = h.main([], runner=self.runner, checker=lambda: next(reports))
        self.assertEqual(rc, 1)
        self.assertNotIn('systemctl', [call[0][0] for call in self.calls])

    def test_not_ready_never_opens_menu(self):
        with contextlib.redirect_stderr(io.StringIO()):
            rc = h.main([], runner=self.runner, checker=lambda: h.CheckResult(['Need reboot'], reboot_required=True))
        self.assertEqual(rc, 1)
        self.assertNotIn('dmenu', [call[0][0] for call in self.calls])
        self.assertNotIn('systemctl', [call[0][0] for call in self.calls])


if __name__ == '__main__': unittest.main()
