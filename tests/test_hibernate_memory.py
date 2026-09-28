"""Memory preparation safeguards, using simulated counters and subprocesses only."""
import contextlib
import configparser
import errno
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch


SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/hibernate/memory-guard.py'
SPEC = importlib.util.spec_from_file_location('hibernate_memory_guard', SCRIPT)
guard = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(guard)
GIB, MIB = guard.GIB, guard.MIB


def settings(**changes):
    result = dict(available_percent=50, max_reclaim_gib=1, timeout_seconds=10,
                  notify_user='desktop-user', hibernate_swap='/swap-hibernate.img')
    result.update(changes)
    return result


def memory(available, swap=20 * GIB):
    return dict(MemTotal=8 * GIB, MemAvailable=available, SwapFree=swap)


class PreparationTests(unittest.TestCase):
    def test_enough_ram_does_not_request_reclaim(self):
        reclaim = Mock(side_effect=AssertionError('No reclaim needed'))
        result = guard.prepare(settings(), read=lambda: memory(5 * GIB),
                               read_swap=lambda _: 18 * GIB,
                               reclaim_fn=reclaim, clock=lambda: 0)
        reclaim.assert_not_called()
        self.assertEqual(result['requested_reclaim_bytes'], 0)
        self.assertEqual(result['available_bytes'], 5 * GIB)
        self.assertEqual(result['swap_free_bytes'], 18 * GIB)

    def test_rechecks_ram_after_each_chunk_and_stops_at_target(self):
        samples = iter([memory(3584 * MIB), memory(3840 * MIB), memory(4 * GIB)])
        reclaim = Mock()
        result = guard.prepare(settings(), read=lambda: next(samples),
                               read_swap=lambda _: 20 * GIB,
                               reclaim_fn=reclaim, clock=lambda: 0)
        self.assertEqual([call.args for call in reclaim.call_args_list],
                         [(256 * MIB, 5), (256 * MIB, 5)])
        self.assertEqual(result['requested_reclaim_bytes'], 512 * MIB)
        self.assertEqual(result['available_bytes'], result['target_bytes'])

    def test_final_chunk_is_limited_to_remaining_ram_target(self):
        samples = iter([memory(4 * GIB - 64 * MIB), memory(4 * GIB)])
        reclaim = Mock()
        guard.prepare(settings(), read=lambda: next(samples),
                      read_swap=lambda _: 20 * GIB,
                      reclaim_fn=reclaim, clock=lambda: 0)
        reclaim.assert_called_once_with(64 * MIB, 5)

    def test_sub_page_gap_requests_a_nonzero_page_aligned_chunk(self):
        for gap in (1, guard.PAGE - 1, guard.PAGE + 1):
            with self.subTest(gap=gap):
                samples = iter([memory(4 * GIB - gap), memory(4 * GIB)])
                reclaim = Mock()
                result = guard.prepare(settings(), read=lambda: next(samples),
                                       read_swap=lambda _: 20 * GIB,
                                       reclaim_fn=reclaim, clock=lambda: 0)
                reclaim.assert_called_once()
                amount = reclaim.call_args.args[0]
                self.assertGreaterEqual(amount, guard.PAGE)
                self.assertGreaterEqual(amount, gap)
                self.assertLess(amount, gap + guard.PAGE)
                self.assertEqual(amount % guard.PAGE, 0)
                self.assertEqual(result['requested_reclaim_bytes'], amount)

    def test_partial_progress_cannot_exceed_total_reclaim_budget(self):
        samples = iter(memory(2 * GIB + i * 64 * MIB) for i in range(5))
        reclaim = Mock()
        with self.assertRaisesRegex(RuntimeError, 'time or reclaim limit'):
            guard.prepare(settings(), read=lambda: next(samples),
                          read_swap=lambda _: 20 * GIB,
                          reclaim_fn=reclaim, clock=lambda: 0)
        self.assertEqual(reclaim.call_count, 4)
        self.assertEqual(sum(call.args[0] for call in reclaim.call_args_list), GIB)

    def test_expired_deadline_aborts_before_requesting_another_chunk(self):
        clock = Mock(side_effect=[0, 0, 10])
        reclaim = Mock()
        with self.assertRaisesRegex(RuntimeError, 'time or reclaim limit'):
            guard.prepare(settings(), read=lambda: memory(2 * GIB),
                          read_swap=lambda _: 20 * GIB,
                          reclaim_fn=reclaim, clock=clock)
        reclaim.assert_called_once_with(256 * MIB, 5)

    def test_chunk_timeout_uses_remaining_deadline(self):
        clock = Mock(side_effect=[0, 8.5])
        samples = iter([memory(4 * GIB - 16 * MIB), memory(4 * GIB)])
        reclaim = Mock()
        guard.prepare(settings(), read=lambda: next(samples),
                      read_swap=lambda _: 20 * GIB,
                      reclaim_fn=reclaim, clock=clock)
        reclaim.assert_called_once_with(16 * MIB, 1.5)

    def test_child_timeout_is_not_reported_as_success(self):
        reclaim = Mock(side_effect=subprocess.TimeoutExpired(['mock-reclaim'], 5))
        with self.assertRaises(subprocess.TimeoutExpired):
            guard.prepare(settings(), read=lambda: memory(2 * GIB),
                          read_swap=lambda _: 20 * GIB,
                          reclaim_fn=reclaim, clock=lambda: 0)
        reclaim.assert_called_once()

    def test_unrelated_swap_cannot_cover_a_full_hibernation_swap(self):
        reclaim = Mock()
        with self.assertRaisesRegex(RuntimeError, 'Insufficient free hibernation swap'):
            guard.prepare(settings(), read=lambda: memory(5 * GIB, swap=40 * GIB),
                          read_swap=lambda _: 5 * GIB,
                          reclaim_fn=reclaim, clock=lambda: 0)
        reclaim.assert_not_called()

    def test_reclaim_must_not_consume_dedicated_image_reserve(self):
        reclaim = Mock()
        with self.assertRaisesRegex(RuntimeError, 'Not enough free hibernation swap'):
            guard.prepare(settings(), read=lambda: memory(2 * GIB),
                          read_swap=lambda _: 6 * GIB + 128 * MIB,
                          reclaim_fn=reclaim, clock=lambda: 0)
        reclaim.assert_not_called()

    def test_aggregate_free_swap_is_also_checked(self):
        with self.assertRaisesRegex(RuntimeError, 'Insufficient free hibernation swap'):
            guard.prepare(settings(), read=lambda: memory(5 * GIB, swap=5 * GIB),
                          read_swap=lambda _: 20 * GIB,
                          reclaim_fn=Mock(), clock=lambda: 0)

    def test_swap_reserve_is_rechecked_after_reclaim(self):
        samples = iter([memory(4 * GIB - 64 * MIB), memory(4 * GIB)])
        swaps = iter([8 * GIB, 5 * GIB])
        reclaim = Mock()
        with self.assertRaisesRegex(RuntimeError, 'Insufficient free hibernation swap'):
            guard.prepare(settings(), read=lambda: next(samples),
                          read_swap=lambda _: next(swaps),
                          reclaim_fn=reclaim, clock=lambda: 0)
        reclaim.assert_called_once()


