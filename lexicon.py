"""Conservative offline extraction from Wiktionary wikitext and local Kaikki JSONL.

This is a template-aware extractor, not a MediaWiki renderer. Unsupported or
ambiguous data stays absent; it never obtains missing information from spelling.
The module performs no network requests.
"""
from __future__ import annotations

import hashlib
import html
import json
from pathlib import Path
import re


_HEADINGS = re.compile(r'^(={2,6})\s*(.*?)\s*\1\s*$', re.MULTILINE)
_GENDERS = {'m': 'der', 'f': 'die', 'n': 'das'}


def _split_arguments(text: str) -> list[str]:
    """Split template arguments without splitting nested templates or links."""
    parts, start, braces, links, i = [], 0, 0, 0, 0
    while i < len(text):
        pair = text[i:i + 2]
        if pair == '{{':
            braces += 1
            i += 2
        elif pair == '}}' and braces:
            braces -= 1
            i += 2
        elif pair == '[[':
            links += 1
            i += 2
        elif pair == ']]' and links:
            links -= 1
            i += 2
        elif text[i] == '|' and not braces and not links:
            parts.append(text[start:i].strip())
            i += 1
            start = i
        else:
            i += 1
    parts.append(text[start:].strip())
    return parts


def _templates(text: str):
    """Yield complete outer templates as (start, end, name, arguments)."""
    depth, start, i = 0, 0, 0
    while i < len(text) - 1:
        pair = text[i:i + 2]
        if pair == '{{':
            if depth == 0:
                start = i
            depth += 1
            i += 2
        elif pair == '}}' and depth:
            depth -= 1
            i += 2
            if not depth:
                args = _split_arguments(text[start + 2:i - 2])
                yield start, i, args[0], args[1:]
        else:
            i += 1


def _without_comments(text: str) -> str:
    return re.sub(r'<!--.*?-->', '', text, flags=re.DOTALL)


def _plain(text: str) -> str:
    text = re.sub(r'<ref\b[^>]*>.*?</ref\s*>|<ref\b[^>]*/\s*>', '', text,
                  flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r'<(?:script|style)\b[^>]*>.*?</(?:script|style)\s*>', '', text,
                  flags=re.IGNORECASE | re.DOTALL)
    chunks, previous = [], 0
    for start, end, name, args in _templates(text):
        chunks.append(text[previous:start])
        # These templates contain lexical text; label/reference/formatting
        # templates do not establish a definition by themselves.
        if name.lower() in {'l', 'link', 'm', 'mention'} and len(args) >= 2:
            chunks.append(_plain(args[2] if len(args) > 2 and '=' not in args[2] else args[1]))
        elif name.lower() in {'nowrap', 'small'} and args:
            chunks.append(_plain(args[0]))
        previous = end
    chunks.append(text[previous:])
    text = ''.join(chunks)
    text = re.sub(r'\[\[(?:[^\]|]*\|)?([^\]]+)\]\]', r'\1', text)
    text = re.sub(r'\[(?:https?://\S+)(?:\s+([^]]+))?\]', lambda m: m[1] or '', text)
    text = re.sub(r'<[^>]*>', '', text)
    text = text.replace("'''", '').replace("''", '')
    text = html.unescape(text)
    return re.sub(r'\s+', ' ', text).strip()


def _german_blocks(wikitext: str, chinese: bool = False):
    text = _without_comments(wikitext)
    headings = [h for h in _HEADINGS.finditer(text) if len(h[1]) == 2]
    for i, heading in enumerate(headings):
        title = heading[2].strip()
        if chinese:
            german = title in {'德語', '德语', 'Deutsch', 'German'}
            german = german or bool(re.fullmatch(r'\{\{\s*-de-\s*\}\}', title, re.I))
            german = german or any(name.lower() in {'langue', '語言', '语言', 'language'} and args and args[0] == 'de'
                                   for _, _, name, args in _templates(title))
        else:
            german = any(name.lower() == 'sprache' and args and args[0] == 'Deutsch'
                         for _, _, name, args in _templates(title))
        if german:
            end = headings[i + 1].start() if i + 1 < len(headings) else len(text)
            yield text[heading.end():end]


def _pos_sections(block: str):
    headings = [h for h in _HEADINGS.finditer(block) if len(h[1]) == 3]
    for i, heading in enumerate(headings):
        end = headings[i + 1].start() if i + 1 < len(headings) else len(block)
        positions = [args[0] for _, _, name, args in _templates(heading[2])
                     if name == 'Wortart' and len(args) >= 2 and args[1] == 'Deutsch']
        if positions:
            yield heading[2], block[heading.end():end], ' / '.join(dict.fromkeys(positions))


