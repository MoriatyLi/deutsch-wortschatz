import concurrent.futures
from pathlib import Path
import socket
import sys
import tempfile
import unittest
from unittest.mock import patch
import wave

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))
from offline_tts import generate, ensure_audio, fill_missing, available, DEFAULT_SPEECH_PATH
from vocab import Store

SPEECH = DEFAULT_SPEECH_PATH


class OfflineSpeechTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    @unittest.skipUnless(available(SPEECH), 'Configure local German speech resources on D: first')
    def test_real_german_synthesis_without_network(self):
        with patch.object(socket.socket, 'connect', side_effect=AssertionError('Network forbidden')):
            fields = generate('Geld', self.root / 'audio', SPEECH)
        self.assertEqual(fields['audio_kind'], 'offline_tts')
        self.assertIn('de', fields['attribution'])
        with wave.open(str(self.root / 'audio' / fields['audio_file'])) as sound:
            self.assertEqual(sound.getnchannels(), 1)
            self.assertEqual(sound.getsampwidth(), 2)
            self.assertGreater(sound.getframerate(), 8000)
            self.assertGreater(sound.getnframes(), 1000)
            self.assertTrue(any(sound.readframes(sound.getnframes())))

    @unittest.skipUnless(available(SPEECH), 'Configure local German speech resources on D: first')
    def test_cache_reuses_file_without_regenerating(self):
        first = generate('gelb', self.root, SPEECH)
        path = self.root / first['audio_file']
        timestamp = path.stat().st_mtime_ns
        second = generate('gelb', self.root, SPEECH)
        self.assertEqual(first, second)
        self.assertEqual(path.stat().st_mtime_ns, timestamp)

    def test_missing_engine_and_invalid_input_do_not_create_audio(self):
        with self.assertRaises(FileNotFoundError):
            generate('Geld', self.root, self.root / 'missing-engine')
        for word in ('', 'a' * 201, 'bad\0word'):
            with self.assertRaises(ValueError):
                generate(word, self.root, SPEECH)
        self.assertFalse(list(self.root.glob('*.wav')))

    def test_existing_human_audio_is_preserved(self):
        store = Store(self.root / 'words.db')
        audio = self.root / 'audio'
        audio.mkdir()
        original = b'OggS' + b'original-recording' * 10
        (audio / 'original.ogg').write_bytes(original)
        row, _ = store.add('Wasser', {'audio_file': 'original.ogg', 'audio_kind': 'human'})
        with patch('offline_tts.generate', side_effect=AssertionError('Must preserve recording')):
            result, changed = ensure_audio(store, row, audio, SPEECH)
        self.assertFalse(changed)
        self.assertEqual(result['audio_kind'], 'human')
        self.assertEqual((audio / 'original.ogg').read_bytes(), original)

    @unittest.skipUnless(available(SPEECH), 'Configure local German speech resources on D: first')
    def test_backfills_existing_words_and_is_idempotent(self):
        store = Store(self.root / 'words.db')
        for word in ('Geld', 'gelb', 'Kappe'):
            store.add(word)
        count, errors = fill_missing(store, self.root / 'audio', SPEECH)
        self.assertEqual((count, errors), (3, []))
        self.assertTrue(all(row['audio_kind'] == 'offline_tts' for row in store.list()))
        self.assertEqual(fill_missing(store, self.root / 'audio', SPEECH), (0, []))

    @unittest.skipUnless(available(SPEECH), 'Configure local German speech resources on D: first')
    def test_concurrent_words_produce_valid_separate_audio(self):
        words = ['Wasser', 'Geld', 'gelb', 'Kappe']
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            results = list(executor.map(lambda word: generate(word, self.root, SPEECH), words))
        self.assertEqual(len({row['audio_file'] for row in results}), 4)
        for row in results:
            with wave.open(str(self.root / row['audio_file'])) as sound:
                self.assertGreater(sound.getnframes(), 1000)


if __name__ == '__main__':
    unittest.main()
