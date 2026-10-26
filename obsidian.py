"""Conservative one-way export into an existing local Obsidian vault.

Only notes bearing this exporter's exact source marker are replaced. The bytes
after DEUTSCH_VOCAB_END belong to the user and are retained verbatim. New notes
and audio use atomic no-clobber publication (rename on Windows, hard link on
POSIX), which cannot replace existing files.
Managed updates use an atomic replacement after checking the original bytes.
This is a local desktop writer, not protection against an adversarial process
that changes filesystem paths between the safety check and the filesystem call.
"""

from collections.abc import Mapping
import hashlib
import html
import json
import os
from pathlib import Path, PureWindowsPath
import re
import stat
import tempfile
import time
import unicodedata
from urllib.parse import urlsplit


MAX_AUDIO_BYTES = 15 * 1024 * 1024
END_MARKER = b'<!-- DEUTSCH_VOCAB_END -->'
TABLE_BEGIN = b'<!-- DEUTSCH_VOCAB_TABLE_BEGIN -->'
TABLE_END = b'<!-- DEUTSCH_VOCAB_TABLE_END -->'
_RESERVED = {'CON', 'PRN', 'AUX', 'NUL', 'CONIN$', 'CONOUT$'} | {
    f'{prefix}{number}' for prefix in ('COM', 'LPT') for number in range(1, 10)
}
_FIELDS = (
    'id', 'word', 'ipa', 'article', 'part_of_speech', 'chinese_meaning',
    'meaning_source', 'meaning_reviewed', 'source_url', 'sense_id', 'sense',
    'candidates', 'meaning_candidates', 'confidence', 'audio_kind', 'audio_license', 'attribution',
    'audio_url', 'note', 'created_at',
)


def _json(value):
    # Escaping angle brackets keeps metadata from impersonating ownership HTML.
    return json.dumps(value, ensure_ascii=False, default=str).replace('<', '\\u003c').replace('>', '\\u003e')


def _slug(value):
    value = unicodedata.normalize('NFC', value)
    value = re.sub(r'[<>:"/\\|?*\[\]#^\x00-\x1f\x7f]', '_', value)
    value = value.strip(' .')[:60].rstrip(' .') or 'Wort'
    if value.split('.')[0].upper() in _RESERVED:
        value = '_' + value
    return value


def _parts(value):
    value = os.fspath(value)
    if not value or PureWindowsPath(value).drive or value.startswith(('/', '\\')):
        raise ValueError('Destination must be a relative directory inside the vault')
    parts = value.replace('\\', '/').split('/')
    if any(p in ('', '.', '..') or _slug(p) != p or p.casefold() == '.obsidian' for p in parts):
        raise ValueError('Unsafe destination directory')
    return parts


def _check(path, root):
    if not path.resolve().is_relative_to(root):
        raise ValueError('Path escapes the selected vault or audio directory')
    current = root
    for part in path.relative_to(root).parts:
        current = current / part
        if current.is_symlink() or (hasattr(current, 'is_junction') and current.is_junction()):
            raise ValueError('Symlink and junction destinations are not supported')
    if root.is_symlink() or (hasattr(root, 'is_junction') and root.is_junction()):
        raise ValueError('Symlink and junction roots are not supported')


def _directory(root, parts):
    current = root
    for part in parts:
        current = current / part
        _check(current, root)
        try:
            current.mkdir()
        except FileExistsError:
            pass
        _check(current, root)
        if not current.is_dir():
            raise ValueError('Destination component is not a directory')
    return current


def _existing(path):
    """Find a case-insensitive collision even on case-sensitive filesystems."""
    return next((p for p in path.parent.iterdir() if p.name.casefold() == path.name.casefold()), None)


def _read_regular(path, root):
    _check(path, root)
    if not stat.S_ISREG(path.stat().st_mode):
        raise ValueError('Expected a regular local file')
    return path.read_bytes()


