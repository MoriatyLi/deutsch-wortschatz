"""Bounded public API clients; every enrichment is optional and attributable."""
from __future__ import annotations

import asyncio
import hashlib
import html
import json
import logging
import os
import re
import tempfile
import time
from http.client import HTTPException
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from lexicon import parse_chinese, parse_german, read_kaikki
from offline_dictionary import lookup as offline_lookup

LOG = logging.getLogger(__name__)
USER_AGENT = 'DeutschWortschatz/1.0 (local personal vocabulary tool; low-rate requests)'
MAX_AUDIO_BYTES = 15 * 1024 * 1024
ALLOWED_HOSTS = {'de.wiktionary.org', 'zh.wiktionary.org', 'commons.wikimedia.org', 'api.mymemory.translated.net', 'upload.wikimedia.org'}
AUDIO_EXTENSIONS = {'.ogg', '.oga', '.mp3', '.wav', '.flac', '.opus'}
LOOKUP_ERRORS = (OSError, ValueError, KeyError, TypeError, HTTPException)


def validate_url(url, hosts):
    if not isinstance(url, str):
        raise ValueError('URL must be a string')
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or parsed.hostname not in hosts or parsed.username or parsed.password or parsed.port not in (None, 443):
        raise ValueError('拒绝不受信任的下载地址。')


def validate_audio_url(url):
    validate_url(url, {'upload.wikimedia.org'})


class SafeRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # A download redirect must remain on the exact permitted file host.
        hosts = {'upload.wikimedia.org'} if urlsplit(req.full_url).hostname == 'upload.wikimedia.org' else ALLOWED_HOSTS - {'upload.wikimedia.org'}
        validate_url(newurl, hosts)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def audio_magic(data):
    return data.startswith((b'OggS', b'RIFF', b'fLaC', b'ID3')) or (len(data) > 1 and data[0] == 255 and data[1] & 224 == 224)


class HttpClient:
    def __init__(self, min_interval=1.0, timeout=12):
        self.min_interval, self.timeout = min_interval, timeout
        self.last_request = {}
        self.opener = build_opener(SafeRedirects())

    def open(self, url):
        validate_url(url, ALLOWED_HOSTS)
        host = urlsplit(url).hostname
        gap = self.min_interval - (time.monotonic() - self.last_request.get(host, 0))
        if gap > 0:
            time.sleep(gap)
        self.last_request[host] = time.monotonic()
        return self.opener.open(Request(url, headers={'User-Agent': USER_AGENT}), timeout=self.timeout)

    def json(self, url, params=None):
        if params:
            url += '?' + urlencode(params)
        with self.open(url) as response:
            payload = response.read(4 * 1024 * 1024 + 1)
        if len(payload) > 4 * 1024 * 1024:
            raise ValueError('API 响应超过 4 MiB。')
        result = json.loads(payload)
        if not isinstance(result, dict):
            raise ValueError('API 未返回有效对象。')
        if result.get('error'):
            raise ValueError('词典 API 返回错误。')
        return result

    def page(self, language, word):
        result = self.json(f'https://{language}.wiktionary.org/w/api.php', {
            'action': 'query', 'format': 'json', 'formatversion': 2, 'prop': 'revisions',
            'rvprop': 'content', 'rvslots': 'main', 'titles': word, 'redirects': 1,
        })
        query = result.get('query')
        if not isinstance(query, dict):
            raise ValueError('词典响应结构无效。')
        pages = query.get('pages', [])
        if not isinstance(pages, list):
            raise ValueError('词典响应结构无效。')
        for page in pages:
            if not isinstance(page, dict):
                raise ValueError('词典页面结构无效。')
            if 'missing' not in page and page.get('revisions'):
                revisions = page['revisions']
                if not isinstance(revisions, list) or not isinstance(revisions[0], dict):
                    raise ValueError('词典修订结构无效。')
                slots = revisions[0].get('slots')
                if not isinstance(slots, dict) or not isinstance(slots.get('main'), dict):
                    raise ValueError('词典修订缺少正文。')
                content = slots['main'].get('content')
                if not isinstance(content, str):
                    raise ValueError('词典正文无效。')
                return content
        return ''

    def download(self, url, target):
        validate_audio_url(url)
        target = Path(target)
        temporary = None
        started = time.monotonic()
        try:
            with self.open(url) as response:
                mime = response.headers.get('Content-Type', '').split(';')[0].strip().lower()
                if mime not in {'audio/ogg', 'application/ogg', 'audio/mpeg', 'audio/mp3', 'audio/wav', 'audio/x-wav', 'audio/flac', 'audio/x-flac', 'audio/opus', 'application/octet-stream'}:
                    raise ValueError('下载结果不是受支持的音频。')
                if int(response.headers.get('Content-Length', '0')) > MAX_AUDIO_BYTES:
                    raise ValueError('音频超过 15 MiB 限制。')
                target.parent.mkdir(parents=True, exist_ok=True)
                with tempfile.NamedTemporaryFile(dir=target.parent, delete=False, suffix='.part') as out:
                    temporary = Path(out.name)
                    total = 0
                    first = True
                    while True:
                        chunk = response.read(65536)
                        if not chunk:
                            break
                        if first and not audio_magic(chunk):
                            raise ValueError('音频文件头无效。')
                        first = False
                        total += len(chunk)
                        if total > MAX_AUDIO_BYTES or time.monotonic() - started > 40:
                            raise ValueError('音频下载超出大小或时间限制。')
                        out.write(chunk)
                    if total == 0:
                        raise ValueError('音频为空。')
                    out.flush()
                    os.fsync(out.fileno())
            os.replace(temporary, target)
            temporary = None
        finally:
            if temporary:
                temporary.unlink(missing_ok=True)
        return target


