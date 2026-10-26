"""Headless export. No network activity and no changes to private vault notes."""
import argparse
import csv
import io
import json
from pathlib import Path

from obsidian import sync_word, sync_word_table
from vocab import DEFAULT_AUDIO, DEFAULT_DB, Store

CSV_FIELDS = ('word', 'article', 'part_of_speech', 'ipa', 'chinese_meaning', 'meaning_source', 'meaning_reviewed', 'sense', 'source_url', 'audio_kind', 'audio_license', 'attribution', 'note', 'created_at')
DEFAULT_TABLE_PATH = Path.home() / 'Documents' / 'Obsidian Vault' / '德语单词.md'


def save_word_table(store, destination=None, audio_root=DEFAULT_AUDIO):
    destination = destination or store.get_setting('word_table_path') or DEFAULT_TABLE_PATH
    return sync_word_table(store.list(), destination, audio_root)


def csv_export(rows):
    output = io.StringIO(newline='')
    writer = csv.DictWriter(output, fieldnames=CSV_FIELDS, lineterminator='\n')
    writer.writeheader()
    for row in rows:
        values = {}
        for key in CSV_FIELDS:
            value = row.get(key)
            if isinstance(value, str) and value.lstrip().startswith(('=', '+', '-', '@')):
                value = "'" + value
            values[key] = value
        writer.writerow(values)
    return output.getvalue().encode('utf-8-sig')


def sync_entry(store, row, vault, audio_root=DEFAULT_AUDIO):
    try:
        document = dict(row)
        document['candidates'] = json.loads(row.get('candidates_json') or '[]')
        document['meaning_candidates'] = json.loads(row.get('meaning_candidates_json') or '[]')
        path = sync_word(document, vault, audio_root)
        store.sync_result(row['id'], f'同步成功：{path.name}', success=True)
        return path
    except (OSError, ValueError, RuntimeError) as exc:
        store.sync_result(row['id'], f'同步失败：{exc}')
        raise


def batch_sync(store, vault, audio_root=DEFAULT_AUDIO):
    succeeded, errors = 0, []
    for row in store.list():
        try:
            sync_entry(store, row, vault, audio_root)
            succeeded += 1
        except (OSError, ValueError, RuntimeError) as exc:
            errors.append(f"{row['word']}：{exc}")
    return succeeded, errors


def main():
    parser = argparse.ArgumentParser(description='将本地词库单向同步到现有 Obsidian Vault')
    parser.add_argument('--vault', required=True, help='包含 .obsidian 子目录的 Vault 路径')
    parser.add_argument('--db', default=str(DEFAULT_DB))
    parser.add_argument('--audio-root', default=str(DEFAULT_AUDIO))
    args = parser.parse_args()
    succeeded, errors = batch_sync(Store(args.db), args.vault, args.audio_root)
    print(f'同步成功 {succeeded} 条；失败 {len(errors)} 条。')
    for error in errors:
        print(error)
    return 1 if errors else 0


if __name__ == '__main__':
    raise SystemExit(main())