def _publish(path, data, root, previous=None):
    _check(path, root)
    descriptor, temporary = tempfile.mkstemp(prefix='.deutsch-', suffix='.tmp', dir=path.parent)
    temp_path = Path(temporary)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        _check(path, root)
        if previous is None:
            # Windows rename fails for an existing name. POSIX rename replaces
            # existing files, so use an exclusive hard-link publication there.
            if os.name == 'nt':
                os.rename(temp_path, path)
            else:
                os.link(temp_path, path)
        else:
            for attempt in range(5):
                try:
                    if _read_regular(path, root) != previous:
                        raise RuntimeError('The note changed during export; retry to preserve personal edits')
                    os.replace(temp_path, path)
                    break
                except PermissionError as exc:
                    # Windows indexers/editors can briefly hold a note. Recheck
                    # the original bytes before every retry to retain edits.
                    if getattr(exc, 'winerror', None) not in (5, 32, 33) or attempt == 4:
                        raise
                    time.sleep(0.05 * 2 ** attempt)
    finally:
        temp_path.unlink(missing_ok=True)


def _managed_tail(data, owner):
    try:
        frontmatter = re.match(rb'\A---\r?\n(.*?)\r?\n---\r?\n', data, re.DOTALL)
        if frontmatter is None:
            return None
        header, rest = frontmatter[1], data[frontmatter.end():]
        expected = ('source_entry: ' + _json(owner)).encode('utf-8')
        if expected not in header.splitlines():
            return None
        begin = f'<!-- DEUTSCH_VOCAB_BEGIN source={owner} -->'.encode()
        if not rest.startswith((begin + b'\n', begin + b'\r\n')):
            return None
        match = re.search(rb'(?m)^<!-- DEUTSCH_VOCAB_END -->', rest)
        if match is None:
            return None
        return rest[match.end():]
    except (ValueError, UnicodeError):
        return None


def _audio_bytes(filename, audio_root):
    if audio_root is None:
        raise ValueError('audio_root is required for a local audio file')
    filename = os.fspath(filename)
    if not filename or any(c in filename for c in '/\\:') or filename in ('.', '..'):
        raise ValueError('audio_file must be a filename inside audio_root')
    if (len(filename) > 200 or filename.endswith((' ', '.')) or
            re.search(r'[<>:"/\\|?*\x00-\x1f\x7f]', filename) or
            filename.split('.')[0].upper() in _RESERVED):
        raise ValueError('Unsafe audio filename')
    root = Path(audio_root).absolute()
    if not root.is_dir():
        raise ValueError('audio_root must exist')
    _check(root, root)
    root = root.resolve()
    source = root / filename
    _check(source, root)
    if not source.is_file() or not stat.S_ISREG(source.stat().st_mode):
        raise ValueError('Audio must be an existing regular file')
    if not 0 < source.stat().st_size <= MAX_AUDIO_BYTES:
        raise ValueError('Audio must be nonempty and no larger than 15 MiB')
    with source.open('rb') as stream:
        data = stream.read(MAX_AUDIO_BYTES + 1)
    if not 0 < len(data) <= MAX_AUDIO_BYTES:
        raise ValueError('Audio changed size or exceeds 15 MiB')
    extension = source.suffix.lower()
    valid = ((extension in ('.ogg', '.oga', '.opus') and data.startswith(b'OggS')) or
             (extension == '.flac' and data.startswith(b'fLaC')) or
             (extension == '.wav' and data.startswith(b'RIFF') and data[8:12] == b'WAVE') or
             (extension == '.mp3' and (data.startswith(b'ID3') or
              len(data) > 1 and data[0] == 255 and data[1] & 0xe0 == 0xe0)))
    if not valid:
        raise ValueError('Unsupported audio format or invalid audio signature')
    return data, extension


def _copy_audio(data, extension, directory, root):
    digest = hashlib.sha256(data).hexdigest()[:20]
    for index in range(10000):
        suffix = f'-{index}' if index else ''
        target = directory / f'audio-{digest}{suffix}{extension}'
        existing = _existing(target)
        if existing is not None:
            _check(existing, root)
            if existing.is_file() and _read_regular(existing, root) == data:
                return existing
            continue
        try:
            _publish(target, data, root)
            return target
        except FileExistsError:
            continue
    raise FileExistsError('Could not find an unused audio filename')


