"""Local vocabulary persistence and orchestration. Network-free storage API."""
from __future__ import annotations

import json
import logging
import sqlite3
import time
import unicodedata
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

LOGGER = logging.getLogger(__name__)
BASE_DIR = Path(__file__).resolve().parent
DEFAULT_DB = BASE_DIR / 'data' / 'vocab.db'
DEFAULT_AUDIO = BASE_DIR / 'data' / 'audio'

COLUMNS = {
    'word': 'TEXT', 'word_key': 'TEXT', 'ipa': 'TEXT', 'audio_file': 'TEXT',
    'audio_kind': 'TEXT', 'audio_url': 'TEXT', 'audio_license': 'TEXT',
    'attribution': 'TEXT', 'source_url': 'TEXT', 'note': 'TEXT',
    'created_at': 'TEXT', 'part_of_speech': 'TEXT', 'article': 'TEXT',
    'chinese_meaning': 'TEXT', 'meaning_source': 'TEXT',
    'meaning_reviewed': 'INTEGER DEFAULT 0', 'meaning_candidates_json': "TEXT DEFAULT '[]'",
    'candidates_json': "TEXT DEFAULT '[]'", 'sense_id': 'TEXT', 'sense': 'TEXT',
    'confidence': 'TEXT', 'manual_fields_json': "TEXT DEFAULT '[]'",
    'updated_at': 'TEXT', 'sync_status': 'TEXT', 'synced_at': 'TEXT',
    'dictionary_word': 'TEXT', 'lookup_status': 'TEXT', 'lookup_checked_at': 'TEXT',
    'lookup_warnings_json': "TEXT DEFAULT '[]'",
}
EDITABLE = {'ipa', 'part_of_speech', 'article', 'chinese_meaning', 'meaning_reviewed', 'note'}
LEXICAL = {'ipa', 'part_of_speech', 'article', 'sense_id', 'sense', 'confidence', 'source_url', 'dictionary_word'}
AUDIO = {'audio_file', 'audio_kind', 'audio_url', 'audio_license', 'attribution'}


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def normalize_word(word):
    word = unicodedata.normalize('NFC', word).strip()
    if not word or len(word) > 200 or any(unicodedata.category(c).startswith('C') for c in word):
        raise ValueError('请输入 1–200 个字符的单行德语单词或短语。')
    return word


def noun(pos):
    return bool(pos and any(p in pos.casefold() for p in ('substantiv', '名词', '名詞', 'noun', 'eigenname')))


def prepare(fields):
    fields = dict(fields or {})
    for field, column in [('candidates', 'candidates_json'), ('meaning_candidates', 'meaning_candidates_json'), ('lookup_warnings', 'lookup_warnings_json')]:
        if field in fields:
            fields[column] = json.dumps(fields.pop(field), ensure_ascii=False)
    fields = {k: v for k, v in fields.items() if k in COLUMNS and k not in {'word', 'word_key', 'created_at', 'manual_fields_json'}}
    if 'article' in fields and fields['article']:
        articles = {x.strip() for x in fields['article'].split('/')}
        if not articles <= {'der', 'die', 'das'}:
            raise ValueError('冠词只能为 der、die、das 或以 / 分隔的多个冠词。')
    if 'part_of_speech' in fields and not noun(fields['part_of_speech']):
        fields['article'] = None
    for key in fields:
        if isinstance(fields[key], str) and not fields[key].strip():
            fields[key] = None
    return fields