def plain(text):
    return html.unescape(re.sub(r'<[^>]*>', '', text)).strip() if isinstance(text, str) else ''


def metadata_text(meta, key):
    value = meta.get(key)
    return plain(value.get('value')) if isinstance(value, dict) else ''


def lookup_failure(service, exc):
    detail = str(exc)
    LOG.warning('%s unavailable: %s: %s', service, type(exc).__name__, detail)
    if 'timed out' in detail.lower() or 'timeout' in detail.lower() or isinstance(exc, TimeoutError):
        return f'{service}连接超时；请检查当前网络或代理后重新查询。'
    if isinstance(exc, (OSError, HTTPException)):
        return f'{service}连接失败；请检查当前网络或代理后重新查询。'
    return f'{service}返回内容无法解析；可以稍后重新查询或手动补充。'


def valid_translation(payload, word):
    if not isinstance(payload, dict) or str(payload.get('responseStatus')) != '200':
        return None
    data = payload.get('responseData')
    text = data.get('translatedText') if isinstance(data, dict) else None
    if not isinstance(text, str):
        return None
    text = plain(text)
    if not text or len(text) > 2000 or text.casefold() == word.casefold():
        return None
    if any(error in text.upper() for error in ('MYMEMORY WARNING', 'QUOTA', 'QUERY LENGTH', 'INVALID LANGUAGE', 'PLEASE SELECT', 'TOO MANY REQUESTS', 'NO QUERY SPECIFIED')):
        return None
    # A Chinese provider response without any CJK characters is not a Chinese gloss.
    if not re.search(r'[\u3400-\u9fff]', text):
        return None
    return text