def _render(word, owner, audio_link):
    lines = ['---', 'source_entry: ' + _json(owner)]
    lines.extend(f'{key}: {_json(word[key])}' for key in _FIELDS if key in word)
    if audio_link:
        lines.append('audio_file: ' + _json(audio_link))
    lines.extend(['---', f'<!-- DEUTSCH_VOCAB_BEGIN source={owner} -->',
                  '# ' + html.escape(str(word['word'])), ''])
    for key, label in (('ipa', 'IPA'), ('article', 'Artikel'),
                       ('part_of_speech', 'Wortart'), ('chinese_meaning', '中文'),
                       ('sense', 'Bedeutung'), ('meaning_source', 'Meaning source'),
                       ('source_url', 'Source'), ('audio_kind', 'Audio kind'),
                       ('audio_license', 'Audio license'), ('attribution', 'Attribution'),
                       ('audio_url', 'Audio source'), ('note', 'Note')):
        if word.get(key) not in (None, ''):
            lines.append(f'**{label}:** {html.escape(str(word[key]))}')
    if audio_link:
        lines.extend(['', f'![[{audio_link}]]'])
    lines.extend(['', END_MARKER.decode()])
    return '\n'.join(lines).encode('utf-8')


def sync_word(word: Mapping, vault: str | Path, audio_root: str | Path | None = None,
              notes_dir='Deutsch/Vokabeln', audio_dir='Deutsch/Audio') -> Path:
    """Export one word; raise ValueError/OSError instead of silently losing data.

    ``word`` accepts SQLite-row-shaped mappings; all metadata is optional except
    a nonempty ``word``. Ownership combines normalized word text and database id.
    Audio is signature checked (Ogg, MP3, WAV, FLAC), bounded to 15 MiB and copied
    locally. Signature checking is not a complete media-decoder validation.
    """
    word = dict(word)
    text = word.get('word')
    if not isinstance(text, str) or not text.strip():
        raise ValueError('A nonempty word is required')
    notes_parts, audio_parts = _parts(notes_dir), _parts(audio_dir)
    root = Path(vault).absolute()
    if not root.is_dir():
        raise ValueError('Select an existing Obsidian vault')
    _check(root, root)
    root = root.resolve()
    _check(root / '.obsidian', root)
    if not (root / '.obsidian').is_dir():
        raise ValueError('The selected vault must contain an .obsidian directory')
    normalized = unicodedata.normalize('NFC', text.strip()).casefold()
    identity = _json([word.get('id'), normalized])
    owner = 'sqlite-word-' + hashlib.sha256(identity.encode()).hexdigest()
    audio = _audio_bytes(word['audio_file'], audio_root) if word.get('audio_file') else None
    directory = _directory(root, notes_parts)
    link = None
    if audio:
        audio_target = _copy_audio(*audio, _directory(root, audio_parts), root)
        link = audio_target.relative_to(root).as_posix()
    generated = _render(word, owner, link)
    # A stable suffix distinguishes different SQLite entries and reserved names.
    stem = _slug(text) + '--' + owner[-16:]
    for index in range(10000):
        suffix = f'-{index}' if index else ''
        target = directory / f'{stem}{suffix}.md'
        existing = _existing(target)
        if existing is not None:
            _check(existing, root)
            if not existing.is_file():
                continue
            original = _read_regular(existing, root)
            tail = _managed_tail(original, owner)
            if tail is None:
                continue
            updated = generated + tail
            if updated != original:
                _publish(existing, updated, root, previous=original)
            return existing
        try:
            _publish(target, generated + '\n\n## 我的笔记\n\n'.encode('utf-8'), root)
            return target
        except FileExistsError:
            continue
    raise FileExistsError('Could not find an unused note filename')


