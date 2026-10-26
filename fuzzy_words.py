"""Read-only local dictionary suggestions; never changes the user's input."""
from bisect import bisect_left
from contextlib import closing
from difflib import get_close_matches
from functools import lru_cache
import json
from pathlib import Path
import sqlite3
import unicodedata


def _normalize(word):
    return (unicodedata.normalize('NFC',word).casefold()
            .replace('ä','ae').replace('ö','oe').replace('ü','ue'))


@lru_cache(maxsize=2)
def _vocabulary(path, stamp, size):
    with closing(sqlite3.connect(Path(path).as_uri()+'?mode=ro',uri=True)) as db:
        rows=db.execute('SELECT DISTINCT word FROM entries').fetchall()
    mapping={}
    for (word,) in rows:
        if isinstance(word,str) and word.strip():
            mapping.setdefault(_normalize(word),[]).append(word)
    keys=sorted(mapping)
    lengths={}
    for key in keys:
        lengths.setdefault(len(key),[]).append(key)
    return mapping, keys, lengths


def suggest(query, dictionary, limit=10):
    query=unicodedata.normalize('NFC',str(query)).strip()
    if not query or len(query)>200 or not any(char.isalpha() for char in query):
        return []
    if any(unicodedata.category(char).startswith('C') for char in query):
        return []
    limit=max(1,min(int(limit),20))
    path=Path(dictionary).expanduser().resolve()
    if not path.is_file():
        raise ValueError('本地词典索引不存在，请先配置离线词典。')
    stat=path.stat()
    mapping, keys, lengths=_vocabulary(str(path),stat.st_mtime_ns,stat.st_size)
    normalized=_normalize(query)
    candidates=[]
    seen=set()

    def add(key,kind):
        for word in sorted(mapping.get(key,()),key=lambda item:(item!=query,not item[0].isupper(),item)):
            if word not in seen:
                seen.add(word)
                candidates.append((word,kind))

    add(normalized,'精确匹配')
    start=bisect_left(keys,normalized)
    prefixes=[]
    for key in keys[start:]:
        if not key.startswith(normalized):
            break
        prefixes.append(key)
    for key in sorted(prefixes,key=lambda item:(len(item),item)):
        add(key,'前缀匹配')
        if len(candidates)>=limit:
            break
    if len(candidates)<limit and len(normalized)>=3:
        pool=[key for length in range(max(1,len(normalized)-2),len(normalized)+3)
              for key in lengths.get(length,()) if key!=normalized]
        for key in get_close_matches(normalized,pool,n=limit,cutoff=.66):
            add(key,'相近拼写')
            if len(candidates)>=limit:
                break
    result=[]
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as db:
        for word,kind in candidates[:limit]:
            payloads=db.execute('SELECT payload FROM entries WHERE word=? LIMIT 3',(word,)).fetchall()
            entries=[]
            for (payload,) in payloads:
                try:
                    entry=json.loads(payload)
                    if isinstance(entry,dict):
                        entries.append(entry)
                except (ValueError,TypeError):
                    continue
            meanings=list(dict.fromkeys(str(entry['chinese_meaning']) for entry in entries if entry.get('chinese_meaning')))
            articles=list(dict.fromkeys(str(entry['article']) for entry in entries if entry.get('article')))
            result.append({'word':word,'meaning':'；'.join(meanings)[:140],
                           'article':' / '.join(articles),'match':kind})
    return result