class ConfigurationAndCounterTests(unittest.TestCase):
    def test_configuration_bounds_and_strict_integer_types(self):
        with patch.object(guard.pwd, 'getpwnam', return_value=SimpleNamespace(pw_uid=1000)):
            for changes in ({'available_percent': 49}, {'available_percent': 81},
                            {'max_reclaim_gib': 0}, {'max_reclaim_gib': 17},
                            {'timeout_seconds': 4}, {'timeout_seconds': 46},
                            {'available_percent': 50.0}, {'max_reclaim_gib': True},
                            {'timeout_seconds': '10'}):
                with self.subTest(changes=changes), self.assertRaises(ValueError):
                    guard.validate(settings(**changes))
            self.assertEqual(guard.validate(settings()), settings())
            self.assertEqual(guard.validate(settings(available_percent=80,
                                                    max_reclaim_gib=16,
                                                    timeout_seconds=45))['available_percent'], 80)

    def test_unknown_or_missing_keys_are_rejected(self):
        for config in (dict(settings(), unknown=1),
                       {k: v for k, v in settings().items() if k != 'hibernate_swap'}):
            with self.subTest(config=config), self.assertRaises(ValueError):
                guard.validate(config)

    def test_invalid_swap_paths_and_missing_user_are_rejected(self):
        with patch.object(guard.pwd, 'getpwnam', return_value=SimpleNamespace(pw_uid=1000)):
            for swap in ('relative.img', '/dir/../swap.img', '/swap file.img'):
                with self.subTest(swap=swap), self.assertRaises(ValueError):
                    guard.validate(settings(hibernate_swap=swap))
        with patch.object(guard.pwd, 'getpwnam', side_effect=KeyError('missing user')):
            with self.assertRaises(KeyError):
                guard.validate(settings())

    def test_dedicated_swap_matches_exact_path_and_subtracts_usage(self):
        swaps = ('Filename\tType\tSize\tUsed\tPriority\n'
                 '/unrelated.img file 100000000 0 -2\n'
                 '/swap-hibernate.img.old file 80000000 0 100\n'
                 '/swap-hibernate.img file 12000 4000 100\n')
        with patch.object(guard.Path, 'read_text', return_value=swaps):
            self.assertEqual(guard.dedicated_swap_free(settings()), 8000 * 1024)
        with patch.object(guard.Path, 'read_text', return_value=swaps.replace(
                '/swap-hibernate.img file', '/different.img file')):
            with self.assertRaisesRegex(RuntimeError, 'not active'):
                guard.dedicated_swap_free(settings())