def _cell(value):
    if value is None or value == '':
        return '—'
    return (html.escape(str(value)).replace('|', '&#124;').replace('[', '&#91;')
            .replace(']', '&#93;').replace('\r\n', '\n').replace('\r', '\n')
            .replace('\n', '<br>'))


def _source_link(url, label):
    if not isinstance(url, str):
        return ''
    try:
        parsed = urlsplit(url)
    except ValueError:
        return ''
    if parsed.scheme not in ('https', 'http') or not parsed.netloc or any(c.isspace() or c in '<>"' for c in url):
        return ''
    return f'[{label}](<{html.escape(url)}>)'


def sync_word_table(rows, destination: str | Path, audio_root=None) -> Path:
    """Refresh only the managed table block inside one chosen Obsidian note."""
    path = Path(destination).expanduser().absolute()
    if path.suffix.lower() != '.md' or _slug(path.stem) != path.stem:
        raise ValueError('请选择有效的 Markdown 文件完整路径（以 .md 结尾）。')
    root = next((parent for parent in path.parents if (parent / '.obsidian').is_dir()), None)
    if root is None:
        raise ValueError('保存位置必须在已有 Obsidian Vault 中（包含 .obsidian 文件夹）。')
    _check(root, root)
    root = root.resolve()
    _check(path, root)
    relative = path.parent.relative_to(root)
    if relative.parts:
        _directory(root, _parts(relative.as_posix()))
    existing = _existing(path)
    if existing is not None:
        path = existing
        original = _read_regular(path, root)
    else:
        original = None
    previous = original or b''
    begins, ends = previous.count(TABLE_BEGIN), previous.count(TABLE_END)
    if begins or ends:
        begin = re.search(rb'(?m)^' + re.escape(TABLE_BEGIN) + rb'\r?$', previous)
        end = re.search(rb'(?m)^' + re.escape(TABLE_END) + rb'\r?$', previous)
        if begins != 1 or ends != 1 or begin is None or end is None or end.start() <= begin.end():
            raise ValueError('单词表的自动更新标记缺失或重复；未修改笔记，请先恢复标记。')
        prefix, suffix = previous[:begin.start()], previous[end.start() + len(TABLE_END):]
    else:
        prefix = previous + (b'\n\n' if previous else b'')
        suffix = b'\n'

    rows = list(rows)
    lines = [TABLE_BEGIN.decode(), '## 德语单词表', '',
             f'共 {len(rows)} 个词条。此区域由德语词库更新；个人笔记请写在区域外。', '',
             '| 德语 | 冠词 | 词性 | 中文释义 | IPA | 发音 | 校对 | 备注 | 来源 |',
             '| --- | --- | --- | --- | --- | --- | --- | --- | --- |']
    credits = []
    for row in rows:
        sound = '暂无录音'
        if row.get('audio_file'):
            try:
                audio = _audio_bytes(row['audio_file'], audio_root)
                audio_target = _copy_audio(*audio, _directory(root, _parts('Deutsch/Audio')), root)
                sound = f'![[{audio_target.relative_to(root).as_posix()}]]'
            except (OSError, ValueError):
                sound = '本地录音不可用'
            audio_source = _source_link(row.get('audio_url'), '录音来源')
            credits.append('- **' + _cell(row['word']) + '** · ' + ' · '.join(
                value for value in (audio_source, _cell(row.get('audio_license')), _cell(row.get('attribution'))) if value))
        source = ' · '.join(value for value in (_cell(row.get('meaning_source')),
                            _source_link(row.get('source_url'), '词典原文')) if value)
        cells = [_cell(row.get(key)) for key in ('word', 'article', 'part_of_speech', 'chinese_meaning', 'ipa')]
        cells += [sound, '已复核' if row.get('meaning_reviewed') else '待复核', _cell(row.get('note')), source]
        lines.append('| ' + ' | '.join(cells) + ' |')
    if credits:
        lines += ['', '### 录音来源与许可', '', *credits]
    lines += ['', TABLE_END.decode()]
    updated = prefix + '\n'.join(lines).encode('utf-8') + suffix
    if updated != original:
        _publish(path, updated, root, previous=original)
    return path
