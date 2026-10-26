"""Explicit online smoke check; never runs with the offline unittest suite."""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from providers import Providers
from vocab import BASE_DIR


def main():
    parser = argparse.ArgumentParser(description='手动检查公共词典/翻译/录音 API，不更改主词库')
    parser.add_argument('words', nargs='*', default=['Wasser', 'sprechen'])
    parser.add_argument('--output', default=str(BASE_DIR / 'data' / 'online-smoke.json'))
    args = parser.parse_args()
    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    provider = Providers(target.parent / 'smoke-audio')
    report = {'checked_at': datetime.now(timezone.utc).isoformat(), 'words': []}
    for word in args.words:
        fields, warnings = provider.lookup(word, force=True)
        item = {'word': word, 'fields': fields, 'warnings': warnings}
        report['words'].append(item)
        print(json.dumps({'word': word, 'candidates': len(fields['candidates']), 'ipa': fields.get('ipa'), 'article': fields.get('article'), 'chinese_meaning': fields.get('chinese_meaning'), 'audio_kind': fields.get('audio_kind'), 'warnings': warnings}, ensure_ascii=False), flush=True)
        target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return 0 if all(item['fields'].get('candidates') and item['fields'].get('ipa') and item['fields'].get('chinese_meaning') and item['fields'].get('audio_file') for item in report['words']) else 1


if __name__ == '__main__':
    raise SystemExit(main())
