import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import Mock

from vocab import Store, Vocabulary


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'vocab.db'
        self.db = Store(self.path)

    def tearDown(self):
        self.tmp.cleanup()

    def test_unicode_casefold_duplicate_retains_first(self):
        row, added = self.db.add('  Straße  ', {'ipa': 'ʃtʁaːsə'})
        duplicate, again = self.db.add('STRASSE', {'ipa': 'wrong'})
        self.assertTrue(added)
        self.assertFalse(again)
        self.assertEqual(row['id'], duplicate['id'])
        self.assertEqual(duplicate['ipa'], 'ʃtʁaːsə')

    def test_old_table_migration_preserves_all_records_and_is_repeatable(self):
        old = Path(self.tmp.name) / 'old.db'
        with closing(sqlite3.connect(old)) as conn, conn:
            conn.execute('CREATE TABLE words (id INTEGER PRIMARY KEY, word TEXT, note TEXT, created_at TEXT)')
            conn.executemany('INSERT INTO words VALUES (?, ?, ?, ?)', [(9, 'Wasser', '私人的备注', '2020'), (12, 'Hund', 'dog', '2021')])
        store = Store(old)
        Store(old)
        self.assertEqual(store.get(9)['note'], '私人的备注')
        self.assertEqual(store.get(9)['created_at'], '2020')
        self.assertEqual(len(store.list()), 2)
        self.assertTrue(list(old.parent.glob('old.db.backup-*')))

    def test_manual_fields_survive_refresh(self):
        row, _ = self.db.add('Bank', {'part_of_speech': 'Substantiv', 'article': 'die', 'chinese_meaning': 'bank', 'meaning_source': 'MyMemory'})
        self.db.update(row['id'], chinese_meaning='银行；长椅', meaning_reviewed=True, article='die', note='mine')
        self.db.refresh(row['id'], {'chinese_meaning': 'wrong', 'meaning_reviewed': False, 'article': 'das', 'ipa': 'baŋk'})
        saved = self.db.get(row['id'])
        self.assertEqual(saved['chinese_meaning'], '银行；长椅')
        self.assertTrue(saved['meaning_reviewed'])
        self.assertEqual(saved['article'], 'die')
        self.assertEqual(saved['ipa'], 'baŋk')
        self.assertEqual(Store(self.path).get(row['id'])['note'], 'mine')

    def test_unknown_is_null_and_non_noun_has_no_article(self):
        row, _ = self.db.add('sprechen', {'part_of_speech': 'Verb', 'article': 'der'})
        self.assertIsNone(row['article'])
        self.assertIsNone(row['ipa'])
        self.assertIsNone(row['chinese_meaning'])

    def test_sense_selection_never_keeps_audio_from_other_sense(self):
        candidates = [dict(sense_id='a', sense='A', ipa='a', article='der', part_of_speech='Substantiv'), dict(sense_id='b', sense='B', ipa='b', article='das', part_of_speech='Substantiv')]
        row, _ = self.db.add('Band', {'candidates': candidates, 'audio_file': 'a.ogg', 'sense_id': 'a'})
        saved = self.db.select_sense(row['id'], 'b')
        self.assertEqual(saved['ipa'], 'b')
        self.assertEqual(saved['article'], 'das')
        self.assertIsNone(saved['audio_file'])
        self.assertEqual(saved['sense_id'], 'b')

    def test_cache_persists_and_expires(self):
        self.db.cache_set('word', {'ok': 1})
        self.assertEqual(Store(self.path).cache_get('word'), {'ok': 1})
        self.assertIsNone(self.db.cache_get('word', max_age=-1))

    def test_search_literal_and_settings_and_delete(self):
        row, _ = self.db.add('Mädchen', {'chinese_meaning': '女孩'})
        self.db.add('Hund')
        self.assertEqual(len(self.db.list('女孩')), 1)
        self.assertEqual(len(self.db.list('%')), 0)
        self.db.set_setting('vault', '中文 path')
        self.assertEqual(Store(self.path).get_setting('vault'), '中文 path')
        self.db.delete(row['id'])
        self.assertIsNone(self.db.get(row['id']))

    def test_invalid_input_and_invalid_edit(self):
        for word in ['', '  ', 'a\nB', 'a' * 201]:
            with self.subTest(word=word), self.assertRaises(ValueError):
                self.db.add(word)
        row, _ = self.db.add('Wasser')
        with self.assertRaises(ValueError):
            self.db.update(row['id'], article='banana')

    def test_legacy_reviewed_meaning_is_protected_on_first_upgrade(self):
        old = Path(self.tmp.name) / 'reviewed.db'
        with closing(sqlite3.connect(old)) as conn, conn:
            conn.execute('CREATE TABLE words (id INTEGER PRIMARY KEY, word TEXT, chinese_meaning TEXT, meaning_reviewed INTEGER)')
            conn.execute("INSERT INTO words VALUES (1, 'Bank', '人工银行', 1)")
        migrated = Store(old)
        migrated.refresh(1, {'chinese_meaning': 'wrong', 'meaning_reviewed': False})
        self.assertEqual(migrated.get(1)['chinese_meaning'], '人工银行')
        self.assertTrue(migrated.get(1)['meaning_reviewed'])

    def test_auto_sense_does_not_block_retry_of_missing_audio(self):
        row, _ = self.db.add('Hund', {'sense_id': 'automatic', 'ipa': 'hʊnt'})
        self.db.refresh(row['id'], {'sense_id': 'automatic', 'audio_file': 'dog.ogg', 'audio_kind': 'human'})
        self.assertEqual(self.db.get(row['id'])['audio_file'], 'dog.ogg')

    def test_marking_reviewed_protects_existing_translation(self):
        row, _ = self.db.add('Bank', {'chinese_meaning': '银行', 'meaning_source': 'Wiktionary (zh)'})
        self.db.update(row['id'], meaning_reviewed=True)
        self.db.refresh(row['id'], {'chinese_meaning': 'wrong', 'meaning_source': 'MyMemory', 'meaning_reviewed': False})
        saved = self.db.get(row['id'])
        self.assertEqual(saved['chinese_meaning'], '银行')
        self.assertTrue(saved['meaning_reviewed'])

    def test_refresh_ambiguous_candidate_set_clears_old_automatic_pronunciation(self):
        row, _ = self.db.add('Band', {'sense_id': 'old', 'ipa': 'old', 'audio_file': 'old.ogg'})
        self.db.refresh(row['id'], {'candidates': [{'sense_id': 'new-a'}, {'sense_id': 'new-b'}]})
        saved = self.db.get(row['id'])
        self.assertIsNone(saved['ipa'])
        self.assertIsNone(saved['audio_file'])
        self.assertIsNone(saved['sense_id'])

    def test_failed_refresh_preserves_previous_candidates(self):
        row, _ = self.db.add('Hund', {'candidates': [{'sense_id': 'a'}], 'ipa': 'hʊnt'})
        self.db.refresh(row['id'], {'candidates': []})
        self.assertEqual(json.loads(self.db.get(row['id'])['candidates_json']), [{'sense_id': 'a'}])
        self.assertEqual(self.db.get(row['id'])['ipa'], 'hʊnt')

    def test_retry_same_sense_preserves_audio_and_change_invalidates_review(self):
        candidates = [{'sense_id': 'a', 'ipa': 'a'}, {'sense_id': 'b', 'ipa': 'b'}]
        row, _ = self.db.add('Band', {'sense_id': 'a', 'ipa': 'a', 'audio_file': 'a.ogg', 'candidates': candidates, 'chinese_meaning': '一', 'meaning_reviewed': True})
        same = self.db.select_sense(row['id'], 'a')
        self.assertEqual(same['audio_file'], 'a.ogg')
        changed = self.db.select_sense(row['id'], 'b')
        self.assertFalse(changed['meaning_reviewed'])
        self.assertEqual(changed['chinese_meaning'], '一')

    def test_refresh_same_source_preserves_audio_when_network_audio_fails(self):
        candidate = {'sense_id': 'a', 'ipa': 'a'}
        row, _ = self.db.add('Hund', {'sense_id': 'a', 'ipa': 'a', 'audio_file': 'a.ogg', 'candidates': [candidate]})
        self.db.refresh(row['id'], {'sense_id': 'a', 'ipa': 'a', 'candidates': [candidate]})
        self.assertEqual(self.db.get(row['id'])['audio_file'], 'a.ogg')

    def test_select_chinese_candidate_preserves_source_and_requires_review(self):
        row, _ = self.db.add('Bank', {'meaning_candidates': [{'text': '银行', 'source': 'Wiktionary (zh)'}, {'text': '长椅', 'source': 'Wiktionary (zh)'}]})
        selected = self.db.select_meaning(row['id'], 1)
        self.assertEqual(selected['chinese_meaning'], '长椅')
        self.assertEqual(selected['meaning_source'], 'Wiktionary (zh)')
        self.assertFalse(selected['meaning_reviewed'])
        self.db.refresh(row['id'], {'chinese_meaning': 'wrong'})
        self.assertEqual(self.db.get(row['id'])['chinese_meaning'], '长椅')

    def test_lookup_failure_details_persist_after_reopen_and_refresh(self):
        fields = {'lookup_status': 'failed', 'lookup_checked_at': '2026-10-25T00:00:00Z', 'lookup_warnings': ['词典连接超时，请检查代理。']}
        row, _ = self.db.add('wasser', fields)
        reopened = Store(self.path).get(row['id'])
        self.assertEqual(reopened['lookup_status'], 'failed')
        self.assertEqual(json.loads(reopened['lookup_warnings_json']), fields['lookup_warnings'])
        self.db.refresh(row['id'], {'dictionary_word': 'Wasser', 'chinese_meaning': '水', 'lookup_status': 'partial', 'lookup_warnings': ['暂无录音。']})
        saved = self.db.get(row['id'])
        self.assertEqual(saved['word'], 'wasser')
        self.assertEqual(saved['dictionary_word'], 'Wasser')
        self.assertEqual(saved['chinese_meaning'], '水')
        self.assertEqual(saved['lookup_status'], 'partial')


