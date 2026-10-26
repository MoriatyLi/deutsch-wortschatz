"""Build an independent, indexed local dictionary without touching user words."""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import tempfile
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

FORMAT = 'DeutschWortschatzOffline/1'
POS = {'noun': 'Substantiv', 'name': 'Eigenname', 'verb': 'Verb', 'adj': 'Adjektiv',
       'adv': 'Adverb', 'pron': 'Pronomen', 'prep': 'Präposition', 'conj': 'Konjunktion',
       'intj': 'Interjektion', 'num': 'Numerale', 'article': 'Artikel', 'phrase': 'Wendung'}
GENDERS = {'masculine': 'der', 'feminine': 'die', 'neuter': 'das',
           'm': 'der', 'f': 'die', 'n': 'das', '阳性': 'der', '陽性': 'der',
           '阴性': 'die', '陰性': 'die', '中性': 'das',
           '阳': 'der', '陽': 'der', '阴': 'die', '陰': 'die', '中': 'das'}


def strings(value):
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


def candidates_from_entry(item, language='zh'):
    if not isinstance(item, dict) or item.get('lang_code') != 'de' or not isinstance(item.get('word'), str):
        return []
    word = item['word'].strip()
    if not word:
        return []
    source = f'Kaikki / Wiktionary ({language}, offline)'
    source_url = item.get('source_url') or f'https://{language}.wiktionary.org/wiki/' + quote(word, safe='')
    senses = item.get('senses')
    senses = [sense for sense in senses if isinstance(sense, dict)] if isinstance(senses, list) else []
    senses = senses or [{}]
    result = []
    pos = POS.get(item.get('pos'), item.get('pos'))
    for index, sense in enumerate(senses):
        tags = set(strings(item.get('tags')) + strings(item.get('raw_tags')) + strings(item.get('genders')) + strings(sense.get('tags')) + strings(sense.get('raw_tags')))
        # Explicit grammatical gender in a headword template is evidence too.
        for template in item.get('head_templates', []) if isinstance(item.get('head_templates'), list) else []:
            if isinstance(template, dict) and template.get('name') == 'de-noun' and isinstance(template.get('args'), dict):
                gender = template['args'].get('1')
                if isinstance(gender, str) and gender in GENDERS:
                    tags.add(gender)
        articles = {GENDERS[tag] for tag in tags if tag in GENDERS}
        article = ' / '.join(a for a in ('der', 'die', 'das') if a in articles) if pos == 'Substantiv' else None
        glosses = strings(sense.get('glosses')) or strings(sense.get('raw_glosses'))
        glosses = [g.strip() for g in glosses if g.strip()]
        for gloss in glosses:
            marker = re.match(r'^\s*[〈<【〔]\s*([阳陽阴陰中])\s*[〉>】〕]', gloss)
            if marker:
                articles.add(GENDERS[marker[1] + '性'])
        if pos == 'Substantiv':
            article = ' / '.join(a for a in ('der', 'die', 'das') if a in articles) or None
        chinese = '；'.join(g for g in glosses if re.search(r'[\u3400-\u9fff]', g)) or None
        sounds = sense.get('sounds', item.get('sounds', []))
        sounds = [s for s in sounds if isinstance(s, dict)] if isinstance(sounds, list) else []
        ipas = list(dict.fromkeys(s['ipa'].strip(' /[]') for s in sounds if isinstance(s.get('ipa'), str) and s['ipa'].strip(' /[]')))
        # Unmapped alternative pronunciations are preserved but not assigned.
        complete_ipas = [value for value in ipas if not value.startswith('-') and not value.endswith('-')]
        ipa = complete_ipas[0] if len(complete_ipas) == 1 else None
        identity = json.dumps([language, word, pos, index, glosses, article, ipas], ensure_ascii=False)
        result.append({
            'sense_id': 'offline-' + hashlib.sha256(identity.encode()).hexdigest()[:24],
            'headword': word, 'dictionary_word': word, 'sense': '；'.join(glosses),
            'part_of_speech': pos, 'article': article or None, 'ipa': ipa,
            'pronunciations': ipas, 'audio_files': [], 'chinese_meaning': chinese,
            'meaning_source': source if chinese else None, 'source': source,
            'source_url': source_url, 'confidence': 'dictionary',
            'license': item.get('license') or 'Wiktionary CC BY-SA/GFDL; see source page and supplied dataset attribution',
        })
    return result


