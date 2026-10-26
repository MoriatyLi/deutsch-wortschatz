import tempfile
import unittest
from pathlib import Path

from desktop_app import initialize_data
from vocab import Store


class DesktopDataTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.resources = self.root / 'application'
        (self.resources / 'dictionary').mkdir(parents=True)
        (self.resources / 'dictionary' / 'de-zh.db').write_bytes(b'fixture')
        self.target = self.root / 'personal'
        seed = Store(self.resources / 'user_data' / 'vocab.db')
        seed.add('Wasser', {'chinese_meaning': '水', 'note': '原备注'})
        seed.set_setting('offline_path', '__BUNDLED__')
        seed.set_setting('bundled_dictionary_path', '__BUNDLED__')

    def tearDown(self):
        self.temp.cleanup()

    def test_first_launch_relocates_seed_dictionary_and_keeps_words(self):
        initialize_data(self.target, self.resources)
        store = Store(self.target / 'vocab.db')
        self.assertEqual(store.find('wasser')['note'], '原备注')
        self.assertEqual(store.get_setting('offline_path'), str(self.resources / 'dictionary' / 'de-zh.db'))
        self.assertEqual(store.get_setting('online'), '0')
        self.assertEqual(store.get_setting('tts'), '0')

    def test_subsequent_launch_never_replaces_user_edits(self):
        initialize_data(self.target, self.resources)
        store = Store(self.target / 'vocab.db')
        store.update(store.find('Wasser')['id'], note='新备注')
        store.add('Hund', {'chinese_meaning': '狗'})
        initialize_data(self.target, self.resources)
        self.assertEqual(store.find('Wasser')['note'], '新备注')
        self.assertEqual(store.find('Hund')['chinese_meaning'], '狗')

    def test_moved_application_relocates_default_but_preserves_custom_dictionary(self):
        initialize_data(self.target, self.resources)
        moved = self.root / 'moved'
        self.resources.rename(moved)
        initialize_data(self.target, moved)
        store = Store(self.target / 'vocab.db')
        self.assertEqual(store.get_setting('offline_path'), str(moved / 'dictionary' / 'de-zh.db'))
        custom = self.root / 'my-dictionary.db'
        custom.touch()
        store.set_setting('offline_path', str(custom))
        moved.rename(self.resources)
        initialize_data(self.target, self.resources)
        self.assertEqual(store.get_setting('offline_path'), str(custom))


if __name__ == '__main__':
    unittest.main()
