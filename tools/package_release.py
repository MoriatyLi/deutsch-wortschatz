"""Add release documentation and dependency notices, then create a portable ZIP."""
from __future__ import annotations

import hashlib
from importlib import metadata
import json
from pathlib import Path
import shutil
import sqlite3
import sys
import zipfile


def main():
    root = Path(__file__).resolve().parents[1]
    release = root / 'dist' / 'DeutschWortschatz'
    if not (release / 'DeutschWortschatz.exe').is_file():
        raise FileNotFoundError('Build the executable first')
    shutil.copy2(root / 'docs' / 'DESKTOP_GUIDE.md', release / '使用说明.md')
    shutil.copy2(root / 'docs' / 'THIRD_PARTY_NOTICES.md', release / 'THIRD_PARTY_NOTICES.md')
    seed = release / '_internal' / 'app_resources' / 'user_data' / 'vocab.db'
    with sqlite3.connect(seed.resolve().as_uri() + '?mode=ro', uri=True) as connection:
        seed_words = connection.execute('SELECT count(*) FROM words').fetchone()[0]
    (release / '请先阅读.txt').write_text(
        'Deutsch Wortschatz · 德语词库\n\n'
        '完整解压后双击 DeutschWortschatz.exe。无需安装 Python。\n'
        '请保留旁边的 _internal 文件夹。\n'
        '个人词库和录音保存在 %LOCALAPPDATA%\\DeutschWortschatz。\n'
        f'内置德语中文离线词典；本构建的种子库含 {seed_words} 条词条。\n'
        'Windows 10/11 x64；桌面窗口需要本机 Microsoft Edge WebView2。\n'
        '详见 使用说明.md 和 THIRD_PARTY_NOTICES.md。\n', encoding='utf-8-sig')

    notices = release / 'THIRD_PARTY_LICENSES'
    notices.mkdir(exist_ok=True)
    packages = []
    for distribution in sorted(metadata.distributions(), key=lambda item: item.metadata['Name'].lower()):
        name, version = distribution.metadata['Name'], distribution.version
        packages.append({'name': name, 'version': version})
        destination = notices / (name + '-' + version)
        destination.mkdir(exist_ok=True)
        text = distribution.read_text('METADATA') or distribution.read_text('PKG-INFO') or ''
        (destination / 'METADATA.txt').write_text(text, encoding='utf-8')
        for file in distribution.files or []:
            basename = file.name.lower()
            if any(label in basename for label in ('license', 'copying', 'notice')):
                source = Path(distribution.locate_file(file))
                if source.is_file() and source.stat().st_size < 2_000_000:
                    tag = hashlib.sha256(str(file).encode()).hexdigest()[:12]
                    target = destination / (tag + '-' + source.name)
                    shutil.copy2(source, target)
    python_license = Path(sys.base_prefix) / 'LICENSE.txt'
    if python_license.is_file():
        shutil.copy2(python_license, notices / 'CPython-LICENSE.txt')

    (release / 'build-info.json').write_text(json.dumps({
        'version': '1.0.0-rc2-desktop', 'platform': 'Windows x64',
        'python': sys.version, 'dictionary_word_forms': 168289,
        'seed_word_count': seed_words,
        'dictionary_senses': 267409, 'build_environment_packages': packages,
    }, indent=2, ensure_ascii=False), encoding='utf-8')
    archive = root / 'dist' / 'DeutschWortschatz-Windows-x64.zip'
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as output:
        for file in sorted(release.rglob('*')):
            if file.is_file():
                output.write(file, file.relative_to(release.parent))
    with zipfile.ZipFile(archive) as check:
        invalid = check.testzip()
        if invalid:
            raise ValueError(f'Archive CRC check failed: {invalid}')
    with archive.open('rb') as handle:
        digest = hashlib.file_digest(handle, 'sha256').hexdigest()
    archive.with_suffix('.zip.sha256').write_text(f'{digest}  {archive.name}\n', encoding='ascii')
    print(json.dumps({'archive': str(archive), 'bytes': archive.stat().st_size,
                      'sha256': digest}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