class ChildAndEntryPointTests(unittest.TestCase):
    def test_reclaim_accepts_eagain_for_partial_progress(self):
        with patch.object(guard.subprocess, 'run', return_value=SimpleNamespace(returncode=11, stderr='')) as process:
            guard.reclaim(128 * MIB, 2)
        args = process.call_args.args[0]
        self.assertEqual(args[1], '-I')
        self.assertEqual(args[-2:], ['--reclaim-chunk', str(128 * MIB)])
        self.assertEqual(process.call_args.kwargs['timeout'], 2)

    def test_non_eagain_child_failure_propagates(self):
        with patch.object(guard.subprocess, 'run', return_value=SimpleNamespace(
                returncode=1, stderr='permission denied')):
            with self.assertRaisesRegex(RuntimeError, 'permission denied'):
                guard.reclaim(128 * MIB, 2)

    def test_chunk_rejects_unprivileged_or_out_of_bounds_requests(self):
        for uid, amount in ((1000, 1), (0, 0), (0, -1), (0, 256 * MIB + 1)):
            with self.subTest(uid=uid, amount=amount), \
                    patch.object(guard.os, 'geteuid', return_value=uid), \
                    patch.object(guard, 'CGROUP') as cgroup:
                self.assertEqual(guard.main(['--reclaim-chunk', str(amount)]), 1)
                cgroup.write_text.assert_not_called()

    def test_chunk_maps_eagain_without_retrying_or_writing_other_paths(self):
        with patch.object(guard.os, 'geteuid', return_value=0), \
                patch.object(guard, 'CGROUP') as cgroup:
            cgroup.write_text.side_effect = OSError(errno.EAGAIN, 'partial reclaim')
            self.assertEqual(guard.main(['--reclaim-chunk', str(256 * MIB)]), 11)
            cgroup.write_text.assert_called_once_with(f'{256 * MIB} swappiness=200\n')

    def test_check_mode_does_not_prepare_or_write_even_as_root(self):
        with patch.object(guard, 'CONFIG') as config, \
                patch.object(guard.pwd, 'getpwnam', return_value=SimpleNamespace(pw_uid=1000)), \
                patch.object(guard.os, 'geteuid', return_value=0), \
                patch.object(guard, 'meminfo', return_value=memory(2 * GIB)), \
                patch.object(guard, 'dedicated_swap_free', return_value=20 * GIB), \
                patch.object(guard, 'prepare') as prepare, \
                patch.object(guard, 'write_status') as status, \
                patch.object(guard.Path, 'write_text') as write, \
                patch.object(guard.subprocess, 'run') as process, \
                contextlib.redirect_stdout(io.StringIO()) as output:
            config.read_text.return_value = json.dumps(settings())
            self.assertEqual(guard.main(['--check']), 0)
        self.assertEqual(json.loads(output.getvalue())['dedicated_swap_free'], 20 * GIB)
        for mock in (prepare, status, write, process):
            mock.assert_not_called()

    def test_check_cannot_be_combined_with_a_reclaim_request(self):
        with patch.object(guard, 'CGROUP') as cgroup, \
                patch.object(guard, 'CONFIG') as config, \
                contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as raised:
                guard.main(['--check', '--reclaim-chunk', '1'])
        self.assertEqual(raised.exception.code, 2)
        cgroup.write_text.assert_not_called()
        config.read_text.assert_not_called()

    def test_timeout_cancels_and_notifies_before_image_policy_write(self):
        with patch.object(guard, 'CONFIG') as config, \
                patch.object(guard, 'CGROUP') as cgroup, \
                patch.object(guard.pwd, 'getpwnam', return_value=SimpleNamespace(pw_uid=1000)), \
                patch.object(guard.os, 'geteuid', return_value=0), \
                patch.object(guard, 'prepare', side_effect=subprocess.TimeoutExpired(['mock-reclaim'], 5)), \
                patch.object(guard, 'write_status') as status, \
                patch.object(guard, 'notify') as notify, \
                patch.object(guard.Path, 'write_text') as write:
            config.read_text.return_value = json.dumps(settings())
            cgroup.exists.return_value = True
            self.assertEqual(guard.main([]), 1)
        self.assertEqual([call.args[0] for call in status.call_args_list], ['preparing', 'cancelled'])
        self.assertIn('timed out', status.call_args.kwargs['error'])
        notify.assert_called_once()
        write.assert_not_called()