class ServiceTests(unittest.TestCase):
    def test_duplicate_does_not_query_network(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Store(Path(folder) / 'v.db')
            store.add('Wasser')
            provider = Mock()
            service = Vocabulary(store, provider)
            row, added, warnings = service.add('wasser')
            self.assertFalse(added)
            provider.lookup.assert_not_called()

    def test_network_failure_still_saves_word(self):
        with tempfile.TemporaryDirectory() as folder:
            provider = Mock()
            provider.lookup.side_effect = OSError('offline')
            row, added, warnings = Vocabulary(Store(Path(folder) / 'v.db'), provider).add('Hund')
            self.assertTrue(added)
            self.assertEqual(row['word'], 'Hund')
            self.assertIsNone(row['chinese_meaning'])
            self.assertTrue(warnings)

    def test_ambiguous_results_are_saved_without_arbitrary_selection(self):
        with tempfile.TemporaryDirectory() as folder:
            provider = Mock()
            provider.lookup.return_value = ({'candidates': [{'sense_id': 'a', 'article': 'der'}, {'sense_id': 'b', 'article': 'das'}]}, [])
            row, _, _ = Vocabulary(Store(Path(folder) / 'v.db'), provider).add('Band')
            self.assertIsNone(row['article'])
            self.assertIsNone(row['sense_id'])
            self.assertEqual(len(json.loads(row['candidates_json'])), 2)


if __name__ == '__main__':
    unittest.main()