def build_index(jsonl_path, db_path, language='zh'):
    sources = [Path(path) for path in jsonl_path] if isinstance(jsonl_path, (list, tuple)) else [Path(jsonl_path)]
    destination = Path(db_path)
    if not sources or any(source.resolve() == destination.resolve() for source in sources):
        raise ValueError('索引路径不能覆盖词典源文件。')
    if destination.is_symlink():
        raise ValueError('词典索引不能写入符号链接。')
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix='.dictionary-', suffix='.db', dir=destination.parent)
    os.close(descriptor)
    temporary = Path(name)
    digest = hashlib.sha256()
    skipped = 0
    try:
        with closing(sqlite3.connect(temporary)) as conn:
            conn.execute('CREATE TABLE entries (sense_id TEXT PRIMARY KEY, word TEXT NOT NULL, payload TEXT NOT NULL)')
            conn.execute('CREATE INDEX word_idx ON entries(word)')
            conn.execute('CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
            for source in sources:
                with source.open('rb') as handle:
                    for line in handle:
                        digest.update(line)
                        try:
                            item = json.loads(line.decode('utf-8-sig'))
                            candidates = candidates_from_entry(item, language)
                        except (ValueError, UnicodeError, TypeError):
                            candidates = []
                        if not candidates:
                            skipped += 1
                            continue
                        for candidate in candidates:
                            conn.execute('INSERT OR IGNORE INTO entries VALUES (?,?,?)', (candidate['sense_id'], candidate['headword'], json.dumps(candidate, ensure_ascii=False)))
            entries, words = conn.execute('SELECT COUNT(*), COUNT(DISTINCT word) FROM entries').fetchone()
            if not entries:
                raise ValueError('文件中没有可导入的德语词条；旧索引保持不变。')
            metadata = {'format': FORMAT, 'entries': entries, 'words': words, 'skipped': skipped,
                        'source_sha256': digest.hexdigest(), 'source_file': sources[0].name if len(sources) == 1 else [source.name for source in sources],
                        'source_language': language, 'created_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
                        'source': 'https://kaikki.org/zhwiktionary/' if language == 'zh' else 'https://kaikki.org/dewiktionary/',
                        'license': 'See the actual Wiktionary/Kaikki source notice; retain attribution and share-alike requirements'}
            conn.executemany('INSERT INTO metadata VALUES (?,?)', [(key, json.dumps(value, ensure_ascii=False)) for key, value in metadata.items()])
            conn.commit()
        os.replace(temporary, destination)
        return metadata
    finally:
        temporary.unlink(missing_ok=True)


def _connect(path):
    path = Path(path)
    if not path.is_file():
        raise ValueError('本地词典索引不存在，请先导入词典。')
    return sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)


def stats(db_path):
    try:
        with closing(_connect(db_path)) as conn:
            metadata = {key: json.loads(value) for key, value in conn.execute('SELECT key,value FROM metadata')}
        if metadata.get('format') != FORMAT:
            raise ValueError('这不是本工具的离线词典索引。')
        return metadata
    except sqlite3.Error as exc:
        raise ValueError('无法读取本地词典索引。') from exc


def lookup(word, db_path):
    stats(db_path)
    variants = [word]
    if word and word.isalpha() and word[0].islower():
        variants.append(word[0].upper() + word[1:])
    candidates, matched = [], []
    with closing(_connect(db_path)) as conn:
        for variant in dict.fromkeys(variants):
            rows = conn.execute('SELECT payload FROM entries WHERE word=? ORDER BY rowid', (variant,)).fetchall()
            if rows:
                matched.append(variant)
                candidates.extend(json.loads(row[0]) for row in rows)
    meanings = [{'text': c['chinese_meaning'], 'source': c['meaning_source'], 'source_url': c['source_url'], 'sense_id': c['sense_id']} for c in candidates if c.get('chinese_meaning')]
    return {'candidates': candidates, 'meaning_candidates': meanings, 'dictionary_word': matched[0] if len(matched) == 1 else word}
