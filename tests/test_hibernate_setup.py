"""Portable hibernation fixtures only: no real boot/device writes or sleep."""
import contextlib
import importlib.util
import io
from pathlib import Path
import stat
import struct
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


h = load('hibernate_setup_tested', ROOT / 'scripts/hibernate/configure.py')
r = load('hibernate_rollback_tested', ROOT / 'scripts/hibernate/rollback.py')
UUID = '11111111-2222-3333-4444-555555555555'


class PortablePlanTests(unittest.TestCase):
    def test_memory_size_uses_headroom_not_this_machine_ram(self):
        self.assertEqual(h.swap_bytes(30 * h.GIB), 34 * h.GIB)
        self.assertEqual(h.swap_bytes(128 * h.GIB), 141 * h.GIB)
        self.assertEqual(h.swap_bytes(30 * h.GIB, 40), 40 * h.GIB)
        with self.assertRaises(RuntimeError): h.swap_bytes(30 * h.GIB, 32)

    def test_actual_wrapper_selects_generator(self):
        self.assertEqual(h.detect_backend('# initramfs-tools adapted for dracut'), 'dracut')
        self.assertEqual(h.detect_backend('# initramfs-tools\nmkinitramfs -o file'), 'initramfs-tools')
        with self.assertRaises(RuntimeError): h.detect_backend('# unknown tool')

    def test_luks_lvm_raid_and_loop_ancestors_are_refused(self):
        h.assert_plain_storage({'blockdevices': [{'type': 'part', 'children': [{'type': 'disk'}]}]})
        for kind in ('crypt', 'lvm', 'raid1', 'loop', None):
            with self.subTest(kind=kind), self.assertRaises(RuntimeError):
                h.assert_plain_storage({'blockdevices': [{'type': 'part', 'children': [{'type': kind}]}]})

    def test_fiemap_uses_page_size_and_rejects_unsafe_extents(self):
        def buffer(physical=8 * 65536, flags=1, logical=0, length=65536):
            return (struct.pack('<QQIIII', 0, 65536, 1, 1, 1, 0) +
                    struct.pack('<QQQQQIIII', logical, physical, length, 0, 0, flags, 0, 0, 0))
        self.assertEqual(h.fiemap_offset(buffer(), 65536), 8)
        for kwargs in ({'physical': 3}, {'flags': 0x800}, {'flags': 0x2000}, {'logical': 65536}, {'length': 4096}):
            with self.subTest(kwargs=kwargs), self.assertRaises(RuntimeError):
                h.fiemap_offset(buffer(**kwargs), 65536)

    def test_filefrag_extent_must_start_at_logical_zero(self):
        self.assertEqual(h.filefrag_offset(' 0: 0.. 8191: 133120.. 141311: 8192: last,eof'), 133120)
        for text in (' 0: 1.. 99: 120.. 218: 99:', 'garbage', ' 1: 0.. 99: 120.. 218: 100:'):
            with self.assertRaises(RuntimeError): h.filefrag_offset(text)

    def test_grub_checks_all_kernels_but_not_memtest(self):
        good = f' linux /boot/vmlinuz-6.8.0 root=UUID={UUID} resume=UUID={UUID} resume_offset=123\n'
        h.validate_grub(good + 'linux /boot/memtest86+x64.bin\n', UUID, 123)
        for extra in (' noresume', ' resume_offset=123', ' resume=UUID=wrong'):
            with self.assertRaises(RuntimeError): h.validate_grub(good.strip() + extra, UUID, 123)
        with self.assertRaises(RuntimeError): h.validate_grub('linux /boot/memtest86+x64.bin', UUID, 123)

    def test_custom_grub_default_refused_without_executing_shell(self):
        h.validate_grub_defaults('#GRUB_DEFAULT=saved\nGRUB_DEFAULT="0" # normal Ubuntu\nGRUB_SAVEDEFAULT=false\n')
        for text in ('GRUB_DEFAULT=saved', 'GRUB_DEFAULT=1', 'GRUB_DEFAULT="Advanced options>old kernel"',
                     'GRUB_DEFAULT=$(touch /never-execute)', 'export GRUB_SAVEDEFAULT=true'):
            with self.subTest(text=text), self.assertRaises(RuntimeError):
                h.validate_grub_defaults(text)

    def test_effective_sleep_config_includes_vendor_overrides(self):
        text = '# HibernateMode=platform shutdown\n[Sleep]\nHibernateMode=platform\n# /usr/lib/systemd/sleep.conf.d/90-vendor.conf\n[Sleep]\nHibernateMode=shutdown\n'
        self.assertEqual(h.sleep_assignments(text), ['platform', 'shutdown'])
        self.assertEqual(h.sleep_assignments('[Other]\nHibernateMode=shutdown\n[Sleep]\n#HibernateMode=platform\n'), [])

    def test_user_permission_is_scoped_and_inhibitors_not_bypassed(self):
        text = h.policy_text('portable-user')
        self.assertIn('subject.local && subject.active', text)
        self.assertIn('subject.user == "portable-user"', text)
        self.assertNotIn('ignore-inhibit', text)

    def test_inspection_permission_error_is_a_report_not_traceback(self):
        with patch.object(Path, 'read_text', side_effect=PermissionError('fixture denied')):
            report = h.inspect_host(SimpleNamespace())
        self.assertFalse(report['eligible'])
        self.assertEqual(report['problems'], ['fixture denied'])

    def test_unreadable_policy_leaf_is_deferred_only_for_ordinary_user(self):
        def metadata(path):
            if path == h.POLICY:
                raise PermissionError(13, 'Permission denied', str(path))
            return SimpleNamespace(st_uid=0, st_mode=stat.S_IFDIR | 0o750)
        with patch.object(Path, 'lstat', autospec=True, side_effect=metadata), \
             patch.object(h.os, 'geteuid', return_value=1000):
            self.assertFalse(h.safe_path(h.POLICY, defer_unreadable_leaf=True))
            with self.assertRaises(PermissionError): h.safe_path(h.POLICY)
        with patch.object(Path, 'lstat', autospec=True, side_effect=metadata), \
             patch.object(h.os, 'geteuid', return_value=0):
            with self.assertRaises(PermissionError):
                h.safe_path(h.POLICY, defer_unreadable_leaf=True)

    def test_deferred_leaf_never_skips_ancestor_safety_checks(self):
        def metadata(path):
            if path == h.POLICY.parent:
                return SimpleNamespace(st_uid=0, st_mode=stat.S_IFLNK | 0o777)
            return SimpleNamespace(st_uid=0, st_mode=stat.S_IFDIR | 0o755)
        with patch.object(Path, 'lstat', autospec=True, side_effect=metadata), \
             patch.object(h.os, 'geteuid', return_value=1000):
            with self.assertRaisesRegex(RuntimeError, 'symlink'):
                h.safe_path(h.POLICY, defer_unreadable_leaf=True)

    def test_conflict_scan_defers_only_previously_checked_unreadable_leaf(self):
        def metadata(path):
            if path == h.POLICY:
                raise PermissionError(13, 'Permission denied', str(path))
            raise FileNotFoundError(str(path))
        with patch.object(Path, 'lstat', autospec=True, side_effect=metadata), \
             patch.object(Path, 'glob', return_value=[]), patch.object(Path, 'is_file', return_value=False), \
             patch.object(h, 'run', return_value=''):
            h.existing_conflicts({h.POLICY})
            with self.assertRaises(PermissionError): h.existing_conflicts()

    def test_check_even_as_root_never_applies_or_creates_tempfiles(self):
        report = dict(eligible=True, problems=[], warnings=[], facts={})
        with patch.object(h, 'inspect_host', return_value=report), patch.object(h.os, 'geteuid', return_value=0), \
             patch.object(h, 'apply') as apply, patch.object(h.tempfile, 'mkstemp') as temporary, \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(h.main(['--check', '--json']), 0)
        apply.assert_not_called(); temporary.assert_not_called()

    def test_nonewprivs_refused_before_lock_or_other_writes(self):
        report = dict(eligible=True, problems=[], warnings=[], facts={})
        with patch.object(h, 'inspect_host', return_value=report), patch.object(h.os, 'geteuid', return_value=0), \
             patch.object(Path, 'read_text', return_value='NoNewPrivs:\t1\n'), patch('builtins.open') as opened, \
             contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(RuntimeError, 'NoNewPrivs'):
                h.main(['--apply', '--user', 'fixture'])
        opened.assert_not_called()


class InitrdValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.config = dict(root_uuid=UUID, resume_offset=123)

    def tearDown(self): self.temp.cleanup()

    def write(self, name, text='', executable=False):
        path = self.root / 'main' / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        if executable: path.chmod(0o755)
        return path

    def dracut(self):
        self.write('usr/lib/systemd/system-generators/systemd-hibernate-resume-generator', 'binary', True)
        self.write('usr/lib/systemd/systemd-hibernate-resume', 'binary', True)
        self.write('usr/lib/systemd/system/systemd-hibernate-resume.service', '[Unit]\nBefore=local-fs-pre.target\n')
        self.write('etc/initrd-release')

    def test_dracut_full_restore_path_and_conflicting_offset(self):
        self.dracut()
        h.validate_image_tree(self.root, 'dracut', self.config)
        self.write('etc/cmdline.d/20-resume.conf', 'resume_offset=124')
        with self.assertRaises(RuntimeError): h.validate_image_tree(self.root, 'dracut', self.config)

    def test_dracut_must_restore_before_mount(self):
        self.dracut()
        self.write('usr/lib/systemd/system/systemd-hibernate-resume.service', 'After=local-fs.target\n')
        with self.assertRaises(RuntimeError): h.validate_image_tree(self.root, 'dracut', self.config)

    def test_initramfs_tools_klibc_resume_and_config(self):
        self.write('scripts/local-premount/resume', '#!/bin/sh\n/bin/resume "$resume" "$resume_offset"\n', True)
        self.write('bin/resume', 'binary', True)
        self.write('conf/conf.d/zz-dwm-hibernate', f'RESUME=UUID={UUID}\nresume_offset=123\n')
        h.validate_image_tree(self.root, 'initramfs-tools', self.config)
        (self.root/'main/bin/resume').unlink()
        with self.assertRaises(RuntimeError): h.validate_image_tree(self.root, 'initramfs-tools', self.config)

    def test_initramfs_tools_direct_sysfs_implementation(self):
        self.write('scripts/local-premount/resume', '#!/bin/sh\n# use resume_offset\necho "$MAJMIN" > /sys/power/resume\n', True)
        self.write('usr/sbin/blkid', 'binary', True)
        self.write('conf/conf.d/zz-dwm-hibernate', f'RESUME=UUID={UUID}\nresume_offset=123\n')
        h.validate_image_tree(self.root, 'initramfs-tools', self.config)
        self.write('conf/conf.d/zz-dwm-hibernate', f'RESUME=UUID={UUID}\nresume_offset=124\n')
        with self.assertRaises(RuntimeError): h.validate_image_tree(self.root, 'initramfs-tools', self.config)


class RollbackScopeTests(unittest.TestCase):
    def test_only_exact_managed_configs_and_boot_images_allowed(self):
        self.assertTrue(r.safe_target('/boot/initrd.img-6.8.0-31-generic'))
        self.assertTrue(r.safe_target('/etc/fstab'))
        for target in ('/etc/passwd', '/boot/../etc/passwd', '/swap-hibernate.img', '/home/user/.zshrc', '/boot/initrd.img-x/../../etc/passwd'):
            self.assertFalse(r.safe_target(target))

    def test_atomic_restore_replaces_content_and_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            source, target = Path(directory)/'original', Path(directory)/'target'
            source.write_text('old config'); source.chmod(0o600)
            target.write_text('new config'); target.chmod(0o644)
            r.atomic_restore(source, target)
            self.assertEqual(target.read_text(), 'old config')
            self.assertEqual(target.stat().st_mode & 0o777, 0o600)
            self.assertEqual(source.read_text(), 'old config')


if __name__ == '__main__': unittest.main()
