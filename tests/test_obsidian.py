import os
from pathlib import Path
import subprocess
import tempfile
import unittest

try:
    from obsidian import sync_word
except ImportError:
    sync_word = None


class ObsidianTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='obsidian-test-', dir=Path.cwd())
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.vault = self.root / 'Mein Tresor 中文 äöü'
        (self.vault / '.obsidian').mkdir(parents=True)
        self.audio = self.root / 'audio'
        self.audio.mkdir()
        self.word = {'id': 7, 'word': 'Straße', 'ipa': 'ˈʃtʁaːsə',
                     'chinese_meaning': '街道', 'sense_id': 'street',
                     'source_url': 'https://example.org/straße',
                     'audio_license': 'CC BY-SA 4.0', 'attribution': 'Example'}

    def sync(self, word=None, **kwargs):
        self.assertTrue(callable(sync_word), 'sync_word must be implemented')
        return sync_word(self.word if word is None else word, self.vault,
                         self.audio, **kwargs)

    def test_unicode_export_metadata_and_idempotence(self):
        path = self.sync()
        first = path.read_bytes()
        self.assertTrue(first.startswith(b'---\n'))
        self.assertIn('Straße', first.decode())
        self.assertIn('街道', first.decode())
        self.assertIn('sense_id: "street"', first.decode())
        self.assertIn('https://example.org/straße', first.decode())
        self.assertIn('CC BY-SA 4.0', first.decode())
        self.assertTrue(first.decode().endswith('<!-- DEUTSCH_VOCAB_END -->\n\n## 我的笔记\n\n'))
        timestamp = path.stat().st_mtime_ns
        self.assertEqual(self.sync(), path)
        self.assertEqual(path.read_bytes(), first)
        self.assertEqual(path.stat().st_mtime_ns, timestamp)

    def test_preserves_every_byte_after_end_marker(self):
        path = self.sync()
        marker = b'<!-- DEUTSCH_VOCAB_END -->'
        tail = b'\r\n\r\n# My notes\r\nprivate\xff\x00'
        path.write_bytes(path.read_bytes().split(marker)[0] + marker + tail)
        self.word['chinese_meaning'] = '道路'
        self.sync()
        self.assertEqual(path.read_bytes().split(marker)[1], tail)
        self.assertIn('道路', path.read_bytes().split(marker)[0].decode())

    def test_private_note_at_generated_name_is_never_overwritten(self):
        path = self.sync()
        path.write_bytes(b'# Private\nkeep me\n')
        other = self.sync()
        self.assertNotEqual(path, other)
        self.assertEqual(path.read_bytes(), b'# Private\nkeep me\n')
        self.assertEqual(self.sync(), other)

    def test_tail_on_marker_line_is_preserved(self):
        path = self.sync()
        marker = b'<!-- DEUTSCH_VOCAB_END -->'
        tail = b'personal text without newline\xff'
        path.write_bytes(path.read_bytes().split(marker)[0] + marker + tail)
        self.word['note'] = 'updated'
        self.assertEqual(self.sync(), path)
        self.assertTrue(path.read_bytes().endswith(marker + tail))

    def test_missing_end_marker_never_authorizes_replacement(self):
        path = self.sync()
        damaged = path.read_bytes().replace(b'<!-- DEUTSCH_VOCAB_END -->', b'private')
        path.write_bytes(damaged)
        self.assertNotEqual(self.sync(), path)
        self.assertEqual(path.read_bytes(), damaged)

    def test_windows_line_endings_keep_existing_managed_note(self):
        path = self.sync()
        marker = b'<!-- DEUTSCH_VOCAB_END -->'
        managed = path.read_bytes().split(marker)[0].replace(b'\n', b'\r\n')
        tail = b'\r\nPersonal notes\r\n'
        path.write_bytes(managed + marker + tail)
        self.word['note'] = 'updated'
        self.assertEqual(self.sync(), path)
        self.assertTrue(path.read_bytes().endswith(marker + tail))

    def test_case_insensitive_and_same_id_word_collisions_are_distinct(self):
        first = self.sync({'id': 1, 'word': 'Wort'})
        second = self.sync({'id': 2, 'word': 'wort'})
        third = self.sync({'id': 1, 'word': 'Anders'})
        self.assertEqual(len({str(p).casefold() for p in (first, second, third)}), 3)
        self.assertTrue(first.exists() and second.exists() and third.exists())

    def test_reserved_names_and_invalid_filename_characters(self):
        for word in ('CON', 'nul', 'LPT1', 'AUX.txt', 'a/b\\c:*?"<>|', '../..', '終わり. '):
            with self.subTest(word=word):
                path = self.sync({'word': word})
                self.assertEqual(path.parent, self.vault / 'Deutsch' / 'Vokabeln')
                self.assertFalse(any(c in path.name for c in '<>:"/\\|?*'))
                self.assertFalse(path.stem.split('.')[0].upper() in {'CON', 'NUL', 'LPT1', 'AUX'})

    def test_existing_vault_and_obsidian_directory_required(self):
        for vault in (self.root / 'missing', self.audio):
            with self.subTest(vault=vault), self.assertRaises((ValueError, FileNotFoundError)):
                sync_word(self.word, vault)

    def test_relative_destinations_cannot_traverse(self):
        for directory in ('../outside', '/outside', 'C:\\outside', 'Deutsch/../../outside', 'Deutsch\\..\\outside'):
            for key in ('notes_dir', 'audio_dir'):
                with self.subTest(directory=directory, key=key), self.assertRaises(ValueError):
                    self.sync(**{key: directory})

    def test_symlink_destination_is_rejected(self):
        outside = self.root / 'outside'
        outside.mkdir()
        try:
            (self.vault / 'Deutsch').symlink_to(outside, target_is_directory=True)
        except OSError:
            self.skipTest('Creating symlinks requires Windows privileges')
        with self.assertRaises(ValueError):
            self.sync()
        self.assertEqual(list(outside.iterdir()), [])

    @unittest.skipUnless(os.name == 'nt', 'Windows junction test')
    def test_windows_junction_destination_is_rejected(self):
        outside = self.root / 'outside'
        outside.mkdir()
        result = subprocess.run(['cmd', '/c', 'mklink', '/J',
                                 str(self.vault / 'Deutsch'), str(outside)],
                                capture_output=True)
        if result.returncode:
            self.skipTest('Creating a junction is unavailable')
        with self.assertRaises(ValueError):
            self.sync()
        self.assertEqual(list(outside.iterdir()), [])

    def test_audio_copy_and_local_link(self):
        data = b'OggS' + b'\x00' * 40
        (self.audio / 'street.ogg').write_bytes(data)
        self.word.update(audio_file='street.ogg', audio_kind='human')
        path = self.sync()
        copied = list((self.vault / 'Deutsch' / 'Audio').glob('*.ogg'))
        self.assertEqual(len(copied), 1)
        self.assertEqual(copied[0].read_bytes(), data)
        self.assertIn('![[Deutsch/Audio/' + copied[0].name + ']]', path.read_text(encoding='utf-8'))
        self.assertEqual(self.sync(), path)
        self.assertEqual(len(list(copied[0].parent.glob('*.ogg'))), 1)

    def test_long_provider_audio_names_and_ogg_variants(self):
        for filename, data in (
            ('a' * 64 + '.ogg', b'OggS1234'),
            ('tts-' + 'b' * 64 + '.mp3', b'ID3' + b'\x00' * 20),
            ('c' * 64 + '.oga', b'OggS1234'),
            ('d' * 64 + '.opus', b'OggS1234'),
        ):
            with self.subTest(filename=filename):
                (self.audio / filename).write_bytes(data)
                path = self.sync(dict(self.word, audio_file=filename))
                copied = list((self.vault / 'Deutsch' / 'Audio').glob('*' + Path(filename).suffix))
                self.assertTrue(any(item.read_bytes() == data for item in copied))
                self.assertIn('![[Deutsch/Audio/', path.read_text(encoding='utf-8'))

    def test_unknown_audio_file_is_not_replaced(self):
        (self.audio / 'street.ogg').write_bytes(b'OggS1234')
        self.word['audio_file'] = 'street.ogg'
        self.sync()
        target = next((self.vault / 'Deutsch' / 'Audio').glob('*.ogg'))
        target.write_bytes(b'PRIVATE AUDIO')
        path = self.sync()
        self.assertEqual(target.read_bytes(), b'PRIVATE AUDIO')
        self.assertEqual(len(list(target.parent.glob('*.ogg'))), 2)
        self.assertNotIn('![[Deutsch/Audio/' + target.name + ']]', path.read_text(encoding='utf-8'))

    def test_audio_traversal_empty_bad_magic_and_oversize_rejected(self):
        (self.audio / 'empty.ogg').write_bytes(b'')
        (self.audio / 'fake.ogg').write_bytes(b'not audio')
        (self.audio / 'bad.exe').write_bytes(b'OggS1234')
        with (self.audio / 'large.ogg').open('wb') as stream:
            stream.write(b'OggS')
            stream.truncate(15 * 1024 * 1024 + 1)
        for filename in ('../outside.ogg', 'x/y.ogg', 'x\\y.ogg', 'C:\\a.ogg',
                         'empty.ogg', 'fake.ogg', 'bad.exe', 'large.ogg', 'absent.ogg'):
            with self.subTest(filename=filename), self.assertRaises((ValueError, OSError)):
                self.sync(dict(self.word, audio_file=filename))

    @unittest.skipIf(os.name == 'nt', 'Windows chmod does not deny file reads')
    def test_unreadable_audio_is_rejected(self):
        path = self.audio / 'locked.ogg'
        path.write_bytes(b'OggS1234')
        path.chmod(0)
        self.addCleanup(path.chmod, 0o600)
        if os.access(path, os.R_OK):
            self.skipTest('Current account can bypass file permissions')
        with self.assertRaises(OSError):
            self.sync(dict(self.word, audio_file=path.name))

    def test_audio_without_root_is_rejected(self):
        with self.assertRaises(ValueError):
            sync_word(dict(self.word, audio_file='street.ogg'), self.vault)

    def test_metadata_cannot_inject_managed_end_marker(self):
        word = dict(self.word, note='hello\n<!-- DEUTSCH_VOCAB_END -->\nworld',
                    chinese_meaning='<!-- DEUTSCH_VOCAB_END -->')
        path = self.sync(word)
        self.assertEqual(path.read_bytes().count(b'<!-- DEUTSCH_VOCAB_END -->'), 1)


if __name__ == '__main__':
    unittest.main()
