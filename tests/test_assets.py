"""Offline installer-asset tests; all writes use temporary fixture homes."""
import io
from pathlib import Path
import shutil
import tarfile
import tempfile
import types
import unittest
from unittest.mock import patch


class AssetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='dwm-asset-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        script = Path(__file__).resolve().parents[1] / 'scripts/install-assets.py'
        self.assets = types.ModuleType('fixture_install_assets')
        self.assets.__file__ = str(script)
        exec(compile(script.read_text(), str(script), 'exec'), self.assets.__dict__)
        self.binary = b'\x7fELFfixture executable'
        self.archives = self.root / 'archives'
        self.archives.mkdir()
        self.archive('starship.tar.gz', {'starship': self.binary})
        self.archive('fastfetch.tar.gz', {
            'release/usr/share/bash-completion/completions/fastfetch': b'not a binary',
            'release/usr/bin/fastfetch': self.binary,
        })
        self.archive('JetBrainsMono.tar.xz', {
            'JetBrainsMonoNerdFontMono-Regular.ttf': b'monospace font',
            'JetBrainsMonoNerdFont-Regular.ttf': b'not selected',
            'OFL.txt': b'font license',
        })

    def archive(self, name, entries):
        with tarfile.open(self.archives / name, 'w:gz') as archive:
            for name, data in entries.items():
                entry = tarfile.TarInfo(name)
                entry.size = len(data)
                archive.addfile(entry, io.BytesIO(data))

    def prepare(self, name):
        stage = self.root / name
        stage.mkdir()
        def download(spec, target):
            shutil.copy2(self.archives / target.name, target)
        def git_checkout(spec, target):
            target.mkdir()
            (target / 'pinned.txt').write_text(spec['commit'])
        with patch.object(self.assets, 'download', download), \
             patch.object(self.assets, 'git_checkout', git_checkout), \
             patch.object(self.assets.subprocess, 'run') as command:
            self.assets.prepare('amd64', stage, True, True)
            self.assertEqual(command.call_count, 2)  # version probes only
        return stage

    def test_prepare_selects_binary_and_mono_fonts(self):
        stage = self.prepare('stage')
        self.assertEqual((stage / 'artifacts/fastfetch').read_bytes(), self.binary)
        self.assertEqual(sorted(p.name for p in (stage / 'fonts').glob('*.ttf')),
                         ['JetBrainsMonoNerdFontMono-Regular.ttf'])
        self.assertTrue((stage / 'fonts/OFL.txt').is_file())
        self.archive('bad.tar.gz', {'release/usr/bin/fastfetch': b'not ELF'})
        with self.assertRaises(RuntimeError):
            self.assets.unpack_file(self.archives / 'bad.tar.gz', 'fastfetch', self.root / 'bad')

    def test_two_installs_preserve_custom_plugin_and_original_backup(self):
        home = self.root / 'home'
        custom = home / '.oh-my-zsh/custom/plugins/mine/settings'
        custom.parent.mkdir(parents=True)
        custom.write_text('keep me')
        (home / '.oh-my-zsh/old.txt').write_text('original framework')
        for round_number in (1, 2):
            stage = self.prepare(f'stage{round_number}')
            backup = self.root / f'backup{round_number}'
            backup.mkdir()
            self.assets.apply(stage, home, backup)
            self.assertEqual(custom.read_text(), 'keep me')
            self.assertTrue((home / '.oh-my-zsh/custom/plugins/zsh-autosuggestions/pinned.txt').is_file())
            self.assertTrue((home / '.local/share/fonts/JetBrainsMono/JetBrainsMonoNerdFontMono-Regular.ttf').is_file())
            self.assertEqual(len((backup / 'user-files.txt').read_text().splitlines()), 2)
        self.assertEqual((self.root / 'backup1/home/.oh-my-zsh/old.txt').read_text(),
                         'original framework')

    def test_preflight_rejects_plugin_and_font_parent_symlinks(self):
        home = self.root / 'home'
        (home / '.oh-my-zsh/custom').mkdir(parents=True)
        outside = self.root / 'outside'
        outside.mkdir()
        sentinel = outside / 'keep'
        sentinel.write_text('unchanged')
        plugins = home / '.oh-my-zsh/custom/plugins'
        plugins.symlink_to(outside, target_is_directory=True)
        with self.assertRaises(RuntimeError):
            self.assets.preflight(home)
        plugins.unlink()
        (home / '.local').symlink_to(outside, target_is_directory=True)
        with self.assertRaises(RuntimeError):
            self.assets.preflight(home)
        self.assertEqual(sentinel.read_text(), 'unchanged')


if __name__ == '__main__':
    unittest.main()
