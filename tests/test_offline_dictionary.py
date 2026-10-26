import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from offline_dictionary import build_index, lookup, stats
from providers import Providers
from vocab import Store


DATA = [
    {'word': 'Wasser', 'lang_code': 'de', 'pos': 'noun', 'tags': ['neuter'], 'sounds': [{'ipa': 'ˈvasɐ'}], 'senses': [{'glosses': ['水']}, {'glosses': ['水域']}]},
    {'word': 'Hund', 'lang_code': 'de', 'pos': 'noun', 'tags': ['masculine'], 'sounds': [{'ipa': 'hʊnt'}], 'senses': [{'glosses': ['狗']}]},
    {'word': 'Mädchen', 'lang_code': 'de', 'pos': 'noun', 'tags': ['neuter'], 'senses': [{'glosses': ['女孩']}]},
    {'word': 'sprechen', 'lang_code': 'de', 'pos': 'verb', 'sounds': [{'ipa': 'ˈʃpʁɛçn̩'}], 'senses': [{'glosses': ['说话']}]},
    {'word': 'schön', 'lang_code': 'de', 'pos': 'adj', 'senses': [{'glosses': ['美丽的']}]},
    {'word': 'Zahnarzt', 'lang_code': 'de', 'pos': 'noun', 'tags': ['masculine'], 'senses': [{'glosses': ['牙医']}]},
    {'word': 'Bank', 'lang_code': 'de', 'pos': 'noun', 'senses': [{'tags': ['feminine'], 'glosses': ['银行']}, {'tags': ['feminine'], 'glosses': ['长椅']}]},
    {'word': 'Joghurt', 'lang_code': 'de', 'pos': 'noun', 'tags': ['masculine', 'neuter'], 'senses': [{'glosses': ['酸奶']}]},
    {'word': 'wasser', 'lang_code': 'de', 'pos': 'verb', 'tags': ['form-of'], 'senses': [{'glosses': ['wassern 的变位形式']}]},
    {'word': 'Water', 'lang_code': 'en', 'pos': 'noun', 'senses': [{'glosses': ['wrong language']}]},
]


class OfflineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.root = Path(self.tmp.name)
        self.source, self.index = self.root / 'source.jsonl', self.root / 'dictionary.db'
        self.source.write_text('\n'.join(json.dumps(item, ensure_ascii=False) for item in DATA) + '\ninvalid JSON\n', encoding='utf-8')

    def tearDown(self):
        self.tmp.cleanup()

    def test_build_index_filters_languages_and_reuses_without_source(self):
        result = build_index(self.source, self.index)
        self.assertEqual(result['words'], 9)
        self.assertEqual(result['skipped'], 2)
        self.source.unlink()
        found = lookup('Hund', self.index)
        self.assertEqual(found['candidates'][0]['article'], 'der')
        self.assertEqual(found['meaning_candidates'][0]['text'], '狗')
        self.assertEqual(stats(self.index)['words'], 9)

    def test_meanings_genders_and_pronunciations_preserve_senses(self):
        build_index(self.source, self.index)
        water = lookup('Wasser', self.index)
        self.assertEqual(len(water['candidates']), 2)
        self.assertTrue(all(c['article'] == 'das' for c in water['candidates']))
        self.assertEqual(lookup('Joghurt', self.index)['candidates'][0]['article'], 'der / das')
        bank = lookup('Bank', self.index)
        self.assertEqual([c['chinese_meaning'] for c in bank['candidates']], ['银行', '长椅'])
        self.assertIsNone(lookup('sprechen', self.index)['candidates'][0]['article'])

    def test_capitalized_noun_and_lowercase_inflection_are_separate_choices(self):
        build_index(self.source, self.index)
        found = lookup('wasser', self.index)
        self.assertEqual({c['headword'] for c in found['candidates']}, {'wasser', 'Wasser'})
        self.assertTrue(any(c['article'] == 'das' for c in found['candidates']))
        noun = lookup('hund', self.index)
        self.assertEqual(noun['dictionary_word'], 'Hund')

    def test_failed_rebuild_never_replaces_working_index(self):
        build_index(self.source, self.index)
        invalid = self.root / 'invalid.jsonl'
        invalid.write_text('not JSON\n', encoding='utf-8')
        with self.assertRaises(ValueError):
            build_index(invalid, self.index)
        self.assertTrue(lookup('Hund', self.index)['candidates'])
        with self.assertRaises(ValueError):
            build_index(self.source, self.source)

    def test_actual_provider_never_calls_network_in_offline_mode(self):
        build_index(self.source, self.index)
        http = Mock()
        http.page.side_effect = AssertionError('Network access is forbidden')
        http.json.side_effect = AssertionError('Network access is forbidden')
        http.download.side_effect = AssertionError('Network access is forbidden')
        store = Store(self.root / 'vocab.db')
        provider = Providers(self.root / 'audio', store, http)
        for word in ['Wasser', 'Hund', 'Mädchen', 'sprechen', 'schön', 'Zahnarzt']:
            with self.subTest(word=word):
                fields, _ = provider.lookup(word, online=False, tts=True, offline_path=self.index)
                self.assertTrue(fields['chinese_meaning'])
                self.assertEqual(fields['lookup_status'], 'offline')
                self.assertIn('Kaikki', fields['meaning_source'])
        fields, warnings = provider.lookup('not-in-dictionary', online=False, offline_path=self.index)
        self.assertFalse(fields.get('chinese_meaning'))
        self.assertTrue(warnings)
        http.page.assert_not_called()
        http.json.assert_not_called()
        http.download.assert_not_called()

    def test_sense_selection_uses_associated_chinese_and_canonical_word(self):
        build_index(self.source, self.index)
        store = Store(self.root / 'vocab.db')
        found = lookup('wasser', self.index)
        row, _ = store.add('wasser', found)
        candidate = next(c for c in found['candidates'] if c['headword'] == 'Wasser' and c['chinese_meaning'] == '水')
        selected = store.select_sense(row['id'], candidate['sense_id'])
        self.assertEqual(selected['dictionary_word'], 'Wasser')
        self.assertEqual(selected['chinese_meaning'], '水')
        self.assertEqual(selected['article'], 'das')
        self.assertFalse(selected['meaning_reviewed'])

    def test_activation_disables_online_features_without_changing_saved_words(self):
        from prepare_offline import activate
        store = Store(self.root / 'vocab.db')
        row, _ = store.add('Wasser', {'chinese_meaning': '我的释义'})
        activate(self.source, self.index, store)
        self.assertEqual(store.get_setting('online'), '0')
        self.assertEqual(store.get_setting('tts'), '0')
        self.assertEqual(store.get(row['id'])['chinese_meaning'], '我的释义')

    def test_slash_ipa_and_existing_recording_are_preserved_offline(self):
        item = dict(DATA[0], sounds=[{'ipa': '/ˈvasɐ/'}])
        self.source.write_text(json.dumps(item, ensure_ascii=False), encoding='utf-8')
        build_index(self.source, self.index)
        audio_root = self.root / 'audio'
        audio_root.mkdir()
        (audio_root / 'water.ogg').write_bytes(b'OggS-local-test')
        store = Store(self.root / 'vocab.db')
        store.add('Wasser', {'ipa': 'ˈvasɐ', 'part_of_speech': 'Substantiv', 'article': 'das', 'audio_file': 'water.ogg', 'audio_kind': 'human', 'audio_license': 'CC BY-SA'})
        fields, _ = Providers(audio_root, store, Mock()).lookup('Wasser', online=False, offline_path=self.index)
        self.assertEqual(fields['audio_file'], 'water.ogg')
        self.assertEqual(fields['ipa'], 'ˈvasɐ')

    def test_multiple_source_files_merge_and_keep_existing_words(self):
        extra = self.root / 'extra.jsonl'
        extra.write_text(json.dumps({'word': 'Baum', 'lang_code': 'de', 'pos': 'noun', 'tags': ['masculine'], 'senses': [{'glosses': ['树']}]}, ensure_ascii=False), encoding='utf-8')
        result = build_index([self.source, extra], self.index)
        self.assertEqual(result['words'], 10)
        self.assertTrue(lookup('Baum', self.index)['candidates'])
        self.assertTrue(lookup('Hund', self.index)['candidates'])

    def test_pronunciation_fragments_are_not_confused_with_full_ipa(self):
        item = {'word': 'sprechen', 'lang_code': 'de', 'pos': 'verb', 'sounds': [{'ipa': '/ˈʃprɛçən/'}, {'ipa': '[ˈʃpʁɛ-]'}, {'ipa': '[-çn̩]'}], 'senses': [{'glosses': ['说话']}]}
        self.source.write_text(json.dumps(item, ensure_ascii=False), encoding='utf-8')
        build_index(self.source, self.index)
        candidate = lookup('sprechen', self.index)['candidates'][0]
        self.assertEqual(candidate['ipa'], 'ˈʃprɛçən')
        self.assertEqual(len(candidate['pronunciations']), 3)

    def test_explicit_chinese_gender_marker_is_dictionary_evidence(self):
        item = {'word': 'Zahnarzt', 'lang_code': 'de', 'pos': 'noun', 'senses': [{'glosses': ['〈阳〉 牙科医生']}]}
        self.source.write_text(json.dumps(item, ensure_ascii=False), encoding='utf-8')
        build_index(self.source, self.index)
        self.assertEqual(lookup('Zahnarzt', self.index)['candidates'][0]['article'], 'der')

    def test_headword_raw_gender_is_used_but_child_form_gender_is_not(self):
        items = [
            {'word': 'Wasser', 'lang_code': 'de', 'pos': 'noun', 'raw_tags': ['中'], 'senses': [{'glosses': ['水']}]},
            {'word': 'Unknown', 'lang_code': 'de', 'pos': 'noun', 'forms': [{'form': 'diminutive', 'raw_tags': ['中']}], 'senses': [{'glosses': ['未知']}]},
        ]
        self.source.write_text('\n'.join(json.dumps(item, ensure_ascii=False) for item in items), encoding='utf-8')
        build_index(self.source, self.index)
        self.assertEqual(lookup('Wasser', self.index)['candidates'][0]['article'], 'das')
        self.assertIsNone(lookup('Unknown', self.index)['candidates'][0]['article'])

    def test_same_word_pronunciation_sense_choice_keeps_downloaded_audio(self):
        build_index(self.source, self.index)
        store = Store(self.root / 'vocab.db')
        found = lookup('Wasser', self.index)
        row, _ = store.add('wasser', dict(found, ipa='ˈvasɐ', part_of_speech='Substantiv', audio_file='water.ogg', audio_kind='human'))
        selected = store.select_sense(row['id'], found['candidates'][1]['sense_id'])
        self.assertEqual(selected['audio_file'], 'water.ogg')
        self.assertEqual(selected['chinese_meaning'], '水域')


if __name__ == '__main__':
    unittest.main()
