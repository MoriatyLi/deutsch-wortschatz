import json
from contextlib import closing
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fuzzy_words import suggest


class FuzzyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / 'dictionary.db'
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute('CREATE TABLE entries (word TEXT,payload TEXT)')
            db.execute('CREATE INDEX word_idx ON entries(word)')
            for word, meaning, article in [('Wasser','水','das'),('Wassermelone','西瓜','die'),
                    ('Wasserglas','水杯','das'),('Geld','钱','das'),('gelb','黄色的',''),
                    ('Mädchen','女孩','das'),('schön','美丽的',''),('Straße','街道','die')]:
                payload=json.dumps({'chinese_meaning':meaning,'article':article,'part_of_speech':'Substantiv'},ensure_ascii=False)
                db.execute('INSERT INTO entries VALUES (?,?)',(word,payload))
            db.execute('INSERT INTO entries SELECT * FROM entries WHERE word=?',('Wasser',))

    def test_prefix_prefers_shorter_headword_and_includes_meaning(self):
        results=suggest('wasse',self.db)
        self.assertEqual(results[0]['word'],'Wasser')
        self.assertEqual(results[0]['meaning'],'水')
        self.assertEqual(results[0]['article'],'das')
        self.assertIn('Wassermelone',[row['word'] for row in results])
        self.assertEqual(len({row['word'] for row in results}),len(results))

    def test_typo_and_adjacent_transposition(self):
        for query in ('wssser','wassre','waseer'):
            self.assertIn('Wasser',[row['word'] for row in suggest(query,self.db)])

    def test_german_transliterations(self):
        for query,expected in [('maedchen','Mädchen'),('schoen','schön'),('strasse','Straße')]:
            self.assertEqual(suggest(query,self.db)[0]['word'],expected)

    def test_exact_match_first_and_result_limit(self):
        self.assertEqual(suggest('gelb',self.db)[0]['word'],'gelb')
        self.assertLessEqual(len(suggest('w',self.db,limit=2)),2)

    def test_empty_wildcard_and_long_input(self):
        for query in ('',' ', '%', '_', 'x'*201):
            self.assertEqual(suggest(query,self.db),[])

    def test_dictionary_is_read_only(self):
        before=self.db.read_bytes()
        suggest('wasse',self.db)
        self.assertEqual(self.db.read_bytes(),before)


if __name__=='__main__':
    unittest.main()