class Providers:
    def __init__(self, audio_root, store=None, http=None):
        self.audio_root = Path(audio_root)
        self.store, self.http = store, http or HttpClient()

    def lookup(self, word, online=True, tts=False, offline_path=None, force=False):
        offline_stamp = None
        if offline_path:
            path = Path(offline_path)
            if path.is_file():
                offline_stamp = (str(path.resolve()), path.stat().st_mtime_ns)
        cache_key = 'lookup-v3:' + json.dumps([word, online, tts, offline_stamp], ensure_ascii=False)
        if self.store and not force:
            cached = self.store.cache_get(cache_key)
            if cached:
                return cached['fields'], cached['warnings']
        fields = {'candidates': [], 'meaning_candidates': [], 'meaning_reviewed': False}
        warnings = []
        dictionary_word = word
        if offline_path:
            try:
                if Path(offline_path).suffix.lower() in {'.db', '.sqlite', '.sqlite3'}:
                    local = offline_lookup(word, offline_path)
                    fields['candidates'] = local['candidates']
                    fields['meaning_candidates'] = local['meaning_candidates']
                    dictionary_word = local['dictionary_word']
                else:
                    fields['candidates'] = read_kaikki(word, offline_path)
                    fields['meaning_candidates'] = [{'text': c['sense'], 'source': c['source'], 'source_url': c['source_url'], 'sense_id': c['sense_id']} for c in fields['candidates'] if re.search(r'[\u3400-\u9fff]', c.get('sense') or '')]
            except LOOKUP_ERRORS as exc:
                warnings.append('本地 Kaikki 文件读取失败，请检查文件路径和 JSONL 格式。')
                LOG.info('Offline dictionary unavailable: %s', type(exc).__name__)
        if online:
            if not fields['candidates']:
                try:
                    url = 'https://de.wiktionary.org/wiki/' + quote(word, safe='')
                    fields['candidates'] = parse_german(word, self.http.page('de', word), url)
                    if not fields['candidates'] and word.isalpha() and word[0].islower():
                        capitalized = word[0].upper() + word[1:]
                        capital_url = 'https://de.wiktionary.org/wiki/' + quote(capitalized, safe='')
                        alternate = parse_german(capitalized, self.http.page('de', capitalized), capital_url)
                        if alternate:
                            fields['candidates'] = alternate
                            dictionary_word = capitalized
                            warnings.append(f'已按词典词形 {capitalized} 检索；原输入 {word} 保留。')
                except LOOKUP_ERRORS as exc:
                    warnings.append(lookup_failure('德语词典', exc))
            if not fields['meaning_candidates']:
                try:
                    url = 'https://zh.wiktionary.org/wiki/' + quote(dictionary_word, safe='')
                    meanings = parse_chinese(dictionary_word, self.http.page('zh', dictionary_word), url)
                    fields['meaning_candidates'] = meanings
                except LOOKUP_ERRORS as exc:
                    warnings.append(lookup_failure('中文词典', exc))
            if not fields['meaning_candidates']:
                try:
                    result = self.http.json('https://api.mymemory.translated.net/get', {'q': dictionary_word, 'langpair': 'de|zh-CN'})
                    translated = valid_translation(result, dictionary_word)
                    if translated:
                        fields['meaning_candidates'] = [{'text': translated, 'source': 'MyMemory（机器翻译，待复核）', 'source_url': 'https://mymemory.translated.net/'}]
                    else:
                        warnings.append('机器翻译未返回有效中文释义，可能配额已用尽；请手动补充。')
                except LOOKUP_ERRORS as exc:
                    warnings.append(lookup_failure('机器翻译', exc))
        if fields['meaning_candidates']:
            fields['chinese_meaning'] = '；'.join(m['text'] for m in fields['meaning_candidates'])
            fields['meaning_source'] = fields['meaning_candidates'][0]['source']
        else:
            warnings.append('中文释义待补充。')
        candidates = fields['candidates']
        if candidates:
            fields['dictionary_word'] = dictionary_word
        if len(candidates) == 1:
            candidate = candidates[0]
            for key in ('sense_id', 'sense', 'ipa', 'part_of_speech', 'article', 'source_url', 'confidence'):
                fields[key] = candidate.get(key)
            if online:
                audio, messages = self.audio(word, candidate, tts=tts)
                fields.update(audio)
                warnings.extend(messages)
        elif len(candidates) > 1:
            # Shared grammatical/pronunciation facts are safe without selecting
            # a definition. Each value must be explicitly supported by all senses.
            for key in ('part_of_speech', 'article', 'ipa', 'source_url', 'confidence'):
                value = candidates[0].get(key)
                if value and all(c.get(key) == value for c in candidates):
                    fields[key] = value
            common_audio = set(candidates[0].get('audio_files', []))
            for candidate in candidates[1:]:
                common_audio.intersection_update(candidate.get('audio_files', []))
            if online and common_audio and fields.get('ipa'):
                shared = {'audio_files': sorted(common_audio), 'ipa': fields['ipa']}
                audio, messages = self.audio(word, shared, tts=False)
                fields.update(audio)
                warnings.extend(messages)
            warnings.append('词典有多个义项，请在候选中选择；中文释义与德语义项尚未自动对应。')
        else:
            warnings.append('未找到可解析的德语义项；词性、冠词和 IPA 待补充。')
            if online and tts:
                audio, messages = self.audio(word, {}, tts=True)
                fields.update(audio)
                warnings.extend(messages)
        if not online and self.store and candidates:
            # Keep an already downloaded recording only when the same word and
            # pronunciation remain supported by the offline result.
            old = self.store.find(dictionary_word)
            if old and old.get('audio_file') and old.get('ipa') and old['ipa'] == fields.get('ipa') and old.get('part_of_speech') == fields.get('part_of_speech'):
                target = (self.audio_root / old['audio_file']).resolve()
                if target.is_relative_to(self.audio_root.resolve()) and target.is_file():
                    fields.update({key: old.get(key) for key in ('audio_file', 'audio_kind', 'audio_url', 'audio_license', 'attribution')})
        if not online and not fields.get('audio_file'):
            warnings.append('本地暂无此词的录音；离线模式不会请求在线录音或 Edge TTS。')
        has_data = bool(candidates or fields['meaning_candidates'])
        fields['lookup_status'] = ('offline' if not online else 'failed' if not has_data else
                                   'complete' if candidates and fields.get('chinese_meaning') and fields.get('audio_file') else 'partial')
        fields['lookup_checked_at'] = datetime.now(timezone.utc).isoformat(timespec='seconds')
        fields['lookup_warnings'] = list(warnings)
        if self.store and has_data:
            self.store.cache_set(cache_key, {'fields': fields, 'warnings': warnings})
        return fields, warnings

    def audio(self, word, candidate, tts=False):
        warnings = []
        for name in candidate.get('audio_files', []):
            try:
                result = self.http.json('https://commons.wikimedia.org/w/api.php', {
                    'action': 'query', 'format': 'json', 'formatversion': 2, 'prop': 'imageinfo',
                    'iiprop': 'url|extmetadata|mime|size', 'titles': 'File:' + name.removeprefix('File:'),
                })
                query = result.get('query')
                if not isinstance(query, dict) or not isinstance(query.get('pages'), list):
                    raise ValueError('录音元数据结构无效。')
                pages = query['pages']
                info = None
                for page in pages:
                    if not isinstance(page, dict):
                        raise ValueError('Invalid Commons page metadata')
                    images = page.get('imageinfo')
                    if not images:
                        continue
                    if not isinstance(images, list) or not isinstance(images[0], dict):
                        raise ValueError('Invalid Commons image metadata')
                    info = images[0]
                    break
                if not info:
                    continue
                url = info['url']
                validate_audio_url(url)
                ext = Path(urlsplit(url).path).suffix.lower()
                if ext not in AUDIO_EXTENSIONS or int(info.get('size', 0)) > MAX_AUDIO_BYTES:
                    raise ValueError('不受支持或过大的音频。')
                meta = info.get('extmetadata', {})
                if not isinstance(meta, dict):
                    raise ValueError('Invalid Commons license metadata')
                license_text = metadata_text(meta, 'LicenseShortName')
                if not license_text:
                    warnings.append('该录音缺少许可元数据，未下载。')
                    continue
                artist = metadata_text(meta, 'Artist')
                credit = metadata_text(meta, 'Credit')
                description = info.get('descriptionurl') or 'https://commons.wikimedia.org/wiki/File:' + quote(name)
                filename = hashlib.sha256(url.encode()).hexdigest() + ext
                target = self.audio_root / filename
                if not target.is_file() or target.stat().st_size == 0:
                    self.http.download(url, target)
                return {'audio_file': filename, 'audio_kind': 'human', 'audio_url': url, 'audio_license': license_text, 'attribution': '\n'.join(x for x in (artist, credit, description, metadata_text(meta, 'LicenseUrl')) if isinstance(x, str) and x)}, warnings
            except LOOKUP_ERRORS as exc:
                warnings.append('Commons 录音获取失败或安全校验未通过。')
                LOG.info('Audio unavailable: %s', type(exc).__name__)
        if tts:
            try:
                import edge_tts
                self.audio_root.mkdir(parents=True, exist_ok=True)
                filename = 'tts-' + hashlib.sha256((word + ':de-DE-KatjaNeural').encode()).hexdigest() + '.mp3'
                target = self.audio_root / filename
                if not target.is_file():
                    async def synthesize():
                        temporary = target.with_suffix('.part')
                        try:
                            await asyncio.wait_for(edge_tts.Communicate(word, 'de-DE-KatjaNeural').save(str(temporary)), 35)
                            if not temporary.is_file() or not 0 < temporary.stat().st_size <= MAX_AUDIO_BYTES or not audio_magic(temporary.read_bytes()[:16]):
                                raise ValueError('TTS 未生成有效音频。')
                            os.replace(temporary, target)
                        finally:
                            temporary.unlink(missing_ok=True)
                    asyncio.run(synthesize())
                warnings.append('使用 TTS 合成发音；同形异音可能不对应所选义项，请核对。')
                return {'audio_file': filename, 'audio_kind': 'tts', 'audio_url': None, 'audio_license': 'Microsoft Edge TTS 服务条款', 'attribution': 'Microsoft Edge TTS · de-DE-KatjaNeural'}, warnings
            except Exception as exc:
                warnings.append('TTS 不可用（需安装可选依赖且联网）；未生成录音。')
                LOG.info('TTS unavailable: %s', type(exc).__name__)
        warnings.append('暂无真人录音。')
        return {}, warnings