def _article(heading: str, body: str, pos: str):
    if 'Substantiv' not in pos.split(' / '):
        return None
    genders = set()
    for _, _, name, _ in _templates(heading):
        if name in _GENDERS:
            genders.add(name)
    for _, _, name, args in _templates(body):
        if name.strip() == 'Deutsch Substantiv Übersicht':
            for arg in args:
                key, sep, value = arg.partition('=')
                if sep and re.fullmatch(r'Genus(?:\s*\d+)?', key.strip()) and value.strip() in _GENDERS:
                    genders.add(value.strip())
    return ' / '.join(_GENDERS[g] for g in ('m', 'f', 'n') if g in genders) or None


def _meanings(body: str) -> list[tuple[str, str]]:
    meanings = []
    active = False
    for line in body.splitlines():
        if re.fullmatch(r'\s*\{\{Bedeutungen\}\}\s*', line):
            active = True
            continue
        if not active:
            continue
        if re.match(r'^\s*\{\{|^\s*={2,}', line):
            break
        match = re.match(r'^\s*:+\s*\[([\d][\da-z., –-]*)\]\s*(.*)', line)
        if match:
            content = _plain(match[2])
            if content and '{{' not in content and '[[' not in content:
                meanings.append((match[1], f'[{match[1]}] {content}'))
    return meanings


def _pronunciations(body: str):
    """Return IPA/audio values with explicit meaning labels, if present."""
    ipa, audio = [], []
    active = False
    for line in body.splitlines():
        if re.fullmatch(r'\s*\{\{Aussprache\}\}\s*', line):
            active = True
            continue
        if active and re.match(r'^\s*(?:\{\{(?!IPA|Lautschrift|Audio|Hörbeispiele)|={2,})', line):
            break
        if not active:
            continue
        for start, _, name, args in _templates(line):
            if name not in {'Lautschrift', 'Audio'} or not args:
                continue
            labels = re.findall(r'\[([\d][\da-z., –-]*)\]', line[:start])
            label = labels[-1] if labels else None
            value = args[0].strip()
            if value and '{{' not in value and '\n' not in value:
                (ipa if name == 'Lautschrift' else audio).append((label, value))
    return ipa, audio


def _label_matches(label: str, number: str) -> bool:
    if label == number:
        return True
    if number in re.split(r'\s*,\s*', label):
        return True
    interval = re.fullmatch(r'(\d+)\s*[-–]\s*(\d+)', label)
    return bool(interval and number.isdigit() and int(interval[1]) <= int(number) <= int(interval[2]))


def _values_for(entries, number):
    explicit = [value for label, value in entries if label and _label_matches(label, number)]
    return list(dict.fromkeys(explicit or [value for label, value in entries if label is None]))


def _sense_id(*parts) -> str:
    return hashlib.sha256(json.dumps(parts, ensure_ascii=False, separators=(',', ':')).encode('utf-8')).hexdigest()[:24]


def parse_german(word: str, wikitext: str, source_url: str = '') -> list[dict]:
    """Extract separate German POS/meaning/pronunciation candidates.

    A single shared pronunciation may cover multiple meanings. Several unlabelled
    pronunciations across several meanings are ambiguous and are left unset.
    No article is inferred for an inflected form or from a compound's spelling.
    """
    result = []
    for block_index, block in enumerate(_german_blocks(wikitext)):
        for section_index, (heading, body, pos) in enumerate(_pos_sections(block)):
            meanings = _meanings(body)
            if not meanings:
                # Inflection-only entries often have grammatical features instead
                # of definitions; retain the entry without inventing a gloss.
                meanings = [('', '')]
            ipa_entries, audio_entries = _pronunciations(body)
            article = _article(heading, body, pos)
            for number, sense in meanings:
                ipas = _values_for(ipa_entries, number)
                audios = _values_for(audio_entries, number)
                explicit = any(label and _label_matches(label, number) for label, _ in ipa_entries)
                if len({value for _, value in ipa_entries}) > 1 and not any(
                    label and _label_matches(label, number) for label, _ in audio_entries
                ):
                    audios = []
                if len(ipas) > 1 and len(meanings) > 1 and not explicit:
                    ipas, audios = [], []
                if len(ipas) > 1:
                    # Audio without a one-to-one pronunciation mapping cannot be
                    # safely associated with an alternative IPA candidate.
                    audios = []
                for ipa in ipas or [None]:
                    result.append({
                        'sense_id': _sense_id('de', word, block_index, section_index, sense, pos, article, ipa),
                        'sense': sense, 'part_of_speech': pos, 'article': article,
                        'ipa': ipa, 'audio_files': audios.copy(), 'source_url': source_url,
                        'confidence': 'dictionary', 'source': 'Wiktionary (de)',
                    })
    return result


