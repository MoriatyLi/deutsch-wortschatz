import hashlib
import tempfile
import unittest
from pathlib import Path

from tools.build_seed import prepare_seed
from vocab import Store


class BuildSeedTests(unittest.TestCase):
    def test_default_seed_excludes_personal_words_and_machine_settings(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            private = Store(root / 'private.db')
            private.add('private-word', {'note': 'PRIVATE-NOTE-MARKER'})
            private.set_setting('vault', 'PRIVATE-VAULT-PATH')
            before = hashlib.sha256(private.path.read_bytes()).hexdigest()
            target = root / 'build' / 'seed.db'
            prepare_seed(target, private.path)
            seed = Store(target)
            self.assertEqual(seed.list(), [])
            self.assertEqual(seed.get_setting('offline_path'), '__BUNDLED__')
            self.assertEqual(seed.get_setting('vault'), '')
            self.assertNotIn(b'PRIVATE', target.read_bytes())
            self.assertEqual(hashlib.sha256(private.path.read_bytes()).hexdigest(), before)

    def test_explicit_personal_build_retains_words_but_clears_paths_and_cache(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            private = Store(root / 'private.db')
            private.add('Wasser', {'chinese_meaning': '水'})
            private.set_setting('word_table_path', 'private-table.md')
            private.set_setting('auto_save_word_table', '1')
            private.cache_set('query', {'private': True})
            target = root / 'seed.db'
            prepare_seed(target, private.path, include_personal=True)
            seed = Store(target)
            self.assertEqual(seed.find('Wasser')['chinese_meaning'], '水')
            self.assertEqual(seed.get_setting('word_table_path'), '')
            self.assertEqual(seed.get_setting('auto_save_word_table'), '0')
            self.assertIsNone(seed.cache_get('query'))

    def test_missing_personal_source_does_not_replace_existing_seed(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            target = root / 'seed.db'
            target.write_bytes(b'keep existing seed')
            with self.assertRaises(FileNotFoundError):
                prepare_seed(target, root / 'missing.db', include_personal=True)
            self.assertEqual(target.read_bytes(), b'keep existing seed')


if __name__ == '__main__':
    unittest.main()
