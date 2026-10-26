import tempfile
import unittest
from pathlib import Path

from export_obsidian import batch_sync, csv_export
from vocab import Store


class ExportTests(unittest.TestCase):
    def test_batch_sync_and_failed_vault_status(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
            root = Path(folder)
            store = Store(root / 'v.db')
            row, _ = store.add('Wasser', {'part_of_speech': 'Substantiv', 'article': 'das', 'chinese_meaning': '水'})
            vault = root / '我的 Vault ü'
            (vault / '.obsidian').mkdir(parents=True)
            ok, errors = batch_sync(store, vault, root / 'audio')
            self.assertEqual(ok, 1)
            self.assertFalse(errors)
            self.assertIn('成功', store.get(row['id'])['sync_status'])
            ok, errors = batch_sync(store, root / 'missing', root / 'audio')
            self.assertEqual(ok, 0)
            self.assertEqual(len(errors), 1)
            self.assertIn('失败', store.get(row['id'])['sync_status'])

    def test_csv_has_bom_quotes_and_formula_protection(self):
        data = csv_export([{'word': '=1+1', 'chinese_meaning': '水, 液体\n第二行'}])
        self.assertTrue(data.startswith(b'\xef\xbb\xbf'))
        self.assertIn("'=1+1", data.decode('utf-8-sig'))
        self.assertIn('"水, 液体\n第二行"', data.decode('utf-8-sig'))

    def test_export_keeps_offline_dictionary_provenance(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
            root = Path(folder)
            store = Store(root / 'v.db')
            store.add('Hund', {'candidates': [{'sense_id': 'local-a', 'source': 'Kaikki / Wiktextract', 'license': 'Dataset attribution'}]})
            (root / 'vault' / '.obsidian').mkdir(parents=True)
            batch_sync(store, root / 'vault', root / 'audio')
            text = next((root / 'vault').rglob('*.md')).read_text('utf-8')
            self.assertIn('Kaikki / Wiktextract', text)
            self.assertIn('Dataset attribution', text)
