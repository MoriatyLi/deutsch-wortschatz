import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from providers import HttpClient, Providers, valid_translation, validate_audio_url


class ProviderTests(unittest.TestCase):
    def test_lowercase_noun_retries_dictionary_capitalization_and_keeps_input(self):
        with tempfile.TemporaryDirectory() as folder:
            http = Mock()
            http.page.side_effect = ['', '== Wasser ({{Sprache|Deutsch}}) ==\n=== {{Wortart|Substantiv|Deutsch}}, {{n}} ===\n{{Aussprache}}\n:{{IPA}} {{Lautschrift|ˈvasɐ}}\n{{Bedeutungen}}\n:[1] Flüssigkeit', '==德語==\n===名詞===\n# 水']
            fields, warnings = Providers(folder, http=http).lookup('wasser')
            self.assertEqual(fields['dictionary_word'], 'Wasser')
            self.assertEqual(fields['article'], 'das')
            self.assertEqual(fields['ipa'], 'ˈvasɐ')
            self.assertEqual(fields['chinese_meaning'], '水')
            self.assertEqual(http.page.call_args_list[0].args, ('de', 'wasser'))
            self.assertEqual(http.page.call_args_list[1].args, ('de', 'Wasser'))
            self.assertEqual(http.page.call_args_list[2].args, ('zh', 'Wasser'))
            self.assertIn('Wasser', fields['source_url'])
            self.assertTrue(any('Wasser' in warning for warning in warnings))

    def test_timeout_is_recorded_with_actionable_status(self):
        from urllib.error import URLError
        with tempfile.TemporaryDirectory() as folder:
            http = Mock()
            http.page.side_effect = URLError(TimeoutError('TLS handshake timed out'))
            http.json.side_effect = URLError(TimeoutError('TLS handshake timed out'))
            fields, warnings = Providers(folder, http=http).lookup('wasser')
            self.assertEqual(fields['lookup_status'], 'failed')
            self.assertIsNone(fields.get('chinese_meaning'))
            self.assertTrue(fields['lookup_checked_at'])
            self.assertEqual(fields['lookup_warnings'], warnings)
            self.assertTrue(any('超时' in warning for warning in warnings))
            self.assertTrue(any('代理' in warning for warning in warnings))

    def test_exact_verb_does_not_try_capitalized_noun(self):
        with tempfile.TemporaryDirectory() as folder:
            http = Mock()
            http.page.side_effect = ['== sprechen ({{Sprache|Deutsch}}) ==\n=== {{Wortart|Verb|Deutsch}} ===\n{{Bedeutungen}}\n:[1] reden', '==德語==\n===動詞===\n# 说话']
            fields, _ = Providers(folder, http=http).lookup('sprechen')
            self.assertEqual(fields['dictionary_word'], 'sprechen')
            self.assertEqual(http.page.call_count, 2)
            self.assertIsNone(fields['article'])

    def test_translation_quota_errors_are_not_glosses(self):
        bad = [None, {}, {'responseStatus': 429, 'responseData': {'translatedText': 'QUOTA EXCEEDED'}}, {'responseStatus': 200, 'responseData': {'translatedText': 'MYMEMORY WARNING: YOU USED ALL AVAILABLE FREE TRANSLATIONS FOR TODAY'}}, {'responseStatus': 200, 'responseData': {'translatedText': 'Wasser'}}]
        for payload in bad:
            with self.subTest(payload=payload):
                self.assertIsNone(valid_translation(payload, 'Wasser'))
        self.assertEqual(valid_translation({'responseStatus': 200, 'responseData': {'translatedText': '水'}}, 'Wasser'), '水')

    def test_audio_url_allowlist(self):
        for url in ['http://upload.wikimedia.org/a.ogg', 'https://upload.wikimedia.org.evil.test/a.ogg', 'https://user@upload.wikimedia.org/a.ogg', 'https://127.0.0.1/a.ogg', 'https://upload.wikimedia.org:444/a.ogg']:
            with self.subTest(url=url), self.assertRaises(ValueError):
                validate_audio_url(url)
        validate_audio_url('https://upload.wikimedia.org/wikipedia/commons/a/a1/De-Wasser.ogg')

    def test_chinese_dictionary_precedes_machine_translation(self):
        with tempfile.TemporaryDirectory() as folder:
            http = Mock()
            http.page.side_effect = ['== Wasser ({{Sprache|Deutsch}}) ==\n=== {{Wortart|Substantiv|Deutsch}}, {{n}} ===\n{{Bedeutungen}}\n:[1] Flüssigkeit', '==德語==\n===名詞===\n# 水']
            fields, warnings = Providers(Path(folder), http=http).lookup('Wasser')
            self.assertEqual(fields['chinese_meaning'], '水')
            self.assertFalse(fields['meaning_reviewed'])
            self.assertIn('Wiktionary', fields['meaning_source'])
            http.json.assert_not_called()

    def test_all_sources_fail_without_losing_entry_or_error_as_translation(self):
        with tempfile.TemporaryDirectory() as folder:
            http = Mock()
            http.page.side_effect = OSError('offline')
            http.json.side_effect = TimeoutError('timeout')
            fields, warnings = Providers(Path(folder), http=http).lookup('unknown')
            self.assertIsNone(fields.get('chinese_meaning'))
            self.assertGreaterEqual(len(warnings), 2)

    def test_consensus_pronunciation_does_not_choose_a_meaning(self):
        with tempfile.TemporaryDirectory() as folder:
            provider = Providers(folder, http=Mock())
            candidate = {'article': 'das', 'part_of_speech': 'Substantiv', 'ipa': 'vasɐ', 'audio_files': ['De-Wasser.ogg']}
            with unittest.mock.patch('providers.parse_german', return_value=[dict(candidate, sense_id='1'), dict(candidate, sense_id='2')]), unittest.mock.patch('providers.parse_chinese', return_value=[]):
                provider.http.page.return_value = ''
                provider.http.json.return_value = {}
                provider.audio = Mock(return_value=({'audio_file': 'water.ogg'}, []))
                fields, _ = provider.lookup('Wasser')
            self.assertIsNone(fields.get('sense_id'))
            self.assertEqual(fields['article'], 'das')
            self.assertEqual(fields['ipa'], 'vasɐ')
            self.assertEqual(fields['audio_file'], 'water.ogg')

    def test_malformed_page_response_is_rejected(self):
        http = HttpClient(min_interval=0)
        http.json = Mock(return_value={'query': []})
        with self.assertRaises(ValueError):
            http.page('de', 'Wasser')

    def test_malformed_commons_and_null_license_do_not_download(self):
        for page in [None, {'imageinfo': [None]}, {'imageinfo': [{'url': 'https://upload.wikimedia.org/a.ogg', 'extmetadata': None}]}, {'imageinfo': [{'url': 'https://upload.wikimedia.org/a.ogg', 'extmetadata': {'LicenseShortName': {'value': None}}}]}]:
            with self.subTest(page=page), tempfile.TemporaryDirectory() as folder:
                http = Mock()
                http.json.return_value = {'query': {'pages': [page]}}
                fields, warnings = Providers(folder, http=http).audio('Hund', {'audio_files': ['De-Hund.ogg']})
                self.assertFalse(fields)
                self.assertTrue(warnings)
                http.download.assert_not_called()

    def test_audio_oversize_and_html_rejected_without_partial_file(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / 'audio.ogg'
            client = HttpClient(min_interval=0)
            response = Mock()
            response.headers = {'Content-Type': 'text/html', 'Content-Length': '30'}
            response.read.return_value = b'<html>error</html>'
            response.__enter__ = Mock(return_value=response)
            response.__exit__ = Mock(return_value=False)
            client.open = Mock(return_value=response)
            with self.assertRaises(ValueError):
                client.download('https://upload.wikimedia.org/a.ogg', target)
            self.assertFalse(target.exists())
            response.headers = {'Content-Type': 'audio/ogg', 'Content-Length': str(16 * 1024 * 1024)}
            with self.assertRaises(ValueError):
                client.download('https://upload.wikimedia.org/a.ogg', target)
            self.assertFalse(target.exists())


if __name__ == '__main__':
    unittest.main()
