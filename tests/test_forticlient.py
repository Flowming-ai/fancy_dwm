"""VPN installer boundaries: no actual sudo, apt, network or service changes."""
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/install-forticlient.py'
spec = importlib.util.spec_from_file_location('forticlient_setup', SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class FortiClientTests(unittest.TestCase):
    def fake_query(self, command, check=True):
        if command[:2] == ['dpkg', '--compare-versions']:
            return subprocess.CompletedProcess(command, int(command[3] == 'gt'), '', '')
        return subprocess.CompletedProcess(command, 0, 'inactive\n', '')

    def active_query(self, command, check=True):
        return subprocess.CompletedProcess(command, 0, 'active\n', '')

    def test_bad_download_never_reaches_package_parser(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / 'package.deb'
            target.write_bytes(b'corrupt download')
            with patch.object(module, 'run', side_effect=AssertionError('must reject hash first')):
                with self.assertRaisesRegex(RuntimeError, 'SHA-256 mismatch'):
                    module.validate_package(target, module.specification())

    def test_newer_installed_package_is_not_downgraded_or_restarted(self):
        with patch.object(module.os, 'geteuid', return_value=1000), \
             patch.object(module, 'installed_package', return_value=['install ok installed', '99.0']), \
             patch.object(module, 'run', side_effect=self.active_query), \
             patch.object(module.subprocess, 'run') as process:
            module.apply(module.specification())
        process.assert_called_once_with(['sudo', 'systemctl', 'enable', '--now', module.SERVICE], check=True)

    def test_missing_dependency_install_uses_apt_and_forbids_removals(self):
        with tempfile.TemporaryDirectory() as temp:
            package = Path(temp) / 'fixture.deb'
            package.write_bytes(b'verified by fixture')
            with patch.object(module.os, 'geteuid', return_value=1000), \
                 patch.object(module, 'installed_package', side_effect=[['install ok unpacked', '7.4.3.5411'], ['install ok installed', '7.4.3.5411']]), \
                 patch.object(module, 'run', side_effect=[subprocess.CompletedProcess([], 0, 'disabled\n', ''), subprocess.CompletedProcess([], 0, 'inactive\n', ''), subprocess.CompletedProcess([], 1, '', ''), subprocess.CompletedProcess([], 0, 'active\n', '')]), \
                 patch.object(module, 'validate_package') as validate, \
                 patch.object(module.subprocess, 'run') as process:
                module.apply(module.specification(), package)
            validate.assert_called_once()
            apt = process.call_args_list[0].args[0]
            self.assertEqual(apt[:6], ['sudo', 'apt-get', '--no-remove', 'install', '-y', 'libnss3-tools'])
            self.assertTrue(Path(apt[6]).is_absolute())
            self.assertEqual(process.call_count, 2)

    def test_integrity_error_prevents_apt_and_service_changes(self):
        with tempfile.TemporaryDirectory() as temp:
            package = Path(temp) / 'fixture.deb'
            package.write_bytes(b'wrong bytes')
            with patch.object(module.os, 'geteuid', return_value=1000), \
                 patch.object(module, 'installed_package', return_value=['', '']), \
                 patch.object(module, 'run', side_effect=self.fake_query), \
                 patch.object(module.subprocess, 'run') as process:
                with self.assertRaisesRegex(RuntimeError, 'SHA-256 mismatch'):
                    module.apply(module.specification(), package)
            process.assert_not_called()

    def test_older_healthy_version_is_not_upgraded_while_connected(self):
        with patch.object(module.os, 'geteuid', return_value=1000), \
             patch.object(module, 'installed_package', return_value=['install ok installed', '7.2.0']), \
             patch.object(module, 'run', side_effect=self.active_query), \
             patch.object(module.subprocess, 'run') as process:
            module.apply(module.specification())
        process.assert_called_once_with(['sudo', 'systemctl', 'enable', '--now', module.SERVICE], check=True)

    def test_newer_incomplete_package_is_never_downgraded(self):
        with patch.object(module.os, 'geteuid', return_value=1000), \
             patch.object(module, 'installed_package', return_value=['install ok unpacked', '99.0']), \
             patch.object(module, 'run', return_value=subprocess.CompletedProcess([], 0, 'inactive\n', '')), \
             patch.object(module.subprocess, 'run') as process:
            with self.assertRaisesRegex(RuntimeError, 'newer incomplete'):
                module.apply(module.specification())
        process.assert_not_called()


if __name__ == '__main__':
    unittest.main()