class Store:
    def __init__(self, path=DEFAULT_DB):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._migrate()

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path, timeout=15)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _migrate(self):
        with self.connect() as conn:
            exists = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='words'").fetchone()
            if exists:
                existing = {r['name'] for r in conn.execute('PRAGMA table_info(words)')}
                if 'id' not in existing or 'word' not in existing:
                    raise ValueError('旧 words 表缺少 id/word；未更改数据库，请先检查原库。')
                if set(COLUMNS) - existing:
                    backup = self.path.with_name(self.path.name + f'.backup-{time.time_ns()}')
                    from contextlib import closing
                    with closing(sqlite3.connect(backup)) as target:
                        conn.backup(target)
                for field, kind in COLUMNS.items():
                    if field not in existing:
                        conn.execute(f'ALTER TABLE words ADD COLUMN {field} {kind}')
                if 'manual_fields_json' not in existing:
                    # Older versions cannot tell machine fields from user edits.
                    # Conservatively protect all populated editable legacy fields.
                    for row in conn.execute('SELECT * FROM words').fetchall():
                        protected = [field for field in EDITABLE if row[field] not in (None, '')]
                        if row['chinese_meaning']:
                            protected.append('meaning_source')
                        conn.execute('UPDATE words SET manual_fields_json=? WHERE id=?', (json.dumps(protected), row['id']))
            else:
                fields = ', '.join(f'{k} {v}' for k, v in COLUMNS.items())
                conn.execute(f'CREATE TABLE words (id INTEGER PRIMARY KEY AUTOINCREMENT, {fields})')
            for row in conn.execute('SELECT id, word FROM words WHERE word_key IS NULL').fetchall():
                key = unicodedata.normalize('NFC', row['word']).strip().casefold()
                conn.execute('UPDATE words SET word_key=? WHERE id=?', (key, row['id']))
            # Nonunique index intentionally preserves duplicates in legacy databases.
            conn.execute('CREATE INDEX IF NOT EXISTS words_key_idx ON words(word_key)')
            conn.execute('CREATE TABLE IF NOT EXISTS query_cache (key TEXT PRIMARY KEY, payload TEXT NOT NULL, saved REAL NOT NULL)')
            conn.execute('CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)')

    def get(self, entry_id):
        with self.connect() as conn:
            row = conn.execute('SELECT * FROM words WHERE id=?', (entry_id,)).fetchone()
            return dict(row) if row else None

    def find(self, word):
        key = normalize_word(word).casefold()
        with self.connect() as conn:
            row = conn.execute('SELECT * FROM words WHERE word_key=? ORDER BY id LIMIT 1', (key,)).fetchone()
            return dict(row) if row else None

    def add(self, word, fields=None):
        word = normalize_word(word)
        values = prepare(fields)
        with self.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            row = conn.execute('SELECT * FROM words WHERE word_key=? ORDER BY id LIMIT 1', (word.casefold(),)).fetchone()
            if row:
                return dict(row), False
            values.update(word=word, word_key=word.casefold(), created_at=now(), updated_at=now())
            columns = ','.join(values)
            marks = ','.join('?' for _ in values)
            cursor = conn.execute(f'INSERT INTO words ({columns}) VALUES ({marks})', list(values.values()))
            entry_id = cursor.lastrowid
        return self.get(entry_id), True

    def _write(self, entry_id, values):
        if values:
            values['updated_at'] = now()
            with self.connect() as conn:
                conn.execute('UPDATE words SET ' + ','.join(f'{k}=?' for k in values) + ' WHERE id=?', [*values.values(), entry_id])
        return self.get(entry_id)

    def update(self, entry_id, **fields):
        if set(fields) - EDITABLE:
            raise ValueError('包含不允许手动编辑的字段。')
        row = self.get(entry_id)
        if not row:
            raise ValueError('词条已不存在。')
        values = prepare(fields)
        pos = values.get('part_of_speech', row['part_of_speech'])
        if not noun(pos):
            values['article'] = None
        manual = set(json.loads(row['manual_fields_json'] or '[]')) | set(values)
        if 'chinese_meaning' in values:
            values['meaning_source'] = '人工校对'
            manual.add('meaning_source')
        if values.get('meaning_reviewed'):
            manual |= {'chinese_meaning', 'meaning_source'}
        values['manual_fields_json'] = json.dumps(sorted(manual))
        return self._write(entry_id, values)

    def refresh(self, entry_id, fields):
        row = self.get(entry_id)
        if not row:
            raise ValueError('词条已不存在。')
        manual = set(json.loads(row['manual_fields_json'] or '[]'))
        values = prepare(fields)
        if 'candidates_json' in values:
            if not json.loads(values['candidates_json'] or '[]'):
                values.pop('candidates_json')
            elif '_selected_sense' not in manual:
                old_ids = {c.get('sense_id') for c in json.loads(row['candidates_json'] or '[]')}
                new_ids = {c.get('sense_id') for c in json.loads(values['candidates_json'])}
                same_source = old_ids == new_ids and row['sense_id'] == values.get('sense_id') and row['ipa'] == values.get('ipa')
                clear = LEXICAL if same_source and not values.get('audio_file') else LEXICAL | AUDIO
                values = {**dict.fromkeys(clear), **values}
        if 'meaning_candidates_json' in values and not json.loads(values['meaning_candidates_json'] or '[]'):
            values.pop('meaning_candidates_json')
        # A refresh offers new candidates, but never silently changes a chosen sense.
        if '_selected_sense' in manual:
            manual |= LEXICAL | AUDIO
        values = {k: v for k, v in values.items() if k not in manual}
        if not noun(values.get('part_of_speech', row['part_of_speech'])):
            values['article'] = None
        return self._write(entry_id, values)

    def select_sense(self, entry_id, sense_id):
        row = self.get(entry_id)
        candidate = next((c for c in json.loads(row['candidates_json'] or '[]') if c['sense_id'] == sense_id), None)
        if not candidate:
            raise ValueError('找不到此义项，请重新查询。')
        fields = {k: candidate.get(k) for k in LEXICAL}
        fields['dictionary_word'] = candidate.get('dictionary_word') or candidate.get('headword') or row.get('dictionary_word') or row['word']
        changed = sense_id != row['sense_id'] or candidate.get('ipa') != row['ipa']
        if changed:
            same_pronunciation = (candidate.get('ipa') and candidate['ipa'] == row['ipa'] and
                                  candidate.get('part_of_speech') == row['part_of_speech'] and
                                  fields['dictionary_word'] == (row.get('dictionary_word') or row['word']))
            if not same_pronunciation:
                fields.update({k: None for k in AUDIO})
            fields['meaning_reviewed'] = False
        manual = set(json.loads(row['manual_fields_json'] or '[]')) | {'_selected_sense'}
        if candidate.get('chinese_meaning') and 'chinese_meaning' not in manual:
            fields.update(chinese_meaning=candidate['chinese_meaning'], meaning_source=candidate.get('meaning_source'), meaning_reviewed=False)
        fields['manual_fields_json'] = json.dumps(sorted(manual))
        # Sense selection is explicit; only freeform edits remain protected on refresh.
        values = prepare(fields)
        values['manual_fields_json'] = fields['manual_fields_json']
        return self._write(entry_id, values)

    def attach_audio(self, entry_id, fields):
        return self._write(entry_id, {k: v for k, v in fields.items() if k in AUDIO})

    def select_meaning(self, entry_id, index):
        row = self.get(entry_id)
        candidates = json.loads(row['meaning_candidates_json'] or '[]')
        if not isinstance(index, int) or not 0 <= index < len(candidates):
            raise ValueError('找不到此中文释义候选。')
        candidate = candidates[index]
        manual = set(json.loads(row['manual_fields_json'] or '[]')) | {'chinese_meaning', 'meaning_source', 'meaning_reviewed'}
        return self._write(entry_id, {'chinese_meaning': candidate['text'], 'meaning_source': candidate.get('source'), 'meaning_reviewed': False, 'manual_fields_json': json.dumps(sorted(manual))})

    def list(self, search=''):
        with self.connect() as conn:
            rows = [dict(row) for row in conn.execute('SELECT * FROM words ORDER BY id DESC')]
        needle = search.casefold().strip()
        return [r for r in rows if not needle or needle in (r['word'] + ' ' + (r['chinese_meaning'] or '')).casefold()]

    def delete(self, entry_id):
        with self.connect() as conn:
            conn.execute('DELETE FROM words WHERE id=?', (entry_id,))

    def cache_get(self, key, max_age=86400 * 7):
        with self.connect() as conn:
            row = conn.execute('SELECT payload,saved FROM query_cache WHERE key=?', (key,)).fetchone()
        if row and time.time() - row['saved'] <= max_age:
            return json.loads(row['payload'])
        return None

    def cache_set(self, key, payload):
        with self.connect() as conn:
            conn.execute('INSERT OR REPLACE INTO query_cache VALUES (?,?,?)', (key, json.dumps(payload, ensure_ascii=False), time.time()))

    def get_setting(self, key, default=''):
        with self.connect() as conn:
            row = conn.execute('SELECT value FROM settings WHERE key=?', (key,)).fetchone()
        return row['value'] if row else default

    def set_setting(self, key, value):
        with self.connect() as conn:
            conn.execute('INSERT OR REPLACE INTO settings VALUES (?,?)', (key, str(value)))

    def sync_result(self, entry_id, message, success=False):
        return self._write(entry_id, {'sync_status': message, 'synced_at': now() if success else None})


class Vocabulary:
    def __init__(self, store, providers):
        self.store, self.providers = store, providers

    def add(self, word, **options):
        word = normalize_word(word)
        existing = self.store.find(word)
        if existing:
            return existing, False, []
        try:
            fields, warnings = self.providers.lookup(word, **options)
        except (OSError, ValueError, TimeoutError) as exc:
            LOGGER.warning('Lookup failed: %s', type(exc).__name__)
            fields, warnings = {}, ['网络查询失败；已保存词条，信息可稍后补充。']
        row, created = self.store.add(word, fields)
        return row, created, warnings