_CHINESE_POS = {'名詞', '名词', '動詞', '动词', '形容詞', '形容词', '副詞', '副词',
                '代詞', '代词', '介詞', '介词', '連詞', '连词', '感嘆詞', '感叹词',
                '數詞', '数词', '冠詞', '冠词', '短語', '短语', '專有名詞', '专有名词',
                '分詞', '分词', '詞形變化', '词形变化', '縮寫', '缩写', '詞組', '词组'}


def parse_chinese(word: str, wikitext: str, source_url: str = '') -> list[dict]:
    """Extract plain numbered Chinese glosses from a German language block.

    Unknown templates are removed rather than treated as translations. Examples,
    translations, redirects, and broken template markup are not glosses.
    """
    del word  # The queried headword is context, not a source of translations.
    result = []
    for block in _german_blocks(wikitext, chinese=True):
        active = False
        for line in block.splitlines():
            heading = _HEADINGS.fullmatch(line)
            if heading:
                title = heading[2].strip()
                active = title in _CHINESE_POS
                continue
            if not active:
                continue
            match = re.match(r'^\s*#+(?![:*#])\s*(.+)', line)
            if not match:
                continue
            content = match[1]
            # Refuse partial markup so it is never displayed as a definition.
            if content.count('{{') != content.count('}}') or content.count('[[') != content.count(']]'):
                continue
            text = _plain(content)
            if not text or '{{' in text or '[[' in text or not re.search(r'[\u3400-\u9fff]', text):
                continue
            row = {'text': text, 'source': 'Wiktionary (zh)', 'source_url': source_url}
            if row not in result:
                result.append(row)
    return result


def read_kaikki(word: str, path: str | Path) -> list[dict]:
    """Stream a user-provided JSONL file; never download or load a full corpus.

    Malformed lines and unrelated words/languages are skipped. License versions
    are not inferred: upstream license metadata is retained when supplied.
    """
    result = []
    pos_names = {'noun': 'Substantiv', 'verb': 'Verb', 'adj': 'Adjektiv', 'adv': 'Adverb',
                 'name': 'Eigenname', 'pron': 'Pronomen', 'prep': 'Präposition'}
    with Path(path).open(encoding='utf-8-sig') as handle:
        for line_index, line in enumerate(handle):
            try:
                item = json.loads(line)
            except (ValueError, TypeError):
                continue
            if not isinstance(item, dict) or item.get('lang_code') != 'de' or item.get('word') != word:
                continue
            pos = pos_names.get(item.get('pos'), item.get('pos'))
            senses = item.get('senses') if isinstance(item.get('senses'), list) else []
            senses = [s for s in senses if isinstance(s, dict)] or [{}]
            sounds = item.get('sounds') if isinstance(item.get('sounds'), list) else []
            for sense_index, sense in enumerate(senses):
                tags = [tag for tag in item.get('tags', []) + sense.get('tags', []) if isinstance(tag, str)]
                genders = {'masculine': 'der', 'feminine': 'die', 'neuter': 'das'}
                article = ' / '.join(value for key, value in genders.items() if key in tags) if pos == 'Substantiv' else None
                glosses = sense.get('glosses', [])
                gloss = '; '.join(g for g in glosses if isinstance(g, str)) if isinstance(glosses, list) else ''
                ipas = list(dict.fromkeys(s['ipa'] for s in sounds if isinstance(s, dict) and isinstance(s.get('ipa'), str)))
                ipa = ipas[0] if len(ipas) == 1 else None
                result.append({
                    'sense_id': _sense_id('kaikki', word, line_index, sense_index, gloss, pos, article, ipa),
                    'sense': gloss, 'part_of_speech': pos, 'article': article or None,
                    'ipa': ipa, 'audio_files': [], 'source_url': item.get('source_url', ''),
                    'source': 'Kaikki / Wiktextract (local JSONL)', 'confidence': 'dictionary',
                    'license': item.get('license') or 'See the license and attribution of the supplied Kaikki/Wiktionary dataset',
                })
    return result
