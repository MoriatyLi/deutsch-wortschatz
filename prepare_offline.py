"""Import an already downloaded dictionary and activate local-only lookup."""
import argparse
import json
from pathlib import Path

from offline_dictionary import build_index
from vocab import BASE_DIR, DEFAULT_DB, Store


def activate(source, index, store, language='zh'):
    report = build_index(source, index, language)
    store.set_setting('offline_path', str(Path(index).resolve()))
    store.set_setting('online', '0')
    store.set_setting('tts', '0')
    return report


def main():
    parser = argparse.ArgumentParser(description='将本地 JSONL 建成离线词典索引，并关闭在线查词/TTS')
    parser.add_argument('--source', required=True, nargs='+')
    parser.add_argument('--index', default=str(BASE_DIR / 'data' / 'dictionaries' / 'de-zh.db'))
    parser.add_argument('--db', default=str(DEFAULT_DB))
    parser.add_argument('--language', choices=['zh', 'de', 'en'], default='zh', help='源词典的释义语言')
    args = parser.parse_args()
    report = activate(args.source, args.index, Store(args.db), args.language)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