def load_module(name, filename):
    spec = importlib.util.spec_from_file_location(name, SCRIPT.with_name(filename))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def unit_text(text):
    parser = configparser.ConfigParser(interpolation=None)
    parser.optionxform = str
    parser.read_string(text)
    return parser


class SystemdBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        base = load_module('memory_test_hibernate_configuration', 'configure.py')
        with patch.dict(sys.modules, {'configure': base}):
            cls.installer = load_module('memory_test_installer', 'install-memory-guard.py')
        cls.rollback = load_module('memory_test_rollback', 'rollback.py')

    def test_both_graphics_and_hibernate_require_the_ordered_guard(self):
        installer = self.installer
        dependency = unit_text(installer.DEPENDENCY)
        service = unit_text(installer.UNIT_TEXT)
        self.assertEqual(installer.UNIT.name, installer.NAME)
        self.assertEqual(dependency['Unit']['Requires'].split(), [installer.NAME])
        self.assertEqual(dependency['Unit']['After'].split(), [installer.NAME])
        self.assertEqual(set(service['Unit']['Before'].split()),
                         {'nvidia-hibernate.service', 'systemd-hibernate.service'})
        self.assertEqual(installer.HIBERNATE.parent.name, 'systemd-hibernate.service.d')
        self.assertEqual(installer.NVIDIA.parent.name, 'nvidia-hibernate.service.d')

    def test_guard_does_not_remain_active_between_hibernation_attempts(self):
        service = unit_text(self.installer.UNIT_TEXT)['Service']
        self.assertEqual(service['Type'], 'oneshot')
        self.assertIn(service.get('RemainAfterExit', 'no').lower(), ('no', 'false', '0'))
        self.assertEqual(service['KillMode'], 'control-group')
        self.assertEqual(service['ExecStart'].split()[:2], ['/usr/bin/python3', '-I'])
        self.assertIn(str(self.installer.HELPER), service['ExecStart'].split())

    def test_resume_uses_vendor_marker_without_restarting_memory_guard(self):
        installer = self.installer
        resume = unit_text(installer.RESUME_TEXT)
        self.assertEqual(installer.RESUME.parent.name, 'nvidia-resume.service.d')
        self.assertEqual(resume['Unit']['ConditionPathExists'],
                         '/run/nvidia-sleep/Xorg.vt_number')
        for field in ('Requires', 'Wants', 'After', 'Before'):
            self.assertNotIn(installer.NAME, resume['Unit'].get(field, '').split())

    def test_rollback_covers_guard_files_without_authorizing_swap_or_power_paths(self):
        installer = self.installer
        for path in (installer.UNIT, installer.HELPER, installer.CONFIG,
                     installer.HIBERNATE, installer.NVIDIA, installer.RESUME):
            with self.subTest(path=path):
                self.assertTrue(self.rollback.safe_target(str(path)))
        for path in ('/swap-hibernate.img', '/swap.img', '/sys/power/resume',
                     '/sys/power/state', '/sys/fs/cgroup/user.slice/memory.reclaim'):
            with self.subTest(path=path):
                self.assertFalse(self.rollback.safe_target(path))

    def test_rollback_rejects_queued_or_running_power_preparation(self):
        for unit in ('dwm-hibernate-memory.service', 'systemd-hibernate.service',
                     'nvidia-hibernate.service', 'systemd-suspend-then-hibernate.service',
                     'suspend-then-hibernate.target', 'suspend.target', 'sleep.target'):
            result = subprocess.CompletedProcess([], 0, f'7 {unit} start waiting\n', '')
            with self.subTest(unit=unit), \
                    patch.object(self.rollback.subprocess, 'run', return_value=result) as process:
                with self.assertRaisesRegex(RuntimeError, 'before rollback'):
                    self.rollback.refuse_active_transition()
                process.assert_called_once()
                self.assertEqual(process.call_args.args[0][1], 'list-jobs')

    def test_rollback_allows_an_unrelated_queued_job(self):
        result = subprocess.CompletedProcess([], 0, '12 cron.service start waiting\n', '')
        with patch.object(self.rollback.subprocess, 'run', return_value=result):
            self.rollback.refuse_active_transition()

    def test_rollback_cannot_proceed_when_pending_jobs_cannot_be_checked(self):
        result = subprocess.CompletedProcess([], 1, '', 'System bus unavailable\n')
        with patch.object(self.rollback.subprocess, 'run', return_value=result):
            with self.assertRaisesRegex(RuntimeError, 'Cannot check pending power operations.*System bus unavailable'):
                self.rollback.refuse_active_transition()

    def test_rollback_job_query_timeout_does_not_allow_restore(self):
        with patch.object(self.rollback.subprocess, 'run', side_effect=
                          subprocess.TimeoutExpired(['mock-systemctl'], 15)):
            with self.assertRaises(subprocess.TimeoutExpired):
                self.rollback.refuse_active_transition()

    def test_rollback_rejects_active_guard_before_any_restore_or_sysfs_write(self):
        rollback = self.rollback
        plan = ({str(self.installer.CONFIG): True},
                dict(image_size='0', disk='platform', retained_swap='/swap-hibernate.img'))
        result = subprocess.CompletedProcess(
            [], 0, '9 dwm-hibernate-memory.service start running\n', '')
        with patch.object(rollback, 'load_plan', return_value=plan), \
                patch.object(rollback.os, 'geteuid', return_value=0), \
                patch.object(rollback.subprocess, 'run', return_value=result) as process, \
                patch.object(rollback, 'atomic_restore') as restore, \
                patch.object(rollback.Path, 'unlink') as unlink, \
                patch.object(rollback.Path, 'write_text') as write, \
                patch.object(rollback.os, 'sync') as sync, \
                contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(RuntimeError, 'before rollback'):
                rollback.main(['--apply'])
        for mutation in (restore, unlink, write, sync):
            mutation.assert_not_called()
        process.assert_called_once()
        self.assertEqual(process.call_args.args[0][1], 'list-jobs')


if __name__ == '__main__':
    unittest.main()
