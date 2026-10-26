"""Offline parser regression tests; fixtures are hand-curated template excerpts."""
import json
from pathlib import Path
import tempfile
import unittest


FIXTURES = json.loads((Path(__file__).parent / 'fixtures' / 'german.json').read_text(encoding='utf-8'))
try:
    import lexicon
except ModuleNotFoundError:
    lexicon = None


class LexiconTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(lexicon, 'The lexicon module has not been implemented')

    def parse(self, word):
        fixture = next(f for f in FIXTURES if f['word'] == word)
        return lexicon.parse_german(word, fixture['text'], 'https://de.wiktionary.org/wiki/' + word)

    def test_representative_template_fixtures(self):
        self.assertGreaterEqual(len(FIXTURES), 20)
        for fixture in FIXTURES:
            with self.subTest(word=fixture['word']):
                rows = self.parse(fixture['word'])
                self.assertTrue(rows)
                if 'articles' in fixture:
                    self.assertEqual([r['article'] for r in rows], fixture['articles'])
                elif 'article' in fixture:
                    self.assertTrue(all(r['article'] == fixture['article'] for r in rows))
                    self.assertTrue(all(r['part_of_speech'] == fixture['pos'] for r in rows))
                    self.assertTrue(all(r['ipa'] == fixture['ipa'] for r in rows))
                if 'ipas' in fixture:
                    self.assertEqual([r['ipa'] for r in rows], fixture['ipas'])

    def test_contract_and_stable_unique_ids(self):
        rows = self.parse('Bank')
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows, self.parse('Bank'))
        self.assertNotEqual(rows[0]['sense_id'], rows[1]['sense_id'])
        self.assertEqual(set(rows[0]), {'sense_id','sense','part_of_speech','article','ipa','audio_files','source_url','confidence','source'})
        self.assertTrue(rows[0]['sense'].startswith('[1]'))
        self.assertEqual(rows[0]['source'], 'Wiktionary (de)')
        self.assertEqual(rows[0]['confidence'], 'dictionary')

    def test_language_and_meaning_boundaries(self):
        rows = self.parse('Café')
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['sense'], '[1] kleines Lokal')
        street = self.parse('Straße')[0]['sense']
        self.assertIn('befestigter Weg', street)
        for unwanted in ('Quelle', 'Beispiel', '{{', '[[', '<ref'):
            self.assertNotIn(unwanted, street)

    def test_pronunciations_stay_in_their_headword_section(self):
        rows = self.parse('umfahren')
        self.assertEqual(rows[0]['audio_files'], ['De-umfahren-trennbar.ogg'])
        self.assertEqual(rows[1]['audio_files'], ['De-umfahren-untrennbar.ogg'])
        self.assertIn('Fall', rows[0]['sense'])
        self.assertIn('herumfahren', rows[1]['sense'])

    def test_ambiguous_pronunciation_not_assigned_to_numbered_meanings(self):
        rows = self.parse('Mutter')
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(r['ipa'] is None and r['audio_files'] == [] for r in rows))

    def test_numbered_pronunciation_mapping(self):
        text = '''== Test ({{Sprache|Deutsch}}) ==
=== {{Wortart|Substantiv|Deutsch}}, {{m}} ===
{{Aussprache}}
:{{IPA}}: [1] {{Lautschrift|a}}, [2] {{Lautschrift|b}}
:{{Hörbeispiele}}: [1] {{Audio|De-a.ogg}}, [2] {{Audio|De-b.ogg}}
{{Bedeutungen}}
:[1] erste Bedeutung
:[2] zweite Bedeutung'''
        rows = lexicon.parse_german('Test', text)
        self.assertEqual([r['ipa'] for r in rows], ['a', 'b'])
        self.assertEqual([r['audio_files'] for r in rows], [['De-a.ogg'], ['De-b.ogg']])

    def test_unlabelled_audio_is_not_attached_to_distinct_mapped_pronunciations(self):
        text = '''== Test ({{Sprache|Deutsch}}) ==
=== {{Wortart|Verb|Deutsch}} ===
{{Aussprache}}
:{{IPA}}: [1] {{Lautschrift|a}}, [2] {{Lautschrift|b}}
:{{Hörbeispiele}}: {{Audio|De-a.ogg}}, {{Audio|De-b.ogg}}
{{Bedeutungen}}
:[1] erstes
:[2] zweites'''
        rows = lexicon.parse_german('Test', text)
        self.assertEqual([r['ipa'] for r in rows], ['a', 'b'])
        self.assertEqual([r['audio_files'] for r in rows], [[], []])

    def test_single_meaning_keeps_alternative_pronunciations(self):
        text = '''== Test ({{Sprache|Deutsch}}) ==
=== {{Wortart|Verb|Deutsch}} ===
{{Aussprache}}
:{{IPA}}: {{Lautschrift|a}}, {{Lautschrift|b}}
:{{Hörbeispiele}}: {{Audio|De-a.ogg}}
{{Bedeutungen}}
:[1] ein Begriff'''
        rows = lexicon.parse_german('Test', text)
        self.assertEqual([r['ipa'] for r in rows], ['a', 'b'])
        self.assertEqual([r['audio_files'] for r in rows], [[], []])

    def test_unknown_and_non_german_return_empty(self):
        for text in ('', 'plain text', '== Hund ({{Sprache|Englisch}}) ==\n{{m}}\n{{Lautschrift|wrong}}'):
            self.assertEqual(lexicon.parse_german('Hund', text), [])

    def test_chinese_german_block_only_and_numbered_glosses(self):
        text = '''==英語==
===名詞===
# 错误语言
==德語==
===名詞===
{{de-noun|n}}
# [[水]]，無色的液體<ref>引用</ref>
# {{lb|de|化學}} 氧化氫
====例句====
# 错误例句
==法語==
# 错误法语'''
        rows = lexicon.parse_chinese('Wasser', text, 'https://zh.wiktionary.org/wiki/Wasser')
        self.assertEqual([r['text'] for r in rows], ['水，無色的液體', '氧化氫'])
        self.assertTrue(all(r['source'] == 'Wiktionary (zh)' for r in rows))
        self.assertTrue(all(r['source_url'].startswith('https://zh.') for r in rows))

    def test_chinese_alternate_language_template_and_bad_markup(self):
        text = '=={{-de-}}==\n===动词===\n# 说话\n# {{unclosed\n# <script>bad()</script>\n=={{-en-}}==\n# 不要'
        self.assertEqual([r['text'] for r in lexicon.parse_chinese('sprechen', text)], ['说话'])
        self.assertEqual(lexicon.parse_chinese('Wasser', '==德語==\n#REDIRECT [[水]]'), [])

    def test_chinese_glosses_allow_compact_number_markers(self):
        text = '==德语==\n===名词===\n#{{lb|de|化学}} [[水]]\n#:这是一条例句\n#*另一条例句'
        self.assertEqual([r['text'] for r in lexicon.parse_chinese('Wasser', text)], ['水'])

    def test_local_kaikki_streams_matching_entries_and_preserves_provenance(self):
        objects = [
            {'word':'Bank','lang_code':'en','pos':'noun','senses':[{'glosses':['wrong']}]},
            {'word':'bank','lang_code':'de','pos':'noun','senses':[{'glosses':['wrong case']}]},
            {'word':'Bank','lang_code':'de','pos':'noun','tags':['feminine'],'sounds':[{'ipa':'baŋk'}], 'senses':[{'glosses':['financial institution']}]},
        ]
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent / 'fixtures') as directory:
            path = Path(directory) / 'local.jsonl'
            path.write_text('\n'.join(json.dumps(o) for o in objects) + '\nnot JSON\n', encoding='utf-8')
            rows = lexicon.read_kaikki('Bank', path)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['article'], 'die')
        self.assertEqual(rows[0]['ipa'], 'baŋk')
        self.assertIn('Kaikki', rows[0]['source'])
        self.assertIn('license', rows[0])
        self.assertEqual(rows[0]['sense'], 'financial institution')


if __name__ == '__main__':
    unittest.main()
