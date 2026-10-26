import tempfile
import unittest
from unittest.mock import patch
import os
from pathlib import Path

from export_obsidian import save_word_table
from obsidian import sync_word_table
from vocab import Store


class WordTableTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.vault = self.root / 'Obsidian Vault'
        (self.vault / '.obsidian').mkdir(parents=True)
        self.path = self.vault / '德语单词.md'
        self.rows = [{'id': 1, 'word': 'Wasser', 'article': 'das', 'part_of_speech': 'Substantiv',
                      'ipa': 'ˈvasɐ', 'chinese_meaning': '水', 'note': '喝水 | 每天\n复习',
                      'meaning_source': 'Wiktionary', 'source_url': 'https://zh.wiktionary.org/wiki/Wasser'}]

    def test_empty_note_becomes_single_table_and_updates_idempotently(self):
        self.path.touch()
        self.assertEqual(sync_word_table(self.rows, self.path), self.path)
        data = self.path.read_bytes()
        text = data.decode()
        for expected in ('Wasser', '水', 'das', 'ˈvasɐ', '喝水 &#124; 每天<br>复习'):
            self.assertIn(expected, text)
        sync_word_table(self.rows, self.path)
        self.assertEqual(data, self.path.read_bytes())
        self.rows[0]['chinese_meaning'] = '水；水域'
        sync_word_table(self.rows, self.path)
        self.assertIn('水；水域', self.path.read_text('utf-8'))
        self.assertEqual(self.path.read_text('utf-8').count('<!-- DEUTSCH_VOCAB_TABLE_BEGIN -->'), 1)

    def test_preserves_existing_note_and_all_bytes_outside_generated_region(self):
        original = b'---\r\ntags: [Deutsch]\r\n---\r\n# Personal\r\nprivate\xff\r\n'
        self.path.write_bytes(original)
        sync_word_table(self.rows, self.path)
        tail = b'\r\n## My notes\r\nkeep this\xff'
        self.path.write_bytes(self.path.read_bytes() + tail)
        self.rows[0]['chinese_meaning'] = '水；液体'
        sync_word_table(self.rows, self.path)
        self.assertTrue(self.path.read_bytes().startswith(original))
        self.assertTrue(self.path.read_bytes().endswith(tail))

    def test_missing_or_duplicate_marker_refuses_to_modify_note(self):
        for content in (b'notes\n<!-- DEUTSCH_VOCAB_TABLE_BEGIN -->\nprivate',
                        b'<!-- DEUTSCH_VOCAB_TABLE_BEGIN -->\n<!-- DEUTSCH_VOCAB_TABLE_BEGIN -->\n<!-- DEUTSCH_VOCAB_TABLE_END -->'):
            self.path.write_bytes(content)
            with self.assertRaises(ValueError):
                sync_word_table(self.rows, self.path)
            self.assertEqual(self.path.read_bytes(), content)

    def test_local_audio_and_attribution_are_exported(self):
        audio = self.root / 'audio'
        audio.mkdir()
        (audio / 'water.ogg').write_bytes(b'OggS' + b'fixture')
        self.rows[0].update(audio_file='water.ogg', audio_url='https://commons.wikimedia.org/wiki/File:water.ogg',
                            audio_license='CC BY-SA 4.0', attribution='Example speaker')
        sync_word_table(self.rows, self.path, audio)
        text = self.path.read_text('utf-8')
        self.assertIn('![[Deutsch/Audio/audio-', text)
        self.assertIn('CC BY-SA 4.0', text)
        self.assertIn('Example speaker', text)
        self.assertEqual(len(list((self.vault / 'Deutsch' / 'Audio').glob('*.ogg'))), 1)

    def test_rejects_non_vault_and_wrong_extension(self):
        for target in (self.root / 'private.md', self.vault / 'private.txt', self.vault / '.obsidian' / 'config.md'):
            with self.assertRaises(ValueError):
                sync_word_table(self.rows, target)
            self.assertFalse(target.exists())

    def test_store_export_uses_all_words(self):
        store = Store(self.root / 'vocab.db')
        store.add('Wasser', {'chinese_meaning': '水'})
        store.add('Hund', {'chinese_meaning': '狗'})
        save_word_table(store, self.path)
        text = self.path.read_text('utf-8')
        self.assertIn('Wasser', text)
        self.assertIn('Hund', text)

    def test_brief_windows_file_lock_retries_without_losing_note(self):
        sync_word_table(self.rows, self.path)
        self.rows[0]['chinese_meaning'] = '水；液体'
        error = PermissionError('Temporary Windows file lock')
        error.winerror = 32
        replace = os.replace
        calls = []

        def locked_once(source, target):
            calls.append(target)
            if len(calls) == 1:
                raise error
            return replace(source, target)

        with patch('obsidian.os.replace', side_effect=locked_once):
            sync_word_table(self.rows, self.path)
        self.assertEqual(len(calls), 2)
        self.assertIn('水；液体', self.path.read_text('utf-8'))

    def test_user_edit_during_retry_is_never_replaced(self):
        sync_word_table(self.rows, self.path)
        original = self.path.read_bytes()
        self.rows[0]['chinese_meaning'] = '水；液体'
        changed = original + b'\nprivate edit\n'
        error = PermissionError('Temporary Windows file lock')
        error.winerror = 32

        def locked_and_edited(source, target):
            self.path.write_bytes(changed)
            raise error

        with patch('obsidian.os.replace', side_effect=locked_and_edited):
            with self.assertRaises(RuntimeError):
                sync_word_table(self.rows, self.path)
        self.assertEqual(self.path.read_bytes(), changed)


if __name__ == '__main__':
    unittest.main()
