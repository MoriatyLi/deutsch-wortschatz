import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    from streamlit.testing.v1 import AppTest
except ImportError:
    AppTest = None


@unittest.skipIf(AppTest is None, 'Install requirements.txt for Streamlit UI tests')
class AppTests(unittest.TestCase):
    def test_choose_word_table_path_and_auto_update_preserves_personal_notes(self):
        from vocab import Store
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'DEUTSCH_VOCAB_DATA_DIR': folder}), patch('logging.basicConfig'):
            root = Path(folder)
            vault = root / '我的 Vault'
            (vault / '.obsidian').mkdir(parents=True)
            destination = vault / '德语单词.md'
            store = Store(root / 'vocab.db')
            store.set_setting('online', '0')
            script = str(Path(__file__).resolve().parents[1] / 'app.py')
            app = AppTest.from_file(script, default_timeout=15).run()
            app.text_input(key='word_table_path_input').set_value(str(destination))
            app.checkbox(key='auto_save_word_table_input').check()
            app.button(key='save_word_table').click().run()
            self.assertFalse(app.exception)
            self.assertEqual(store.get_setting('word_table_path'), str(destination))
            destination.write_bytes(destination.read_bytes() + '\n我的手写笔记\n'.encode())
            app.text_input(key='new_word').set_value('Wasser')
            app.button(key='add_word').click().run()
            app.text_area(key='edit_meaning').set_value('水')
            app.button(key='save_entry').click().run()
            self.assertFalse(app.exception)
            self.assertIn('Wasser', destination.read_text('utf-8'))
            self.assertIn('水', destination.read_text('utf-8'))
            self.assertTrue(destination.read_text('utf-8').endswith('我的手写笔记\n'))

    def test_local_dictionary_adds_chinese_without_any_http(self):
        import json
        from prepare_offline import activate
        from vocab import Store
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder, patch.dict(os.environ, {'DEUTSCH_VOCAB_DATA_DIR': folder}), patch('logging.basicConfig'):
            root = Path(folder)
            source = root / 'source.jsonl'
            source.write_text(json.dumps({'word': 'Hund', 'lang_code': 'de', 'pos': 'noun', 'tags': ['masculine'], 'sounds': [{'ipa': '/hʊnt/'}], 'senses': [{'glosses': ['狗']}]}, ensure_ascii=False), encoding='utf-8')
            store = Store(root / 'vocab.db')
            activate(source, root / 'dictionary.db', store)
            script = str(Path(__file__).resolve().parents[1] / 'app.py')
            with patch('providers.HttpClient.open', side_effect=AssertionError('HTTP forbidden')) as http:
                app = AppTest.from_file(script, default_timeout=15).run()
                app.text_input(key='new_word').set_value('Hund')
                app.button(key='add_word').click().run()
                self.assertFalse(app.exception)
                self.assertEqual(app.text_area(key='edit_meaning').value, '狗')
                self.assertEqual(app.text_input(key='edit_article').value, 'der')
                self.assertTrue(any('完全离线' in item.value for item in app.success))
                http.assert_not_called()

    def test_query_failure_remains_visible_and_refresh_never_reports_updated(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder, patch.dict(os.environ, {'DEUTSCH_VOCAB_DATA_DIR': folder}), patch('logging.basicConfig'):
            from vocab import Store
            store = Store(Path(folder) / 'vocab.db')
            fields = {'dictionary_word': 'Wasser', 'lookup_status': 'failed', 'lookup_warnings': ['德语词典连接超时；请检查网络或代理。']}
            store.add('wasser', fields)
            script = str(Path(__file__).resolve().parents[1] / 'app.py')
            app = AppTest.from_file(script, default_timeout=15).run()
            self.assertFalse(app.exception)
            self.assertTrue(app.error)
            self.assertIn('自动补全失败', app.error[0].value)
            refresh = next(button for button in app.button if button.label == '重新查询（保留人工修改）')
            with patch('providers.Providers.lookup', return_value=(fields, fields['lookup_warnings'])) as lookup:
                refresh.click().run()
                self.assertEqual(lookup.call_args.args[0], 'Wasser')
            self.assertFalse(app.exception)
            self.assertTrue(any('自动补全未成功' in message.value for message in app.info))
            self.assertFalse(any('查询已更新' in message.value for message in app.success))

    def test_offline_add_edit_duplicate_reopen_and_csv(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder, patch.dict(os.environ, {'DEUTSCH_VOCAB_DATA_DIR': folder}), patch('logging.basicConfig'):
            from vocab import Store
            Store(Path(folder) / 'vocab.db').set_setting('online', '0')
            script = str(Path(__file__).resolve().parents[1] / 'app.py')
            app = AppTest.from_file(script, default_timeout=15).run()
            self.assertFalse(app.exception)
            app.text_input(key='new_word').set_value('Wasser')
            app.button(key='add_word').click().run()
            self.assertFalse(app.exception)
            self.assertEqual(len(Store(Path(folder) / 'vocab.db').list()), 1)
            app.text_area(key='edit_meaning').set_value('水')
            app.text_input(key='edit_pos').set_value('Substantiv')
            app.text_input(key='edit_article').set_value('das')
            app.checkbox(key='edit_reviewed').check()
            app.button(key='save_entry').click().run()
            self.assertFalse(app.exception)
            row = Store(Path(folder) / 'vocab.db').find('Wasser')
            self.assertEqual(row['chinese_meaning'], '水')
            self.assertEqual(row['article'], 'das')
            self.assertTrue(row['meaning_reviewed'])
            app.text_input(key='new_word').set_value('Hund')
            app.button(key='add_word').click().run()
            self.assertFalse(app.exception)
            self.assertEqual(app.text_area(key='edit_meaning').value, '')
            app.text_input(key='new_word').set_value('Wasser')
            app.button(key='add_word').click().run()
            self.assertEqual(app.text_area(key='edit_meaning').value, '水')
            app.text_input(key='new_word').set_value('WASSER')
            app.button(key='add_word').click().run()
            self.assertFalse(app.exception)
            self.assertEqual(len(Store(Path(folder) / 'vocab.db').list()), 2)
            reopened = AppTest.from_file(script, default_timeout=15).run()
            reopened.selectbox(key='entry_picker').select(row['id']).run()
            self.assertEqual(reopened.text_area(key='edit_meaning').value, '水')
            self.assertFalse(reopened.exception)


if __name__ == '__main__':
    unittest.main()
